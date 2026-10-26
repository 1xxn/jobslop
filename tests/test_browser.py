"""Ende-zu-Ende-Tests mit echtem Chromium gegen lokale Testformulare."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from conftest import ScriptedInteractor, add_job
from jobpilot.apply.engine import ApplyEngine, BrowserSession
from jobpilot.apply.executor import Executor, Files
from jobpilot.apply.extract import extract_state
from jobpilot.apply.planner import FieldAction, HeuristicPlanner
from jobpilot.db import Answer, Application, session_scope

pytestmark = pytest.mark.browser


async def _page(settings):
    session = BrowserSession(settings, headless=True)
    await session.__aenter__()
    return session, await session.new_page()


async def test_extract_finds_all_widgets(settings, site):
    session, page = await _page(settings)
    try:
        await page.goto(f"{site.base_url}/greenhouse_like.html")
        state = await extract_state(page)
        by_label = {f["label"].split(" |")[0]: f for f in state.fields}
        assert by_label["First Name *"]["kind"] == "text" and by_label["First Name *"]["required"]
        assert by_label["Email *"]["input_type"] == "email"
        resume = next(f for f in state.fields if f["kind"] == "file")
        assert resume["label"].startswith("Resume/CV *") and resume["required"]
        visa = next(f for f in state.fields if f["kind"] == "radio")
        assert visa["label"].startswith("Do you require visa sponsorship")
        assert [o["label"] for o in visa["options"]] == ["Yes", "No"]
        land = next(f for f in state.fields if f["kind"] == "select")
        assert [o["label"] for o in land["options"]] == ["Bitte wählen", "Deutschland", "Österreich"]
        combo = next(f for f in state.fields if f["kind"] == "combobox")
        assert combo["label"] == "How did you hear about us? *"
        assert any(b["text"] == "Submit application" for b in state.buttons)
        assert not state.captcha_visible
    finally:
        await session.__aexit__(None, None, None)


async def test_extract_shadow_dom_and_iframe(settings, site):
    session, page = await _page(settings)
    try:
        await page.goto(f"{site.base_url}/apply.html")
        await page.wait_for_timeout(500)
        state = await extract_state(page)
        labels = [f["label"] for f in state.fields]
        assert "Vorname*" in labels and "Nachname*" in labels
        assert "Telefonnummer" in labels  # Feld im Shadow DOM
        assert all(f["frame"] == 1 for f in state.fields)  # alles im iframe
        assert state.frame_for(state.fields[0]["id"]) is not None
    finally:
        await session.__aexit__(None, None, None)


async def test_executor_handles_custom_widgets(settings, site, profile):
    session, page = await _page(settings)
    try:
        await page.goto(f"{site.base_url}/greenhouse_like.html")
        state = await extract_state(page)
        fid = {f["label"].split(" |")[0]: f["id"] for f in state.fields}
        visa = next(f for f in state.fields if f["kind"] == "radio")
        resume = next(f for f in state.fields if f["kind"] == "file")
        combo = next(f for f in state.fields if f["kind"] == "combobox")

        def a(field_id, action, value=""):
            return FieldAction(
                field_id=field_id, action=action, value=value, confidence="high", source="profile", reason="t"
            )

        results = await Executor(page, Files(cv=profile.cv_path(settings.home))).run(
            state,
            [
                a(fid["First Name *"], "fill", "Max"),
                a(fid["Land *"], "select", "Deutschland"),
                a(visa["id"], "select", "No"),
                a(resume["id"], "upload", "@cv"),
                a(combo["id"], "select", "company website"),
                a(fid["I agree to the privacy policy *"], "check"),
            ],
        )
        assert all(r.ok for r in results), [r.detail for r in results if not r.ok]
        assert await page.input_value("#first_name") == "Max"
        assert await page.input_value("#country") == "Deutschland"
        assert await page.is_checked("#visa-no")
        assert await page.input_value("#hear-value") == "Company website"
        assert await page.is_checked("#privacy")
        assert (
            await page.evaluate("document.getElementById('resume').files[0].name")
            == "Max_Mustermann_CV_SRE.pdf"
        )
    finally:
        await session.__aexit__(None, None, None)


async def test_engine_single_page_with_questions(settings, site, profile, config):
    job_id = add_job(
        settings, f"{site.base_url}/greenhouse_like.html", "Acme Cloud", "Site Reliability Engineer"
    )
    interactor = ScriptedInteractor({"visa": "No", "salary": "70000", "hear about": "Company website"})
    before = len(site.submissions)
    async with BrowserSession(settings, headless=True) as browser:
        engine = ApplyEngine(
            settings=settings,
            config=config,
            profile=profile,
            planner=HeuristicPlanner(profile),
            interactor=interactor,
            browser=browser,
            mode="auto",
        )
        outcome = await engine.apply(job_id)
    assert outcome.status == "submitted", outcome.message
    sub = site.submissions[before]
    assert (
        sub["first_name"] == "Max" and sub["last_name"] == "Mustermann" and sub["email"] == "max.mustermann@example.com"
    )
    assert sub["visa"] == "no" and sub["salary"] == "70000" and sub["hear"] == "Company website"
    assert sub["country"] == "Deutschland" and sub["privacy"] is True
    assert sub["resume"] == "Max_Mustermann_CV_SRE.pdf"
    assert sub["linkedin"] == "https://www.linkedin.com/in/max-mustermann-example"
    with session_scope(settings.db_path) as s:
        app = s.get(Application, outcome.application_id)
        assert app.status == "submitted" and "Thank you" in app.confirmation
        stored = {a.question: a.answer for a in s.execute(select(Answer)).scalars()}
    assert any("visa" in q.lower() for q in stored)  # Antworten landen in der Antwortbank
    # Zweiter Versuch derselben Stelle wird blockiert
    async with BrowserSession(settings, headless=True) as browser:
        engine = ApplyEngine(
            settings=settings,
            config=config,
            profile=profile,
            planner=HeuristicPlanner(profile),
            interactor=interactor,
            browser=browser,
            mode="auto",
        )
        again = await engine.apply(job_id)
    assert again.status == "skipped" and "Schon beworben" in again.message


async def test_engine_multistep_iframe_new_tab(settings, site, profile, config):
    job_id = add_job(settings, f"{site.base_url}/posting.html")
    before = len(site.submissions)
    async with BrowserSession(settings, headless=True) as browser:
        engine = ApplyEngine(
            settings=settings,
            config=config,
            profile=profile,
            planner=HeuristicPlanner(profile),
            interactor=ScriptedInteractor({}),
            browser=browser,
            mode="auto",
        )
        outcome = await engine.apply(job_id)
    assert outcome.status == "submitted", outcome.message
    sub = site.submissions[before]
    assert sub == {
        "vorname": "Max",
        "nachname": "Mustermann",
        "mail": "max.mustermann@example.com",
        "tel": "+49 30 12345678",
        "cv": "Max_Mustermann_CV_SRE.pdf",
        "datenschutz": True,
        "talentpool": False,
    }


async def test_review_mode_rejects_without_submitting(settings, site, profile, config):
    job_id = add_job(settings, f"{site.base_url}/posting.html", "Review GmbH", "Platform Engineer")
    before = len(site.submissions)
    interactor = ScriptedInteractor({}, decision="reject")
    async with BrowserSession(settings, headless=True) as browser:
        engine = ApplyEngine(
            settings=settings,
            config=config,
            profile=profile,
            planner=HeuristicPlanner(profile),
            interactor=interactor,
            browser=browser,
            mode="review",
        )
        outcome = await engine.apply(job_id)
    assert outcome.status == "needs_review"
    assert interactor.confirmed == 1
    assert len(site.submissions) == before


async def test_dry_run_and_missing_answers_park(settings, site, profile, config):
    job_id = add_job(settings, f"{site.base_url}/greenhouse_like.html", "Dry Run AG", "SRE")
    async with BrowserSession(settings, headless=True) as browser:
        engine = ApplyEngine(
            settings=settings,
            config=config,
            profile=profile,
            planner=HeuristicPlanner(profile),
            interactor=ScriptedInteractor({}),
            browser=browser,
            mode="dry-run",
        )
        outcome = await engine.apply(job_id)
    assert outcome.status == "needs_input"
    with session_scope(settings.db_path) as s:
        app = s.get(Application, outcome.application_id)
        labels = " ".join(q["label"] for q in app.open_questions)
    assert "visa" in labels.lower() and "salary" in labels.lower()

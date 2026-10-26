"""Ende-zu-Ende-Tests mit echtem Chromium gegen lokale Testformulare."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from conftest import ScriptedInteractor, add_job
from jobslop.apply.engine import ApplyEngine, BrowserSession
from jobslop.apply.executor import Executor, Files
from jobslop.apply.extract import extract_state
from jobslop.apply.planner import FieldAction, HeuristicPlanner
from jobslop.apply.prepare import dismiss_cookie_banners, reveal_lazy_content, try_autofill
from jobslop.db import Answer, Application, ApplicationEvent, session_scope

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
            await page.evaluate("document.getElementById('resume').files[0].name") == "Max_Mustermann_CV.pdf"
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
        sub["first_name"] == "Max"
        and sub["last_name"] == "Mustermann"
        and sub["email"] == "max.mustermann@example.com"
    )
    assert sub["visa"] == "no" and sub["salary"] == "70000" and sub["hear"] == "Company website"
    assert sub["country"] == "Deutschland" and sub["privacy"] is True
    assert sub["resume"] == "Max_Mustermann_CV.pdf"
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
        "cv": "Max_Mustermann_CV.pdf",
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


def _engine(settings, config, profile, browser, interactor=None, mode="auto"):
    return ApplyEngine(
        settings=settings,
        config=config,
        profile=profile,
        planner=HeuristicPlanner(profile),
        interactor=interactor or ScriptedInteractor({}),
        browser=browser,
        mode=mode,
    )


async def test_cookie_overlay_in_shadow_dom_and_hidden_form_section(settings, site):
    session, page = await _page(settings)
    try:
        await page.goto(f"{site.base_url}/toggle_form.html")
        state = await extract_state(page)
        # Upload-Feld im zugeklappten Formular gehört noch nicht zur Seite (Zalando-Fall)
        assert not [f for f in state.fields if f["kind"] == "file"]
        assert next(b for b in state.buttons if b["text"] == "Only essential")["cookie"]
        assert not next(b for b in state.buttons if b["text"] == "Apply").get("cookie")
        assert await dismiss_cookie_banners(page) == ["Only essential"]
        assert await page.evaluate("window.cookieChoice") == "essential"
        assert await dismiss_cookie_banners(page) == []  # nichts mehr da
    finally:
        await session.__aexit__(None, None, None)


async def test_engine_toggle_form_behind_cookie_overlay(settings, site, profile, config):
    job_id = add_job(settings, f"{site.base_url}/toggle_form.html", "Toggle AG", "Software Engineer")
    before = len(site.submissions)
    async with BrowserSession(settings, headless=True) as browser:
        outcome = await _engine(settings, config, profile, browser).apply(job_id)
    assert outcome.status == "submitted", outcome.message
    assert site.submissions[before] == {
        "firstName": "Max",
        "lastName": "Mustermann",
        "email": "max.mustermann@example.com",
        "resume": "Max_Mustermann_CV.pdf",
        "consent": True,
        "cookie": "essential",
    }


async def test_lazy_iframe_below_the_fold_is_revealed(settings, site):
    session, page = await _page(settings)
    try:
        await page.goto(f"{site.base_url}/lazy_embed.html")
        await reveal_lazy_content(page)
        state = await extract_state(page)
        first = next(f for f in state.fields if f["label"].startswith("First Name"))
        assert first["frame"] > 0
    finally:
        await session.__aexit__(None, None, None)


async def test_autofill_from_resume_then_corrects_wrong_values(settings, site, profile, config):
    job_id = add_job(
        settings, f"{site.base_url}/autofill.html?mode=resume", "Autofill AG", "Platform Engineer"
    )
    before = len(site.submissions)
    async with BrowserSession(settings, headless=True) as browser:
        outcome = await _engine(settings, config, profile, browser).apply(job_id)
    assert outcome.status == "submitted", outcome.message
    sub = site.submissions[before]
    assert sub["autofill"] == "Max_Mustermann_CV.pdf"  # Autofill-Button wurde mit dem Lebenslauf bedient
    assert sub["first"] == "Max" and sub["last"] == "Mustermann"
    assert sub["mail"] == "max.mustermann@example.com"  # falscher Autofill-Wert durch Profilwert ersetzt
    assert sub["cv"] == "Max_Mustermann_CV.pdf" and sub["privacy"] is True
    with session_scope(settings.db_path) as s:
        events = (
            s.execute(select(ApplicationEvent).where(ApplicationEvent.kind == "autofill")).scalars().all()
        )
        assert any("Lebenslauf" in e.message for e in events)


async def test_autofill_that_needs_login_is_skipped(settings, site, profile):
    session, page = await _page(settings)
    try:
        await page.goto(f"{site.base_url}/autofill.html?mode=login")
        state = await extract_state(page)
        note, _ = await try_autofill(page, state, profile.cv_path(settings.home))
        assert "Login" in note
        assert await page.locator("#login-mail").count() == 0  # Login-Dialog wieder geschlossen
    finally:
        await session.__aexit__(None, None, None)


class _StaleTargetPlanner(HeuristicPlanner):
    """Erster Plan zielt auf einen Button, der beim Klicken schon ersetzt ist (wie 'Alle ablehnen' bei Zattoo)."""

    def __init__(self, profile, browser):
        super().__init__(profile)
        self.browser = browser
        self.calls = 0

    async def plan(self, data):
        from jobslop.apply.planner import PagePlan

        self.calls += 1
        if self.calls > 1:
            return await super().plan(data)
        page = self.browser.context.pages[-1]
        bid = next(b["id"] for b in data.state.buttons if b["text"] == "Submit application")
        await page.evaluate(
            """id => { const el = document.querySelector(`[data-jp="${id}"]`);
                       const copy = el.cloneNode(true); copy.removeAttribute('data-jp'); el.replaceWith(copy); }""",
            bid,
        )
        return PagePlan(
            page_kind="application_form",
            actions=[],
            open_questions=[],
            next_step="click_next",
            next_target_id=bid,
            summary="Ziel ist inzwischen ersetzt",
        )


async def test_vanished_button_does_not_fail_application(settings, site, profile, config):
    job_id = add_job(settings, f"{site.base_url}/greenhouse_like.html?stale=1", "Stale GmbH", "SRE")
    interactor = ScriptedInteractor({"visa": "No", "salary": "70000", "hear about": "Company website"})
    async with BrowserSession(settings, headless=True) as browser:
        engine = _engine(settings, config, profile, browser, interactor)
        engine.planner = _StaleTargetPlanner(profile, browser)
        outcome = await engine.apply(job_id)
    assert outcome.status == "submitted", outcome.message


class _LimitPlanner:
    """Simuliert ein erschöpftes Abo-Kontingent beim ersten Planungsschritt."""

    async def plan(self, data):
        from jobslop.llm import LLMLimitReached

        raise LLMLimitReached("You've hit your session limit · resets 5pm")

    def remember(self, question, answer):
        pass


async def test_usage_limit_pauses_and_requeues(settings, site, profile, config):
    from jobslop.apply.engine import run_batch
    from jobslop.db import Job

    first = add_job(settings, f"{site.base_url}/greenhouse_like.html", company="Erste GmbH")
    second = add_job(settings, f"{site.base_url}/greenhouse_like.html?b=2", company="Zweite GmbH")
    async with BrowserSession(settings, headless=True) as browser:
        engine = ApplyEngine(
            settings=settings,
            config=config,
            profile=profile,
            planner=_LimitPlanner(),
            interactor=ScriptedInteractor({}),
            browser=browser,
            mode="auto",
        )
        outcomes = await run_batch(engine, [first, second], max_count=5, min_delay=0)
    assert [o.status for o in outcomes] == ["paused"]  # Lauf stoppt, zweite Stelle wird nicht angefasst
    with session_scope(settings.db_path) as s:
        assert s.get(Job, first).queued is True
        app = s.execute(select(Application).where(Application.job_id == first)).scalars().one()
        assert app.status == "paused" and "limit" in app.confirmation.lower()
        assert not s.execute(select(Application).where(Application.job_id == second)).scalars().all()
    # pausierte Bewerbung blockiert keinen neuen Versuch
    from jobslop.guard import check_job

    with session_scope(settings.db_path) as s:
        assert check_job(s, s.get(Job, first), config.limits).ok

"""Ende-zu-Ende mit echtem Claude Code (Abo) gegen das lokale Testformular. Nur mit JOBPILOT_LIVE=1."""

from __future__ import annotations

import os

import pytest

from conftest import ScriptedInteractor, add_job
from jobpilot.apply.engine import ApplyEngine, BrowserSession
from jobpilot.apply.planner import LLMPlanner
from jobpilot.llm import LLM, check_login

pytestmark = [
    pytest.mark.live,
    pytest.mark.browser,
    pytest.mark.skipif(
        os.environ.get("JOBPILOT_LIVE") != "1", reason="nur mit JOBPILOT_LIVE=1 (nutzt das Abo)"
    ),
]


class _Lenient(ScriptedInteractor):
    """Wie ein Mensch am Terminal: beantwortet jede Rückfrage (Stichwort, sonst erste Option bzw. Platzhalter)."""

    async def ask(self, app_id, title, questions):
        out = {}
        for q in questions:
            self.asked.append(q.question)
            hit = next((v for k, v in self.answers.items() if k in q.question.lower()), None)
            out[q.field_id] = hit or (q.options[0] if q.options else "Nach Absprache")
        return out


async def test_live_greenhouse_like_form(settings, site, profile, config):
    login = check_login(settings)
    assert login.ok, login.message
    cv_txt = settings.home / "cv.txt"
    cv_txt.write_text(profile.to_prompt(), encoding="utf-8")
    llm = LLM(settings)
    planner = LLMPlanner(llm, profile, settings.home, [], cover_letter_auto=False)
    planner.cv_text = cv_txt.read_text(encoding="utf-8")
    planner.cv_file = None
    job_id = add_job(settings, f"{site.base_url}/greenhouse_like.html", company="Live Test GmbH")
    interactor = _Lenient(
        {
            "gehalt": "70000",
            "salary": "70000",
            "kündigung": "3 Monate",
            "notice": "3 months",
            "start": "2027-01-01",
            "eintritt": "2027-01-01",
            "visa": "No",
            "sponsor": "No",
        }
    )
    before = len(site.submissions)
    async with BrowserSession(settings, headless=True) as browser:
        engine = ApplyEngine(
            settings=settings,
            config=config,
            profile=profile,
            planner=planner,
            interactor=interactor,
            browser=browser,
            llm=llm,
            mode="auto",
        )
        outcome = await engine.apply(job_id)
    print(
        "\nOutcome:",
        outcome.status,
        outcome.message,
        "| Claude:",
        llm.usage.as_dict(),
        "| Fragen:",
        interactor.asked,
    )
    assert outcome.status == "submitted", outcome.message
    sub = site.submissions[before]
    assert sub["first_name"] == "Max" and sub["email"] == "max.mustermann@example.com"

"""Rückkanal über das Dashboard (DbInteractor): Freigaben, Rückfragen, Übergaben und ihre Wartezeiten."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sqlalchemy import select

from conftest import add_job
from jobslop.apply.interact import DbInteractor
from jobslop.apply.planner import OpenQuestion
from jobslop.db import Application, Prompt, session_scope, utcnow


@pytest.fixture
def app_id(settings) -> int:
    job_id = add_job(settings, "https://jobs.example/1")
    with session_scope(settings.db_path) as s:
        a = Application(job_id=job_id, status="running", started_at=utcnow())
        s.add(a)
        s.flush()
        return a.id


def _open_prompt(settings) -> Prompt | None:
    with session_scope(settings.db_path) as s:
        return s.execute(select(Prompt).where(Prompt.status == "open")).scalars().first()


def _answer(settings, response: dict[str, Any]) -> None:
    """Wie ein Klick im Dashboard."""
    with session_scope(settings.db_path) as s:
        p = s.execute(select(Prompt).where(Prompt.status == "open")).scalars().one()
        p.status, p.answered_at, p.response = "answered", utcnow(), response


async def _when_open(settings, answer: dict[str, Any] | None) -> None:
    """Beantwortet die nächste Rückfrage – ``None``: schließt sie wie das Dashboard nach einem gestoppten Lauf."""
    for _ in range(200):
        if _open_prompt(settings):
            if answer is None:
                with session_scope(settings.db_path) as s:
                    s.execute(
                        select(Prompt).where(Prompt.status == "open")
                    ).scalars().one().status = "expired"
            else:
                _answer(settings, answer)
            return
        await asyncio.sleep(0.01)
    raise AssertionError("keine Rückfrage angelegt")


async def test_confirm_waits_for_the_dashboard(settings, app_id):
    interactor = DbInteractor(settings.db_path, timeout_s=10, poll_s=0.01)
    decision, _ = await asyncio.gather(
        interactor.confirm(app_id, "Acme – SRE", [{"label": "E-Mail", "value": "a@b.c"}], None),
        _when_open(settings, {"decision": "submit"}),
    )
    assert decision == "submit"


async def test_confirm_without_answer_times_out_and_submits_nothing(settings, app_id):
    interactor = DbInteractor(settings.db_path, timeout_s=0.05, poll_s=0.01)
    assert await interactor.confirm(app_id, "Acme – SRE", [], None) == "timeout"
    with session_scope(settings.db_path) as s:
        assert s.execute(select(Prompt.status)).scalars().one() == "expired"


async def test_last_second_approval_is_not_lost(settings, app_id):
    """Die Wartezeit läuft ab, während du „Absenden“ klickst: deine Antwort gilt, statt still zu verfallen."""

    class StaleRead(DbInteractor):
        stale = True

        def _state(self, prompt_id: int) -> tuple[str, dict[str, Any]]:
            if self.stale:  # die Antwort kam zwischen Lesen und Ablauf
                self.stale = False
                _answer(settings, {"decision": "submit"})
                return "open", {}
            return super()._state(prompt_id)

    interactor = StaleRead(settings.db_path, timeout_s=0, poll_s=0.01)
    assert await interactor.confirm(app_id, "Acme – SRE", [], None) == "submit"
    with session_scope(settings.db_path) as s:
        assert s.execute(select(Prompt.status)).scalars().one() == "answered"


async def test_handoff_continues_once_the_page_is_ready(settings, app_id):
    """CAPTCHA gelöst oder Login erledigt: der Lauf geht von selbst weiter, ohne Klick im Dashboard."""
    interactor = DbInteractor(settings.db_path, timeout_s=10, poll_s=0.01)
    calls = 0

    async def check() -> bool:
        nonlocal calls
        calls += 1
        return calls >= 3

    assert await interactor.handoff(app_id, "Acme – SRE", "Bitte CAPTCHA lösen", check) is True
    with session_scope(settings.db_path) as s:
        p = s.execute(select(Prompt)).scalars().one()
        assert p.status == "answered" and p.response == {"auto": True}


async def test_handoff_abort_and_closed_prompt(settings, app_id):
    interactor = DbInteractor(settings.db_path, timeout_s=10, poll_s=0.01)
    ok, _ = await asyncio.gather(
        interactor.handoff(app_id, "Acme – SRE", "Bitte einloggen"),
        _when_open(settings, {"abort": True}),
    )
    assert ok is False
    # Lauf gestoppt: das Dashboard räumt die Rückfrage ab – der Lauf wartet nicht die volle Zeit
    ok, _ = await asyncio.wait_for(
        asyncio.gather(
            interactor.handoff(app_id, "Acme – SRE", "Bitte einloggen"), _when_open(settings, None)
        ),
        timeout=5,
    )
    assert ok is False


async def test_questions_need_every_answer(settings, app_id):
    interactor = DbInteractor(settings.db_path, timeout_s=10, poll_s=0.01)
    questions = [
        OpenQuestion(field_id="0-1", question="Gehaltswunsch?", why="Pflichtfeld", options=[]),
        OpenQuestion(field_id="0-2", question="Eintritt?", why="Pflichtfeld", options=[]),
    ]
    answers, _ = await asyncio.gather(
        interactor.ask(app_id, "Acme – SRE", questions),
        _when_open(settings, {"answers": {"0-1": "70000", "0-2": "sofort"}}),
    )
    assert answers == {"0-1": "70000", "0-2": "sofort"}
    partial, _ = await asyncio.gather(
        interactor.ask(app_id, "Acme – SRE", questions),
        _when_open(settings, {"answers": {"0-1": "70000", "0-2": " "}}),
    )
    assert partial is None
    skipped, _ = await asyncio.gather(
        interactor.ask(app_id, "Acme – SRE", questions), _when_open(settings, {"skip": True})
    )
    assert skipped is None

"""Dashboard-Routen und LLM-Planer (mit gefälschtem Claude-Client)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from jobpilot.apply.extract import PageState
from jobpilot.apply.planner import JobContext, LLMPlanner, PagePlan, PlanInput
from jobpilot.db import Answer, Application, Job, Prompt, session_scope
from jobpilot.llm import Usage
from jobpilot.runtime import Runtime
from jobpilot.seeds import import_seeds
from jobpilot.web.app import create_app


def _client(settings, config, profile) -> TestClient:
    import_seeds(settings.db_path)
    return TestClient(create_app(Runtime(settings=settings, config=config, profile=profile)))


def test_dashboard_pages_and_actions(settings, config, profile):
    client = _client(settings, config, profile)
    for path in (
        "/",
        "/jobs",
        "/jobs?cat=SRE&where=B&level=noS",
        "/jobs/1",
        "/applications",
        "/crawls",
        "/answers",
        "/exclusions",
    ):
        r = client.get(path)
        assert r.status_code == 200, path
    assert "Zalando" in client.get("/jobs").text

    client.post("/jobs/3/queue", data={"on": 1}, follow_redirects=False)
    with session_scope(settings.db_path) as s:
        assert s.get(Job, 3).queued
    client.post("/exclude", data={"kind": "company", "value": "Zalando"}, follow_redirects=False)
    with session_scope(settings.db_path) as s:
        assert not s.get(Job, 3).queued
    client.post("/jobs/4/mark", data={"status": "applied"}, follow_redirects=False)
    with session_scope(settings.db_path) as s:
        assert s.get(Job, 4).applications[-1].status == "manual"
    client.post(
        "/answers", data={"question": "Kündigungsfrist?", "answer": "3 Monate"}, follow_redirects=False
    )
    with session_scope(settings.db_path) as s:
        assert s.execute(select(Answer)).scalars().one().answer == "3 Monate"


def test_prompt_roundtrip(settings, config, profile):
    client = _client(settings, config, profile)
    with session_scope(settings.db_path) as s:
        app = Application(job_id=1, status="running")
        s.add(app)
        s.flush()
        p = Prompt(
            application_id=app.id,
            kind="questions",
            payload={
                "title": "Sii",
                "questions": [{"field_id": "0-7", "question": "Gehalt?", "why": "fehlt", "options": []}],
            },
        )
        c = Prompt(
            application_id=app.id, kind="confirm", payload={"title": "Sii", "rows": [], "screenshot": ""}
        )
        s.add_all([p, c])
        s.flush()
        pid, cid = p.id, c.id
    assert "Gehalt?" in client.get("/").text
    assert client.get("/api/prompts").json()["open"][0]["kind"] == "questions"
    client.post(f"/prompts/{pid}", data={"q_0-7": "70000"}, follow_redirects=False)
    client.post(f"/prompts/{cid}", data={"decision": "submit"}, follow_redirects=False)
    with session_scope(settings.db_path) as s:
        assert s.get(Prompt, pid).response == {"answers": {"0-7": "70000"}}
        assert s.get(Prompt, cid).response == {"decision": "submit"}


class _FakeLLM:
    def __init__(self):
        self.calls = []
        self.usage = Usage()

    async def parse(self, schema, *, system, content, model=None, max_tokens=4096, cache_system=True):
        self.calls.append({"schema": schema, "system": system, "content": content})
        return PagePlan(
            page_kind="application_form",
            actions=[],
            open_questions=[],
            next_step="click_submit",
            next_target_id="0-9",
            summary="ok",
        )


async def test_llm_planner_prompt(settings, profile):
    fake = _FakeLLM()
    planner = LLMPlanner(
        fake, profile, settings.home, [("Kündigungsfrist", "3 Monate")], cover_letter_auto=True
    )
    planner.remember("Wie hast du von uns erfahren?", "Karriereseite")
    state = PageState(
        url="https://x/apply",
        title="Apply",
        fields=[
            {"id": "0-1", "kind": "text", "label": "First Name *", "required": True, "value": "", "frame": 0}
        ],
        buttons=[{"id": "0-9", "text": "Submit", "kind": "submit"}],
        errors=["Bitte Feld ausfüllen"],
    )
    job = JobContext(
        id=1,
        company="Sii",
        title="SRE GCP",
        location="Berlin",
        url="https://x",
        description="GCP SRE",
        language="de",
    )
    plan = await planner.plan(PlanInput(job=job, state=state, step=1))
    assert plan.next_target_id == "0-9"
    call = fake.calls[0]
    assert call["schema"] is PagePlan
    assert "Max" in call["system"] and "UNBEKANNT" in call["system"]  # TODO-Felder als unbekannt markiert
    assert "Kündigungsfrist" in call["system"] and "Karriereseite" in call["system"]
    assert call["content"][0]["type"] == "document"  # Lebenslauf als PDF-Block, gecacht
    assert call["content"][0]["cache_control"] == {"type": "ephemeral"}
    text = call["content"][-1]["text"]
    assert "First Name *" in text and "Bitte Feld ausfüllen" in text and "SRE GCP" in text

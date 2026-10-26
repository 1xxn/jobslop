from __future__ import annotations

import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from jobpilot.apply.planner import OpenQuestion
from jobpilot.config import SearchConfig, Settings
from jobpilot.db import Job, get_engine, session_scope
from jobpilot.profile import Profile

SITE = Path(__file__).parent / "fixtures" / "site"
EXAMPLE_PROFILE = Path(__file__).parents[1] / "src" / "jobpilot" / "examples" / "profile.yaml"


class _Site:
    def __init__(self) -> None:
        self.submissions: list[dict[str, Any]] = []
        self.base_url = ""


@pytest.fixture(scope="session")
def site():
    state = _Site()

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(SITE), **kw)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            state.submissions.append(json.loads(self.rfile.read(length) or b"{}"))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.base_url = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield state
    server.shutdown()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    s = Settings(home=tmp_path / "home", headless=True, vision="never", max_steps_per_application=12)
    s.ensure_dirs()
    get_engine(s.db_path)
    return s


@pytest.fixture
def config() -> SearchConfig:
    return SearchConfig.load(Path("/nonexistent"))  # Standardkonfiguration


@pytest.fixture
def profile(settings: Settings) -> Profile:
    p = Profile.load(EXAMPLE_PROFILE)
    cv = settings.home / "Max_Mustermann_CV_SRE.pdf"
    cv.write_bytes(b"%PDF-1.4\n% Test-Lebenslauf\n")
    p.documents.cv = str(cv)
    p.documents.cover_letter = "none"
    return p


def add_job(
    settings: Settings, url: str, company: str = "Beispiel GmbH", title: str = "DevOps Engineer"
) -> int:
    from jobpilot.classify import fingerprint, match_key

    with session_scope(settings.db_path) as s:
        job = Job(
            fingerprint=fingerprint("test", url),
            match_key=match_key(company, title),
            source="test",
            company=company,
            title=title,
            url=url,
            location="Berlin",
            where="B",
            category="DevOps",
        )
        s.add(job)
        s.flush()
        return job.id


class ScriptedInteractor:
    """Beantwortet Rückfragen anhand von Stichworten, gibt Absenden frei, bestätigt Übergaben."""

    def __init__(self, answers: dict[str, str], decision: str = "submit") -> None:
        self.answers = answers
        self.decision = decision
        self.asked: list[str] = []
        self.confirmed = 0

    def info(self, message: str) -> None:
        pass

    async def ask(self, app_id: int, title: str, questions: list[OpenQuestion]) -> dict[str, str] | None:
        out = {}
        for q in questions:
            self.asked.append(q.question)
            hit = next((v for k, v in self.answers.items() if k.lower() in q.question.lower()), None)
            if hit is None:
                return None
            out[q.field_id] = hit
        return out

    async def confirm(self, app_id, title, rows, screenshot) -> str:
        self.confirmed += 1
        return self.decision

    async def handoff(self, app_id, title, message, check=None) -> bool:
        return True

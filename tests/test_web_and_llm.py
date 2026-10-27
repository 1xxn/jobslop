"""Dashboard-API, Autopilot-Zeitplan, Benachrichtigungen und LLM-Planer (mit gefälschtem Claude-Client)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select

from jobslop.apply.engine import ApplyEngine
from jobslop.apply.extract import PageState
from jobslop.apply.planner import JobContext, LLMPlanner, PagePlan, PlanInput
from jobslop.autopilot import next_run, record
from jobslop.config import DemoModeError
from jobslop.crawl.pipeline import run_crawl
from jobslop.db import Answer, Application, Job, Prompt, session_scope
from jobslop.importer import import_jobs
from jobslop.jobpage import parse_html
from jobslop.llm import DYNAMIC_BOUNDARY, Usage
from jobslop.notify import notify
from jobslop.runtime import Runtime
from jobslop.web.app import create_app

FIXTURES = Path(__file__).parent / "fixtures"


def _client(settings, config, profile) -> TestClient:
    import_jobs(settings.db_path, FIXTURES / "jobs_import.json", config)
    app = create_app(Runtime(settings=settings, config=config, profile=profile))
    return TestClient(app, headers={"X-Jobslop": "1"})


def test_api_rejects_foreign_sites(settings, config, profile):
    client = _client(settings, config, profile)
    assert client.post("/api/crawl", headers={"X-Jobslop": ""}).status_code == 403  # CSRF
    assert client.get("/api/status", headers={"Host": "evil.example"}).status_code == 403  # DNS-Rebinding
    assert client.get("/api/status").status_code == 200


async def test_demo_mode_blocks_real_actions(settings, config, profile):
    """Ein Demo-Ordner darf nie echt crawlen, bewerben oder Nachrichten verschicken."""
    settings.demo = True
    settings.autopilot_enabled = True
    settings.notify_webhook_url = "https://hooks.example/abc"
    client = _client(settings, config, profile)
    assert client.get("/api/status").json()["demo"] is True
    for path, body in (
        ("/api/crawl", None),
        ("/api/apply", {"job_ids": [1], "mode": "dry-run"}),
        ("/api/autopilot/run", None),
        ("/api/jobs", {"url": "https://example.com/jobs/1"}),
    ):
        r = client.post(path, json=body)
        assert r.status_code == 409 and "Demo-Modus" in r.json()["detail"], (path, r.text)
    assert next_run(settings) is None
    with respx.mock(assert_all_called=False) as router:
        hook = router.post("https://hooks.example/abc").respond(204)
        assert await notify(settings, "t", "m") == 0
        assert not hook.called
    with pytest.raises(DemoModeError):
        await run_crawl(settings, config)
    engine = ApplyEngine.__new__(ApplyEngine)
    engine.settings = settings
    with pytest.raises(DemoModeError):
        await engine.apply(1)


def test_jobs_pipeline_and_stats(settings, config, profile):
    client = _client(settings, config, profile)
    status = client.get("/api/status").json()
    assert status["setup_completed"] is False and status["counts"]["open_jobs"] == 3
    jobs = client.get("/api/jobs", params={"view": "all", "status": "all"}).json()
    assert jobs["total"] == 3 and jobs["facets"]["category"]["SRE"] == 1
    todo = client.get("/api/jobs").json()
    # die SRE-Stelle ist laut Import schon beworben
    assert {j["title"] for j in todo["items"]} == {"Cloud Engineer (m/w/d)", "Platform Engineer"}
    platform = next(j for j in todo["items"] if j["title"] == "Platform Engineer")
    assert platform["starred"]

    detail = client.get(f"/api/jobs/{platform['id']}").json()
    assert detail["verdict"]["ok"] and detail["history"][0]["change"] == "imported"
    assert client.patch(f"/api/jobs/{platform['id']}", json={"queued": True, "notes": "Top"}).json()["queued"]
    assert client.get("/api/jobs", params={"view": "queued"}).json()["total"] == 1

    marked = client.post(f"/api/jobs/{platform['id']}/status", json={"status": "applied"}).json()
    assert marked["app_status"] == "manual" and not marked["queued"]
    pipe = client.get("/api/pipeline").json()
    applied = {a["title"]: a for a in pipe["stages"]["applied"]}
    assert set(applied) == {"Site Reliability Engineer", "Platform Engineer"}
    assert applied["Platform Engineer"]["follow_up_at"]  # Nachfass-Erinnerung gesetzt
    app_id = applied["Platform Engineer"]["id"]
    moved = client.patch(f"/api/applications/{app_id}", json={"status": "interview"}).json()
    assert moved["status"] == "interview"
    assert client.patch(f"/api/applications/{app_id}", json={"status": "bogus"}).status_code == 400
    assert [a["id"] for a in client.get("/api/pipeline").json()["stages"]["interview"]] == [app_id]

    stats = client.get("/api/stats").json()
    assert stats["applications"]["sent_total"] == 2
    assert stats["applications"]["interview_rate"] == 0.5
    assert len(stats["applications"]["per_week"]) == 12
    ids = [j["id"] for j in todo["items"]]
    assert len(client.post("/api/jobs/bulk", json={"ids": ids, "action": "star"}).json()["changed"]) == 2
    assert len(client.get("/api/export.csv").text.strip().splitlines()) == 4  # Kopf + 3 Stellen
    assert any("interview" in a["message"] for a in client.get("/api/activity").json())


def test_triage_dismissed_and_counts(settings, config, profile):
    client = _client(settings, config, profile)
    # Import: die SRE-Stelle ist beworben, Platform gemerkt – zu sichten bleibt nur Cloud
    triage = client.get("/api/jobs", params={"view": "triage"}).json()
    assert [j["title"] for j in triage["items"]] == ["Cloud Engineer (m/w/d)"]
    counts = client.get("/api/status").json()["counts"]
    assert counts["to_review"] == 1
    assert triage["counts"] == {"triage": 1, "starred": 1, "queued": 0, "all": 3, "dismissed": 0}
    # der Rollenfilter wirkt auf Liste und Zähler, das Rollenmenü (facets) zeigt weiter alle Rollen
    sre = client.get("/api/jobs", params={"view": "all", "status": "all", "category": "SRE"}).json()
    assert sre["total"] == 1 and sre["counts"]["all"] == 1 and len(sre["facets"]["category"]) == 3
    cloud = triage["items"][0]
    assert cloud["excluded"] is False

    # Aussortieren nimmt die Stelle aus allen Arbeitslisten und liefert die ID für „Rückgängig“
    r = client.post("/api/jobs/bulk", json={"ids": [cloud["id"]], "action": "exclude"}).json()
    assert r["changed"] == [cloud["id"]] and len(r["exclusions"]) == 1
    assert client.get("/api/jobs", params={"view": "triage"}).json()["total"] == 0
    assert cloud["id"] not in [j["id"] for j in client.get("/api/jobs").json()["items"]]
    dismissed = client.get("/api/jobs", params={"view": "dismissed"}).json()["items"]
    assert [j["id"] for j in dismissed] == [cloud["id"]] and dismissed[0]["excluded"]
    assert client.get(f"/api/jobs/{cloud['id']}").json()["excluded"]
    assert client.get("/api/status").json()["counts"]["to_review"] == 0

    client.delete(f"/api/exclusions/{r['exclusions'][0]}")
    assert client.get("/api/jobs", params={"view": "triage"}).json()["total"] == 1

    # fälliges Nachfassen zählt nur die letzte Bewerbung je Stelle mit Termin in der Vergangenheit
    due_before = client.get("/api/status").json()["counts"]["follow_ups_due"]
    with session_scope(settings.db_path) as s:
        s.add(Application(job_id=cloud["id"], status="submitted", follow_up_at=datetime(2020, 1, 1)))
    assert client.get("/api/status").json()["counts"]["follow_ups_due"] == due_before + 1


def test_prompt_roundtrip(settings, config, profile):
    client = _client(settings, config, profile)
    with session_scope(settings.db_path) as s:
        app = Application(job_id=1, status="running")
        s.add(app)
        s.flush()
        questions = [{"field_id": "0-7", "question": "Gehalt?", "why": "", "options": []}]
        p = Prompt(
            application_id=app.id, kind="questions", payload={"title": "Beispiel", "questions": questions}
        )
        c = Prompt(
            application_id=app.id, kind="confirm", payload={"title": "Beispiel", "rows": [], "screenshot": ""}
        )
        s.add_all([p, c])
        s.flush()
        pid, cid = p.id, c.id
    assert [x["kind"] for x in client.get("/api/status").json()["prompts"]] == ["questions", "confirm"]
    client.post(f"/api/prompts/{pid}", json={"answers": {"0-7": "70000"}})
    assert client.post(f"/api/prompts/{cid}", json={"decision": "nope"}).status_code == 400
    client.post(f"/api/prompts/{cid}", json={"decision": "submit"})
    assert (
        client.post(f"/api/prompts/{cid}", json={"decision": "submit"}).status_code == 409
    )  # schon beantwortet
    with session_scope(settings.db_path) as s:
        assert s.get(Prompt, pid).response == {"answers": {"0-7": "70000"}}
        assert s.get(Prompt, cid).response == {"decision": "submit"}
    assert client.get("/api/prompts").json() == []


def test_settings_search_and_profile(settings, config, profile):
    client = _client(settings, config, profile)
    assert client.get("/api/settings").json()["apply_mode"] == "review"
    saved = client.put("/api/settings", json={"autopilot_enabled": True, "autopilot_time": "06:30"}).json()
    assert saved["autopilot_enabled"] and settings.settings_path.exists()
    assert client.put("/api/settings", json={"claude_bin": "evil.exe"}).status_code == 422

    assert {p["id"] for p in client.get("/api/presets").json()} >= {"cloud", "software", "data"}
    preview = client.post(
        "/api/search/preset", json={"presets": ["software"], "cities": ["Köln"], "remote": True}
    ).json()
    assert preview["roles"][0]["name"] == "Backend" and preview["filters"]["onsite_locations"] == ["köln"]
    assert client.put("/api/search", json=preview).status_code == 200 and settings.search_path.exists()
    assert client.get("/api/search").json()["roles"][0]["name"] == "Backend"
    assert client.put("/api/search", json=preview | {"roles": []}).status_code == 422

    data = client.get("/api/profile").json()
    assert data["profile"]["personal"]["first_name"] == "Max"
    assert data["profile"]["work"]["notice_period"] == ""  # TODO wird für die Oberfläche geleert
    data["profile"]["personal"]["city"] = "Köln"
    saved = client.put("/api/profile", json=data["profile"]).json()
    assert saved["profile"]["personal"]["city"] == "Köln"
    assert "notice_period: TODO" in settings.profile_path.read_text(
        encoding="utf-8"
    )  # leer bleibt "unbekannt"

    up = client.post(
        "/api/profile/document",
        files={"file": ("Max_Mustermann_CV.pdf", b"%PDF-1.4\n%", "application/pdf")},
        data={"kind": "cv", "import_cv": "false"},
    ).json()
    assert up["documents"]["cv"] == {"name": "Max_Mustermann_CV.pdf", "exists": True}
    assert (settings.documents_dir / "Max_Mustermann_CV.pdf").exists()
    bad = client.post(
        "/api/profile/document",
        files={"file": ("cv.docx", b"x", "application/octet-stream")},
        data={"kind": "cv"},
    )
    assert bad.status_code == 400


def test_answers_and_exclusions(settings, config, profile):
    client = _client(settings, config, profile)
    aid = client.post("/api/answers", json={"question": "Kündigungsfrist?", "answer": "3 Monate"}).json()[
        "id"
    ]
    client.post(
        "/api/answers", json={"question": "Kündigungsfrist", "answer": "1 Monat"}
    )  # gleiche Frage → Update
    with session_scope(settings.db_path) as s:
        assert [a.answer for a in s.execute(select(Answer)).scalars()] == ["1 Monat"]
    client.put(f"/api/answers/{aid}", json={"question": "Kündigungsfrist?", "answer": "2 Monate"})
    assert client.get("/api/answers").json()[0]["answer"] == "2 Monate"
    client.delete(f"/api/answers/{aid}")
    assert client.get("/api/answers").json() == []

    with session_scope(settings.db_path) as s:
        job = s.execute(select(Job).where(Job.company == "Spreebyte")).scalars().one()
        job.queued = True
        jid = job.id
    ex = client.post("/api/exclusions", json={"kind": "company", "value": "Spreebyte"}).json()
    job = client.get(f"/api/jobs/{jid}").json()
    assert not job["queued"]  # Ausschluss nimmt aus der Warteschlange
    assert "ausgeschlossen" in job["verdict"]["reason"]
    assert client.post("/api/exclusions", json={"kind": "bogus", "value": "x"}).status_code == 400
    client.delete(f"/api/exclusions/{ex['id']}")
    assert client.get("/api/exclusions").json() == []


def test_spa_is_served(settings, config, profile):
    client = _client(settings, config, profile)
    r = client.get("/pipeline")
    assert r.status_code in (200, 503)
    if r.status_code == 200:
        assert '<div id="root">' in r.text
    assert client.get("/api/does-not-exist").status_code == 404


JOB_HTML = """<html><head><title>Careers</title>
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"WebPage"},
{"@type":"JobPosting","title":"Platform Engineer (m/w/d)","hiringOrganization":{"@type":"Organization","name":"Havelstack"},
"jobLocation":{"@type":"Place","address":{"addressLocality":"Berlin","addressCountry":"DE"}},
"jobLocationType":"TELECOMMUTE","datePosted":"2026-10-01","description":"&lt;p&gt;Kubernetes und Terraform&lt;/p&gt;"}]}</script>
</head><body></body></html>"""


def test_job_page_parsing():
    job = parse_html("https://x/job", JOB_HTML)
    assert job.via == "jsonld" and job.title == "Platform Engineer (m/w/d)" and job.company == "Havelstack"
    assert job.location == "Berlin, DE, Remote" and job.remote and "Kubernetes" in job.description
    meta = parse_html(
        "https://x/2", '<meta property="og:title" content="DevOps Engineer | Acme"><title>t</title>'
    )
    assert meta.via == "meta" and meta.title == "DevOps Engineer"


def test_add_job_by_link(settings, config, profile):
    client = _client(settings, config, profile)
    with respx.mock(assert_all_called=False) as router:
        router.get("https://jobs.example.com/platform").respond(text=JOB_HTML)
        r = client.post("/api/jobs", json={"url": "https://jobs.example.com/platform"}).json()
        again = client.post("/api/jobs", json={"url": "https://jobs.example.com/platform"}).json()
    assert r["created"] and r["via"] == "jsonld"
    assert again == {"id": r["id"], "created": False, "via": "jsonld"}
    job = client.get(f"/api/jobs/{r['id']}").json()
    assert job["company"] == "Havelstack" and job["category"] == "Platform" and job["starred"]
    assert client.post("/api/jobs", json={"url": "keine-url"}).status_code == 422


def test_autopilot_schedule(settings):
    s = settings.model_copy(
        update={"autopilot_enabled": True, "autopilot_days": [0, 1, 2, 3, 4], "autopilot_time": "08:00"}
    )
    monday_early = datetime(2026, 10, 26, 7, 0)
    assert next_run(s, monday_early) == datetime(2026, 10, 26, 8, 0)
    saturday = datetime(2026, 10, 31, 9, 0)
    assert next_run(s, saturday) == datetime(2026, 11, 2, 8, 0)  # Wochenende übersprungen
    late = datetime(2026, 10, 26, 20, 0)
    assert next_run(s, late) == datetime(2026, 10, 27, 8, 0)  # lange verpasst → nicht nachholen
    record(s, "autopilot", "Autopilot gestartet")
    assert next_run(s, datetime.now().replace(hour=23, minute=59)) is not None
    assert next_run(s.model_copy(update={"autopilot_enabled": False}), monday_early) is None


async def test_notifications(settings):
    s = settings.model_copy(
        update={
            "notify_ntfy_url": "https://ntfy.example/topic",
            "notify_webhook_url": "https://hook.example/x",
        }
    )
    with respx.mock() as router:
        ntfy = router.post("https://ntfy.example/topic").respond(200)
        hook = router.post("https://hook.example/x").respond(204)
        assert await notify(s, "jobslop – Rückfrage", "Bitte antworten", url="http://127.0.0.1:8765") == 2
    assert ntfy.calls[0].request.headers["Click"] == "http://127.0.0.1:8765"
    assert ntfy.calls[0].request.headers["Title"].startswith("=?UTF-8?B?")  # Umlaute RFC-2047-kodiert
    assert b"Bitte antworten" in hook.calls[0].request.content
    with respx.mock() as router:
        router.post("https://ntfy.example/topic").mock(side_effect=httpx.ConnectError("down"))
        router.post("https://hook.example/x").respond(500)
        assert await notify(s, "x", "y") == 0  # Fehler werden geschluckt, nicht geworfen


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
        company="Beispiel GmbH",
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
    # Test-PDF ohne Textebene: Claude bekommt die Datei selbst (Read-Tool)
    assert call["content"][0]["type"] == "file" and call["content"][0]["path"].name.endswith(".pdf")
    # Antwortbank steht hinter der Cache-Grenze, Profil davor
    head, tail = call["system"].split(DYNAMIC_BOUNDARY)
    assert "Max" in head and "Kündigungsfrist" in tail and "Karriereseite" in tail
    text = call["content"][-1]["text"]
    assert "First Name *" in text and "Bitte Feld ausfüllen" in text and "SRE GCP" in text


async def test_llm_planner_uses_cv_text(settings, profile):
    cv = settings.home / "cv.txt"
    cv.write_text(
        "Max Mustermann – Site Reliability Engineer. " * 10 + "Terraform-Module für GCP", encoding="utf-8"
    )
    profile.documents.cv = str(cv)
    fake = _FakeLLM()
    planner = LLMPlanner(fake, profile, settings.home, [], cover_letter_auto=False)
    state = PageState(url="https://x", title="x", fields=[], buttons=[], errors=[])
    job = JobContext(
        id=1, company="A", title="SRE", location="Berlin", url="https://x", description="", language=""
    )
    await planner.plan(PlanInput(job=job, state=state, step=1))
    call = fake.calls[0]
    assert "Terraform-Module für GCP" in call["system"].split(DYNAMIC_BOUNDARY)[0]
    assert all(block["type"] == "text" for block in call["content"])  # kein Datei-Upload nötig


def test_extension_install_uses_the_running_address(settings, config, profile):
    client = _client(settings, config, profile)
    info = client.post("/api/extension/install").json()
    assert info["installed"] and not info["outdated"]
    cfg = (Path(info["path"]) / "config.js").read_text(encoding="utf-8")
    assert '"server": "http://testserver"' in cfg  # Adresse, unter der das Dashboard gerade läuft
    assert (Path(info["path"]) / "extract.js").read_text(encoding="utf-8").startswith("// Aus jobslop")
    # Assistenz-API nur mit Kopplungs-Token
    assert client.get("/api/assist/status").status_code == 401
    token = (settings.home / "extension-token").read_text(encoding="utf-8")
    assert client.get("/api/assist/status", headers={"X-Jobslop-Token": token}).json()["portals"] is False


def test_backend_texts_carry_codes_for_translation(settings, config, profile):
    """Das Dashboard übersetzt Aktivitäten und Prüf-Ergebnisse über Code + Parameter statt deutschem Klartext."""
    client = _client(settings, config, profile)
    client.post("/api/setup/complete", params={"start_crawl": False})
    entry = client.get("/api/activity").json()[0]
    assert entry["data"]["code"] == "setup.done" and entry["message"] == "Einrichtung abgeschlossen"
    job = next(j for j in client.get("/api/jobs", params={"view": "all", "status": "all"}).json()["items"])
    client.post("/api/exclusions", json={"kind": "company", "value": job["company"], "reason": "test"})
    verdict = client.get(f"/api/jobs/{job['id']}").json()["verdict"]
    assert not verdict["ok"] and verdict["code"].startswith("guard.") and verdict["params"]
    detail = client.get(f"/api/jobs/{job['id']}").json()
    assert sum(p["points"] for p in detail["score_parts"]) == pytest.approx(detail["score"], abs=0.11)


def test_frontend_score_max_matches_backend():
    """Der Score-Kreis im Dashboard misst gegen dieselbe Obergrenze wie classify."""
    from jobslop.classify import SCORE_MAX

    domain = (Path(__file__).resolve().parents[1] / "frontend/src/components/domain.tsx").read_text(
        encoding="utf-8"
    )
    assert f"export const SCORE_MAX = {SCORE_MAX:g};" in domain


def test_every_backend_code_has_a_translation():
    """Jeder Code, den das Backend ausgibt (record/activity/_no), braucht einen be.*-Text in beiden Sprachen.
    Abgeleitet aus dem Quelltext – ein neuer Code ohne Übersetzung fällt hier auf."""
    import re

    root = Path(__file__).resolve().parents[1]
    source = "\n".join(p.read_text(encoding="utf-8") for p in (root / "src" / "jobslop").rglob("*.py"))
    codes = set(re.findall(r'code="([a-z_]+\.[a-z_.]+)"', source))
    codes |= {f"guard.{c}" for c in re.findall(r'_no\(\s*(?:f?"[^"]*"|\w+),\s*"([a-z_]+)"', source, re.S)}
    assert {"crawl.done", "status.changed", "guard.closed", "guard.company_limit"} <= codes
    messages = (root / "frontend" / "src" / "lib" / "messages.ts").read_text(encoding="utf-8")
    missing = [c for c in sorted(codes) if messages.count(f'"be.{c}":') != 2]  # Deutsch und Englisch
    assert missing == []

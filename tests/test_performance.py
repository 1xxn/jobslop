"""Performance-Eigenschaften, die nicht wieder verloren gehen sollen: keine Abfrage pro Zeile (N+1), Crawl-Abfragen
über Indizes, Status-Zähler aus dem Zwischenspeicher, schneller Dashboard-Start. Gezählt werden SQL-Anweisungen und
Abfragepläne statt Sekunden – das ist auf jedem CI-Rechner gleich. Messrahmen für echte Zahlen: scripts/bench.py."""

from __future__ import annotations

import socket
import sqlite3
import time
from datetime import timedelta

import respx
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from conftest import LOCAL
from jobslop.cli import _port_free, _running_instance
from jobslop.crawl import pipeline
from jobslop.db import Application, InboxMessage, Job, get_engine, session_scope, utcnow
from jobslop.runtime import Runtime
from jobslop.web.app import create_app
from test_crawl import _config, _mock


class Statements:
    """SQL-Anweisungen der Datenbank mitschreiben (mit Parametern, für EXPLAIN QUERY PLAN)."""

    def __init__(self, settings) -> None:
        self.seen: list[tuple[str, tuple]] = []
        self.active = True
        event.listen(get_engine(settings.db_path), "before_cursor_execute", self._record)

    def _record(self, _conn, _cursor, statement, parameters, _context, _executemany) -> None:
        if self.active:
            self.seen.append((statement, tuple(parameters) if isinstance(parameters, list | tuple) else ()))

    def count(self, call) -> int:
        self.seen.clear()
        call()
        return len(self.seen)


def _seed(settings, jobs: int, *, apps_per_job: int = 1, replies: int = 0) -> int:
    """``jobs`` Stellen, jede zweite mit ``apps_per_job`` Bewerbungen. Rückgabe: ID einer Stelle mit Bewerbungen."""
    now = utcnow()
    with session_scope(settings.db_path) as s:
        first = None
        for i in range(jobs):
            job = Job(
                fingerprint=f"perf-{jobs}-{i}",
                match_key=f"firma {i}|site reliability engineer",
                source="greenhouse:perf",
                company=f"Firma {i}",
                title="Site Reliability Engineer",
                url=f"https://example.com/{jobs}/{i}",
                location="Berlin",
                where="B",
                category="SRE",
                description="Beschreibung " * 300,
            )
            s.add(job)
            if i % 2 == 0:
                for _ in range(apps_per_job):
                    app = Application(job=job, status="submitted", submitted_at=now, follow_up_at=now)
                    s.add(app)
                first = first or job
        s.flush()
        for app in s.scalars(select(Application).limit(replies)):
            s.add(InboxMessage(message_id=f"<{app.id}-{jobs}@x>", kind="rejection", application=app))
        assert first is not None
        return first.id


def _client(settings, config, profile) -> TestClient:
    app = create_app(Runtime(settings=settings, config=config, profile=profile))
    return TestClient(app, base_url=LOCAL, headers={"X-Jobslop": "1"})


def test_endpoints_need_the_same_queries_for_more_rows(settings, config, profile):
    """Keine Abfrage pro Bewerbung, Stelle oder Antwort: Listen- und Zähler-Endpoints brauchen bei 4× so vielen Zeilen
    genau so viele SQL-Anweisungen (früher: /api/applications 273, /api/pipeline 911, Export 20 001 bei 20.000 Stellen)."""
    client = _client(settings, config, profile)
    sql = Statements(settings)
    urls = [
        "/api/status",
        "/api/jobs?view=triage&level=noS",
        "/api/jobs?view=all&status=all&sort=new&limit=500",
        "/api/applications",
        "/api/pipeline",
        "/api/stats",
        "/api/export.csv",
    ]
    _seed(settings, 10, replies=1)
    small = {url: sql.count(lambda url=url: client.get(url)) for url in urls}
    _seed(settings, 40, replies=4)
    large = {url: sql.count(lambda url=url: client.get(url)) for url in urls}
    assert large == small


def test_job_detail_needs_the_same_queries_for_more_applications(settings, config, profile):
    client = _client(settings, config, profile)
    sql = Statements(settings)
    one = _seed(settings, 2, apps_per_job=1)
    three = _seed(settings, 4, apps_per_job=3)
    assert sql.count(lambda: client.get(f"/api/jobs/{three}")) == sql.count(
        lambda: client.get(f"/api/jobs/{one}")
    )


async def test_crawl_looks_up_postings_by_index(settings, config, monkeypatch):
    """Was der Crawl pro Posting abfragt, muss über einen passenden Index gehen. Regression: die Dubletten-Suche mit
    „status = open“ nahm ix_jobs_state und las jede offene Stelle samt Beschreibung (25 s statt 3 s für 2.000)."""
    config = _config(config)
    _seed(settings, 20)  # offene Stellen, die eine falsche Suche durchlesen würde
    sql = Statements(settings)
    sql.active = False
    upsert = pipeline._upsert

    def watched(*args, **kwargs):
        sql.active = True
        try:
            return upsert(*args, **kwargs)
        finally:
            sql.active = False

    monkeypatch.setattr(pipeline, "_upsert", watched)
    with respx.mock(assert_all_called=False) as router:
        _mock(router)
        report = await pipeline.run_crawl(settings, config, enrich=False, use_browser=False)
    assert report.new
    selects = {(st, params) for st, params in sql.seen if st.lstrip().upper().startswith("SELECT")}
    assert selects
    con = sqlite3.connect(settings.db_path)
    try:
        for statement, params in selects:
            plan = " | ".join(row[-1] for row in con.execute(f"EXPLAIN QUERY PLAN {statement}", params))
            assert "SCAN" not in plan and "ix_jobs_state" not in plan, f"{plan}\n{statement}"
    finally:
        con.close()


def test_status_counts_follow_every_writer(settings, config, profile):
    """Der Zähler „zu sichten“ kommt beim Polling aus dem Zwischenspeicher – aber jede Änderung, auch aus einem
    anderen Prozess (Bewerbungslauf, CLI), zählt beim nächsten Abruf neu."""
    client = _client(settings, config, profile)
    _seed(settings, 6)
    sql = Statements(settings)

    def counted() -> bool:
        """Hat der letzte Abruf die Stellen neu gezählt (Abfrage „ohne Bewerbung“)?"""
        return any("EXISTS" in statement for statement, _ in sql.seen)

    first = client.get("/api/status").json()["counts"]["to_review"]
    assert first == 3 and counted()  # jede zweite Stelle hat eine Bewerbung
    sql.seen.clear()
    assert client.get("/api/status").json()["counts"]["to_review"] == first
    assert not counted()  # nichts geändert: aus dem Zwischenspeicher

    triage = client.get("/api/jobs", params={"view": "triage"}).json()["items"]
    # eine fremde Verbindung schreibt (wie der Bewerbungslauf in seinem eigenen Prozess)
    con = sqlite3.connect(settings.db_path)
    with con:
        con.execute("UPDATE jobs SET starred = 1 WHERE id = ?", (triage[0]["id"],))
    con.close()
    sql.seen.clear()
    assert client.get("/api/status").json()["counts"]["to_review"] == first - 1
    assert counted()
    # das Dashboard selbst schreibt
    client.post("/api/jobs/bulk", json={"ids": [triage[1]["id"]], "action": "exclude"})
    assert client.get("/api/status").json()["counts"]["to_review"] == first - 2
    # und eine Bewerbung im Hintergrund
    with session_scope(settings.db_path) as s:
        s.add(
            Application(job_id=triage[2]["id"], status="running", started_at=utcnow() - timedelta(minutes=1))
        )
    assert client.get("/api/status").json()["counts"]["to_review"] == first - 3


def test_free_port_check_is_instant():
    """Unter Windows dauerte die Prüfung eines freien Ports 2 s (Verbindungsversuch mit SYN-Wiederholungen) – der
    Dashboard-Start wartete zweimal darauf."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    started = time.perf_counter()
    assert _port_free("127.0.0.1", port)
    assert not _running_instance("127.0.0.1", port)
    assert time.perf_counter() - started < 1.0
    with socket.socket() as server:
        server.bind(("127.0.0.1", port))
        server.listen()
        assert not _port_free("127.0.0.1", port)

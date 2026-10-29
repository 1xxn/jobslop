"""Härtung: was fremde Seiten, Job-Quellen, andere Prozesse oder eine fremde .env nicht dürfen.

Jeder Test steht für einen Befund aus docs/security.md – er schlägt fehl, wenn die Schutzmaßnahme wegfällt.
"""

from __future__ import annotations

import os
import socket
import sys
import time
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select

from conftest import LOCAL
from jobslop import netguard
from jobslop.config import Settings, is_source_checkout, load_settings, private_windows_folder
from jobslop.db import Exclusion, Job, session_scope
from jobslop.guard import excluded_job_ids, regex_problem
from jobslop.llm import subscription_env
from jobslop.netguard import BlockedTarget, ensure_public_target, is_public_url, public_client, read_limited
from jobslop.runtime import Runtime
from jobslop.web.app import create_app, safe_filename

ROOT = Path(__file__).resolve().parents[1]


def _client(settings, config, profile) -> TestClient:
    app = create_app(Runtime(settings=settings, config=config, profile=profile))
    return TestClient(app, base_url=LOCAL, headers={"X-Jobslop": "1"})


# --------------------------------------------------------------------------- SSRF: nur öffentliche Ziele


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8765/api/profile",
        "http://localhost:8765/",
        "http://app.localhost/",
        "http://10.0.0.1/",
        "http://192.168.178.1/",  # Router
        "http://172.16.5.4/",
        "http://100.64.0.1/",  # Carrier-NAT
        "http://169.254.169.254/latest/meta-data/",  # Cloud-Metadaten
        "http://0.0.0.0/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[fe80::1]/",
        "http://[fd00::1]/",
        "http://2130706433/",  # 127.0.0.1 als Zahl – Browser lesen das als IPv4
        "http://127.1/",
        "http://0x7f.0.0.1/",
        "http://0177.0.0.1/",
        "http://router/",  # Name ohne Punkt: löst das lokale Netz auf
        "http://printer.local/",
        "http://wiki.internal/",
        "javascript:alert(1)",
        "file:///etc/passwd",
        "ftp://example.com/",
        "http://256.1.1.1/",
        "",
    ],
)
def test_private_and_odd_targets_are_not_public(url):
    assert not is_public_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://boards.greenhouse.io/acme/jobs/1",
        "http://8.8.8.8/",
        "https://[2606:4700::1111]/",
        "https://jobs.example.de/x",
    ],
)
def test_public_targets_pass(url):
    assert is_public_url(url)


def _resolve_to(monkeypatch, address: str) -> None:
    """Jeder Name zeigt auf ``address`` (wie ein bösartiger DNS-Eintrag oder DNS-Rebinding)."""

    async def fake_getaddrinfo(_loop, host, port, *_args, **_kw):
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (address, port or 0))]

    monkeypatch.setattr(netguard.asyncio.get_running_loop().__class__, "getaddrinfo", fake_getaddrinfo)
    netguard._dns_cache.clear()


async def test_names_that_resolve_into_the_own_network_are_blocked(monkeypatch):
    """Ein öffentlicher Name, der auf 127.0.0.1 zeigt: Engine und Erweiterung öffnen die Seite nicht."""
    _resolve_to(monkeypatch, "127.0.0.1")
    with pytest.raises(BlockedTarget):
        await ensure_public_target("https://jobs.evil.example/apply", Settings())
    await ensure_public_target("https://jobs.evil.example/apply", Settings(allow_private_targets=True))
    _resolve_to(monkeypatch, "93.184.215.14")
    await ensure_public_target("https://jobs.example.org/apply", Settings())


async def test_public_client_checks_every_connection(monkeypatch, site):
    """Auch nach einer Weiterleitung oder bei DNS-Rebinding: verbunden wird nur zu einer geprüften öffentlichen
    Adresse. Hier zeigt der Name auf den lokalen Testserver – die Verbindung wird verweigert."""
    port = int(site.base_url.rsplit(":", 1)[1])
    _resolve_to(monkeypatch, "127.0.0.1")
    async with public_client() as client:
        with pytest.raises(BlockedTarget):
            await client.get(f"http://jobs.evil.example:{port}/posting.html")
        with pytest.raises(BlockedTarget):
            await client.get(f"{site.base_url}/posting.html")


async def test_add_job_by_link_refuses_local_targets(settings, config, profile, monkeypatch):
    """„Stelle per Link“ lädt nichts aus dem eigenen Netz – auch nicht das Dashboard selbst."""
    settings.allow_private_targets = False
    client = _client(settings, config, profile)
    r = client.post("/api/jobs", json={"url": "http://127.0.0.1:8765/api/profile"})
    assert r.status_code == 422
    _resolve_to(monkeypatch, "169.254.169.254")
    r = client.post("/api/jobs", json={"url": "http://metadata.evil.example/latest/meta-data/"})
    assert r.status_code == 422
    with session_scope(settings.db_path) as s:
        assert s.scalar(select(Job.id)) is None


async def test_downloads_are_capped():
    """Eine riesige Antwort wird nur bis zur Grenze gelesen."""

    def handler(_request):
        return httpx.Response(200, content=b"x" * 5_000_000)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with client, client.stream("GET", "https://example.com/huge") as resp:
        data = await read_limited(resp, 1_000_000)
    assert len(data) == 1_000_000


async def test_crawl_drops_postings_on_private_addresses(settings, config):
    """Eine Job-Quelle, die 127.0.0.1 (das Dashboard) als Stellenadresse liefert, kommt nicht in die Datenbank –
    sonst öffnete der Bewerbungs-Browser jobslop selbst und der Planer bediente es."""
    from jobslop.crawl.pipeline import run_crawl
    from test_crawl import GH_JOBS, _config, _mock

    settings.allow_private_targets = False
    config = _config(config)
    evil = dict(
        GH_JOBS["jobs"][0], id=98, title="Platform Engineer", absolute_url="http://127.0.0.1:8765/settings"
    )
    with respx.mock(assert_all_called=False) as router:
        _mock(router, gh={"jobs": [*GH_JOBS["jobs"], evil]})
        await run_crawl(settings, config, enrich=False, use_browser=False)
    with session_scope(settings.db_path) as s:
        urls = list(s.execute(select(Job.url)).scalars())
    assert urls and all(is_public_url(u) for u in urls)


async def test_extension_refuses_pages_in_the_own_network(settings, config, profile):
    """Die Erweiterung füllt nichts auf Seiten im eigenen Netz aus (z. B. das Dashboard in einem Tab)."""
    from jobslop import assist

    settings.allow_private_targets = False
    rt = Runtime(settings=settings, config=config, profile=profile)
    frame = {
        "url": "http://127.0.0.1:8765/settings",
        "title": "jobslop",
        "text": "",
        "headings": [],
        "fields": [],
        "buttons": [],
        "errors": [],
        "captcha": [],
    }
    result = await assist.step(rt, assist.StepIn(frames=[assist.FrameIn(index=0, data=frame)]), None)
    assert "eigenen" in result["blocked"]


# --------------------------------------------------------------------------- ReDoS in Titel-Ausschlüssen


@pytest.mark.parametrize(
    "pattern",
    ["(a+)+$", "(a|aa)*b", "(x+x+)+y", "(.*a){3}", r"(\w)\1", "a.*b.*c.*d", "(?:senior|lead)+", "x" * 201],
)
def test_catastrophic_title_regexes_are_rejected(pattern):
    assert regex_problem(pattern)


@pytest.mark.parametrize(
    "pattern",
    [
        r"\b(senior|lead|principal)\b",
        "werkstudent|praktikum",
        "^head of",
        r"sales.*manager",
        r"\bsr\.?\s",
        "(?i)intern",
    ],
)
def test_ordinary_title_regexes_are_allowed(pattern):
    assert regex_problem(pattern) == ""


def test_bad_regex_cannot_stall_the_status_poll(settings):
    """Steht ein gefährlicher Ausdruck schon in der Datenbank (ältere Version), gilt er als Text – der Status-Abruf
    bleibt schnell, auch gegen präparierte Titel."""
    with session_scope(settings.db_path) as s:
        s.add(Exclusion(kind="title", value="(a+)+$"))
        s.add(Exclusion(kind="title", value="(a|aa)*c"))
        rows = [
            Job(id=i, fingerprint=f"r{i}", company="X", title="a" * (40 + i) + "!", url="https://x.example/")
            for i in range(1, 300)
        ]
        started = time.perf_counter()
        assert excluded_job_ids(s, rows) == set()
        assert time.perf_counter() - started < 1.0


def test_api_rejects_catastrophic_regex(settings, config, profile):
    client = _client(settings, config, profile)
    r = client.post("/api/exclusions", json={"kind": "title", "value": "(a+)+$"})
    assert r.status_code == 400 and r.json()["code"] == "api.bad_regex"
    assert client.post("/api/exclusions", json={"kind": "title", "value": r"\bsenior\b"}).status_code == 200


# --------------------------------------------------------------------------- Eingaben, Größen, Dateien


def test_request_bodies_and_lists_are_bounded(settings, config, profile):
    client = _client(settings, config, profile)
    huge = {"question": "Warum?", "answer": "x" * 2_000_000}
    r = client.post("/api/answers", json=huge)
    assert r.status_code == 413 and r.json()["code"] == "api.too_large"
    assert client.get("/api/jobs", params={"limit": 100_000}).status_code == 422
    assert client.get("/api/runner", params={"lines": 10**9}).status_code == 422
    assert client.get("/api/activity", params={"limit": -1}).status_code == 422
    assert client.post("/api/answers", json={"question": "a", "answer": "b", "extra": 1}).status_code == 422


def test_settings_are_validated(settings, config, profile):
    client = _client(settings, config, profile)
    bad = [
        {"claude_effort": "--dangerously-skip-permissions"},  # landet als Argument beim claude-Aufruf
        {"llm_model": "sonnet --tools Bash"},
        {"inbox_folder": 'INBOX" DELETE "x'},  # steht in Anführungszeichen im IMAP-Befehl
        {"inbox_folder": "INBOX\r\nA1 LOGOUT"},
        {"notify_webhook_url": "javascript:alert(1)"},
        {"notify_ntfy_url": "file:///etc/passwd"},
        {"claude_parallel": 500},
        {"autopilot_time": "25:99"},
        {"autopilot_days": [9]},
        {"dashboard_host": "0.0.0.0"},  # nicht änderbar
        {"unknown": True},
    ]
    for body in bad:
        assert client.put("/api/settings", json=body).status_code == 422, body
    ok = client.put("/api/settings", json={"claude_effort": "high", "notify_ntfy_url": "https://ntfy.sh/x"})
    assert ok.status_code == 200 and ok.json()["claude_effort"] == "high"


def test_profile_rejects_unknown_fields_and_outside_documents(settings, config, profile, tmp_path):
    client = _client(settings, config, profile)
    data = client.get("/api/profile").json()["profile"]
    assert client.put("/api/profile", json=data | {"admin": True}).status_code == 422
    outside = tmp_path / "geheim.pdf"
    outside.write_bytes(b"%PDF-1.4 privat")
    for value in (str(outside), "../geheim.pdf", "~/.ssh/id_rsa"):
        body = data | {"documents": data["documents"] | {"cv": value}}
        r = client.put("/api/profile", json=body)
        assert r.status_code == 422 and r.json()["code"] == "api.document_outside", value
    inside = data | {"documents": data["documents"] | {"certificates": ["documents/zeugnis.pdf"]}}
    assert client.put("/api/profile", json=inside).status_code == 200


def test_uploads_are_streamed_checked_and_named_safely(settings, config, profile):
    client = _client(settings, config, profile)

    def upload(name: str, content: bytes):
        return client.post(
            "/api/profile/document",
            files={"file": (name, content, "application/pdf")},
            data={"kind": "certificate"},
        )

    assert upload("fake.pdf", b"MZ\x90\x00 kein PDF").status_code == 400  # Endung allein genügt nicht
    assert upload("leer.pdf", b"").status_code == 400
    assert upload("gross.pdf", b"%PDF-" + b"0" * (16 * 1024 * 1024)).status_code == 413
    assert upload("../../evil.pdf", b"%PDF-1.4").status_code == 200
    assert upload("CON.pdf", b"%PDF-1.4").status_code == 200
    names = sorted(p.name for p in settings.documents_dir.iterdir())
    assert names == ["_CON.pdf", "evil.pdf"]  # keine Zwischendateien, nichts außerhalb von documents/
    assert not (settings.home.parent / "evil.pdf").exists()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../x.pdf", "x.pdf"),
        ("..\\..\\x.pdf", "x.pdf"),
        ("C:\\Windows\\win.ini", "win.ini"),
        ("cv.pdf:stream", "cv.pdf_stream"),  # alternativer Datenstrom unter Windows
        ("NUL.pdf", "_NUL.pdf"),
        ("com1.tar.pdf", "_com1.tar.pdf"),
        ("  .versteckt.pdf. ", "versteckt.pdf"),
        ("", "dokument.pdf"),
    ],
)
def test_safe_filename(raw, expected):
    assert safe_filename(raw) == expected


# --------------------------------------------------------------------------- Konfiguration und Prozesse


def test_dashboard_only_binds_to_loopback():
    assert Settings(dashboard_host="0.0.0.0").dashboard_host == "127.0.0.1"
    assert Settings(dashboard_host="192.168.1.5").dashboard_host == "127.0.0.1"
    assert Settings(dashboard_host="localhost").dashboard_host == "localhost"


def test_dotenv_in_a_foreign_folder_is_ignored(tmp_path, monkeypatch):
    """Eine .env in einem fremden Ordner (heruntergeladenes Repo) darf kein Programm als „Claude“ unterschieben."""
    for key in [k for k in os.environ if k.startswith(("JOBSLOP_", "JOBPILOT_"))]:
        monkeypatch.delenv(key)
    monkeypatch.setenv("JOBSLOP_HOME", str(tmp_path / "home"))
    foreign = tmp_path / "repo"
    foreign.mkdir()
    (foreign / ".env").write_bytes(b"JOBSLOP_CLAUDE_BIN=C:/evil/claude.exe\nJOBSLOP_DASHBOARD_HOST=0.0.0.0\n")
    monkeypatch.chdir(foreign)
    loaded = load_settings()
    assert loaded.claude_bin == "" and loaded.dashboard_host == "127.0.0.1"
    assert "JOBSLOP_CLAUDE_BIN" not in os.environ
    assert not is_source_checkout(foreign) and is_source_checkout(ROOT)


def test_claude_does_not_inherit_jobslop_secrets(monkeypatch):
    monkeypatch.setenv("JOBSLOP_INBOX_PASSWORD", "app-passwort")
    monkeypatch.setenv("JOBPILOT_INBOX_PASSWORD", "alt")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    env = subscription_env()
    assert not any(k.startswith(("JOBSLOP_", "JOBPILOT_")) for k in env) and "ANTHROPIC_API_KEY" not in env


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-ACLs")
def test_windows_folder_outside_the_profile_is_private(tmp_path):
    import subprocess

    folder = tmp_path / "jobslop-home"
    folder.mkdir()
    assert private_windows_folder(folder) and (folder / ".private").exists()
    acl = subprocess.run(["icacls", str(folder)], capture_output=True, text=True, check=False).stdout
    assert "(I)" not in acl.split("\n")[0]  # keine geerbten Einträge mehr
    for group in ("S-1-1-0", "Everyone", "Jeder", "BUILTIN\\Users", "VORDEFINIERT\\Benutzer"):
        assert group not in acl


def test_fastapi_telemetry_stays_off(settings, config, profile, monkeypatch):
    """FastAPI bringt OpenTelemetry mit: jobslop exportiert nichts, auch wenn die Umgebung Exporter verlangt."""
    monkeypatch.setenv("FASTAPI_OTEL_AUTO_CONFIGURE", "true")
    app = create_app(Runtime(settings=settings, config=config, profile=profile))
    telemetry = app._telemetry  # FastAPI hat dafür keinen öffentlichen Getter
    assert not any(telemetry[k] for k in ("tracing", "metrics", "logs", "operation_spans", "auto_configure"))
    assert not app._native_telemetry.enabled()

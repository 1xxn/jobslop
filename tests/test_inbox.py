"""Antworten aus dem Postfach: Zuordnung, Datenschutz-Filter, nur lesender IMAP-Zugriff und API."""

from __future__ import annotations

from datetime import datetime
from email.message import EmailMessage
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from conftest import LOCAL, add_job, signed_in
from jobslop import inbox
from jobslop.db import Application, InboxMessage, session_scope
from jobslop.inbox import Candidate, Mail, MailVerdict, check_inbox, fetch_mails, related
from jobslop.runtime import Runtime
from jobslop.web.app import create_app


def mail(sender: str, subject: str, text: str = "", uid: int = 1) -> Mail:
    return Mail(uid, f"<m{uid}@x>", sender, subject, datetime(2026, 10, 1), text)


APPS = [
    Candidate(1, "Acme Cloud GmbH", "Site Reliability Engineer", "submitted", "acme cloud"),
    Candidate(2, "Zalando SE", "Platform Engineer", "submitted", "zalando"),
]


def test_only_application_mails_are_related():
    assert [a.id for a in related(mail("jobs@zalando.de", "Deine Bewerbung"), APPS)] == [2]
    assert [a.id for a in related(mail("hr@example.org", "Ihre Bewerbung bei Acme Cloud"), APPS)] == [1]
    # Bewerbungssystem ohne Firmennamen: alle Bewerbungen kommen in Frage
    assert len(related(mail("no-reply@greenhouse-mail.io", "Thank you for applying"), APPS)) == 2
    # private Mail, Newsletter: geht nie an Claude
    assert related(mail("oma@web.de", "Kuchen am Sonntag?"), APPS) == []
    assert related(mail("news@shop.de", "Angebote der Woche", "Cloud Speicher"), APPS) == []


def test_parse_reads_html_mails():
    msg = EmailMessage()
    msg["From"] = "Acme Cloud <jobs@acme.com>"
    msg["Subject"] = "Ihre Bewerbung"
    msg["Date"] = "Wed, 01 Oct 2026 09:30:00 +0200"
    msg["Message-ID"] = "<abc@acme.com>"
    msg.set_content("Hallo")
    msg.add_alternative("<p>Leider haben wir uns <b>anders</b> entschieden.</p>", subtype="html")
    m = inbox._parse(7, msg.as_bytes())
    assert m.message_id == "<abc@acme.com>" and m.domain == "acme.com"
    assert m.received_at == datetime(2026, 10, 1, 7, 30)
    assert m.text == "Hallo"  # Klartext bevorzugt


class FakeImap:
    """Zeichnet auf, wie jobslop das Postfach anfasst."""

    calls: ClassVar[list[tuple[Any, ...]]] = []

    def __init__(self, host: str, port: int, timeout: int = 0) -> None:
        FakeImap.calls = [("connect", host, port)]

    def login(self, user: str, password: str) -> None:
        self.calls.append(("login", user))

    def select(self, folder: str, readonly: bool = False):
        self.calls.append(("select", folder, readonly))
        return "OK", [b"3"]

    def response(self, code: str):
        return code, [b"42"]

    def uid(self, command: str, *args: Any):
        self.calls.append(("uid", command, *args))
        if command == "SEARCH":
            return "OK", [b"5 6 7"]
        msg = EmailMessage()
        msg["From"] = "jobs@acme.com"
        msg["Subject"] = f"Mail {args[0]}"
        msg.set_content("Text")
        return "OK", [(b"1 (BODY[] {10}", msg.as_bytes()), b")"]

    def logout(self) -> None:
        self.calls.append(("logout",))


def test_fetch_is_read_only_and_incremental(settings, monkeypatch):
    settings.inbox_host, settings.inbox_user, settings.inbox_password = "imap.example.org", "me", "app-pw"
    monkeypatch.setattr(inbox.imaplib, "IMAP4_SSL", FakeImap)
    mails, state = fetch_mails(settings, {"uidvalidity": "42", "last_uid": 5})
    assert [m.uid for m in mails] == [6, 7] and state == {"uidvalidity": "42", "last_uid": 7}
    assert ("select", '"INBOX"', True) in FakeImap.calls  # EXAMINE: nichts wird verändert
    fetches = [c for c in FakeImap.calls if c[:2] == ("uid", "FETCH")]
    assert fetches and all("BODY.PEEK" in c[3] for c in fetches)  # bleibt ungelesen
    assert ("uid", "SEARCH", None, "UID 6:*") in FakeImap.calls and FakeImap.calls[-1] == ("logout",)
    # neue UIDVALIDITY (Postfach neu aufgebaut): wieder ab Rückblick-Datum
    fetch_mails(settings, {"uidvalidity": "1", "last_uid": 5})
    assert any(c[:3] == ("uid", "SEARCH", None) and c[3] == "SINCE" for c in FakeImap.calls)


class FakeLLM:
    def __init__(self, verdicts: list[MailVerdict]) -> None:
        self.verdicts = verdicts
        self.seen: list[str] = []

    async def parse(self, schema: type, *, system: str, content: Any, **_kw: Any) -> Any:
        self.seen.append(content)
        return self.verdicts.pop(0)


def _sent_application(settings, company: str, title: str) -> int:
    job_id = add_job(settings, f"https://example.com/{company}", company, title)
    with session_scope(settings.db_path) as s:
        app = Application(job_id=job_id, status="submitted")
        s.add(app)
        s.flush()
        return app.id


async def test_check_inbox_suggests_and_logs(settings, monkeypatch):
    acme = _sent_application(settings, "Acme Cloud GmbH", "Site Reliability Engineer")
    mails = [
        mail("jobs@acme.com", "Ihre Bewerbung", "Leider haben wir uns anders entschieden", uid=11),
        mail("oma@web.de", "Kuchen?", uid=12),
        mail("jobs@acme.com", "Eingang bestätigt", uid=13),
    ]
    monkeypatch.setattr(inbox, "fetch_mails", lambda _s, _st: (mails, {"uidvalidity": "1", "last_uid": 13}))
    llm = FakeLLM(
        [
            MailVerdict(application_id=acme, kind="rejection", summary="Absage"),
            MailVerdict(application_id=acme, kind="confirmation", summary="Eingang bestätigt"),
        ]
    )
    counts = await check_inbox(settings, llm)
    assert counts == {"checked": 3, "related": 2, "suggested": 1, "logged": 1}
    assert not any("Kuchen" in c for c in llm.seen)  # private Mail ging nicht an Claude
    with session_scope(settings.db_path) as s:
        rows = {m.kind: m.status for m in s.scalars(select(InboxMessage))}
        assert rows == {"rejection": "open", "confirmation": "logged"}
        assert [e.kind for e in s.get(Application, acme).events] == ["mail", "mail"]
    assert inbox.load_state(settings) == {"uidvalidity": "1", "last_uid": 13}
    # zweiter Lauf: dieselben Mails werden nicht noch einmal gefragt
    again = FakeLLM([])
    assert (await check_inbox(settings, again))["related"] == 0 and again.seen == []


def test_inbox_api_applies_and_hides_the_password(settings, config, profile):
    acme = _sent_application(settings, "Acme Cloud GmbH", "Site Reliability Engineer")
    with session_scope(settings.db_path) as s:
        s.add(InboxMessage(message_id="<x>", kind="interview", summary="Einladung", application_id=acme))
    client = TestClient(
        create_app(Runtime(settings=settings, config=config, profile=profile)),
        base_url=LOCAL,
        headers={"X-Jobslop": "1"},
        cookies=signed_in(settings),
    )
    client.put("/api/settings", json={"inbox_user": "me@example.org", "inbox_password": "geheim"})
    got = client.get("/api/settings").json()
    assert got["inbox_password"] == "" and got["inbox_password_set"] is True
    client.put(
        "/api/settings", json={"inbox_password": "", "inbox_folder": "Bewerbungen"}
    )  # leer = unverändert
    assert client.app.state.ctx.settings.inbox_password == "geheim"
    status = client.get("/api/status").json()
    assert status["counts"]["replies"] == 1 and status["replies"][0]["company"] == "Acme Cloud GmbH"
    reply = status["replies"][0]["id"]
    r = client.post(f"/api/inbox/{reply}", json={"action": "apply"}).json()
    assert r == {"application_id": acme, "previous_status": "submitted", "status": "interview"}
    assert client.post(f"/api/inbox/{reply}", json={"action": "apply"}).json()["code"] == "api.reply_closed"
    assert client.get("/api/status").json()["replies"] == []


@pytest.mark.parametrize("missing", ["inbox_host", "inbox_password"])
def test_incomplete_setup_is_a_clear_error(settings, config, profile, missing):
    settings.inbox_host, settings.inbox_user, settings.inbox_password = "imap.example.org", "me", "pw"
    setattr(settings, missing, "")
    client = TestClient(
        create_app(Runtime(settings=settings, config=config, profile=profile)),
        base_url=LOCAL,
        headers={"X-Jobslop": "1"},
        cookies=signed_in(settings),
    )
    r = client.post("/api/inbox/test")
    assert r.status_code == 502 and r.json()["code"] == "api.inbox_failed"

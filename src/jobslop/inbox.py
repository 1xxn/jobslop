"""Antworten aus dem Postfach: neue Mails per IMAP lesen, Antworten auf Bewerbungen erkennen und die passende
Statusänderung vorschlagen (bestätigt wird im Dashboard unter „Heute“).

Datenschutz: An Claude gehen nur Mails, die erkennbar zu einer Bewerbung gehören – Absender, Betreff oder Text
nennen eine Firma, bei der du dich beworben hast, oder die Mail kommt von einem Bewerbungssystem (Greenhouse,
Personio …). Alles andere verlässt den Rechner nicht. Gelesen wird mit EXAMINE und BODY.PEEK: nichts wird als
gelesen markiert, verschoben oder gelöscht.
"""

from __future__ import annotations

import asyncio
import contextlib
import email
import email.policy
import imaplib
import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from .classify import html_to_text
from .config import Settings, ensure_not_demo
from .db import Application, ApplicationEvent, InboxMessage, session_scope, utcnow
from .guard import company_key
from .llm import LLM

log = logging.getLogger(__name__)

# Absender-Domains von Bewerbungssystemen: deren Mails nennen die Firma oft nur im Text
ATS_DOMAINS = (
    "greenhouse.io",
    "greenhouse-mail.io",
    "lever.co",
    "ashbyhq.com",
    "personio.de",
    "personio.com",
    "smartrecruiters.com",
    "myworkday.com",
    "workday.com",
    "recruitee.com",
    "workablemail.com",
    "workable.com",
    "join.com",
    "softgarden.de",
    "softgarden.io",
    "successfactors.com",
    "successfactors.eu",
    "icims.com",
    "teamtailor.com",
    "teamtailor-mail.com",
    "bamboohr.com",
    "jobvite.com",
    "dvinci.de",
    "dvinci-easy.com",
    "rexx-systems.com",
    "taleo.net",
    "breezy.hr",
    "pinpointhq.com",
    "comeet.co",
)
SENT_STATES = ("submitted", "manual", "interview", "offer")
KIND_STATUS = {"rejection": "rejected", "interview": "interview", "offer": "offer"}
MAX_MAILS = 300  # pro Prüfung – beim ersten Mal reicht der Rückblick, danach kommen nur neue
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class InboxError(RuntimeError):
    """Postfach nicht erreichbar oder Anmeldung abgelehnt."""


@dataclass
class Mail:
    uid: int
    message_id: str
    sender: str
    subject: str
    received_at: datetime
    text: str

    @property
    def domain(self) -> str:
        m = re.search(r"@([\w.-]+)", self.sender)
        return m.group(1).lower() if m else ""


@dataclass
class Candidate:
    id: int
    company: str
    title: str
    status: str
    key: str


class MailVerdict(BaseModel):
    application_id: int | None = Field(None, description="ID der Bewerbung aus der Liste, sonst null")
    kind: Literal["confirmation", "rejection", "interview", "offer", "other"]
    summary: str = Field(description="Ein Satz in der Sprache der Mail: was sie sagt")


SYSTEM = """Du ordnest eine E-Mail den Bewerbungen einer Person zu.

- application_id: die Bewerbung aus der Liste, um die es geht (Firma und Stelle passen), sonst null.
- kind: confirmation (Eingang bestätigt), rejection (Absage), interview (Einladung zu Gespräch, Test oder
  Termin), offer (Angebot oder Zusage), other (alles andere: Jobalarm, Newsletter, Werbung, Umfrage).
- Im Zweifel other. Eine Absage, die nur „leider“ andeutet, ist trotzdem rejection.

Bewerbungen (id · Firma · Stelle · Stand):
{apps}"""


# --------------------------------------------------------------------------- IMAP (blockierend, im Thread)


def _since(days: int) -> str:
    d = date.today() - timedelta(days=days)
    return f"{d.day:02d}-{_MONTHS[d.month - 1]}-{d.year}"  # IMAP verlangt englische Monatsnamen


def _parse(uid: int, raw: bytes) -> Mail:
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    try:
        received = parsedate_to_datetime(str(msg.get("Date", ""))).astimezone(UTC).replace(tzinfo=None)
    except (TypeError, ValueError):
        received = utcnow()
    text = ""
    try:
        body = msg.get_body(preferencelist=("plain", "html"))
        if body is not None:
            content = body.get_content()
            text = html_to_text(content) if body.get_content_type() == "text/html" else content
    except (LookupError, ValueError, KeyError) as exc:  # abgeschnittene oder exotisch kodierte Mails
        log.debug("Mail %s nicht lesbar: %s", uid, exc)
    return Mail(
        uid=uid,
        message_id=str(msg.get("Message-ID", "")).strip() or f"uid-{uid}",
        sender=str(msg.get("From", "")),
        subject=str(msg.get("Subject", "")),
        received_at=received,
        text=re.sub(r"\s+", " ", text).strip()[:6000],
    )


def _connect(settings: Settings) -> imaplib.IMAP4_SSL:
    if not (settings.inbox_host and settings.inbox_user and settings.inbox_password):
        raise InboxError("nicht eingerichtet – Server, Benutzer und App-Passwort angeben")
    try:
        imap = imaplib.IMAP4_SSL(settings.inbox_host, settings.inbox_port, timeout=30)
    except OSError as exc:
        raise InboxError(
            f"Server {settings.inbox_host}:{settings.inbox_port} nicht erreichbar: {exc}"
        ) from exc
    try:
        imap.login(settings.inbox_user, settings.inbox_password)
        typ, _ = imap.select(f'"{settings.inbox_folder}"', readonly=True)  # EXAMINE: nur lesen
        if typ != "OK":
            raise InboxError(f"Ordner „{settings.inbox_folder}“ nicht gefunden")
    except imaplib.IMAP4.error as exc:
        _logout(imap)
        raise InboxError(f"Anmeldung abgelehnt: {exc}") from exc
    except InboxError:
        _logout(imap)
        raise
    return imap


def _logout(imap: imaplib.IMAP4) -> None:
    with contextlib.suppress(imaplib.IMAP4.error, OSError):
        imap.logout()


def try_connection(settings: Settings) -> int:
    """Anmelden und den Ordner öffnen; Rückgabe: Anzahl Mails im Ordner."""
    imap = _connect(settings)
    try:
        typ, data = imap.search(None, "ALL")
        return len(data[0].split()) if typ == "OK" and data and data[0] else 0
    finally:
        _logout(imap)


def fetch_mails(settings: Settings, state: dict[str, Any]) -> tuple[list[Mail], dict[str, Any]]:
    """Neue Mails seit der letzten Prüfung (beim ersten Mal: die letzten ``inbox_lookback_days`` Tage)."""
    imap = _connect(settings)
    try:
        validity = str((imap.response("UIDVALIDITY")[1] or [b""])[0] or b"", "ascii", "replace")
        last = int(state.get("last_uid") or 0) if state.get("uidvalidity") == validity else 0
        if last:
            typ, data = imap.uid("SEARCH", None, f"UID {last + 1}:*")
        else:
            typ, data = imap.uid("SEARCH", None, "SINCE", _since(settings.inbox_lookback_days))
        if typ != "OK":
            raise InboxError("Suche fehlgeschlagen")
        uids = sorted(u for u in (int(x) for x in (data[0] or b"").split()) if u > last)[-MAX_MAILS:]
        mails = []
        for uid in uids:
            typ, parts = imap.uid("FETCH", str(uid), "(BODY.PEEK[]<0.150000>)")  # große Anhänge abschneiden
            raw = next((p[1] for p in parts or [] if isinstance(p, tuple) and len(p) > 1), None)
            if typ == "OK" and raw:
                mails.append(_parse(uid, raw))
        return mails, {"uidvalidity": validity, "last_uid": max(uids, default=last)}
    except imaplib.IMAP4.error as exc:
        raise InboxError(f"IMAP-Fehler: {exc}") from exc
    finally:
        _logout(imap)


# --------------------------------------------------------------------------- Zuordnen


def candidates(settings: Settings, days: int = 180) -> list[Candidate]:
    since = utcnow() - timedelta(days=days)
    with session_scope(settings.db_path) as s:
        rows = s.scalars(
            select(Application).where(Application.status.in_(SENT_STATES), Application.started_at >= since)
        ).all()
        return [
            Candidate(a.id, a.job.company, a.job.title, a.status, company_key(a.job.company)) for a in rows
        ]


def related(mail: Mail, apps: list[Candidate]) -> list[Candidate]:
    """Bewerbungen, zu denen die Mail gehören könnte – leer heißt: geht nicht an Claude."""
    hay = f" {re.sub(r'[^a-z0-9]+', ' ', f'{mail.sender} {mail.subject} {mail.text[:5000]}'.lower())} "
    label = mail.domain.rsplit(".", 2)[-2] if mail.domain.count(".") >= 1 else mail.domain
    label = label.replace("-", "")

    def same_company(a: Candidate) -> bool:
        first = a.key.split()[0] if a.key else ""
        return f" {a.key} " in hay or a.key.replace(" ", "") == label or (len(first) >= 4 and first == label)

    hits = [a for a in apps if len(a.key) >= 3 and same_company(a)]
    if hits:
        return hits
    if any(mail.domain == d or mail.domain.endswith(f".{d}") for d in ATS_DOMAINS):
        return apps
    return []


def state_path(settings: Settings):
    return settings.home / "inbox.json"


def load_state(settings: Settings) -> dict[str, Any]:
    try:
        return json.loads(state_path(settings).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(settings: Settings, state: dict[str, Any]) -> None:
    state_path(settings).write_text(json.dumps(state), encoding="utf-8")


async def classify(llm: LLM, settings: Settings, mail: Mail, apps: list[Candidate]) -> MailVerdict:
    listing = "\n".join(f"{a.id} · {a.company} · {a.title} · {a.status}" for a in apps[:40])
    content = f"Von: {mail.sender}\nBetreff: {mail.subject}\nDatum: {mail.received_at:%Y-%m-%d}\n\n{mail.text[:4000]}"
    return await llm.parse(
        MailVerdict, system=SYSTEM.format(apps=listing), content=content, model=settings.llm_model_fast
    )


async def check_inbox(settings: Settings, llm: LLM | None) -> dict[str, int]:
    """Neue Mails prüfen. Eingangsbestätigungen landen im Verlauf der Bewerbung, Absagen, Einladungen und
    Angebote als Vorschlag (InboxMessage, status=open)."""
    ensure_not_demo(settings, "Postfach prüfen")
    if llm is None:
        raise InboxError("Claude Code ist nicht verfügbar")
    state = load_state(settings)
    mails, new_state = await asyncio.to_thread(fetch_mails, settings, state)
    apps = candidates(settings)
    counts = {"checked": len(mails), "related": 0, "suggested": 0, "logged": 0}
    with session_scope(settings.db_path) as s:
        seen = set(s.scalars(select(InboxMessage.message_id)))
    try:
        for mail in mails:
            hits = related(mail, apps) if mail.message_id not in seen else []
            if hits:
                counts["related"] += 1
                verdict = await classify(llm, settings, mail, hits)
                if verdict.application_id in {a.id for a in hits} and verdict.kind != "other":
                    counts["suggested" if verdict.kind in KIND_STATUS else "logged"] += 1
                    store(settings, mail, verdict)
            state = {"uidvalidity": new_state["uidvalidity"], "last_uid": mail.uid}
        state = new_state
    finally:
        save_state(settings, state)  # auch nach Abbruch (Claude-Limit): Erledigtes nicht noch einmal prüfen
    return counts


def store(settings: Settings, mail: Mail, verdict: MailVerdict) -> None:
    with session_scope(settings.db_path) as s:
        app = s.get(Application, verdict.application_id)
        if app is None:
            return
        open_ = verdict.kind in KIND_STATUS and app.status != KIND_STATUS[verdict.kind]
        s.add(
            InboxMessage(
                message_id=mail.message_id[:300],
                received_at=mail.received_at,
                sender=mail.sender[:300],
                subject=mail.subject[:500],
                kind=verdict.kind,
                summary=verdict.summary[:500],
                application_id=app.id,
                status="open" if open_ else "logged",
            )
        )
        s.add(
            ApplicationEvent(
                application_id=app.id,
                kind="mail",
                message=f"Mail: {mail.subject}"[:300],
                data={"kind": verdict.kind, "summary": verdict.summary[:500], "from": mail.sender[:200]},
            )
        )

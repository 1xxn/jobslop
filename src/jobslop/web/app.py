"""Dashboard-Server: JSON-API unter ``/api`` und die gebaute React-Oberfläche (``web/dist``).

Sicherheit: Der Server lauscht nur lokal. Zusätzlich werden fremde Host-Header abgewiesen (DNS-Rebinding)
und ändernde Anfragen brauchen den Header ``X-Jobslop: 1`` – den kann eine fremde Webseite ohne CORS-Freigabe
nicht setzen (CSRF-Schutz). Einbetten in fremde Seiten ist verboten (Clickjacking: eine Seite legt das Dashboard
unsichtbar über einen Köder und lässt dich „Absenden“ klicken), die Oberfläche lädt nur eigene Skripte (CSP).
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import mimetypes
import os
import re
from collections import Counter
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.orm import defer, selectinload
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import __version__, assist
from ..apply.coverletter import headless_pdf_context
from ..apply.executor import Files
from ..apply.planner import JobContext
from ..apply.tailor import cached_cv, ensure_tailored_cv
from ..autopilot import Scheduler, activity, crawl_and_queue, next_run, record
from ..classify import job_score_parts
from ..config import (
    EDITABLE_SETTINGS,
    ApplyMode,
    DemoModeError,
    SearchConfig,
    Settings,
    ensure_not_demo,
    save_settings,
    search_config_from_preset,
)
from ..crawl.sources import BOARD_SOURCES
from ..db import (
    Activity,
    Answer,
    Application,
    ApplicationEvent,
    ChangeCounter,
    CrawlRun,
    Exclusion,
    InboxMessage,
    Job,
    JobSnapshot,
    Prompt,
    session_scope,
    utcnow,
)
from ..guard import ACTIVE_STATES, DONE_STATES, check_job, excluded_job_ids, regex_problem
from ..inbox import KIND_STATUS, InboxError, check_inbox, try_connection
from ..llm import LLMLimitReached, LLMUnavailable
from ..netguard import WEB_SCHEMES
from ..notify import notify
from ..presets import presets_for_ui
from ..profile import TODO, Profile, Work, normalize_question
from ..queueing import pick_top, queue_jobs
from ..runner import Runner
from ..runtime import Runtime
from ..system import BrowserInstaller, open_claude_install, open_claude_login, open_folder, system_report

log = logging.getLogger(__name__)

DIST = Path(__file__).parent / "dist"
# Windows liest Dateitypen aus der Registry, dort steht für .js manchmal text/plain – mit „nosniff“ (und für
# Module ohnehin) führt der Browser die Oberfläche dann nicht aus.
for _type, _ext in (("text/javascript", ".js"), ("text/css", ".css"), ("image/svg+xml", ".svg")):
    mimetypes.add_type(_type, _ext)
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
}
# Nur für HTML: Chromes PDF-Ansicht (Lebenslauf-Vorschau) verträgt object-src 'none' nicht. Inline-Styles braucht
# Radix für die Position von Menüs und Tooltips.
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
    "font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
    "frame-ancestors 'none'"
)
STAGES = {
    "applied": ("submitted", "manual"),
    "interview": ("interview",),
    "offer": ("offer",),
    "rejected": ("rejected",),
}
MARK = {"applied": "manual", "interview": "interview", "rejected": "rejected", "offer": "offer"}
# Obergrenzen für Anfragen: ein lokaler Prozess (oder ein Fehler im Frontend) soll den Server nicht mit riesigen
# Körpern, Listen oder Texten in die Knie zwingen können
MAX_BODY = 1024 * 1024  # JSON-Anfragen
MAX_UPLOAD = 15 * 1024 * 1024  # PDF-Dokumente
UPLOAD_PATHS = ("/api/profile/document",)
MAX_TEXT = 50_000  # Zeichen pro Text in Profil, Suche, Antworten
MAX_ITEMS = 1_000  # Einträge pro Liste oder Objekt
MAX_DEPTH = 12
WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(10)),
    *(f"LPT{i}" for i in range(10)),
}


class Problem(HTTPException):
    """API-Fehler mit Code für das Dashboard (übersetzt über ``be.<code>``); ``detail`` bleibt der Klartext."""

    def __init__(self, status_code: int, code: str, detail: str, **params: Any) -> None:
        super().__init__(status_code, detail)
        self.code, self.params = code, params


# --------------------------------------------------------------------------- Serialisierung


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() + "Z" if d else None


def status_activity(job: Job, status: str) -> Activity:
    return activity(
        "status",
        f"{job.company} · {job.title}: {status}",
        code="status.changed",
        company=job.company,
        title=job.title,
        status=status,
    )


def job_summary(j: Job, *, excluded: bool = False) -> dict[str, Any]:
    last = j.applications[-1] if j.applications else None
    return {
        "id": j.id,
        "company": j.company,
        "title": j.title,
        "location": j.location,
        "where": j.where,
        "workplace": j.workplace,
        "category": j.category,
        "level": j.level,
        "fit": j.fit,
        "score": round(j.score, 1),
        "status": j.status,
        "queued": j.queued,
        "starred": j.starred,
        "source": j.source,
        # Firmen-Board (Greenhouse, Ashby …): die Adresse ist das Board selbst – sonst zeigt die UI, wohin es geht
        "board": j.source.split(":", 1)[0] in BOARD_SOURCES,
        "url": j.url,
        "posted": j.posted,
        "first_seen": _iso(j.first_seen),
        "enriched": bool(j.enrichment),
        "summary": (j.enrichment or {}).get("summary", ""),
        "app_status": last.status if last else ("queued" if j.queued else ""),
        "app_id": last.id if last else None,
        "excluded": excluded,
    }


def inbox_json(m: InboxMessage) -> dict[str, Any]:
    a = m.application
    return {
        "id": m.id,
        "kind": m.kind,
        "summary": m.summary,
        "subject": m.subject,
        "sender": m.sender,
        "received_at": _iso(m.received_at),
        "application_id": a.id,
        "company": a.job.company,
        "title": a.job.title,
        "app_status": a.status,
    }


JOB_VIEWS = ("triage", "starred", "queued", "all", "dismissed")
# Stelle zur Bewerbung gleich mitladen (eine Abfrage statt einer pro Bewerbung), ohne die Beschreibung
WITH_JOB = selectinload(Application.job).defer(Job.description)
WITH_APP_JOB = selectinload(InboxMessage.application).selectinload(Application.job).defer(Job.description)


@dataclass(slots=True)
class ListRow:
    """Was Ansichten, Zähler und Sortierung der Stellenliste von einer Stelle brauchen – ohne ORM-Objekt."""

    id: int
    company: str
    title: str
    url: str
    category: str
    level: str
    score: float
    status: str
    queued: bool
    starred: bool
    last_status: str | None  # Stand der letzten Bewerbung, None = keine


def _in_view(view: str, j: ListRow, excluded: set[int]) -> bool:
    """Gehört die Stelle in diese Ansicht? Aussortiertes verlässt alle Arbeitslisten."""
    last = j.last_status
    if view == "all":
        return True
    if view == "dismissed":
        return j.id in excluded
    if view == "applied":
        return last in DONE_STATES
    if j.id in excluded:
        return False
    if view == "triage":  # zu sichten: weder gemerkt, vorgemerkt noch beworben
        return not (last is not None or j.queued or j.starred)
    if view == "starred":
        return j.starred
    if view == "queued":
        return j.queued
    return last not in DONE_STATES  # todo: offen, ohne abgeschlossene Bewerbung


def host_name(header: str) -> str:
    """Host-Header ohne Port: „127.0.0.1:8765“ → „127.0.0.1“, „[::1]:8765“ und „[::1]“ → „[::1]“."""
    header = header.strip().lower()
    if header.startswith("["):
        return header[: header.find("]") + 1]
    return header.partition(":")[0]


def waiting_for_you(session: Any) -> dict[int, str]:
    """Bewerbungen mit offener Rückfrage: Der Lauf steht technisch auf „running“, wartet aber auf dich –
    Freigabe vor dem Absenden (needs_review) oder Antworten/Übergabe (needs_input)."""
    waiting: dict[int, str] = {}
    for app_id, kind in session.execute(
        select(Prompt.application_id, Prompt.kind).where(Prompt.status == "open")
    ):
        if kind == "confirm" or app_id not in waiting:
            waiting[app_id] = "needs_review" if kind == "confirm" else "needs_input"
    return waiting


def app_summary(a: Application, waiting: dict[int, str] | None = None) -> dict[str, Any]:
    return {
        "id": a.id,
        "job_id": a.job_id,
        "company": a.job.company,
        "title": a.job.title,
        "job_url": a.job.url,
        "status": (waiting or {}).get(a.id, a.status),
        "mode": a.mode,
        "origin": a.origin,
        "started_at": _iso(a.started_at),
        "finished_at": _iso(a.finished_at),
        "submitted_at": _iso(a.submitted_at),
        "error": a.error,
        "confirmation": a.confirmation,
        "notes": a.notes,
        "follow_up_at": _iso(a.follow_up_at),
        "open_questions": len(a.open_questions or []),
    }


def prompt_json(p: Prompt) -> dict[str, Any]:
    return {
        "id": p.id,
        "kind": p.kind,
        "application_id": p.application_id,
        "payload": p.payload,
        "created_at": _iso(p.created_at),
    }


def profile_json(profile: Profile) -> dict[str, Any]:
    data = profile.model_dump(mode="json")
    data["work"] = {k: ("" if v == TODO else v) for k, v in data["work"].items()}
    return data


# --------------------------------------------------------------------------- Request-Modelle
# Unbekannte Felder sind ein Fehler (extra="forbid"), Texte und Listen haben Obergrenzen.

Text: Any = Field(default="", max_length=MAX_TEXT)
Ids: Any = Field(default_factory=list, max_length=5_000)


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class JobPatch(_In):
    queued: bool | None = None
    starred: bool | None = None
    notes: str | None = Field(default=None, max_length=MAX_TEXT)


class JobStatus(_In):
    status: str = Field(max_length=20)
    note: str = Text


class BulkAction(_In):
    ids: list[int] = Ids
    action: str = Field(max_length=20)  # queue | unqueue | star | unstar | exclude


class ApplyRequest(_In):
    job_ids: list[int] = Ids
    mode: str | None = Field(default=None, max_length=20)
    max: int | None = Field(default=None, ge=1, le=500)
    force: bool = False


class AppPatch(_In):
    status: str | None = Field(default=None, max_length=20)
    notes: str | None = Field(default=None, max_length=MAX_TEXT)
    follow_up_at: datetime | None = None
    clear_follow_up: bool = False


class PromptAnswer(_In):
    answers: dict[str, str] = Field(default_factory=dict, max_length=200)
    skip: bool = False
    decision: str = Field(default="", max_length=20)
    done: bool = False
    abort: bool = False

    @field_validator("answers")
    @classmethod
    def _short_answers(cls, value: dict[str, str]) -> dict[str, str]:
        if any(len(k) > 200 or len(v) > MAX_TEXT for k, v in value.items()):
            raise ValueError("Antwort zu lang")
        return value


class AnswerIn(_In):
    question: str = Field(min_length=1, max_length=2_000)
    answer: str = Field(max_length=MAX_TEXT)


class ExclusionIn(_In):
    kind: str = Field(max_length=20)
    value: str = Field(max_length=500)
    reason: str = Field(default="", max_length=500)


class PresetRequest(_In):
    presets: list[str] = Field(default_factory=lambda: ["cloud"], max_length=50)
    cities: list[str] = Field(default_factory=lambda: ["berlin"], max_length=50)
    remote: bool = True
    exclude_leadership: bool = True


class UrlIn(_In):
    url: str = Field(max_length=2_000)


class InboxAction(_In):
    action: str = Field(max_length=20)  # apply | dismiss


class AppAnswers(_In):
    answers: dict[str, str] = Field(max_length=200)
    requeue: bool = True


def _web_or_empty(value: str) -> str:
    value = value.strip()
    if value and not value.lower().startswith(tuple(f"{s}://" for s in WEB_SCHEMES)):
        raise ValueError("nur http(s)-Adressen")
    return value


class SettingsUpdate(_In):
    """Was das Dashboard an den Einstellungen ändern darf (``EDITABLE_SETTINGS``) – mit Wertebereichen. Modellnamen
    und Effort landen als Argumente beim claude-Aufruf, der Postfach-Ordner im IMAP-Befehl."""

    llm_model: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._\-\[\]]{1,80}$")
    llm_model_fast: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._\-\[\]]{1,80}$")
    claude_parallel: int | None = Field(default=None, ge=1, le=8)
    claude_effort: Literal["", "low", "medium", "high", "xhigh", "max"] | None = None
    apply_mode: ApplyMode | None = None
    headless: bool | None = None
    vision: Literal["auto", "always", "never"] | None = None
    autofill: bool | None = None
    max_steps_per_application: int | None = Field(default=None, ge=1, le=60)
    autopilot_enabled: bool | None = None
    autopilot_days: list[int] | None = Field(default=None, max_length=7)
    autopilot_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    autopilot_apply: bool | None = None
    autopilot_apply_max: int | None = Field(default=None, ge=0, le=50)
    autopilot_apply_mode: ApplyMode | None = None
    notify_desktop: bool | None = None
    notify_ntfy_url: str | None = Field(default=None, max_length=2_000)
    notify_webhook_url: str | None = Field(default=None, max_length=2_000)
    follow_up_days: int | None = Field(default=None, ge=1, le=365)
    inbox_enabled: bool | None = None
    inbox_host: str | None = Field(default=None, pattern=r"^[A-Za-z0-9.\-]{0,253}$")
    inbox_port: int | None = Field(default=None, ge=1, le=65535)
    inbox_user: str | None = Field(default=None, max_length=320)
    inbox_password: str | None = Field(default=None, max_length=1_000)
    inbox_folder: str | None = Field(default=None, min_length=1, max_length=200)
    inbox_interval_min: int | None = Field(default=None, ge=5, le=1440)
    inbox_lookback_days: int | None = Field(default=None, ge=1, le=365)
    setup_completed: bool | None = None
    extension_portals: bool | None = None
    extension_portal_daily_limit: int | None = Field(default=None, ge=0, le=100)

    @field_validator("notify_ntfy_url", "notify_webhook_url")
    @classmethod
    def _web_urls(cls, value: str | None) -> str | None:
        return _web_or_empty(value) if value is not None else None

    @field_validator("autopilot_days")
    @classmethod
    def _weekdays(cls, value: list[int] | None) -> list[int] | None:
        if value is not None and any(not 0 <= d <= 6 for d in value):
            raise ValueError("Wochentage 0 (Montag) bis 6")
        return value

    @field_validator("inbox_folder")
    @classmethod
    def _imap_folder(cls, value: str | None) -> str | None:
        # Der Name steht in Anführungszeichen im IMAP-Befehl: kein " oder \, keine Steuerzeichen (CR/LF)
        if value is not None and (any(c in value for c in '"\\') or not value.isprintable()):
            raise ValueError("Ordnername ohne Anführungszeichen, Backslash und Steuerzeichen")
        return value


def bounded(value: Any, depth: int = 0) -> None:
    """Texte, Listen und Verschachtelung eines JSON-Körpers begrenzen (Profil und Suche haben freie Struktur)."""
    if depth > MAX_DEPTH:
        raise Problem(413, "api.too_large", "Zu tief verschachtelt")
    if isinstance(value, str):
        if len(value) > MAX_TEXT:
            raise Problem(413, "api.too_large", f"Text länger als {MAX_TEXT} Zeichen")
    elif isinstance(value, dict | list):
        if len(value) > MAX_ITEMS:
            raise Problem(413, "api.too_large", f"Mehr als {MAX_ITEMS} Einträge")
        for item in value.values() if isinstance(value, dict) else value:
            bounded(item, depth + 1)


def safe_filename(raw: str | None, default: str = "dokument.pdf") -> str:
    """Dateiname aus einem Upload: nur der letzte Teil, harmlose Zeichen (kein „:“ für alternative Datenströme unter
    Windows), keine führenden/abschließenden Punkte, keine reservierten Windows-Namen (CON, NUL, COM1 …)."""
    name = re.sub(r"[^\w.\- ]", "_", Path((raw or "").replace("\\", "/")).name).strip(" .")
    stem, dot, suffix = name.rpartition(".")
    if not dot:
        stem, suffix = name, ""
    if stem.split(".")[0].upper() in WINDOWS_RESERVED:
        stem = f"_{stem}"
    name = f"{stem[:120]}.{suffix[:10]}" if suffix else stem[:120]
    return name or default


# --------------------------------------------------------------------------- App


class Context:
    """Geteilter Zustand des Servers. Profil und Suche werden bei jedem Zugriff frisch geladen."""

    def __init__(self, runtime: Runtime) -> None:
        self.settings: Settings = runtime.settings
        self._initial = runtime
        self.runner = Runner(self.settings)
        self.browser_installer = BrowserInstaller()
        self.crawl: dict[str, Any] = {"running": False, "last": None, "started_at": None}
        self.last_prompt_notified = 0
        self.scheduler = Scheduler(self.run_autopilot, lambda: self.settings)
        self.autopilot_running = False
        self.tasks: set[asyncio.Task[Any]] = set()
        self.crawl_idle = asyncio.Event()
        self._llm: tuple[Settings, Any] | None = None
        self.crawl_idle.set()
        self.inbox_running = False
        self.tailoring: set[int] = (
            set()
        )  # Stellen, für die gerade ein Lebenslauf entsteht (ein Claude-Lauf je Stelle)
        self.inbox_checked_at: datetime | None = None
        self.inbox_error = ""
        # Zähler „zu sichten“ (Ausschlussregeln über Tausende Stellen) – neu berechnet, sobald jemand schreibt
        self.changes = ChangeCounter(self.settings.db_path)
        self.to_review: tuple[int, int] | None = None  # (data_version, Anzahl)

    @property
    def db(self) -> Path:
        return self.settings.db_path

    def llm(self) -> Any:
        """Claude Code einmal pro Einstellungsstand suchen – die Browser-Erweiterung fragt bei jedem Formularschritt."""
        if self._llm is None or self._llm[0] is not self.settings:
            self._llm = (self.settings, self.runtime().llm())
        return self._llm[1]

    def runtime(self) -> Runtime:
        """Stand von der Platte; solange Profil/Suche noch nicht gespeichert sind, gilt der Startzustand."""
        rt = Runtime.load(self.settings)
        if not self.settings.profile_path.exists():
            rt.profile = self._initial.profile
        if not self.settings.search_path.exists():
            rt.config = self._initial.config
        return rt

    async def notify(self, title: str, message: str, url: str = "") -> None:
        try:
            await notify(self.settings, title, message, url=url)
        except Exception:
            log.exception("Benachrichtigung fehlgeschlagen")

    async def start_crawl(self, *, queue_count: int = 0) -> bool:
        if self.crawl["running"]:
            return False
        ensure_not_demo(self.settings, "Crawlen")
        self.crawl.update(running=True, started_at=_iso(utcnow()))
        self.crawl_idle.clear()

        async def job() -> None:
            try:
                summary = await crawl_and_queue(self.runtime(), queue_count=queue_count)
                self.crawl["last"] = summary
                if summary["new"]:
                    await self.notify(
                        "jobslop: neue Stellen", f"{summary['new']} neue passende Stellen gefunden"
                    )
            except Exception as exc:
                log.exception("Crawl fehlgeschlagen")
                self.crawl["last"] = {"error": str(exc)}
                record(
                    self.settings,
                    "crawl",
                    f"Crawl fehlgeschlagen: {exc}",
                    code="crawl.failed",
                    error=str(exc),
                )
            finally:
                self.crawl["running"] = False
                self.crawl_idle.set()

        self.spawn(job())
        return True

    def spawn(self, coro: Any) -> None:
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def run_autopilot(self) -> None:
        if self.autopilot_running:
            return
        self.autopilot_running = True
        s = self.settings
        record(s, "autopilot", "Autopilot gestartet", code="autopilot.started")
        try:
            await self.crawl_idle.wait()
            self.crawl.update(running=True, started_at=_iso(utcnow()))
            self.crawl_idle.clear()
            try:
                count = s.autopilot_apply_max if s.autopilot_apply else 0
                summary = await crawl_and_queue(self.runtime(), queue_count=count)
                self.crawl["last"] = summary
            finally:
                self.crawl["running"] = False
                self.crawl_idle.set()
            started = False
            if s.autopilot_apply and summary["queued"] and not self.runner.active:
                started = self.runner.start(
                    mode=s.autopilot_apply_mode, max_count=s.autopilot_apply_max, label="Autopilot"
                )
            text = f"{summary['new']} neue Stellen, {len(summary['queued'])} eingereiht" + (
                " – Bewerbungen laufen" if started else ""
            )
            record(
                s,
                "autopilot",
                f"Autopilot: {text}",
                summary,
                code="autopilot.done",
                new=summary["new"],
                queued=len(summary["queued"]),
            )
            await self.notify("jobslop Autopilot", text)
        except Exception as exc:
            # Der Lauf startet auch per Knopf als losgelöste Task – ohne Eintrag bliebe ein Fehler unsichtbar.
            log.exception("Autopilot-Lauf fehlgeschlagen")
            error = f"{type(exc).__name__}: {exc}"[:300]
            self.crawl["last"] = {"error": error}
            record(s, "autopilot", f"Autopilot fehlgeschlagen: {error}", code="autopilot.failed", error=error)
            await self.notify("jobslop Autopilot", f"Fehlgeschlagen: {error}")
        finally:
            self.autopilot_running = False

    async def check_inbox(self) -> dict[str, int]:
        """Postfach jetzt prüfen (Knopf oder Zeitplan). Fehler gehen an den Aufrufer."""
        if self.inbox_running:
            return {}
        self.inbox_running, self.inbox_checked_at = True, utcnow()
        try:
            counts = await check_inbox(self.settings, self.llm())
        finally:
            self.inbox_running = False
        if counts["suggested"] or counts["logged"]:
            record(
                self.settings,
                "inbox",
                f"Postfach: {counts['suggested']} Antwort(en) zum Bestätigen, {counts['logged']} Eingangsbestätigung(en)",
                code="inbox.checked",
                suggested=counts["suggested"],
                logged=counts["logged"],
            )
        if counts["suggested"]:
            await self.notify("jobslop: Antwort auf eine Bewerbung", "Unter „Heute“ bestätigen")
        return counts

    def inbox_due(self) -> bool:
        s = self.settings
        if not s.inbox_enabled or s.demo or self.inbox_running:
            return False
        last = self.inbox_checked_at
        return last is None or utcnow() - last >= timedelta(minutes=max(5, s.inbox_interval_min))

    async def _inbox_tick(self) -> None:
        try:
            await self.check_inbox()
            self.inbox_error = ""
        except (
            Exception
        ) as exc:  # Postfach weg, Passwort falsch, Claude-Limit: protokollieren, nicht abbrechen
            error = f"{type(exc).__name__}: {exc}"[:300] if not isinstance(exc, InboxError) else str(exc)
            if error != self.inbox_error:  # gleicher Fehler alle 30 Minuten: nur einmal ins Protokoll
                log.warning("Postfach-Prüfung fehlgeschlagen: %s", error)
                record(
                    self.settings,
                    "inbox",
                    f"Postfach-Prüfung fehlgeschlagen: {error}",
                    code="inbox.failed",
                    error=error,
                )
            self.inbox_error = error

    async def watch(self) -> None:
        """Hintergrund: Ende von Bewerbungsläufen und neue Rückfragen melden."""
        was_active = False
        with session_scope(self.db) as s:
            self.last_prompt_notified = s.scalar(select(func.max(Prompt.id))) or 0
        while True:
            try:
                active = self.runner.active
                if was_active and not active:
                    await self._run_finished()
                was_active = active
                if self.inbox_due():
                    self.spawn(self._inbox_tick())
                with session_scope(self.db) as s:
                    new = list(
                        s.execute(
                            select(Prompt).where(
                                Prompt.status == "open", Prompt.id > self.last_prompt_notified
                            )
                        ).scalars()
                    )
                    for p in new:
                        self.last_prompt_notified = max(self.last_prompt_notified, p.id)
                        title = p.payload.get("title", "")
                        what = {"questions": "hat Rückfragen", "confirm": "wartet auf Freigabe"}.get(
                            p.kind, "braucht dich im Browser"
                        )
                        await self.notify("jobslop braucht dich", f"{title} {what}")
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Hintergrundprüfung fehlgeschlagen")
            await asyncio.sleep(3)

    async def _run_finished(self) -> None:
        since = self.runner.started_at or utcnow()
        with session_scope(self.db) as s:
            # Gestoppt oder abgestürzt: Was der Prozess nicht mehr abschließen konnte, steht sonst für immer auf
            # „läuft“ (und sperrt die Stelle), seine Rückfragen beantwortet niemand mehr.
            run_apps = select(Application.id).where(Application.started_at >= since)
            for a in s.scalars(
                select(Application).where(
                    Application.id.in_(run_apps),
                    Application.status == "running",
                    Application.origin != "extension",
                )
            ):
                a.status, a.finished_at = "failed", utcnow()
                a.error = a.error or "Lauf beendet, bevor die Bewerbung fertig war"
            for p in s.scalars(
                select(Prompt).where(Prompt.status == "open", Prompt.application_id.in_(run_apps))
            ):
                p.status = "expired"
            rows = (
                s.execute(select(Application.status).where(Application.started_at >= since)).scalars().all()
            )
        counts = Counter(rows)
        text = (
            ", ".join(f"{n}× {status}" for status, n in counts.most_common()) or "keine Bewerbung gestartet"
        )
        record(
            self.settings,
            "run",
            f"Bewerbungslauf beendet: {text}",
            dict(counts),
            code="run.finished",
            counts=dict(counts),
        )
        await self.notify("jobslop: Lauf beendet", text)
        code = self.runner.returncode
        if code not in (0, None) and not self.runner.stopped:
            lines = [line for line in self.runner.tail(40).splitlines() if line.strip()]
            error = " ".join(lines[-3:])[-300:] or f"Exit {code}"
            record(
                self.settings,
                "run",
                f"Bewerbungslauf abgebrochen (Exit {code}): {error}",
                code="run.crashed",
                exit=code,
                error=error,
            )
            await self.notify("jobslop: Lauf abgebrochen", error)


class _TooLarge(Exception):
    pass


class BodyLimit:
    """Anfragekörper begrenzen, bevor jemand sie liest: per Content-Length sofort, bei gestückelter Übertragung
    während des Lesens. JSON bis ``MAX_BODY``, Dokument-Uploads bis ``MAX_UPLOAD`` (plus Formular-Rahmen)."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        # Abrufe ohne Körper (Status-Polling alle 3 s, Listen) laufen ohne Hülle durch: Starlette liest bei ihnen
        # keinen Körper, und jede Hülle pro Anfrage kostet bei großen Datenbanken messbar (mehr Müllsammlung)
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return
        limit = MAX_UPLOAD + 64 * 1024 if scope["path"] in UPLOAD_PATHS else MAX_BODY
        length = dict(scope["headers"]).get(b"content-length", b"0")
        if not length.isdigit() or int(length) > limit:
            await self._reject(send)
            return
        received, started = 0, False

        async def limited_receive() -> Any:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _TooLarge
            return message

        async def tracking_send(message: Any) -> None:
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _TooLarge:
            if not started:
                await self._reject(send)

    @staticmethod
    async def _reject(send: Any) -> None:
        response = JSONResponse({"detail": "Anfrage zu groß", "code": "api.too_large", "params": {}}, 413)
        await send({"type": "http.response.start", "status": 413, "headers": response.raw_headers})
        await send({"type": "http.response.body", "body": response.body})


def create_app(runtime: Runtime) -> FastAPI:
    ctx = Context(runtime)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        watcher = asyncio.create_task(ctx.watch())
        ctx.scheduler.start()
        try:
            yield
        finally:
            watcher.cancel()
            await ctx.scheduler.stop()
            ctx.changes.close()

    app = FastAPI(
        title="jobslop",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
        # FastAPIs OpenTelemetry-Anbindung aus: auch wenn die Umgebung Exporter einrichtet
        # (FASTAPI_OTEL_AUTO_CONFIGURE, OTEL_*), gehen keine Spans, Exception-Texte oder Routen mit Personendaten raus
        telemetry={
            "tracing": False,
            "metrics": False,
            "logs": False,
            "operation_spans": False,
            "auto_configure": False,
        },
    )
    app.state.ctx = ctx
    app.add_middleware(BodyLimit)

    @app.exception_handler(DemoModeError)
    async def demo_mode(_request: Request, exc: DemoModeError) -> JSONResponse:
        return JSONResponse({"detail": str(exc), "code": "api.demo"}, status_code=409)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        body: dict[str, Any] = {"detail": exc.detail}
        if isinstance(exc, Problem):
            body |= {"code": exc.code, "params": exc.params}
        elif exc.status_code == 404:
            body["code"] = "api.not_found"
        return JSONResponse(body, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(LLMLimitReached)
    async def llm_limit(_request: Request, exc: LLMLimitReached) -> JSONResponse:
        return JSONResponse({"detail": str(exc), "code": "api.llm_limit"}, status_code=429)

    @app.exception_handler(LLMUnavailable)
    async def llm_unavailable(_request: Request, exc: LLMUnavailable) -> JSONResponse:
        return JSONResponse({"detail": str(exc), "code": "api.llm_unavailable"}, status_code=503)

    @app.exception_handler(Exception)
    async def internal_error(_request: Request, exc: Exception) -> JSONResponse:
        # Den Traceback schreibt uvicorn; das Dashboard bekommt JSON statt „Internal Server Error“ als Text – aber
        # nur die Art des Fehlers: Exception-Texte enthalten Pfade, Werte aus dem Profil oder Teile fremder Seiten.
        error = type(exc).__name__
        detail = f"Interner Fehler ({error}) – Details im Server-Protokoll"
        return JSONResponse({"detail": detail, "code": "api.internal", "params": {"error": error}}, 500)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        host = host_name(request.headers.get("host") or "")
        if host not in LOCAL_HOSTS and host != ctx.settings.dashboard_host:
            return JSONResponse({"detail": "Nur lokal erreichbar"}, status_code=403)
        if (
            request.url.path.startswith("/api/")
            and request.method not in ("GET", "HEAD", "OPTIONS")
            and request.headers.get("x-jobslop") != "1"
        ):
            return JSONResponse({"detail": "Fehlender X-Jobslop-Header"}, status_code=403)
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Content-Security-Policy"] = CSP
        return response

    # ------------------------------------------------------------------ Status & System
    @app.get("/api/status")
    def status() -> dict[str, Any]:
        s = ctx.settings
        # vor der ersten Abfrage lesen: Ein Commit danach ist im Ergebnis enthalten oder löst beim nächsten Abruf
        # eine Neuberechnung aus – ein veralteter Wert kann nie unter einer neueren Version landen
        version = ctx.changes.value()
        with session_scope(ctx.db) as db:
            prompts = [
                prompt_json(p)
                for p in db.execute(
                    select(Prompt).where(Prompt.status == "open").order_by(Prompt.id)
                ).scalars()
            ]
            open_jobs = db.scalar(select(func.count(Job.id)).where(Job.status == "open")) or 0
            queued = db.scalar(select(func.count(Job.id)).where(Job.queued)) or 0
            waiting_ids = set(
                db.scalars(
                    select(Application.id).where(Application.status.in_(["needs_input", "needs_review"]))
                )
            )
            attention = len(waiting_ids | set(waiting_for_you(db)))
            replies = [
                inbox_json(m)
                for m in db.scalars(
                    select(InboxMessage)
                    .where(InboxMessage.status == "open")
                    .order_by(InboxMessage.received_at)
                    .options(WITH_APP_JOB)
                )
            ]
            # Zähler für die Navigation: Stellen zu sichten (wie die Standardansicht, ohne Stretch-Level) …
            # Der Abruf läuft alle paar Sekunden; neu gezählt wird nur, wenn seitdem jemand geschrieben hat.
            if ctx.to_review is not None and ctx.to_review[0] == version:
                to_review = ctx.to_review[1]
            else:
                undecided = db.execute(
                    select(Job.id, Job.company, Job.title, Job.url)
                    .where(Job.status == "open", ~Job.queued, ~Job.starred, Job.level != "S")
                    .where(~Job.applications.any())
                ).all()
                to_review = len(undecided) - len(excluded_job_ids(db, undecided))
                ctx.to_review = (version, to_review)
            # … und fällige Nachfass-Termine (letzte Bewerbung je Stelle, wie in der Pipeline)
            latest = select(func.max(Application.id)).group_by(Application.job_id)
            follow_ups_due = (
                db.scalar(
                    select(func.count(Application.id)).where(
                        Application.id.in_(latest),
                        Application.follow_up_at <= utcnow(),
                        Application.status.in_(["submitted", "manual", "interview"]),
                    )
                )
                or 0
            )
        runner = ctx.runner.state(lines=0)
        runner.pop("log", None)
        nxt = next_run(s)
        return {
            "version": __version__,
            "setup_completed": s.setup_completed,
            "demo": s.demo,
            "prompts": prompts,
            "runner": runner,
            "crawl": ctx.crawl,
            "autopilot": {
                "enabled": s.autopilot_enabled,
                "running": ctx.autopilot_running,
                "next_run": nxt.isoformat() if nxt else None,
            },
            "counts": {
                "open_jobs": open_jobs,
                "queued": queued,
                "attention": attention,
                "to_review": to_review,
                "follow_ups_due": follow_ups_due,
                "replies": len(replies),
            },
            "replies": replies,
            "inbox": {
                "enabled": s.inbox_enabled,
                "error": ctx.inbox_error,
                "checked_at": _iso(ctx.inbox_checked_at),
            },
            "notify_desktop": s.notify_desktop,
        }

    @app.get("/api/system")
    async def system(refresh: bool = False) -> dict[str, Any]:
        rt = ctx.runtime()
        report = await system_report(ctx.settings, rt.profile, refresh=refresh)
        report["browser_install"] = ctx.browser_installer.state()
        report["version"] = __version__
        return report

    @app.post("/api/system/claude-login")
    def claude_login() -> dict[str, Any]:
        return open_claude_login(ctx.settings)

    @app.post("/api/system/claude-install")
    def claude_install() -> dict[str, Any]:
        return open_claude_install()

    @app.post("/api/system/browser-install")
    async def browser_install() -> dict[str, Any]:
        await ctx.browser_installer.start()
        return ctx.browser_installer.state()

    @app.post("/api/system/open-folder")
    def open_home() -> dict[str, Any]:
        return {"opened": open_folder(ctx.settings.home)}

    # ------------------------------------------------------------------ Browser-Erweiterung
    # Einrichten/Anzeigen gehört zum Dashboard; alles unter /api/assist/ ruft die Erweiterung mit ihrem Token auf.
    def assist_info() -> dict[str, Any]:
        installed = assist.installed_version(ctx.settings)
        return {
            "path": str(assist.extension_dir(ctx.settings)),
            "installed": bool(installed),
            "outdated": bool(installed) and installed != __version__,
            "version": __version__,
        } | assist.status(ctx.settings)

    @app.get("/api/extension")
    def extension_info() -> dict[str, Any]:
        return assist_info()

    @app.post("/api/extension/install")
    def extension_install(request: Request) -> dict[str, Any]:
        assist.install(ctx.settings, server=str(request.base_url))
        record(ctx.settings, "setup", "Browser-Erweiterung eingerichtet", code="extension.installed")
        return assist_info()

    @app.post("/api/extension/open-folder")
    def extension_open_folder() -> dict[str, Any]:
        path = assist.extension_dir(ctx.settings)
        return {"opened": path.is_dir() and open_folder(path)}

    def paired(request: Request) -> None:
        if not assist.token_ok(ctx.settings, request.headers.get("x-jobslop-token", "")):
            raise HTTPException(
                401,
                "Erweiterung nicht gekoppelt – in jobslop unter Einstellungen → Browser-Erweiterung neu einrichten",
            )

    @app.get("/api/assist/status")
    def assist_status(request: Request) -> dict[str, Any]:
        paired(request)
        return assist.status(ctx.settings)

    @app.post("/api/assist/step")
    async def assist_step(request: Request, body: assist.StepIn) -> dict[str, Any]:
        paired(request)
        return await assist.step(ctx.runtime(), body, ctx.llm())

    @app.post("/api/assist/result")
    def assist_result(request: Request, body: assist.ResultIn) -> dict[str, Any]:
        paired(request)
        assist.record_results(ctx.settings, body)
        return {"ok": True}

    @app.post("/api/assist/answers")
    def assist_answers(request: Request, body: assist.AnswersIn) -> dict[str, Any]:
        paired(request)
        return {"saved": assist.save_answers(ctx.settings, body)}

    @app.post("/api/assist/finish")
    async def assist_finish(request: Request, body: assist.FinishIn) -> dict[str, Any]:
        paired(request)
        assist.finish(ctx.settings, body)
        if body.status == "submitted":
            await ctx.notify(
                "jobslop: Bewerbung abgeschickt", body.message[:200] or "über die Browser-Erweiterung"
            )
        return {"ok": True}

    @app.get("/api/assist/file")
    def assist_file(request: Request, application_id: int, value: str, index: int = 0) -> FileResponse:
        paired(request)
        path = assist.upload_file(ctx.runtime(), application_id, value, index)
        if path is None:
            raise HTTPException(404, "Datei nicht gefunden")
        return FileResponse(path, filename=path.name)

    # ------------------------------------------------------------------ Profil & Dokumente
    @app.get("/api/profile")
    def get_profile() -> dict[str, Any]:
        rt = ctx.runtime()
        cv = rt.profile.cv_path(ctx.settings.profile_path.parent)
        cv_en = rt.profile.cv_path(ctx.settings.profile_path.parent, "en")
        return {
            "profile": profile_json(rt.profile),
            "missing": rt.profile.missing_fields(),
            "documents": {
                "cv": {"name": cv.name, "exists": cv.exists()} if cv else None,
                "cv_en": {"name": cv_en.name, "exists": cv_en.exists()}
                if cv_en and rt.profile.documents.cv_en
                else None,
            },
        }

    def documents_inside_home(profile: Profile) -> None:
        """Dokumente, die über die API neu gesetzt werden, müssen im jobslop-Ordner liegen (Uploads landen in
        documents/). Sonst könnte ein Aufrufer ~/.ssh/id_rsa als Lebenslauf eintragen – Engine und Erweiterung
        lüden die Datei auf eine Bewerbungsseite hoch. Was schon im Profil steht (von dir in profile.yaml), bleibt."""
        base = ctx.settings.profile_path.parent
        current = ctx.runtime().profile.documents
        known = {current.cv, current.cv_en, current.cover_letter, *current.certificates}
        docs = profile.documents
        root = os.path.realpath(ctx.settings.home)
        for value in (docs.cv, docs.cv_en, docs.cover_letter, *docs.certificates):
            if value in known or not (path := docs.resolve(value, base)):
                continue
            if not os.path.realpath(path).startswith(root + os.sep):
                raise Problem(
                    422, "api.document_outside", "Dokumente nur aus dem jobslop-Ordner", value=value
                )

    @app.put("/api/profile")
    def put_profile(body: dict[str, Any]) -> dict[str, Any]:
        bounded(body)
        try:
            profile = Profile.model_validate(body, extra="forbid")
        except ValidationError as exc:
            raise HTTPException(
                422, exc.errors(include_url=False, include_context=False, include_input=False)
            ) from exc
        documents_inside_home(profile)
        for name, default in Work():
            if default == TODO and getattr(profile.work, name) in ("", None):
                setattr(profile.work, name, TODO)  # leer = unbekannt, der Agent fragt nach
        ctx.settings.home.mkdir(parents=True, exist_ok=True)
        profile.save(ctx.settings.profile_path)
        return get_profile()

    @app.post("/api/profile/document")
    async def upload_document(
        file: UploadFile = File(...),
        kind: str = Form("cv"),
        import_cv: bool = Form(False),
    ) -> dict[str, Any]:
        if kind not in ("cv", "cv_en", "certificate"):
            raise HTTPException(400, "Unbekannte Dokumentart")
        name = safe_filename(file.filename)
        if not name.lower().endswith(".pdf"):
            raise Problem(400, "api.pdf_only", "Bitte eine PDF-Datei hochladen")
        ctx.settings.ensure_dirs()
        target = ctx.settings.documents_dir / name
        # Stückweise in eine Zwischendatei: nie mehr als 15 MB, und erst eine vollständige, echte PDF ersetzt das Ziel
        partial = target.with_name(f".{name}.upload")
        size = 0
        try:
            with partial.open("wb") as out:
                while chunk := await file.read(64 * 1024):
                    if size == 0 and not chunk.startswith(b"%PDF-"):
                        raise Problem(400, "api.pdf_only", "Bitte eine PDF-Datei hochladen")
                    size += len(chunk)
                    if size > MAX_UPLOAD:
                        raise Problem(413, "api.too_large", "Datei ist größer als 15 MB")
                    out.write(chunk)
            if size == 0:
                raise Problem(400, "api.pdf_only", "Bitte eine PDF-Datei hochladen")
            os.replace(partial, target)
        finally:
            partial.unlink(missing_ok=True)
        rt = ctx.runtime()
        profile = rt.profile
        rel = f"documents/{name}"
        if kind == "cv":
            profile.documents.cv = rel
        elif kind == "cv_en":
            profile.documents.cv_en = rel
        elif rel not in profile.documents.certificates:
            profile.documents.certificates.append(rel)
        message = ""
        if import_cv and kind == "cv":
            from ..cvimport import import_cv as run_import
            from ..system import claude_status

            login = await asyncio.to_thread(claude_status, ctx.settings)
            llm = rt.llm() if login.ok else None
            if llm is None:
                message = "Claude ist noch nicht verbunden – Profil bitte von Hand ausfüllen"
            else:
                try:
                    profile = await run_import(llm, target, profile)
                    message = "Profil aus dem Lebenslauf übernommen"
                except Exception as exc:
                    log.exception("Lebenslauf-Import fehlgeschlagen")
                    message = f"Lebenslauf konnte nicht ausgelesen werden ({type(exc).__name__})"
        profile.save(ctx.settings.profile_path)
        return get_profile() | {"message": message}

    # ------------------------------------------------------------------ Suche & Einstellungen
    @app.get("/api/search")
    def get_search() -> dict[str, Any]:
        return ctx.runtime().config.model_dump(mode="json")

    @app.put("/api/search")
    def put_search(body: dict[str, Any]) -> dict[str, Any]:
        bounded(body)
        try:
            config = SearchConfig.model_validate(body, extra="forbid")
        except ValidationError as exc:
            raise HTTPException(
                422, exc.errors(include_url=False, include_context=False, include_input=False)
            ) from exc
        if not config.roles and not config.filters.include_titles:
            raise Problem(422, "api.roles_missing", "Mindestens eine Zielrolle angeben")
        config.save(ctx.settings.search_path)
        return config.model_dump(mode="json")

    @app.get("/api/presets")
    def presets() -> list[dict[str, Any]]:
        return presets_for_ui()

    @app.post("/api/search/preset")
    def preset_preview(body: PresetRequest) -> dict[str, Any]:
        config = search_config_from_preset(
            body.presets, cities=body.cities, remote=body.remote, exclude_leadership=body.exclude_leadership
        )
        return config.model_dump(mode="json")

    @app.get("/api/settings")
    def get_settings_api() -> dict[str, Any]:
        data = ctx.settings.model_dump(mode="json")
        out = {k: data[k] for k in sorted(EDITABLE_SETTINGS)} | {"home": str(ctx.settings.home)}
        # Das App-Passwort verlässt den Server nicht; leer zurückschicken heißt „unverändert“
        return out | {"inbox_password": "", "inbox_password_set": bool(ctx.settings.inbox_password)}

    @app.put("/api/settings")
    def put_settings(body: dict[str, Any]) -> dict[str, Any]:
        body = {k: v for k, v in body.items() if k not in ("home", "inbox_password_set")}
        if not body.get("inbox_password"):
            body.pop("inbox_password", None)
        try:
            changes = SettingsUpdate.model_validate(body).model_dump(exclude_unset=True)
            ctx.settings = save_settings(ctx.settings, changes)
        except ValidationError as exc:
            raise HTTPException(
                422, exc.errors(include_url=False, include_context=False, include_input=False)
            ) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        ctx.runner.settings = ctx.settings
        return get_settings_api()

    @app.post("/api/inbox/test")
    async def inbox_test() -> dict[str, Any]:
        try:
            count = await asyncio.to_thread(try_connection, ctx.settings)
        except InboxError as exc:
            raise Problem(502, "api.inbox_failed", str(exc), error=str(exc)) from exc
        return {"ok": True, "messages": count}

    @app.post("/api/inbox/check")
    async def inbox_check() -> dict[str, Any]:
        try:
            counts = await ctx.check_inbox()
        except InboxError as exc:
            ctx.inbox_error = str(exc)
            raise Problem(502, "api.inbox_failed", str(exc), error=str(exc)) from exc
        ctx.inbox_error = ""
        return counts

    @app.post("/api/inbox/{message_id}")
    def inbox_action(message_id: int, body: InboxAction) -> dict[str, Any]:
        """Vorschlag übernehmen (Status der Bewerbung setzen) oder verwerfen. Rückgabe enthält den vorigen
        Status, damit das Dashboard „Rückgängig“ anbieten kann."""
        with session_scope(ctx.db) as s:
            m = s.get(InboxMessage, message_id)
            if m is None or m.status != "open":
                raise Problem(409, "api.reply_closed", "Dieser Vorschlag ist schon erledigt")
            a = m.application
            previous = a.status
            if body.action == "apply":
                a.status = KIND_STATUS[m.kind]
                a.stage_changed_at = utcnow()
                if a.status in ("offer", "rejected"):
                    a.follow_up_at = None
                s.add(status_activity(a.job, a.status))
                m.status = "applied"
            elif body.action == "dismiss":
                m.status = "dismissed"
            else:
                raise HTTPException(400, "action muss apply oder dismiss sein")
            return {"application_id": a.id, "previous_status": previous, "status": a.status}

    @app.post("/api/notify/test")
    async def notify_test() -> dict[str, Any]:
        sent = await notify(ctx.settings, "jobslop", "Testnachricht – Benachrichtigungen funktionieren.")
        return {"sent": sent}

    @app.post("/api/setup/complete")
    async def setup_complete(start_crawl: bool = True) -> dict[str, Any]:
        ctx.settings = save_settings(ctx.settings, {"setup_completed": True})
        ctx.runner.settings = ctx.settings
        record(ctx.settings, "setup", "Einrichtung abgeschlossen", code="setup.done")
        started = await ctx.start_crawl() if start_crawl and not ctx.settings.demo else False
        return {"ok": True, "crawl_started": started}

    # ------------------------------------------------------------------ Stellen
    @app.get("/api/jobs")
    def jobs(
        q: str = "",
        category: str = "",
        where: str = "",
        level: str = "",
        status: str = "open",
        view: str = "todo",
        min_fit: int = 0,
        sort: str = "score",
        limit: int = Query(100, ge=1, le=1_000),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        with session_scope(ctx.db) as s:
            # Ansichten und Zähler brauchen jede Stelle, die Liste nur eine Seite: schlichte Zeilen für alle, ORM-Objekte
            # nur für die Seite. status/queued/starred und first_seen liegen in der Tabelle hinter der Beschreibung
            # (Überlaufseiten) – sie kommen aus ihren Indizes, die SQLite ohne die Tabelle liest.
            stmt = select(Job.id, Job.company, Job.title, Job.url, Job.category, Job.level, Job.score)
            if where in ("B", "R"):
                stmt = stmt.where(Job.where.in_([where, "BR"]))
            if level and level != "noS":
                stmt = stmt.where(Job.level.in_(level.split(",")))
            if min_fit:
                stmt = stmt.where(Job.fit >= min_fit)
            if q:
                like = f"%{q}%"
                stmt = stmt.where(
                    Job.title.ilike(like)
                    | Job.company.ilike(like)
                    | Job.location.ilike(like)
                    | Job.notes.ilike(like)
                )
            listed = s.execute(stmt).all()
            # Erst danach lesen: Die Abfragen sehen keinen gemeinsamen Stand, und eine Stelle, die ein Crawl gerade
            # eingefügt hat, braucht hier ihren Zustand (Stellen werden nie gelöscht).
            state = {r[0]: r[1:] for r in s.execute(select(Job.id, Job.status, Job.queued, Job.starred))}
            last_status: dict[int, str] = {}
            for job_id, app_status in s.execute(
                select(Application.job_id, Application.status).order_by(Application.id)
            ):
                last_status[job_id] = app_status  # die letzte Bewerbung je Stelle zählt
            rows = [ListRow(*r, *state[r[0]], last_status.get(r[0])) for r in listed]
            if sort == "new":
                seen = dict(s.execute(select(Job.id, Job.first_seen)).all())
                rows.sort(key=lambda j: seen[j.id], reverse=True)
            elif sort == "company":
                rows.sort(key=lambda j: (j.company, -j.score))
            else:
                rows.sort(key=lambda j: (not j.starred, -j.score, j.company))
            excluded = excluded_job_ids(s, rows)
            cats = set(category.split(",")) if category else set()

            def shown(v: str, j: ListRow) -> bool:
                # „Ohne Stretch“ gilt beim Sichten. Was du schon entschieden hast (vorgemerkt, gemerkt, aussortiert),
                # bleibt sichtbar – auch wenn Claude die Stelle später als Stretch einstuft.
                return _in_view(v, j, excluded) and not (
                    level == "noS" and j.level == "S" and v in ("triage", "all")
                )

            # Zähler für die Reiter: offene Stellen, bei „Alle“ und „Aussortiert“ auch geschlossene
            counts = {
                v: sum(
                    1
                    for j in rows
                    if (not cats or j.category in cats)
                    and (v in ("all", "dismissed") or j.status == "open")
                    and shown(v, j)
                )
                for v in JOB_VIEWS
            }
            rows = [j for j in rows if (status == "all" or j.status == status) and shown(view, j)]
            facets = Counter(j.category for j in rows)  # vor dem Rollenfilter: das Menü zeigt alle Rollen
            if cats:
                rows = [j for j in rows if j.category in cats]
            total = len(rows)
            page = [j.id for j in rows[offset : offset + limit]]
            loaded: dict[int, Job] = {}
            for i in range(0, len(page), 500):  # SQLite begrenzt die Parameter pro Abfrage
                loaded |= {
                    j.id: j
                    for j in s.execute(
                        select(Job)
                        .where(Job.id.in_(page[i : i + 500]))
                        .options(defer(Job.description), selectinload(Job.applications))
                    ).scalars()
                }
            items = [job_summary(loaded[job_id], excluded=job_id in excluded) for job_id in page]
        return {"items": items, "total": total, "facets": {"category": dict(facets)}, "counts": counts}

    @app.post("/api/jobs")
    async def add_job(body: UrlIn) -> dict[str, Any]:
        from ..jobpage import add_fetched_job, fetch_job

        ensure_not_demo(ctx.settings, "Stelle per Link laden")
        rt = ctx.runtime()
        try:
            fetched = await fetch_job(
                body.url.strip(),
                llm=rt.llm(),
                fast_model=ctx.settings.llm_model_fast,
                allow_private=ctx.settings.allow_private_targets,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        job_id, created = add_fetched_job(ctx.db, rt.config, fetched)
        return {"id": job_id, "created": created, "via": fetched.via}

    @app.get("/api/jobs/{job_id}")
    def job_detail(job_id: int) -> dict[str, Any]:
        with session_scope(ctx.db) as s:
            j = s.get(Job, job_id)
            if j is None:
                raise HTTPException(404)
            config = ctx.runtime().config
            verdict = check_job(s, j, config.limits)
            parts = job_score_parts(j, config.role_names)
            if abs(rest := round(j.score - sum(p for _, p in parts), 2)) >= 0.1:
                parts.append(("other", rest))  # z. B. Import mit eigener Einordnung
            waiting = waiting_for_you(s)  # einmal, nicht pro Bewerbung
            return job_summary(j, excluded=bool(excluded_job_ids(s, [j]))) | {
                "description": j.description,
                "apply_url": j.apply_url,
                "alt_urls": j.alt_urls,
                "notes": j.notes,
                "enrichment": j.enrichment,
                "segment": j.segment,
                "language": j.language,
                "last_seen": _iso(j.last_seen),
                "verdict": {
                    "ok": verdict.ok,
                    "reason": verdict.reason,
                    "code": verdict.code,
                    "params": verdict.params,
                },
                "score_parts": [{"key": k, "points": p} for k, p in parts],
                "history": [
                    {"seen_at": _iso(sn.seen_at), "change": sn.change, "diff": sn.diff} for sn in j.snapshots
                ],
                "applications": [app_summary(a, waiting) for a in j.applications],
            }

    # ------------------------------------------------------------------ Lebenslauf je Stelle
    def tailored_json(job_id: int) -> dict[str, Any]:
        cached = cached_cv(ctx.settings.home, job_id)
        enabled = ctx.runtime().profile.documents.tailor_cv
        if cached is None:
            return {"enabled": enabled, "file": None, "url": None, "matched_keywords": []}
        pdf, meta = cached
        return {
            "enabled": enabled,
            "file": pdf.name,
            # Zeitstempel in der Adresse: nach „Neu erstellen“ zeigt der Browser nicht die alte Datei
            "url": f"/api/jobs/{job_id}/cv/file?v={int(pdf.stat().st_mtime)}",
            "matched_keywords": meta.get("matched_keywords", []),
        }

    @app.get("/api/jobs/{job_id}/cv")
    def job_cv(job_id: int) -> dict[str, Any]:
        return tailored_json(job_id)

    @app.post("/api/jobs/{job_id}/cv")
    async def job_cv_create(job_id: int) -> dict[str, Any]:
        """Lebenslauf für die Stelle (neu) erstellen – genau diese Datei lädt jobslop später hoch."""
        ensure_not_demo(ctx.settings, "Lebenslauf zuschneiden")
        if job_id in ctx.tailoring:  # Doppelklick: nicht zweimal Claude-Kontingent verbrauchen
            raise Problem(409, "api.cv_running", "Der Lebenslauf für diese Stelle entsteht gerade")
        ctx.tailoring.add(job_id)
        try:
            return await tailor_for(job_id)
        finally:
            ctx.tailoring.discard(job_id)

    async def tailor_for(job_id: int) -> dict[str, Any]:
        with session_scope(ctx.db) as s:
            j = s.get(Job, job_id)
            if j is None:
                raise HTTPException(404)
            job = JobContext.from_job(j)
        rt = ctx.runtime()
        files = Files.from_profile(rt.profile, ctx.settings.profile_path.parent)
        if files.cv is None or not files.cv.exists():
            raise Problem(409, "api.cv_missing", "Zuerst einen Lebenslauf hochladen")
        pdf, note = await ensure_tailored_cv(
            ctx.llm(),
            rt.profile,
            job,
            ctx.settings.home,
            ctx.settings.profile_path.parent,
            files,
            headless_pdf_context,
            force=True,
        )
        if pdf is None:
            raise Problem(422, "api.cv_rejected", note, reason=note)
        return tailored_json(job_id)

    @app.get("/api/jobs/{job_id}/cv/file")
    def job_cv_file(job_id: int) -> FileResponse:
        cached = cached_cv(ctx.settings.home, job_id)
        if cached is None:
            raise HTTPException(404)
        return FileResponse(cached[0], media_type="application/pdf", content_disposition_type="inline")

    @app.patch("/api/jobs/{job_id}")
    def job_patch(job_id: int, body: JobPatch) -> dict[str, Any]:
        with session_scope(ctx.db) as s:
            j = s.get(Job, job_id)
            if j is None:
                raise HTTPException(404)
            if body.queued is True:
                verdict = check_job(s, j, ctx.runtime().config.limits)
                if not verdict.ok:
                    raise Problem(409, verdict.code, verdict.reason, **verdict.params)
            for key, value in body.model_dump(exclude_none=True).items():
                setattr(j, key, value)
            return job_summary(j)

    @app.post("/api/jobs/{job_id}/status")
    def job_status(job_id: int, body: JobStatus) -> dict[str, Any]:
        if body.status not in MARK:
            raise HTTPException(400, "applied, interview, rejected oder offer")
        with session_scope(ctx.db) as s:
            j = s.get(Job, job_id)
            if j is None:
                raise HTTPException(404)
            last = j.applications[-1] if j.applications else None
            now = utcnow()
            if last and body.status != "applied" and last.status not in ("failed", "skipped", "paused"):
                last.status = MARK[body.status]
                last.stage_changed_at = now
                if body.note:
                    last.notes = (last.notes + "\n" + body.note).strip()
                if body.status in ("rejected", "offer"):
                    last.follow_up_at = None
            else:
                s.add(
                    Application(
                        job=j,
                        status=MARK[body.status],
                        origin="manual",
                        mode="manual",
                        submitted_at=now,
                        finished_at=now,
                        stage_changed_at=now,
                        follow_up_at=now + timedelta(days=ctx.settings.follow_up_days)
                        if body.status == "applied"
                        else None,
                        confirmation="im Dashboard eingetragen",
                        notes=body.note,
                    )
                )
            j.queued = False
            s.add(status_activity(j, MARK.get(body.status, body.status)))
            s.flush()
            return job_summary(j)

    @app.post("/api/jobs/bulk")
    def jobs_bulk(body: BulkAction) -> dict[str, Any]:
        config = ctx.runtime().config
        if body.action == "queue":
            added, skipped = queue_jobs(ctx.db, config, body.ids)
            return {"changed": added, "skipped": skipped}
        changed = []
        exclusions: list[Exclusion] = []
        with session_scope(ctx.db) as s:
            for jid in body.ids:
                j = s.get(Job, jid)
                if j is None:
                    continue
                if body.action == "unqueue":
                    j.queued = False
                elif body.action in ("star", "unstar"):
                    j.starred = body.action == "star"
                elif body.action == "exclude":
                    # schon aussortiert: keinen zweiten Ausschluss anlegen (Rückgängig löscht nur die neuen)
                    known = s.scalar(
                        select(Exclusion.id).where(Exclusion.kind == "job", Exclusion.value == str(jid))
                    )
                    if known is None:
                        ex = Exclusion(kind="job", value=str(jid), reason="im Dashboard ausgeschlossen")
                        s.add(ex)
                        exclusions.append(ex)
                    j.queued = False
                else:
                    raise HTTPException(400, "Unbekannte Aktion")
                changed.append(jid)
            s.flush()
            # IDs der neuen Ausschlüsse, damit die Oberfläche „Rückgängig“ anbieten kann
            return {"changed": changed, "skipped": [], "exclusions": [ex.id for ex in exclusions]}

    @app.post("/api/queue/top")
    def queue_top(count: int = Query(10, ge=1, le=50)) -> dict[str, Any]:
        config = ctx.runtime().config
        picked = pick_top(ctx.db, config, count)
        added, skipped = queue_jobs(ctx.db, config, picked)
        return {"changed": added, "skipped": skipped}

    @app.post("/api/queue/clear")
    def queue_clear() -> dict[str, Any]:
        with session_scope(ctx.db) as s:
            rows = list(s.execute(select(Job).where(Job.queued)).scalars())
            for j in rows:
                j.queued = False
        return {"changed": [j.id for j in rows]}

    # ------------------------------------------------------------------ Bewerbungsläufe
    @app.post("/api/apply")
    def apply(body: ApplyRequest) -> dict[str, Any]:
        mode = body.mode or ctx.settings.apply_mode
        if mode not in ("review", "auto", "dry-run"):
            raise HTTPException(400, "Modus muss review, auto oder dry-run sein")
        if ctx.runner.active:
            raise Problem(409, "api.run_active", "Es läuft bereits ein Bewerbungslauf")
        if not body.job_ids:
            with session_scope(ctx.db) as s:
                if not s.scalar(select(func.count(Job.id)).where(Job.queued)):
                    raise Problem(409, "api.queue_empty", "Die Warteschlange ist leer")
        ctx.runner.start(body.job_ids or None, mode=mode, max_count=body.max, force=body.force)  # type: ignore[arg-type]
        record(
            ctx.settings,
            "run",
            f"Bewerbungslauf gestartet ({ctx.runner.label}, {mode})",
            code="run.started",
            mode=mode,
        )
        return ctx.runner.state()

    @app.get("/api/runner")
    def runner_state(lines: int = Query(200, ge=0, le=2_000)) -> dict[str, Any]:
        return ctx.runner.state(lines=lines)

    @app.post("/api/runner/stop")
    def runner_stop() -> dict[str, Any]:
        stopped = ctx.runner.stop()
        if stopped:
            record(ctx.settings, "run", "Bewerbungslauf abgebrochen", code="run.stopped")
        return ctx.runner.state() | {"stopped": stopped}

    # ------------------------------------------------------------------ Crawl & Autopilot
    @app.post("/api/crawl")
    async def crawl() -> dict[str, Any]:
        started = await ctx.start_crawl()
        return {"started": started, **ctx.crawl}

    @app.get("/api/crawls")
    def crawls(limit: int = Query(50, ge=1, le=500)) -> list[dict[str, Any]]:
        with session_scope(ctx.db) as s:
            return [
                {
                    "id": r.id,
                    "started_at": _iso(r.started_at),
                    "finished_at": _iso(r.finished_at),
                    "status": r.status,
                    "stats": r.stats,
                    "errors": r.errors,
                }
                for r in s.execute(select(CrawlRun).order_by(CrawlRun.id.desc()).limit(limit)).scalars()
            ]

    @app.get("/api/crawls/{run_id}")
    def crawl_detail(run_id: int) -> dict[str, Any]:
        with session_scope(ctx.db) as s:
            run = s.get(CrawlRun, run_id)
            if run is None:
                raise HTTPException(404)
            snaps = s.execute(
                select(JobSnapshot).where(
                    JobSnapshot.crawl_run_id == run_id, JobSnapshot.change != "unchanged"
                )
            ).scalars()
            return {
                "id": run.id,
                "started_at": _iso(run.started_at),
                "status": run.status,
                "stats": run.stats,
                "errors": run.errors,
                "changes": [
                    {
                        "job_id": sn.job_id,
                        "change": sn.change,
                        "company": sn.job.company,
                        "title": sn.title,
                        "diff": sn.diff,
                    }
                    for sn in snaps
                ],
            }

    @app.post("/api/autopilot/run")
    async def autopilot_run() -> dict[str, Any]:
        if ctx.autopilot_running:
            raise Problem(409, "api.autopilot_running", "Autopilot läuft bereits")
        ensure_not_demo(ctx.settings, "Autopilot")
        ctx.spawn(ctx.run_autopilot())
        return {"started": True}

    @app.get("/api/activity")
    def activity(limit: int = Query(30, ge=1, le=1_000)) -> list[dict[str, Any]]:
        with session_scope(ctx.db) as s:
            return [
                {"id": a.id, "ts": _iso(a.ts), "kind": a.kind, "message": a.message, "data": a.data}
                for a in s.execute(select(Activity).order_by(Activity.id.desc()).limit(limit)).scalars()
            ]

    # ------------------------------------------------------------------ Bewerbungen & Pipeline
    @app.get("/api/applications")
    def applications(status: str = "", limit: int = Query(300, ge=1, le=5_000)) -> list[dict[str, Any]]:
        with session_scope(ctx.db) as s:
            stmt = select(Application).order_by(Application.id.desc()).limit(limit).options(WITH_JOB)
            if status:
                stmt = stmt.where(Application.status.in_(status.split(",")))
            waiting = waiting_for_you(s)
            return [app_summary(a, waiting) for a in s.execute(stmt).scalars()]

    @app.get("/api/pipeline")
    def pipeline() -> dict[str, Any]:
        now = utcnow()
        with session_scope(ctx.db) as s:
            latest: dict[int, Application] = {}
            last_ids = select(func.max(Application.id)).group_by(Application.job_id)
            for a in s.execute(
                select(Application)
                .where(Application.id.in_(last_ids))
                .order_by(Application.id)
                .options(WITH_JOB)
            ).scalars():
                latest[a.job_id] = a  # pro Stelle zählt der letzte Stand
            stages: dict[str, list[dict[str, Any]]] = {k: [] for k in STAGES}
            due = []
            for a in sorted(latest.values(), key=lambda x: x.stage_changed_at or x.started_at, reverse=True):
                for stage, statuses in STAGES.items():
                    if a.status in statuses:
                        stages[stage].append(app_summary(a))
                if (
                    a.follow_up_at
                    and a.follow_up_at <= now
                    and a.status in ("submitted", "manual", "interview")
                ):
                    due.append(app_summary(a))
            return {"stages": stages, "follow_ups_due": due}

    @app.get("/api/applications/{app_id}")
    def application_detail(app_id: int) -> dict[str, Any]:
        with session_scope(ctx.db) as s:
            a = s.get(Application, app_id)
            if a is None:
                raise HTTPException(404)
            folder = Path(a.artifacts_dir) if a.artifacts_dir else None
            files = sorted(p.name for p in folder.iterdir()) if folder and folder.is_dir() else []
            prompts = s.execute(
                select(Prompt).where(Prompt.application_id == app_id, Prompt.status == "open")
            ).scalars()
            return app_summary(a, waiting_for_you(s)) | {
                "events": [
                    {"ts": _iso(e.ts), "kind": e.kind, "message": e.message}
                    for e in s.execute(
                        select(ApplicationEvent)
                        .where(ApplicationEvent.application_id == app_id)
                        .order_by(ApplicationEvent.id)
                    ).scalars()
                ],
                "screenshots": [f for f in files if f.endswith((".jpg", ".png"))],
                "documents": [f for f in files if f.endswith(".pdf")],
                "filled": a.filled,
                "questions": a.open_questions,
                "usage": a.usage,
                "final_url": a.final_url,
                "prompts": [prompt_json(p) for p in prompts],
            }

    @app.patch("/api/applications/{app_id}")
    def application_patch(app_id: int, body: AppPatch) -> dict[str, Any]:
        with session_scope(ctx.db) as s:
            a = s.get(Application, app_id)
            if a is None:
                raise HTTPException(404)
            if body.status is not None:
                valid = {"submitted", "manual", "interview", "offer", "rejected"}
                if body.status not in valid:
                    raise HTTPException(400, "Ungültiger Status")
                a.status = body.status
                a.stage_changed_at = utcnow()
                if body.status in ("offer", "rejected"):
                    a.follow_up_at = None
                s.add(status_activity(a.job, body.status))
            if body.notes is not None:
                a.notes = body.notes
            if body.clear_follow_up:
                a.follow_up_at = None
            elif body.follow_up_at is not None:
                a.follow_up_at = body.follow_up_at.replace(tzinfo=None)
            s.flush()
            return app_summary(a)

    @app.post("/api/applications/{app_id}/answers")
    def application_answers(app_id: int, body: AppAnswers) -> dict[str, Any]:
        with session_scope(ctx.db) as s:
            a = s.get(Application, app_id)
            if a is None:
                raise HTTPException(404)
            saved = 0
            for i, q in enumerate(a.open_questions or []):
                value = str(body.answers.get(str(i), "")).strip()
                if not value:
                    continue
                question = q.get("label") or q.get("question", "")
                key = normalize_question(question)
                existing = s.execute(select(Answer).where(Answer.question_key == key)).scalars().first()
                if existing:
                    existing.answer, existing.updated_at = value, utcnow()
                else:
                    s.add(Answer(question_key=key, question=question, answer=value))
                saved += 1
            if body.requeue and a.status in ACTIVE_STATES | {"failed", "paused"}:
                a.job.queued = True
                a.status = "skipped"
                a.confirmation = "Fragen beantwortet, neu eingereiht"
            return {"saved": saved, "requeued": body.requeue}

    @app.get("/artifacts/{app_id}/{name}")
    def artifact(app_id: int, name: str) -> FileResponse:
        with session_scope(ctx.db) as s:
            a = s.get(Application, app_id)
            if a is None or not a.artifacts_dir:
                raise HTTPException(404)
            base = os.path.realpath(a.artifacts_dir)
        # nur Dateien direkt im Belege-Ordner, nie ein Pfad nach draußen
        if name != os.path.basename(name) or name.startswith("."):
            raise HTTPException(404)
        path = os.path.realpath(os.path.join(base, name))
        if not path.startswith(base + os.sep) or not os.path.isfile(path):
            raise HTTPException(404)
        return FileResponse(path)

    # ------------------------------------------------------------------ Rückfragen
    @app.get("/api/prompts")
    def prompts() -> list[dict[str, Any]]:
        with session_scope(ctx.db) as s:
            return [
                prompt_json(p)
                for p in s.execute(
                    select(Prompt).where(Prompt.status == "open").order_by(Prompt.id)
                ).scalars()
            ]

    @app.post("/api/prompts/{prompt_id}")
    def prompt_answer(prompt_id: int, body: PromptAnswer) -> dict[str, Any]:
        with session_scope(ctx.db) as s:
            p = s.get(Prompt, prompt_id)
            if p is None or p.status != "open":
                raise Problem(409, "api.prompt_closed", "Die Rückfrage ist nicht mehr offen")
            response: dict[str, Any]
            if p.kind == "questions":
                response = {"skip": True} if body.skip else {"answers": body.answers}
            elif p.kind == "confirm":
                if body.decision not in ("submit", "manual", "reject"):
                    raise HTTPException(400, "decision muss submit, manual oder reject sein")
                response = {"decision": body.decision}
            else:
                response = {"abort": True} if body.abort else {"done": True}
            # Nur solange offen: läuft die Wartezeit des Laufs gerade ab, gewinnt genau einer – sonst stünde hier
            # „beantwortet“, während der Lauf schon aufgegeben hat
            done = s.connection().execute(
                update(Prompt)
                .where(Prompt.id == prompt_id, Prompt.status == "open")
                .values(status="answered", answered_at=utcnow(), response=response)
            )
            if not done.rowcount:
                raise Problem(409, "api.prompt_closed", "Die Rückfrage ist nicht mehr offen")
            s.refresh(p)
            return prompt_json(p)

    # ------------------------------------------------------------------ Antwortbank & Ausschlüsse
    @app.get("/api/answers")
    def answers() -> list[dict[str, Any]]:
        with session_scope(ctx.db) as s:
            return [
                {"id": a.id, "question": a.question, "answer": a.answer, "updated_at": _iso(a.updated_at)}
                for a in s.execute(select(Answer).order_by(Answer.updated_at.desc())).scalars()
            ]

    @app.post("/api/answers")
    def answer_create(body: AnswerIn) -> dict[str, Any]:
        key = normalize_question(body.question)
        with session_scope(ctx.db) as s:
            row = s.execute(select(Answer).where(Answer.question_key == key)).scalars().first()
            if row is None:
                row = Answer(question_key=key, question=body.question, answer=body.answer)
                s.add(row)
            else:
                row.question, row.answer, row.updated_at = body.question, body.answer, utcnow()
            s.flush()
            return {"id": row.id}

    @app.put("/api/answers/{answer_id}")
    def answer_update(answer_id: int, body: AnswerIn) -> dict[str, Any]:
        with session_scope(ctx.db) as s:
            row = s.get(Answer, answer_id)
            if row is None:
                raise HTTPException(404)
            row.question, row.answer, row.updated_at = body.question, body.answer, utcnow()
            row.question_key = normalize_question(body.question)
            return {"id": row.id}

    @app.delete("/api/answers/{answer_id}")
    def answer_delete(answer_id: int) -> dict[str, Any]:
        with session_scope(ctx.db) as s:
            if row := s.get(Answer, answer_id):
                s.delete(row)
        return {"deleted": answer_id}

    @app.get("/api/exclusions")
    def exclusions() -> list[dict[str, Any]]:
        with session_scope(ctx.db) as s:
            return [
                {
                    "id": e.id,
                    "kind": e.kind,
                    "value": e.value,
                    "reason": e.reason,
                    "created_at": _iso(e.created_at),
                }
                for e in s.execute(select(Exclusion).order_by(Exclusion.id.desc())).scalars()
            ]

    @app.post("/api/exclusions")
    def exclusion_create(body: ExclusionIn) -> dict[str, Any]:
        if body.kind not in ("company", "job", "title", "url") or not body.value.strip():
            raise HTTPException(400, "kind muss company, job, title oder url sein")
        if body.kind == "title" and (problem := regex_problem(body.value.strip())):
            raise Problem(400, "api.bad_regex", f"Ungültiger regulärer Ausdruck: {problem}", error=problem)
        with session_scope(ctx.db) as s:
            e = Exclusion(kind=body.kind, value=body.value.strip(), reason=body.reason)
            s.add(e)
            for j in s.execute(select(Job).where(Job.queued)).scalars():
                hit = (body.kind == "company" and body.value.lower() in j.company.lower()) or (
                    body.kind == "job" and str(j.id) == body.value.strip()
                )
                if hit:
                    j.queued = False
            s.flush()
            return {"id": e.id}

    @app.delete("/api/exclusions/{ex_id}")
    def exclusion_delete(ex_id: int) -> dict[str, Any]:
        with session_scope(ctx.db) as s:
            if e := s.get(Exclusion, ex_id):
                s.delete(e)
        return {"deleted": ex_id}

    # ------------------------------------------------------------------ Statistik & Export
    @app.get("/api/stats")
    def stats() -> dict[str, Any]:
        now = utcnow()
        with session_scope(ctx.db) as s:
            jobs_open = s.scalar(select(func.count(Job.id)).where(Job.status == "open")) or 0
            new_7d = (
                s.scalar(select(func.count(Job.id)).where(Job.first_seen >= now - timedelta(days=7))) or 0
            )
            by_category = dict(
                s.execute(
                    select(Job.category, func.count()).where(Job.status == "open").group_by(Job.category)
                ).all()
            )
            apps = s.execute(
                select(Application.status, Application.submitted_at, Application.started_at)
            ).all()
        by_status = Counter(a.status for a in apps)
        sent = [a for a in apps if a.status in DONE_STATES]
        weeks: list[dict[str, Any]] = []
        monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        for i in range(11, -1, -1):
            start = monday - timedelta(weeks=i)
            end = start + timedelta(weeks=1)
            weeks.append(
                {
                    "week": start.date().isoformat(),
                    "sent": sum(1 for a in sent if start <= (a.submitted_at or a.started_at) < end),
                }
            )
        responded = sum(by_status[k] for k in ("interview", "offer", "rejected"))
        interviews = by_status["interview"] + by_status["offer"]
        return {
            "jobs": {"open": jobs_open, "new_7d": new_7d, "by_category": by_category},
            "applications": {
                "by_status": dict(by_status),
                "sent_total": len(sent),
                "sent_7d": sum(
                    1 for a in sent if (a.submitted_at or a.started_at) >= now - timedelta(days=7)
                ),
                "response_rate": round(responded / len(sent), 3) if sent else 0,
                "interview_rate": round(interviews / len(sent), 3) if sent else 0,
                "per_week": weeks,
            },
        }

    @app.get("/api/export.csv")
    def export_csv() -> Response:
        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=";")
        writer.writerow(
            ["id", "company", "title", "location", "category", "score", "status", "application", "url"]
        )
        with session_scope(ctx.db) as s:
            last = dict(
                s.execute(select(Application.job_id, Application.status).order_by(Application.id)).all()
            )
            columns = (Job.id, Job.company, Job.title, Job.location, Job.category, Job.score, Job.status)
            for j in s.execute(select(*columns, Job.url).order_by(Job.score.desc())):
                writer.writerow([*j[:7], last.get(j.id, ""), j.url])
        return Response(
            "﻿" + buf.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="jobslop-export.csv"'},
        )

    # ------------------------------------------------------------------ Oberfläche (SPA)
    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> Response:
        if path.startswith("api/"):
            raise HTTPException(404)
        if DIST.is_dir():
            root = os.path.realpath(DIST)
            candidate = os.path.realpath(os.path.join(root, path))
            if path and candidate.startswith(root + os.sep) and os.path.isfile(candidate):
                return FileResponse(candidate)
            index = DIST / "index.html"
            if index.exists():
                return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return HTMLResponse(
            "<h1>jobslop</h1><p>Die Oberfläche ist nicht gebaut. Im Projektordner ausführen: "
            "<code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code></p>",
            status_code=503,
        )

    return app

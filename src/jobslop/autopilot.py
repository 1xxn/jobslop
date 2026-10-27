"""Autopilot: neue Stellen suchen, die besten einreihen und bewerben – nach Zeitplan oder auf Knopfdruck.

Im Dashboard läuft der Zeitplan, solange das Dashboard offen ist. Ohne Dashboard: ``jobslop autopilot`` aus
der Windows-Aufgabenplanung bzw. cron aufrufen (unbeaufsichtigt, offene Fragen werden geparkt).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from .config import Settings
from .db import Activity, session_scope
from .queueing import pick_top, queue_jobs
from .runtime import Runtime

log = logging.getLogger(__name__)

Notify = Callable[[str, str], Awaitable[Any]]


def activity(
    kind: str, message: str, data: dict[str, Any] | None = None, *, code: str = "", **params: Any
) -> Activity:
    """Eintrag im Aktivitätsprotokoll. ``message`` ist deutscher Klartext (CLI, ältere Einträge); ``code`` und
    ``params`` übersetzt das Dashboard (Schlüssel ``be.<code>`` in frontend/src/lib/messages.ts)."""
    payload = dict(data or {})
    if code:
        payload |= {"code": code, "params": params}
    return Activity(kind=kind, message=message, data=payload)


def record(
    settings: Settings,
    kind: str,
    message: str,
    data: dict[str, Any] | None = None,
    *,
    code: str = "",
    **params: Any,
) -> None:
    with session_scope(settings.db_path) as s:
        s.add(activity(kind, message, data, code=code, **params))


async def crawl_and_queue(runtime: Runtime, *, queue_count: int) -> dict[str, Any]:
    """Crawlen (mit Claude-Bewertung, falls angemeldet) und die besten Stellen einreihen."""
    from .crawl.pipeline import run_crawl
    from .system import claude_status

    login = await asyncio.to_thread(claude_status, runtime.settings)
    llm = runtime.llm() if login.ok else None
    report = await run_crawl(
        runtime.settings, runtime.config, llm=llm, profile=runtime.profile, enrich=llm is not None
    )
    picked = pick_top(runtime.settings.db_path, runtime.config, queue_count) if queue_count else []
    added, _skipped = queue_jobs(runtime.settings.db_path, runtime.config, picked)
    summary = {
        "run_id": report.run_id,
        "new": len(report.new),
        "closed": len(report.closed),
        "kept": report.kept,
        "queued": added,
        "errors": len(report.errors),
        "discovered": len(report.discovered),
    }
    record(
        runtime.settings,
        "crawl",
        f"Crawl #{report.run_id}: {len(report.new)} neue Stellen, {len(added)} eingereiht",
        summary,
        code="crawl.done",
        run=report.run_id,
        new=len(report.new),
        queued=len(added),
    )
    return summary


def last_autopilot_run(settings: Settings) -> datetime | None:
    with session_scope(settings.db_path) as s:
        row = (
            s.execute(select(Activity).where(Activity.kind == "autopilot").order_by(Activity.id.desc()))
            .scalars()
            .first()
        )
        return row.ts if row else None


def next_run(settings: Settings, now: datetime | None = None) -> datetime | None:
    """Nächster geplanter Lauf in Ortszeit (None, wenn der Autopilot aus ist)."""
    if settings.demo or not settings.autopilot_enabled or not settings.autopilot_days:
        return None
    now = now or datetime.now()
    try:
        hour, minute = (int(x) for x in settings.autopilot_time.split(":", 1))
    except ValueError:
        hour, minute = 8, 0
    last = last_autopilot_run(settings)
    offset_utc = datetime.now().astimezone().utcoffset() or timedelta(0)
    last_local = last + offset_utc if last else None  # gespeichert wird UTC
    for offset in range(8):
        day = now + timedelta(days=offset)
        slot = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if day.weekday() not in settings.autopilot_days:
            continue
        if offset == 0 and last_local and last_local.date() == now.date() and last_local >= slot:
            continue  # heute schon gelaufen
        if offset == 0 and slot < now - timedelta(hours=6):
            continue  # Termin heute lange verpasst – nicht nachholen, sondern morgen
        return slot
    return None


class Scheduler:
    """Prüft jede halbe Minute, ob ein Autopilot-Lauf fällig ist."""

    def __init__(self, run: Callable[[], Awaitable[Any]], settings_getter: Callable[[], Settings]) -> None:
        self._run = run
        self._settings = settings_getter
        self._task: asyncio.Task[None] | None = None
        self.running = False

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                due = next_run(self._settings())
                if due is not None and due <= datetime.now() and not self.running:
                    self.running = True
                    try:
                        await self._run()
                    finally:
                        self.running = False
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Autopilot-Lauf fehlgeschlagen")
            await asyncio.sleep(30)

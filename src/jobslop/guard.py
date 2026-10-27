"""Regeln, die vor jeder Bewerbung greifen: Ausschlüsse, Dubletten, Firmen-Limit."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .classify import match_key
from .config import LimitConfig
from .db import Application, Exclusion, Job, utcnow
from .hosts import is_browser_only

DONE_STATES = {"submitted", "manual", "interview", "rejected", "offer"}
ACTIVE_STATES = {"running", "needs_input", "needs_review", "ready"}


@dataclass
class Verdict:
    """Ergebnis der Prüfung. ``reason`` ist deutscher Klartext (CLI, Logs); ``code`` + ``params`` übersetzt das
    Dashboard in die gewählte Sprache (Schlüssel ``be.<code>`` in frontend/src/lib/messages.ts)."""

    ok: bool
    reason: str = ""
    code: str = ""
    params: dict[str, Any] = field(default_factory=dict)


def _no(reason: str, code: str, **params: Any) -> Verdict:
    return Verdict(False, reason, f"guard.{code}", params)


def company_key(name: str) -> str:
    n = name.lower()
    n = re.sub(r"\b(gmbh|ag|se|kg|co|inc|ltd|llc|group|gruppe|deutschland|germany|tech)\b", " ", n)
    return re.sub(r"[^a-z0-9]+", " ", n).strip()


def is_excluded(session: Session, job: Job) -> Verdict | None:
    for ex in session.execute(select(Exclusion)).scalars():
        v = ex.value
        if ex.kind == "company" and company_key(v) and company_key(v) in company_key(job.company):
            return _no(f"Firma ausgeschlossen ({v})", "excluded_company", value=v)
        if ex.kind == "job" and v == str(job.id):
            return _no("Stelle ausgeschlossen", "excluded_job")
        if ex.kind == "title" and re.search(v, job.title, re.I):
            return _no(f"Titel-Ausschluss ({v})", "excluded_title", value=v)
        if ex.kind == "url" and v.lower() in job.url.lower():
            return _no(f"URL-Ausschluss ({v})", "excluded_url", value=v)
    return None


def already_applied(session: Session, job: Job) -> Verdict | None:
    for app in job.applications:
        if app.status in DONE_STATES:
            return _no(f"Schon beworben (#{app.id}, {app.status})", "applied", id=app.id, status=app.status)
    key = match_key(job.company, job.title)
    twins = session.execute(select(Job).where(Job.match_key == key, Job.id != job.id)).scalars().all()
    for twin in twins:
        for app in twin.applications:
            if app.status in DONE_STATES:
                return _no(
                    f"Gleiche Stelle über andere Quelle schon beworben (Job #{twin.id})",
                    "applied_twin",
                    job=twin.id,
                )
    return None


def check_job(session: Session, job: Job, limits: LimitConfig, *, force: bool = False) -> Verdict:
    if job.status == "closed" and not force:
        return _no("Stelle ist laut letztem Crawl geschlossen", "closed")
    if verdict := is_excluded(session, job) or already_applied(session, job):
        return verdict
    if is_browser_only(job.target_url):
        # Im automatisierten Browser hängt die Bot-Abfrage endlos – auch „trotzdem bewerben“ hilft da nicht
        return _no(
            "Nur in deinem eigenen Browser bewerbbar (Bot-Abfrage der Jobbörse) – Link öffnen", "browser_only"
        )
    if not force:
        for app in job.applications:
            if app.status in ACTIVE_STATES:
                return _no(
                    f"Bewerbung #{app.id} ist noch offen ({app.status})", "open", id=app.id, status=app.status
                )
        since = utcnow() - timedelta(days=limits.company_window_days)
        ck = company_key(job.company)
        recent = session.execute(
            select(Application, Job)
            .join(Job)
            .where(Application.status.in_(DONE_STATES), Application.started_at >= since)
        ).all()
        count = sum(1 for _app, j in recent if company_key(j.company) == ck)
        if count >= limits.max_per_company_window:
            return _no(
                f"Firmen-Limit erreicht: {count} Bewerbungen bei {job.company} in {limits.company_window_days} Tagen",
                "company_limit",
                count=count,
                company=job.company,
                days=limits.company_window_days,
            )
    return Verdict(True)

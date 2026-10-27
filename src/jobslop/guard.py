"""Regeln, die vor jeder Bewerbung greifen: Ausschlüsse, Dubletten, Firmen-Limit."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta

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
    ok: bool
    reason: str = ""


def company_key(name: str) -> str:
    n = name.lower()
    n = re.sub(r"\b(gmbh|ag|se|kg|co|inc|ltd|llc|group|gruppe|deutschland|germany|tech)\b", " ", n)
    return re.sub(r"[^a-z0-9]+", " ", n).strip()


def is_excluded(session: Session, job: Job) -> str:
    for ex in session.execute(select(Exclusion)).scalars():
        v = ex.value
        if ex.kind == "company" and company_key(v) and company_key(v) in company_key(job.company):
            return f"Firma ausgeschlossen ({v})"
        if ex.kind == "job" and v == str(job.id):
            return "Stelle ausgeschlossen"
        if ex.kind == "title" and re.search(v, job.title, re.I):
            return f"Titel-Ausschluss ({v})"
        if ex.kind == "url" and v.lower() in job.url.lower():
            return f"URL-Ausschluss ({v})"
    return ""


def already_applied(session: Session, job: Job) -> str:
    for app in job.applications:
        if app.status in DONE_STATES:
            return f"Schon beworben (#{app.id}, {app.status})"
    key = match_key(job.company, job.title)
    twins = session.execute(select(Job).where(Job.match_key == key, Job.id != job.id)).scalars().all()
    for twin in twins:
        for app in twin.applications:
            if app.status in DONE_STATES:
                return f"Gleiche Stelle über andere Quelle schon beworben (Job #{twin.id})"
    return ""


def check_job(session: Session, job: Job, limits: LimitConfig, *, force: bool = False) -> Verdict:
    if job.status == "closed" and not force:
        return Verdict(False, "Stelle ist laut letztem Crawl geschlossen")
    if reason := is_excluded(session, job):
        return Verdict(False, reason)
    if reason := already_applied(session, job):
        return Verdict(False, reason)
    if is_browser_only(job.target_url):
        # Im automatisierten Browser hängt die Bot-Abfrage endlos – auch „trotzdem bewerben“ hilft da nicht
        return Verdict(
            False, "Nur in deinem eigenen Browser bewerbbar (Bot-Abfrage der Jobbörse) – Link öffnen"
        )
    if not force:
        for app in job.applications:
            if app.status in ACTIVE_STATES:
                return Verdict(False, f"Bewerbung #{app.id} ist noch offen ({app.status})")
        since = utcnow() - timedelta(days=limits.company_window_days)
        ck = company_key(job.company)
        recent = session.execute(
            select(Application, Job)
            .join(Job)
            .where(Application.status.in_(DONE_STATES), Application.started_at >= since)
        ).all()
        count = sum(1 for _app, j in recent if company_key(j.company) == ck)
        if count >= limits.max_per_company_window:
            return Verdict(
                False,
                f"Firmen-Limit erreicht: {count} Bewerbungen bei {job.company} in {limits.company_window_days} Tagen",
            )
    return Verdict(True)

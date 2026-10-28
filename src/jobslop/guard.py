"""Regeln, die vor jeder Bewerbung greifen: Ausschlüsse, Dubletten, Firmen-Limit."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
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


_LEGAL_FORM_RX = re.compile(r"\b(gmbh|ag|se|kg|co|inc|ltd|llc|group|gruppe|deutschland|germany|tech)\b")
_NON_ALNUM_RX = re.compile(r"[^a-z0-9]+")


def company_key(name: str) -> str:
    return _NON_ALNUM_RX.sub(" ", _LEGAL_FORM_RX.sub(" ", name.lower())).strip()


def _title_test(pattern: str) -> Callable[[str], bool]:
    """Titel-Ausschluss als regulärer Ausdruck – ein ungültiger (z. B. „senior (“) gilt als einfacher Text, statt die
    Status- und Stellenabfragen des Dashboards mit einem Fehler zu blockieren."""
    try:
        rx = re.compile(pattern, re.I)
    except re.error:
        low = pattern.lower()
        return lambda title: low in title.lower()
    return lambda title: rx.search(title) is not None


def title_matches(pattern: str, title: str) -> bool:
    return _title_test(pattern)(title)


def _exclusion_verdict(ex: Exclusion, job: Job) -> Verdict | None:
    v = ex.value
    if ex.kind == "company" and company_key(v) and company_key(v) in company_key(job.company):
        return _no(f"Firma ausgeschlossen ({v})", "excluded_company", value=v)
    if ex.kind == "job" and v == str(job.id):
        return _no("Stelle ausgeschlossen", "excluded_job")
    if ex.kind == "title" and title_matches(v, job.title):
        return _no(f"Titel-Ausschluss ({v})", "excluded_title", value=v)
    if ex.kind == "url" and v.lower() in job.url.lower():
        return _no(f"URL-Ausschluss ({v})", "excluded_url", value=v)
    return None


def is_excluded(session: Session, job: Job) -> Verdict | None:
    for ex in session.execute(select(Exclusion)).scalars():
        if verdict := _exclusion_verdict(ex, job):
            return verdict
    return None


def excluded_job_ids(session: Session, jobs: Iterable[Any]) -> set[int]:
    """IDs der Stellen (oder Zeilen mit id, company, title, url), die eine Ausschlussregel trifft – wie
    ``_exclusion_verdict``, aber die Regeln werden einmal vorbereitet (der Status-Abruf alle paar Sekunden prüft
    damit Tausende Stellen)."""
    rules = list(session.execute(select(Exclusion)).scalars())
    if not rules:
        return set()
    companies = [key for ex in rules if ex.kind == "company" and (key := company_key(ex.value))]
    # Als Zahl vergleichen spart str() pro Stelle; „7“ trifft Stelle 7, „007“ wie bisher nicht
    job_ids = {
        int(v)
        for ex in rules
        if ex.kind == "job" and (v := ex.value).isascii() and v.isdigit() and str(int(v)) == v
    }
    titles = [_title_test(ex.value) for ex in rules if ex.kind == "title"]
    urls = [ex.value.lower() for ex in rules if ex.kind == "url"]
    # Titel und Firmen wiederholen sich (dieselbe Firma, „DevOps Engineer (m/w/d)“ bei vielen) – jedes Ergebnis nur
    # einmal berechnen; das waren zwei Drittel eines Status-Abrufs
    title_hit: dict[str, bool] = {}
    company_hit: dict[str, bool] = {}

    def hit(job: Any) -> bool:
        if job.id in job_ids:
            return True
        if titles:
            if (by_title := title_hit.get(job.title)) is None:
                by_title = title_hit[job.title] = any(test(job.title) for test in titles)
            if by_title:
                return True
        if urls and any(u in job.url.lower() for u in urls):
            return True
        if companies:
            if (by_company := company_hit.get(job.company)) is None:
                key = company_key(job.company)
                by_company = company_hit[job.company] = any(c in key for c in companies)
            return by_company
        return False

    return {j.id for j in jobs if hit(j)}


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

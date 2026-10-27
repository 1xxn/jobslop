"""Warteschlange: die besten passenden Stellen für die nächste Bewerbungsrunde auswählen."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from .config import SearchConfig
from .db import Job, session_scope
from .guard import check_job
from .hosts import is_handoff


def queue_jobs(db_path: Path, config: SearchConfig, job_ids: list[int]) -> tuple[list[int], list[str]]:
    """Bestimmte Stellen einreihen. Rückgabe: (eingereiht, übersprungen mit Grund)."""
    added, skipped = [], []
    with session_scope(db_path) as s:
        for jid in job_ids:
            job = s.get(Job, jid)
            if job is None:
                continue
            verdict = check_job(s, job, config.limits)
            if verdict.ok:
                job.queued = True
                added.append(jid)
            else:
                skipped.append(f"#{jid} {job.company}: {verdict.reason}")
    return added, skipped


def pick_top(
    db_path: Path,
    config: SearchConfig,
    count: int,
    *,
    categories: list[str] | None = None,
    where: str | None = None,
    include_stretch: bool = False,
) -> list[int]:
    """Beste offene Stellen ohne Bewerbung, die alle Regeln (Ausschlüsse, Firmen-Limit, Mindest-Score) erfüllen."""
    picked: list[int] = []
    with session_scope(db_path) as s:
        q = select(Job).where(Job.status == "open", Job.score >= config.limits.min_score_for_auto_queue)
        if categories:
            q = q.where(Job.category.in_(categories))
        if where in ("B", "R"):
            q = q.where(Job.where.in_([where, "BR"]))
        if not include_stretch:
            q = q.where(Job.level != "S")
        for job in s.execute(q.order_by(Job.starred.desc(), Job.score.desc())).scalars():
            if len(picked) >= count:
                break
            if is_handoff(job.target_url):
                continue  # LinkedIn/Indeed brauchen dich (oder die Browser-Erweiterung) – nicht automatisch einreihen
            if not job.queued and check_job(s, job, config.limits).ok:
                picked.append(job.id)
    return picked

"""Crawl-Lauf: Quellen abfragen, filtern, einordnen, in die DB übernehmen und History schreiben."""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..classify import classify, content_hash, fingerprint, match_key, score, title_allowed, where_of
from ..config import SearchConfig, Settings
from ..db import CrawlRun, Job, JobSnapshot, session_scope, utcnow
from ..llm import LLM, LLMLimitReached
from ..profile import Profile
from .base import RawPosting, make_client
from .render import PageRenderer
from .sources import build_sources, gather_limited

log = logging.getLogger(__name__)


@dataclass
class CrawlReport:
    run_id: int
    fetched: int = 0
    kept: int = 0
    new: list[int] = field(default_factory=list)
    updated: list[int] = field(default_factory=list)
    reopened: list[int] = field(default_factory=list)
    closed: list[int] = field(default_factory=list)
    merged_seeds: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    per_source: dict[str, int] = field(default_factory=dict)
    rejected: Counter[str] = field(default_factory=Counter)


def _workplace(p: RawPosting, where: str) -> str:
    if p.workplace:
        return p.workplace
    if where == "R":
        return "Remote"
    loc = p.location.lower()
    if "hybrid" in loc:
        return "Hybrid"
    return ""


async def run_crawl(
    settings: Settings,
    config: SearchConfig,
    *,
    only: list[str] | None = None,
    llm: LLM | None = None,
    profile: Profile | None = None,
    enrich: bool = True,
    use_browser: bool = True,
) -> CrawlReport:
    with session_scope(settings.db_path) as s:
        run = CrawlRun(status="running")
        s.add(run)
        s.flush()
        run_id = run.id

    report = CrawlReport(run_id=run_id)
    renderer = PageRenderer() if use_browser and config.sources.generic else None
    try:
        sources = build_sources(
            config, llm=llm, render=renderer, fast_model=settings.llm_model_fast, only=only
        )
        async with make_client() as client:
            results = await gather_limited([src.fetch(client) for src in sources], limit=8)
            ok_sources: set[str] = set()
            kept: list[tuple[Any, RawPosting, str]] = []
            for src, result in zip(sources, results, strict=True):
                if isinstance(result, BaseException):
                    report.errors.append(f"{src.name}: {type(result).__name__}: {result}")
                    continue
                ok_sources.add(src.name)
                report.per_source[src.name] = len(result)
                report.fetched += len(result)
                for posting in result:
                    allowed, _why = title_allowed(posting.title, config.filters)
                    if not allowed:
                        report.rejected["Titel"] += 1
                        continue
                    where = where_of(posting.location, config.filters, posting.remote)
                    if where is None:
                        report.rejected["Ort"] += 1
                        continue
                    kept.append((src, posting, where))

            # Details (Beschreibung) nur für die gefilterten Treffer nachladen
            detail_jobs = [(src, p) for src, p, _ in kept if not p.description and hasattr(src, "details")]
            detail_results = await gather_limited([src.details(client, p) for src, p in detail_jobs], limit=6)
            for (_src, p), res in zip(detail_jobs, detail_results, strict=True):
                if isinstance(res, BaseException):
                    log.info("Details für %s fehlgeschlagen: %s", p.url, res)
    finally:
        if renderer is not None:
            await renderer.__aexit__(None, None, None)

    report.kept = len(kept)
    touched: list[int] = []
    with session_scope(settings.db_path) as s:
        run = s.get(CrawlRun, run_id)
        assert run is not None
        seen_ids: set[int] = set()
        for _src, posting, where in kept:
            job_id, change = _upsert(s, run, posting, where, config, report)
            seen_ids.add(job_id)
            if change in ("new", "updated", "reopened", "merged"):
                touched.append(job_id)

        # Stellen, die in einer erfolgreich abgefragten Quelle nicht mehr auftauchen, gelten als geschlossen.
        open_jobs = s.execute(select(Job).where(Job.status == "open", Job.origin == "crawl")).scalars().all()
        for job in open_jobs:
            if job.source in ok_sources and job.id not in seen_ids:
                job.status = "closed"
                job.closed_at = utcnow()
                s.add(
                    JobSnapshot(
                        job=job,
                        crawl_run=run,
                        change="closed",
                        title=job.title,
                        location=job.location,
                        content_hash=job.content_hash,
                    )
                )
                report.closed.append(job.id)

        run.sources = [src.name for src in sources]
        run.errors = report.errors
        run.stats = {
            "fetched": report.fetched,
            "kept": report.kept,
            "new": len(report.new),
            "updated": len(report.updated),
            "reopened": len(report.reopened),
            "closed": len(report.closed),
            "merged_seeds": len(report.merged_seeds),
            "rejected": dict(report.rejected),
            "per_source": report.per_source,
        }
        run.status = "ok" if not report.errors else "partial"
        run.finished_at = utcnow()

    if enrich and llm is not None and profile is not None and touched:
        await enrich_jobs(settings, config, llm, profile, touched)
    return report


def _upsert(
    s: Session, run: CrawlRun, p: RawPosting, where: str, config: SearchConfig, report: CrawlReport
) -> tuple[int, str]:
    fp = fingerprint(p.source, p.external_id)
    mk = match_key(p.company, p.title)
    chash = content_hash(p.title, p.location, p.description)
    job = s.execute(select(Job).where(Job.fingerprint == fp)).scalars().first()
    change = "unchanged"

    if job is None:
        # Gleiche Stelle aus der Startliste (z. B. LinkedIn-Link)? Dann übernehmen und auf die direkte URL umstellen.
        twin = (
            s.execute(select(Job).where(Job.match_key == mk, Job.origin == "seed")).scalars().first()
            if mk
            else None
        )
        if twin is not None:
            job = twin
            if job.url and job.url != p.url:
                job.alt_urls = [*job.alt_urls, job.url]
            job.fingerprint = fp
            job.origin = "crawl"
            job.source = p.source
            job.external_id = p.external_id
            job.url = p.url
            job.apply_url = p.apply_url
            report.merged_seeds.append(job.id)
            change = "merged"
        else:
            job = Job(
                fingerprint=fp,
                match_key=mk,
                source=p.source,
                external_id=p.external_id,
                origin="crawl",
                company=p.company,
                title=p.title,
                url=p.url,
            )
            s.add(job)
            change = "new"

    diff: dict[str, Any] = {}
    if change == "unchanged":
        for attr, new in (("title", p.title), ("location", p.location)):
            if getattr(job, attr) != new:
                diff[attr] = [getattr(job, attr), new]
        if job.content_hash and job.content_hash != chash:
            diff["description"] = "geändert"
        if diff:
            change = "updated"
        if job.status == "closed":
            change = "reopened"

    meta = classify(
        company=p.company,
        title=p.title,
        description=p.description,
        where=where,
        near=bool(job.near and "km" in job.near),
        config=config,
    )
    job.company = p.company or job.company
    job.title = p.title
    job.match_key = mk
    job.location = p.location
    job.where = where
    job.workplace = _workplace(p, where) or job.workplace
    job.url = p.url or job.url
    job.apply_url = p.apply_url or job.apply_url
    job.description = p.description or job.description
    job.posted = p.posted or job.posted
    job.content_hash = chash
    job.last_seen = utcnow()
    job.status = "open"
    job.closed_at = None
    if not job.enrichment:  # LLM-Bewertung hat Vorrang vor Regeln
        job.category = str(meta["category"])
        job.level = str(meta["level"])
        job.fit = int(meta["fit"])  # type: ignore[arg-type]
        job.score = float(meta["score"])  # type: ignore[arg-type]
    else:
        job.category = str(meta["category"])
    job.segment = str(meta["segment"])
    job.language = str(meta["language"])
    s.flush()

    if change != "unchanged" or not job.snapshots:
        s.add(
            JobSnapshot(
                job=job,
                crawl_run=run,
                change=change,
                title=job.title,
                location=job.location,
                content_hash=chash,
                diff=diff,
            )
        )
    {"new": report.new, "updated": report.updated, "reopened": report.reopened}.get(change, []).append(job.id)
    return job.id, change


# --------------------------------------------------------------------------- LLM-Bewertung


class JobAssessment(BaseModel):
    required_years: int
    seniority: Literal["junior", "mid", "senior", "unklar"]
    fit: Literal[1, 2, 3]
    fit_reason: str
    german_required: bool
    workplace: Literal["Hybrid", "Vor Ort", "Remote", "unklar"]
    red_flags: list[str]
    summary: str


ASSESS_SYSTEM = """Du bewertest Stellenanzeigen für einen Bewerber. Antworte nüchtern und knapp auf Deutsch.

fit: 3 = Stack und Aufgaben passen stark zum Profil, 2 = teilweise, 1 = kaum.
seniority: aus Anforderungen ableiten (Jahre, Verantwortung), nicht nur aus dem Titel.
required_years: geforderte Mindestjahre, 0 wenn nicht genannt.
red_flags: z. B. "Sicherheitsüberprüfung", "befristet", "Reisebereitschaft 50 %", "nur Deutsch C2", "Senior trotz Titel".

Profil des Bewerbers:
{profile}
"""


class AssessedJob(JobAssessment):
    job_id: int


class AssessmentBatch(BaseModel):
    items: list[AssessedJob]


ENRICH_BATCH = 6  # mehrere Stellen pro Claude-Aufruf: schont das Abo-Kontingent


async def enrich_jobs(
    settings: Settings, config: SearchConfig, llm: LLM, profile: Profile, job_ids: list[int]
) -> int:
    system = ASSESS_SYSTEM.format(profile=profile.to_prompt())
    with session_scope(settings.db_path) as s:
        jobs = [
            (j.id, j.company, j.title, j.location, j.description)
            for j in s.execute(select(Job).where(Job.id.in_(job_ids))).scalars()
            if j.description
        ]
    batches = [jobs[i : i + ENRICH_BATCH] for i in range(0, len(jobs), ENRICH_BATCH)]
    limit_hit = asyncio.Event()

    async def assess(batch: list[tuple[int, str, str, str, str]]) -> list[tuple[int, JobAssessment]]:
        if limit_hit.is_set():
            return []
        parts = [
            f"## job_id={jid}\nFirma: {company}\nTitel: {title}\nOrt: {location}\n\nBeschreibung:\n{desc[:6000]}"
            for jid, company, title, location, desc in batch
        ]
        prompt = (
            f"Bewerte jede der folgenden {len(batch)} Stellen einzeln. Gib für jede genau ein Element in items "
            "zurück, mit ihrer job_id.\n\n" + "\n\n---\n\n".join(parts)
        )
        try:
            result = await llm.parse(
                AssessmentBatch, system=system, content=prompt, model=settings.llm_model_fast
            )
        except LLMLimitReached:
            limit_hit.set()
            raise
        wanted = {b[0] for b in batch}
        return [(item.job_id, item) for item in result.items if item.job_id in wanted]

    nested = await gather_limited([assess(b) for b in batches], limit=max(1, settings.claude_parallel))
    if limit_hit.is_set():
        log.warning(
            "Claude-Nutzungslimit erreicht – restliche Stellen bleiben unbewertet (später `jobpilot jobs enrich`)."
        )
    results: list[Any] = []
    for res in nested:
        if isinstance(res, BaseException):
            results.append(res)
        else:
            results.extend(res)
    count = 0
    with session_scope(settings.db_path) as s:
        for res in results:
            if isinstance(res, BaseException):
                log.warning("Bewertung fehlgeschlagen: %s", res)
                continue
            jid, a = res
            job = s.get(Job, jid)
            if job is None:
                continue
            level = {"junior": "J", "mid": "M", "senior": "S"}.get(a.seniority, job.level)
            if job.level == "S":  # Stretch-Markierung im Titel bleibt
                level = "S"
            job.level = level
            job.fit = int(a.fit)
            if a.workplace != "unklar":
                job.workplace = a.workplace
            job.enrichment = a.model_dump()
            job.score = score(
                job.category, job.fit, job.segment, job.level, bool(job.near and "km" in job.near), job.where
            )
            count += 1
    return count

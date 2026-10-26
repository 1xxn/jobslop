"""Stellen aus einer JSON-Datei importieren (z. B. eigene Recherche, Export aus einem anderen Tool).

Format: ``{"jobs": [...]}`` oder direkt eine Liste. Pflicht pro Eintrag: ``company``, ``title``, ``url``.
Optional: ``location``, ``description``, ``notes``, ``posted``, ``alt_urls``, ``status`` (``applied`` = schon
beworben, ``saved`` = gemerkt) sowie ``category``/``level``/``where``/``segment``/``fit`` zum Überschreiben der
automatischen Einordnung.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from .classify import classify, fingerprint, match_key, score, where_of
from .config import SearchConfig
from .db import Application, Job, JobSnapshot, session_scope, utcnow


def load_items(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("jobs", []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError('Erwartet eine Liste von Stellen oder {"jobs": [...]}')
    return items


def import_jobs(db_path: Path, path: Path, config: SearchConfig) -> tuple[int, int]:
    """Legt Stellen an; bereits importierte URLs werden übersprungen. Rückgabe: (neu, als beworben markiert)."""
    created = applied = 0
    with session_scope(db_path) as s:
        for item in load_items(path):
            company, title, url = (str(item.get(k, "")).strip() for k in ("company", "title", "url"))
            if not (company and title and url):
                continue
            fp = fingerprint("seed", url)  # gleicher Schlüssel wie frühere Importe
            if s.execute(select(Job.id).where(Job.fingerprint == fp)).first():
                continue
            location = str(item.get("location", ""))
            where = (
                item.get("where") or where_of(location, config.filters, "remote" in location.lower()) or "B"
            )
            near = str(item.get("near", ""))
            meta = classify(
                company=company,
                title=title,
                description=str(item.get("description", "")),
                where=where,
                near="km" in near,
                config=config,
            )
            category = str(item.get("category") or meta["category"])
            level = str(item.get("level") or meta["level"])
            segment = str(item.get("segment") or meta["segment"])
            fit = int(item.get("fit") or meta["fit"])  # type: ignore[call-overload]
            label = str(item.get("source_label", "") or "import").lower()
            job = Job(
                fingerprint=fp,
                match_key=match_key(company, title),
                source=f"seed:{label}",
                company=company,
                title=title,
                location=location or ("Remote" if where == "R" else ""),
                where=where,
                workplace=str(item.get("workplace", "")),
                url=url,
                alt_urls=list(item.get("alt_urls", [])),
                category=category,
                level=level,
                segment=segment,
                fit=fit,
                score=score(category, fit, segment, level, "km" in near, where, config.role_names),
                description=str(item.get("description", "")),
                posted=str(item.get("posted", "")),
                notes=str(item.get("notes", "")),
                near=near,
                origin="seed",
            )
            s.add(job)
            s.flush()
            s.add(JobSnapshot(job=job, change="imported", title=job.title, location=job.location))
            created += 1
            status = item.get("status") or item.get("linkedin_status")
            if status == "applied":
                s.add(
                    Application(
                        job=job,
                        status="submitted",
                        origin="import",
                        mode="manual",
                        submitted_at=utcnow(),
                        finished_at=utcnow(),
                        confirmation=f"Importiert aus {path.name}: bereits beworben",
                    )
                )
                applied += 1
            elif status == "saved":
                job.starred = True
    return created, applied

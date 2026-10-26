"""Import der Startliste (Recherche vom 26.10.2026)."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

from sqlalchemy import select

from ..classify import fingerprint, match_key, score
from ..db import Application, Job, JobSnapshot, session_scope, utcnow

SEED_FILE = "jobs_2026-10-26.json"


def load_seed_data(path: Path | None = None) -> dict:
    if path is not None:
        return json.loads(path.read_text(encoding="utf-8"))
    return json.loads(resources.files(__package__).joinpath(SEED_FILE).read_text(encoding="utf-8"))


def import_seeds(db_path: Path, path: Path | None = None) -> tuple[int, int]:
    """Legt Jobs aus der Startliste an. Bereits bekannte URLs werden übersprungen.

    Rückgabe: (neu angelegte Jobs, importierte "schon beworben"-Einträge)
    """
    data = load_seed_data(path)
    created = applied = 0
    with session_scope(db_path) as s:
        for item in data["jobs"]:
            fp = fingerprint("seed", item["url"])
            if s.execute(select(Job.id).where(Job.fingerprint == fp)).first():
                continue
            near = item.get("near", "")
            job = Job(
                fingerprint=fp,
                match_key=match_key(item["company"], item["title"]),
                source="seed:" + item.get("source_label", "").lower(),
                external_id="",
                company=item["company"],
                title=item["title"],
                location="Berlin" if item["where"] != "R" else "Remote, Deutschland",
                where=item["where"],
                workplace=item.get("workplace", ""),
                url=item["url"],
                alt_urls=item.get("alt_urls", []),
                category=item["category"],
                level=item["level"],
                segment=item["segment"],
                fit=int(item["fit"]),
                score=score(
                    item["category"],
                    int(item["fit"]),
                    item["segment"],
                    item["level"],
                    "km" in near,
                    item["where"],
                ),
                posted=item.get("posted", ""),
                notes=item.get("notes", ""),
                near=near,
                origin="seed",
            )
            s.add(job)
            s.flush()
            s.add(JobSnapshot(job=job, change="imported", title=job.title, location=job.location))
            created += 1
            if item.get("linkedin_status") == "applied":
                s.add(
                    Application(
                        job=job,
                        status="submitted",
                        origin="import",
                        mode="manual",
                        submitted_at=utcnow(),
                        finished_at=utcnow(),
                        confirmation="Laut LinkedIn bereits beworben (Import 26.10.2026)",
                    )
                )
                applied += 1
            elif item.get("linkedin_status") == "saved":
                job.notes = (job.notes + " Auf LinkedIn gemerkt.").strip()
    return created, applied

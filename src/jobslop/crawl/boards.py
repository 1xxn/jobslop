"""Firmen-Boards entdecken: Firmen aus Jobbörsen auf ein öffentliches Bewerbungssystem prüfen.

Jobbörsen (Himalayas, LinkedIn, Arbeitsagentur …) verlinken oft nur auf sich selbst – teils hinter Bot-Abfragen,
die im automatisierten Browser endlos hängen. Hat die Firma ein Board bei Greenhouse, Ashby, Lever, Recruitee,
Workable oder Personio, fragt jobslop es direkt ab: vollständige Daten, direkte Bewerbungs-URL – und die Stelle
ersetzt den Börsen-Eintrag. Als gefunden gilt ein Board nur, wenn dort dieselbe Stelle steht (sonst gehört der
Name womöglich einer anderen Firma).
"""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from datetime import timedelta
from typing import Any

import httpx
from sqlalchemy import select

from ..classify import match_key
from ..db import Board, session_scope, utcnow
from ..guard import company_key
from .base import RawPosting, single_attempt
from .sources import BOARD_SOURCES, gather_limited

log = logging.getLogger(__name__)

# In dieser Reihenfolge geraten (SmartRecruiters-IDs lassen sich nicht sinnvoll aus dem Namen ableiten)
DISCOVERABLE = ("greenhouse", "ashby", "lever", "recruitee", "workable", "personio")
RECHECK_DAYS = 30  # Firmen ohne Board erst nach so vielen Tagen erneut prüfen

_LEGAL_RX = re.compile(
    r"\b(gmbh|mbh|ag|se|kg|kgaa|co|inc|ltd|llc|plc|corp|corporation|s\.?a\.?|b\.?v\.?|n\.?v\.?|oy|ab|"
    r"group|gruppe|holding|deutschland|germany|europe|technologies|technology|software)\b\.?",
)


def slug_candidates(company: str) -> list[str]:
    """Wahrscheinliche Board-Namen: „Acme Cloud GmbH“ → acmecloud, acme-cloud."""
    name = unicodedata.normalize("NFKD", company).encode("ascii", "ignore").decode().lower()
    name = re.sub(r"\(.*?\)|&", " ", name)
    words = re.findall(r"[a-z0-9]+", _LEGAL_RX.sub(" ", name))
    if not words:
        return []
    return list(dict.fromkeys(s for s in ("".join(words), "-".join(words)) if len(s) >= 2))


async def _probe(client: httpx.AsyncClient, kind: str, slug: str, company: str) -> list[RawPosting] | None:
    """Fragt ein geratenes Board über seine Quelle ab – ohne Wiederholungen. None = gibt es nicht."""
    with single_attempt():
        try:
            return await board_source(kind, slug, company).fetch(client)
        except Exception:  # 404, Zeitüberschreitung, kein XML …: kein Board unter diesem Namen
            return None


async def find_board(
    client: httpx.AsyncClient, company: str, titles: list[str]
) -> tuple[str, str, list[RawPosting]] | None:
    """Sucht ein Board, auf dem mindestens eine der Stellen steht. Alle Kandidaten parallel, Vorrang nach
    Reihenfolge. Rückgabe: (Art, Name, Stellen des Boards) – die Stellen werden gleich weiterverwendet."""
    candidates = [(slug, kind) for slug in slug_candidates(company) for kind in DISCOVERABLE]
    results = await asyncio.gather(*(_probe(client, kind, slug, company) for slug, kind in candidates))
    wanted = {match_key(company, t) for t in titles}
    for (slug, kind), postings in zip(candidates, results, strict=True):
        if postings and wanted & {match_key(company, p.title) for p in postings}:
            return kind, slug, postings
    return None


def board_source(kind: str, slug: str, company: str) -> Any:
    # Der Firmenname aus der Jobbörse sorgt dafür, dass beide Einträge dieselbe Stelle ergeben (match_key)
    return BOARD_SOURCES[kind](f"{slug}:{company}")


def known_board_sources(db_path: Any, skip: set[str]) -> list[Any]:
    """Früher entdeckte Boards, die nicht ohnehin in search.toml stehen."""
    with session_scope(db_path) as s:
        rows = s.execute(select(Board).where(Board.enabled, Board.kind != "")).scalars().all()
        sources = [board_source(b.kind, b.slug, b.company) for b in rows]
    return [src for src in sources if src.name not in skip]


async def discover(
    client: httpx.AsyncClient, db_path: Any, postings: list[RawPosting], *, limit: int
) -> list[tuple[Any, list[RawPosting]]]:
    """Prüft bis zu ``limit`` noch unbekannte Firmen aus Jobbörsen-Treffern.

    Rückgabe: (Quelle, ihre Stellen) für neu gefundene Boards – schon abgefragt, nicht noch einmal laden.
    """
    by_company: dict[str, tuple[str, list[str]]] = {}
    for p in postings:
        key = company_key(p.company)
        if key:
            by_company.setdefault(key, (p.company, []))[1].append(p.title)
    stale = utcnow() - timedelta(days=RECHECK_DAYS)
    with session_scope(db_path) as s:
        checked = {
            b.company_key for b in s.execute(select(Board)).scalars() if b.kind or b.checked_at >= stale
        }
    todo = [(key, name, titles) for key, (name, titles) in by_company.items() if key not in checked][:limit]
    if not todo:
        return []
    results = await gather_limited([find_board(client, name, titles) for _, name, titles in todo], limit=4)
    found = []
    with session_scope(db_path) as s:
        rows = {b.company_key: b for b in s.execute(select(Board)).scalars()}
        for (key, name, _titles), res in zip(todo, results, strict=True):
            hit = None if isinstance(res, BaseException) else res
            row = rows.get(key) or Board(company_key=key, company=name)
            s.add(row)
            row.company, row.checked_at = name, utcnow()
            row.kind, row.slug, row.jobs = (hit[0], hit[1], len(hit[2])) if hit else ("", "", 0)
            if hit:
                found.append((board_source(row.kind, row.slug, name), hit[2]))
                log.info("Board gefunden: %s → %s:%s (%s Stellen)", name, row.kind, row.slug, row.jobs)
    return found

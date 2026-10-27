"""Firmen-Boards entdecken: Firmen aus Jobbörsen auf ein öffentliches Bewerbungssystem prüfen.

Jobbörsen (Himalayas, LinkedIn, Arbeitsagentur …) verlinken oft nur auf sich selbst – teils hinter Bot-Abfragen,
die im automatisierten Browser endlos hängen. Hat die Firma ein Board bei Greenhouse, Ashby, Lever, Recruitee,
Workable oder Personio, fragt jobslop es direkt ab: vollständige Daten, direkte Bewerbungs-URL – und die Stelle
ersetzt den Börsen-Eintrag. Als gefunden gilt ein Board nur, wenn dort dieselbe Stelle steht (sonst gehört der
Name womöglich einer anderen Firma).
"""

from __future__ import annotations

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
from .base import RawPosting
from .sources import (
    AshbySource,
    GreenhouseSource,
    LeverSource,
    PersonioSource,
    RecruiteeSource,
    WorkableSource,
    gather_limited,
)

log = logging.getLogger(__name__)

SOURCE_TYPES: dict[str, Any] = {
    "greenhouse": GreenhouseSource,
    "ashby": AshbySource,
    "lever": LeverSource,
    "recruitee": RecruiteeSource,
    "workable": WorkableSource,
    "personio": PersonioSource,
}
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


async def _board_titles(client: httpx.AsyncClient, kind: str, slug: str) -> list[str] | None:
    """Stellentitel eines Boards – oder None, wenn es das Board nicht gibt. Ohne Wiederholungen: es wird geraten."""
    urls = {
        "greenhouse": [f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"],
        "ashby": [f"https://api.ashbyhq.com/posting-api/job-board/{slug}"],
        "lever": [
            f"https://api.lever.co/v0/postings/{slug}?mode=json",
            f"https://api.eu.lever.co/v0/postings/{slug}?mode=json",
        ],
        "recruitee": [f"https://{slug}.recruitee.com/api/offers/"],
        "workable": [f"https://apply.workable.com/api/v1/widget/accounts/{slug}"],
        "personio": [f"https://{slug}.jobs.personio.de/xml"],
    }[kind]
    for url in urls:
        try:
            resp = await client.get(url, timeout=10)
        except httpx.HTTPError:
            continue
        if resp.status_code != 200:
            continue
        if kind == "personio":
            return re.findall(r"<name>([^<]+)</name>", resp.text) if "<workzag-jobs" in resp.text else None
        try:
            data = resp.json()
        except ValueError:
            continue
        items = data if isinstance(data, list) else data.get({"recruitee": "offers"}.get(kind, "jobs"), [])
        if isinstance(items, list):
            return [str(i.get("title") or i.get("text") or "") for i in items if isinstance(i, dict)]
    return None


async def find_board(
    client: httpx.AsyncClient, company: str, titles: list[str]
) -> tuple[str, str, int] | None:
    """Sucht ein Board, auf dem mindestens eine der Stellen steht. Rückgabe: (Art, Name, Anzahl Stellen)."""
    wanted = {match_key(company, t) for t in titles}
    for slug in slug_candidates(company):
        for kind in SOURCE_TYPES:
            found = await _board_titles(client, kind, slug)
            if found and wanted & {match_key(company, t) for t in found}:
                return kind, slug, len(found)
    return None


def board_source(kind: str, slug: str, company: str) -> Any:
    # Der Firmenname aus der Jobbörse sorgt dafür, dass beide Einträge dieselbe Stelle ergeben (match_key)
    return SOURCE_TYPES[kind](f"{slug}:{company}")


def known_board_sources(db_path: Any, skip: set[str]) -> list[Any]:
    """Früher entdeckte Boards, die nicht ohnehin in search.toml stehen."""
    with session_scope(db_path) as s:
        rows = s.execute(select(Board).where(Board.enabled, Board.kind != "")).scalars().all()
        sources = [board_source(b.kind, b.slug, b.company) for b in rows]
    return [src for src in sources if src.name not in skip]


async def discover(
    client: httpx.AsyncClient, db_path: Any, postings: list[RawPosting], *, limit: int
) -> list[Any]:
    """Prüft bis zu ``limit`` noch unbekannte Firmen aus Jobbörsen-Treffern und gibt Quellen für neue Boards zurück."""
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
    results = await gather_limited([find_board(client, name, titles) for _, name, titles in todo], limit=6)
    found = []
    with session_scope(db_path) as s:
        for (key, name, _titles), res in zip(todo, results, strict=True):
            hit = None if isinstance(res, BaseException) else res
            row = s.execute(select(Board).where(Board.company_key == key)).scalars().first()
            if row is None:
                row = Board(company_key=key, company=name)
                s.add(row)
            row.company, row.checked_at = name, utcnow()
            row.kind, row.slug, row.jobs = hit or ("", "", 0)
            if hit:
                found.append(board_source(row.kind, row.slug, name))
                log.info("Board gefunden: %s → %s:%s (%s Stellen)", name, row.kind, row.slug, row.jobs)
    return found

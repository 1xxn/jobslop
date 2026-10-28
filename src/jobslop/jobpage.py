"""Eine Stelle per Link hinzufügen.

Reihenfolge: strukturierte Daten der Seite (schema.org ``JobPosting`` – liefern fast alle Karriereseiten für
Google Jobs) → Meta-Tags → gerenderte Seite + Claude. So kostet das Hinzufügen meist kein Abo-Kontingent.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel
from sqlalchemy import select

from .classify import classify, content_hash, fingerprint, html_to_text, job_score, match_key, where_of
from .config import SearchConfig
from .db import Job, JobSnapshot, session_scope

log = logging.getLogger(__name__)


class _Head(HTMLParser):
    """JSON-LD-Blöcke, Meta-Angaben und den Titel einer Seite einsammeln – in einem Durchgang und in linearer Zeit
    (die früheren Regexes ließen sich mit präpariertem HTML ausbremsen, CodeQL py/polynomial-redos)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ld: list[str] = []
        self.meta: dict[str, str] = {}
        self.title = ""
        self._open: str | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): v or "" for k, v in attrs}
        if tag == "script" and a.get("type", "").strip().lower() == "application/ld+json":
            self._open, self._buf = "ld", []
        elif tag == "title" and not self.title:
            self._open, self._buf = "title", []
        elif tag == "meta" and "content" in a and (key := (a.get("property") or a.get("name") or "").lower()):
            self.meta.setdefault(key, a["content"])

    def handle_endtag(self, tag: str) -> None:
        if self._open == "ld" and tag == "script":
            self.ld.append("".join(self._buf))
            self._open = None
        elif self._open == "title" and tag == "title":
            self.title = " ".join("".join(self._buf).split())
            self._open = None

    def handle_data(self, data: str) -> None:
        if self._open:
            self._buf.append(data)


def _head(html: str) -> _Head:
    parser = _Head()
    parser.feed(html)
    parser.close()
    return parser


def _site_title(title: str) -> str:
    """„Platform Engineer | Acme – Karriere“ → „Platform Engineer“ (ohne Regex)."""
    title = " ".join(title.split())
    cuts = [i for sep in (" | ", " – ", " - ") if (i := title.find(sep)) > 0]
    return title[: min(cuts)].strip() if cuts else title


@dataclass
class FetchedJob:
    url: str
    title: str = ""
    company: str = ""
    location: str = ""
    description: str = ""
    posted: str = ""
    remote: bool = False
    via: str = ""  # jsonld | meta | claude


class _Extracted(BaseModel):
    title: str
    company: str
    location: str
    remote: bool


def _walk(node: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, list):
        for item in node:
            found += _walk(item)
    elif isinstance(node, dict):
        kind = node.get("@type")
        kinds = kind if isinstance(kind, list) else [kind]
        if "JobPosting" in kinds:
            found.append(node)
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in node:
                found += _walk(node[key])
    return found


def _location(posting: dict[str, Any]) -> str:
    locs = posting.get("jobLocation") or []
    locs = locs if isinstance(locs, list) else [locs]
    parts = []
    for loc in locs:
        addr = (loc or {}).get("address") or {}
        if isinstance(addr, str):
            parts.append(addr)
            continue
        country = addr.get("addressCountry")
        if isinstance(country, dict):
            country = country.get("name", "")
        text = ", ".join(str(x) for x in (addr.get("addressLocality"), country) if x)
        if text:
            parts.append(text)
    return "; ".join(dict.fromkeys(parts))


def parse_html(url: str, html: str) -> FetchedJob:
    job = FetchedJob(url=url)
    head = _head(html)
    for raw in head.ld:
        try:
            data = json.loads(raw.strip())
        except json.JSONDecodeError:
            continue
        postings = _walk(data)
        if not postings:
            continue
        p = postings[0]
        org = p.get("hiringOrganization") or {}
        job.title = unescape(str(p.get("title") or "")).strip()
        job.company = unescape(str(org.get("name") if isinstance(org, dict) else org or "")).strip()
        job.location = _location(p)
        job.description = html_to_text(str(p.get("description") or ""))
        job.posted = str(p.get("datePosted") or "")[:10]
        job.remote = "TELECOMMUTE" in str(p.get("jobLocationType") or "").upper()
        if job.remote and "remote" not in job.location.lower():
            job.location = ", ".join(x for x in (job.location, "Remote") if x)
        job.via = "jsonld"
        if job.title:
            return job
    meta = head.meta
    title = meta.get("og:title") or head.title
    job.title = _site_title(title) if title else ""
    job.company = meta.get("og:site_name", "")
    job.description = meta.get("og:description") or meta.get("description", "")
    job.via = "meta"
    return job


async def fetch_job(url: str, *, llm: Any = None, render: Any = None, fast_model: str = "") -> FetchedJob:
    if not re.match(r"https?://", url):
        raise ValueError("Bitte einen vollständigen Link (https://…) angeben")
    html = ""
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; jobslop/1.0)"})
            if resp.status_code < 400:
                html = resp.text
    except httpx.HTTPError as exc:
        log.info("Abruf von %s fehlgeschlagen: %s", url, exc)
    job = parse_html(url, html) if html else FetchedJob(url=url)
    if job.via == "jsonld" and job.company:
        return job
    text = ""
    if render is not None:
        try:
            text, _links = await render(url)
        except Exception as exc:
            log.info("Rendern von %s fehlgeschlagen: %s", url, exc)
    if llm is not None and (text or html):
        content = text or html_to_text(html)
        result = await llm.parse(
            _Extracted,
            system="Lies aus der Stellenanzeige Titel, Firma, Ort und ob die Stelle remote ist. Nichts erfinden; "
            "Unbekanntes als leerer String.",
            content=f"URL: {url}\n\n{content[:12000]}",
            model=fast_model or None,
            max_tokens=800,
            cache_system=False,
        )
        job.title = result.title or job.title
        job.company = result.company or job.company
        job.location = result.location or job.location
        job.remote = result.remote or job.remote
        job.description = job.description or content[:20000]
        job.via = "claude"
    if not job.company:
        job.company = company_from_url(url)
    if not job.title:
        raise ValueError("Auf der Seite wurde keine Stellenanzeige erkannt")
    return job


def company_from_url(url: str) -> str:
    """Notlösung ohne Firmennamen auf der Seite: „jobs.acme-cloud.de“ → „Jobs“ wäre falsch, also der erste Teil
    nach typischen Karriere-Präfixen."""
    parts = (urlparse(url).hostname or "").removeprefix("www.").split(".")
    while len(parts) > 2 and parts[0] in ("jobs", "careers", "karriere", "career", "apply", "boards"):
        parts = parts[1:]
    return parts[0].replace("-", " ").title() if parts and parts[0] else "Unbekannt"


def add_fetched_job(
    db_path: Any, config: SearchConfig, fetched: FetchedJob, *, source: str = "manual"
) -> tuple[int, bool]:
    """Legt die Stelle an (oder findet sie wieder). Rückgabe: (Job-ID, neu angelegt).

    ``source`` ist „manual“ (Per Link, gemerkt) oder „extension“ (aus der Browser-Erweiterung).
    """
    fp = fingerprint(source, fetched.url)
    with session_scope(db_path) as s:
        existing = (
            s.execute(select(Job).where((Job.fingerprint == fp) | (Job.url == fetched.url))).scalars().first()
        )
        if existing is not None:
            return existing.id, False
        where = where_of(fetched.location, config.filters, fetched.remote) or ("R" if fetched.remote else "B")
        meta = classify(
            company=fetched.company,
            title=fetched.title,
            description=fetched.description,
            where=where,
            near=False,
            config=config,
        )
        job = Job(
            fingerprint=fp,
            match_key=match_key(fetched.company, fetched.title),
            source=source,
            company=fetched.company,
            title=fetched.title,
            location=fetched.location,
            where=where,
            workplace="Remote" if fetched.remote else "",
            url=fetched.url,
            description=fetched.description,
            content_hash=content_hash(fetched.title, fetched.location, fetched.description),
            posted=fetched.posted,
            origin="manual",
            category=str(meta["category"]),
            level=str(meta["level"]),
            segment=str(meta["segment"]),
            fit=int(meta["fit"]),  # type: ignore[call-overload]
            language=str(meta["language"]),
            starred=source == "manual",
        )
        job.score = job_score(job, config.role_names)
        s.add(job)
        s.flush()
        s.add(JobSnapshot(job=job, change="new", title=job.title, location=job.location))
        return job.id, True

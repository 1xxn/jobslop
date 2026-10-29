"""Eine Stelle per Link hinzufügen.

Reihenfolge: strukturierte Daten der Seite (schema.org ``JobPosting`` – liefern fast alle Karriereseiten für
Google Jobs) → Meta-Tags → gerenderte Seite + Claude. So kostet das Hinzufügen meist kein Abo-Kontingent.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from html import unescape
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel
from sqlalchemy import select

from .classify import classify, content_hash, fingerprint, html_to_text, job_score, match_key, where_of
from .config import SearchConfig
from .db import Job, JobSnapshot, session_scope
from .netguard import BlockedTarget, is_public_url, public_client, read_limited

log = logging.getLogger(__name__)


_MAX_HTML = 3_000_000  # Stellenseiten sind weit kleiner; mehr wird nicht gelesen
_FETCH_BUDGET_S = 30  # Gesamtzeit für Abruf samt Weiterleitungen
_WS = " \t\r\n\f"


@dataclass
class _Head:
    """JSON-LD-Blöcke, Meta-Angaben und Titel einer fremden Seite. Gelesen wird mit str.find in linearer Zeit und
    ohne Regex – Regexes und (auf manchen Python-Versionen) html.parser ließen sich mit präpariertem HTML ausbremsen
    (CodeQL py/polynomial-redos)."""

    ld: list[str]
    meta: dict[str, str]
    title: str


def _open_tags(html: str, low: str, name: str) -> Any:
    """Öffnende Tags <name …>: (Tag-Text, Position hinter „>“). Jedes Zeichen wird höchstens einmal überflogen."""
    needle, pos = "<" + name, 0
    while (start := low.find(needle, pos)) != -1:
        after = start + len(needle)
        if after < len(low) and low[after] not in _WS + "/>":  # <scripts, <metadata …
            pos = after
            continue
        end = low.find(">", after)
        if end == -1:
            return
        yield html[start : end + 1], end + 1
        pos = end + 1


def _attr(tag: str, name: str) -> str:
    """Wert eines Attributs im Tag-Text (Anführungszeichen optional), ohne Regex."""
    low, i = tag.lower(), 0
    while (i := low.find(name, i)) != -1:
        k = i + len(name)
        if i > 0 and low[i - 1] in _WS:
            while k < len(low) and low[k] in _WS:
                k += 1
            if k < len(low) and low[k] == "=":
                k += 1
                while k < len(low) and low[k] in _WS:
                    k += 1
                if k < len(tag) and tag[k] in "\"'":
                    close = tag.find(tag[k], k + 1)
                    return unescape(tag[k + 1 : close]) if close != -1 else ""
                stop = k
                while stop < len(tag) and tag[stop] not in _WS + ">":
                    stop += 1
                return unescape(tag[k:stop])
        i += len(name)
    return ""


def _head(html: str) -> _Head:
    html = html[:_MAX_HTML]
    low = html.lower()
    ld: list[str] = []
    pos = 0
    while (start := low.find("<script", pos)) != -1:
        tag_end = low.find(">", start)
        if tag_end == -1:
            break
        close = low.find("</script", tag_end)
        if close == -1:
            break
        if "application/ld+json" in low[start:tag_end]:
            ld.append(html[tag_end + 1 : close])
        pos = close + 8  # hinter „</script“ weiter – Inhalt nie doppelt durchsuchen
    meta: dict[str, str] = {}
    for tag, _after in _open_tags(html, low, "meta"):
        key = (_attr(tag, "property") or _attr(tag, "name")).lower()
        if key and key not in meta and " content" in tag.lower().replace("\n", " ").replace("\t", " "):
            meta[key] = _attr(tag, "content")
    title = ""
    for _tag, after in _open_tags(html, low, "title"):
        close = low.find("</title", after)
        if close != -1:
            title = " ".join(unescape(html[after:close]).split())
        break
    return _Head(ld, meta, title)


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


_MAX_LD_DEPTH = 20  # JobPostings stecken höchstens in @graph/itemListElement – tiefer sucht niemand


def _walk(node: Any, depth: int = 0) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if depth > _MAX_LD_DEPTH:
        return found
    if isinstance(node, list):
        for item in node:
            found += _walk(item, depth + 1)
    elif isinstance(node, dict):
        kind = node.get("@type")
        kinds = kind if isinstance(kind, list) else [kind]
        if "JobPosting" in kinds:
            found.append(node)
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in node:
                found += _walk(node[key], depth + 1)
    return found


def _location(posting: dict[str, Any]) -> str:
    # Fremdes JSON-LD: jobLocation und address kommen als Objekt, Liste, Text oder Unsinn
    locs = posting.get("jobLocation") or []
    locs = locs if isinstance(locs, list) else [locs]
    parts = []
    for loc in locs:
        if isinstance(loc, str):
            parts.append(loc)
            continue
        addr = loc.get("address") if isinstance(loc, dict) else None
        if isinstance(addr, str):
            parts.append(addr)
            continue
        if not isinstance(addr, dict):
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
        except (json.JSONDecodeError, RecursionError):  # „[[[[…“ tiefer als Pythons Rekursionsgrenze
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


async def _download(url: str, allow_private: bool) -> str:
    """Seite laden – nur von öffentlichen Adressen (auch nach Weiterleitungen), höchstens ``_MAX_HTML`` Bytes und
    ``_FETCH_BUDGET_S`` Sekunden. Der Link kommt von dir, die Seite (und wohin sie weiterleitet) von fremden Servern."""
    client = (
        httpx.AsyncClient(timeout=20, follow_redirects=True, max_redirects=5)
        if allow_private
        else public_client()
    )
    async with asyncio.timeout(_FETCH_BUDGET_S), client:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; jobslop/1.0)", "Accept": "text/html,*/*;q=0.5"}
        async with client.stream("GET", url, headers=headers) as resp:
            if resp.status_code >= 400:
                return ""
            data = await read_limited(resp, _MAX_HTML)
            return data.decode(resp.encoding or "utf-8", errors="replace")


async def fetch_job(
    url: str, *, llm: Any = None, render: Any = None, fast_model: str = "", allow_private: bool = False
) -> FetchedJob:
    if not re.match(r"https?://", url):
        raise ValueError("Bitte einen vollständigen Link (https://…) angeben")
    if not allow_private and not is_public_url(url):
        raise BlockedTarget("Dieser Link zeigt in dein eigenes Netz – jobslop lädt nur öffentliche Seiten")
    html = ""
    try:
        html = await _download(url, allow_private)
    except (httpx.HTTPError, TimeoutError) as exc:
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

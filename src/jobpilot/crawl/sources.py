"""Quellen-Adapter für öffentliche Job-Board-APIs und beliebige Karriereseiten."""

from __future__ import annotations

import asyncio
import logging
import xml.etree.ElementTree as ET
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from pydantic import BaseModel

from ..classify import html_to_text
from ..config import GenericPage, SearchConfig, WorkdaySite
from .base import RawPosting, SourceError, get_json, get_text, post_json

log = logging.getLogger(__name__)


def split_slug(entry: str) -> tuple[str, str]:
    """Erlaubt ``"slug"`` oder ``"slug:Anzeigename"`` in search.toml."""
    if ":" in entry:
        slug, name = entry.split(":", 1)
        return slug.strip(), name.strip()
    return entry.strip(), ""


def pretty(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").title()


# --------------------------------------------------------------------------- Greenhouse


class GreenhouseSource:
    def __init__(self, entry: str) -> None:
        self.board, self.company = split_slug(entry)
        self.name = f"greenhouse:{self.board}"

    async def fetch(self, client: httpx.AsyncClient) -> list[RawPosting]:
        base = f"https://boards-api.greenhouse.io/v1/boards/{self.board}"
        if not self.company:
            try:
                meta = await get_json(client, base)
                self.company = meta.get("name") or pretty(self.board)
            except Exception:
                self.company = pretty(self.board)
        data = await get_json(client, f"{base}/jobs", params={"content": "true"})
        return [self._posting(j) for j in data.get("jobs", [])]

    def _posting(self, j: dict[str, Any]) -> RawPosting:
        location = (j.get("location") or {}).get("name", "")
        offices = ", ".join(o.get("name", "") for o in j.get("offices", []) if o.get("name"))
        if offices and offices not in location:
            location = f"{location}; {offices}" if location else offices
        return RawPosting(
            source=self.name,
            external_id=str(j["id"]),
            company=j.get("company_name") or self.company,
            title=j.get("title", "").strip(),
            location=location,
            url=j.get("absolute_url", ""),
            description=html_to_text(j.get("content", "")),
            posted=(j.get("first_published") or j.get("updated_at") or "")[:10],
        )


# --------------------------------------------------------------------------- Ashby


class AshbySource:
    def __init__(self, entry: str) -> None:
        self.board, self.company = split_slug(entry)
        self.company = self.company or pretty(self.board)
        self.name = f"ashby:{self.board}"

    async def fetch(self, client: httpx.AsyncClient) -> list[RawPosting]:
        data = await get_json(client, f"https://api.ashbyhq.com/posting-api/job-board/{self.board}")
        out = []
        for j in data.get("jobs", []):
            if j.get("isListed") is False:
                continue
            locations = [j.get("location", "")] + [
                s.get("location", "") for s in j.get("secondaryLocations", [])
            ]
            workplace = {"Remote": "Remote", "Hybrid": "Hybrid", "OnSite": "Vor Ort"}.get(
                j.get("workplaceType", ""), ""
            )
            out.append(
                RawPosting(
                    source=self.name,
                    external_id=str(j["id"]),
                    company=self.company,
                    title=j.get("title", "").strip(),
                    location="; ".join(x for x in locations if x),
                    url=j.get("jobUrl", ""),
                    apply_url=j.get("applyUrl", ""),
                    description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml", "")),
                    posted=(j.get("publishedAt") or "")[:10],
                    remote=bool(j.get("isRemote")),
                    workplace=workplace,
                )
            )
        return out


# --------------------------------------------------------------------------- Lever


class LeverSource:
    def __init__(self, entry: str) -> None:
        self.slug, self.company = split_slug(entry)
        self.company = self.company or pretty(self.slug)
        self.name = f"lever:{self.slug}"

    async def fetch(self, client: httpx.AsyncClient) -> list[RawPosting]:
        data = None
        for host in ("api.lever.co", "api.eu.lever.co"):
            try:
                data = await get_json(
                    client, f"https://{host}/v0/postings/{self.slug}", params={"mode": "json"}
                )
                break
            except SourceError:
                continue
        if data is None:
            raise SourceError(f"Lever-Board '{self.slug}' nicht gefunden")
        out = []
        for j in data:
            cats = j.get("categories") or {}
            locations = cats.get("allLocations") or [cats.get("location", "")]
            wt = (j.get("workplaceType") or "").lower()
            out.append(
                RawPosting(
                    source=self.name,
                    external_id=str(j["id"]),
                    company=self.company,
                    title=j.get("text", "").strip(),
                    location="; ".join(x for x in locations if x),
                    url=j.get("hostedUrl", ""),
                    apply_url=j.get("applyUrl", ""),
                    description=j.get("descriptionPlain", "")
                    + "\n"
                    + "\n".join(
                        f"{lst.get('text', '')}\n{html_to_text(lst.get('content', ''))}"
                        for lst in j.get("lists", [])
                    ),
                    remote=wt == "remote",
                    workplace={"remote": "Remote", "hybrid": "Hybrid", "onsite": "Vor Ort"}.get(wt, ""),
                )
            )
        return out


# --------------------------------------------------------------------------- SmartRecruiters


class SmartRecruitersSource:
    def __init__(self, entry: str) -> None:
        self.company_id, self.company = split_slug(entry)
        self.name = f"smartrecruiters:{self.company_id}"

    async def fetch(self, client: httpx.AsyncClient) -> list[RawPosting]:
        out: list[RawPosting] = []
        offset = 0
        while True:
            data = await get_json(
                client,
                f"https://api.smartrecruiters.com/v1/companies/{self.company_id}/postings",
                params={"country": "de", "limit": 100, "offset": offset},
            )
            content = data.get("content", [])
            for j in content:
                loc = j.get("location") or {}
                out.append(
                    RawPosting(
                        source=self.name,
                        external_id=str(j["id"]),
                        company=self.company or (j.get("company") or {}).get("name") or self.company_id,
                        title=j.get("name", "").strip(),
                        location=loc.get("fullLocation")
                        or ", ".join(x for x in (loc.get("city"), loc.get("country")) if x),
                        url=f"https://jobs.smartrecruiters.com/{self.company_id}/{j['id']}",
                        posted=(j.get("releasedDate") or "")[:10],
                        remote=bool(loc.get("remote")),
                    )
                )
            offset += len(content)
            if not content or offset >= data.get("totalFound", 0):
                break
        return out

    async def details(self, client: httpx.AsyncClient, posting: RawPosting) -> RawPosting:
        data = await get_json(
            client,
            f"https://api.smartrecruiters.com/v1/companies/{self.company_id}/postings/{posting.external_id}",
        )
        sections = (data.get("jobAd") or {}).get("sections") or {}
        posting.description = "\n\n".join(
            f"{s.get('title', '')}\n{html_to_text(s.get('text', ''))}"
            for s in sections.values()
            if isinstance(s, dict)
        )
        posting.apply_url = data.get("applyUrl", "") or posting.apply_url
        return posting


# --------------------------------------------------------------------------- Personio


class PersonioSource:
    def __init__(self, entry: str) -> None:
        self.slug, self.company = split_slug(entry)
        self.name = f"personio:{self.slug}"

    async def fetch(self, client: httpx.AsyncClient) -> list[RawPosting]:
        xml = await get_text(client, f"https://{self.slug}.jobs.personio.de/xml?language=de")
        root = ET.fromstring(xml)
        out = []
        for pos in root.findall("position"):
            pid = (pos.findtext("id") or "").strip()
            offices = [pos.findtext("office") or ""] + [
                o.text or "" for o in pos.findall("additionalOffices/office")
            ]
            descs = [
                f"{d.findtext('name') or ''}\n{html_to_text(d.findtext('value') or '')}"
                for d in pos.findall("jobDescriptions/jobDescription")
            ]
            out.append(
                RawPosting(
                    source=self.name,
                    external_id=pid,
                    company=self.company or (pos.findtext("subcompany") or "").strip() or pretty(self.slug),
                    title=(pos.findtext("name") or "").strip(),
                    location="; ".join(x.strip() for x in offices if x and x.strip()),
                    url=f"https://{self.slug}.jobs.personio.de/job/{pid}",
                    description="\n\n".join(descs),
                    posted=(pos.findtext("createdAt") or "")[:10],
                    extra={
                        "seniority": pos.findtext("seniority") or "",
                        "years": pos.findtext("yearsOfExperience") or "",
                    },
                )
            )
        return out


# --------------------------------------------------------------------------- Workday


class WorkdaySource:
    def __init__(self, site: WorkdaySite) -> None:
        self.site = site
        self.name = f"workday:{site.tenant}/{site.site}"

    @property
    def _api(self) -> str:
        return f"https://{self.site.host}/wday/cxs/{self.site.tenant}/{self.site.site}"

    async def fetch(self, client: httpx.AsyncClient) -> list[RawPosting]:
        out: list[RawPosting] = []
        offset, total = 0, None
        while total is None or offset < total:
            data = await post_json(
                client,
                f"{self._api}/jobs",
                {"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": self.site.search_text},
            )
            total = data.get("total", 0) if total is None else total
            postings = data.get("jobPostings", [])
            if not postings:
                break
            for j in postings:
                path = j.get("externalPath", "")
                out.append(
                    RawPosting(
                        source=self.name,
                        external_id=path.rsplit("_", 1)[-1] or path,
                        company=self.site.company,
                        title=j.get("title", "").strip(),
                        location=j.get("locationsText", ""),
                        url=f"https://{self.site.host}/{self.site.site}{path}",
                        posted=j.get("postedOn", ""),
                        extra={"path": path},
                    )
                )
            offset += len(postings)
            if offset >= 400:
                break
        return out

    async def details(self, client: httpx.AsyncClient, posting: RawPosting) -> RawPosting:
        data = await get_json(client, f"{self._api}{posting.extra.get('path', '')}")
        info = data.get("jobPostingInfo") or {}
        posting.description = html_to_text(info.get("jobDescription", ""))
        posting.location = info.get("location") or posting.location
        remote = (info.get("remoteType") or "").lower()
        posting.remote = "remote" in remote
        posting.workplace = (
            "Remote" if "remote" in remote else ("Hybrid" if "hybrid" in remote else posting.workplace)
        )
        return posting


# --------------------------------------------------------------------------- amazon.jobs


class AmazonSource:
    def __init__(self, queries: list[str], country: str) -> None:
        self.queries = queries
        self.country = country
        self.name = "amazon"

    async def fetch(self, client: httpx.AsyncClient) -> list[RawPosting]:
        seen: dict[str, RawPosting] = {}
        headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) jobpilot", "Accept": "application/json"}
        for query in self.queries:
            offset = 0
            while offset < 500:
                data = await get_json(
                    client,
                    "https://www.amazon.jobs/en/search.json",
                    params={
                        "base_query": query,
                        "country": self.country,
                        "result_limit": 100,
                        "offset": offset,
                        "sort": "recent",
                    },
                    headers=headers,
                )
                jobs = data.get("jobs", [])
                for j in jobs:
                    jid = str(j.get("id_icims") or j.get("id"))
                    if jid in seen:
                        continue
                    seen[jid] = RawPosting(
                        source=self.name,
                        external_id=jid,
                        company="AWS"
                        if "aws" in (j.get("company_name", "") + j.get("title", "")).lower()
                        or "Web Services" in j.get("company_name", "")
                        else "Amazon",
                        title=j.get("title", "").strip(),
                        location=j.get("normalized_location") or j.get("location") or j.get("city", ""),
                        url="https://www.amazon.jobs" + j.get("job_path", f"/en/jobs/{jid}"),
                        description="\n\n".join(
                            html_to_text(j.get(k, ""))
                            for k in ("description", "basic_qualifications", "preferred_qualifications")
                        ),
                        posted=j.get("posted_date", ""),
                    )
                offset += len(jobs)
                if not jobs or offset >= int(data.get("hits", 0)):
                    break
        return list(seen.values())


# --------------------------------------------------------------------------- generische Karriereseiten (Browser + Claude)


class _ExtractedPosting(BaseModel):
    title: str
    url: str
    location: str


class _ExtractedList(BaseModel):
    postings: list[_ExtractedPosting]


PageRenderer = Callable[[str], Awaitable[tuple[str, list[dict[str, str]]]]]


class GenericPageSource:
    """Rendert eine Karriereseite im Browser und lässt Claude die Stellenliste herauslesen."""

    def __init__(self, page: GenericPage, render: PageRenderer, llm: Any, model: str) -> None:
        self.page = page
        self.render = render
        self.llm = llm
        self.model = model
        import hashlib

        self.name = f"generic:{page.company.lower()}:{hashlib.sha1(page.url.encode()).hexdigest()[:8]}"

    async def fetch(self, client: httpx.AsyncClient) -> list[RawPosting]:
        if self.llm is None:
            raise SourceError("Generische Quellen brauchen Claude Code (angemeldet)")
        text, links = await self.render(self.page.url)
        link_lines = "\n".join(f"- {link['text'][:140]} -> {link['href']}" for link in links[:400])
        result = await self.llm.parse(
            _ExtractedList,
            system=(
                "Du extrahierst Stellenanzeigen aus Karriereseiten. Gib nur echte, einzelne Stellen zurück "
                "(keine Kategorien, Filter, Blogartikel). Nutze ausschließlich URLs aus der Linkliste. "
                "Wenn der Ort unbekannt ist, gib einen leeren String zurück."
            ),
            content=f"Firma: {self.page.company}\nSeite: {self.page.url}\n\nSichtbarer Text (gekürzt):\n{text[:12000]}"
            f"\n\nLinks:\n{link_lines}",
            model=self.model,
            max_tokens=4000,
            cache_system=False,
        )
        out = []
        for p in result.postings:
            if not p.url.startswith("http"):
                continue
            out.append(
                RawPosting(
                    source=self.name,
                    external_id=p.url,
                    company=self.page.company,
                    title=p.title.strip(),
                    location=p.location,
                    url=p.url,
                )
            )
        return out

    async def details(self, client: httpx.AsyncClient, posting: RawPosting) -> RawPosting:
        text, _ = await self.render(posting.url)
        posting.description = text[:20000]
        if not posting.location:
            for city in ("Berlin", "Remote", "Germany", "Deutschland"):
                if city.lower() in text.lower()[:3000]:
                    posting.location = city
                    break
        return posting


# --------------------------------------------------------------------------- registry


def build_sources(
    config: SearchConfig,
    *,
    llm: Any = None,
    render: PageRenderer | None = None,
    fast_model: str = "",
    only: list[str] | None = None,
) -> list[Any]:
    s = config.sources
    sources: list[Any] = []
    sources += [GreenhouseSource(b) for b in s.greenhouse]
    sources += [AshbySource(b) for b in s.ashby]
    sources += [LeverSource(b) for b in s.lever]
    sources += [SmartRecruitersSource(c) for c in s.smartrecruiters]
    sources += [PersonioSource(c) for c in s.personio]
    sources += [WorkdaySource(w) for w in s.workday]
    if s.amazon_queries:
        sources.append(AmazonSource(s.amazon_queries, s.amazon_country))
    if render is not None:
        sources += [GenericPageSource(p, render, llm, fast_model) for p in s.generic]
    if only:
        wanted = [o.lower() for o in only]
        sources = [
            src
            for src in sources
            if any(src.name.lower().startswith(w) or w in src.name.lower() for w in wanted)
        ]
    return sources


async def gather_limited(coros: list[Awaitable[Any]], limit: int = 6) -> list[Any]:
    sem = asyncio.Semaphore(limit)

    async def run(c: Awaitable[Any]) -> Any:
        async with sem:
            return await c

    return await asyncio.gather(*(run(c) for c in coros), return_exceptions=True)

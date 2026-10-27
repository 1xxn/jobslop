"""Quellen-Adapter für öffentliche Job-Board-APIs und beliebige Karriereseiten."""

from __future__ import annotations

import asyncio
import base64
import inspect
import logging
import re
import xml.etree.ElementTree as ET
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar
from urllib.parse import urlparse

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


# --------------------------------------------------------------------------- Recruitee


class RecruiteeSource:
    def __init__(self, entry: str) -> None:
        self.slug, self.company = split_slug(entry)
        self.name = f"recruitee:{self.slug}"

    async def fetch(self, client: httpx.AsyncClient) -> list[RawPosting]:
        data = await get_json(client, f"https://{self.slug}.recruitee.com/api/offers/")
        out = []
        for j in data.get("offers", []):
            if j.get("status", "published") != "published":
                continue
            place = ", ".join(x for x in (j.get("city"), j.get("country")) if x)
            remote = bool(j.get("remote"))
            out.append(
                RawPosting(
                    source=self.name,
                    external_id=str(j["id"]),
                    company=self.company or j.get("company_name") or pretty(self.slug),
                    title=(j.get("title") or "").strip(),
                    location=place or j.get("location") or "",
                    url=j.get("careers_url", ""),
                    apply_url=j.get("careers_apply_url", ""),
                    description=html_to_text(
                        (j.get("description") or "") + "\n" + (j.get("requirements") or "")
                    ),
                    posted=(j.get("published_at") or "")[:10],
                    remote=remote,
                    workplace="Remote" if remote else ("Hybrid" if j.get("hybrid") else ""),
                )
            )
        return out


# --------------------------------------------------------------------------- Workable


class WorkableSource:
    def __init__(self, entry: str) -> None:
        self.slug, self.company = split_slug(entry)
        self.name = f"workable:{self.slug}"

    async def fetch(self, client: httpx.AsyncClient) -> list[RawPosting]:
        data = await get_json(
            client,
            f"https://apply.workable.com/api/v1/widget/accounts/{self.slug}",
            params={"details": "true"},
        )
        out = []
        for j in data.get("jobs", []):
            remote = str(j.get("telecommuting")).lower() == "true"
            out.append(
                RawPosting(
                    source=self.name,
                    external_id=str(j.get("shortcode") or j.get("code") or j.get("url")),
                    company=self.company or data.get("name") or pretty(self.slug),
                    title=(j.get("title") or "").strip(),
                    location=", ".join(x for x in (j.get("city"), j.get("country")) if x),
                    url=j.get("url", ""),
                    apply_url=j.get("application_url", ""),
                    description=html_to_text(j.get("description", "")),
                    posted=(j.get("published_on") or "")[:10],
                    remote=remote,
                    workplace="Remote" if remote else "",
                )
            )
        return out


# --------------------------------------------------------------------------- Workday


class WorkdaySource:
    def __init__(self, site: WorkdaySite) -> None:
        self.site = site
        self.name = f"workday:{site.tenant}/{site.site}"
        self.complete = True

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
                self.complete = offset >= total  # gedeckelt: fehlende Stellen sind nicht geschlossen
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
        self.complete = True

    async def fetch(self, client: httpx.AsyncClient) -> list[RawPosting]:
        seen: dict[str, RawPosting] = {}
        headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) jobslop", "Accept": "application/json"}
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
            else:
                self.complete = False  # mehr als 500 Treffer: Rest nicht abgefragt
        return list(seen.values())


# --------------------------------------------------------------------------- Jobbörsen (viele Firmen, eine Quelle)
#
# Börsen liefern Stellen vieler Firmen. Ist eine Abfrage gedeckelt (Seitenlimit), fehlen Stellen nicht, weil sie
# geschlossen sind – solche Quellen setzen ``complete = False``, damit der Crawl daraus keine Schließungen ableitet.


# Arbeitnow betreibt Länderseiten; die Domain der Stellen-URL verrät das Land (Ortsangaben fehlt es oft).
_ARBEITNOW_COUNTRIES = {
    "arbeitnow.com": ("Germany", r"germany|deutschland"),
    "arbeitnow.de": ("Germany", r"germany|deutschland"),
    "arbeitnow.at": ("Austria", r"austria|österreich"),
    "arbeitnow.ch": ("Switzerland", r"switzerland|schweiz|suisse"),
    "arbeitnow.nl": ("Netherlands", r"netherlands|nederland"),
    "arbeitnow.fr": ("France", r"france|frankreich"),
    "arbeitnow.co.uk": ("United Kingdom", r"united kingdom|uk|england|scotland|wales"),
}


def _arbeitnow_location(location: str, url: str) -> str:
    host = (urlparse(url).hostname or "").removeprefix("www.")
    country, known = _ARBEITNOW_COUNTRIES.get(host, ("", ""))
    if not country or re.search(known, location, re.I):
        return location
    return f"{location}, {country}" if location else country


class ArbeitnowSource:
    """arbeitnow.com: freie API mit Stellen aus Deutschland und Nachbarländern (viele aus Greenhouse, Personio …)."""

    name = "arbeitnow"

    def __init__(self, max_pages: int, pause_s: float = 2.0) -> None:
        self.max_pages = max_pages
        self.pause_s = pause_s  # die API drosselt schnelle Seitenfolgen (429)
        self.complete = True

    async def fetch(self, client: httpx.AsyncClient) -> list[RawPosting]:
        out: dict[str, RawPosting] = {}
        page = 1
        while page <= self.max_pages:
            try:
                data = await get_json(
                    client, "https://www.arbeitnow.com/api/job-board-api", params={"page": page}
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429 and out:
                    log.info("arbeitnow drosselt ab Seite %s – behalte %s Stellen", page, len(out))
                    self.complete = False
                    break
                raise
            for j in data.get("data", []):
                slug = j.get("slug") or j.get("url", "")
                types = " ".join(j.get("job_types") or [])
                location = _arbeitnow_location((j.get("location") or "").strip(), j.get("url", ""))
                out[slug] = RawPosting(
                    source=self.name,
                    external_id=slug,
                    company=(j.get("company_name") or "").strip(),
                    title=(j.get("title") or "").strip(),
                    location=location,
                    url=j.get("url", ""),
                    description=html_to_text(j.get("description", "")),
                    posted=_epoch_date(j.get("created_at")),
                    remote=bool(j.get("remote")),
                    workplace="Remote"
                    if j.get("remote")
                    else ("Hybrid" if "hybrid" in types.lower() else ""),
                )
            if not (data.get("links") or {}).get("next"):
                break
            page += 1
            await asyncio.sleep(self.pause_s)
        else:
            self.complete = False  # Seitenlimit erreicht
        return list(out.values())


class HimalayasSource:
    """himalayas.app: Remote-Stellen, die für ein Land offen sind (Suche nach Stichworten)."""

    name = "himalayas"

    def __init__(self, queries: list[str], country: str, max_pages: int = 5) -> None:
        self.queries = queries
        self.country = country
        self.max_pages = max_pages
        self.complete = False  # Suchtreffer sind gedeckelt

    async def fetch(self, client: httpx.AsyncClient) -> list[RawPosting]:
        out: dict[str, RawPosting] = {}
        for query in self.queries:
            for page in range(1, self.max_pages + 1):
                data = await get_json(
                    client,
                    "https://himalayas.app/jobs/api/search",
                    params={"q": query, "country": self.country, "page": page},
                )
                jobs = data.get("jobs", [])
                for j in jobs:
                    guid = j.get("guid") or j.get("applicationLink", "")
                    allowed = j.get("locationRestrictions") or []
                    region = ", ".join(allowed[:6]) if allowed else f"{self.country}, Worldwide"
                    out[guid] = RawPosting(
                        source=self.name,
                        external_id=guid,
                        company=(j.get("companyName") or "").strip(),
                        title=(j.get("title") or "").strip(),
                        location=f"Remote ({region})",
                        url=j.get("applicationLink") or guid,
                        description=html_to_text(j.get("description", "")),
                        posted=_epoch_date(j.get("pubDate")),
                        remote=True,
                        workplace="Remote",
                    )
                if len(jobs) < 20:
                    break
        return list(out.values())


def _epoch_date(value: Any) -> str:
    from datetime import UTC, datetime

    try:
        return datetime.fromtimestamp(int(value), tz=UTC).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return ""


class ArbeitsagenturSource:
    """Bundesagentur für Arbeit: offizielle Jobsuche – ganz Deutschland, alle Branchen, auch kleine Firmen."""

    name = "arbeitsagentur"
    api = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service"
    # Öffentlicher, dokumentierter Zugang der Jobsuche-API (https://jobsuche.api.bund.dev)
    headers: ClassVar[dict[str, str]] = {"X-API-Key": "jobboerse-jobsuche"}

    def __init__(
        self,
        queries: list[str],
        cities: list[str],
        *,
        remote: bool,
        radius_km: int,
        skip_agencies: bool,
        max_pages: int = 2,
        days: int = 28,
    ) -> None:
        self.queries = queries
        self.cities = cities
        self.remote = remote
        self.radius_km = radius_km
        self.skip_agencies = skip_agencies
        self.max_pages = max_pages
        self.days = days
        self.complete = False  # Suchtreffer sind gedeckelt

    def _searches(self) -> list[tuple[str, dict[str, Any], bool]]:
        out = [
            (q, {"wo": city, "umkreis": self.radius_km}, False) for q in self.queries for city in self.cities
        ]
        if self.remote:
            out += [(q, {"arbeitszeit": "ho"}, True) for q in self.queries]  # ho = Homeoffice
        return out

    async def fetch(self, client: httpx.AsyncClient) -> list[RawPosting]:
        out: dict[str, RawPosting] = {}
        for query, where, remote in self._searches():
            for page in range(1, self.max_pages + 1):
                params: dict[str, Any] = {
                    "was": query,
                    "angebotsart": 1,  # Arbeit (keine Ausbildung, Praktika, Selbstständigkeit)
                    "veroeffentlichtseit": self.days,
                    "size": 100,
                    "page": page,
                    **where,
                }
                if self.skip_agencies:
                    params |= {"zeitarbeit": "false", "pav": "false"}
                data = await get_json(client, f"{self.api}/pc/v6/jobs", params=params, headers=self.headers)
                items = data.get("ergebnisliste") or data.get("stellenangebote") or []
                for j in items:
                    posting = self._posting(j, remote)
                    if posting.external_id and posting.external_id not in out:
                        out[posting.external_id] = posting
                if len(items) < 100:
                    break
        return list(out.values())

    def _posting(self, j: dict[str, Any], remote: bool) -> RawPosting:
        ref = j.get("referenznummer") or j.get("refnr") or ""
        places = j.get("stellenlokationen") or [{"adresse": j.get("arbeitsort") or {}}]
        cities = [((p.get("adresse") or {}).get("ort") or "").strip() for p in places]
        location = "; ".join(dict.fromkeys(c for c in cities if c))
        return RawPosting(
            source=self.name,
            external_id=ref,
            company=(j.get("firma") or j.get("arbeitgeber") or "").strip(),
            title=(j.get("stellenangebotsTitel") or j.get("titel") or "").strip(),
            location=f"{location}, Deutschland" if location else "Deutschland",
            url=f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{ref}",
            posted=(j.get("datumErsteVeroeffentlichung") or j.get("aktuelleVeroeffentlichungsdatum") or "")[
                :10
            ],
            remote=remote,
            workplace="Remote" if remote else "",
        )

    async def details(self, client: httpx.AsyncClient, posting: RawPosting) -> RawPosting:
        ref = base64.b64encode(posting.external_id.encode()).decode()
        data = await get_json(client, f"{self.api}/pc/v4/jobdetails/{ref}", headers=self.headers)
        posting.description = html_to_text(
            data.get("stellenangebotsBeschreibung") or data.get("stellenbeschreibung") or ""
        )
        posting.apply_url = data.get("externeUrl") or posting.apply_url
        if data.get("homeofficemoeglich") and not posting.remote:
            posting.workplace = "Hybrid"
        return posting


# --------------------------------------------------------------------------- Große Portale (JobSpy)


def _jobspy_scrape(**kwargs: Any) -> list[dict[str, Any]]:
    """Ruft JobSpy auf (synchron, im Thread) und liefert schlichte Dicts statt eines DataFrames."""
    try:
        from jobspy import scrape_jobs
    except ImportError as exc:  # pragma: no cover - Abhängigkeit ist Teil der Installation
        raise SourceError("JobSpy fehlt – `uv sync` bzw. jobslop neu installieren") from exc
    accepted = inspect.signature(scrape_jobs).parameters
    df = scrape_jobs(**{k: v for k, v in kwargs.items() if k in accepted})
    return [] if df is None or df.empty else df.to_dict("records")


def _text(value: Any) -> str:
    """JobSpy liefert fehlende Werte als NaN/None – alles Nicht-Text wird leer."""
    return value.strip() if isinstance(value, str) else ""


_COUNTRY_NAMES = {"germany": "Germany", "austria": "Austria", "switzerland": "Switzerland"}


class PortalSource:
    """LinkedIn, Indeed oder Glassdoor über JobSpy – öffentliche Suchseiten, ohne Login und ohne Konto.

    Die Portale untersagen automatisierte Abfragen in ihren Nutzungsbedingungen; jobslop fragt deshalb gedrosselt
    und nur Suchergebnisse ab. Beworben wird möglichst beim Arbeitgeber, nicht über das Portal.
    """

    def __init__(
        self,
        site: str,
        queries: list[str],
        cities: list[str],
        *,
        remote: bool,
        country: str,
        results: int,
        hours_old: int,
        pause_s: float = 3.0,
        scrape: Callable[..., list[dict[str, Any]]] = _jobspy_scrape,
    ) -> None:
        self.site = site
        self.name = f"portal:{site}"
        self.queries = queries
        self.cities = cities
        self.remote = remote
        self.country = country
        self.results = results
        self.hours_old = hours_old
        self.pause_s = pause_s
        self.scrape = scrape
        self.complete = False
        self._detail_lock = asyncio.Lock()
        self._throttled = False

    def _terms(self) -> list[str]:
        # LinkedIn drosselt schnell (429): alle Suchbegriffe als eine ODER-Suche pro Ort statt einzeln
        if self.site == "linkedin" and len(self.queries) > 1:
            return [" OR ".join(f'"{q}"' if " " in q else q for q in self.queries)]
        return self.queries

    def _searches(self) -> list[tuple[str, str, bool]]:
        land = _COUNTRY_NAMES.get(self.country.lower(), self.country.title())
        terms = self._terms()
        out = [(q, f"{city.title()}, {land}", False) for q in terms for city in self.cities]
        if self.remote:
            out += [(q, land, True) for q in terms]
        return out

    async def fetch(self, client: httpx.AsyncClient) -> list[RawPosting]:
        out: dict[str, RawPosting] = {}
        errors: list[str] = []
        for i, (query, location, remote) in enumerate(self._searches()):
            if i:
                await asyncio.sleep(self.pause_s)  # Portale drosseln schnelle Suchfolgen
            try:
                rows = await asyncio.to_thread(
                    self.scrape,
                    site_name=[self.site],
                    search_term=query,
                    location=location,
                    is_remote=remote,
                    results_wanted=self.results * (2 if len(self._terms()) < len(self.queries) else 1),
                    hours_old=self.hours_old,
                    country_indeed=self.country,
                    description_format="markdown",
                    verbose=0,
                )
            except Exception as exc:  # eine gesperrte Suche soll die übrigen nicht verhindern
                errors.append(f"{query} @ {location}: {type(exc).__name__}: {exc}")
                continue
            for row in rows:
                posting = self._posting(row, remote)
                if posting.title and posting.external_id not in out:
                    out[posting.external_id] = posting
        if errors and not out:
            raise SourceError("; ".join(errors)[:500])
        for err in errors:
            log.info("%s: %s", self.name, err)
        return list(out.values())

    def _posting(self, row: dict[str, Any], remote: bool) -> RawPosting:
        portal_url = _text(row.get("job_url"))
        direct = _text(row.get("job_url_direct"))
        job_id = _text(row.get("id")) or portal_url
        posted = row.get("date_posted")
        is_remote = row.get("is_remote") is True or remote
        return RawPosting(
            source=self.name,
            external_id=job_id,
            company=_text(row.get("company")),
            title=_text(row.get("title")),
            location=_text(row.get("location")),
            # Direkter Link zum Arbeitgeber (Indeed liefert ihn oft) schlägt die Portal-Seite
            url=direct or portal_url,
            description=_text(row.get("description")),
            posted=str(posted)[:10] if posted is not None and str(posted) not in ("nan", "NaT") else "",
            remote=is_remote,
            workplace="Remote" if is_remote else "",
            extra={"portal_url": portal_url, "linkedin_id": job_id.removeprefix("li-")},
        )

    async def details(self, client: httpx.AsyncClient, posting: RawPosting) -> RawPosting:
        """LinkedIn-Suchtreffer haben keine Beschreibung – nur für passende Stellen die öffentliche Detailseite laden."""
        if self.site != "linkedin" or not posting.extra.get("linkedin_id") or self._throttled:
            return posting
        async with self._detail_lock:  # nacheinander und mit Pause – sonst sperrt LinkedIn (429)
            if self._throttled:
                return posting
            try:
                html = await get_text(
                    client,
                    f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{posting.extra['linkedin_id']}",
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:  # gedrosselt: für diesen Lauf nicht weiter anklopfen
                    self._throttled = True
                    log.info("LinkedIn drosselt – restliche Beschreibungen beim nächsten Crawl")
                    return posting
                raise
            await asyncio.sleep(self.pause_s / 3)
        m = re.search(r"show-more-less-html__markup[^>]*>(.*?)</div>", html, re.S)
        posting.description = html_to_text(m.group(1)) if m else ""
        return posting


AGGREGATOR_SOURCES = ("arbeitnow", "himalayas", "arbeitsagentur", "portal")


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
        # Claude liest die Liste aus gekürztem Seitentext – eine fehlende Stelle heißt nicht „geschlossen“
        self.complete = False
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
    sources += [RecruiteeSource(c) for c in s.recruitee]
    sources += [WorkableSource(c) for c in s.workable]
    sources += [WorkdaySource(w) for w in s.workday]
    if s.amazon_queries:
        sources.append(AmazonSource(s.amazon_queries, s.amazon_country))
    if s.arbeitnow:
        sources.append(ArbeitnowSource(s.arbeitnow_max_pages))
    cities = config.filters.onsite_locations
    remote = config.filters.allow_remote
    if s.himalayas and s.queries and remote:
        sources.append(HimalayasSource(s.queries, s.himalayas_country))
    if s.arbeitsagentur and s.queries:
        sources.append(
            ArbeitsagenturSource(
                s.queries,
                cities,
                remote=remote,
                radius_km=s.arbeitsagentur_radius_km,
                skip_agencies=s.arbeitsagentur_skip_agencies,
            )
        )
    if s.queries:
        sources += [
            PortalSource(
                site,
                s.queries,
                cities,
                remote=remote,
                country=s.portal_country,
                results=s.portal_results,
                hours_old=s.portal_hours_old,
            )
            for site in dict.fromkeys(s.portals)
        ]
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

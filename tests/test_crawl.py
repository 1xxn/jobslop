"""Crawler gegen gemockte Job-Board-APIs: Filter, Upsert, History, Startlisten-Merge."""

from __future__ import annotations

from urllib.parse import urlparse

import httpx
import respx
from sqlalchemy import select

from jobslop.config import WorkdaySite
from jobslop.crawl.pipeline import run_crawl
from jobslop.db import Job, JobSnapshot, session_scope

GH_JOBS = {
    "jobs": [
        {
            "id": 1,
            "title": "Site Reliability Engineer",
            "location": {"name": "Berlin, Germany"},
            "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/1",
            "content": "&lt;p&gt;Kubernetes, Terraform, GCP, Python, Prometheus, Helm, Go&lt;/p&gt;",
            "updated_at": "2026-10-20T10:00:00Z",
        },
        {
            "id": 2,
            "title": "Senior Site Reliability Engineer",
            "location": {"name": "Berlin"},
            "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/2",
            "content": "",
        },
        {
            "id": 3,
            "title": "Account Executive",
            "location": {"name": "Berlin"},
            "absolute_url": "https://x/3",
            "content": "",
        },
        {
            "id": 4,
            "title": "Platform Engineer",
            "location": {"name": "Munich, Germany"},
            "absolute_url": "https://x/4",
            "content": "",
        },
        {
            "id": 5,
            "title": "(Senior) Platform Engineer",
            "location": {"name": "Berlin"},
            "absolute_url": "https://x/5",
            "content": "",
        },
    ]
}
ASHBY = {
    "jobs": [
        {
            "id": "a1",
            "title": "DevOps Engineer",
            "location": "Remote - Germany",
            "isRemote": True,
            "workplaceType": "Remote",
            "jobUrl": "https://jobs.ashbyhq.com/beta/a1",
            "applyUrl": "https://jobs.ashbyhq.com/beta/a1/application",
            "descriptionPlain": "Kubernetes and CI/CD",
            "publishedAt": "2026-10-01T00:00:00Z",
            "secondaryLocations": [],
        },
        {
            "id": "a2",
            "title": "DevOps Engineer",
            "location": "Remote - Spain",
            "isRemote": True,
            "jobUrl": "https://jobs.ashbyhq.com/beta/a2",
            "descriptionPlain": "",
            "secondaryLocations": [],
        },
    ]
}
LEVER = [
    {
        "id": "l1",
        "text": "Cloud Engineer (m/w/d)",
        "categories": {"location": "Berlin", "allLocations": ["Berlin"]},
        "workplaceType": "hybrid",
        "hostedUrl": "https://jobs.lever.co/gamma/l1",
        "applyUrl": "https://jobs.lever.co/gamma/l1/apply",
        "descriptionPlain": "AWS Kubernetes Terraform",
        "lists": [],
    }
]
SR_LIST = {
    "content": [
        {
            "id": "s1",
            "name": "Systems Engineer Kubernetes",
            "releasedDate": "2026-10-10T00:00:00Z",
            "location": {
                "city": "Berlin",
                "country": "de",
                "remote": False,
                "fullLocation": "Berlin, Germany",
            },
            "company": {"name": "Delta GmbH"},
        }
    ],
    "totalFound": 1,
}
SR_DETAIL = {
    "jobAd": {
        "sections": {"jobDescription": {"title": "Aufgaben", "text": "<p>Linux, Kubernetes, Terraform</p>"}}
    },
    "applyUrl": "https://jobs.smartrecruiters.com/Delta/s1/apply",
}
PERSONIO = """<?xml version="1.0" encoding="UTF-8"?><workzag-jobs><position><id>777</id><subcompany>Epsilon GmbH</subcompany>
<office>Berlin</office><name>Site Reliability Engineer (m/w/d)</name><jobDescriptions><jobDescription><name>Deine Aufgaben</name>
<value><![CDATA[<p>Kubernetes und Observability mit Prometheus und Grafana</p>]]></value></jobDescription></jobDescriptions>
<createdAt>2026-10-05T00:00:00+00:00</createdAt></position></workzag-jobs>"""
WD_LIST = {
    "total": 1,
    "jobPostings": [
        {
            "title": "DevOps Engineer",
            "externalPath": "/job/Berlin/DevOps-Engineer_R123",
            "locationsText": "Berlin",
            "postedOn": "Posted Today",
        }
    ],
}
WD_DETAIL = {
    "jobPostingInfo": {"jobDescription": "<p>CI/CD, GitLab</p>", "location": "Berlin", "remoteType": "Hybrid"}
}
AMAZON = {
    "hits": 1,
    "jobs": [
        {
            "id_icims": "10503488",
            "title": "Systems Engineer/DevOps Eng, Managed Operations",
            "normalized_location": "Berlin, BE, DEU",
            "job_path": "/en/jobs/10503488/systems-engineer",
            "company_name": "Amazon Web Services Development Center Germany GmbH",
            "description": "Operate the AWS European Sovereign Cloud",
            "basic_qualifications": "Linux",
            "posted_date": "August 17, 2026",
        }
    ],
}


def _mock(router: respx.MockRouter, *, gh=GH_JOBS, ashby=ASHBY) -> None:
    router.get("https://boards-api.greenhouse.io/v1/boards/acme").respond(json={"name": "Acme Cloud"})
    router.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").respond(json=gh)
    router.get("https://api.ashbyhq.com/posting-api/job-board/beta").respond(json=ashby)
    router.get("https://api.lever.co/v0/postings/gamma").respond(json=LEVER)
    router.get("https://api.smartrecruiters.com/v1/companies/Delta/postings").respond(json=SR_LIST)
    router.get("https://api.smartrecruiters.com/v1/companies/Delta/postings/s1").respond(json=SR_DETAIL)
    router.get("https://epsilon.jobs.personio.de/xml").respond(text=PERSONIO)
    router.post("https://wd.example.com/wday/cxs/ten/Careers/jobs").respond(json=WD_LIST)
    router.get("https://wd.example.com/wday/cxs/ten/Careers/job/Berlin/DevOps-Engineer_R123").respond(
        json=WD_DETAIL
    )
    router.get("https://www.amazon.jobs/en/search.json").respond(json=AMAZON)
    router.get("https://boards-api.greenhouse.io/v1/boards/broken").respond(status_code=404)
    router.get("https://boards-api.greenhouse.io/v1/boards/broken/jobs").respond(status_code=404)


def _config(config):
    s = config.sources
    s.greenhouse, s.ashby, s.lever, s.smartrecruiters, s.personio = (
        ["acme", "broken"],
        ["beta"],
        ["gamma"],
        ["Delta"],
        ["epsilon"],
    )
    s.workday = [WorkdaySite(company="Zeta AG", host="wd.example.com", tenant="ten", site="Careers")]
    s.amazon_queries, s.generic = ["engineer"], []
    s.arbeitnow, s.queries, s.portals, s.arbeitsagentur, s.discover_boards = False, [], [], False, False
    return config


async def test_crawl_filters_upserts_and_tracks_history(settings, config):
    config = _config(config)
    # Eintrag aus der Startliste (LinkedIn), der beim Crawl auf die direkte Firmen-URL umgestellt werden soll
    from jobslop.classify import fingerprint, match_key

    with session_scope(settings.db_path) as s:
        s.add(
            Job(
                fingerprint=fingerprint("seed", "li"),
                match_key=match_key("Acme Cloud", "Site Reliability Engineer"),
                source="seed:linkedin",
                company="Acme Cloud",
                title="Site Reliability Engineer",
                url="https://www.linkedin.com/jobs/view/1/",
                origin="seed",
                where="B",
            )
        )

    with respx.mock(assert_all_called=False) as router:
        _mock(router)
        report = await run_crawl(settings, config, enrich=False, use_browser=False)

    assert any(e.startswith("greenhouse:broken") for e in report.errors)
    with session_scope(settings.db_path) as s:
        all_jobs = list(s.execute(select(Job)).scalars())
        jobs = {j.title: j for j in all_jobs}
        titles = set(jobs)
        assert titles == {
            "Site Reliability Engineer",
            "Senior Site Reliability Engineer",  # Senior ist Stretch, nicht ausgeschlossen
            "(Senior) Platform Engineer",
            "DevOps Engineer",
            "Cloud Engineer (m/w/d)",
            "Systems Engineer Kubernetes",
            "Site Reliability Engineer (m/w/d)",
            "Systems Engineer/DevOps Eng, Managed Operations",
        }
        sre = jobs["Site Reliability Engineer"]
        assert sre.url == "https://job-boards.greenhouse.io/acme/jobs/1"  # Startlisten-Eintrag übernommen
        assert sre.alt_urls == ["https://www.linkedin.com/jobs/view/1/"]
        assert sre.category == "SRE" and sre.fit == 3 and sre.where == "B"
        assert jobs["(Senior) Platform Engineer"].level == "S"
        assert jobs["Senior Site Reliability Engineer"].level == "S"
        assert jobs["Senior Site Reliability Engineer"].score < sre.score
        devops = next(j for j in all_jobs if j.source == "ashby:beta")
        workday = next(j for j in all_jobs if j.source.startswith("workday:"))
        assert workday.workplace == "Hybrid" and "GitLab" in workday.description
        assert devops.where == "R" and devops.workplace == "Remote"
        assert jobs["Systems Engineer Kubernetes"].apply_url.endswith("/apply")  # Details nachgeladen
        assert "Kubernetes" in jobs["Systems Engineer Kubernetes"].description
        assert jobs["Systems Engineer/DevOps Eng, Managed Operations"].company == "AWS"
        assert len(report.merged_seeds) == 1 and len(report.new) == 8

    # Zweiter Lauf: Ashby-Stelle verschwindet, Greenhouse-Titel ändert sich
    gh2 = {"jobs": [dict(GH_JOBS["jobs"][0], title="Site Reliability Engineer II")]}
    with respx.mock(assert_all_called=False) as router:
        _mock(router, gh=gh2, ashby={"jobs": []})
        report2 = await run_crawl(settings, config, enrich=False, use_browser=False)

    with session_scope(settings.db_path) as s:
        changes = {
            (sn.job.title, sn.change)
            for sn in s.execute(
                select(JobSnapshot).where(JobSnapshot.crawl_run_id == report2.run_id)
            ).scalars()
        }
        assert ("Site Reliability Engineer II", "updated") in changes
        assert ("DevOps Engineer", "closed") in changes
        assert ("(Senior) Platform Engineer", "closed") in changes
        closed = s.execute(select(Job).where(Job.status == "closed")).scalars().all()
        assert {j.source for j in closed} == {"ashby:beta", "greenhouse:acme"}

    # Dritter Lauf: Ashby-Stelle ist wieder da → reopened
    with respx.mock(assert_all_called=False) as router:
        _mock(router, gh=gh2)
        report3 = await run_crawl(settings, config, enrich=False, use_browser=False)
    assert len(report3.reopened) == 1


async def test_source_failure_does_not_close_jobs(settings, config):
    config = _config(config)
    config.sources.greenhouse = ["acme"]
    with respx.mock(assert_all_called=False) as router:
        _mock(router)
        await run_crawl(settings, config, enrich=False, use_browser=False)
    with respx.mock(assert_all_called=False) as router:
        _mock(router)
        router.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").mock(
            side_effect=httpx.ConnectError("down")
        )
        report = await run_crawl(settings, config, enrich=False, use_browser=False)
    assert report.closed == []  # ausgefallene Quelle schließt keine Stellen


async def test_filter_change_does_not_close_listed_jobs(settings, config):
    config = _config(config)
    with respx.mock(assert_all_called=False) as router:
        _mock(router)
        await run_crawl(settings, config, enrich=False, use_browser=False)
    # Rolle aus dem Filter genommen: die Stellen sind weiter online und dürfen nicht als geschlossen gelten
    config.filters.exclude_titles = [*config.filters.exclude_titles, "reliability"]
    with respx.mock(assert_all_called=False) as router:
        _mock(router)
        report = await run_crawl(settings, config, enrich=False, use_browser=False)
    assert report.closed == []
    with session_scope(settings.db_path) as s:
        sre = s.execute(select(Job).where(Job.title == "Site Reliability Engineer")).scalars().one()
        assert sre.status == "open"


async def test_capped_workday_search_is_not_complete():
    from jobslop.crawl.base import make_client
    from jobslop.crawl.sources import WorkdaySource

    page = {"total": 1000, "jobPostings": WD_LIST["jobPostings"] * 20}
    source = WorkdaySource(
        WorkdaySite(company="Zeta AG", host="wd.example.com", tenant="ten", site="Careers")
    )
    with respx.mock() as router:
        router.post("https://wd.example.com/wday/cxs/ten/Careers/jobs").respond(json=page)
        async with make_client() as client:
            postings = await source.fetch(client)
    assert len(postings) == 400 and source.complete is False


ARBEITNOW = {
    "data": [
        {
            "slug": "sre-acme-1",
            "company_name": "Acme Cloud GmbH",
            "title": "Site Reliability Engineer",
            "description": "<p>Kubernetes</p>",
            "remote": False,
            "url": "https://www.arbeitnow.com/jobs/acme/sre",
            "job_types": [],
            "location": "Berlin",
            "created_at": 1792900000,
        },
        {
            "slug": "linux-omega-2",
            "company_name": "Omega GmbH",
            "title": "Linux Administrator (m/w/d)",
            "description": "<p>Linux, Bash, Ansible</p>",
            "remote": True,
            "url": "https://www.arbeitnow.com/jobs/omega/linux",
            "job_types": [],
            "location": "Hamburg",
            "created_at": 1792900000,
        },
        {
            "slug": "audit-3",
            "company_name": "Prüf AG",
            "title": "Audit Engineer",
            "description": "",
            "remote": False,
            "url": "https://www.arbeitnow.com/jobs/pruef/audit",
            "job_types": [],
            "location": "Berlin",
            "created_at": 1792900000,
        },
    ],
    "links": {"next": None},
}
HIMALAYAS = {
    "jobs": [
        {
            "guid": "https://himalayas.app/companies/acme/jobs/sre",
            "title": "Site Reliability Engineer",
            "companyName": "Acme Cloud",
            "locationRestrictions": ["Germany"],
            "applicationLink": "https://himalayas.app/companies/acme/jobs/sre",
            "description": "",
            "pubDate": 1792900000,
        },
        {
            "guid": "https://himalayas.app/companies/remote-co/jobs/k8s",
            "title": "Kubernetes Engineer",
            "companyName": "Remote Co",
            "locationRestrictions": [],
            "applicationLink": "https://himalayas.app/companies/remote-co/jobs/k8s",
            "description": "<p>Kubernetes, Terraform</p>",
            "pubDate": 1792900000,
        },
    ]
}


async def test_job_boards_add_jobs_without_duplicates(settings, config):
    config = _config(config)
    s = config.sources
    s.greenhouse, s.ashby, s.lever, s.smartrecruiters, s.personio, s.workday, s.amazon_queries = (
        ["acme"],
        [],
        [],
        [],
        [],
        [],
        [],
    )
    s.arbeitnow, s.queries, s.portals, s.arbeitsagentur, s.discover_boards = True, ["sre"], [], False, False
    with respx.mock(assert_all_called=False) as router:
        _mock(router)
        router.get("https://www.arbeitnow.com/api/job-board-api").respond(json=ARBEITNOW)
        router.get("https://himalayas.app/jobs/api/search").respond(json=HIMALAYAS)
        report = await run_crawl(settings, config, enrich=False, use_browser=False)
    assert report.errors == []
    assert report.rejected["Dublette"] == 2  # Acme-SRE kommt aus Arbeitnow und Himalayas noch einmal
    with session_scope(settings.db_path) as db:
        jobs = {j.title: j for j in db.execute(select(Job)).scalars()}
        sres = [j for j in jobs.values() if j.title == "Site Reliability Engineer"]
        assert len(sres) == 1 and sres[0].source == "greenhouse:acme"
        assert jobs["Linux Administrator (m/w/d)"].where == "R"  # Remote in Deutschland
        assert jobs["Kubernetes Engineer"].where == "R" and jobs["Kubernetes Engineer"].source == "himalayas"
        assert "Audit Engineer" not in jobs  # "it engineer" darf nicht in "audit engineer" treffen

    # Zweiter Lauf: beide Börsen liefern nichts mehr. Arbeitnow war vollständig → schließen;
    # Himalayas ist eine gedeckelte Suche → Stelle bleibt offen, bis sie lange nicht mehr auftaucht.
    with respx.mock(assert_all_called=False) as router:
        _mock(router)
        router.get("https://www.arbeitnow.com/api/job-board-api").respond(json={"data": [], "links": {}})
        router.get("https://himalayas.app/jobs/api/search").respond(json={"jobs": []})
        report2 = await run_crawl(settings, config, enrich=False, use_browser=False)
    with session_scope(settings.db_path) as db:
        status = {j.title: j.status for j in db.execute(select(Job)).scalars()}
    assert status["Linux Administrator (m/w/d)"] == "closed"
    assert status["Kubernetes Engineer"] == "open"
    assert status["Site Reliability Engineer"] == "open"
    assert len(report2.closed) == 1


def test_arbeitnow_country_comes_from_the_job_domain():
    from jobslop.crawl.sources import _arbeitnow_location

    assert _arbeitnow_location("Berlin", "https://www.arbeitnow.com/jobs/a/b") == "Berlin, Germany"
    assert (
        _arbeitnow_location("Munich, Bayern, Germany", "https://www.arbeitnow.com/x")
        == "Munich, Bayern, Germany"
    )
    # Länderseiten: früher wurde aus „Remote job“ in Paris eine Remote-Stelle in Deutschland
    assert _arbeitnow_location("Remote job", "https://www.arbeitnow.fr/jobs/x") == "Remote job, France"
    assert _arbeitnow_location("London", "https://www.arbeitnow.co.uk/jobs/x") == "London, United Kingdom"
    assert _arbeitnow_location("Veghel, Nederland", "https://www.arbeitnow.nl/x") == "Veghel, Nederland"
    assert _arbeitnow_location("", "https://www.arbeitnow.ch/x") == "Switzerland"
    assert _arbeitnow_location("Wien", "https://example.com/x") == "Wien"  # unbekannt: nichts erfinden


async def test_arbeitnow_throttling_keeps_loaded_pages(settings, config, monkeypatch):
    from jobslop.crawl import base
    from jobslop.crawl.sources import ArbeitnowSource

    monkeypatch.setattr(base, "wait_exponential", lambda **_: lambda _state: 0)
    page2 = dict(ARBEITNOW, links={"next": "https://www.arbeitnow.com/api/job-board-api?page=2"})
    with respx.mock() as router:
        router.get("https://www.arbeitnow.com/api/job-board-api", params={"page": "1"}).respond(json=page2)
        router.get("https://www.arbeitnow.com/api/job-board-api", params={"page": "2"}).respond(
            status_code=429
        )
        src = ArbeitnowSource(max_pages=5, pause_s=0)
        async with base.make_client() as client:
            postings = await src.fetch(client)
    assert len(postings) == 3
    assert src.complete is False  # gedrosselt → keine Schließungen aus diesem Lauf


async def test_company_board_replaces_job_board_entry(settings, config):
    config = _config(config)
    s = config.sources
    s.greenhouse, s.ashby, s.lever, s.smartrecruiters, s.personio, s.workday, s.amazon_queries = (
        [],
        [],
        [],
        [],
        [],
        [],
        [],
    )
    s.arbeitnow = True
    with respx.mock(assert_all_called=False) as router:
        router.get("https://www.arbeitnow.com/api/job-board-api").respond(json=ARBEITNOW)
        await run_crawl(settings, config, enrich=False, use_browser=False)
    s.greenhouse = ["acme"]
    with respx.mock(assert_all_called=False) as router:
        _mock(router)
        router.get("https://www.arbeitnow.com/api/job-board-api").respond(json=ARBEITNOW)
        await run_crawl(settings, config, enrich=False, use_browser=False)
    with session_scope(settings.db_path) as db:
        sres = [j for j in db.execute(select(Job)).scalars() if j.title == "Site Reliability Engineer"]
    assert len(sres) == 1
    assert (
        sres[0].source == "greenhouse:acme" and urlparse(sres[0].url).hostname == "job-boards.greenhouse.io"
    )
    assert sres[0].alt_urls == ["https://www.arbeitnow.com/jobs/acme/sre"]


class _BatchLLM:
    """Bewertet Stapel; der zweite Stapel scheitert am Abo-Limit."""

    def __init__(self):
        from jobslop.llm import Usage

        self.usage = Usage()
        self.prompts: list[str] = []

    async def parse(self, schema, *, system, content, model=None, max_tokens=4096, cache_system=True):
        import re

        from jobslop.llm import LLMLimitReached

        self.prompts.append(content)
        if len(self.prompts) > 1:
            raise LLMLimitReached("You've hit your session limit")
        ids = [int(x) for x in re.findall(r"job_id=(\d+)", content)]
        item = {
            "required_years": 2,
            "seniority": "mid",
            "fit": 3,
            "fit_reason": "GCP + Kubernetes",
            "german_required": False,
            "workplace": "Hybrid",
            "red_flags": [],
            "summary": "passt",
        }
        return schema.model_validate(
            {"items": [item | {"job_id": i} for i in ids] + [item | {"job_id": 9999}]}
        )


async def test_enrich_batches_and_stops_at_limit(settings, config, profile):
    from conftest import add_job
    from jobslop.crawl.pipeline import ENRICH_BATCH, enrich_jobs

    settings.claude_parallel = 1  # Reihenfolge deterministisch
    ids = [add_job(settings, f"https://x/{i}", company=f"Firma {i}") for i in range(ENRICH_BATCH * 3)]
    with session_scope(settings.db_path) as s:
        for j in s.execute(select(Job)).scalars():
            j.description = "Kubernetes, Terraform, GCP"
    llm = _BatchLLM()
    count = await enrich_jobs(settings, config, llm, profile, ids)
    assert count == ENRICH_BATCH  # erster Stapel bewertet, fremde job_id ignoriert
    assert len(llm.prompts) == 2  # dritter Stapel wird nach dem Limit gar nicht mehr gestartet
    with session_scope(settings.db_path) as s:
        rated = [j for j in s.execute(select(Job)).scalars() if j.enrichment]
        assert len(rated) == ENRICH_BATCH and all(j.fit == 3 and j.workplace == "Hybrid" for j in rated)

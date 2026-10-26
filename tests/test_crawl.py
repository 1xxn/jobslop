"""Crawler gegen gemockte Job-Board-APIs: Filter, Upsert, History, Startlisten-Merge."""

from __future__ import annotations

import httpx
import respx
from sqlalchemy import select

from jobpilot.config import WorkdaySite
from jobpilot.crawl.pipeline import run_crawl
from jobpilot.db import Job, JobSnapshot, session_scope

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
    return config


async def test_crawl_filters_upserts_and_tracks_history(settings, config):
    config = _config(config)
    # Eintrag aus der Startliste (LinkedIn), der beim Crawl auf die direkte Firmen-URL umgestellt werden soll
    from jobpilot.classify import fingerprint, match_key

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
        devops = next(j for j in all_jobs if j.source == "ashby:beta")
        workday = next(j for j in all_jobs if j.source.startswith("workday:"))
        assert workday.workplace == "Hybrid" and "GitLab" in workday.description
        assert devops.where == "R" and devops.workplace == "Remote"
        assert jobs["Systems Engineer Kubernetes"].apply_url.endswith("/apply")  # Details nachgeladen
        assert "Kubernetes" in jobs["Systems Engineer Kubernetes"].description
        assert jobs["Systems Engineer/DevOps Eng, Managed Operations"].company == "AWS"
        assert len(report.merged_seeds) == 1 and len(report.new) == 7

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

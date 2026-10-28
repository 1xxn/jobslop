"""Neue Quellen (Arbeitsagentur, Recruitee, Workable, LinkedIn/Indeed über JobSpy) und Board-Entdeckung."""

from __future__ import annotations

import base64
import math
from urllib.parse import urlparse

import respx
from sqlalchemy import select

from conftest import add_job
from jobslop.config import SearchConfig
from jobslop.crawl.base import make_client
from jobslop.crawl.boards import find_board, slug_candidates
from jobslop.crawl.pipeline import run_crawl
from jobslop.crawl.sources import ArbeitsagenturSource, PortalSource, RecruiteeSource, WorkableSource
from jobslop.db import Board, Job, session_scope
from jobslop.guard import check_job
from jobslop.queueing import pick_top

BA = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service"


def _only(config: SearchConfig) -> SearchConfig:
    """Alle Standardquellen aus – jeder Test schaltet nur ein, was er prüft."""
    s = config.sources
    s.greenhouse = s.ashby = s.lever = s.smartrecruiters = s.personio = s.recruitee = s.workable = []
    s.workday, s.amazon_queries, s.generic, s.portals = [], [], [], []
    s.arbeitnow = s.himalayas = s.arbeitsagentur = s.discover_boards = False
    return config


async def test_arbeitsagentur_search_and_details():
    source = ArbeitsagenturSource(["DevOps"], ["berlin"], remote=True, radius_km=30, skip_agencies=True)
    item = {
        "referenznummer": "10001-123-S",
        "stellenangebotsTitel": "DevOps Engineer (m/w/d)",
        "firma": "Spree Cloud GmbH",
        "stellenlokationen": [{"adresse": {"ort": "Berlin", "plz": "10115"}}],
        "datumErsteVeroeffentlichung": "2026-10-20",
    }
    with respx.mock() as router:
        search = router.get(f"{BA}/pc/v6/jobs").respond(json={"ergebnisliste": [item], "maxErgebnisse": 1})
        ref = base64.b64encode(b"10001-123-S").decode()
        router.get(f"{BA}/pc/v4/jobdetails/{ref}").respond(
            json={"stellenangebotsBeschreibung": "Kubernetes und Terraform", "homeofficemoeglich": True}
        )
        async with make_client() as client:
            postings = await source.fetch(client)
            await source.details(client, postings[0])
    assert len(postings) == 1  # vor Ort und Homeoffice liefern dieselbe Stelle nur einmal
    p = postings[0]
    assert p.company == "Spree Cloud GmbH" and p.location == "Berlin, Deutschland"
    assert p.url == "https://www.arbeitsagentur.de/jobsuche/jobdetail/10001-123-S"
    assert "Kubernetes" in p.description and p.workplace == "Hybrid"
    first, remote = search.calls[0].request, search.calls[1].request
    assert first.headers["X-API-Key"] == "jobboerse-jobsuche"
    assert first.url.params["wo"] == "berlin" and first.url.params["zeitarbeit"] == "false"
    assert remote.url.params["arbeitszeit"] == "ho" and "wo" not in remote.url.params


async def test_recruitee_and_workable_boards():
    offer = {
        "id": 7,
        "title": "Platform Engineer",
        "status": "published",
        "city": "Berlin",
        "country": "Germany",
        "remote": False,
        "careers_url": "https://acme.recruitee.com/o/platform",
        "careers_apply_url": "https://acme.recruitee.com/o/platform/c/new",
        "description": "<p>Kubernetes</p>",
        "published_at": "2026-10-01 10:00:00 UTC",
    }
    job = {
        "title": "SRE",
        "shortcode": "AB12",
        "url": "https://apply.workable.com/j/AB12",
        "application_url": "https://apply.workable.com/j/AB12/apply",
        "city": "Berlin",
        "country": "Germany",
        "telecommuting": True,
        "description": "<p>On-call</p>",
    }
    with respx.mock() as router:
        router.get("https://acme.recruitee.com/api/offers/").respond(json={"offers": [offer]})
        router.get("https://apply.workable.com/api/v1/widget/accounts/beta").respond(
            json={"name": "Beta Labs", "jobs": [job]}
        )
        async with make_client() as client:
            rec = await RecruiteeSource("acme:Acme GmbH").fetch(client)
            wor = await WorkableSource("beta").fetch(client)
    assert (
        rec[0].company == "Acme GmbH"
        and rec[0].apply_url.endswith("/c/new")
        and rec[0].location == "Berlin, Germany"
    )
    assert wor[0].company == "Beta Labs" and wor[0].remote and wor[0].workplace == "Remote"


class _FakeJobSpy:
    def __init__(self, rows):
        self.rows = rows
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return list(self.rows)


async def test_linkedin_bundles_queries_and_loads_details():
    fake = _FakeJobSpy(
        [
            {
                "id": "li-42",
                "title": "Site Reliability Engineer",
                "company": "Acme Cloud",
                "location": "Berlin, Berlin, Germany",
                "job_url": "https://www.linkedin.com/jobs/view/42",
                "job_url_direct": math.nan,  # JobSpy liefert NaN für fehlende Werte
                "description": None,
                "is_remote": False,
                "date_posted": "2026-10-25",
            }
        ]
    )
    source = PortalSource(
        "linkedin",
        ["site reliability", "devops"],
        ["berlin"],
        remote=True,
        country="germany",
        results=10,
        hours_old=336,
        pause_s=0,
        scrape=fake,
    )
    with respx.mock() as router:
        router.get("https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/42").respond(
            text='<div class="show-more-less-html__markup">Kubernetes &amp; Go</div>'
        )
        async with make_client() as client:
            postings = await source.fetch(client)
            await source.details(client, postings[0])
    # LinkedIn drosselt: eine ODER-Suche pro Ort (Berlin + remote) statt eine pro Suchbegriff
    assert [c["search_term"] for c in fake.calls] == ['"site reliability" OR devops'] * 2
    assert [c["location"] for c in fake.calls] == ["Berlin, Germany", "Germany"]
    assert fake.calls[1]["is_remote"] is True
    p = postings[0]
    assert p.url == "https://www.linkedin.com/jobs/view/42" and p.posted == "2026-10-25"
    assert p.description == "Kubernetes & Go"


async def test_indeed_prefers_the_employer_link():
    fake = _FakeJobSpy(
        [
            {
                "id": "in-1",
                "title": "DevOps Engineer",
                "company": "Beta GmbH",
                "location": "Berlin, BE, Germany",
                "job_url": "https://de.indeed.com/viewjob?jk=1",
                "job_url_direct": "https://join.com/companies/beta/1-devops",
                "description": "Terraform",
                "is_remote": True,
                "date_posted": None,
            }
        ]
    )
    source = PortalSource(
        "indeed", ["devops", "sre"], ["berlin"], remote=False, country="germany", results=10, hours_old=72,
        pause_s=0, scrape=fake,
    )  # fmt: skip
    async with make_client() as client:
        postings = await source.fetch(client)
    assert len(fake.calls) == 2  # Indeed drosselt nicht: ein Suchbegriff pro Abfrage
    assert postings[0].url == "https://join.com/companies/beta/1-devops"
    assert urlparse(postings[0].extra["portal_url"]).hostname == "de.indeed.com"
    assert postings[0].remote and postings[0].posted == ""


def test_slug_candidates():
    assert slug_candidates("Acme Cloud GmbH") == ["acmecloud", "acme-cloud"]
    assert slug_candidates("Société Générale S.A.") == ["societegenerale", "societe-generale"]
    assert slug_candidates("GmbH") == []


async def test_find_board_needs_the_same_job():
    with respx.mock(assert_all_called=False) as router:
        router.get("https://boards-api.greenhouse.io/v1/boards/acmecloud/jobs").respond(
            json={
                "jobs": [{"id": 1, "title": "Account Executive"}]
            }  # gleicher Name, aber andere Firma/Stelle
        )
        router.get("https://api.ashbyhq.com/posting-api/job-board/acmecloud").respond(
            json={"jobs": [{"id": "a1", "title": "Site Reliability Engineer (m/w/d)", "location": "Berlin"}]}
        )
        router.route().respond(status_code=404)
        async with make_client() as client:
            hit = await find_board(client, "Acme Cloud", ["Site Reliability Engineer"])
    assert hit is not None and hit[:2] == ("ashby", "acmecloud") and len(hit[2]) == 1


HIMALAYAS_JOB = {
    "guid": "https://himalayas.app/companies/acme-cloud/jobs/sre",
    "title": "Site Reliability Engineer",
    "companyName": "Acme Cloud",
    "locationRestrictions": ["Germany"],
    "applicationLink": "https://himalayas.app/companies/acme-cloud/jobs/sre?utm_source=api",
    "description": "<p>Kubernetes</p>",
    "pubDate": 1792900000,
}
GH_BOARD = {
    "jobs": [
        {
            "id": 9,
            "title": "Site Reliability Engineer",
            "location": {"name": "Remote, Germany"},
            "absolute_url": "https://job-boards.greenhouse.io/acmecloud/jobs/9",
            "content": "&lt;p&gt;Kubernetes, Terraform&lt;/p&gt;",
        }
    ]
}


async def test_discovered_board_replaces_cloudflare_job(settings, config):
    config = _only(config)
    s = config.sources
    s.himalayas, s.queries, s.discover_boards = True, ["sre"], True

    def mock(router):
        router.get("https://himalayas.app/jobs/api/search").respond(json={"jobs": [HIMALAYAS_JOB]})
        router.get("https://boards-api.greenhouse.io/v1/boards/acmecloud/jobs").respond(json=GH_BOARD)
        router.get("https://boards-api.greenhouse.io/v1/boards/acmecloud").respond(
            json={"name": "Acme Cloud"}
        )
        router.route().respond(status_code=404)

    with respx.mock(assert_all_called=False) as router:
        mock(router)
        report = await run_crawl(settings, config, enrich=False, use_browser=False)
    assert report.discovered == ["greenhouse:acmecloud"]
    with session_scope(settings.db_path) as db:
        jobs = db.execute(select(Job)).scalars().all()
        assert len(jobs) == 1  # nur ein Eintrag – der Board-Eintrag gewinnt
        job = jobs[0]
        assert job.source == "greenhouse:acmecloud" and job.url.startswith(
            "https://job-boards.greenhouse.io/"
        )
        assert check_job(db, job, config.limits).ok  # direkt bewerbbar, keine Bot-Abfrage mehr
        board = db.execute(select(Board)).scalars().one()
        assert (board.kind, board.slug, board.company) == ("greenhouse", "acmecloud", "Acme Cloud")

    # Zweiter Crawl: das Board ist bekannt und wird direkt abgefragt, ohne neue Suche
    with respx.mock(assert_all_called=False) as router:
        mock(router)
        report2 = await run_crawl(settings, config, enrich=False, use_browser=False)
    assert "greenhouse:acmecloud" in report2.per_source and report2.discovered == []


async def test_unresolved_himalayas_job_is_browser_only(settings, config):
    config = _only(config)
    s = config.sources
    s.himalayas, s.queries, s.discover_boards = True, ["sre"], True
    with respx.mock(assert_all_called=False) as router:
        router.get("https://himalayas.app/jobs/api/search").respond(json={"jobs": [HIMALAYAS_JOB]})
        router.route().respond(status_code=404)  # kein Board zu finden
        await run_crawl(settings, config, enrich=False, use_browser=False)
    linkedin = add_job(
        settings, "https://www.linkedin.com/jobs/view/1", "Gamma AG", "Site Reliability Engineer"
    )
    with session_scope(settings.db_path) as db:
        him = db.execute(select(Job).where(Job.source == "himalayas")).scalars().one()
        verdict = check_job(db, him, config.limits)
        assert not verdict.ok and "eigenen Browser" in verdict.reason
        db.get(Job, linkedin).score = 99
        board = db.execute(select(Board)).scalars().one()
        assert board.kind == ""  # vergeblich gesucht, wird erst nach 30 Tagen erneut geprüft
    config.limits.min_score_for_auto_queue = 0
    picked = pick_top(settings.db_path, config, 10, include_stretch=True)
    assert linkedin not in picked and him.id not in picked  # LinkedIn braucht dich, Himalayas deinen Browser


def test_legacy_himalayas_queries_are_migrated(tmp_path):
    path = tmp_path / "search.toml"
    path.write_text('[sources]\nhimalayas_queries = ["devops", "sre"]\n', encoding="utf-8")
    config = SearchConfig.load(path)
    assert config.sources.queries == ["devops", "sre"] and config.sources.himalayas
    config.save(path)
    assert "himalayas_queries" not in path.read_text(encoding="utf-8")


async def test_board_job_with_vague_location_still_replaces_job_board_entry(settings, config):
    config = _only(config)
    s = config.sources
    s.himalayas, s.queries, s.discover_boards = True, ["sre"], True
    board = {"jobs": [dict(GH_BOARD["jobs"][0], location={"name": "Remote"})]}  # ohne Land
    with respx.mock(assert_all_called=False) as router:
        router.get("https://himalayas.app/jobs/api/search").respond(json={"jobs": [HIMALAYAS_JOB]})
        router.get("https://boards-api.greenhouse.io/v1/boards/acmecloud/jobs").respond(json=board)
        router.route().respond(status_code=404)
        await run_crawl(settings, config, enrich=False, use_browser=False)
    with session_scope(settings.db_path) as db:
        job = db.execute(select(Job)).scalars().one()
        assert job.source == "greenhouse:acmecloud" and job.where == "R"  # Ort aus der Jobbörse übernommen


async def test_stored_descriptions_are_not_fetched_again(settings, config):
    """Arbeitsagentur/LinkedIn brauchen eine Detailseite pro Stelle – gespeicherte Beschreibungen nicht neu laden."""
    config = _only(config)
    s = config.sources
    s.arbeitsagentur, s.queries = True, ["Site Reliability"]
    config.filters.allow_remote = False
    item = {
        "referenznummer": "10001-9-S",
        "stellenangebotsTitel": "Site Reliability Engineer (m/w/d)",
        "firma": "Spree Cloud GmbH",
        "stellenlokationen": [{"adresse": {"ort": "Berlin"}}],
    }
    ref = base64.b64encode(b"10001-9-S").decode()

    async def crawl():
        with respx.mock(assert_all_called=False) as router:
            router.get(f"{BA}/pc/v6/jobs").respond(json={"ergebnisliste": [item]})
            details = router.get(f"{BA}/pc/v4/jobdetails/{ref}").respond(
                json={"stellenangebotsBeschreibung": "Kubernetes, Terraform und Bereitschaft"}
            )
            report = await run_crawl(settings, config, enrich=False, use_browser=False)
        return report, details.call_count

    first, first_calls = await crawl()
    report, second_calls = await crawl()
    assert first.new and first_calls == 1 and second_calls == 0
    assert report.updated == []  # gleiche Beschreibung → keine „Änderung“

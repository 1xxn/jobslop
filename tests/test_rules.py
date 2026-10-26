"""Einordnung, Filter, Guard-Regeln, Seeds."""

from __future__ import annotations

from conftest import add_job
from jobpilot.classify import categorize, html_to_text, level_of, match_key, title_allowed, where_of
from jobpilot.db import Application, Exclusion, Job, session_scope
from jobpilot.guard import check_job
from jobpilot.seeds import import_seeds


def test_title_filter(config):
    f = config.filters
    assert title_allowed("Site Reliability Engineer (m/w/d)", f)[0]
    assert title_allowed("(Senior) Cloud Site Reliability Engineer (Platform)", f)[0]
    assert not title_allowed("Senior Site Reliability Engineer", f)[0]
    assert not title_allowed("Staff Platform Engineer", f)[0]
    assert not title_allowed("Werkstudent DevOps", f)[0]
    assert not title_allowed("Data Platform Engineer", f)[0]
    assert not title_allowed("Account Executive", f)[0]
    assert title_allowed("SRE / Platform Engineer – Remote Germany", f)[0]


def test_level_category_where(config):
    f = config.filters
    assert level_of("Junior Azure Platform Engineer", f) == "J"
    assert level_of("(Senior) DevOps Engineer", f) == "S"
    assert level_of("DevOps Engineer", f) == "O"
    assert categorize("Systems Engineer/DevOps Eng, Managed Operations") == "DevOps"
    assert categorize("Kubernetes Platform Engineer") == "Platform"
    assert categorize("Site Reliability Engineer GCP") == "SRE"
    assert where_of("Berlin, Germany", f) == "B"
    assert where_of("Remote - Germany", f) == "R"
    assert where_of("Berlin; Remote (Germany)", f) == "BR"
    assert where_of("Munich, Germany", f) is None
    assert where_of("Remote - Spain", f) is None
    assert where_of("Germany", f) is None


def test_match_key_ignores_gender_suffix():
    assert match_key("Bundesdruckerei GmbH", "DevOps Engineer (m/w/d)") == match_key(
        "Bundesdruckerei", "DevOps Engineer"
    )


def test_html_to_text():
    assert html_to_text("&lt;p&gt;A&lt;/p&gt;&lt;ul&gt;&lt;li&gt;B&lt;/li&gt;&lt;/ul&gt;").split() == [
        "A",
        "•",
        "B",
    ]


def test_guard_rules(settings, config):
    config.limits.max_per_company_window = 2
    j1 = add_job(settings, "https://a/1", "Bundesdruckerei", "DevOps Engineer – Platform Services")
    j2 = add_job(settings, "https://a/2", "Bundesdruckerei GmbH", "DevOps Engineer – SaaS")
    j3 = add_job(settings, "https://a/3", "Bundesdruckerei", "DevOps Engineer – Digital Platform")
    j4 = add_job(
        settings, "https://linkedin/4", "Bundesdruckerei", "DevOps Engineer – Platform Services (m/w/d)"
    )
    with session_scope(settings.db_path) as s:
        for jid in (j1, j2):
            s.add(Application(job_id=jid, status="submitted"))
    with session_scope(settings.db_path) as s:
        assert "Schon beworben" in check_job(s, s.get(Job, j1), config.limits).reason
        assert "Firmen-Limit" in check_job(s, s.get(Job, j3), config.limits).reason
        assert check_job(s, s.get(Job, j3), config.limits, force=True).ok
        assert "andere Quelle" in check_job(s, s.get(Job, j4), config.limits).reason
        s.add(Exclusion(kind="title", value="(?i)saas"))
    other = add_job(settings, "https://b/1", "Acme", "SaaS Platform Engineer")
    with session_scope(settings.db_path) as s:
        assert "Titel-Ausschluss" in check_job(s, s.get(Job, other), config.limits).reason


def test_seed_import_is_idempotent(settings):
    created, applied = import_seeds(settings.db_path)
    assert created == 141 and applied == 11
    assert import_seeds(settings.db_path) == (0, 0)

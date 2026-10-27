"""Einordnung, Filter, Guard-Regeln, Vorlagen, Konfiguration, Import und Migrationen."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from conftest import add_job
from jobslop.apply.planner import is_final_submit
from jobslop.classify import categorize, html_to_text, level_of, match_key, score, title_allowed, where_of
from jobslop.config import (
    SearchConfig,
    Settings,
    load_settings,
    migrate_legacy_home,
    save_settings,
    search_config_from_preset,
)
from jobslop.db import Application, Exclusion, Job, get_engine, session_scope
from jobslop.guard import check_job
from jobslop.importer import import_jobs

FIXTURES = Path(__file__).parent / "fixtures"


def test_title_filter(config):
    assert title_allowed("Site Reliability Engineer (m/w/d)", config)[0]
    assert title_allowed("(Senior) Cloud Site Reliability Engineer (Platform)", config)[0]
    assert title_allowed("Senior Site Reliability Engineer", config)[0]  # Stretch statt Ausschluss
    assert level_of("Senior Site Reliability Engineer", config.filters) == "S"
    assert not title_allowed("Staff Platform Engineer", config)[0]
    assert not title_allowed("Lead DevOps Engineer", config)[0]
    assert not title_allowed("Werkstudent DevOps", config)[0]
    assert not title_allowed("Data Platform Engineer", config)[0]
    assert not title_allowed("Account Executive", config)[0]
    assert title_allowed("SRE / Platform Engineer – Remote Germany", config)[0]
    # breitere Zielrollen
    assert title_allowed("Linux Administrator (m/w/d)", config)[0]
    assert title_allowed("Netzwerkadministrator (m/w/d)", config)[0]
    assert title_allowed("IT-Systemadministrator Rechenzentrum", config)[0]
    assert title_allowed("IT Engineer Infrastructure & Operations", config)[0]
    assert title_allowed("Fachinformatiker für Systemintegration (m/w/d)", config)[0]
    assert title_allowed("Test Automation Engineer", config)[0]
    assert not title_allowed("Audit Engineer", config)[0]  # "it engineer" nicht mitten im Wort
    assert not title_allowed("Salesforce Administrator", config)[0]
    assert not title_allowed("SAP Basis Administrator", config)[0]


def test_level_category_where(config):
    f = config.filters
    assert level_of("Junior Azure Platform Engineer", f) == "J"
    assert level_of("(Senior) DevOps Engineer", f) == "S"
    assert level_of("DevOps Engineer", f) == "O"
    assert categorize("Systems Engineer/DevOps Eng, Managed Operations", config.roles) == "DevOps"
    assert categorize("Kubernetes Platform Engineer", config.roles) == "Platform"
    assert categorize("Site Reliability Engineer GCP", config.roles) == "SRE"
    assert categorize("Office Manager", config.roles) == "Other"
    assert where_of("Berlin, Germany", f) == "B"
    assert where_of("Remote - Germany", f) == "R"
    assert where_of("Berlin; Remote (Germany)", f) == "BR"
    assert where_of("Munich, Germany", f) is None
    assert where_of("Remote - Spain", f) is None
    assert where_of("Germany", f) is None


def test_presets_make_jobslop_usable_beyond_devops():
    software = search_config_from_preset(["software"], cities=["Hamburg"], remote=False)
    assert [r.name for r in software.roles][:2] == ["Backend", "Fullstack"]
    assert title_allowed("Frontend Developer (m/w/d)", software)[0]  # "frontend" ist hier Zielrolle
    assert not title_allowed("Site Reliability Engineer", software)[0]
    assert where_of("Hamburg, Germany", software.filters) == "B"
    assert where_of("Remote, Germany", software.filters) is None  # Remote abgeschaltet
    both = search_config_from_preset(["cloud", "software"])
    assert title_allowed("Frontend Developer", both)[
        0
    ]  # Ausschluss der einen Vorlage blockiert die andere nicht
    leaders = search_config_from_preset(["cloud"], exclude_leadership=False)
    assert title_allowed("Lead DevOps Engineer", leaders)[0]


def test_score_follows_role_priority(config):
    roles = config.role_names
    first = score(roles[0], 2, "tech", "O", False, "B", roles)
    last = score(roles[-1], 2, "tech", "O", False, "B", roles)
    other = score("Other", 2, "tech", "O", False, "B", roles)
    assert first > last > other
    assert score(roles[0], 2, "tech", "S", False, "B", roles) < first  # Stretch landet weiter unten


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


def test_final_submit_detection():
    def btn(text, form=True, **kw):
        return {"text": text, "form": form, **kw}

    assert is_final_submit(btn("Submit application"), form_filled=False)
    assert is_final_submit(btn("Bewerbung absenden", form=False), form_filled=False)
    assert is_final_submit(btn("Apply"), form_filled=True)  # „Apply“ unter einem ausgefüllten Formular
    assert not is_final_submit(btn("Jetzt bewerben", form=False), form_filled=False)  # Stellenanzeige
    assert not is_final_submit(btn("Apply"), form_filled=False)
    assert not is_final_submit(btn("Weiter"), form_filled=True)
    assert not is_final_submit(btn("Review and submit"), form_filled=True)
    assert not is_final_submit(btn("Submit", cookie=True), form_filled=True)


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


def test_import_is_idempotent(settings, config):
    created, applied = import_jobs(settings.db_path, FIXTURES / "jobs_import.json", config)
    assert (created, applied) == (3, 1)
    assert import_jobs(settings.db_path, FIXTURES / "jobs_import.json", config) == (0, 0)
    with session_scope(settings.db_path) as s:
        jobs = {j.title: j for j in s.execute(Job.__table__.select()).mappings()}
        assert jobs["Site Reliability Engineer"]["category"] == "SRE"
        assert jobs["Cloud Engineer (m/w/d)"]["where"] == "R"
        assert jobs["Platform Engineer"]["starred"]


def test_search_config_roundtrip(tmp_path):
    path = tmp_path / "search.toml"
    config = search_config_from_preset(["data"], cities=["München"])
    config.save(path)
    loaded = SearchConfig.load(path)
    assert loaded.model_dump() == config.model_dump()
    assert path.read_text(encoding="utf-8").startswith("# jobslop")


def test_settings_file_and_env_precedence(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSLOP_HOME", str(tmp_path))
    settings = Settings(home=tmp_path)
    save_settings(settings, {"autopilot_enabled": True, "autopilot_time": "07:15", "apply_mode": "dry-run"})
    loaded = load_settings()
    assert loaded.autopilot_enabled and loaded.autopilot_time == "07:15" and loaded.apply_mode == "dry-run"
    monkeypatch.setenv("JOBSLOP_APPLY_MODE", "auto")  # Umgebung schlägt Datei
    assert load_settings().apply_mode == "auto"
    try:
        save_settings(settings, {"home": "/etc"})
    except ValueError as exc:
        assert "home" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("home darf nicht über das Dashboard änderbar sein")


def test_legacy_home_is_migrated(tmp_path, monkeypatch):
    monkeypatch.delenv("JOBSLOP_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    old = tmp_path / ".jobpilot"
    old.mkdir()
    (old / "jobpilot.db").write_bytes(b"")
    (old / "profile.yaml").write_text(f"documents:\n  cv: {old / 'cv.pdf'}\n", encoding="utf-8")
    new = migrate_legacy_home()
    assert new == tmp_path / ".jobslop" and not old.exists()
    assert (new / "jobslop.db").exists()
    assert ".jobpilot" not in (new / "profile.yaml").read_text(encoding="utf-8")
    assert "setup_completed = true" in (new / "settings.toml").read_text(encoding="utf-8")
    assert migrate_legacy_home() is None  # nur einmal


def test_old_database_gets_new_columns(tmp_path):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE jobs (id INTEGER PRIMARY KEY, fingerprint VARCHAR(64), match_key VARCHAR(300),
            source VARCHAR(40), company VARCHAR(200), title VARCHAR(400), url TEXT);
        INSERT INTO jobs (fingerprint, match_key, source, company, title, url)
            VALUES ('f', 'k', 's', 'Acme', 'SRE', 'https://x');
        CREATE TABLE applications (id INTEGER PRIMARY KEY, job_id INTEGER, status VARCHAR(20),
            artifacts_dir TEXT);
        INSERT INTO applications (job_id, status, artifacts_dir)
            VALUES (1, 'submitted', 'C:/Users/x/.jobpilot/artifacts/0001');
        """
    )
    con.commit()
    con.close()
    get_engine(db)
    con = sqlite3.connect(db)
    job_cols = {r[1] for r in con.execute("PRAGMA table_info(jobs)")}
    app_cols = {r[1] for r in con.execute("PRAGMA table_info(applications)")}
    assert {"starred", "queued", "enrichment"} <= job_cols
    assert {"notes", "follow_up_at", "stage_changed_at"} <= app_cols
    assert con.execute("SELECT starred FROM jobs").fetchone()[0] == 0
    assert ".jobslop" in con.execute("SELECT artifacts_dir FROM applications").fetchone()[0]
    con.close()


def test_import_file_format_is_documented():
    data = json.loads((FIXTURES / "jobs_import.json").read_text(encoding="utf-8"))
    assert {"company", "title", "url"} <= set(data["jobs"][0])


def test_cli_output_survives_non_utf8_streams(monkeypatch):
    import io
    import sys

    from jobslop.cli import utf8_output

    # So sieht stdout unter Windows aus, wenn die Ausgabe umgeleitet wird (Pipe, Aufgabenplanung)
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", stream)
    utf8_output()
    print("↺ 2 wieder offen  − 1 geschlossen")
    stream.flush()
    assert "↺".encode() in raw.getvalue()


def _alive(pid: int) -> bool:
    import os
    import subprocess
    import sys

    if sys.platform == "win32":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, errors="replace"
        ).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_runner_stop_kills_the_whole_process_tree():
    """„Stopp“ muss auch Enkelprozesse (Playwright-Treiber, Chromium) beenden, sonst bleibt das Profil gesperrt."""
    import subprocess
    import sys
    import time

    from jobslop.runner import kill_tree, process_group

    script = (
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "print(child.pid, flush=True)\n"
        "time.sleep(60)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script], stdout=subprocess.PIPE, text=True, **process_group()
    )
    assert proc.stdout is not None
    grandchild = int(proc.stdout.readline())
    kill_tree(proc)
    assert proc.poll() is not None
    deadline = time.monotonic() + 5
    while _alive(grandchild) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not _alive(grandchild)


def test_versions_agree():
    """Der Release-Workflow prüft dasselbe gegen den Tag – hier fällt es schon vorher auf."""
    import tomllib

    import jobslop

    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    package_json = json.loads((root / "frontend" / "package.json").read_text(encoding="utf-8"))["version"]
    assert jobslop.__version__ == pyproject == package_json

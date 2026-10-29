"""Messrahmen für jobslop: API, Crawl, Bewerbungs-Engine, Start, Oberfläche und Speicher – nur mit erfundenen Daten.

Jeder Teil legt einen frischen Temp-Ordner als JOBSLOP_HOME an (nie ~/.jobslop), füllt ihn mit erfundenen Stellen,
Bewerbungen, Snapshots, Rückfragen und Ausschlüssen und misst dort. Claude wird nie aufgerufen: die Engine plant mit
dem Regel-Planer bzw. einer LLM-Attrappe mit fester Latenz, Crawl-Quellen sind per respx nachgebildet (kein Netz).

    uv run python scripts/bench.py api --jobs 5000 20000
    uv run python scripts/bench.py crawl --postings 2000
    uv run python scripts/bench.py engine
    uv run python scripts/bench.py startup
    uv run python scripts/bench.py frontend --jobs 5000 --idle 60
    uv run python scripts/bench.py memory --jobs 5000 --minutes 3
    uv run python scripts/bench.py all --json bench.json
    uv run python scripts/bench.py compare before.json after.json

Zeiten in Millisekunden; p50/p95 über ``--repeat`` Wiederholungen nach zwei Aufwärmläufen.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import gzip
import json
import os
import random
import re
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable, Iterator
from datetime import timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "tests" / "fixtures" / "site"
PROFILE = ROOT / "tests" / "fixtures" / "profile.yaml"
LOCAL = "http://127.0.0.1"
KEEP = False  # --keep: Temp-Ordner nach der Messung behalten


# --------------------------------------------------------------------------- Sicherheit: nie echte Daten


def _refuse_real(home: Path) -> None:
    """Abbruch, wenn ein Ordner in den echten Daten liegt (~/.jobslop, ~/.jobpilot, ~/.jobslop-backup-…)."""
    user = Path.home().resolve()
    resolved = home.resolve()
    for part in (resolved, *resolved.parents):
        if part.parent == user and part.name.startswith((".jobslop", ".jobpilot")):
            raise SystemExit(f"Abbruch: {home} liegt in echten Daten")


def temp_home(kind: str) -> Path:
    home = Path(tempfile.mkdtemp(prefix=f"jobslop-bench-{kind}-")) / "home"
    _refuse_real(home)
    return home


def cleanup(home: Path) -> None:
    if not KEEP:
        shutil.rmtree(home.parent, ignore_errors=True)


# Alles, was versehentlich get_settings() ohne Ordner aufruft, landet in einem Wegwerf-Ordner
os.environ["JOBSLOP_HOME"] = str(temp_home("default"))
for _key in [k for k in os.environ if k.startswith(("JOBSLOP_", "JOBPILOT_")) and k != "JOBSLOP_HOME"]:
    os.environ.pop(_key)


# --------------------------------------------------------------------------- Hilfen


def pct(values: list[float], p: float) -> float:
    """Perzentil nach Nearest-Rank (bei wenigen Werten ehrlicher als Interpolation)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, round(p / 100 * len(ordered) + 0.5))
    return ordered[min(rank, len(ordered)) - 1]


def ms(seconds: float) -> float:
    return round(seconds * 1000, 1)


def table(title: str, header: list[str], rows: list[list[Any]]) -> None:
    widths = [max(len(str(x)) for x in col) for col in zip(header, *rows, strict=False)]
    print(f"\n## {title}\n")
    print(" | ".join(str(h).ljust(w) for h, w in zip(header, widths, strict=True)))
    print("-|-".join("-" * w for w in widths))
    for row in rows:
        print(" | ".join(str(c).ljust(w) for c, w in zip(row, widths, strict=True)))


def session_cookie(settings: Any) -> dict[str, str]:
    """Sitzungs-Cookie des Dashboards (wie nach dem Anmelde-Link von `jobslop`)."""
    from jobslop.web.app import SESSION_COOKIE, dashboard_token

    return {SESSION_COOKIE: dashboard_token(settings)}


def browser_session(home: Path, url: str) -> list[dict[str, Any]]:
    from jobslop.config import Settings

    return [{"name": k, "value": v, "url": url} for k, v in session_cookie(Settings(home=home)).items()]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class SqlCounter:
    """Zählt SQL-Anweisungen (und ihre Zeit) einer Engine – N+1 zeigt sich als oft wiederholte gleiche Anweisung."""

    def __init__(self, engine: Any) -> None:
        from sqlalchemy import event

        self.statements: Counter[str] = Counter()
        self.seconds = 0.0
        event.listen(engine, "before_cursor_execute", self._before)
        event.listen(engine, "after_cursor_execute", self._after)

    def _before(self, conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        conn.info.setdefault("bench_t", []).append(time.perf_counter())
        self.statements[statement] += 1

    def _after(self, conn: Any, *_args: Any) -> None:
        self.seconds += time.perf_counter() - conn.info["bench_t"].pop()

    def reset(self) -> None:
        self.statements.clear()
        self.seconds = 0.0

    @property
    def count(self) -> int:
        return sum(self.statements.values())

    @property
    def repeated(self) -> int:
        return max(self.statements.values(), default=0)


# --------------------------------------------------------------------------- Prozessbaum und Speicher


def _process_pairs() -> list[tuple[int, int]]:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Entry(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_char * 260),
            ]

        k32 = ctypes.windll.kernel32
        k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        snap = k32.CreateToolhelp32Snapshot(0x2, 0)
        entry = Entry()
        entry.dwSize = ctypes.sizeof(Entry)
        pairs = []
        ok = k32.Process32First(snap, ctypes.byref(entry))
        while ok:
            pairs.append((entry.th32ProcessID, entry.th32ParentProcessID))
            ok = k32.Process32Next(snap, ctypes.byref(entry))
        k32.CloseHandle(snap)
        return pairs
    out = subprocess.run(["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True, check=False).stdout
    return [(int(a), int(b)) for a, b in (line.split() for line in out.splitlines() if line.strip())]


def tree_pids(root: int) -> list[int]:
    children: dict[int, list[int]] = defaultdict(list)
    for pid, ppid in _process_pairs():
        children[ppid].append(pid)
    todo, seen = [root], []
    while todo:
        pid = todo.pop()
        if pid in seen:
            continue
        seen.append(pid)
        todo += children.get(pid, [])
    return seen


def memory_mb(pid: int) -> tuple[float, float]:
    """(Working Set/RSS, private Bytes) eines Prozesses in MB – unter Linux/macOS ist beides RSS."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        k32 = ctypes.windll.kernel32
        k32.OpenProcess.restype = wintypes.HANDLE
        handle = k32.OpenProcess(0x1000 | 0x0010, False, pid)
        if not handle:
            return 0.0, 0.0
        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        k32.K32GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
        k32.CloseHandle(handle)
        return counters.WorkingSetSize / 2**20, counters.PagefileUsage / 2**20
    status = Path(f"/proc/{pid}/status")
    if status.exists():
        rss = next((int(x.split()[1]) for x in status.read_text().splitlines() if x.startswith("VmRSS")), 0)
        return rss / 1024, rss / 1024
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True, check=False)
    rss = int(out.stdout.strip() or 0) / 1024
    return rss, rss


def tree_memory_mb(root: int) -> tuple[float, float]:
    """Summe über den Prozessbaum (unter Windows startet die venv-python.exe den eigentlichen Interpreter als Kind)."""
    values = [memory_mb(pid) for pid in tree_pids(root)]
    return sum(v[0] for v in values), sum(v[1] for v in values)


# --------------------------------------------------------------------------- Erfundene Daten

COMPANY_WORDS = [
    "Nord",
    "Spree",
    "Kiez",
    "Havel",
    "Lumen",
    "Ost",
    "Tempel",
    "Moabit",
    "Pankow",
    "Wolken",
    "Kreuz",
]
COMPANY_TAILS = [
    "Cloud",
    "byte",
    "labs",
    "stack",
    "Systems",
    "Robotics",
    "Payments",
    "Energy",
    "Data AG",
    "werk",
]
TITLES = [
    ("Site Reliability Engineer (m/w/d)", "SRE"),
    ("Senior Site Reliability Engineer", "SRE"),
    ("Platform Engineer – Kubernetes", "Platform"),
    ("Cloud Platform Engineer", "Platform"),
    ("DevOps Engineer (all genders)", "DevOps"),
    ("DevSecOps Engineer", "DevOps"),
    ("Cloud Engineer AWS", "Cloud"),
    ("Kubernetes Engineer", "Cloud"),
    ("Linux System Engineer", "System"),
    ("Observability Engineer", "SRE"),
    ("Infrastructure Engineer", "Platform"),
    ("Backend Developer Go", "Other"),
]
LOCATIONS = [
    ("Berlin", "B", "Hybrid"),
    ("Remote, Deutschland", "R", "Remote"),
    ("Berlin oder remote", "BR", ""),
]
SOURCES = ["greenhouse:bench", "ashby:bench", "lever:bench", "arbeitnow", "himalayas", "portal:linkedin"]
WORDS = [
    "Kubernetes",
    "Terraform",
    "Prometheus",
    "Grafana",
    "Incident",
    "SLO",
    "On-Call",
    "Linux",
    "Go",
    "Python",
    "AWS",
    "GCP",
    "Azure",
    "Team",
    "Plattform",
    "Betrieb",
    "Automatisierung",
    "Monitoring",
    "Sicherheit",
    "Skalierung",
    "Verantwortung",
    "Kunden",
    "Produkt",
    "Entwicklung",
    "Qualität",
]


def _descriptions(rnd: random.Random, count: int = 40, size: int = 6000) -> list[str]:
    out = []
    for _ in range(count):
        words: list[str] = []
        while sum(len(w) + 1 for w in words) < size:
            words.append(rnd.choice(WORDS))
        out.append(" ".join(words))
    return out


def seed_home(home: Path, *, jobs: int, demo: bool = True, seed: int = 7) -> dict[str, Any]:
    """Ordner mit erfundenen Daten: ``jobs`` Stellen (6 KB Beschreibung), ~6 % mit Bewerbung samt Ereignissen,
    Snapshots, Rückfragen, Ausschlüssen, Aktivität, Antwortbank, Postfach-Vorschlägen und Boards."""
    from sqlalchemy import insert

    from jobslop.config import Settings, default_search_config, save_settings
    from jobslop.db import (
        Activity,
        Answer,
        Application,
        ApplicationEvent,
        Board,
        CrawlRun,
        Exclusion,
        InboxMessage,
        Job,
        JobSnapshot,
        Prompt,
        session_scope,
        utcnow,
    )
    from jobslop.profile import Profile

    _refuse_real(home)
    rnd = random.Random(seed)
    started = time.perf_counter()
    settings = Settings(home=home)
    settings.ensure_dirs()
    profile = Profile.load(PROFILE)
    cv = settings.documents_dir / "Max_Mustermann_CV.pdf"
    cv.write_bytes(b"%PDF-1.4\n% Bench-Lebenslauf\n")
    profile.documents.cv = "documents/Max_Mustermann_CV.pdf"
    profile.save(settings.profile_path)
    config = default_search_config()
    config.save(settings.search_path)
    save_settings(settings, {"setup_completed": True, "autopilot_enabled": False})
    if demo:
        with settings.settings_path.open("a", encoding="utf-8") as fh:
            fh.write("demo = true\n")

    now = utcnow()
    descriptions = _descriptions(rnd)
    companies = [
        f"{rnd.choice(COMPANY_WORDS)}{rnd.choice(COMPANY_TAILS)} {i}" for i in range(max(10, jobs // 8))
    ]
    job_rows, snap_rows, app_rows, event_rows, prompt_rows = [], [], [], [], []
    runs = 60
    for i in range(1, jobs + 1):
        company = companies[rnd.randrange(len(companies))]
        title, category = TITLES[rnd.randrange(len(TITLES))]
        if rnd.random() < 0.5:  # etwa die Hälfte der Titel kommt nur einmal vor (Team, Produkt, Zusatz)
            title = f"{title} – {rnd.choice(['Team', 'Produkt', 'Bereich', 'Squad'])} {rnd.randrange(jobs)}"
        location, where, workplace = LOCATIONS[rnd.randrange(len(LOCATIONS))]
        level = "S" if title.startswith("Senior") else rnd.choice("OOOMMJ")
        status = "closed" if rnd.random() < 0.15 else "open"
        first_seen = now - timedelta(days=rnd.uniform(0, 120))
        enriched = rnd.random() < 0.3
        job_rows.append(
            {
                "id": i,
                "fingerprint": f"bench:{i}",
                "match_key": f"{company.lower()}|{title.lower()}",
                "source": SOURCES[rnd.randrange(len(SOURCES))],
                "external_id": str(i),
                "company": company,
                "title": title,
                "location": location,
                "where": where,
                "workplace": workplace,
                "url": f"https://jobs.example.com/{i}",
                "apply_url": "",
                "alt_urls": [],
                "category": category,
                "level": level,
                "segment": "tech",
                "fit": rnd.choice([1, 2, 2, 3]),
                "score": round(rnd.uniform(2, 21), 1),
                "language": rnd.choice(["de", "en"]),
                "description": descriptions[i % len(descriptions)] + f" #{i}",
                "content_hash": f"h{i}",
                "posted": first_seen.date().isoformat(),
                "notes": "Notiz zur Stelle" if rnd.random() < 0.01 else "",
                "near": "",
                "origin": "crawl",
                "status": status,
                "queued": rnd.random() < 0.01,
                "starred": rnd.random() < 0.03,
                "first_seen": first_seen,
                "last_seen": now,
                "closed_at": now if status == "closed" else None,
                "enrichment": {"summary": "Kubernetes-Plattform betreiben, On-Call im Team.", "fit": 2}
                if enriched
                else {},
            }
        )
        for change in (
            ["new"] + (["updated"] if rnd.random() < 0.3 else []) + (["closed"] if status == "closed" else [])
        ):
            snap_rows.append(
                {
                    "job_id": i,
                    "crawl_run_id": rnd.randint(1, runs),
                    "seen_at": first_seen,
                    "change": change,
                    "title": title,
                    "location": location,
                    "content_hash": f"h{i}",
                    "diff": {"title": ["alt", title]} if change == "updated" else {},
                }
            )
    app_statuses = (
        ["submitted"] * 35 + ["manual"] * 10 + ["interview"] * 8 + ["rejected"] * 20 + ["offer"] * 2
    )
    app_statuses += ["failed"] * 10 + ["skipped"] * 8 + ["needs_review"] * 4 + ["ready"] * 3
    app_id = 0
    for job_id in rnd.sample(range(1, jobs + 1), k=max(5, jobs * 6 // 100)):
        for _ in range(2 if rnd.random() < 0.1 else 1):
            app_id += 1
            status = rnd.choice(app_statuses)
            start = now - timedelta(days=rnd.uniform(0, 90))
            done = status in ("submitted", "manual", "interview", "rejected", "offer")
            follow = start + timedelta(days=10) if status in ("submitted", "manual", "interview") else None
            app_rows.append(
                {
                    "id": app_id,
                    "job_id": job_id,
                    "status": status,
                    "origin": "jobslop",
                    "mode": "review",
                    "started_at": start,
                    "finished_at": start + timedelta(minutes=4),
                    "submitted_at": start + timedelta(minutes=4) if done else None,
                    "artifacts_dir": "",
                    "final_url": f"https://jobs.example.com/{job_id}/thanks",
                    "confirmation": "Thank you for applying" if done else "",
                    "error": "TimeoutError: Seite lädt nicht" if status == "failed" else "",
                    "open_questions": [{"label": "Visa?", "question": "Visa?"}]
                    if status == "needs_review"
                    else [],
                    "filled": [
                        {
                            "step": 1,
                            "field_id": f"f{k}",
                            "label": f"Feld {k}",
                            "action": "fill",
                            "value": "Max",
                            "ok": True,
                            "detail": "",
                            "source": "profile",
                            "confidence": "high",
                        }
                        for k in range(15)
                    ],
                    "usage": {"calls": 4, "input_tokens": 20000, "output_tokens": 2000},
                    "notes": "",
                    "follow_up_at": follow,
                    "stage_changed_at": start,
                }
            )
            for k in range(12):
                event_rows.append(
                    {
                        "application_id": app_id,
                        "ts": start + timedelta(seconds=10 * k),
                        "kind": ["navigate", "plan", "fill", "review", "decision", "status"][k % 6],
                        "message": "Schritt mit einer Beschreibung von etwa hundert Zeichen, wie sie die Engine schreibt.",
                        "data": {},
                    }
                )
            prompt_rows.append(
                {
                    "application_id": app_id,
                    "kind": "questions",
                    "payload": {"title": "Firma – Stelle", "questions": [{"question": "Visa?"}]},
                    "response": {"answers": {"0": "Nein"}},
                    "status": rnd.choice(["answered", "expired"]),
                    "created_at": start,
                    "answered_at": start,
                }
            )
    # drei offene Rückfragen wie bei einem laufenden Bewerbungslauf
    for n, kind in enumerate(("confirm", "questions", "handoff")):
        prompt_rows.append(
            {
                "application_id": n + 1,
                "kind": kind,
                "payload": {"title": "Nordcloud – SRE", "rows": [{"label": "Vorname", "value": "Max"}] * 15},
                "response": {},
                "status": "open",
                "created_at": now,
                "answered_at": None,
            }
        )
    exclusions = [{"kind": "company", "value": c} for c in rnd.sample(companies, k=10)]
    exclusions += [{"kind": "job", "value": str(j)} for j in rnd.sample(range(1, jobs + 1), k=15)]
    exclusions += [
        {"kind": "title", "value": v} for v in ("werkstudent", "praktik", r"intern\b", "lead|head of")
    ]
    exclusions += [{"kind": "url", "value": v} for v in ("stepstone", "example.org/blocked", "xing.com")]
    with session_scope(settings.db_path) as s:
        s.execute(
            insert(CrawlRun),
            [
                {
                    "id": r,
                    "started_at": now - timedelta(days=runs - r),
                    "finished_at": now - timedelta(days=runs - r) + timedelta(minutes=3),
                    "status": "ok",
                    "sources": ["greenhouse:bench"],
                    "stats": {"fetched": 9000, "kept": 400, "new": 20, "closed": 3},
                    "errors": [],
                }
                for r in range(1, runs + 1)
            ],
        )
        for i in range(0, len(job_rows), 2000):
            s.execute(insert(Job), job_rows[i : i + 2000])
        for rows, model in (
            (snap_rows, JobSnapshot),
            (app_rows, Application),
            (event_rows, ApplicationEvent),
        ):
            for i in range(0, len(rows), 5000):
                s.execute(insert(model), rows[i : i + 5000])
        s.execute(insert(Prompt), prompt_rows)
        s.execute(
            insert(Exclusion),
            [e | {"reason": "Bench", "created_at": now} for e in exclusions],
        )
        s.execute(
            insert(Activity),
            [
                {
                    "ts": now - timedelta(minutes=k),
                    "kind": "crawl",
                    "message": f"Crawl #{k}: 12 neue Stellen",
                    "data": {"code": "crawl.done", "params": {"run": k, "new": 12, "queued": 0}},
                }
                for k in range(3000)
            ],
        )
        s.execute(
            insert(Answer),
            [
                {
                    "question_key": f"frage {k}",
                    "question": f"Frage {k}?",
                    "answer": "Antwort",
                    "uses": k % 5,
                    "created_at": now,
                    "updated_at": now,
                }
                for k in range(100)
            ],
        )
        s.execute(
            insert(InboxMessage),
            [
                {
                    "message_id": f"<bench-{k}@example.com>",
                    "received_at": now - timedelta(days=k),
                    "sender": "jobs@example.com",
                    "subject": "Deine Bewerbung",
                    "kind": rnd.choice(["confirmation", "rejection", "interview"]),
                    "summary": "Absage nach Prüfung",
                    "application_id": k + 1,
                    "status": "open" if k < 4 else "applied",
                    "created_at": now,
                }
                for k in range(min(30, app_id))
            ],
        )
        s.execute(
            insert(Board),
            [
                {
                    "company_key": f"firma {k}",
                    "company": f"Firma {k}",
                    "kind": "greenhouse" if k % 3 == 0 else "",
                    "slug": f"firma{k}" if k % 3 == 0 else "",
                    "jobs": 5,
                    "enabled": True,
                    "checked_at": now,
                }
                for k in range(300)
            ],
        )
    # Wie im Betrieb: Der Server startet auf einer gewachsenen Datenbank mit frischen Verbindungen (eine Verbindung,
    # die selbst geschrieben hat, behält ihr altes Memory-Mapping – das wäre nicht der Normalfall).
    from jobslop.db import _engines

    if (engine := _engines.pop(settings.db_path, None)) is not None:
        engine.dispose()
    return {
        "jobs": jobs,
        "applications": len(app_rows),
        "events": len(event_rows),
        "snapshots": len(snap_rows),
        "prompts": len(prompt_rows),
        "exclusions": len(exclusions),
        "db_mb": round(settings.db_path.stat().st_size / 2**20, 1),
        "seed_s": round(time.perf_counter() - started, 1),
    }


# --------------------------------------------------------------------------- API


def _api_app(home: Path) -> tuple[Any, Any]:
    from fastapi.testclient import TestClient

    from jobslop.config import Settings
    from jobslop.runtime import Runtime
    from jobslop.web.app import create_app

    Runtime.llm = lambda self: None  # type: ignore[method-assign]  # Claude bleibt draußen
    settings = Settings(home=home)
    app = create_app(Runtime.load(settings))
    # ohne „with“: kein Lebenszyklus, also keine Hintergrundprüfung, die mitten in die Messung fragt
    return TestClient(app, base_url=LOCAL, cookies=session_cookie(settings)), settings


def _api_size(size: int, repeat: int, results: dict[str, Any]) -> None:
    """Eine Datengröße: Ordner befüllen, jeden Endpoint messen, Ergebnisse unter ``<Größe>:<Name>`` ablegen."""
    from jobslop.db import get_engine

    home = temp_home(f"api{size}")
    info = seed_home(home, jobs=size)
    client, settings = _api_app(home)
    sql = SqlCounter(get_engine(settings.db_path))
    h = {"X-Jobslop": "1"}

    def measure(
        name: str,
        call: Callable[[], Any],
        after: Callable[[Any], None] | None = None,
        *,
        n: int = repeat,
    ) -> None:
        for _ in range(2):
            r = call()
            if after:
                after(r)
        times, counts, repeated, size_b = [], [], [], 0
        for _ in range(n):
            sql.reset()
            t0 = time.perf_counter()
            r = call()
            times.append(time.perf_counter() - t0)
            counts.append(sql.count)
            repeated.append(sql.repeated)
            size_b = len(r.content)
            if r.status_code >= 400:
                raise SystemExit(f"{name}: HTTP {r.status_code} {r.text[:200]}")
            if after:
                after(r)
        results[f"{size}:{name}"] = {
            "p50": ms(pct(times, 50)),
            "p95": ms(pct(times, 95)),
            "sql": int(statistics.median(counts)),
            "same_sql": int(statistics.median(repeated)),
            "kb": round(size_b / 1024, 1),
        }

    get = client.get
    views = {
        "jobs triage": "view=triage&level=noS&status=open&sort=score&limit=60",
        "jobs triage q=cloud": "view=triage&level=noS&status=open&sort=score&limit=60&q=cloud",
        "jobs triage sort=new": "view=triage&level=noS&status=open&sort=new&limit=60",
        "jobs starred": "view=starred&level=noS&status=open&sort=score&limit=60",
        "jobs queued": "view=queued&level=noS&status=open&sort=score&limit=60",
        "jobs all": "view=all&level=noS&status=all&sort=score&limit=60",
        "jobs dismissed": "view=dismissed&level=noS&status=all&sort=score&limit=60",
        "jobs triage limit=600": "view=triage&level=noS&status=open&sort=score&limit=600",
    }
    measure("status", lambda: get("/api/status"))
    for label, query in views.items():
        measure(label, lambda query=query: get(f"/api/jobs?{query}"))
    triage = get(f"/api/jobs?{views['jobs triage']}").json()["items"]
    detail_id = next(
        j["id"] for j in get(f"/api/jobs?{views['jobs all']}&limit=600").json()["items"] if j["app_id"]
    )
    measure("job detail", lambda: get(f"/api/jobs/{detail_id}"))
    measure("applications", lambda: get("/api/applications"))
    app_id = get("/api/applications").json()[0]["id"]
    measure("application detail", lambda: get(f"/api/applications/{app_id}"))
    measure("pipeline", lambda: get("/api/pipeline"))
    measure("stats", lambda: get("/api/stats"))
    measure("activity", lambda: get("/api/activity?limit=60"))
    measure("crawls", lambda: get("/api/crawls"))
    measure("runner", lambda: get("/api/runner?lines=400"))
    measure("prompts", lambda: get("/api/prompts"))
    measure("exclusions", lambda: get("/api/exclusions"))
    measure("answers", lambda: get("/api/answers"))
    measure("export.csv", lambda: get("/api/export.csv"), n=max(3, repeat // 4))
    # Sichten wie im Dashboard: Taste S (merken) und wieder zurück, X (aussortieren) und Rückgängig
    target = triage[0]["id"]
    measure(
        "triage S (bulk star)",
        lambda: client.post("/api/jobs/bulk", json={"ids": [target], "action": "star"}, headers=h),
        lambda _r: client.post("/api/jobs/bulk", json={"ids": [target], "action": "unstar"}, headers=h),
    )
    measure(
        "triage X (bulk exclude)",
        lambda: client.post("/api/jobs/bulk", json={"ids": [target], "action": "exclude"}, headers=h),
        lambda r: [client.delete(f"/api/exclusions/{x}", headers=h) for x in r.json()["exclusions"]],
    )

    class _Seq:
        """Die Abfragen, die eine Entscheidung im Dashboard auslöst (Liste, Status, Detail)."""

        content = b""
        status_code = 200

    def refetch() -> Any:
        out = _Seq()
        for url in (f"/api/jobs?{views['jobs triage']}", "/api/status", f"/api/jobs/{triage[1]['id']}"):
            r = get(url)
            out.content += r.content
        return out

    measure("triage refetch (jobs+status+detail)", refetch)
    results[f"{size}:seed"] = info
    if (changes := getattr(client.app.state.ctx, "changes", None)) is not None:  # nicht im alten Stand
        changes.close()
    client.close()
    from jobslop.db import _engines

    _engines.pop(settings.db_path).dispose()
    cleanup(home)


def api_bench(sizes: list[int], repeat: int) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for size in sizes:
        _api_size(size, repeat, results)
    rows = []
    for key, v in results.items():
        if key.endswith(":seed"):
            continue
        rows.append([key, v["p50"], v["p95"], v["sql"], v["same_sql"], v["kb"]])
    table("API (TestClient, ms)", ["Endpoint", "p50", "p95", "SQL", "gleiche SQL", "KB"], rows)
    for size in sizes:
        print(f"\nDaten {size}: {results[f'{size}:seed']}")
    return {"api": results}


# --------------------------------------------------------------------------- Crawl


def _gh_job(board: int, n: int, rnd: random.Random, variant: int = 0) -> dict[str, Any]:
    title, _cat = TITLES[(board * 7 + n) % len(TITLES)]
    if n % 10 == 9:
        title = "Sales Manager DACH"  # scheitert am Titelfilter
    location = ["Berlin", "Remote - Germany", "Berlin, Germany", "Munich"][n % 4]
    body = " ".join(rnd.choice(WORDS) for _ in range(450))
    return {
        "id": board * 100_000 + n,
        "title": title,
        "absolute_url": f"https://job-boards.greenhouse.io/bench{board}/jobs/{n}",
        "location": {"name": location},
        "offices": [],
        "content": f"&lt;p&gt;{body} v{variant}&lt;/p&gt;",
        "company_name": f"Bench Board {board}",
        "first_published": "2026-10-01T10:00:00Z",
    }


async def crawl_bench(postings: int, existing: int) -> dict[str, Any]:
    import httpx
    import respx

    from jobslop.config import Settings, default_search_config
    from jobslop.crawl import pipeline
    from jobslop.db import get_engine

    home = temp_home("crawl")
    seed_home(home, jobs=existing, demo=False)
    settings = Settings(home=home)
    config = default_search_config()
    s = config.sources
    boards = max(1, postings // 100)
    s.greenhouse = [f"bench{b}:Bench Board {b}" for b in range(boards)]
    s.queries, s.himalayas, s.arbeitsagentur, s.portals, s.discover_boards, s.generic = (
        ["devops"],
        True,
        False,
        [],
        False,
        [],
    )
    rnd = random.Random(3)
    base = {b: [_gh_job(b, n, rnd) for n in range(100)] for b in range(boards)}
    # Jobbörse (Himalayas): 100 Stellen, die Hälfte davon dieselben Stellen wie auf den Firmen-Boards
    hima = []
    for n in range(100):
        twin = base[n % boards][n % 9]
        company = twin["company_name"] if n % 2 == 0 else f"Remote Firma {n}"
        hima.append(
            {
                "guid": f"https://himalayas.app/companies/x/jobs/{n}",
                "companyName": company,
                "title": twin["title"],
                "applicationLink": f"https://himalayas.app/companies/x/jobs/{n}",
                "description": "<p>" + " ".join(rnd.choice(WORDS) for _ in range(300)) + "</p>",
                "pubDate": 1790000000,
                "locationRestrictions": ["Germany"],
            }
        )

    sql = SqlCounter(get_engine(settings.db_path))
    timing: dict[str, float] = defaultdict(float)
    upsert, gather = pipeline._upsert, pipeline.gather_limited

    def timed_upsert(*args: Any, **kwargs: Any) -> Any:
        t0 = time.perf_counter()
        try:
            return upsert(*args, **kwargs)
        finally:
            timing["upsert"] += time.perf_counter() - t0

    async def timed_gather(coros: list[Awaitable[Any]], limit: int = 6) -> list[Any]:
        t0 = time.perf_counter()
        try:
            return await gather(coros, limit)
        finally:
            timing["fetch"] += time.perf_counter() - t0

    pipeline._upsert = timed_upsert  # type: ignore[assignment]
    pipeline.gather_limited = timed_gather  # type: ignore[assignment]

    def mock(router: respx.MockRouter, jobs: dict[int, list[dict[str, Any]]]) -> None:
        for b, items in jobs.items():
            router.get(f"https://boards-api.greenhouse.io/v1/boards/bench{b}/jobs").respond(
                json={"jobs": items}
            )

        def himalayas(request: httpx.Request) -> httpx.Response:
            page = int(request.url.params.get("page", "1"))
            return httpx.Response(200, json={"jobs": hima[(page - 1) * 20 : page * 20]})

        router.get(url__startswith="https://himalayas.app/jobs/api/search").mock(side_effect=himalayas)

    scenarios: list[tuple[str, dict[int, list[dict[str, Any]]]]] = [("1 neu", base), ("2 unverändert", base)]
    changed = {}
    for b, items in base.items():
        keep = [it for n, it in enumerate(items) if n % 20 != 5]  # 5 % verschwinden → geschlossen
        keep = [
            _gh_job(b, n, rnd, variant=1) if n % 10 == 3 else it for n, it in enumerate(keep)
        ]  # 10 % geändert
        keep += [_gh_job(b, 100 + n, rnd) for n in range(5)]  # 5 % neu
        changed[b] = keep
    scenarios.append(("3 10 % geändert, 5 % weg/neu", changed))
    results: dict[str, Any] = {}
    try:
        for label, jobs in scenarios:
            sql.reset()
            timing.clear()
            with respx.mock(assert_all_called=False) as router:
                mock(router, jobs)
                t0 = time.perf_counter()
                report = await pipeline.run_crawl(settings, config, enrich=False, use_browser=False)
                total = time.perf_counter() - t0
            kept = max(1, report.kept)
            results[label] = {
                "total_ms": ms(total),
                "fetch_ms": ms(timing["fetch"]),
                "upsert_ms": ms(timing["upsert"]),
                "rest_ms": ms(total - timing["fetch"] - timing["upsert"]),
                "sql": sql.count,
                "sql_ms": ms(sql.seconds),
                "sql_per_posting": round(sql.count / kept, 1),
                "fetched": report.fetched,
                "kept": report.kept,
                "new": len(report.new),
                "updated": len(report.updated),
                "closed": len(report.closed),
                "duplicates": report.rejected.get("Dublette", 0),
            }
    finally:
        pipeline._upsert, pipeline.gather_limited = upsert, gather  # type: ignore[assignment]
        from jobslop.db import _engines

        _engines.pop(settings.db_path).dispose()
        cleanup(home)
    table(
        f"Crawl ({postings} Board-Postings + 100 Jobbörse, {existing} Stellen in der DB, ms)",
        [
            "Lauf",
            "gesamt",
            "Abruf",
            "_upsert",
            "Rest",
            "SQL",
            "SQL ms",
            "SQL/Posting",
            "neu/geändert/zu/Dubl.",
        ],
        [
            [
                k,
                v["total_ms"],
                v["fetch_ms"],
                v["upsert_ms"],
                v["rest_ms"],
                v["sql"],
                v["sql_ms"],
                v["sql_per_posting"],
                f"{v['new']}/{v['updated']}/{v['closed']}/{v['duplicates']}",
            ]
            for k, v in results.items()
        ],
    )
    return {"crawl": results}


# --------------------------------------------------------------------------- Bewerbungs-Engine


@contextlib.contextmanager
def fixture_site() -> Iterator[tuple[str, list[dict[str, Any]]]]:
    submissions: list[dict[str, Any]] = []

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a: Any, **kw: Any) -> None:
            super().__init__(*a, directory=str(SITE), **kw)

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            submissions.append(json.loads(self.rfile.read(length) or b"{}"))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", submissions
    finally:
        server.shutdown()


class _Interactor:
    """Beantwortet Rückfragen anhand von Stichworten und gibt das Absenden frei (wie in den Tests)."""

    def __init__(self, answers: dict[str, str]) -> None:
        self.answers = answers

    def info(self, message: str) -> None:
        pass

    async def ask(self, app_id: int, title: str, questions: list[Any]) -> dict[str, str] | None:
        out = {}
        for q in questions:
            hit = next((v for k, v in self.answers.items() if k.lower() in q.question.lower()), None)
            if hit is None:
                return None
            out[q.field_id] = hit
        return out

    async def confirm(self, *_args: Any) -> str:
        return "submit"

    async def handoff(self, *_args: Any, **_kw: Any) -> bool:
        return True


ENGINE_FIXTURES = [
    ("greenhouse_like.html", "Site Reliability Engineer"),
    ("posting.html", "DevOps Engineer"),
    ("ashby_like.html", "Platform Engineer"),
    ("recruitee_like.html", "Platform Engineer"),
    ("toggle_form.html", "Software Engineer"),
    ("popup_posting.html", "Infrastructure Engineer"),
]
ANSWERS = {"visa": "No", "salary": "70000", "hear about": "Company website"}


async def engine_bench(latency: float, rounds: int) -> dict[str, Any]:
    from jobslop.apply import engine as engine_mod
    from jobslop.apply import executor as executor_mod
    from jobslop.apply.engine import ApplyEngine, BrowserSession
    from jobslop.apply.planner import HeuristicPlanner, LLMPlanner
    from jobslop.classify import fingerprint, match_key
    from jobslop.config import Settings, default_search_config
    from jobslop.db import ApplicationEvent, Job, select, session_scope
    from jobslop.llm import LLM, strict_schema
    from jobslop.profile import Profile

    timing: dict[str, list[float]] = defaultdict(list)

    def timed(name: str, fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            t0 = time.perf_counter()
            try:
                return await fn(*args, **kwargs)
            finally:
                timing[name].append(time.perf_counter() - t0)

        return wrapper

    originals = {
        name: getattr(engine_mod, name)
        for name in (
            "settle",
            "save_screenshot",
            "extract_state",
            "dismiss_cookie_banners",
            "reveal_lazy_content",
            "click_element",
            "annotated_screenshots",
        )
    }
    executor_run = executor_mod.Executor.run
    for name, fn in originals.items():
        setattr(engine_mod, name, timed(name, fn))
    executor_mod.Executor.run = timed("executor", executor_run)  # type: ignore[method-assign]

    prompt_sizes: list[tuple[int, int, int]] = []

    class FakeLLM:
        """LLM-Attrappe: misst Prompt-Größen, legt den Arbeitsordner wie das echte LLM an, wartet ``latency`` Sekunden
        und antwortet mit dem Plan des Regel-Planers."""

        def __init__(self, settings: Any, profile: Profile) -> None:
            self.settings = settings
            self.rules = HeuristicPlanner(profile)
            self.current: Any = None
            self.usage = type("U", (), {"as_dict": staticmethod(dict)})()

        async def parse(self, schema: Any, *, system: str, content: Any, **_kw: Any) -> Any:
            t0 = time.perf_counter()
            workdir = self.settings.home / "claude-work" / "bench"
            workdir.mkdir(parents=True, exist_ok=True)
            prompt, _files = LLM._materialize(content, workdir, self.settings.home)
            (workdir / "system.txt").write_text(system, encoding="utf-8")
            schema_json = json.dumps(strict_schema(schema), ensure_ascii=False)
            shutil.rmtree(workdir, ignore_errors=True)
            stable = len(system.split("__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__")[0])
            prompt_sizes.append((stable, len(system) - stable, len(prompt) + len(schema_json)))
            timing["llm_overhead"].append(time.perf_counter() - t0)
            await asyncio.sleep(latency)
            return await self.rules.plan(self.current)

    class BenchLLMPlanner(LLMPlanner):
        async def plan(self, data: Any) -> Any:
            self.llm.current = data  # type: ignore[attr-defined]
            return await super().plan(data)

        def remember(self, question: str, answer: str) -> None:
            super().remember(question, answer)
            self.llm.rules.remember(question, answer)  # type: ignore[attr-defined]

    results: dict[str, Any] = {}
    home = temp_home("engine")
    try:
        settings = Settings(
            home=home, headless=True, vision="never", max_steps_per_application=12, allow_private_targets=True
        )
        settings.ensure_dirs()
        config = default_search_config()
        profile = Profile.load(PROFILE)
        cv = settings.home / "Max_Mustermann_CV.pdf"
        cv.write_bytes(b"%PDF-1.4\n% Test-Lebenslauf\n")
        profile.documents.cv, profile.documents.cover_letter = str(cv), "none"
        with fixture_site() as (base, submissions):
            t0 = time.perf_counter()
            browser = BrowserSession(settings, headless=True)
            await browser.__aenter__()
            results["browser_start_ms"] = ms(time.perf_counter() - t0)
            try:
                for planner_kind in ("rules", f"llm-attrappe {latency:g}s"):
                    for fixture, title in ENGINE_FIXTURES:
                        walls, steps_all = [], []
                        before = {k: len(v) for k, v in timing.items()}
                        for r in range(rounds):
                            url = f"{base}/{fixture}?bench={planner_kind[:3]}{r}"
                            # eigene Firma je Fixture und Runde – sonst greift der Dublettenschutz (schon beworben)
                            company = f"{fixture.split('.')[0]} {r}{planner_kind[:3]}"
                            with session_scope(settings.db_path) as s:
                                job = Job(
                                    fingerprint=fingerprint("bench", url),
                                    match_key=match_key(company, title),
                                    source="bench",
                                    company=company,
                                    title=title,
                                    url=url,
                                    location="Berlin",
                                    where="B",
                                    category="DevOps",
                                )
                                s.add(job)
                                s.flush()
                                job_id = job.id
                            if planner_kind == "rules":
                                planner: Any = HeuristicPlanner(profile)
                            else:
                                fake = FakeLLM(settings, profile)
                                planner = BenchLLMPlanner(
                                    fake, profile, settings.profile_path.parent, [], False
                                )  # type: ignore[arg-type]
                            planner.plan = timed("planner", planner.plan)
                            engine = ApplyEngine(
                                settings=settings,
                                config=config,
                                profile=profile,
                                planner=planner,
                                interactor=_Interactor(ANSWERS),  # type: ignore[arg-type]
                                browser=browser,
                                mode="auto",
                            )
                            sent = len(submissions)
                            t0 = time.perf_counter()
                            outcome = await engine.apply(job_id)
                            walls.append(time.perf_counter() - t0)
                            if outcome.status != "submitted" or len(submissions) != sent + 1:
                                print(f"  ! {fixture}: {outcome.status} {outcome.message[:120]}")
                            with session_scope(settings.db_path) as s:
                                steps_all.append(
                                    len(
                                        s.execute(
                                            select(ApplicationEvent.id).where(
                                                ApplicationEvent.application_id == outcome.application_id,
                                                ApplicationEvent.kind == "plan",
                                            )
                                        ).all()
                                    )
                                )
                        parts = {
                            k: ms(sum(v[before.get(k, 0) :]) / rounds)
                            for k, v in timing.items()
                            if len(v) > before.get(k, 0)
                        }
                        results[f"{planner_kind}:{fixture}"] = {
                            "wall_ms": ms(statistics.median(walls)),
                            "steps": statistics.median(steps_all),
                            "parts_ms": parts,
                        }
            finally:
                await browser.__aexit__(None, None, None)
    finally:
        for name, fn in originals.items():
            setattr(engine_mod, name, fn)
        executor_mod.Executor.run = executor_run  # type: ignore[method-assign]
        from jobslop.db import _engines

        if (engine_obj := _engines.pop(Settings(home=home).db_path, None)) is not None:
            engine_obj.dispose()
        cleanup(home)
    keys = ["settle", "save_screenshot", "dismiss_cookie_banners", "reveal_lazy_content", "extract_state"]
    keys += ["planner", "executor", "click_element"]
    rows = []
    for key, v in results.items():
        if not isinstance(v, dict):
            continue
        rows.append([key, v["wall_ms"], v["steps"], *[v["parts_ms"].get(k, 0) for k in keys]])
    table(
        f"Engine (Fixture-Site, auto, Browser-Start {results['browser_start_ms']} ms, ms pro Bewerbung)",
        [
            "Planer:Fixture",
            "gesamt",
            "Schritte",
            "settle",
            "Screens",
            "Cookies",
            "Lazy",
            "extract",
            "Planer",
            "Executor",
            "Klick",
        ],
        rows,
    )
    if prompt_sizes:
        stable = statistics.median(p[0] for p in prompt_sizes)
        dynamic = statistics.median(p[1] for p in prompt_sizes)
        user = statistics.median(p[2] for p in prompt_sizes)
        overhead = statistics.median(timing["llm_overhead"]) if timing["llm_overhead"] else 0
        results["prompt"] = {
            "system_stable_chars": stable,
            "system_dynamic_chars": dynamic,
            "user_chars": user,
            "llm_call_overhead_ms": ms(overhead),
        }
        print(f"\nPrompt (Median Zeichen): {results['prompt']}")
    return {"engine": results}


# --------------------------------------------------------------------------- Start und Importe


def _wall(cmd: list[str], runs: int, env: dict[str, str] | None = None) -> float:
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        subprocess.run(cmd, capture_output=True, check=False, env=env, cwd=ROOT)
        times.append(time.perf_counter() - t0)
    return statistics.median(times)


def _importtime(module: str) -> list[tuple[str, int, int]]:
    out = subprocess.run(
        [sys.executable, "-X", "importtime", "-c", f"import {module}"],
        capture_output=True,
        text=True,
        check=False,
    ).stderr
    rows = []
    for line in out.splitlines():
        m = re.match(r"import time:\s+(\d+) \|\s+(\d+) \|( *)(\S+)", line)
        if m and len(m.group(3)) <= 3:  # das Modul selbst und seine direkten Importe
            rows.append((m.group(4), int(m.group(1)), int(m.group(2))))
    return sorted(rows, key=lambda r: -r[2])


@contextlib.contextmanager
def dashboard(home: Path) -> Iterator[tuple[str, subprocess.Popen[bytes], float]]:
    """Startet ``jobslop start`` als eigenen Prozess gegen ``home`` und beendet ihn samt Prozessbaum."""
    import httpx

    from jobslop.runner import kill_tree, process_group

    _refuse_real(home)
    port = free_port()
    env = os.environ | {"JOBSLOP_HOME": str(home), "JOBSLOP_AUTOPILOT_ENABLED": "false", "PYTHONUTF8": "1"}
    log = (home / "bench-server.log").open("wb")
    t0 = time.perf_counter()
    proc = subprocess.Popen(
        [sys.executable, "-m", "jobslop", "start", "--no-open", "--port", str(port)],
        stdout=log,
        stderr=subprocess.STDOUT,
        env=env,
        cwd=ROOT,
        **process_group(),
    )
    url = f"http://127.0.0.1:{port}"
    try:
        while True:
            with contextlib.suppress(httpx.HTTPError):
                # /api/ping: antwortet ohne Anmeldung (ältere Stände ohne Sitzung: /api/status)
                if httpx.get(f"{url}/api/ping", timeout=2).status_code == 200:
                    break
            if proc.poll() is not None or time.perf_counter() - t0 > 90:
                raise SystemExit(
                    f"Dashboard startet nicht:\n{(home / 'bench-server.log').read_text()[-2000:]}"
                )
            time.sleep(0.02)
        ready = time.perf_counter() - t0
        # Wie früher die Bereitschaftsprobe über /api/status: der erste Status-Abruf (SQL-Kompilierung, erste
        # Zählung) ist danach warm – sonst zählte die erste Seite der Oberflächen-Messung ihn mit
        from jobslop.config import Settings

        with contextlib.suppress(httpx.HTTPError):
            httpx.get(f"{url}/api/status", timeout=10, cookies=session_cookie(Settings(home=home)))
        yield url, proc, ready
    finally:
        kill_tree(proc)
        log.close()


def startup_bench(runs: int) -> dict[str, Any]:
    py = sys.executable
    results: dict[str, Any] = {
        "python -c pass": ms(_wall([py, "-c", "pass"], runs)),
        "import jobslop.cli": ms(_wall([py, "-c", "import jobslop.cli"], runs)),
        "import jobslop.web.app": ms(_wall([py, "-c", "import jobslop.web.app"], runs)),
        "jobslop --help": ms(_wall([py, "-m", "jobslop", "--help"], runs)),
        "jobslop apply --help": ms(_wall([py, "-m", "jobslop", "apply", "--help"], runs)),
        # Was ein Bewerbungslauf (eigener Prozess pro Lauf) vor dem Browserstart importiert
        "import apply-Pfad (+ playwright)": ms(
            _wall([py, "-c", "import jobslop.cli, jobslop.runtime, playwright.async_api"], runs)
        ),
    }
    ready = []
    for _ in range(max(1, runs // 2)):
        home = temp_home("start")
        seed_home(home, jobs=200)
        with dashboard(home) as (_url, _proc, seconds):
            ready.append(seconds)
        cleanup(home)
    results["dashboard bis /api/status antwortet"] = ms(statistics.median(ready))
    table("Start (Median Wanduhr, ms)", ["Messung", "ms"], [[k, v] for k, v in results.items()])
    for module in ("jobslop.cli", "jobslop.web.app"):
        top = _importtime(module)[:12]
        table(
            f"Importe von {module} (µs, kumuliert)", ["Modul", "selbst", "kumuliert"], [list(t) for t in top]
        )
        results[f"importtime {module}"] = {name: cum for name, _self, cum in top}
    return {"startup": results}


# --------------------------------------------------------------------------- Oberfläche

OBSERVER_JS = """
(() => {
  const b = (window.__bench = { longtasks: [], events: [], paints: [], lcp: 0 });
  try {
    new PerformanceObserver((l) => l.getEntries().forEach((e) => b.longtasks.push([e.startTime, e.duration])))
      .observe({ type: "longtask", buffered: true });
    new PerformanceObserver((l) => l.getEntries().forEach((e) => {
      if (e.interactionId) b.events.push([e.name, e.startTime, e.duration]);
    })).observe({ type: "event", durationThreshold: 16, buffered: true });
    new PerformanceObserver((l) => l.getEntries().forEach((e) => (b.lcp = e.startTime)))
      .observe({ type: "largest-contentful-paint", buffered: true });
  } catch (e) {}
  // Wann erscheint was – in der Zeit der Seite (ab Navigationsstart, ohne Start des Browserprozesses)
  b.marks = {};
  new MutationObserver(() => {
    for (const [key, sel] of [["shell", "nav"], ["heading", "main h1"], ["row", "[role=option]"]]) {
      if (!(key in b.marks) && document.querySelector(sel)) b.marks[key] = Math.round(performance.now());
    }
  }).observe(document, { subtree: true, childList: true });
  // Taste bis zum nächsten Bild (wie INP: Verarbeitung + Rendern + Malen)
  addEventListener("keydown", (e) => {
    const t0 = performance.now();
    requestAnimationFrame(() => setTimeout(() => b.paints.push([e.key, performance.now() - t0]), 0));
  }, true);
})();
"""


def bundle_report() -> dict[str, Any]:
    import jobslop

    out = {}
    # die gebaute Oberfläche des gemessenen Pakets (auch bei einem zweiten Checkout als Vergleich)
    for path in sorted((Path(jobslop.__file__).parent / "web" / "dist" / "assets").glob("*")):
        if path.suffix in (".js", ".css"):
            data = path.read_bytes()
            out[path.name] = {
                "kb": round(len(data) / 1024, 1),
                "gzip_kb": round(len(gzip.compress(data)) / 1024, 1),
            }
    return out


async def frontend_bench(jobs: int, idle_s: int) -> dict[str, Any]:
    from playwright.async_api import async_playwright

    home = temp_home("ui")
    seed_home(home, jobs=jobs)
    results: dict[str, Any] = {}
    try:
        with dashboard(home) as (url, _proc, _ready):
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)

                async def load(path: str, ready: str, context: Any = None) -> tuple[Any, Any, dict[str, Any]]:
                    if context is None:
                        context = await browser.new_context(
                            viewport={"width": 1440, "height": 900}, locale="de-DE"
                        )
                        await context.add_cookies(browser_session(home, url))
                    ctx = context
                    await ctx.add_init_script(OBSERVER_JS)
                    page = await ctx.new_page()
                    requests: list[Any] = []
                    page.on("requestfinished", lambda r: requests.append(r))
                    t0 = time.perf_counter()
                    await page.goto(url + path, wait_until="domcontentloaded")
                    await page.wait_for_selector(ready, timeout=30_000)
                    ready_ms = ms(time.perf_counter() - t0)
                    await page.wait_for_load_state("networkidle")
                    nav = await page.evaluate(
                        "(() => { const n = performance.getEntriesByType('navigation')[0];"
                        " const f = performance.getEntriesByName('first-contentful-paint')[0];"
                        " return {dcl: n.domContentLoadedEventEnd, load: n.loadEventEnd, fcp: f ? f.startTime : 0,"
                        " lcp: window.__bench.lcp, longtasks: window.__bench.longtasks, marks: window.__bench.marks}; })()"
                    )
                    sizes = [await r.sizes() for r in requests]
                    info = {
                        # Seitenkopf bzw. erste Zeile sichtbar, gemessen in der Seite ab Navigationsstart
                        "heading_ms": nav["marks"].get("heading"),
                        "row_ms": nav["marks"].get("row"),
                        "ready_ms": ready_ms,  # inkl. Start des Browserprozesses (Playwright-Sicht)
                        "fcp_ms": round(nav["fcp"], 1),
                        "lcp_ms": round(nav["lcp"], 1),
                        "load_ms": round(nav["load"], 1),
                        "longtasks": len(nav["longtasks"]),
                        "longtask_ms": round(sum(d for _s, d in nav["longtasks"]), 1),
                        "requests": len(requests),
                        "kb": round(sum(s["responseBodySize"] for s in sizes) / 1024, 1),
                        "api_requests": sum(1 for r in requests if "/api/" in r.url),
                    }
                    return ctx, page, info

                ctx, page, results["load / (Heute), kalt"] = await load("/", "main h1")
                await page.close()
                _c, page, results["load /jobs, Cache warm"] = await load("/jobs", "[role=option]", ctx)
                await ctx.close()
                ctx, page, results["load /jobs, kalt"] = await load("/jobs", "[role=option]")

                # Sichten: X (aussortieren) bis die Zeile verschwindet, Z (Rückgängig) bis sie wieder da ist
                async def active_id() -> int:
                    for _ in range(100):
                        m = re.search(r"job=(\d+)", page.url)
                        if m:
                            return int(m.group(1))
                        await asyncio.sleep(0.05)
                    raise SystemExit("keine aktive Stelle")

                await page.evaluate("window.__bench.paints = []; window.__bench.longtasks = []")
                x_times, z_times = [], []
                for _ in range(8):
                    jid = await active_id()
                    await page.locator(f"#job-row-{jid}").focus()
                    t0 = time.perf_counter()
                    await page.keyboard.press("x")
                    await page.wait_for_selector(f"#job-row-{jid}", state="detached", timeout=15_000)
                    x_times.append(time.perf_counter() - t0)
                    t0 = time.perf_counter()
                    await page.keyboard.press("z")
                    await page.wait_for_selector(f"#job-row-{jid}", timeout=15_000)
                    z_times.append(time.perf_counter() - t0)
                    await page.wait_for_load_state("networkidle")
                bench = await page.evaluate("window.__bench")
                paints = [d for _k, d in bench["paints"]]
                results["triage X bis Zeile weg"] = {
                    "p50_ms": ms(pct(x_times, 50)),
                    "p95_ms": ms(pct(x_times, 95)),
                }
                results["triage Z bis Zeile zurück"] = {
                    "p50_ms": ms(pct(z_times, 50)),
                    "p95_ms": ms(pct(z_times, 95)),
                }
                results["triage Taste→Bild"] = {
                    "p50_ms": round(pct(paints, 50), 1),
                    "max_ms": round(max(paints, default=0), 1),
                    "longtasks": len(bench["longtasks"]),
                    "inp_events_ms": [round(d, 1) for _n, _s, d in bench["events"]][-10:],
                }

                # Lange Liste: „Mehr“ bis 600 Zeilen, dann J (nächste Stelle) – rendert die ganze Liste neu?
                for rows in (60, 600):
                    while await page.locator("[role=option]").count() < rows:
                        more = page.get_by_role("button", name=re.compile(r"(weitere|more)", re.I))
                        if not await more.count():
                            break
                        n = await page.locator("[role=option]").count()
                        t0 = time.perf_counter()
                        await more.first.click()
                        # (wait_for_function mit Text scheitert an der CSP des Dashboards: kein eval)
                        await page.locator("[role=option]").nth(n).wait_for()
                        results[f"mehr laden bis {rows}"] = {"last_ms": ms(time.perf_counter() - t0)}
                    await page.wait_for_load_state("networkidle")
                    await page.evaluate("window.__bench.paints = []; window.__bench.longtasks = []")
                    jid = await active_id()
                    await page.locator(f"#job-row-{jid}").focus()
                    for _ in range(15):
                        await page.keyboard.press("j")
                        await asyncio.sleep(0.12)
                    bench = await page.evaluate("window.__bench")
                    paints = [d for _k, d in bench["paints"]]
                    results[f"J mit {await page.locator('[role=option]').count()} Zeilen Taste→Bild"] = {
                        "p50_ms": round(pct(paints, 50), 1),
                        "p95_ms": round(pct(paints, 95), 1),
                        "longtasks": len(bench["longtasks"]),
                    }

                # Polling: Netzwerkverkehr pro Minute, Seite offen ohne Bedienung
                for path, ready in (("/jobs", "[role=option]"), ("/", "main h1")):
                    await page.goto(url + path)
                    await page.wait_for_selector(ready)
                    await page.wait_for_load_state("networkidle")
                    seen: list[Any] = []

                    def collect(r: Any, seen: list[Any] = seen) -> None:
                        seen.append(r)

                    page.on("requestfinished", collect)
                    await asyncio.sleep(idle_s)
                    page.remove_listener("requestfinished", collect)
                    sizes = [await r.sizes() for r in seen]
                    per_min = 60 / idle_s
                    results[f"Polling {path} pro Minute"] = {
                        "requests": round(len(seen) * per_min, 1),
                        "kb": round(sum(s["responseBodySize"] for s in sizes) / 1024 * per_min, 1),
                        "endpoints": dict(Counter(r.url.split("?")[0].replace(url, "") for r in seen)),
                    }
                await browser.close()
    finally:
        cleanup(home)
    results["bundle"] = bundle_report()
    rows = []
    for key, v in results.items():
        if key == "bundle":
            continue
        rows.append([key, json.dumps(v, ensure_ascii=False)[:150]])
    table(f"Oberfläche ({jobs} Stellen, Chromium headless)", ["Messung", "Werte"], rows)
    table(
        "Bundle (dist/assets)",
        ["Datei", "KB", "gzip KB"],
        [[k, v["kb"], v["gzip_kb"]] for k, v in results["bundle"].items()],
    )
    return {"frontend": results}


# --------------------------------------------------------------------------- Speicher


def memory_bench(jobs: int, minutes: float) -> dict[str, Any]:
    import httpx

    from jobslop.config import Settings

    home = temp_home("mem")
    seed_home(home, jobs=jobs)
    samples: list[tuple[float, float, float, int]] = []
    try:
        with (
            dashboard(home) as (url, proc, _ready),
            httpx.Client(base_url=url, timeout=30, cookies=session_cookie(Settings(home=home))) as client,
        ):
            ids = [j["id"] for j in client.get("/api/jobs?view=all&status=all&limit=500").json()["items"]]
            rnd = random.Random(1)
            requests = 0
            # Ein offenes Dashboard, zeitgerafft: Status in jeder Runde, Liste/Detail/Bewerbungen seltener
            pattern = [
                (1, "/api/status"),
                (5, "/api/jobs?view=triage&level=noS&status=open&sort=score&limit=60"),
                (10, "/api/jobs/{id}"),
                (20, "/api/applications"),
                (20, "/api/pipeline"),
                (20, "/api/stats"),
                (30, "/api/runner?lines=400"),
            ]
            t0 = time.perf_counter()
            last_sample = 0.0
            tick = 0
            while (elapsed := time.perf_counter() - t0) < minutes * 60:
                tick += 1
                for every, path in pattern:
                    if tick % every == 0:
                        client.get(path.replace("{id}", str(rnd.choice(ids))))
                        requests += 1
                if elapsed - last_sample >= 2 or tick == 1:
                    last_sample = elapsed
                    rss, private = tree_memory_mb(proc.pid)
                    samples.append((round(elapsed, 1), round(rss, 1), round(private, 1), requests))
            rss, private = tree_memory_mb(proc.pid)
            samples.append((round(time.perf_counter() - t0, 1), round(rss, 1), round(private, 1), requests))
    finally:
        cleanup(home)
    first = samples[min(2, len(samples) - 1)]  # nach dem Aufwärmen
    last = samples[-1]
    per_k = (last[2] - first[2]) / max(1, (last[3] - first[3]) / 1000)
    result = {
        "requests": last[3],
        "rss_start_mb": first[1],
        "rss_peak_mb": max(s[1] for s in samples),
        "rss_end_mb": last[1],
        "private_start_mb": first[2],
        "private_end_mb": last[2],
        "private_growth_mb_per_1000_req": round(per_k, 2),
        "samples": samples,
    }
    table(
        f"Speicher Dashboard-Server ({jobs} Stellen, {minutes:g} min Dauerlast)",
        [
            "Anfragen",
            "RSS Start",
            "RSS Spitze",
            "RSS Ende",
            "privat Start",
            "privat Ende",
            "MB/1000 Anfragen",
        ],
        [
            [
                result["requests"],
                first[1],
                result["rss_peak_mb"],
                last[1],
                first[2],
                last[2],
                result["private_growth_mb_per_1000_req"],
            ]
        ],
    )
    return {"memory": result}


# --------------------------------------------------------------------------- Vergleich


def compare(before_path: Path, after_path: Path) -> None:
    before = json.loads(before_path.read_text(encoding="utf-8"))
    after = json.loads(after_path.read_text(encoding="utf-8"))
    rows = []
    for key, old in before.get("api", {}).items():
        new = after.get("api", {}).get(key)
        if new and "p50" in old:
            change = (new["p50"] - old["p50"]) / old["p50"] * 100 if old["p50"] else 0
            rows.append([key, old["p50"], new["p50"], f"{change:+.0f} %", old["sql"], new["sql"]])
    if rows:
        table(
            "API vorher/nachher (p50 ms, SQL)",
            ["Endpoint", "vorher", "nachher", "Δ", "SQL vorher", "SQL nachher"],
            rows,
        )
    for section in ("crawl", "engine", "startup", "frontend", "memory"):
        if section in before and section in after:
            print(f"\n## {section}\nvorher: {json.dumps(before[section], ensure_ascii=False)[:1500]}")
            print(f"nachher: {json.dumps(after[section], ensure_ascii=False)[:1500]}")


# --------------------------------------------------------------------------- Aufruf


def main() -> None:
    global KEEP
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "what", choices=["api", "crawl", "engine", "startup", "frontend", "memory", "all", "compare"]
    )
    parser.add_argument("files", nargs="*", type=Path, help="compare: vorher.json nachher.json")
    parser.add_argument("--jobs", type=int, nargs="+", default=[5000, 20000])
    parser.add_argument("--repeat", type=int, default=20)
    parser.add_argument("--postings", type=int, default=2000)
    parser.add_argument(
        "--existing", type=int, default=5000, help="Crawl: Stellen, die schon in der DB stehen"
    )
    parser.add_argument("--latency", type=float, default=2.0, help="Engine: Antwortzeit der LLM-Attrappe (s)")
    parser.add_argument("--rounds", type=int, default=2, help="Engine: Bewerbungen pro Fixture")
    parser.add_argument("--runs", type=int, default=5, help="Start: Wiederholungen")
    parser.add_argument("--idle", type=int, default=60, help="Oberfläche: Sekunden Polling-Messung")
    parser.add_argument("--minutes", type=float, default=3.0, help="Speicher: Dauer der Last")
    parser.add_argument("--json", type=Path, help="Ergebnisse zusätzlich als JSON schreiben")
    parser.add_argument("--keep", action="store_true", help="Temp-Ordner behalten")
    args = parser.parse_args()
    KEEP = args.keep
    if args.what == "compare":
        compare(*args.files[:2])
        return
    import jobslop

    print(f"jobslop {jobslop.__version__} aus {Path(jobslop.__file__).parent}")
    out: dict[str, Any] = {"python": sys.version.split()[0], "platform": sys.platform}
    todo = ["api", "crawl", "engine", "startup", "frontend", "memory"] if args.what == "all" else [args.what]
    for what in todo:
        print(f"\n# {what}", flush=True)
        if what == "api":
            out |= api_bench(args.jobs, args.repeat)
        elif what == "crawl":
            out |= asyncio.run(crawl_bench(args.postings, args.existing))
        elif what == "engine":
            out |= asyncio.run(engine_bench(args.latency, args.rounds))
        elif what == "startup":
            out |= startup_bench(args.runs)
        elif what == "frontend":
            out |= asyncio.run(frontend_bench(args.jobs[0], args.idle))
        elif what == "memory":
            out |= memory_bench(args.jobs[0], args.minutes)
    if args.json:
        args.json.write_bytes(json.dumps(out, ensure_ascii=False, indent=1).encode("utf-8"))
        print(f"\nJSON: {args.json}")


if __name__ == "__main__":
    try:
        main()
    finally:  # auch nach „compare“ oder einem Fehler: den Wegwerf-Ordner für JOBSLOP_HOME entfernen
        shutil.rmtree(Path(os.environ["JOBSLOP_HOME"]).parent, ignore_errors=True)

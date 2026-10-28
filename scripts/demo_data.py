"""Erzeugt einen Demo-Datenordner mit erfundenen Daten (für Screenshots, Entwicklung und Tests der Oberfläche).

    uv run python scripts/demo_data.py --home .demo-home
    JOBSLOP_HOME=.demo-home uv run jobslop

Alle Firmen, Personen und Stellen sind frei erfunden.
"""

from __future__ import annotations

import argparse
import random
import shutil
from datetime import timedelta
from pathlib import Path

from jobslop.autopilot import activity
from jobslop.classify import fingerprint, match_key
from jobslop.config import Settings, default_search_config, save_settings
from jobslop.db import (
    Answer,
    Application,
    ApplicationEvent,
    CrawlRun,
    InboxMessage,
    Job,
    JobSnapshot,
    Prompt,
    session_scope,
    utcnow,
)
from jobslop.profile import Profile

ROOT = Path(__file__).resolve().parents[1]

COMPANIES = [
    ("Nordwind Cloud", "tech"),
    ("Spreebyte", "tech"),
    ("Kiezlabs", "tech"),
    ("Havelstack", "tech"),
    ("Lumen Mobility", "tech"),
    ("Ostkreuz Systems", "corp"),
    ("Tempelhof Robotics", "tech"),
    ("Moabit Payments", "tech"),
    ("Pankow Energy", "corp"),
    ("Brandenburg Data AG", "corp"),
    ("Mitte Consulting", "cons"),
    ("Wolkenwerk", "tech"),
    ("Kreuzberg Health", "tech"),
    ("Lichtenberg Logistics", "corp"),
]
TITLES = [
    ("Site Reliability Engineer (m/w/d)", "SRE", 3),
    ("Senior Site Reliability Engineer", "SRE", 3),
    ("Platform Engineer – Kubernetes", "Platform", 3),
    ("Cloud Platform Engineer", "Platform", 2),
    ("DevOps Engineer (all genders)", "DevOps", 3),
    ("DevSecOps Engineer", "DevOps", 2),
    ("Cloud Engineer AWS", "Cloud", 2),
    ("Kubernetes Engineer", "Cloud", 3),
    ("Linux System Engineer", "System", 2),
    ("IT Operations Engineer", "System", 1),
    ("Observability Engineer", "SRE", 3),
    ("Infrastructure Engineer", "Platform", 2),
]
LOCATIONS = [
    ("Berlin", "B", "Hybrid"),
    ("Remote, Deutschland", "R", "Remote"),
    ("Berlin oder remote", "BR", "Hybrid"),
]
SUMMARIES = [
    "Betrieb einer Kubernetes-Plattform auf GCP mit Fokus auf SLOs und Incident Response.",
    "Aufbau von CI/CD und Infrastructure as Code (Terraform) für ein wachsendes Produktteam.",
    "Observability-Stack mit Prometheus und Grafana weiterentwickeln, On-Call im Team.",
]


def build(home: Path, *, seed: int = 7) -> None:
    rnd = random.Random(seed)
    if home.exists():
        shutil.rmtree(home)
    settings = Settings(home=home)
    settings.ensure_dirs()
    profile = Profile.load(ROOT / "tests" / "fixtures" / "profile.yaml")
    cv = settings.documents_dir / "Max_Mustermann_CV.pdf"
    cv.write_bytes(b"%PDF-1.4\n% Demo-Lebenslauf\n")
    profile.documents.cv = "documents/Max_Mustermann_CV.pdf"
    profile.work.years_experience_total = "5"
    profile.work.years_experience_relevant = "4"
    profile.work.notice_period = "3 Monate zum Monatsende"
    profile.work.earliest_start = "01.03.2027"
    profile.work.salary_expectation_eur = "72000"
    profile.save(settings.profile_path)
    config = default_search_config()
    config.save(settings.search_path)
    # Autopilot aus und Demo-Modus an: ein Demo-Server darf nie echt crawlen, bewerben oder Nachrichten senden.
    # „demo“ ist im Dashboard nicht änderbar und steht deshalb direkt in settings.toml.
    save_settings(settings, {"setup_completed": True, "autopilot_enabled": False, "autopilot_time": "08:00"})
    with settings.settings_path.open("a", encoding="utf-8") as fh:
        fh.write("demo = true\n")
    roles = config.role_names
    now = utcnow()

    with session_scope(settings.db_path) as s:
        runs = []
        for i in range(6):
            started = now - timedelta(days=12 - 2 * i, hours=rnd.randint(0, 3))
            run = CrawlRun(
                started_at=started,
                finished_at=started + timedelta(minutes=3),
                status="ok" if i != 2 else "partial",
                stats={
                    "fetched": rnd.randint(9000, 13000),
                    "kept": rnd.randint(300, 420),
                    "new": rnd.randint(4, 40),
                    "closed": rnd.randint(0, 9),
                },
                errors=["himalayas: ReadTimeout"] if i == 2 else [],
            )
            s.add(run)
            runs.append(run)
        s.flush()

        jobs: list[Job] = []
        for n in range(46):
            company, segment = COMPANIES[n % len(COMPANIES)]
            title, category, fit = TITLES[(n * 5 + n // 3) % len(TITLES)]
            location, where, workplace = LOCATIONS[n % len(LOCATIONS)]
            level = "S" if title.startswith("Senior") else rnd.choice(["O", "M", "O"])
            idx = roles.index(category)
            score = round(
                10 * (1 - idx / len(roles))
                + fit * 2
                + {"tech": 2, "corp": 1, "cons": 0.5}[segment]
                + (-4 if level == "S" else 0.5)
                - (0.5 if where == "R" else 0)
                + rnd.random(),
                1,
            )
            url = f"https://careers.example.com/{company.lower().replace(' ', '-')}/{n}"
            job = Job(
                fingerprint=fingerprint("demo", url),
                match_key=match_key(company, title),
                source=rnd.choice(["greenhouse:demo", "ashby:demo", "arbeitnow", "personio:demo"]),
                company=company,
                title=title,
                location=location,
                where=where,
                workplace=workplace,
                url=url,
                category=category,
                level=level,
                segment=segment,
                fit=fit,
                score=score,
                language="de",
                description="Wir suchen Verstärkung für unser Plattform-Team.\n\n• Kubernetes, Terraform, GCP oder AWS\n• Monitoring mit Prometheus und Grafana\n• Python oder Go\n• Rufbereitschaft im Team",
                first_seen=now - timedelta(days=rnd.randint(0, 20), hours=rnd.randint(0, 20)),
                starred=n in (3, 9),
                queued=n in (1, 4, 6),
                enrichment={
                    "required_years": rnd.choice([0, 2, 3]),
                    "seniority": "mid",
                    "fit": fit,
                    "fit_reason": "Kubernetes, Terraform und Observability decken sich mit dem Profil.",
                    "german_required": n % 4 == 0,
                    "workplace": workplace,
                    "red_flags": ["24/7-Rufbereitschaft"] if n % 7 == 0 else [],
                    "summary": SUMMARIES[n % len(SUMMARIES)],
                }
                if n % 3 != 2
                else {},
            )
            s.add(job)
            jobs.append(job)
        s.flush()
        for job in jobs:
            s.add(
                JobSnapshot(
                    job=job,
                    crawl_run=runs[-1],
                    change="new",
                    title=job.title,
                    location=job.location,
                    seen_at=job.first_seen,
                )
            )

        def app(job: Job, status: str, days: int, **kw) -> Application:
            started = now - timedelta(days=days, hours=2)
            a = Application(
                job=job,
                status=status,
                mode=kw.pop("mode", "review"),
                started_at=started,
                finished_at=started + timedelta(minutes=4),
                submitted_at=started + timedelta(minutes=4)
                if status in ("submitted", "interview", "offer", "rejected")
                else None,
                stage_changed_at=started + timedelta(days=2),
                artifacts_dir="",
                **kw,
            )
            s.add(a)
            return a

        sent = [jobs[i] for i in (10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21)]
        stages = [
            "submitted",
            "submitted",
            "submitted",
            "interview",
            "interview",
            "offer",
            "rejected",
            "rejected",
            "submitted",
            "submitted",
            "rejected",
            "submitted",
        ]
        for i, (job, status) in enumerate(zip(sent, stages, strict=True)):
            a = app(
                job,
                status,
                days=3 + i * 6,
                confirmation="Thank you for applying! We have received your application.",
                follow_up_at=now - timedelta(days=1)
                if i in (0, 8)
                else (now + timedelta(days=4) if status == "submitted" else None),
                notes="Gespräch mit Lea (Engineering Manager) am Dienstag" if status == "interview" else "",
                filled=[
                    {
                        "label": "First Name",
                        "value": "Max",
                        "ok": True,
                        "source": "profile",
                        "confidence": "high",
                    },
                    {
                        "label": "Email",
                        "value": "max.mustermann@example.com",
                        "ok": True,
                        "source": "profile",
                        "confidence": "high",
                    },
                    {
                        "label": "Résumé",
                        "value": "Max_Mustermann_CV.pdf",
                        "ok": True,
                        "source": "profile",
                        "confidence": "high",
                    },
                ],
            )
            s.flush()
            for kind, msg in (
                ("navigate", job.url),
                ("plan", "[application_form → click_submit] Formular vollständig ausgefüllt"),
                ("submit", "Klick auf Absenden"),
                ("status", "submitted: Bestätigung erkannt"),
            ):
                s.add(ApplicationEvent(application=a, kind=kind, message=msg, ts=a.started_at))
            if i == 9:  # Antwort aus dem Postfach, die unter „Heute“ auf Bestätigung wartet
                s.add(
                    InboxMessage(
                        message_id=f"<demo-{a.id}@example.com>",
                        received_at=now - timedelta(hours=3),
                        sender=f"Recruiting <jobs@{job.company.split()[0].lower()}.example>",
                        subject=f"Ihre Bewerbung als {job.title}",
                        kind="rejection",
                        summary="Leider haben wir uns für andere Kandidatinnen und Kandidaten entschieden.",
                        application=a,
                    )
                )
        failed = app(jobs[22], "failed", 1, error="TimeoutError: Seite hat nicht geantwortet", mode="auto")
        review = app(jobs[23], "running", 0, mode="review")
        question = app(jobs[24], "running", 0, mode="review")
        s.flush()
        s.add(
            ApplicationEvent(
                application=failed, kind="error", message="TimeoutError: Seite hat nicht geantwortet"
            )
        )
        s.add(
            Prompt(
                application_id=review.id,
                kind="confirm",
                payload={
                    "title": f"{jobs[23].company} – {jobs[23].title}",
                    "rows": [
                        {"label": "First Name *", "value": "Max", "source": "profile", "confidence": "high"},
                        {
                            "label": "Last Name *",
                            "value": "Mustermann",
                            "source": "profile",
                            "confidence": "high",
                        },
                        {
                            "label": "Email *",
                            "value": "max.mustermann@example.com",
                            "source": "profile",
                            "confidence": "high",
                        },
                        {
                            "label": "Resume/CV *",
                            "value": "Max_Mustermann_CV.pdf",
                            "source": "profile",
                            "confidence": "high",
                        },
                        {
                            "label": "Salary expectations *",
                            "value": "72000",
                            "source": "profile",
                            "confidence": "high",
                        },
                        {
                            "label": "Why are you interested in us?",
                            "value": "Ihr Plattform-Team betreibt Kubernetes in großem Maßstab – genau dort habe ich die letzten Jahre gearbeitet …",
                            "source": "job_tailored",
                            "confidence": "medium",
                        },
                        {
                            "label": "Earliest start date",
                            "value": "01.03.2027",
                            "source": "profile",
                            "confidence": "low",
                        },
                    ],
                    "screenshot": "",
                },
            )
        )
        s.add(
            Prompt(
                application_id=question.id,
                kind="questions",
                payload={
                    "title": f"{jobs[24].company} – {jobs[24].title}",
                    "questions": [
                        {
                            "field_id": "0-12",
                            "question": "Bist du bereit, an Rufbereitschaft teilzunehmen?",
                            "why": "Pflichtfeld, nicht im Profil",
                            "options": ["Ja", "Nein"],
                        },
                        {
                            "field_id": "0-14",
                            "question": "Wie viele Jahre Erfahrung hast du mit Terraform?",
                            "why": "Pflichtfeld, nicht im Profil",
                            "options": [],
                        },
                    ],
                },
            )
        )
        for q, a in (
            (
                "Warum möchtest du wechseln?",
                "Ich suche mehr Verantwortung für die Plattform und ein Team mit starker SRE-Kultur.",
            ),
            ("Kündigungsfrist", "3 Monate zum Monatsende"),
            ("Hast du eine Arbeitserlaubnis in der EU?", "Ja"),
        ):
            s.add(Answer(question_key=q.lower(), question=q, answer=a))
        # Wie im echten Betrieb: Klartext plus Code/Parameter, die das Dashboard übersetzt
        entries = [
            activity(
                "crawl", "Crawl #6: 18 neue Stellen, 5 eingereiht", code="crawl.done", run=6, new=18, queued=5
            ),
            activity(
                "run",
                "Bewerbungslauf beendet: 3× submitted, 1× needs_input",
                code="run.finished",
                counts={"submitted": 3, "needs_input": 1},
            ),
            activity(
                "status",
                "Spreebyte · Platform Engineer – Kubernetes: interview",
                code="status.changed",
                company="Spreebyte",
                title="Platform Engineer – Kubernetes",
                status="interview",
            ),
            activity(
                "autopilot",
                "Autopilot: 18 neue Stellen, 5 eingereiht",
                code="autopilot.done",
                new=18,
                queued=5,
            ),
            activity("setup", "Einrichtung abgeschlossen", code="setup.done"),
        ]
        for i, entry in enumerate(entries):
            entry.ts = now - timedelta(hours=3 + i * 9)
            s.add(entry)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=ROOT / ".demo-home")
    args = parser.parse_args()
    build(args.home.resolve())
    print(f"Demo-Daten in {args.home.resolve()} – starten mit: JOBSLOP_HOME={args.home} uv run jobslop")


if __name__ == "__main__":
    main()

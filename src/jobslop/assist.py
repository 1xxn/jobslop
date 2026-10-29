"""Browser-Erweiterung („jobslop Assistent“): Formulare in deinem eigenen Chrome ausfüllen.

Dein normaler Browser ist kein ferngesteuerter Browser – Bot-Abfragen wie Cloudflare und Logins verhalten sich wie
bei dir selbst. Die Erweiterung liest das Formular mit demselben ``extract.js`` wie die Engine, jobslop plant die
Werte (Claude oder Regel-Planer, Profil, Antwortbank) und die Erweiterung trägt sie ein. Abgeschickt wird erst,
wenn du in der Erweiterung auf „Absenden“ klickst; CAPTCHAs löst du selbst.

LinkedIn und Indeed bedient die Erweiterung nur, wenn du es in den Einstellungen erlaubst – die Portale untersagen
Automatisierung in ihren Nutzungsbedingungen – und höchstens ``extension_portal_daily_limit`` Bewerbungen am Tag.
"""

from __future__ import annotations

import json
import re
import secrets
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from . import __version__
from .apply.coverletter import headless_pdf_context
from .apply.engine import (
    artifacts_dir,
    ensure_cover_letter,
    log_event,
    remember_answer,
    wants_cover_letter,
)
from .apply.executor import Files, chosen_options, select_index, text_value
from .apply.extract import CAPTCHA_HOST_HINTS, PageState, state_from_frames
from .apply.planner import (
    _CONFIRM_RX,
    FieldAction,
    JobContext,
    PlanInput,
    confirmation_excerpt,
    guard_submit_clicks,
)
from .apply.tailor import cached_cv, ensure_tailored_cv, wants_cv
from .config import SearchConfig, Settings, ensure_not_demo
from .db import Application, ApplicationEvent, Job, session_scope, utcnow
from .guard import already_applied
from .hosts import host_of, is_handoff
from .jobpage import FetchedJob, add_fetched_job, company_from_url, parse_html
from .llm import LLM, LLMLimitReached
from .netguard import BlockedTarget, ensure_public_target
from .profile import normalize_question
from .runtime import Runtime

TOKEN_FILE = "extension-token"  # noqa: S105 – Dateiname, nicht das Token
MAX_STEPS = 30  # Sicherheitsnetz gegen Endlosschleifen pro Bewerbung


# --------------------------------------------------------------------------- Kopplung & Installation


def token(settings: Settings) -> str:
    """Geheimnis, mit dem sich die Erweiterung ausweist (die API liefert Profildaten)."""
    path = settings.home / TOKEN_FILE
    if path.is_file() and (value := path.read_text(encoding="utf-8").strip()):
        return value
    settings.home.mkdir(parents=True, exist_ok=True)
    value = secrets.token_urlsafe(24)
    path.write_text(value, encoding="utf-8")
    return value


def token_ok(settings: Settings, value: str) -> bool:
    return bool(value) and secrets.compare_digest(value, token(settings))


def extension_dir(settings: Settings) -> Path:
    return settings.home / "extension"


def install(settings: Settings, server: str = "") -> Path:
    """Schreibt die Erweiterung nach ``~/.jobslop/extension`` – samt Server-Adresse und Kopplungs-Token.

    ``server`` ist die Adresse, unter der das Dashboard gerade läuft (``jobslop start --port`` weicht ab).
    """
    dest = extension_dir(settings)
    dest.mkdir(parents=True, exist_ok=True)
    for item in resources.files("jobslop").joinpath("extension").iterdir():
        if item.is_file() and item.name != "manifest.json":
            (dest / item.name).write_bytes(item.read_bytes())
    manifest = json.loads(
        resources.files("jobslop").joinpath("extension", "manifest.json").read_text("utf-8")
    )
    manifest["version"] = re.sub(r"[^0-9.]", "", __version__) or "1.0.0"
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    extract = resources.files("jobslop.apply").joinpath("extract.js").read_text("utf-8").strip()
    (dest / "extract.js").write_text(
        "// Aus jobslop/apply/extract.js – dieselbe Formularerkennung wie die Engine. Wird von jobslop erzeugt.\n"
        f"self.jobslopExtract = {extract};\n",
        encoding="utf-8",
    )
    config = {
        "server": server.rstrip("/") or f"http://{settings.dashboard_host}:{settings.dashboard_port}",
        "token": token(settings),
        "version": __version__,
        # CAPTCHA-Frames liest und bedient die Erweiterung nie – dieselbe Liste wie die Engine
        "captchaHosts": list(CAPTCHA_HOST_HINTS),
    }
    (dest / "config.js").write_text(
        f"// Von jobslop erzeugt – nicht weitergeben (enthält den Kopplungs-Token).\nself.JOBSLOP_CONFIG = {json.dumps(config)};\n",
        encoding="utf-8",
    )
    return dest


def installed_version(settings: Settings) -> str:
    path = extension_dir(settings) / "config.js"
    if not path.is_file():
        return ""
    m = re.search(r'"version":\s*"([^"]+)"', path.read_text(encoding="utf-8"))
    return m.group(1) if m else ""


def status(settings: Settings) -> dict[str, Any]:
    return {
        "version": __version__,
        "portals": settings.extension_portals,
        "portal_limit": settings.extension_portal_daily_limit,
        "portal_used": portal_submissions_today(settings),
        "demo": settings.demo,
    }


# --------------------------------------------------------------------------- Anfragen der Erweiterung


# Alles, was die Erweiterung schickt, stammt zum Teil von der fremden Seite: Form und Größe werden geprüft, bevor
# etwas davon in Planer, Datenbank oder Antwortbank geht.
class FrameData(BaseModel):
    """Ergebnis von extract.js für einen Frame (extract.js kürzt selbst; hier die harte Grenze)."""

    url: str = Field(max_length=4_000)
    title: str = Field(default="", max_length=2_000)
    text: str = Field(default="", max_length=20_000)
    headings: list[str] = Field(default_factory=list, max_length=50)
    fields: list[dict[str, Any]] = Field(default_factory=list, max_length=500)
    buttons: list[dict[str, Any]] = Field(default_factory=list, max_length=300)
    errors: list[str] = Field(default_factory=list, max_length=100)
    captcha: list[dict[str, Any]] = Field(default_factory=list, max_length=50)


class FrameIn(BaseModel):
    index: int = Field(ge=0, le=100_000)
    data: FrameData


class StepIn(BaseModel):
    frames: list[FrameIn] = Field(max_length=100)
    application_id: int | None = None
    history: list[str] = Field(default_factory=list, max_length=200)
    submit_clicked: bool = False
    step: int = Field(default=1, ge=1, le=1_000)
    # JSON-LD der Seite (Titel/Firma neuer Stellen)
    ld_json: list[str] = Field(default_factory=list, max_length=5)


class ResultIn(BaseModel):
    application_id: int
    step: int = Field(ge=0, le=1_000)
    summary: str = Field(default="", max_length=5_000)
    results: list[dict[str, Any]] = Field(default_factory=list, max_length=500)


class AnswerItem(BaseModel):
    question: str = Field(max_length=500)
    answer: str = Field(max_length=5_000)


class AnswersIn(BaseModel):
    application_id: int
    answers: list[AnswerItem] = Field(max_length=50)


class FinishIn(BaseModel):
    application_id: int
    status: Literal["submitted", "aborted"]
    url: str = Field(default="", max_length=4_000)
    message: str = Field(default="", max_length=5_000)


# --------------------------------------------------------------------------- Stellen & Bewerbungen


def _norm_url(url: str) -> str:
    u = urlparse(url)
    return f"{(u.hostname or '').lower()}{u.path.rstrip('/')}"


def find_job(session: Any, url: str) -> Job | None:
    """Die Stelle zur Seite: exakte URL, LinkedIn-/Indeed-ID oder gleiche Adresse ohne Parameter."""
    exact = session.execute(select(Job).where(or_(Job.url == url, Job.apply_url == url))).scalars().first()
    if exact:
        return exact
    if m := re.search(r"linkedin\.com/jobs/(?:view/(\d+)|.*[?&]currentJobId=(\d+))", url):
        job_id = m.group(1) or m.group(2)
        hit = session.execute(select(Job).where(Job.url.like(f"%linkedin.com/jobs/view/{job_id}%"))).scalars()
        if job := hit.first():
            return job
    jk = parse_qs(urlparse(url).query).get("jk") if "indeed." in host_of(url) else None
    if jk and (job := session.execute(select(Job).where(Job.url.like(f"%jk={jk[0]}%"))).scalars().first()):
        return job
    norm = _norm_url(url)
    if len(norm) > 12:
        rows = session.execute(
            select(Job.id, Job.url, Job.apply_url).where(Job.url.like(f"%{urlparse(url).hostname}%"))
        )
        for job_id, job_url, apply_url in rows:
            if norm in (_norm_url(job_url), _norm_url(apply_url)):
                return session.get(Job, job_id)
    return None


def _fetched_from_page(state: PageState, ld_json: list[str]) -> FetchedJob:
    """Stelle aus der offenen Seite: JSON-LD, sonst Überschrift/Titel und Seitentext."""
    html = "".join(f'<script type="application/ld+json">{x}</script>' for x in ld_json)
    fetched = parse_html(state.url, html) if html else FetchedJob(url=state.url)
    fetched.company = fetched.company or company_from_url(state.url)
    fetched.title = fetched.title or (state.headings[0] if state.headings else state.title) or "Stelle"
    fetched.description = fetched.description or state.text[:20000]
    return fetched


def _open_application(
    settings: Settings, config: SearchConfig, state: PageState, body: StepIn
) -> tuple[int, JobContext, Path, str]:
    """Laufende Bewerbung fortsetzen oder neu anlegen. Rückgabe: (ID, Stelle, Artefakt-Ordner, Sperrgrund)."""
    with session_scope(settings.db_path) as s:
        app = s.get(Application, body.application_id) if body.application_id else None
        if app is not None and app.status == "running":
            return app.id, JobContext.from_job(app.job), Path(app.artifacts_dir), ""
        job = find_job(s, state.url)
        job_id = job.id if job else None
    if job_id is None:  # unbekannte Seite: wie „Per Link“ anlegen – mit Einordnung und Score
        job_id, _ = add_fetched_job(
            settings.db_path, config, _fetched_from_page(state, body.ld_json), source="extension"
        )
    with session_scope(settings.db_path) as s:
        job = s.get(Job, job_id)
        if job is None:
            raise RuntimeError(f"Stelle {job_id} fehlt in der Datenbank")
        if done := already_applied(s, job):
            return 0, JobContext.from_job(job), Path(), done.reason
        app = next(
            (a for a in job.applications if a.origin == "extension" and a.status == "running"), None
        ) or Application(job=job, origin="extension", mode="review", status="running")
        s.add(app)
        s.flush()
        if not app.artifacts_dir:
            app.artifacts_dir = str(artifacts_dir(settings, app.id, job))
        job.queued = False
        return app.id, JobContext.from_job(job), Path(app.artifacts_dir), ""


def portal_submissions_today(settings: Settings) -> int:
    """Heute über die Erweiterung auf LinkedIn/Indeed abgeschickte Bewerbungen (Tageslimit)."""
    midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    since = midnight.astimezone(UTC).replace(tzinfo=None)
    with session_scope(settings.db_path) as s:
        rows = s.execute(
            select(Application.final_url).where(
                Application.origin == "extension", Application.submitted_at >= since
            )
        ).scalars()
        return sum(1 for url in rows if is_handoff(url or ""))


# --------------------------------------------------------------------------- Dateien & Anschreiben


def files_for(rt: Runtime, artdir: Path, job_id: int | None = None) -> Files:
    """Dateien aus dem Profil plus ein in einem früheren Schritt erzeugtes Anschreiben und der Lebenslauf für die
    Stelle (jeder Schritt ist eine eigene Anfrage – die Engine hält das im Speicher)."""
    files = Files.from_profile(rt.profile, rt.settings.profile_path.parent)
    if rt.profile.documents.tailor_cv and job_id and (cached := cached_cv(rt.settings.home, job_id)):
        files.cv = files.cv_en = cached[0]
    if artdir.is_dir() and (pdfs := sorted(artdir.glob("Anschreiben_*.pdf"))):
        files.cover_letter_pdf = pdfs[-1]
    if (letter := artdir / "anschreiben.txt").is_file():
        files.cover_letter_text = letter.read_text(encoding="utf-8")
    return files


# --------------------------------------------------------------------------- Plan → Anweisungen für den Browser


def compile_action(state: PageState, a: FieldAction, files: Files) -> dict[str, Any]:
    """Übersetzt eine geplante Aktion in eine konkrete Anweisung (Option, Datei, Format schon aufgelöst)."""
    f = state.field(a.field_id)
    button = state.button(a.field_id)
    op: dict[str, Any] = {
        "field_id": a.field_id,
        "action": a.action,
        "label": (f or {}).get("label") or (button or {}).get("text", ""),
        "value": a.value,
        "source": a.source,
        "confidence": a.confidence,
    }

    def fail(detail: str) -> dict[str, Any]:
        return op | {"op": "error", "detail": detail}

    if a.action == "click":
        return op | {"op": "click"}
    if a.action == "upload":
        paths = [p for p in files.resolve_upload(a.value) if p and p.exists()]
        if not paths:
            return fail(f"Keine Datei für {a.value} vorhanden")
        return op | {"op": "upload", "names": [p.name for p in paths]}
    if f is None:
        return fail(f"Unbekannte Feld-ID {a.field_id}")
    # Dieselben Regeln wie apply/executor.py – nur dass hier der Browser des Nutzers ausführt
    try:
        kind, value = f["kind"], files.fill_value(a.action, a.value)
        if kind in ("radio", "checkbox_group"):
            chosen = chosen_options(f, value)
            if any("id" not in o for o in chosen):
                return fail(f"Option '{value}' nicht gefunden")
            return op | {
                "op": "check",
                "ids": [o["id"] for o in chosen],
                "checked": a.action != "uncheck",
                "value": ", ".join(o["label"] for o in chosen),
            }
        if kind in ("checkbox", "aria_checkbox", "aria_radio"):
            return op | {"op": "check", "ids": [a.field_id], "checked": a.action != "uncheck"}
        if kind == "select":
            opt = f["options"][select_index(f, value)]
            return op | {"op": "select", "option_value": opt.get("value", ""), "option_label": opt["label"]}
        if kind in ("combobox", "richtext"):
            return op | {"op": kind, "value": value}
        if kind in ("text", "textarea", "date"):
            return op | {"op": "fill", "value": text_value(f, value)}
    except RuntimeError as exc:
        return fail(str(exc))
    return fail(f"Feldtyp {kind or '?'} nicht unterstützt")


async def step(rt: Runtime, body: StepIn, llm: LLM | None = None) -> dict[str, Any]:
    """Ein Schritt: Seite lesen → planen → Anweisungen. Abgeschickt wird nie hier, sondern nach deinem Klick."""
    settings = rt.settings
    ensure_not_demo(settings, "Bewerben")
    state = state_from_frames({f.index: f.data.model_dump() for f in body.frames})
    if not state.url:
        return {"blocked": "Die Seite ließ sich nicht lesen – neu laden und noch einmal versuchen."}
    try:
        await ensure_public_target(state.url, settings)
    except BlockedTarget as exc:
        return {"blocked": str(exc)}
    if is_handoff(state.url):
        if not settings.extension_portals:
            return {
                "blocked": "LinkedIn/Indeed füllt die Erweiterung nur aus, wenn du es in jobslop erlaubst "
                "(Einstellungen → Bewerben → Browser-Erweiterung). Die Portale untersagen Automatisierung."
            }
        used = portal_submissions_today(settings)
        if used >= settings.extension_portal_daily_limit:
            return {
                "blocked": f"Tageslimit für LinkedIn/Indeed erreicht ({used}/{settings.extension_portal_daily_limit})."
            }
    app_id, job, artdir, reason = _open_application(settings, rt.config, state, body)
    if reason:
        return {"blocked": reason}
    base = {"application_id": app_id, "job": {"id": job.id, "company": job.company, "title": job.title}}
    if body.step > MAX_STEPS:
        return base | {"blocked": f"Mehr als {MAX_STEPS} Schritte – bitte im Formular selbst prüfen."}
    if body.submit_clicked and _CONFIRM_RX.search(state.text):
        excerpt = confirmation_excerpt(state.text)
        finish(settings, FinishIn(application_id=app_id, status="submitted", url=state.url, message=excerpt))
        return base | {"confirmed": True, "message": excerpt}
    if state.captcha_visible:
        return base | {"wait": "Bitte löse die Sicherheitsabfrage selbst – danach auf „Weiter“."}

    planner = rt.planner(llm)
    with session_scope(settings.db_path) as s:
        app = s.get(Application, app_id)
        filled = list(app.filled) if app else []
    try:
        plan = await planner.plan(
            PlanInput(
                job=job,
                state=state,
                step=body.step,
                history=body.history,
                failures=[],
                submit_clicked=body.submit_clicked,
                screenshots=[],
            )
        )
    except LLMLimitReached as exc:
        return base | {"blocked": f"Claude-Limit erreicht – später weitermachen. ({str(exc)[:160]})"}
    notes = guard_submit_clicks(state, plan, filled)
    files = files_for(rt, artdir, job.id)
    if wants_cv(plan.actions):
        _pdf, note = await ensure_tailored_cv(
            llm,
            rt.profile,
            job,
            settings.home,
            settings.profile_path.parent,
            files,
            headless_pdf_context,
        )
        if note:
            notes.append(note)
    if wants_cover_letter(plan, rt.profile, state):
        _created, problem = await ensure_cover_letter(
            llm,
            rt.profile,
            job,
            artdir,
            files,
            headless_pdf_context,
            cv_file=getattr(planner, "cv_file", None),
        )
        if problem:
            notes.append(problem)
    ops = [compile_action(state, a, files) for a in plan.actions if a.action != "skip"]
    questions = [
        q.model_dump() | {"label": (state.field(q.field_id) or {}).get("label", "")} for q in plan.open_questions
    ]
    log_event(
        settings.db_path,
        app_id,
        "plan",
        f"[Erweiterung · {plan.page_kind} → {plan.next_step}] {plan.summary}",
        {
            "actions": len(ops),
            "questions": len(questions),
            "url": state.url,
            # Nur auf diese Fragen nimmt save_answers Antworten an
            "asked": [q["label"] or q["question"] for q in questions],
        },
    )
    review = None
    if plan.next_step == "click_submit":
        review = {
            "rows": [*[r for r in filled if r.get("ok")], *[o for o in ops if o["op"] != "error"]][-40:],
            "missing": [f.get("label", "") for f in state.missing_required()],
        }
    return base | {
        "plan": {
            "page_kind": plan.page_kind,
            "summary": plan.summary,
            "next_step": plan.next_step,
            "next_target_id": plan.next_target_id,
            "questions": questions,
        },
        "ops": ops,
        "notes": notes,
        "review": review,
    }


def record_results(settings: Settings, body: ResultIn) -> None:
    with session_scope(settings.db_path) as s:
        app = s.get(Application, body.application_id)
        if app is None:
            return
        rows = [
            {
                "step": body.step,
                "field_id": r.get("field_id", ""),
                "label": r.get("label", ""),
                "action": r.get("action", ""),
                "value": r.get("value", "")
                if not str(r.get("value", "")).startswith("@cover_letter")
                else "(Anschreiben)",
                "ok": bool(r.get("ok")),
                "detail": str(r.get("detail", ""))[:300],
                "source": r.get("source", ""),
                "confidence": r.get("confidence", ""),
            }
            for r in body.results
        ]
        app.filled = [*app.filled, *rows]
        ok = sum(r["ok"] for r in rows)
        s.add(
            ApplicationEvent(
                application_id=app.id,
                kind="fill",
                message=f"{ok}/{len(rows)} Aktionen ok (Erweiterung)",
                data={"failures": [f"{r['label']}: {r['detail']}" for r in rows if not r["ok"]]},
            )
        )


def save_answers(settings: Settings, body: AnswersIn) -> int:
    """Antworten aus dem Panel in die Antwortbank – nur für Fragen, die jobslop im letzten Schritt dieser laufenden
    Bewerbung gestellt hat. Die Antwortbank füllt jede künftige Bewerbung; eine Seite darf dort nichts unterbringen."""
    with session_scope(settings.db_path) as s:
        app = s.get(Application, body.application_id)
        if app is None or app.origin != "extension" or app.status != "running":
            return 0
        last_plan = s.scalars(
            select(ApplicationEvent)
            .where(ApplicationEvent.application_id == app.id, ApplicationEvent.kind == "plan")
            .order_by(ApplicationEvent.id.desc())
            .limit(1)
        ).first()
        asked = {normalize_question(q) for q in ((last_plan.data or {}).get("asked") or [])} if last_plan else set()
        saved = 0
        for item in body.answers:
            question, answer = item.question.strip(), item.answer.strip()
            if question and answer and normalize_question(question) in asked:
                remember_answer(s, question, answer)
                saved += 1
        s.add(
            ApplicationEvent(
                application_id=body.application_id, kind="answers", message=f"{saved} Antworten gespeichert"
            )
        )
    return saved


def finish(settings: Settings, body: FinishIn) -> None:
    with session_scope(settings.db_path) as s:
        app = s.get(Application, body.application_id)
        if app is None or app.status != "running":
            return
        app.finished_at = utcnow()
        app.final_url = body.url or app.final_url
        if body.status == "submitted":
            app.status, app.submitted_at, app.confirmation = "submitted", utcnow(), body.message[:2000]
        else:
            app.status, app.confirmation = "skipped", body.message[:2000] or "In der Erweiterung abgebrochen"
        s.add(
            ApplicationEvent(
                application_id=app.id, kind="status", message=f"{app.status}: {app.confirmation}"
            )
        )


def upload_file(rt: Runtime, application_id: int, value: str, index: int) -> Path | None:
    """Datei für eine Upload-Anweisung (nur Platzhalter wie @cv – nie beliebige Pfade)."""
    with session_scope(rt.settings.db_path) as s:
        app = s.get(Application, application_id)
        if app is None:
            return None
        artdir, job_id = Path(app.artifacts_dir), app.job_id
    paths = [p for p in files_for(rt, artdir, job_id).resolve_upload(value) if p and p.exists()]
    return paths[index] if 0 <= index < len(paths) else None

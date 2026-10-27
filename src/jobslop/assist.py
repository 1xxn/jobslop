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
from .apply.coverletter import cover_letter_html, cover_letter_text, render_pdf, write_cover_letter
from .apply.engine import remember_answer, slugify
from .apply.executor import Files, best_option, to_iso_date
from .apply.extract import PageState, state_from_frames
from .apply.planner import _CONFIRM_RX, FieldAction, JobContext, PlanInput, guard_submit_clicks
from .classify import fingerprint, match_key
from .config import Settings, ensure_not_demo
from .db import Application, ApplicationEvent, Job, session_scope, utcnow
from .guard import already_applied
from .hosts import host_of, is_handoff
from .jobpage import parse_html
from .llm import LLMLimitReached
from .runtime import Runtime

TOKEN_FILE = "extension-token"
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
    host = settings.dashboard_host if settings.dashboard_host not in ("0.0.0.0", "::") else "127.0.0.1"
    config = {
        "server": server.rstrip("/") or f"http://{host}:{settings.dashboard_port}",
        "token": token(settings),
        "version": __version__,
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


class FrameIn(BaseModel):
    index: int
    data: dict[str, Any]


class StepIn(BaseModel):
    frames: list[FrameIn]
    application_id: int | None = None
    history: list[str] = Field(default_factory=list)
    submit_clicked: bool = False
    step: int = 1
    ld_json: list[str] = Field(default_factory=list)  # JSON-LD der Seite (Titel/Firma neuer Stellen)


class ResultIn(BaseModel):
    application_id: int
    step: int
    summary: str = ""
    results: list[dict[str, Any]] = Field(default_factory=list)


class AnswersIn(BaseModel):
    application_id: int
    answers: list[dict[str, str]]  # {"question": …, "answer": …}


class FinishIn(BaseModel):
    application_id: int
    status: Literal["submitted", "aborted"]
    url: str = ""
    message: str = ""


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
        for job in session.execute(select(Job).where(Job.url.like(f"%{urlparse(url).hostname}%"))).scalars():
            if norm in (_norm_url(job.url), _norm_url(job.apply_url)):
                return job
    return None


def _new_job(state: PageState, ld_json: list[str]) -> Job:
    html = "".join(f'<script type="application/ld+json">{x}</script>' for x in ld_json)
    fetched = parse_html(state.url, html) if html else None
    host = host_of(state.url).removeprefix("www.")
    company = (fetched.company if fetched else "") or host.split(".")[-2].title() if "." in host else host
    title = (
        (fetched.title if fetched else "")
        or (state.headings[0] if state.headings else state.title)
        or "Stelle"
    )
    return Job(
        fingerprint=fingerprint("extension", _norm_url(state.url)),
        match_key=match_key(company, title),
        source="extension",
        origin="manual",
        company=company[:200],
        title=title[:400],
        url=state.url,
        location=(fetched.location if fetched else "")[:400],
        description=(fetched.description if fetched else "") or state.text[:20000],
    )


def _context(job: Job) -> JobContext:
    return JobContext(
        id=job.id,
        company=job.company,
        title=job.title,
        location=job.location,
        url=job.target_url,
        description=job.description or job.notes,
        language=job.language,
    )


def _open_application(
    settings: Settings, state: PageState, body: StepIn
) -> tuple[int, JobContext, Path, str]:
    """Laufende Bewerbung fortsetzen oder neu anlegen. Rückgabe: (ID, Stelle, Artefakt-Ordner, Sperrgrund)."""
    with session_scope(settings.db_path) as s:
        app = s.get(Application, body.application_id) if body.application_id else None
        if app is None or app.status != "running":
            job = find_job(s, state.url)
            if job is None:
                job = _new_job(state, body.ld_json)
                s.add(job)
                s.flush()
            if reason := already_applied(s, job):
                return 0, _context(job), Path(), reason
            app = next(
                (a for a in job.applications if a.origin == "extension" and a.status == "running"), None
            ) or Application(job=job, origin="extension", mode="review", status="running")
            s.add(app)
            s.flush()
            if not app.artifacts_dir:
                artdir = settings.artifacts_dir / f"{app.id:04d}-{slugify(job.company)}-{slugify(job.title)}"
                artdir.mkdir(parents=True, exist_ok=True)
                app.artifacts_dir = str(artdir)
            job.queued = False
        return app.id, _context(app.job), Path(app.artifacts_dir), ""


def _event(
    settings: Settings, app_id: int, kind: str, message: str, data: dict[str, Any] | None = None
) -> None:
    with session_scope(settings.db_path) as s:
        s.add(ApplicationEvent(application_id=app_id, kind=kind, message=message[:2000], data=data or {}))


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


def files_for(rt: Runtime, artdir: Path) -> Files:
    profile, base = rt.profile, rt.settings.profile_path.parent
    files = Files(
        cv=profile.cv_path(base),
        cv_en=profile.documents.resolve(profile.documents.cv_en, base),
        certificates=[p for c in profile.documents.certificates if (p := profile.documents.resolve(c, base))],
    )
    custom = profile.documents.resolve(profile.documents.cover_letter, base)
    if custom and custom.exists():
        files.cover_letter_pdf = custom
    for pdf in sorted(artdir.glob("Anschreiben_*.pdf")) if artdir.is_dir() else []:
        files.cover_letter_pdf = pdf
    letter = artdir / "anschreiben.txt"
    if letter.is_file():
        files.cover_letter_text = letter.read_text(encoding="utf-8")
    return files


async def _ensure_cover_letter(rt: Runtime, llm: Any, job: JobContext, artdir: Path, files: Files) -> str:
    """Anschreiben erzeugen, wenn das Formular eins will. Rückgabe: Hinweis, falls es nicht geht."""
    profile = rt.profile
    if files.cover_letter_text or files.cover_letter_pdf or profile.documents.cover_letter != "auto":
        return ""
    if llm is None:
        return "Anschreiben verlangt, aber Claude ist nicht verbunden"
    letter = await write_cover_letter(
        llm, profile, job, profile.preferences.cover_letter_language, cv_file=files.cv
    )
    files.cover_letter_text = cover_letter_text(letter, profile)
    (artdir / "anschreiben.txt").write_text(files.cover_letter_text, encoding="utf-8")
    from playwright.async_api import async_playwright

    pdf = artdir / f"Anschreiben_{slugify(profile.personal.full_name)}_{slugify(job.company)}.pdf"
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            await render_pdf(await browser.new_context(), cover_letter_html(letter, profile, job), pdf)
        finally:
            await browser.close()
    files.cover_letter_pdf = pdf
    return ""


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
    kind, value = f["kind"], a.value
    if a.action == "fill" and value.strip().lower() == "@cover_letter":
        if not files.cover_letter_text:
            return fail("Kein Anschreiben-Text verfügbar")
        value = files.cover_letter_text
    if kind in ("radio", "checkbox_group"):
        options = f.get("options", [])
        ids, chosen = [], []
        for wanted in [v.strip() for v in re.split(r";|\n", value) if v.strip()] or [value]:
            idx, score = best_option([o["label"] for o in options], wanted)
            if idx < 0 or score < 0.5 or "id" not in options[idx]:
                return fail(f"Option '{wanted}' nicht gefunden")
            ids.append(options[idx]["id"])
            chosen.append(options[idx]["label"])
        return op | {"op": "check", "ids": ids, "checked": a.action != "uncheck", "value": ", ".join(chosen)}
    if kind in ("checkbox", "aria_checkbox", "aria_radio"):
        return op | {"op": "check", "ids": [a.field_id], "checked": a.action != "uncheck"}
    if kind == "select":
        options = f.get("options", [])
        idx, score = best_option([o["label"] for o in options], value)
        if idx < 0 or score < 0.55:
            idx, score = best_option([o.get("value", "") for o in options], value)
            if idx < 0 or score < 0.8:
                return fail(f"Option '{value}' nicht gefunden")
        opt = options[idx]
        return op | {"op": "select", "option_value": opt.get("value", ""), "option_label": opt["label"]}
    if kind == "combobox":
        return op | {"op": "combobox", "value": value}
    if kind == "richtext":
        return op | {"op": "richtext", "value": value}
    if kind in ("text", "textarea", "date"):
        if f.get("input_type") == "date" or kind == "date":
            value = to_iso_date(value)
        if f.get("max_length") and len(value) > f["max_length"]:
            value = value[: f["max_length"]]
        return op | {"op": "fill", "value": value}
    return fail(f"Feldtyp {kind or '?'} nicht unterstützt")


async def step(rt: Runtime, body: StepIn) -> dict[str, Any]:
    """Ein Schritt: Seite lesen → planen → Anweisungen. Abgeschickt wird nie hier, sondern nach deinem Klick."""
    settings = rt.settings
    ensure_not_demo(settings, "Bewerben")
    state = state_from_frames({f.index: f.data for f in body.frames})
    if not state.url:
        return {"blocked": "Die Seite ließ sich nicht lesen – neu laden und noch einmal versuchen."}
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
    app_id, job, artdir, reason = _open_application(settings, state, body)
    if reason:
        return {"blocked": reason}
    base = {"application_id": app_id, "job": {"id": job.id, "company": job.company, "title": job.title}}
    if body.step > MAX_STEPS:
        return base | {"blocked": f"Mehr als {MAX_STEPS} Schritte – bitte im Formular selbst prüfen."}
    if body.submit_clicked and (m := _CONFIRM_RX.search(state.text)):
        excerpt = re.sub(r"\s+", " ", state.text[m.start() : m.end() + 200]).strip()
        finish(settings, FinishIn(application_id=app_id, status="submitted", url=state.url, message=excerpt))
        return base | {"confirmed": True, "message": excerpt}
    if state.captcha_visible:
        return base | {"wait": "Bitte löse die Sicherheitsabfrage selbst – danach auf „Weiter“."}

    llm = rt.llm()
    planner = rt.planner(llm)
    with session_scope(settings.db_path) as s:
        app = s.get(Application, app_id)
        filled_before = any(r.get("ok") and r.get("action") != "click" for r in (app.filled if app else []))
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
    notes = guard_submit_clicks(state, plan, filled_before=filled_before)
    files = files_for(rt, artdir)
    wants_letter = any(
        a.value.strip().lower() in ("@cover_letter", "@cover_letter_pdf") for a in plan.actions
    )
    if wants_letter and rt.profile.documents.cover_letter == "none":
        for a in plan.actions:
            if a.value.strip().lower() in ("@cover_letter", "@cover_letter_pdf"):
                a.action = "skip"
    elif wants_letter and (hint := await _ensure_cover_letter(rt, llm, job, artdir, files)):
        notes.append(hint)
    ops = [compile_action(state, a, files) for a in plan.actions if a.action != "skip"]
    _event(
        settings,
        app_id,
        "plan",
        f"[Erweiterung · {plan.page_kind} → {plan.next_step}] {plan.summary}",
        {"actions": len(ops), "questions": len(plan.open_questions), "url": state.url},
    )
    review = None
    if plan.next_step == "click_submit":
        with session_scope(settings.db_path) as s:
            app = s.get(Application, app_id)
            rows = [r for r in (app.filled if app else []) if r.get("ok")]
        review = {
            "rows": [*rows, *[o for o in ops if o["op"] != "error"]][-40:],
            "missing": [f.get("label", "") for f in state.missing_required()],
        }
    return base | {
        "plan": {
            "page_kind": plan.page_kind,
            "summary": plan.summary,
            "next_step": plan.next_step,
            "next_target_id": plan.next_target_id,
            "questions": [
                q.model_dump() | {"label": (state.field(q.field_id) or {}).get("label", "")}
                for q in plan.open_questions
            ],
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
    with session_scope(settings.db_path) as s:
        saved = 0
        for item in body.answers:
            question, answer = item.get("question", "").strip(), item.get("answer", "").strip()
            if question and answer:
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
        artdir = Path(app.artifacts_dir)
    paths = [p for p in files_for(rt, artdir).resolve_upload(value) if p and p.exists()]
    return paths[index] if 0 <= index < len(paths) else None

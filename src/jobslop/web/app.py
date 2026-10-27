"""Dashboard-Server: JSON-API unter ``/api`` und die gebaute React-Oberfläche (``web/dist``).

Sicherheit: Der Server lauscht nur lokal. Zusätzlich werden fremde Host-Header abgewiesen (DNS-Rebinding)
und ändernde Anfragen brauchen den Header ``X-Jobslop: 1`` – den kann eine fremde Webseite ohne CORS-Freigabe
nicht setzen (CSRF-Schutz).
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import re
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select

from .. import __version__, assist
from ..autopilot import Scheduler, crawl_and_queue, next_run, record
from ..classify import SCORE_MAX, score_parts
from ..config import (
    EDITABLE_SETTINGS,
    DemoModeError,
    SearchConfig,
    Settings,
    ensure_not_demo,
    save_settings,
    search_config_from_preset,
)
from ..crawl.pipeline import BROWSER_ONLY_PENALTY
from ..db import (
    Activity,
    Answer,
    Application,
    ApplicationEvent,
    CrawlRun,
    Exclusion,
    Job,
    JobSnapshot,
    Prompt,
    session_scope,
    utcnow,
)
from ..guard import ACTIVE_STATES, DONE_STATES, check_job
from ..hosts import is_browser_only
from ..notify import notify
from ..presets import presets_for_ui
from ..profile import TODO, Profile, Work, normalize_question
from ..queueing import pick_top, queue_jobs
from ..runner import Runner
from ..runtime import Runtime
from ..system import BrowserInstaller, open_claude_install, open_claude_login, open_folder, system_report

log = logging.getLogger(__name__)

DIST = Path(__file__).parent / "dist"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "testserver"}
STAGES = {
    "applied": ("submitted", "manual"),
    "interview": ("interview",),
    "offer": ("offer",),
    "rejected": ("rejected",),
}
MARK = {"applied": "manual", "interview": "interview", "rejected": "rejected", "offer": "offer"}


# --------------------------------------------------------------------------- Serialisierung


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() + "Z" if d else None


def job_summary(j: Job) -> dict[str, Any]:
    last = j.applications[-1] if j.applications else None
    return {
        "id": j.id,
        "company": j.company,
        "title": j.title,
        "location": j.location,
        "where": j.where,
        "workplace": j.workplace,
        "category": j.category,
        "level": j.level,
        "fit": j.fit,
        "score": round(j.score, 1),
        "status": j.status,
        "queued": j.queued,
        "starred": j.starred,
        "source": j.source,
        "url": j.url,
        "posted": j.posted,
        "first_seen": _iso(j.first_seen),
        "enriched": bool(j.enrichment),
        "summary": (j.enrichment or {}).get("summary", ""),
        "app_status": last.status if last else ("queued" if j.queued else ""),
        "app_id": last.id if last else None,
    }


def app_summary(a: Application) -> dict[str, Any]:
    return {
        "id": a.id,
        "job_id": a.job_id,
        "company": a.job.company,
        "title": a.job.title,
        "job_url": a.job.url,
        "status": a.status,
        "mode": a.mode,
        "origin": a.origin,
        "started_at": _iso(a.started_at),
        "finished_at": _iso(a.finished_at),
        "submitted_at": _iso(a.submitted_at),
        "error": a.error,
        "confirmation": a.confirmation,
        "notes": a.notes,
        "follow_up_at": _iso(a.follow_up_at),
        "open_questions": len(a.open_questions or []),
    }


def prompt_json(p: Prompt) -> dict[str, Any]:
    return {
        "id": p.id,
        "kind": p.kind,
        "application_id": p.application_id,
        "payload": p.payload,
        "created_at": _iso(p.created_at),
    }


def profile_json(profile: Profile) -> dict[str, Any]:
    data = profile.model_dump(mode="json")
    data["work"] = {k: ("" if v == TODO else v) for k, v in data["work"].items()}
    return data


# --------------------------------------------------------------------------- Request-Modelle


class JobPatch(BaseModel):
    queued: bool | None = None
    starred: bool | None = None
    notes: str | None = None


class JobStatus(BaseModel):
    status: str
    note: str = ""


class BulkAction(BaseModel):
    ids: list[int]
    action: str  # queue | unqueue | star | unstar | exclude


class ApplyRequest(BaseModel):
    job_ids: list[int] = []
    mode: str | None = None
    max: int | None = None
    force: bool = False


class AppPatch(BaseModel):
    status: str | None = None
    notes: str | None = None
    follow_up_at: datetime | None = None
    clear_follow_up: bool = False


class PromptAnswer(BaseModel):
    answers: dict[str, str] = {}
    skip: bool = False
    decision: str = ""
    done: bool = False
    abort: bool = False


class AnswerIn(BaseModel):
    question: str
    answer: str


class ExclusionIn(BaseModel):
    kind: str
    value: str
    reason: str = ""


class PresetRequest(BaseModel):
    presets: list[str] = ["cloud"]
    cities: list[str] = ["berlin"]
    remote: bool = True
    exclude_leadership: bool = True


class UrlIn(BaseModel):
    url: str


class AppAnswers(BaseModel):
    answers: dict[str, str]
    requeue: bool = True


# --------------------------------------------------------------------------- App


class Context:
    """Geteilter Zustand des Servers. Profil und Suche werden bei jedem Zugriff frisch geladen."""

    def __init__(self, runtime: Runtime) -> None:
        self.settings: Settings = runtime.settings
        self._initial = runtime
        self.runner = Runner(self.settings)
        self.browser_installer = BrowserInstaller()
        self.crawl: dict[str, Any] = {"running": False, "last": None, "started_at": None}
        self.last_prompt_notified = 0
        self.scheduler = Scheduler(self.run_autopilot, lambda: self.settings)
        self.autopilot_running = False
        self.tasks: set[asyncio.Task[Any]] = set()
        self.crawl_idle = asyncio.Event()
        self.crawl_idle.set()

    @property
    def db(self) -> Path:
        return self.settings.db_path

    def runtime(self) -> Runtime:
        """Stand von der Platte; solange Profil/Suche noch nicht gespeichert sind, gilt der Startzustand."""
        rt = Runtime.load(self.settings)
        if not self.settings.profile_path.exists():
            rt.profile = self._initial.profile
        if not self.settings.search_path.exists():
            rt.config = self._initial.config
        return rt

    async def notify(self, title: str, message: str, url: str = "") -> None:
        try:
            await notify(self.settings, title, message, url=url)
        except Exception:
            log.exception("Benachrichtigung fehlgeschlagen")

    async def start_crawl(self, *, queue_count: int = 0) -> bool:
        if self.crawl["running"]:
            return False
        ensure_not_demo(self.settings, "Crawlen")
        self.crawl.update(running=True, started_at=_iso(utcnow()))
        self.crawl_idle.clear()

        async def job() -> None:
            try:
                summary = await crawl_and_queue(self.runtime(), queue_count=queue_count)
                self.crawl["last"] = summary
                if summary["new"]:
                    await self.notify(
                        "jobslop: neue Stellen", f"{summary['new']} neue passende Stellen gefunden"
                    )
            except Exception as exc:
                log.exception("Crawl fehlgeschlagen")
                self.crawl["last"] = {"error": str(exc)}
                record(
                    self.settings,
                    "crawl",
                    f"Crawl fehlgeschlagen: {exc}",
                    code="crawl.failed",
                    error=str(exc),
                )
            finally:
                self.crawl["running"] = False
                self.crawl_idle.set()

        self.spawn(job())
        return True

    def spawn(self, coro: Any) -> None:
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def run_autopilot(self) -> None:
        if self.autopilot_running:
            return
        self.autopilot_running = True
        s = self.settings
        record(s, "autopilot", "Autopilot gestartet", code="autopilot.started")
        try:
            await self.crawl_idle.wait()
            self.crawl.update(running=True, started_at=_iso(utcnow()))
            self.crawl_idle.clear()
            try:
                count = s.autopilot_apply_max if s.autopilot_apply else 0
                summary = await crawl_and_queue(self.runtime(), queue_count=count)
                self.crawl["last"] = summary
            finally:
                self.crawl["running"] = False
                self.crawl_idle.set()
            started = False
            if s.autopilot_apply and summary["queued"] and not self.runner.active:
                started = self.runner.start(
                    mode=s.autopilot_apply_mode, max_count=s.autopilot_apply_max, label="Autopilot"
                )
            text = f"{summary['new']} neue Stellen, {len(summary['queued'])} eingereiht" + (
                " – Bewerbungen laufen" if started else ""
            )
            record(
                s,
                "autopilot",
                f"Autopilot: {text}",
                summary,
                code="autopilot.done",
                new=summary["new"],
                queued=len(summary["queued"]),
                started=int(started),
            )
            await self.notify("jobslop Autopilot", text)
        finally:
            self.autopilot_running = False

    async def watch(self) -> None:
        """Hintergrund: Ende von Bewerbungsläufen und neue Rückfragen melden."""
        was_active = False
        with session_scope(self.db) as s:
            self.last_prompt_notified = s.scalar(select(func.max(Prompt.id))) or 0
        while True:
            try:
                active = self.runner.active
                if was_active and not active:
                    await self._run_finished()
                was_active = active
                with session_scope(self.db) as s:
                    new = list(
                        s.execute(
                            select(Prompt).where(
                                Prompt.status == "open", Prompt.id > self.last_prompt_notified
                            )
                        ).scalars()
                    )
                    for p in new:
                        self.last_prompt_notified = max(self.last_prompt_notified, p.id)
                        title = p.payload.get("title", "")
                        what = {"questions": "hat Rückfragen", "confirm": "wartet auf Freigabe"}.get(
                            p.kind, "braucht dich im Browser"
                        )
                        await self.notify("jobslop braucht dich", f"{title} {what}")
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Hintergrundprüfung fehlgeschlagen")
            await asyncio.sleep(3)

    async def _run_finished(self) -> None:
        since = self.runner.started_at or utcnow()
        with session_scope(self.db) as s:
            rows = (
                s.execute(select(Application.status).where(Application.started_at >= since)).scalars().all()
            )
        counts = Counter(rows)
        text = (
            ", ".join(f"{n}× {status}" for status, n in counts.most_common()) or "keine Bewerbung gestartet"
        )
        record(
            self.settings,
            "run",
            f"Bewerbungslauf beendet: {text}",
            dict(counts),
            code="run.finished",
            counts=dict(counts),
        )
        await self.notify("jobslop: Lauf beendet", text)


def create_app(runtime: Runtime) -> FastAPI:
    ctx = Context(runtime)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        watcher = asyncio.create_task(ctx.watch())
        ctx.scheduler.start()
        try:
            yield
        finally:
            watcher.cancel()
            await ctx.scheduler.stop()

    app = FastAPI(title="jobslop", version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.ctx = ctx

    @app.exception_handler(DemoModeError)
    async def demo_mode(_request: Request, exc: DemoModeError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].lower()
        if host not in LOCAL_HOSTS and host != ctx.settings.dashboard_host:
            return JSONResponse({"detail": "Nur lokal erreichbar"}, status_code=403)
        if (
            request.url.path.startswith("/api/")
            and request.method not in ("GET", "HEAD", "OPTIONS")
            and request.headers.get("x-jobslop") != "1"
        ):
            return JSONResponse({"detail": "Fehlender X-Jobslop-Header"}, status_code=403)
        return await call_next(request)

    # ------------------------------------------------------------------ Status & System
    @app.get("/api/status")
    def status() -> dict[str, Any]:
        s = ctx.settings
        with session_scope(ctx.db) as db:
            prompts = [
                prompt_json(p)
                for p in db.execute(
                    select(Prompt).where(Prompt.status == "open").order_by(Prompt.id)
                ).scalars()
            ]
            open_jobs = db.scalar(select(func.count(Job.id)).where(Job.status == "open")) or 0
            queued = db.scalar(select(func.count(Job.id)).where(Job.queued)) or 0
            attention = (
                db.scalar(
                    select(func.count(Application.id)).where(
                        Application.status.in_(["needs_input", "needs_review"])
                    )
                )
                or 0
            )
        runner = ctx.runner.state(lines=0)
        runner.pop("log", None)
        nxt = next_run(s)
        return {
            "version": __version__,
            "setup_completed": s.setup_completed,
            "demo": s.demo,
            "prompts": prompts,
            "runner": runner,
            "crawl": ctx.crawl,
            "autopilot": {
                "enabled": s.autopilot_enabled,
                "running": ctx.autopilot_running,
                "next_run": nxt.isoformat() if nxt else None,
            },
            "counts": {"open_jobs": open_jobs, "queued": queued, "attention": attention},
            "notify_desktop": s.notify_desktop,
        }

    @app.get("/api/system")
    async def system(refresh: bool = False) -> dict[str, Any]:
        rt = ctx.runtime()
        report = await system_report(ctx.settings, rt.profile, refresh=refresh)
        report["browser_install"] = ctx.browser_installer.state()
        report["version"] = __version__
        return report

    @app.post("/api/system/claude-login")
    def claude_login() -> dict[str, Any]:
        return open_claude_login(ctx.settings)

    @app.post("/api/system/claude-install")
    def claude_install() -> dict[str, Any]:
        return open_claude_install()

    @app.post("/api/system/browser-install")
    async def browser_install() -> dict[str, Any]:
        await ctx.browser_installer.start()
        return ctx.browser_installer.state()

    @app.post("/api/system/open-folder")
    def open_home() -> dict[str, Any]:
        return {"opened": open_folder(ctx.settings.home)}

    # ------------------------------------------------------------------ Browser-Erweiterung
    # Einrichten/Anzeigen gehört zum Dashboard; alles unter /api/assist/ ruft die Erweiterung mit ihrem Token auf.
    def assist_info() -> dict[str, Any]:
        installed = assist.installed_version(ctx.settings)
        return {
            "path": str(assist.extension_dir(ctx.settings)),
            "installed": bool(installed),
            "outdated": bool(installed) and installed != __version__,
            "version": __version__,
        } | assist.status(ctx.settings)

    @app.get("/api/extension")
    def extension_info() -> dict[str, Any]:
        return assist_info()

    @app.post("/api/extension/install")
    def extension_install(request: Request) -> dict[str, Any]:
        assist.install(ctx.settings, server=str(request.base_url))
        record(ctx.settings, "setup", "Browser-Erweiterung eingerichtet", code="extension.installed")
        return assist_info()

    @app.post("/api/extension/open-folder")
    def extension_open_folder() -> dict[str, Any]:
        path = assist.extension_dir(ctx.settings)
        return {"opened": path.is_dir() and open_folder(path)}

    def paired(request: Request) -> None:
        if not assist.token_ok(ctx.settings, request.headers.get("x-jobslop-token", "")):
            raise HTTPException(
                401, "Erweiterung nicht gekoppelt – in jobslop unter Einstellungen → Bewerben neu einrichten"
            )

    @app.get("/api/assist/status")
    def assist_status(request: Request) -> dict[str, Any]:
        paired(request)
        return assist.status(ctx.settings)

    @app.post("/api/assist/step")
    async def assist_step(request: Request, body: assist.StepIn) -> dict[str, Any]:
        paired(request)
        return await assist.step(ctx.runtime(), body)

    @app.post("/api/assist/result")
    def assist_result(request: Request, body: assist.ResultIn) -> dict[str, Any]:
        paired(request)
        assist.record_results(ctx.settings, body)
        return {"ok": True}

    @app.post("/api/assist/answers")
    def assist_answers(request: Request, body: assist.AnswersIn) -> dict[str, Any]:
        paired(request)
        return {"saved": assist.save_answers(ctx.settings, body)}

    @app.post("/api/assist/finish")
    async def assist_finish(request: Request, body: assist.FinishIn) -> dict[str, Any]:
        paired(request)
        assist.finish(ctx.settings, body)
        if body.status == "submitted":
            await ctx.notify(
                "jobslop: Bewerbung abgeschickt", body.message[:200] or "über die Browser-Erweiterung"
            )
        return {"ok": True}

    @app.get("/api/assist/file")
    def assist_file(request: Request, application_id: int, value: str, index: int = 0) -> FileResponse:
        paired(request)
        path = assist.upload_file(ctx.runtime(), application_id, value, index)
        if path is None:
            raise HTTPException(404, "Datei nicht gefunden")
        return FileResponse(path, filename=path.name)

    # ------------------------------------------------------------------ Profil & Dokumente
    @app.get("/api/profile")
    def get_profile() -> dict[str, Any]:
        rt = ctx.runtime()
        cv = rt.profile.cv_path(ctx.settings.profile_path.parent)
        cv_en = rt.profile.cv_path(ctx.settings.profile_path.parent, "en")
        return {
            "profile": profile_json(rt.profile),
            "missing": rt.profile.missing_fields(),
            "documents": {
                "cv": {"name": cv.name, "exists": cv.exists()} if cv else None,
                "cv_en": {"name": cv_en.name, "exists": cv_en.exists()}
                if cv_en and rt.profile.documents.cv_en
                else None,
            },
        }

    @app.put("/api/profile")
    def put_profile(body: dict[str, Any]) -> dict[str, Any]:
        try:
            profile = Profile.model_validate(body)
        except ValidationError as exc:
            raise HTTPException(422, exc.errors()) from exc
        for name, default in Work():
            if default == TODO and getattr(profile.work, name) in ("", None):
                setattr(profile.work, name, TODO)  # leer = unbekannt, der Agent fragt nach
        ctx.settings.home.mkdir(parents=True, exist_ok=True)
        profile.save(ctx.settings.profile_path)
        return get_profile()

    @app.post("/api/profile/document")
    async def upload_document(
        file: UploadFile = File(...),
        kind: str = Form("cv"),
        import_cv: bool = Form(False),
    ) -> dict[str, Any]:
        if kind not in ("cv", "cv_en", "certificate"):
            raise HTTPException(400, "Unbekannte Dokumentart")
        name = re.sub(r"[^\w.\- ]", "_", Path(file.filename or "dokument.pdf").name).strip() or "dokument.pdf"
        if not name.lower().endswith(".pdf"):
            raise HTTPException(400, "Bitte eine PDF-Datei hochladen")
        data = await file.read()
        if len(data) > 15 * 1024 * 1024:
            raise HTTPException(413, "Datei ist größer als 15 MB")
        ctx.settings.ensure_dirs()
        target = ctx.settings.documents_dir / name
        target.write_bytes(data)
        rt = ctx.runtime()
        profile = rt.profile
        rel = f"documents/{name}"
        if kind == "cv":
            profile.documents.cv = rel
        elif kind == "cv_en":
            profile.documents.cv_en = rel
        elif rel not in profile.documents.certificates:
            profile.documents.certificates.append(rel)
        message = ""
        if import_cv and kind == "cv":
            from ..cvimport import import_cv as run_import
            from ..system import claude_status

            login = await asyncio.to_thread(claude_status, ctx.settings)
            llm = rt.llm() if login.ok else None
            if llm is None:
                message = "Claude ist noch nicht verbunden – Profil bitte von Hand ausfüllen"
            else:
                try:
                    profile = await run_import(llm, target, profile)
                    message = "Profil aus dem Lebenslauf übernommen"
                except Exception as exc:
                    log.exception("Lebenslauf-Import fehlgeschlagen")
                    message = f"Lebenslauf konnte nicht ausgelesen werden: {exc}"
        profile.save(ctx.settings.profile_path)
        return get_profile() | {"message": message}

    # ------------------------------------------------------------------ Suche & Einstellungen
    @app.get("/api/search")
    def get_search() -> dict[str, Any]:
        return ctx.runtime().config.model_dump(mode="json")

    @app.put("/api/search")
    def put_search(body: dict[str, Any]) -> dict[str, Any]:
        try:
            config = SearchConfig.model_validate(body)
        except ValidationError as exc:
            raise HTTPException(422, exc.errors()) from exc
        if not config.roles and not config.filters.include_titles:
            raise HTTPException(422, "Mindestens eine Zielrolle angeben")
        config.save(ctx.settings.search_path)
        return config.model_dump(mode="json")

    @app.get("/api/presets")
    def presets() -> list[dict[str, Any]]:
        return presets_for_ui()

    @app.post("/api/search/preset")
    def preset_preview(body: PresetRequest) -> dict[str, Any]:
        config = search_config_from_preset(
            body.presets, cities=body.cities, remote=body.remote, exclude_leadership=body.exclude_leadership
        )
        return config.model_dump(mode="json")

    @app.get("/api/settings")
    def get_settings_api() -> dict[str, Any]:
        data = ctx.settings.model_dump(mode="json")
        return {k: data[k] for k in sorted(EDITABLE_SETTINGS)} | {"home": str(ctx.settings.home)}

    @app.put("/api/settings")
    def put_settings(body: dict[str, Any]) -> dict[str, Any]:
        body = {k: v for k, v in body.items() if k != "home"}
        try:
            ctx.settings = save_settings(ctx.settings, body)
        except (ValueError, ValidationError) as exc:
            raise HTTPException(422, str(exc)) from exc
        ctx.runner.settings = ctx.settings
        return get_settings_api()

    @app.post("/api/notify/test")
    async def notify_test() -> dict[str, Any]:
        sent = await notify(ctx.settings, "jobslop", "Testnachricht – Benachrichtigungen funktionieren.")
        return {"sent": sent}

    @app.post("/api/setup/complete")
    async def setup_complete(start_crawl: bool = True) -> dict[str, Any]:
        ctx.settings = save_settings(ctx.settings, {"setup_completed": True})
        ctx.runner.settings = ctx.settings
        record(ctx.settings, "setup", "Einrichtung abgeschlossen", code="setup.done")
        started = await ctx.start_crawl() if start_crawl and not ctx.settings.demo else False
        return {"ok": True, "crawl_started": started}

    # ------------------------------------------------------------------ Stellen
    @app.get("/api/jobs")
    def jobs(
        q: str = "",
        category: str = "",
        where: str = "",
        level: str = "",
        status: str = "open",
        view: str = "todo",
        min_fit: int = 0,
        sort: str = "score",
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        with session_scope(ctx.db) as s:
            stmt = select(Job)
            if status != "all":
                stmt = stmt.where(Job.status == status)
            if category:
                stmt = stmt.where(Job.category.in_(category.split(",")))
            if where in ("B", "R"):
                stmt = stmt.where(Job.where.in_([where, "BR"]))
            if level == "noS":
                stmt = stmt.where(Job.level != "S")
            elif level:
                stmt = stmt.where(Job.level.in_(level.split(",")))
            if min_fit:
                stmt = stmt.where(Job.fit >= min_fit)
            if view == "queued":
                stmt = stmt.where(Job.queued)
            elif view == "starred":
                stmt = stmt.where(Job.starred)
            if q:
                like = f"%{q}%"
                stmt = stmt.where(
                    Job.title.ilike(like)
                    | Job.company.ilike(like)
                    | Job.location.ilike(like)
                    | Job.notes.ilike(like)
                )
            order = {
                "new": (Job.first_seen.desc(),),
                "company": (Job.company, Job.score.desc()),
            }.get(sort, (Job.starred.desc(), Job.score.desc(), Job.company))
            rows = list(s.execute(stmt.order_by(*order)).scalars())
            if view == "todo":
                rows = [j for j in rows if not j.applications or j.applications[-1].status not in DONE_STATES]
            elif view == "applied":
                rows = [j for j in rows if j.applications and j.applications[-1].status in DONE_STATES]
            facets = Counter(j.category for j in rows)
            total = len(rows)
            items = [job_summary(j) for j in rows[offset : offset + limit]]
        return {"items": items, "total": total, "facets": {"category": dict(facets)}}

    @app.post("/api/jobs")
    async def add_job(body: UrlIn) -> dict[str, Any]:
        from ..jobpage import add_fetched_job, fetch_job

        ensure_not_demo(ctx.settings, "Stelle per Link laden")
        rt = ctx.runtime()
        try:
            fetched = await fetch_job(body.url.strip(), llm=rt.llm(), fast_model=ctx.settings.llm_model_fast)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        job_id, created = add_fetched_job(ctx.db, rt.config, fetched)
        return {"id": job_id, "created": created, "via": fetched.via}

    @app.get("/api/jobs/{job_id}")
    def job_detail(job_id: int) -> dict[str, Any]:
        with session_scope(ctx.db) as s:
            j = s.get(Job, job_id)
            if j is None:
                raise HTTPException(404)
            config = ctx.runtime().config
            verdict = check_job(s, j, config.limits)
            parts = score_parts(
                j.category,
                j.fit,
                j.segment,
                j.level,
                bool(j.near and "km" in j.near),
                j.where,
                config.role_names,
            )
            if is_browser_only(j.target_url):
                parts.append(("browser_only", -BROWSER_ONLY_PENALTY))
            if abs(rest := round(j.score - sum(p for _, p in parts), 2)) >= 0.1:
                parts.append(("other", rest))  # z. B. Import mit eigener Einordnung
            return job_summary(j) | {
                "description": j.description,
                "apply_url": j.apply_url,
                "alt_urls": j.alt_urls,
                "notes": j.notes,
                "enrichment": j.enrichment,
                "segment": j.segment,
                "language": j.language,
                "last_seen": _iso(j.last_seen),
                "verdict": {
                    "ok": verdict.ok,
                    "reason": verdict.reason,
                    "code": verdict.code,
                    "params": verdict.params,
                },
                "score_parts": [{"key": k, "points": p} for k, p in parts],
                "score_max": SCORE_MAX,
                "history": [
                    {"seen_at": _iso(sn.seen_at), "change": sn.change, "diff": sn.diff} for sn in j.snapshots
                ],
                "applications": [app_summary(a) for a in j.applications],
            }

    @app.patch("/api/jobs/{job_id}")
    def job_patch(job_id: int, body: JobPatch) -> dict[str, Any]:
        with session_scope(ctx.db) as s:
            j = s.get(Job, job_id)
            if j is None:
                raise HTTPException(404)
            if body.queued is True:
                verdict = check_job(s, j, ctx.runtime().config.limits)
                if not verdict.ok:
                    raise HTTPException(409, verdict.reason)
            for key, value in body.model_dump(exclude_none=True).items():
                setattr(j, key, value)
            return job_summary(j)

    @app.post("/api/jobs/{job_id}/status")
    def job_status(job_id: int, body: JobStatus) -> dict[str, Any]:
        if body.status not in MARK:
            raise HTTPException(400, "applied, interview, rejected oder offer")
        with session_scope(ctx.db) as s:
            j = s.get(Job, job_id)
            if j is None:
                raise HTTPException(404)
            last = j.applications[-1] if j.applications else None
            now = utcnow()
            if last and body.status != "applied" and last.status not in ("failed", "skipped", "paused"):
                last.status = MARK[body.status]
                last.stage_changed_at = now
                if body.note:
                    last.notes = (last.notes + "\n" + body.note).strip()
                if body.status in ("rejected", "offer"):
                    last.follow_up_at = None
            else:
                s.add(
                    Application(
                        job=j,
                        status=MARK[body.status],
                        origin="manual",
                        mode="manual",
                        submitted_at=now,
                        finished_at=now,
                        stage_changed_at=now,
                        follow_up_at=now + timedelta(days=ctx.settings.follow_up_days)
                        if body.status == "applied"
                        else None,
                        confirmation="im Dashboard eingetragen",
                        notes=body.note,
                    )
                )
            j.queued = False
            s.add(
                Activity(
                    kind="status",
                    message=f"{j.company} · {j.title}: {body.status}",
                    data={
                        "code": "status.changed",
                        "params": {
                            "company": j.company,
                            "title": j.title,
                            "status": MARK.get(body.status, body.status),
                        },
                    },
                )
            )
            s.flush()
            return job_summary(j)

    @app.post("/api/jobs/bulk")
    def jobs_bulk(body: BulkAction) -> dict[str, Any]:
        config = ctx.runtime().config
        if body.action == "queue":
            added, skipped = queue_jobs(ctx.db, config, body.ids)
            return {"changed": added, "skipped": skipped}
        changed = []
        with session_scope(ctx.db) as s:
            for jid in body.ids:
                j = s.get(Job, jid)
                if j is None:
                    continue
                if body.action == "unqueue":
                    j.queued = False
                elif body.action in ("star", "unstar"):
                    j.starred = body.action == "star"
                elif body.action == "exclude":
                    s.add(Exclusion(kind="job", value=str(jid), reason="im Dashboard ausgeschlossen"))
                    j.queued = False
                else:
                    raise HTTPException(400, "Unbekannte Aktion")
                changed.append(jid)
        return {"changed": changed, "skipped": []}

    @app.post("/api/queue/top")
    def queue_top(count: int = 10) -> dict[str, Any]:
        config = ctx.runtime().config
        picked = pick_top(ctx.db, config, max(1, min(count, 50)))
        added, skipped = queue_jobs(ctx.db, config, picked)
        return {"changed": added, "skipped": skipped}

    @app.post("/api/queue/clear")
    def queue_clear() -> dict[str, Any]:
        with session_scope(ctx.db) as s:
            rows = list(s.execute(select(Job).where(Job.queued)).scalars())
            for j in rows:
                j.queued = False
        return {"changed": [j.id for j in rows]}

    # ------------------------------------------------------------------ Bewerbungsläufe
    @app.post("/api/apply")
    def apply(body: ApplyRequest) -> dict[str, Any]:
        mode = body.mode or ctx.settings.apply_mode
        if mode not in ("review", "auto", "dry-run"):
            raise HTTPException(400, "Modus muss review, auto oder dry-run sein")
        if ctx.runner.active:
            raise HTTPException(409, "Es läuft bereits ein Bewerbungslauf")
        if not body.job_ids:
            with session_scope(ctx.db) as s:
                if not s.scalar(select(func.count(Job.id)).where(Job.queued)):
                    raise HTTPException(409, "Die Warteschlange ist leer")
        ctx.runner.start(body.job_ids or None, mode=mode, max_count=body.max, force=body.force)  # type: ignore[arg-type]
        record(
            ctx.settings,
            "run",
            f"Bewerbungslauf gestartet ({ctx.runner.label}, {mode})",
            code="run.started",
            jobs=len(body.job_ids),
            mode=mode,
        )
        return ctx.runner.state()

    @app.get("/api/runner")
    def runner_state(lines: int = 200) -> dict[str, Any]:
        return ctx.runner.state(lines=max(0, min(lines, 2000)))

    @app.post("/api/runner/stop")
    def runner_stop() -> dict[str, Any]:
        stopped = ctx.runner.stop()
        if stopped:
            record(ctx.settings, "run", "Bewerbungslauf abgebrochen", code="run.stopped")
        return ctx.runner.state() | {"stopped": stopped}

    # ------------------------------------------------------------------ Crawl & Autopilot
    @app.post("/api/crawl")
    async def crawl() -> dict[str, Any]:
        started = await ctx.start_crawl()
        return {"started": started, **ctx.crawl}

    @app.get("/api/crawls")
    def crawls(limit: int = 50) -> list[dict[str, Any]]:
        with session_scope(ctx.db) as s:
            return [
                {
                    "id": r.id,
                    "started_at": _iso(r.started_at),
                    "finished_at": _iso(r.finished_at),
                    "status": r.status,
                    "stats": r.stats,
                    "errors": r.errors,
                }
                for r in s.execute(select(CrawlRun).order_by(CrawlRun.id.desc()).limit(limit)).scalars()
            ]

    @app.get("/api/crawls/{run_id}")
    def crawl_detail(run_id: int) -> dict[str, Any]:
        with session_scope(ctx.db) as s:
            run = s.get(CrawlRun, run_id)
            if run is None:
                raise HTTPException(404)
            snaps = s.execute(
                select(JobSnapshot).where(
                    JobSnapshot.crawl_run_id == run_id, JobSnapshot.change != "unchanged"
                )
            ).scalars()
            return {
                "id": run.id,
                "started_at": _iso(run.started_at),
                "status": run.status,
                "stats": run.stats,
                "errors": run.errors,
                "changes": [
                    {
                        "job_id": sn.job_id,
                        "change": sn.change,
                        "company": sn.job.company,
                        "title": sn.title,
                        "diff": sn.diff,
                    }
                    for sn in snaps
                ],
            }

    @app.post("/api/autopilot/run")
    async def autopilot_run() -> dict[str, Any]:
        if ctx.autopilot_running:
            raise HTTPException(409, "Autopilot läuft bereits")
        ensure_not_demo(ctx.settings, "Autopilot")
        ctx.spawn(ctx.run_autopilot())
        return {"started": True}

    @app.get("/api/activity")
    def activity(limit: int = 30) -> list[dict[str, Any]]:
        with session_scope(ctx.db) as s:
            return [
                {"id": a.id, "ts": _iso(a.ts), "kind": a.kind, "message": a.message, "data": a.data}
                for a in s.execute(select(Activity).order_by(Activity.id.desc()).limit(limit)).scalars()
            ]

    # ------------------------------------------------------------------ Bewerbungen & Pipeline
    @app.get("/api/applications")
    def applications(status: str = "", limit: int = 300) -> list[dict[str, Any]]:
        with session_scope(ctx.db) as s:
            stmt = select(Application).order_by(Application.id.desc()).limit(limit)
            if status:
                stmt = stmt.where(Application.status.in_(status.split(",")))
            return [app_summary(a) for a in s.execute(stmt).scalars()]

    @app.get("/api/pipeline")
    def pipeline() -> dict[str, Any]:
        now = utcnow()
        with session_scope(ctx.db) as s:
            latest: dict[int, Application] = {}
            for a in s.execute(select(Application).order_by(Application.id)).scalars():
                latest[a.job_id] = a  # pro Stelle zählt der letzte Stand
            stages: dict[str, list[dict[str, Any]]] = {k: [] for k in STAGES}
            due = []
            for a in sorted(latest.values(), key=lambda x: x.stage_changed_at or x.started_at, reverse=True):
                for stage, statuses in STAGES.items():
                    if a.status in statuses:
                        stages[stage].append(app_summary(a))
                if (
                    a.follow_up_at
                    and a.follow_up_at <= now
                    and a.status in ("submitted", "manual", "interview")
                ):
                    due.append(app_summary(a))
            return {"stages": stages, "follow_ups_due": due}

    @app.get("/api/applications/{app_id}")
    def application_detail(app_id: int) -> dict[str, Any]:
        with session_scope(ctx.db) as s:
            a = s.get(Application, app_id)
            if a is None:
                raise HTTPException(404)
            folder = Path(a.artifacts_dir) if a.artifacts_dir else None
            files = sorted(p.name for p in folder.iterdir()) if folder and folder.is_dir() else []
            prompts = s.execute(
                select(Prompt).where(Prompt.application_id == app_id, Prompt.status == "open")
            ).scalars()
            return app_summary(a) | {
                "events": [
                    {"ts": _iso(e.ts), "kind": e.kind, "message": e.message}
                    for e in s.execute(
                        select(ApplicationEvent)
                        .where(ApplicationEvent.application_id == app_id)
                        .order_by(ApplicationEvent.id)
                    ).scalars()
                ],
                "screenshots": [f for f in files if f.endswith((".jpg", ".png"))],
                "documents": [f for f in files if f.endswith(".pdf")],
                "filled": a.filled,
                "questions": a.open_questions,
                "usage": a.usage,
                "final_url": a.final_url,
                "prompts": [prompt_json(p) for p in prompts],
            }

    @app.patch("/api/applications/{app_id}")
    def application_patch(app_id: int, body: AppPatch) -> dict[str, Any]:
        with session_scope(ctx.db) as s:
            a = s.get(Application, app_id)
            if a is None:
                raise HTTPException(404)
            if body.status is not None:
                valid = {"submitted", "manual", "interview", "offer", "rejected"}
                if body.status not in valid:
                    raise HTTPException(400, "Ungültiger Status")
                a.status = body.status
                a.stage_changed_at = utcnow()
                if body.status in ("offer", "rejected"):
                    a.follow_up_at = None
                s.add(
                    Activity(
                        kind="status",
                        message=f"{a.job.company} · {a.job.title}: {body.status}",
                        data={
                            "code": "status.changed",
                            "params": {"company": a.job.company, "title": a.job.title, "status": body.status},
                        },
                    )
                )
            if body.notes is not None:
                a.notes = body.notes
            if body.clear_follow_up:
                a.follow_up_at = None
            elif body.follow_up_at is not None:
                a.follow_up_at = body.follow_up_at.replace(tzinfo=None)
            s.flush()
            return app_summary(a)

    @app.post("/api/applications/{app_id}/answers")
    def application_answers(app_id: int, body: AppAnswers) -> dict[str, Any]:
        with session_scope(ctx.db) as s:
            a = s.get(Application, app_id)
            if a is None:
                raise HTTPException(404)
            saved = 0
            for i, q in enumerate(a.open_questions or []):
                value = str(body.answers.get(str(i), "")).strip()
                if not value:
                    continue
                question = q.get("label") or q.get("question", "")
                key = normalize_question(question)
                existing = s.execute(select(Answer).where(Answer.question_key == key)).scalars().first()
                if existing:
                    existing.answer, existing.updated_at = value, utcnow()
                else:
                    s.add(Answer(question_key=key, question=question, answer=value))
                saved += 1
            if body.requeue and a.status in ACTIVE_STATES | {"failed", "paused"}:
                a.job.queued = True
                a.status = "skipped"
                a.confirmation = "Fragen beantwortet, neu eingereiht"
            return {"saved": saved, "requeued": body.requeue}

    @app.get("/artifacts/{app_id}/{name}")
    def artifact(app_id: int, name: str) -> FileResponse:
        with session_scope(ctx.db) as s:
            a = s.get(Application, app_id)
            if a is None or not a.artifacts_dir:
                raise HTTPException(404)
            base = Path(a.artifacts_dir).resolve()
        path = (base / name).resolve()
        if base not in path.parents or not path.is_file():
            raise HTTPException(404)
        return FileResponse(path)

    # ------------------------------------------------------------------ Rückfragen
    @app.get("/api/prompts")
    def prompts() -> list[dict[str, Any]]:
        with session_scope(ctx.db) as s:
            return [
                prompt_json(p)
                for p in s.execute(
                    select(Prompt).where(Prompt.status == "open").order_by(Prompt.id)
                ).scalars()
            ]

    @app.post("/api/prompts/{prompt_id}")
    def prompt_answer(prompt_id: int, body: PromptAnswer) -> dict[str, Any]:
        with session_scope(ctx.db) as s:
            p = s.get(Prompt, prompt_id)
            if p is None or p.status != "open":
                raise HTTPException(409, "Die Rückfrage ist nicht mehr offen")
            if p.kind == "questions":
                p.response = {"skip": True} if body.skip else {"answers": body.answers}
            elif p.kind == "confirm":
                if body.decision not in ("submit", "manual", "reject"):
                    raise HTTPException(400, "decision muss submit, manual oder reject sein")
                p.response = {"decision": body.decision}
            else:
                p.response = {"abort": True} if body.abort else {"done": True}
            p.status, p.answered_at = "answered", utcnow()
            return prompt_json(p)

    # ------------------------------------------------------------------ Antwortbank & Ausschlüsse
    @app.get("/api/answers")
    def answers() -> list[dict[str, Any]]:
        with session_scope(ctx.db) as s:
            return [
                {"id": a.id, "question": a.question, "answer": a.answer, "updated_at": _iso(a.updated_at)}
                for a in s.execute(select(Answer).order_by(Answer.updated_at.desc())).scalars()
            ]

    @app.post("/api/answers")
    def answer_create(body: AnswerIn) -> dict[str, Any]:
        key = normalize_question(body.question)
        with session_scope(ctx.db) as s:
            row = s.execute(select(Answer).where(Answer.question_key == key)).scalars().first()
            if row is None:
                row = Answer(question_key=key, question=body.question, answer=body.answer)
                s.add(row)
            else:
                row.question, row.answer, row.updated_at = body.question, body.answer, utcnow()
            s.flush()
            return {"id": row.id}

    @app.put("/api/answers/{answer_id}")
    def answer_update(answer_id: int, body: AnswerIn) -> dict[str, Any]:
        with session_scope(ctx.db) as s:
            row = s.get(Answer, answer_id)
            if row is None:
                raise HTTPException(404)
            row.question, row.answer, row.updated_at = body.question, body.answer, utcnow()
            row.question_key = normalize_question(body.question)
            return {"id": row.id}

    @app.delete("/api/answers/{answer_id}")
    def answer_delete(answer_id: int) -> dict[str, Any]:
        with session_scope(ctx.db) as s:
            if row := s.get(Answer, answer_id):
                s.delete(row)
        return {"deleted": answer_id}

    @app.get("/api/exclusions")
    def exclusions() -> list[dict[str, Any]]:
        with session_scope(ctx.db) as s:
            return [
                {
                    "id": e.id,
                    "kind": e.kind,
                    "value": e.value,
                    "reason": e.reason,
                    "created_at": _iso(e.created_at),
                }
                for e in s.execute(select(Exclusion).order_by(Exclusion.id.desc())).scalars()
            ]

    @app.post("/api/exclusions")
    def exclusion_create(body: ExclusionIn) -> dict[str, Any]:
        if body.kind not in ("company", "job", "title", "url") or not body.value.strip():
            raise HTTPException(400, "kind muss company, job, title oder url sein")
        with session_scope(ctx.db) as s:
            e = Exclusion(kind=body.kind, value=body.value.strip(), reason=body.reason)
            s.add(e)
            for j in s.execute(select(Job).where(Job.queued)).scalars():
                hit = (body.kind == "company" and body.value.lower() in j.company.lower()) or (
                    body.kind == "job" and str(j.id) == body.value.strip()
                )
                if hit:
                    j.queued = False
            s.flush()
            return {"id": e.id}

    @app.delete("/api/exclusions/{ex_id}")
    def exclusion_delete(ex_id: int) -> dict[str, Any]:
        with session_scope(ctx.db) as s:
            if e := s.get(Exclusion, ex_id):
                s.delete(e)
        return {"deleted": ex_id}

    # ------------------------------------------------------------------ Statistik & Export
    @app.get("/api/stats")
    def stats() -> dict[str, Any]:
        now = utcnow()
        with session_scope(ctx.db) as s:
            jobs_open = s.scalar(select(func.count(Job.id)).where(Job.status == "open")) or 0
            new_7d = (
                s.scalar(select(func.count(Job.id)).where(Job.first_seen >= now - timedelta(days=7))) or 0
            )
            by_category = dict(
                s.execute(
                    select(Job.category, func.count()).where(Job.status == "open").group_by(Job.category)
                ).all()
            )
            apps = list(s.execute(select(Application)).scalars())
        by_status = Counter(a.status for a in apps)
        sent = [a for a in apps if a.status in DONE_STATES]
        weeks: list[dict[str, Any]] = []
        monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        for i in range(11, -1, -1):
            start = monday - timedelta(weeks=i)
            end = start + timedelta(weeks=1)
            weeks.append(
                {
                    "week": start.date().isoformat(),
                    "sent": sum(1 for a in sent if start <= (a.submitted_at or a.started_at) < end),
                }
            )
        responded = sum(by_status[k] for k in ("interview", "offer", "rejected"))
        interviews = by_status["interview"] + by_status["offer"]
        return {
            "jobs": {"open": jobs_open, "new_7d": new_7d, "by_category": by_category},
            "applications": {
                "by_status": dict(by_status),
                "sent_total": len(sent),
                "sent_7d": sum(
                    1 for a in sent if (a.submitted_at or a.started_at) >= now - timedelta(days=7)
                ),
                "response_rate": round(responded / len(sent), 3) if sent else 0,
                "interview_rate": round(interviews / len(sent), 3) if sent else 0,
                "per_week": weeks,
            },
        }

    @app.get("/api/export.csv")
    def export_csv() -> Response:
        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=";")
        writer.writerow(
            ["id", "company", "title", "location", "category", "score", "status", "application", "url"]
        )
        with session_scope(ctx.db) as s:
            for j in s.execute(select(Job).order_by(Job.score.desc())).scalars():
                last = j.applications[-1].status if j.applications else ""
                writer.writerow(
                    [j.id, j.company, j.title, j.location, j.category, j.score, j.status, last, j.url]
                )
        return Response(
            "﻿" + buf.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="jobslop-export.csv"'},
        )

    # ------------------------------------------------------------------ Oberfläche (SPA)
    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> Response:
        if path.startswith("api/"):
            raise HTTPException(404)
        if DIST.is_dir():
            candidate = (DIST / path).resolve()
            if path and candidate.is_file() and DIST.resolve() in candidate.parents:
                return FileResponse(candidate)
            index = DIST / "index.html"
            if index.exists():
                return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return HTMLResponse(
            "<h1>jobslop</h1><p>Die Oberfläche ist nicht gebaut. Im Projektordner ausführen: "
            "<code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code></p>",
            status_code=503,
        )

    return app

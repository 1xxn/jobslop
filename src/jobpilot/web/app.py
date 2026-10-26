"""FastAPI-Dashboard: Stellen, Warteschlange, Bewerbungen, Rückfragen, Crawl-History, Antwortbank."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from ..classify import LEVEL_LABEL
from ..db import Answer, Application, CrawlRun, Exclusion, Job, JobSnapshot, Prompt, session_scope, utcnow
from ..guard import ACTIVE_STATES, DONE_STATES, check_job
from ..profile import normalize_question
from ..runtime import Runtime

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
TEMPLATES.env.globals.update(LEVEL_LABEL=LEVEL_LABEL, DONE=DONE_STATES, ACTIVE=ACTIVE_STATES)
TEMPLATES.env.filters["dt"] = lambda d: d.strftime("%d.%m.%Y %H:%M") if d else ""
TEMPLATES.env.filters["where"] = lambda w: {"B": "Berlin", "R": "Remote DE", "BR": "Berlin/Remote"}.get(w, w)


def create_app(runtime: Runtime) -> FastAPI:
    app = FastAPI(title="jobpilot", docs_url=None, redoc_url=None)
    settings = runtime.settings
    db = settings.db_path
    state: dict[str, Any] = {"runner": None, "crawl": {"running": False, "last": None, "task": None}}
    runner_log = settings.home / "runner.log"

    def render(request: Request, name: str, **ctx: Any) -> HTMLResponse:
        with session_scope(db) as s:
            ctx.setdefault(
                "open_prompts", s.scalar(select(func.count(Prompt.id)).where(Prompt.status == "open")) or 0
            )
        ctx["runner_active"] = _runner_active()
        ctx["crawl_running"] = state["crawl"]["running"]
        return TEMPLATES.TemplateResponse(request, name, ctx)

    def back(request: Request, default: str = "/jobs") -> RedirectResponse:
        return RedirectResponse(request.headers.get("referer") or default, status_code=303)

    def _runner_active() -> bool:
        proc = state["runner"]
        return proc is not None and proc.poll() is None

    # ------------------------------------------------------------------ overview
    @app.get("/", response_class=HTMLResponse)
    def overview(request: Request) -> HTMLResponse:
        with session_scope(db) as s:
            open_jobs = s.scalar(select(func.count(Job.id)).where(Job.status == "open")) or 0
            queued = s.scalar(select(func.count(Job.id)).where(Job.queued)) or 0
            counts = Counter(
                dict(s.execute(select(Application.status, func.count()).group_by(Application.status)).all())
            )
            prompts = list(
                s.execute(select(Prompt).where(Prompt.status == "open").order_by(Prompt.id)).scalars()
            )
            recent = list(s.execute(select(Application).order_by(Application.id.desc()).limit(12)).scalars())
            last_run = s.execute(select(CrawlRun).order_by(CrawlRun.id.desc()).limit(1)).scalars().first()
            top = [
                j
                for j in s.execute(
                    select(Job)
                    .where(Job.status == "open", Job.level != "S")
                    .order_by(Job.score.desc())
                    .limit(60)
                ).scalars()
                if not j.applications
            ][:8]
            for p in prompts:
                _ = p.payload
            for a in recent:
                _ = a.job.company
            return render(
                request,
                "overview.html",
                open_jobs=open_jobs,
                queued=queued,
                counts=counts,
                prompts=prompts,
                recent=recent,
                last_run=last_run,
                top=top,
                done=sum(counts[k] for k in DONE_STATES),
                attention=counts["needs_input"] + counts["needs_review"],
                log_tail=_tail(runner_log),
            )

    # ------------------------------------------------------------------ jobs
    @app.get("/jobs", response_class=HTMLResponse)
    def jobs(
        request: Request,
        q: str = "",
        cat: str = "",
        where: str = "",
        level: str = "",
        status: str = "open",
        show: str = "todo",
    ) -> HTMLResponse:
        with session_scope(db) as s:
            stmt = select(Job)
            if status != "all":
                stmt = stmt.where(Job.status == status)
            if cat:
                stmt = stmt.where(Job.category == cat)
            if where == "B":
                stmt = stmt.where(Job.where.in_(["B", "BR"]))
            elif where == "R":
                stmt = stmt.where(Job.where.in_(["R", "BR"]))
            if level == "noS":
                stmt = stmt.where(Job.level != "S")
            elif level:
                stmt = stmt.where(Job.level == level)
            if q:
                like = f"%{q}%"
                stmt = stmt.where(Job.title.ilike(like) | Job.company.ilike(like) | Job.notes.ilike(like))
            rows = list(s.execute(stmt.order_by(Job.score.desc(), Job.company)).scalars())
            items = []
            for j in rows:
                last = j.applications[-1] if j.applications else None
                if show == "todo" and last and last.status in DONE_STATES:
                    continue
                if show == "queued" and not j.queued:
                    continue
                items.append({"job": j, "app": last})
            return render(
                request,
                "jobs.html",
                items=items,
                f={"q": q, "cat": cat, "where": where, "level": level, "status": status, "show": show},
            )

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    def job_detail(request: Request, job_id: int) -> HTMLResponse:
        with session_scope(db) as s:
            j = s.get(Job, job_id)
            if j is None:
                raise HTTPException(404)
            verdict = check_job(s, j, runtime.config.limits)
            _ = (j.snapshots, j.applications)
            return render(request, "job.html", job=j, verdict=verdict)

    @app.post("/jobs/{job_id}/queue")
    def job_queue(request: Request, job_id: int, on: int = Form(1)) -> RedirectResponse:
        with session_scope(db) as s:
            if j := s.get(Job, job_id):
                j.queued = bool(on)
        return back(request)

    @app.post("/jobs/{job_id}/mark")
    def job_mark(
        request: Request, job_id: int, status: str = Form(...), note: str = Form("")
    ) -> RedirectResponse:
        mapping = {"applied": "manual", "interview": "interview", "rejected": "rejected", "offer": "offer"}
        with session_scope(db) as s:
            j = s.get(Job, job_id)
            if j is None or status not in mapping:
                raise HTTPException(400)
            last = j.applications[-1] if j.applications else None
            if last and status != "applied" and last.status not in ("failed", "skipped"):
                last.status = mapping[status]
            else:
                s.add(
                    Application(
                        job=j,
                        status=mapping[status],
                        origin="manual",
                        mode="manual",
                        submitted_at=utcnow(),
                        finished_at=utcnow(),
                        confirmation=note or "im Dashboard eingetragen",
                    )
                )
            j.queued = False
        return back(request)

    @app.post("/exclude")
    def exclude(
        request: Request, kind: str = Form(...), value: str = Form(...), reason: str = Form("")
    ) -> RedirectResponse:
        if kind not in ("company", "job", "title", "url"):
            raise HTTPException(400)
        with session_scope(db) as s:
            s.add(Exclusion(kind=kind, value=value.strip(), reason=reason))
            if kind == "job" and value.isdigit() and (j := s.get(Job, int(value))):
                j.queued = False
            if kind == "company":
                for j in s.execute(select(Job).where(Job.queued)).scalars():
                    if value.lower() in j.company.lower():
                        j.queued = False
        return back(request)

    @app.get("/exclusions", response_class=HTMLResponse)
    def exclusions(request: Request) -> HTMLResponse:
        with session_scope(db) as s:
            rows = list(s.execute(select(Exclusion).order_by(Exclusion.id.desc())).scalars())
            return render(request, "exclusions.html", rows=rows)

    @app.post("/exclusions/{ex_id}/delete")
    def exclusion_delete(request: Request, ex_id: int) -> RedirectResponse:
        with session_scope(db) as s:
            if e := s.get(Exclusion, ex_id):
                s.delete(e)
        return back(request, "/exclusions")

    # ------------------------------------------------------------------ applications
    @app.get("/applications", response_class=HTMLResponse)
    def applications(request: Request, status: str = "") -> HTMLResponse:
        with session_scope(db) as s:
            stmt = select(Application).order_by(Application.id.desc()).limit(300)
            if status:
                stmt = stmt.where(Application.status == status)
            rows = list(s.execute(stmt).scalars())
            for a in rows:
                _ = a.job.title
            counts = dict(
                s.execute(select(Application.status, func.count()).group_by(Application.status)).all()
            )
            return render(request, "applications.html", rows=rows, counts=counts, status=status)

    @app.get("/applications/{app_id}", response_class=HTMLResponse)
    def application_detail(request: Request, app_id: int) -> HTMLResponse:
        with session_scope(db) as s:
            a = s.get(Application, app_id)
            if a is None:
                raise HTTPException(404)
            _ = (a.events, a.job.title)
            shots = []
            if a.artifacts_dir and Path(a.artifacts_dir).exists():
                shots = sorted(p.name for p in Path(a.artifacts_dir).glob("*.jpg"))
            pdfs = sorted(p.name for p in Path(a.artifacts_dir).glob("*.pdf")) if a.artifacts_dir else []
            prompts = list(
                s.execute(
                    select(Prompt).where(Prompt.application_id == app_id, Prompt.status == "open")
                ).scalars()
            )
            return render(request, "application.html", a=a, shots=shots, pdfs=pdfs, prompts=prompts)

    @app.get("/artifacts/{app_id}/{name}")
    def artifact(app_id: int, name: str) -> FileResponse:
        with session_scope(db) as s:
            a = s.get(Application, app_id)
            if a is None or not a.artifacts_dir:
                raise HTTPException(404)
            base = Path(a.artifacts_dir).resolve()
        path = (base / name).resolve()
        if base not in path.parents or not path.exists():
            raise HTTPException(404)
        return FileResponse(path)

    @app.post("/applications/{app_id}/answers")
    async def application_answers(request: Request, app_id: int) -> RedirectResponse:
        form = await request.form()
        with session_scope(db) as s:
            a = s.get(Application, app_id)
            if a is None:
                raise HTTPException(404)
            for i, q in enumerate(a.open_questions or []):
                value = str(form.get(f"a{i}", "")).strip()
                if not value:
                    continue
                question = q.get("label") or q.get("question", "")
                key = normalize_question(question)
                existing = s.execute(select(Answer).where(Answer.question_key == key)).scalars().first()
                if existing:
                    existing.answer, existing.updated_at = value, utcnow()
                else:
                    s.add(Answer(question_key=key, question=question, answer=value))
            if form.get("requeue"):
                a.job.queued = True
                a.status = "skipped"
                a.confirmation = "Fragen beantwortet, neu eingereiht"
        return back(request, f"/applications/{app_id}")

    # ------------------------------------------------------------------ prompts (Live-Rückfragen)
    @app.get("/api/prompts")
    def api_prompts() -> JSONResponse:
        with session_scope(db) as s:
            rows = (
                s.execute(select(Prompt).where(Prompt.status == "open").order_by(Prompt.id)).scalars().all()
            )
            return JSONResponse(
                {
                    "open": [
                        {
                            "id": p.id,
                            "kind": p.kind,
                            "application_id": p.application_id,
                            "title": p.payload.get("title", ""),
                        }
                        for p in rows
                    ],
                    "runner": _runner_active(),
                    "crawl": state["crawl"]["running"],
                }
            )

    @app.post("/prompts/{prompt_id}")
    async def prompt_answer(request: Request, prompt_id: int) -> RedirectResponse:
        form = await request.form()
        with session_scope(db) as s:
            p = s.get(Prompt, prompt_id)
            if p is None or p.status != "open":
                return back(request, "/")
            if p.kind == "questions":
                if form.get("skip"):
                    p.response = {"skip": True}
                else:
                    p.response = {
                        "answers": {
                            q["field_id"]: str(form.get(f"q_{q['field_id']}", ""))
                            for q in p.payload.get("questions", [])
                        }
                    }
            elif p.kind == "confirm":
                p.response = {"decision": str(form.get("decision", "reject"))}
            else:
                p.response = {"abort": True} if form.get("abort") else {"done": True}
            p.status = "answered"
            p.answered_at = utcnow()
        return back(request, "/")

    # ------------------------------------------------------------------ runner (Bewerbungen im Hintergrund)
    @app.post("/run")
    async def run(request: Request) -> RedirectResponse:
        form = await request.form()
        if _runner_active():
            return back(request, "/")
        ids = [str(v) for v in form.getlist("job_id")] if hasattr(form, "getlist") else []
        mode = str(form.get("mode", settings.apply_mode))
        args = [sys.executable, "-m", "jobpilot", "apply", "--via-dashboard", "--mode", mode]
        args += ids if ids else ["--queue"]
        if form.get("max"):
            args += ["--max", str(form.get("max"))]
        log = runner_log.open("w", encoding="utf-8")
        env = os.environ | {"PYTHONUNBUFFERED": "1", "JOBPILOT_HOME": str(settings.home), "COLUMNS": "140"}
        state["runner"] = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, env=env)  # noqa: ASYNC220
        return back(request, "/")

    @app.post("/run/stop")
    def run_stop(request: Request) -> RedirectResponse:
        if _runner_active():
            state["runner"].terminate()
        return back(request, "/")

    @app.get("/api/runner-log")
    def runner_log_api() -> JSONResponse:
        return JSONResponse({"active": _runner_active(), "log": _tail(runner_log, 60)})

    # ------------------------------------------------------------------ crawls
    @app.get("/crawls", response_class=HTMLResponse)
    def crawls(request: Request) -> HTMLResponse:
        with session_scope(db) as s:
            rows = list(s.execute(select(CrawlRun).order_by(CrawlRun.id.desc()).limit(100)).scalars())
            return render(request, "crawls.html", rows=rows, last=state["crawl"]["last"])

    @app.get("/crawls/{run_id}", response_class=HTMLResponse)
    def crawl_detail(request: Request, run_id: int) -> HTMLResponse:
        with session_scope(db) as s:
            run = s.get(CrawlRun, run_id)
            if run is None:
                raise HTTPException(404)
            snaps = list(
                s.execute(
                    select(JobSnapshot).where(
                        JobSnapshot.crawl_run_id == run_id, JobSnapshot.change != "unchanged"
                    )
                ).scalars()
            )
            for sn in snaps:
                _ = sn.job.company
            return render(request, "crawl.html", run=run, snaps=snaps)

    @app.post("/crawls/start")
    async def crawl_start(request: Request) -> RedirectResponse:
        if not state["crawl"]["running"]:
            state["crawl"]["running"] = True
            state["crawl"]["task"] = asyncio.create_task(_crawl())
        return back(request, "/crawls")

    async def _crawl() -> None:
        from ..crawl.pipeline import run_crawl

        try:
            from ..llm import check_login

            r = Runtime.load(settings)
            login = await asyncio.to_thread(check_login, r.settings)
            llm = r.llm() if login.ok else None
            report = await run_crawl(r.settings, r.config, llm=llm, profile=r.profile, enrich=llm is not None)
            state["crawl"]["last"] = (
                f"Crawl #{report.run_id}: +{len(report.new)} neu, −{len(report.closed)} geschlossen"
            )
        except Exception as exc:
            state["crawl"]["last"] = f"Crawl fehlgeschlagen: {exc}"
        finally:
            state["crawl"]["running"] = False

    # ------------------------------------------------------------------ answers
    @app.get("/answers", response_class=HTMLResponse)
    def answers(request: Request) -> HTMLResponse:
        with session_scope(db) as s:
            rows = list(s.execute(select(Answer).order_by(Answer.updated_at.desc())).scalars())
            return render(request, "answers.html", rows=rows)

    @app.post("/answers")
    def answers_save(
        request: Request, question: str = Form(...), answer: str = Form(...), answer_id: int = Form(0)
    ) -> RedirectResponse:
        with session_scope(db) as s:
            row = s.get(Answer, answer_id) if answer_id else None
            if row is None:
                key = normalize_question(question)
                row = s.execute(select(Answer).where(Answer.question_key == key)).scalars().first()
            if row is None:
                s.add(Answer(question_key=normalize_question(question), question=question, answer=answer))
            else:
                row.question, row.answer, row.updated_at = question, answer, utcnow()
        return back(request, "/answers")

    @app.post("/answers/{answer_id}/delete")
    def answers_delete(request: Request, answer_id: int) -> RedirectResponse:
        with session_scope(db) as s:
            if a := s.get(Answer, answer_id):
                s.delete(a)
        return back(request, "/answers")

    return app


def _tail(path: Path, lines: int = 25) -> str:
    if not path.exists():
        return ""
    data = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(data[-lines:])

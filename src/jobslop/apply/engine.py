"""Ablaufsteuerung einer Bewerbung: Navigieren → Erfassen → Planen → Ausfüllen → Freigeben → Absenden → Bestätigen."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
import re
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select

from ..config import ApplyMode, SearchConfig, Settings, ensure_not_demo
from ..db import Answer, Application, ApplicationEvent, Job, session_scope, utcnow
from ..guard import check_job
from ..hosts import host_of, is_handoff
from ..llm import LLM, LLMLimitReached
from ..profile import Profile, normalize_question
from .coverletter import cover_letter_html, cover_letter_text, render_pdf, write_cover_letter
from .executor import Executor, Files, click_element
from .extract import PageState, extract_state
from .interact import Interactor
from .marks import annotated_screenshots, save_screenshot
from .planner import (
    _CONFIRM_RX,
    JobContext,
    LLMPlanner,
    PagePlan,
    PlanInput,
    Planner,
    guard_submit_clicks,
)
from .prepare import dismiss_cookie_banners, reveal_lazy_content, try_autofill

log = logging.getLogger(__name__)


class Park(Exception):
    """Bewerbung anhalten und mit Status ablegen."""

    def __init__(self, status: str, message: str, questions: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.questions = questions or []


@dataclass
class Outcome:
    job_id: int
    application_id: int | None
    status: str
    message: str = ""
    artifacts: str = ""


@dataclass
class _Run:
    app_id: int
    job: JobContext
    artdir: Path
    history: list[str] = field(default_factory=list)
    filled: list[dict[str, Any]] = field(default_factory=list)
    submit_clicked: bool = False
    submit_attempts: int = 0
    submit_clicks: int = 0
    fills_since_submit: int = 0
    captcha_ack: set[str] = field(default_factory=set)
    signatures: list[str] = field(default_factory=list)
    vision_forced: bool = False
    seen_urls: set[str] = field(default_factory=set)
    autofill_tried: set[str] = field(default_factory=set)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "job"


async def settle(page: Any) -> None:
    for state, timeout in (("domcontentloaded", 15_000), ("networkidle", 6_000)):
        with contextlib.suppress(Exception):
            await page.wait_for_load_state(state, timeout=timeout)
    await asyncio.sleep(0.8)


class BrowserSession:
    """Persistenter Chromium-Kontext (Logins bei Bewerbungsportalen bleiben erhalten) plus Headless-Browser für PDFs."""

    def __init__(self, settings: Settings, headless: bool | None = None) -> None:
        self.settings = settings
        self.headless = settings.headless if headless is None else headless
        self._pw: Any = None
        self.context: Any = None
        self._pdf_browser: Any = None

    async def __aenter__(self) -> BrowserSession:
        from playwright.async_api import async_playwright

        self.settings.ensure_dirs()
        self._pw = await async_playwright().start()
        self.context = await self._pw.chromium.launch_persistent_context(
            str(self.settings.browser_profile_dir),
            headless=self.headless,
            locale="de-DE",
            timezone_id="Europe/Berlin",
            viewport={"width": 1366, "height": 900},
            accept_downloads=True,
        )
        self.context.set_default_timeout(15_000)
        self.context.set_default_navigation_timeout(self.settings.navigation_timeout_ms)
        return self

    async def __aexit__(self, *exc: object) -> None:
        for closer in (self.context, self._pdf_browser):
            if closer is not None:
                with contextlib.suppress(Exception):
                    await closer.close()
        if self._pw is not None:
            await self._pw.stop()

    async def new_page(self) -> Any:
        return await self.context.new_page()

    async def pdf_context(self) -> Any:
        if self._pdf_browser is None:
            self._pdf_browser = await self._pw.chromium.launch(headless=True)
        return await self._pdf_browser.new_context()


class ApplyEngine:
    def __init__(
        self,
        *,
        settings: Settings,
        config: SearchConfig,
        profile: Profile,
        planner: Planner,
        interactor: Interactor,
        browser: BrowserSession,
        llm: LLM | None = None,
        mode: ApplyMode = "review",
        on_event: Callable[[str], None] | None = None,
    ) -> None:
        self.settings = settings
        self.config = config
        self.profile = profile
        self.planner = planner
        self.interactor = interactor
        self.browser = browser
        self.llm = llm
        self.mode = mode
        self.on_event = on_event or (lambda _m: None)
        self._kept_page: Any = None  # zuletzt im Testlauf ausgefüllte Seite (bleibt zum Nachsehen offen)
        base = settings.profile_path.parent
        self.files = Files(
            cv=profile.cv_path(base),
            cv_en=profile.documents.resolve(profile.documents.cv_en, base),
            certificates=[
                p for c in profile.documents.certificates if (p := profile.documents.resolve(c, base))
            ],
        )

    # ------------------------------------------------------------------ public
    async def apply(self, job_id: int, *, force: bool = False) -> Outcome:
        ensure_not_demo(self.settings, "Bewerben")
        if self._kept_page is not None:  # nur die jeweils letzte Testlauf-Seite offen halten
            with contextlib.suppress(Exception):
                await self._kept_page.close()
            self._kept_page = None
        with session_scope(self.settings.db_path) as s:
            job = s.get(Job, job_id)
            if job is None:
                return Outcome(job_id, None, "skipped", "Job nicht gefunden")
            verdict = check_job(s, job, self.config.limits, force=force)
            if not verdict.ok:
                return Outcome(job_id, None, "skipped", verdict.reason)
            app = Application(job=job, mode=self.mode, status="running")
            s.add(app)
            s.flush()
            artdir = self.settings.artifacts_dir / f"{app.id:04d}-{slugify(job.company)}-{slugify(job.title)}"
            artdir.mkdir(parents=True, exist_ok=True)
            app.artifacts_dir = str(artdir)
            ctx = JobContext(
                id=job.id,
                company=job.company,
                title=job.title,
                location=job.location,
                url=job.target_url,
                description=job.description or job.notes,
                language=job.language,
            )
            app_id = app.id
            job.queued = False

        run = _Run(app_id=app_id, job=ctx, artdir=artdir)
        usage_before = self.llm.usage.as_dict() if self.llm else {}
        page = None
        status, message, questions = "failed", "", []
        try:
            page = await self.browser.new_page()
            status, message, page = await self._run(run, page)
        except Park as park:
            status, message, questions = park.status, park.message, park.questions
        except LLMLimitReached as exc:
            # Abo-Limit: nichts abgesendet, Stelle bleibt in der Warteschlange und kann später neu starten.
            status, message = "paused", str(exc)[:300]
        except Exception as exc:
            status, message = "failed", f"{type(exc).__name__}: {exc}"
            self._event(app_id, "error", message, {"traceback": traceback.format_exc()[-4000:]})
        finally:
            final_url = page.url if page is not None else ""
            if page is not None:
                await save_screenshot(page, artdir / "final.jpg")
                if status == "ready":  # Testlauf: Seite offen lassen, damit man reinschauen kann
                    self._kept_page = page
                else:
                    with contextlib.suppress(Exception):
                        await page.close()
            usage = self._usage_delta(usage_before)
            (artdir / "filled.json").write_text(
                json.dumps(run.filled, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            with session_scope(self.settings.db_path) as s:
                app = s.get(Application, app_id)
                assert app is not None
                app.status = status
                app.finished_at = utcnow()
                app.final_url = final_url
                app.filled = run.filled
                app.usage = usage
                app.open_questions = questions
                if status == "paused" and (job_row := s.get(Job, job_id)) is not None:
                    job_row.queued = True
                if status == "submitted":
                    app.submitted_at = utcnow()
                    app.confirmation = message
                elif status in ("failed",):
                    app.error = message
                else:
                    app.confirmation = message
            self._event(app_id, "status", f"{status}: {message}")
        return Outcome(job_id, app_id, status, message, str(artdir))

    # ------------------------------------------------------------------ main loop
    async def _run(self, run: _Run, page: Any) -> tuple[str, str, Any]:
        title = f"{run.job.company} – {run.job.title}"
        self._event(run.app_id, "navigate", run.job.url)
        await page.goto(run.job.url, wait_until="domcontentloaded")

        failures: list[str] = []
        for step in range(1, self.settings.max_steps_per_application + 1):
            await settle(page)
            # Auch mitten im Ablauf: führt ein Klick (Weiterleitung, „Mit LinkedIn bewerben“) auf LinkedIn/Indeed,
            # wird dort nichts automatisch bedient.
            if is_handoff(page.url):
                page = await self._aggregator_handoff(run, page, title)
                await settle(page)
            state = await self._prepare(run, page)

            if run.submit_clicked and _CONFIRM_RX.search(state.text):
                await save_screenshot(page, run.artdir / "confirmation.jpg")
                return "submitted", self._confirmation_excerpt(state.text), page

            if state.captcha_visible and state.url not in run.captcha_ack:
                run.captcha_ack.add(state.url)
                page = await self._handoff(
                    run, page, title, "Bitte löse das CAPTCHA im Browserfenster. Danach mache ich weiter."
                )
                continue

            page_key = state.url.split("#")[0].split("?")[0]
            if (
                self.settings.autofill
                and page_key not in run.autofill_tried
                and any(b.get("autofill") for b in state.buttons)
            ):
                run.autofill_tried.add(page_key)
                try:
                    note, page = await try_autofill(page, state, self.files.cv)
                except Exception as exc:  # Autofill ist ein Bonus – nie die Bewerbung daran scheitern lassen
                    note = f"Autofill fehlgeschlagen ({type(exc).__name__}) – Formular wird normal ausgefüllt"
                if note:
                    run.history.append(f"Schritt {step}: {note}")
                    self._event(run.app_id, "autofill", note)
                    self.on_event(note)
                    await settle(page)
                    state = await extract_state(page)

            self._loop_guard(run, state)
            shots: list[bytes] = []
            vision = self.settings.vision
            if isinstance(self.planner, LLMPlanner) and (
                vision == "always"
                or (
                    vision == "auto"
                    and (run.vision_forced or (not state.form_fields and len(state.buttons) < 2))
                )
            ):
                shots = await annotated_screenshots(page, state)

            plan = await self.planner.plan(
                PlanInput(
                    job=run.job,
                    state=state,
                    step=step,
                    history=run.history,
                    failures=failures,
                    submit_clicked=run.submit_clicked,
                    screenshots=shots,
                )
            )
            (run.artdir / f"step-{step:02d}-plan.json").write_text(
                plan.model_dump_json(indent=2), encoding="utf-8"
            )
            await save_screenshot(page, run.artdir / f"step-{step:02d}.jpg", full_page=False)
            self._event(
                run.app_id,
                "plan",
                f"[{plan.page_kind} → {plan.next_step}] {plan.summary}",
                {"actions": len(plan.actions), "questions": len(plan.open_questions), "url": state.url},
            )
            self.on_event(f"Schritt {step}: {plan.summary}")

            if plan.page_kind == "confirmation":
                if run.submit_clicked:
                    return "submitted", self._confirmation_excerpt(state.text), page
                raise Park(
                    "needs_review",
                    "Bestätigungsseite ohne eigenes Absenden – bitte prüfen, ob schon beworben",
                )
            if plan.page_kind == "closed_or_error" or plan.next_step == "abort":
                return "failed", f"Abgebrochen: {plan.summary}", page
            if plan.page_kind in ("login_or_account", "captcha") or (
                plan.next_step == "wait_for_user" and not plan.open_questions
            ):
                page = await self._handoff(run, page, title, self._handoff_text(plan))
                run.history.append(f"Schritt {step}: Übergabe an dich ({plan.page_kind}) erledigt")
                continue

            if plan.open_questions:
                await self._resolve_questions(run, state, plan, title)
                failures = []
                continue

            wants_letter = [
                a
                for a in plan.actions
                if a.action != "skip" and a.value.strip().lower() in ("@cover_letter", "@cover_letter_pdf")
            ]
            if wants_letter and self.profile.documents.cover_letter == "none":
                for a in wants_letter:  # Anschreiben abgeschaltet: diese Felder auslassen
                    a.action = "skip"
            elif wants_letter:
                await self._ensure_cover_letter(run)

            self._guard_submit_clicks(run, state, plan)
            results = await Executor(page, self.files).run(state, plan.actions)
            planned = {a.field_id: a for a in plan.actions}
            for r in results:
                a = planned.get(r.field_id)
                run.filled.append(
                    {
                        "step": step,
                        "field_id": r.field_id,
                        "label": r.label,
                        "action": r.action,
                        "value": r.value if r.value != "@cover_letter" else "(Anschreiben)",
                        "ok": r.ok,
                        "detail": r.detail,
                        "source": a.source if a else "",
                        "confidence": a.confidence if a else "",
                    }
                )
            failures = [
                f"{r.label or r.field_id} ({r.action} '{r.value[:40]}'): {r.detail}"
                for r in results
                if not r.ok
            ]
            ok_count = sum(r.ok for r in results)
            run.fills_since_submit += sum(1 for r in results if r.ok and r.action != "click")
            run.history.append(f"Schritt {step}: {plan.summary} – {ok_count}/{len(results)} Aktionen ok")
            self._event(run.app_id, "fill", f"{ok_count}/{len(results)} Aktionen ok", {"failures": failures})

            clicked = {r.field_id for r in results if r.action == "click" and r.ok}
            if (
                plan.next_step in ("click_apply", "click_next", "click_submit")
                and plan.next_target_id in clicked
            ):
                # Ziel wurde schon als Aktion geklickt (z. B. Cookie-Banner) – Seite neu erfassen statt doppelt klicken.
                continue

            if plan.next_step in ("click_apply", "click_next"):
                if not plan.next_target_id or (
                    state.button(plan.next_target_id) is None and state.field(plan.next_target_id) is None
                ):
                    failures.append(f"Button-ID '{plan.next_target_id}' existiert nicht")
                    continue
                try:
                    page = await click_element(page, state, plan.next_target_id)
                except Exception as exc:
                    failures.append(
                        f"Button '{plan.next_target_id}' nicht klickbar: {str(exc).splitlines()[0][:160]}"
                    )
                    continue
                run.history.append(
                    f"Schritt {step}: '{(state.button(plan.next_target_id) or {}).get('text', '')}' geklickt"
                )
                continue

            if plan.next_step == "click_submit":
                if failures and run.submit_attempts < 2:
                    run.submit_attempts += 1
                    continue  # erst Fehler beheben lassen
                # Schutz vor Doppel-Bewerbungen: erneut absenden nur, wenn seit dem letzten Klick etwas korrigiert wurde.
                if run.submit_clicked and (run.fills_since_submit == 0 or run.submit_clicks >= 3):
                    errors = "; ".join(state.errors[:5]) or "keine Fehlermeldung sichtbar"
                    raise Park(
                        "needs_review",
                        f"Nach dem Absenden keine Bestätigung erkannt ({errors}) – bitte im Browser prüfen",
                    )
                page = await self._submit(run, page, state, plan, title)
                continue

            if plan.next_step == "done":
                if run.submit_clicked:
                    return "submitted", "Abgesendet (keine eindeutige Bestätigungsseite erkannt)", page
                raise Park("needs_review", f"Planer meldet fertig ohne Absenden: {plan.summary}")

        raise Park("needs_review", "Zu viele Schritte ohne Abschluss – bitte im Browser prüfen")

    # ------------------------------------------------------------------ pieces
    async def _submit(self, run: _Run, page: Any, state: PageState, plan: PagePlan, title: str) -> Any:
        await save_screenshot(page, run.artdir / "pre-submit.jpg")
        rows = [r for r in run.filled if r["ok"]]
        low = [r for r in rows if r.get("confidence") == "low"]
        missing = (await extract_state(page)).missing_required()
        self._event(
            run.app_id,
            "review",
            f"{len(rows)} Felder gefüllt, {len(low)} unsicher, {len(missing)} Pflichtfelder leer",
        )

        if self.mode == "dry-run":
            raise Park("ready", "Formular vollständig ausgefüllt, Testlauf ohne Absenden")
        if self.mode == "auto" and not low and not missing:
            decision = "submit"
        else:
            decision = await self.interactor.confirm(run.app_id, title, rows, run.artdir / "pre-submit.jpg")
        self._event(run.app_id, "decision", decision)
        if decision == "manual":

            async def confirmed() -> bool:
                try:
                    st = await extract_state(page)
                except Exception:
                    return False
                return bool(_CONFIRM_RX.search(st.text))

            ok = await self.interactor.handoff(
                run.app_id,
                title,
                "Korrigiere das Formular und sende es selbst ab. "
                "Ich erkenne die Bestätigungsseite und trage die Bewerbung ein.",
                confirmed,
            )
            if ok and await confirmed():
                run.submit_clicked = True
                return page
            raise Park("needs_review", "Manuelles Absenden nicht bestätigt")
        if decision != "submit":
            raise Park(
                "needs_review",
                "Absenden nicht freigegeben" + (f" ({len(low)} unsichere Felder)" if low else ""),
            )

        self._event(run.app_id, "submit", f"Klick auf {plan.next_target_id}")
        try:
            page = await click_element(page, state, plan.next_target_id)
        except Exception as exc:
            run.history.append(f"Absenden-Button nicht klickbar: {str(exc).splitlines()[0][:160]}")
            return page
        run.submit_clicked = True
        run.submit_clicks += 1
        run.fills_since_submit = 0
        run.history.append("Absenden geklickt")
        return page

    async def _prepare(self, run: _Run, page: Any) -> PageState:
        """Cookie-Banner schließen und (beim ersten Besuch einer URL) nachgeladene Inhalte wecken, dann erfassen."""
        key = page.url.split("#")[0]
        try:
            closed = await dismiss_cookie_banners(page)
        except Exception as exc:
            closed = []
            log.info("Cookie-Banner konnte nicht geprüft werden: %s", exc)
        if closed:
            run.history.append(f"Cookie-Banner geschlossen ('{closed[-1]}')")
            await settle(page)
        if key not in run.seen_urls:
            run.seen_urls.add(key)
            await reveal_lazy_content(page)
        return await extract_state(page)

    async def _resolve_questions(self, run: _Run, state: PageState, plan: PagePlan, title: str) -> None:
        questions = plan.open_questions
        answers = await self.interactor.ask(run.app_id, title, questions)
        if not answers:
            payload = [
                q.model_dump() | {"label": (state.field(q.field_id) or {}).get("label", "")}
                for q in questions
            ]
            raise Park("needs_input", f"{len(questions)} offene Frage(n)", payload)
        with session_scope(self.settings.db_path) as s:
            for q in questions:
                if q.field_id not in answers:
                    continue
                label = (state.field(q.field_id) or {}).get("label") or q.question
                remember_answer(s, label, answers[q.field_id])
                self.planner.remember(label, answers[q.field_id])
        run.history.append(f"{len(answers)} Rückfrage(n) beantwortet und gespeichert")
        self._event(run.app_id, "answers", f"{len(answers)} Antworten gespeichert")

    async def _ensure_cover_letter(self, run: _Run) -> None:
        if self.files.cover_letter_text or self.profile.documents.cover_letter == "none":
            return
        custom = self.profile.documents.resolve(
            self.profile.documents.cover_letter, self.settings.profile_path.parent
        )
        if custom and custom.exists():
            self.files.cover_letter_pdf = custom
            return
        if self.llm is None:
            raise Park(
                "needs_input",
                "Anschreiben verlangt, aber Claude Code ist nicht verfügbar (offline) – documents.cover_letter "
                "auf eine PDF setzen oder mit Claude Code starten",
            )
        letter = await write_cover_letter(
            self.llm,
            self.profile,
            run.job,
            self.profile.preferences.cover_letter_language,
            cv_text=getattr(self.planner, "cv_text", ""),
            cv_file=getattr(self.planner, "cv_file", None) or self.files.cv,
        )
        text = cover_letter_text(letter, self.profile)
        (run.artdir / "anschreiben.txt").write_text(text, encoding="utf-8")
        pdf_path = (
            run.artdir
            / f"Anschreiben_{slugify(self.profile.personal.full_name)}_{slugify(run.job.company)}.pdf"
        )
        ctx = await self.browser.pdf_context()
        try:
            await render_pdf(ctx, cover_letter_html(letter, self.profile, run.job), pdf_path)
        finally:
            await ctx.close()
        self.files.cover_letter_text = text
        self.files.cover_letter_pdf = pdf_path
        self._event(
            run.app_id, "cover_letter", f"Anschreiben erstellt ({letter.language})", {"pdf": str(pdf_path)}
        )

    async def _handoff(self, run: _Run, page: Any, title: str, message: str) -> Any:
        self._event(run.app_id, "handoff", message)
        await page.bring_to_front()
        ok = await self.interactor.handoff(run.app_id, title, message, None)
        if not ok:
            raise Park("needs_review", f"Übergabe nicht abgeschlossen: {message}")
        pages = page.context.pages
        return pages[-1] if pages and pages[-1] is not page and not pages[-1].is_closed() else page

    async def _aggregator_handoff(self, run: _Run, page: Any, title: str) -> Any:
        context = page.context

        def employer_page() -> Any:
            for p in reversed(context.pages):
                if not p.is_closed() and p.url.startswith("http") and not is_handoff(p.url):
                    return p
            return None

        async def check() -> bool:
            return employer_page() is not None

        message = (
            "Diese Stelle liegt auf LinkedIn/Indeed. Ich bediene diese Portale nicht automatisch, weil sie "
            "Automatisierung sperren. Klicke im Browser selbst auf „Bewerben“ bzw. „Auf Unternehmenswebsite "
            "bewerben“. Sobald die Firmenseite offen ist, übernehme ich. Bei „Einfach bewerben“ bitte selbst "
            "absenden und danach 'abbrechen' tippen – die Stelle dann mit `jobslop mark applied` eintragen."
        )
        self._event(run.app_id, "handoff", "Übergabe LinkedIn/Indeed")
        ok = await self.interactor.handoff(run.app_id, title, message, check)
        target = employer_page()
        if not ok or target is None:
            raise Park("needs_review", "Übergabe von LinkedIn/Indeed nicht erfolgt")
        await target.bring_to_front()
        run.history.append(f"Von LinkedIn/Indeed zur Firmenseite gewechselt: {host_of(target.url)}")
        return target

    @staticmethod
    def _guard_submit_clicks(run: _Run, state: PageState, plan: PagePlan) -> None:
        """Abgesendet wird nur über ``_submit`` (Freigabe, Testlauf, Doppel-Schutz) – nie als Nebenbei-Klick."""
        filled_before = any(r["ok"] and r["action"] != "click" for r in run.filled)
        run.history += guard_submit_clicks(state, plan, filled_before=filled_before)

    def _loop_guard(self, run: _Run, state: PageState) -> None:
        sig = (
            state.url.split("#")[0] + "|" + "|".join(f"{f['id']}={f.get('value', '')}" for f in state.fields)
        )
        run.signatures.append(sig)
        repeats = sum(1 for s in run.signatures[-5:] if s == sig)
        if repeats >= 3:
            run.vision_forced = True
        if repeats >= 5:
            raise Park("needs_review", "Seite ändert sich nicht mehr – Formular hängt, bitte prüfen")

    @staticmethod
    def _handoff_text(plan: PagePlan) -> str:
        if plan.page_kind == "login_or_account":
            return (
                "Dieses Portal verlangt ein Konto oder einen Login. Bitte im Browser einloggen bzw. Konto anlegen "
                "und bis zum Bewerbungsformular gehen. Der Login bleibt für künftige Bewerbungen gespeichert."
            )
        if plan.page_kind == "captcha":
            return "Bitte löse das CAPTCHA im Browser."
        return f"Bitte im Browser übernehmen: {plan.summary}"

    @staticmethod
    def _confirmation_excerpt(text: str) -> str:
        m = _CONFIRM_RX.search(text)
        if not m:
            return text[:300]
        start = m.start()
        return re.sub(r"\s+", " ", text[start : m.end() + 200]).strip()

    def _usage_delta(self, before: dict[str, Any]) -> dict[str, Any]:
        if not self.llm:
            return {}
        after = self.llm.usage.as_dict()
        return {
            k: round(after[k] - before.get(k, 0), 1)
            if isinstance(after[k], float)
            else after[k] - before.get(k, 0)
            for k in after
            if isinstance(after[k], int | float)
        }

    def _event(self, app_id: int, kind: str, message: str, data: dict[str, Any] | None = None) -> None:
        log.info("[app %s] %s: %s", app_id, kind, message)
        with session_scope(self.settings.db_path) as s:
            s.add(ApplicationEvent(application_id=app_id, kind=kind, message=message[:2000], data=data or {}))


# --------------------------------------------------------------------------- Batch


async def run_batch(
    engine: ApplyEngine,
    job_ids: list[int],
    *,
    max_count: int,
    min_delay: int,
    on_result: Callable[[Outcome], None] | None = None,
) -> list[Outcome]:
    outcomes: list[Outcome] = []
    attempted = 0
    for job_id in job_ids:
        if attempted >= max_count:
            break
        outcome = await engine.apply(job_id)
        outcomes.append(outcome)
        if on_result:
            on_result(outcome)
        if outcome.status == "paused":
            break  # Abo-Limit erreicht: Rest bleibt eingereiht
        if outcome.application_id is not None:
            attempted += 1
            if attempted < max_count and job_id != job_ids[-1]:
                await asyncio.sleep(random.uniform(min_delay, min_delay * 1.6))
    return outcomes


def remember_answer(session: Any, question: str, answer: str) -> None:
    """Antwort in die Antwortbank – künftige Formulare mit derselben Frage füllt jobslop dann selbst."""
    key = normalize_question(question)
    existing = session.execute(select(Answer).where(Answer.question_key == key)).scalars().first()
    if existing:
        existing.answer, existing.updated_at = answer, utcnow()
    else:
        session.add(Answer(question_key=key, question=question, answer=answer))


def load_answers(db_path: Path) -> list[tuple[str, str]]:
    with session_scope(db_path) as s:
        rows = s.execute(select(Answer).order_by(Answer.updated_at.desc())).scalars().all()
        return [(a.question, a.answer) for a in rows]

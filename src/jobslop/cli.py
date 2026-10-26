"""Kommandozeile: `jobslop …`"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.markup import escape
from rich.table import Table
from sqlalchemy import func, select

from . import __version__
from .classify import LEVEL_LABEL
from .config import get_settings
from .db import Answer, Application, CrawlRun, Exclusion, Job, JobSnapshot, session_scope, utcnow
from .guard import DONE_STATES
from .runtime import Runtime, init_home

console = Console()
app = typer.Typer(
    help="jobslop – Bewerbungs-Autopilot. Ohne Befehl startet das Dashboard (inkl. Einrichtung).",
    no_args_is_help=False,
    rich_markup_mode="rich",
)
jobs_app = typer.Typer(help="Stellen anzeigen und bewerten.", no_args_is_help=True)
queue_app = typer.Typer(help="Warteschlange für Bewerbungen.", no_args_is_help=True)
profile_app = typer.Typer(help="Bewerberprofil.", no_args_is_help=True)
exclude_app = typer.Typer(help="Firmen, Stellen oder Titel ausschließen.", no_args_is_help=True)
answers_app = typer.Typer(help="Antwortbank für wiederkehrende Formularfragen.", no_args_is_help=True)
apps_app = typer.Typer(help="Bewerbungen und ihr Status.", no_args_is_help=True)
for sub, name in (
    (jobs_app, "jobs"),
    (queue_app, "queue"),
    (profile_app, "profile"),
    (exclude_app, "exclude"),
    (answers_app, "answers"),
    (apps_app, "apps"),
):
    app.add_typer(sub, name=name)

CAT_STYLE = {
    "SRE": "#e8743b",
    "Platform": "#6c8cf5",
    "DevOps": "#3fbf8a",
    "Cloud": "#3cb6d3",
    "System": "#b48af0",
}
STATUS_STYLE = {
    "submitted": "green",
    "manual": "green",
    "interview": "bold green",
    "offer": "bold green",
    "needs_input": "yellow",
    "needs_review": "yellow",
    "paused": "magenta",
    "ready": "cyan",
    "running": "cyan",
    "failed": "red",
    "rejected": "dim",
    "skipped": "dim",
}


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Ausführliche Logs")] = False,
    version: Annotated[bool, typer.Option("--version", help="Version anzeigen")] = False,
) -> None:
    if version:
        console.print(f"jobslop {__version__}")
        raise typer.Exit()
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_path=False, rich_tracebacks=True)],
    )
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if ctx.invoked_subcommand is None:
        start(port=None, open_browser=True)


def rt() -> Runtime:
    return Runtime.load()


def need_claude(r: Runtime):
    """LLM-Client oder Abbruch mit klarer Meldung, wenn Claude Code fehlt bzw. nicht eingeloggt ist."""
    from .llm import check_login

    login = check_login(r.settings)
    llm = r.llm() if login.ok else None
    if llm is None:
        console.print(f"[red]{escape(login.message)}[/red]")
        raise typer.Exit(1)
    return llm


def _where(w: str) -> str:
    return {"B": "Berlin", "R": "Remote DE", "BR": "Berlin/Remote"}.get(w, w)


def _app_status(job: Job) -> str:
    if not job.applications:
        return "queued" if job.queued else ""
    return job.applications[-1].status


# --------------------------------------------------------------------------- setup


@app.command()
def init(
    force: Annotated[bool, typer.Option(help="Vorhandene search.toml/profile.yaml überschreiben")] = False,
) -> None:
    """Arbeitsordner mit Standard-Suche und leerem Profil anlegen (macht `jobslop` beim ersten Start selbst)."""
    settings = get_settings()
    created = init_home(settings, force=force)
    for path in created:
        console.print(f"[green]✓[/green] {path}")
    console.print(f"Arbeitsordner: [bold]{settings.home}[/bold] – weiter mit [bold]jobslop[/bold]")


@app.command("install-browser")
def install_browser() -> None:
    """Chromium für Playwright installieren (macht auch die Einrichtung im Dashboard)."""
    import subprocess

    code = subprocess.call([sys.executable, "-m", "playwright", "install", "chromium"])
    raise typer.Exit(code)


@app.command("import")
def import_cmd(
    file: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="JSON-Datei mit Stellen")],
) -> None:
    """Stellen aus einer JSON-Datei importieren (Format: docs/configuration.md)."""
    from .importer import import_jobs

    r = rt()
    created, applied = import_jobs(r.settings.db_path, file, r.config)
    console.print(f"[green]✓[/green] {created} Stellen importiert, {applied} als 'schon beworben' markiert")


@app.command()
def doctor() -> None:
    """Prüft Profil, Dokumente, Claude Code (Abo-Login), Browser und Datenbank."""
    import os

    from .cvtext import cv_text
    from .llm import check_login

    r = rt()
    ok = True

    def line(good: bool, text: str, hint: str = "") -> None:
        nonlocal ok
        ok &= good
        console.print(
            f"{'[green]✓' if good else '[red]✗'}[/] {text}"
            + (f"  [dim]{hint}[/dim]" if hint and not good else "")
        )

    line(
        r.settings.profile_path.exists(),
        f"Profil: {r.settings.profile_path}",
        "`jobslop` starten → Einrichtung",
    )
    missing = r.profile.missing_fields()
    line(
        not missing,
        "Profil vollständig" if not missing else f"Profil: fehlt {', '.join(missing)}",
        "profile.yaml ergänzen – fehlende Angaben fragt der Agent sonst im Formular nach",
    )
    cv = r.profile.cv_path(r.settings.profile_path.parent)
    line(bool(cv and cv.exists()), f"Lebenslauf: {cv}", "Pfad in profile.yaml → documents.cv")
    if cv and cv.exists():
        chars = len(cv_text(cv))
        console.print(
            f"  [dim]Lebenslauf-Text: {chars} Zeichen"
            + (" (Bild-PDF – Claude liest die Datei bei jedem Schritt, langsamer)" if not chars else "")
            + "[/dim]"
        )
    login = check_login(r.settings)
    line(
        login.ok,
        login.message,
        "Installation: https://code.claude.com · danach `claude` starten und einloggen",
    )
    if os.environ.get("ANTHROPIC_API_KEY"):
        console.print(
            "  [dim]Hinweis: ANTHROPIC_API_KEY ist gesetzt – jobslop entfernt ihn für Claude-Aufrufe, "
            "damit nur das Abo genutzt wird.[/dim]"
        )
    line(r.settings.search_path.exists(), f"Suchkonfiguration: {r.settings.search_path}")
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            b.close()
        line(True, "Chromium startet")
    except Exception as exc:
        line(False, f"Chromium: {exc!s:.120}", "uv run playwright install chromium")
    with session_scope(r.settings.db_path) as s:
        jobs = s.scalar(select(func.count(Job.id))) or 0
        apps = s.scalar(select(func.count(Application.id))) or 0
    line(True, f"Datenbank: {jobs} Stellen, {apps} Bewerbungen ({r.settings.db_path})")
    console.print(
        f"\nClaude Code (Abo): {r.settings.llm_model} (Formulare), {r.settings.llm_model_fast} (Bewertung) · "
        f"parallel {r.settings.claude_parallel} · Modus: {r.settings.apply_mode}"
    )
    raise typer.Exit(0 if ok else 1)


# --------------------------------------------------------------------------- profile


@profile_app.command("show")
def profile_show() -> None:
    """Profil so anzeigen, wie es der Agent sieht."""
    console.print(rt().profile.to_prompt())


@profile_app.command("import-cv")
def profile_import_cv(
    cv: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="Lebenslauf als PDF")],
    overwrite: Annotated[bool, typer.Option(help="Vorhandene Werte überschreiben")] = False,
) -> None:
    """Lebenslauf mit Claude auslesen und ins Profil übernehmen (Backup: profile.yaml.bak)."""
    from .cvimport import import_cv

    r = rt()
    llm = need_claude(r)
    with console.status("Claude liest den Lebenslauf …"):
        profile = asyncio.run(import_cv(llm, cv.resolve(), r.profile, overwrite=overwrite))
    if r.settings.profile_path.exists():
        r.settings.profile_path.with_suffix(".yaml.bak").write_text(
            r.settings.profile_path.read_text(encoding="utf-8"), encoding="utf-8"
        )
    profile.save(r.settings.profile_path)
    console.print(f"[green]✓[/green] Profil aktualisiert: {r.settings.profile_path}")
    if missing := profile.missing_fields():
        console.print(f"[yellow]Noch offen:[/yellow] {', '.join(missing)}")


# --------------------------------------------------------------------------- crawl & history


@app.command()
def crawl(
    source: Annotated[
        list[str] | None, typer.Option("--source", "-s", help="Nur diese Quellen (Präfix, z. B. greenhouse)")
    ] = None,
    enrich: Annotated[bool, typer.Option(help="Neue/geänderte Stellen mit Claude bewerten")] = True,
    browser: Annotated[bool, typer.Option(help="Generische Karriereseiten im Browser rendern")] = True,
) -> None:
    """Alle Quellen neu abfragen, Liste aktualisieren und Änderungen in der History speichern."""
    from .crawl.pipeline import run_crawl

    r = rt()
    llm = None
    if enrich or (browser and r.config.sources.generic):
        from .llm import check_login

        login = check_login(r.settings)
        if login.ok:
            llm = r.llm()
        else:
            console.print(
                f"[yellow]{escape(login.message)} – crawle ohne Bewertung und ohne generische Karriereseiten.[/yellow]"
            )
    with console.status("Crawle Quellen …"):
        report = asyncio.run(
            run_crawl(
                r.settings,
                r.config,
                only=source,
                llm=llm,
                profile=r.profile,
                enrich=enrich,
                use_browser=browser,
            )
        )
    console.print(
        f"[bold]Crawl #{report.run_id}[/bold]: {report.fetched} Stellen abgefragt, {report.kept} passen zu den Filtern"
    )
    console.print(
        f"  [green]+{len(report.new)} neu[/green]  [cyan]~{len(report.updated)} geändert[/cyan]  "
        f"[yellow]↺{len(report.reopened)} wieder offen[/yellow]  [red]−{len(report.closed)} geschlossen[/red]  "
        f"⇄{len(report.merged_seeds)} Startlisten-Einträge auf Firmen-URL umgestellt"
    )
    if report.rejected.get("Dublette"):
        console.print(f"  [dim]{report.rejected['Dublette']} Dubletten aus Jobbörsen übersprungen[/dim]")
    if report.enrich_skipped:
        console.print(
            f"  [dim]{report.enrich_skipped} neue Stellen nur nach Regeln bewertet (Abo schonen) – "
            "Claude-Bewertung später mit `jobslop jobs enrich`[/dim]"
        )
    if report.errors:
        console.print(f"[yellow]{len(report.errors)} Quellen mit Fehlern:[/yellow]")
        for err in report.errors[:15]:
            console.print(f"  [dim]{escape(err[:160])}[/dim]")
    if report.new:
        _print_jobs(report.new, title="Neue Stellen")


@app.command()
def history(
    run_id: Annotated[int | None, typer.Argument(help="Crawl-Lauf anzeigen")] = None,
    limit: Annotated[int, typer.Option(help="Anzahl Läufe")] = 15,
) -> None:
    """Crawl-Läufe und ihre Änderungen (neu, geändert, geschlossen)."""
    r = rt()
    with session_scope(r.settings.db_path) as s:
        if run_id is None:
            t = Table(title="Crawl-History")
            for col in (
                "#",
                "Start",
                "Status",
                "abgefragt",
                "passend",
                "neu",
                "geändert",
                "geschlossen",
                "Fehler",
            ):
                t.add_column(col)
            for run in s.execute(select(CrawlRun).order_by(CrawlRun.id.desc()).limit(limit)).scalars():
                st = run.stats or {}
                t.add_row(
                    str(run.id),
                    run.started_at.strftime("%d.%m.%Y %H:%M"),
                    run.status,
                    str(st.get("fetched", "")),
                    str(st.get("kept", "")),
                    str(st.get("new", "")),
                    str(st.get("updated", "")),
                    str(st.get("closed", "")),
                    str(len(run.errors or [])),
                )
            console.print(t)
            return
        snaps = (
            s.execute(
                select(JobSnapshot).where(
                    JobSnapshot.crawl_run_id == run_id, JobSnapshot.change != "unchanged"
                )
            )
            .scalars()
            .all()
        )
        t = Table(title=f"Änderungen in Crawl #{run_id}")
        for col in ("Änderung", "Job", "Firma", "Titel", "Details"):
            t.add_column(col, overflow="fold")
        for sn in snaps:
            t.add_row(
                sn.change,
                str(sn.job_id),
                sn.job.company,
                sn.title,
                json.dumps(sn.diff, ensure_ascii=False) if sn.diff else "",
            )
        console.print(t)


# --------------------------------------------------------------------------- jobs


def _job_query(
    status: str,
    category: list[str] | None,
    where: str | None,
    level: str | None,
    search: str | None,
    min_fit: int,
    include_stretch: bool,
):
    q = select(Job)
    if status != "all":
        q = q.where(Job.status == status)
    if category:
        q = q.where(Job.category.in_(category))
    if where == "B":
        q = q.where(Job.where.in_(["B", "BR"]))
    elif where == "R":
        q = q.where(Job.where.in_(["R", "BR"]))
    if level:
        q = q.where(Job.level == level)
    elif not include_stretch:
        q = q.where(Job.level != "S")
    if search:
        like = f"%{search}%"
        q = q.where(
            Job.title.ilike(like)
            | Job.company.ilike(like)
            | Job.notes.ilike(like)
            | Job.description.ilike(like)
        )
    if min_fit:
        q = q.where(Job.fit >= min_fit)
    return q.order_by(Job.score.desc(), Job.company)


def _print_jobs(ids: list[int] | None = None, rows: list[Job] | None = None, title: str = "Stellen") -> None:
    r = rt()
    with session_scope(r.settings.db_path) as s:
        if rows is None:
            rows = list(
                s.execute(select(Job).where(Job.id.in_(ids or [])).order_by(Job.score.desc())).scalars()
            )
        # In schmalen Terminals bekäme der Titel sonst nur ein Zeichen pro Zeile.
        compact = console.width < 110
        t = Table(title=f"{title} ({len(rows)})", expand=True)
        columns = [
            ("ID", {"justify": "right", "no_wrap": True}),
            ("Score", {"justify": "right", "no_wrap": True}),
            ("Rolle", {"no_wrap": True}),
            ("Level", {"no_wrap": True}),
            ("Firma", {"overflow": "fold", "min_width": 8}),
            ("Titel", {"overflow": "fold", "ratio": 3, "min_width": 20}),
            ("Ort", {"no_wrap": True}),
            ("Stack", {"no_wrap": True}),
            ("Status", {"no_wrap": True}),
        ]
        keep = {"ID", "Score", "Firma", "Titel", "Status"} if compact else {c for c, _ in columns}
        for col, kw in columns:
            if col in keep:
                t.add_column(col, **kw)
        for j in rows:
            j = s.merge(j)
            st = _app_status(j)
            cells = {
                "ID": str(j.id),
                "Score": f"{j.score:.1f}",
                "Rolle": f"[{CAT_STYLE.get(j.category, 'white')}]{j.category}[/]",
                "Level": LEVEL_LABEL.get(j.level, j.level),
                "Firma": j.company,
                "Titel": j.title,
                "Ort": _where(j.where) + (f" · {j.workplace}" if j.workplace else ""),
                "Stack": "●" * j.fit + "○" * (3 - j.fit),
                "Status": f"[{STATUS_STYLE.get(st, 'white')}]{st}[/]"
                if st
                else ("[dim]geschlossen[/dim]" if j.status == "closed" else ""),
            }
            t.add_row(*(cells[col] for col, _ in columns if col in keep))
    console.print(t)
    if compact:
        console.print(
            "[dim]Schmales Fenster: Rolle, Level, Ort und Stack ausgeblendet – Fenster breiter ziehen.[/dim]"
        )


@jobs_app.command("list")
def jobs_list(
    category: Annotated[
        list[str] | None, typer.Option("--category", "-c", help="SRE, Platform, DevOps, Cloud, System")
    ] = None,
    where: Annotated[str | None, typer.Option(help="B = Berlin, R = Remote")] = None,
    level: Annotated[str | None, typer.Option(help="J, M, O oder S")] = None,
    search: Annotated[str | None, typer.Option("--search", "-q")] = None,
    status: Annotated[str, typer.Option(help="open, closed oder all")] = "open",
    min_fit: Annotated[int, typer.Option(help="Mindest-Stack-Match 1–3")] = 0,
    stretch: Annotated[bool, typer.Option(help="Stretch-Rollen anzeigen")] = False,
    todo: Annotated[bool, typer.Option(help="Nur Stellen ohne Bewerbung")] = False,
    top: Annotated[int, typer.Option(help="Nur die besten N")] = 0,
) -> None:
    """Stellen nach Priorität anzeigen."""
    r = rt()
    with session_scope(r.settings.db_path) as s:
        rows = list(s.execute(_job_query(status, category, where, level, search, min_fit, stretch)).scalars())
        if todo:
            rows = [j for j in rows if not j.applications]
        if top:
            rows = rows[:top]
    _print_jobs(rows=rows)


@jobs_app.command("show")
def jobs_show(job_id: int) -> None:
    """Details, History und Bewerbungen einer Stelle."""
    r = rt()
    with session_scope(r.settings.db_path) as s:
        j = s.get(Job, job_id)
        if j is None:
            raise typer.BadParameter("Unbekannte Job-ID")
        console.rule(f"[bold]{j.company}[/bold] · {j.title}")
        console.print(
            f"ID {j.id} · {j.category} · {LEVEL_LABEL.get(j.level)} · {_where(j.where)} {j.workplace} · "
            f"Stack {j.fit}/3 · Score {j.score} · Status {j.status}\nURL: {j.url}"
        )
        if j.apply_url:
            console.print(f"Bewerben: {j.apply_url}")
        if j.alt_urls:
            console.print("Weitere: " + ", ".join(j.alt_urls))
        if j.notes:
            console.print(f"[dim]{escape(j.notes)}[/dim]")
        if j.enrichment:
            e = j.enrichment
            console.print(
                f"\n[bold]Bewertung:[/bold] {e.get('summary', '')}\nPassung: {e.get('fit_reason', '')}\n"
                f"Mindestjahre: {e.get('required_years')} · Deutsch nötig: {e.get('german_required')} · "
                f"Hinweise: {', '.join(e.get('red_flags', [])) or '–'}"
            )
        if j.description:
            console.print("\n" + escape(j.description[:1500]) + (" …" if len(j.description) > 1500 else ""))
        console.print("\n[bold]History[/bold]")
        for sn in j.snapshots:
            console.print(
                f"  {sn.seen_at:%d.%m.%Y %H:%M}  {sn.change}  {json.dumps(sn.diff, ensure_ascii=False) if sn.diff else ''}"
            )
        if j.applications:
            console.print("\n[bold]Bewerbungen[/bold]")
            for a in j.applications:
                console.print(
                    f"  #{a.id} {a.started_at:%d.%m.%Y %H:%M} [{STATUS_STYLE.get(a.status, 'white')}]{a.status}[/] "
                    f"{a.confirmation or a.error}"[:220]
                )


@jobs_app.command("enrich")
def jobs_enrich(
    all_open: Annotated[
        bool, typer.Option("--all", help="Alle offenen Stellen mit Beschreibung neu bewerten")
    ] = False,
    max_jobs: Annotated[
        int, typer.Option("--max", help="Höchstens so viele Stellen (die besten zuerst; 6 pro Claude-Aufruf)")
    ] = 60,
) -> None:
    """Stellen mit Claude einordnen (echtes Level aus den Anforderungen, Stack-Match, Hinweise)."""
    from .crawl.pipeline import enrich_jobs

    r = rt()
    llm = need_claude(r)
    with session_scope(r.settings.db_path) as s:
        rows = s.execute(
            select(Job).where(Job.status == "open", Job.description != "").order_by(Job.score.desc())
        ).scalars()
        ids = [j.id for j in rows if all_open or not j.enrichment][: max(0, max_jobs)]
    with console.status(f"Bewerte {len(ids)} Stellen …"):
        n = asyncio.run(enrich_jobs(r.settings, r.config, llm, r.profile, ids))
    console.print(f"[green]✓[/green] {n} Stellen bewertet")


# --------------------------------------------------------------------------- queue


@queue_app.command("add")
def queue_add(
    job_ids: Annotated[list[int] | None, typer.Argument()] = None,
    top: Annotated[int, typer.Option(help="Die besten N offenen Stellen ohne Bewerbung einreihen")] = 0,
    category: Annotated[list[str] | None, typer.Option("--category", "-c")] = None,
    where: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Stellen für die nächste Bewerbungsrunde einreihen."""
    from .queueing import pick_top, queue_jobs

    r = rt()
    ids = list(job_ids or [])
    if top:
        ids += pick_top(r.settings.db_path, r.config, top, categories=category, where=where)
    added, skipped = queue_jobs(r.settings.db_path, r.config, ids)
    console.print(f"[green]✓[/green] {len(added)} eingereiht: {', '.join(map(str, added))}")
    for line in skipped:
        console.print(f"  [dim]übersprungen {line}[/dim]")


@queue_app.command("list")
def queue_list() -> None:
    """Warteschlange anzeigen."""
    r = rt()
    with session_scope(r.settings.db_path) as s:
        rows = list(s.execute(select(Job).where(Job.queued).order_by(Job.score.desc())).scalars())
    _print_jobs(rows=rows, title="Warteschlange")


@queue_app.command("remove")
def queue_remove(job_ids: list[int]) -> None:
    r = rt()
    with session_scope(r.settings.db_path) as s:
        for jid in job_ids:
            if j := s.get(Job, jid):
                j.queued = False
    console.print("[green]✓[/green] entfernt")


@queue_app.command("clear")
def queue_clear() -> None:
    r = rt()
    with session_scope(r.settings.db_path) as s:
        for j in s.execute(select(Job).where(Job.queued)).scalars():
            j.queued = False
    console.print("[green]✓[/green] Warteschlange geleert")


# --------------------------------------------------------------------------- apply


@app.command()
def apply(
    job_ids: Annotated[list[int] | None, typer.Argument(help="Job-IDs; ohne Angabe: --queue")] = None,
    queue: Annotated[bool, typer.Option("--queue", help="Alle eingereihten Stellen abarbeiten")] = False,
    mode: Annotated[str | None, typer.Option(help="review (Standard) | auto | dry-run")] = None,
    max_count: Annotated[
        int | None, typer.Option("--max", help="Höchstens so viele Bewerbungen in diesem Lauf")
    ] = None,
    headless: Annotated[
        bool, typer.Option(help="Browser unsichtbar (nur mit --unattended sinnvoll)")
    ] = False,
    offline: Annotated[bool, typer.Option(help="Ohne Claude, nur Regel-Planer für Standardfelder")] = False,
    unattended: Annotated[bool, typer.Option(help="Keine Rückfragen; offene Punkte werden geparkt")] = False,
    via_dashboard: Annotated[
        bool, typer.Option(help="Rückfragen im Dashboard beantworten statt im Terminal")
    ] = False,
    force: Annotated[bool, typer.Option(help="Firmen-Limit und Offen-Status ignorieren")] = False,
) -> None:
    """Bewerbungen ausfüllen und – je nach Modus – absenden."""
    from .apply.interact import ConsoleInteractor, DbInteractor, UnattendedInteractor

    r = rt()
    mode = mode or r.settings.apply_mode
    if mode not in ("review", "auto", "dry-run"):
        raise typer.BadParameter("mode muss review, auto oder dry-run sein")
    with session_scope(r.settings.db_path) as s:
        ids = list(job_ids or [])
        if queue or not ids:
            ids += [
                j.id for j in s.execute(select(Job).where(Job.queued).order_by(Job.score.desc())).scalars()
            ]
    if not ids:
        console.print(
            "Nichts zu tun. Stellen einreihen: [bold]jobslop queue add --top 10[/bold] oder im Dashboard"
        )
        raise typer.Exit()
    if not offline:
        from .llm import check_login

        login = check_login(r.settings)
        if not login.ok:
            console.print(f"[red]{escape(login.message)}[/red]")
            console.print("Ohne Claude geht nur der Regel-Planer für Standardfelder: [bold]--offline[/bold]")
            raise typer.Exit(1)
    if unattended:
        interactor = UnattendedInteractor()
    elif via_dashboard:
        interactor = DbInteractor(r.settings.db_path, timeout_s=r.settings.user_wait_timeout_s)
    else:
        interactor = ConsoleInteractor(console)
    limit = max_count or r.config.limits.max_applications_per_run
    _run_apply(r, ids, mode, limit, interactor, headless=headless, offline=offline, force=force)


def _run_apply(
    r: Runtime,
    ids: list[int],
    mode: str,
    limit: int,
    interactor,
    *,
    headless: bool = False,
    offline: bool = False,
    force: bool = False,
) -> None:
    from .apply.engine import BrowserSession, run_batch

    console.print(
        f"[bold]{len(ids)} Stelle(n)[/bold] · Modus [bold]{mode}[/bold] · max. {limit} · "
        f"{'Regel-Planer' if offline else r.settings.llm_model}"
    )

    def on_result(o) -> None:
        style = STATUS_STYLE.get(o.status, "white")
        console.print(
            f"[{style}]● {o.status}[/] Job #{o.job_id}"
            + (f" (Bewerbung #{o.application_id})" if o.application_id else "")
            + f" – {escape(o.message[:200])}"
        )

    async def main() -> None:
        async with BrowserSession(r.settings, headless=headless) as browser:
            engine = r.engine(
                browser=browser,
                interactor=interactor,
                mode=mode,
                offline=offline,  # type: ignore[arg-type]
                on_event=lambda m: console.print(f"  [dim]{escape(m)}[/dim]"),
            )
            outcomes = []
            if force:
                for jid in ids:
                    outcomes.append(o := await engine.apply(jid, force=True))
                    on_result(o)
                    if o.status == "paused":
                        break
            else:
                outcomes = await run_batch(
                    engine,
                    ids,
                    max_count=limit,
                    min_delay=r.config.limits.min_delay_seconds,
                    on_result=on_result,
                )
            if engine.llm:
                u = engine.llm.usage
                console.print(
                    f"[dim]Claude Code (Abo): {u.calls} Aufrufe in {u.seconds:.0f}s · {u.input_tokens:,} Input- "
                    f"(+{u.cache_read_tokens:,} aus Cache), {u.output_tokens:,} Output-Tokens[/dim]"
                )
            if any(o.status == "paused" for o in outcomes):
                console.print(
                    "[magenta]Claude-Nutzungslimit erreicht – Rest bleibt in der Warteschlange. "
                    "Später einfach `jobslop apply --queue` erneut starten.[/magenta]"
                )

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Abgebrochen.[/yellow]")


@app.command()
def login(url: str) -> None:
    """Browser mit dem jobslop-Profil öffnen, um dich einmalig bei einem Bewerbungsportal einzuloggen."""
    from .apply.engine import BrowserSession

    r = rt()

    async def main() -> None:
        async with BrowserSession(r.settings, headless=False) as b:
            page = await b.new_page()
            await page.goto(url)
            await asyncio.to_thread(input, "Einloggen, dann hier Enter drücken … ")

    asyncio.run(main())
    console.print("[green]✓[/green] Login im jobslop-Browserprofil gespeichert")


# --------------------------------------------------------------------------- applications


@apps_app.command("list")
def apps_list(
    status: Annotated[str | None, typer.Option(help="Nur diesen Status")] = None,
    limit: Annotated[int, typer.Option()] = 50,
) -> None:
    """Bewerbungen mit Status."""
    r = rt()
    with session_scope(r.settings.db_path) as s:
        q = select(Application).order_by(Application.id.desc()).limit(limit)
        if status:
            q = q.where(Application.status == status)
        t = Table(title="Bewerbungen", expand=True)
        for col in ("#", "Datum", "Status", "Job", "Firma", "Titel", "Hinweis"):
            t.add_column(col, overflow="fold")
        for a in s.execute(q).scalars():
            t.add_row(
                str(a.id),
                a.started_at.strftime("%d.%m.%y %H:%M"),
                f"[{STATUS_STYLE.get(a.status, 'white')}]{a.status}[/]",
                str(a.job_id),
                a.job.company,
                a.job.title,
                (a.error or a.confirmation or "")[:90],
            )
        console.print(t)
        counts = dict(s.execute(select(Application.status, func.count()).group_by(Application.status)).all())
    console.print("  ".join(f"{k}: {v}" for k, v in sorted(counts.items())))


@apps_app.command("show")
def apps_show(app_id: int) -> None:
    """Ablaufprotokoll einer Bewerbung."""
    r = rt()
    with session_scope(r.settings.db_path) as s:
        a = s.get(Application, app_id)
        if a is None:
            raise typer.BadParameter("Unbekannte Bewerbung")
        console.rule(f"Bewerbung #{a.id} · {a.job.company} · {a.job.title}")
        console.print(f"Status: {a.status} · Modus {a.mode} · Artefakte: {a.artifacts_dir}")
        for e in a.events:
            console.print(f"  {e.ts:%H:%M:%S} [bold]{e.kind}[/bold] {escape(e.message[:200])}")
        if a.open_questions:
            console.print("\n[yellow]Offene Fragen:[/yellow]")
            for q in a.open_questions:
                console.print(f"  • {q.get('label') or q.get('question')}  [dim]({q.get('why', '')})[/dim]")
            console.print(
                'Antworten: [bold]jobslop answers add "<Frage>" "<Antwort>"[/bold] oder im Dashboard, '
                "dann erneut [bold]jobslop apply <Job-ID>[/bold]"
            )


@app.command()
def mark(
    status: Annotated[str, typer.Argument(help="applied | interview | rejected | offer")],
    job_id: int,
    note: Annotated[str, typer.Option()] = "",
) -> None:
    """Status von Hand setzen, z. B. wenn du dich selbst beworben hast."""
    mapping = {"applied": "manual", "interview": "interview", "rejected": "rejected", "offer": "offer"}
    if status not in mapping:
        raise typer.BadParameter("applied, interview, rejected oder offer")
    r = rt()
    with session_scope(r.settings.db_path) as s:
        j = s.get(Job, job_id)
        if j is None:
            raise typer.BadParameter("Unbekannte Job-ID")
        last = j.applications[-1] if j.applications else None
        if (
            last
            and last.status in DONE_STATES | {"needs_review", "needs_input", "ready"}
            and status != "applied"
        ):
            last.status = mapping[status]
            last.confirmation = (last.confirmation + f" | {note}").strip(" |")
        else:
            s.add(
                Application(
                    job=j,
                    status=mapping[status],
                    origin="manual",
                    mode="manual",
                    submitted_at=utcnow(),
                    finished_at=utcnow(),
                    confirmation=note or "von Hand eingetragen",
                )
            )
        j.queued = False
    console.print(f"[green]✓[/green] Job #{job_id}: {status}")


# --------------------------------------------------------------------------- exclusions & answers


@exclude_app.command("add")
def exclude_add(
    kind: Annotated[str, typer.Argument(help="company | job | title | url")],
    value: str,
    reason: Annotated[str, typer.Option()] = "",
) -> None:
    """Etwas dauerhaft ausschließen (Firma, Job-ID, Titel-Regex, URL-Teil)."""
    if kind not in ("company", "job", "title", "url"):
        raise typer.BadParameter("company, job, title oder url")
    r = rt()
    with session_scope(r.settings.db_path) as s:
        s.add(Exclusion(kind=kind, value=value, reason=reason))
        if kind == "company":
            for j in s.execute(select(Job).where(Job.queued)).scalars():
                if value.lower() in j.company.lower():
                    j.queued = False
    console.print(f"[green]✓[/green] ausgeschlossen: {kind} = {value}")


@exclude_app.command("list")
def exclude_list() -> None:
    r = rt()
    with session_scope(r.settings.db_path) as s:
        t = Table(title="Ausschlüsse")
        for col in ("#", "Art", "Wert", "Grund", "seit"):
            t.add_column(col)
        for e in s.execute(select(Exclusion).order_by(Exclusion.id)).scalars():
            t.add_row(str(e.id), e.kind, e.value, e.reason, e.created_at.strftime("%d.%m.%Y"))
    console.print(t)


@exclude_app.command("remove")
def exclude_remove(exclusion_id: int) -> None:
    r = rt()
    with session_scope(r.settings.db_path) as s:
        if e := s.get(Exclusion, exclusion_id):
            s.delete(e)
    console.print("[green]✓[/green] entfernt")


@answers_app.command("list")
def answers_list() -> None:
    r = rt()
    with session_scope(r.settings.db_path) as s:
        t = Table(title="Antwortbank", expand=True)
        for col in ("#", "Frage", "Antwort"):
            t.add_column(col, overflow="fold")
        for a in s.execute(select(Answer).order_by(Answer.updated_at.desc())).scalars():
            t.add_row(str(a.id), a.question, a.answer)
    console.print(t)


@answers_app.command("add")
def answers_add(question: str, answer: str) -> None:
    from .profile import normalize_question

    r = rt()
    key = normalize_question(question)
    with session_scope(r.settings.db_path) as s:
        existing = s.execute(select(Answer).where(Answer.question_key == key)).scalars().first()
        if existing:
            existing.answer, existing.updated_at = answer, utcnow()
        else:
            s.add(Answer(question_key=key, question=question, answer=answer))
    console.print("[green]✓[/green] gespeichert")


@answers_app.command("remove")
def answers_remove(answer_id: int) -> None:
    r = rt()
    with session_scope(r.settings.db_path) as s:
        if a := s.get(Answer, answer_id):
            s.delete(a)
    console.print("[green]✓[/green] entfernt")


# --------------------------------------------------------------------------- dashboard & export


def _running_instance(host: str, port: int) -> bool:
    """Läuft auf dem Port schon ein jobslop-Dashboard?"""
    import httpx

    try:
        r = httpx.get(f"http://{host}:{port}/api/status", timeout=1.5)
        return r.status_code == 200 and "setup_completed" in r.json()
    except (httpx.HTTPError, ValueError):
        return False


def _port_free(host: str, port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex((host, port)) != 0


@app.command()
def start(
    port: Annotated[int | None, typer.Option(help="Port (Standard 8765)")] = None,
    open_browser: Annotated[
        bool, typer.Option("--open/--no-open", help="Dashboard im Standardbrowser öffnen")
    ] = True,
) -> None:
    """Dashboard starten (Standard, wenn `jobslop` ohne Befehl aufgerufen wird). Beim ersten Mal mit Einrichtung."""
    import threading
    import webbrowser

    import uvicorn

    from .web.app import create_app

    settings = get_settings()
    init_home(settings)
    r = rt()
    host = r.settings.dashboard_host
    port = port or r.settings.dashboard_port
    url = f"http://{host}:{port}"
    if _running_instance(host, port):
        console.print(f"jobslop läuft schon: [bold]{url}[/bold]")
        if open_browser:
            webbrowser.open(url)
        return
    while not _port_free(host, port):
        port += 1
    url = f"http://{host}:{port}"
    console.print(f"[bold]jobslop {__version__}[/bold] · Dashboard: [bold]{url}[/bold]  (Strg+C beendet)")
    if not r.settings.setup_completed:
        console.print("Erster Start – die Einrichtung öffnet sich im Browser.")
    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(r), host=host, port=port, log_level="warning")


@app.command()
def dashboard(
    port: Annotated[int | None, typer.Option(help="Port")] = None,
    open_browser: Annotated[bool, typer.Option("--open/--no-open")] = True,
) -> None:
    """Alias für `jobslop start`."""
    start(port=port, open_browser=open_browser)


@app.command()
def autopilot(
    apply_jobs: Annotated[bool, typer.Option("--apply/--no-apply", help="Nach dem Crawl bewerben")] = True,
    count: Annotated[int | None, typer.Option("--max", help="Höchstens so viele Bewerbungen")] = None,
) -> None:
    """Einmal Autopilot: crawlen, beste Stellen einreihen, unbeaufsichtigt bewerben (für Aufgabenplanung/cron)."""
    from .apply.interact import UnattendedInteractor
    from .autopilot import crawl_and_queue, record

    r = rt()
    s = r.settings
    count = count or s.autopilot_apply_max
    record(s, "autopilot", "Autopilot gestartet (Kommandozeile)")
    summary = asyncio.run(crawl_and_queue(r, queue_count=count if apply_jobs else 0))
    console.print(f"Crawl #{summary['run_id']}: {summary['new']} neu, {len(summary['queued'])} eingereiht")
    if apply_jobs and summary["queued"]:
        _run_apply(r, summary["queued"], s.autopilot_apply_mode, count, UnattendedInteractor(), headless=True)
    record(
        s,
        "autopilot",
        f"Autopilot fertig: {summary['new']} neu, {len(summary['queued'])} eingereiht",
        summary,
    )


@app.command()
def export(
    fmt: Annotated[str, typer.Option("--format", help="csv oder json")] = "csv",
    out: Annotated[Path | None, typer.Option(help="Zieldatei, sonst stdout")] = None,
) -> None:
    """Alle Stellen mit Bewerbungsstatus exportieren."""
    r = rt()
    with session_scope(r.settings.db_path) as s:
        rows = []
        for j in s.execute(select(Job).order_by(Job.score.desc())).scalars():
            rows.append(
                {
                    "id": j.id,
                    "company": j.company,
                    "title": j.title,
                    "category": j.category,
                    "level": j.level,
                    "where": j.where,
                    "workplace": j.workplace,
                    "fit": j.fit,
                    "score": j.score,
                    "status": j.status,
                    "application": _app_status(j),
                    "url": j.url,
                    "first_seen": j.first_seen.isoformat(),
                    "last_seen": j.last_seen.isoformat(),
                }
            )
    handle = out.open("w", encoding="utf-8", newline="") if out else sys.stdout
    if fmt == "json":
        json.dump(rows, handle, ensure_ascii=False, indent=1)
    else:
        w = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else ["id"])
        w.writeheader()
        w.writerows(rows)
    if out:
        handle.close()
        console.print(f"[green]✓[/green] {len(rows)} Zeilen → {out}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()

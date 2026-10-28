"""Rückkanal zum Menschen: Fragen stellen, Absenden freigeben, an den Menschen übergeben (CAPTCHA, Login)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt as RichPrompt
from rich.table import Table
from sqlalchemy import update

from ..db import Prompt, session_scope, utcnow
from .planner import OpenQuestion

Check = Callable[[], Awaitable[bool]]


class Interactor(Protocol):
    async def ask(self, app_id: int, title: str, questions: list[OpenQuestion]) -> dict[str, str] | None: ...

    async def confirm(
        self, app_id: int, title: str, rows: list[dict[str, Any]], screenshot: Path | None
    ) -> str: ...

    async def handoff(self, app_id: int, title: str, message: str, check: Check | None = None) -> bool: ...

    def info(self, message: str) -> None: ...


# --------------------------------------------------------------------------- Konsole


class ConsoleInteractor:
    """Interaktiv im Terminal. Der Browser läuft sichtbar daneben."""

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()

    def info(self, message: str) -> None:
        self.console.print(f"[dim]›[/dim] {message}")

    async def _input(self, prompt: str, default: str = "") -> str:
        return await asyncio.to_thread(
            RichPrompt.ask, prompt, default=default, console=self.console, show_default=bool(default)
        )

    async def ask(self, app_id: int, title: str, questions: list[OpenQuestion]) -> dict[str, str] | None:
        self.console.print(
            Panel.fit(
                f"[bold]{title}[/bold]\nDas Formular fragt etwas, das nicht in deinem Profil steht. "
                "Antworten landen in der Antwortbank und werden künftig wiederverwendet.\n"
                "Leer lassen = überspringen und die Bewerbung parken.",
                title="Rückfrage",
            )
        )
        answers: dict[str, str] = {}
        for q in questions:
            hint = f"\n  Optionen: {' | '.join(q.options[:20])}" if q.options else ""
            self.console.print(f"[bold cyan]?[/bold cyan] {q.question}[dim]  ({q.why}){hint}[/dim]")
            value = (await self._input("  Antwort")).strip()
            if not value:
                return None
            answers[q.field_id] = value
        return answers

    async def confirm(
        self, app_id: int, title: str, rows: list[dict[str, Any]], screenshot: Path | None
    ) -> str:
        table = Table(title=f"Vor dem Absenden · {title}", show_lines=False, expand=True)
        table.add_column("Feld", overflow="fold", ratio=2)
        table.add_column("Wert", overflow="fold", ratio=3)
        table.add_column("Quelle", ratio=1)
        for r in rows:
            conf = r.get("confidence", "")
            style = "yellow" if conf == "low" else ("" if conf == "high" else "cyan")
            table.add_row(
                r.get("label", "")[:90],
                str(r.get("value", ""))[:160],
                f"{r.get('source', '')} {conf}",
                style=style,
            )
        self.console.print(table)
        if screenshot:
            self.console.print(f"[dim]Screenshot: {screenshot}[/dim]")
        self.console.print(
            "Prüfe das Formular im Browserfenster. [bold]j[/bold] = absenden, "
            "[bold]m[/bold] = ich korrigiere/sende selbst, [bold]n[/bold] = nicht absenden"
        )
        answer = (await self._input("Absenden?", default="n")).strip().lower()
        return {"j": "submit", "y": "submit", "m": "manual"}.get(answer[:1], "reject")

    async def handoff(self, app_id: int, title: str, message: str, check: Check | None = None) -> bool:
        self.console.print(
            Panel.fit(
                f"{message}\n\nDrücke Enter, wenn du fertig bist (oder tippe 'abbrechen').",
                title=f"Du bist dran · {title}",
                border_style="yellow",
            )
        )
        for _ in range(3):
            answer = (await self._input("Fertig?", default="")).strip().lower()
            if answer.startswith("abb"):
                return False
            if check is None or await check():
                return True
            self.console.print(
                "[yellow]Ich erkenne den erwarteten Zustand noch nicht. Bitte prüfen und erneut Enter.[/yellow]"
            )
        return check is None or await check()


# --------------------------------------------------------------------------- Dashboard (über DB-Prompts)


class DbInteractor:
    """Legt Rückfragen in der Datenbank ab; das Dashboard beantwortet sie. Wartet mit Polling."""

    def __init__(self, db_path: Path, timeout_s: int = 900, poll_s: float = 1.5) -> None:
        self.db_path = db_path
        self.timeout_s = timeout_s
        self.poll_s = poll_s
        self.log: list[str] = []

    def info(self, message: str) -> None:
        self.log.append(message)

    def _create(self, app_id: int, kind: str, payload: dict[str, Any]) -> int:
        with session_scope(self.db_path) as s:
            p = Prompt(application_id=app_id, kind=kind, payload=payload)
            s.add(p)
            s.flush()
            return p.id

    def _state(self, prompt_id: int) -> tuple[str, dict[str, Any]]:
        with session_scope(self.db_path) as s:
            p = s.get(Prompt, prompt_id)
            return (p.status, dict(p.response or {})) if p else ("gone", {})

    def _close(self, prompt_id: int, status: str, response: dict[str, Any] | None = None) -> bool:
        """Schließt die Rückfrage nur, solange sie offen ist. Dashboard und Lauf schreiben gleichzeitig – genau einer
        gewinnt, sonst ginge z. B. eine Freigabe in der letzten Sekunde der Wartezeit verloren."""
        values: dict[str, Any] = {"status": status}
        if response is not None:
            values |= {"response": response, "answered_at": utcnow()}
        with session_scope(self.db_path) as s:
            done = s.connection().execute(
                update(Prompt).where(Prompt.id == prompt_id, Prompt.status == "open").values(**values)
            )
            return bool(done.rowcount)

    async def _wait(self, prompt_id: int, check: Check | None = None) -> dict[str, Any] | None:
        deadline = time.monotonic() + self.timeout_s  # inklusive der Zeit für check() und die Datenbank
        while True:
            status, response = self._state(prompt_id)
            if status == "answered":
                return response
            if status != "open":  # vom Dashboard geschlossen (Lauf gestoppt oder abgestürzt)
                return None
            if check is not None and await check() and self._close(prompt_id, "answered", {"auto": True}):
                return {"auto": True}
            if time.monotonic() >= deadline:
                if self._close(prompt_id, "expired"):
                    return None
                continue  # gerade eben beantwortet – die Antwort gilt
            await asyncio.sleep(self.poll_s)

    async def ask(self, app_id: int, title: str, questions: list[OpenQuestion]) -> dict[str, str] | None:
        pid = self._create(
            app_id, "questions", {"title": title, "questions": [q.model_dump() for q in questions]}
        )
        resp = await self._wait(pid)
        if not resp or resp.get("skip"):
            return None
        answers = {k: v for k, v in (resp.get("answers") or {}).items() if str(v).strip()}
        return answers if len(answers) == len(questions) else None

    async def confirm(
        self, app_id: int, title: str, rows: list[dict[str, Any]], screenshot: Path | None
    ) -> str:
        pid = self._create(
            app_id, "confirm", {"title": title, "rows": rows, "screenshot": str(screenshot or "")}
        )
        resp = await self._wait(pid)
        # Keine Antwort in der Wartezeit: wie Ablehnen nichts absenden – aber als solches erkennbar melden
        return "timeout" if resp is None else resp.get("decision", "reject")

    async def handoff(self, app_id: int, title: str, message: str, check: Check | None = None) -> bool:
        pid = self._create(app_id, "handoff", {"title": title, "message": message})
        resp = await self._wait(pid, check)
        if resp is None:
            return False
        if resp.get("abort"):
            return False
        return check is None or await check() or bool(resp.get("auto") or resp.get("done"))


# --------------------------------------------------------------------------- unbeaufsichtigt


class UnattendedInteractor:
    """Für nächtliche Läufe: keine Rückfragen. Offene Punkte führen zu 'needs_input' bzw. 'needs_review'."""

    def info(self, message: str) -> None:
        pass

    async def ask(self, app_id: int, title: str, questions: list[OpenQuestion]) -> dict[str, str] | None:
        return None

    async def confirm(
        self, app_id: int, title: str, rows: list[dict[str, Any]], screenshot: Path | None
    ) -> str:
        return "reject"

    async def handoff(self, app_id: int, title: str, message: str, check: Check | None = None) -> bool:
        return False

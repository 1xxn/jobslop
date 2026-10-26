"""Systemzustand für Einrichtung und Doctor: Claude Code, Browser, Profil, Lebenslauf."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .config import Settings
from .llm import LoginCheck, check_login, find_claude
from .profile import Profile

log = logging.getLogger(__name__)

CLAUDE_INSTALL = {
    "win32": "irm https://claude.ai/install.ps1 | iex",
    "default": "curl -fsSL https://claude.ai/install.sh | bash",
}


@dataclass
class Check:
    ok: bool
    message: str
    detail: dict[str, Any] = field(default_factory=dict)


class _Cache:
    """Teure Prüfungen (Claude startet ~2 s) kurz zwischenspeichern."""

    def __init__(self, ttl: float) -> None:
        self.ttl = ttl
        self.value: Any = None
        self.at = 0.0

    def get(self) -> Any:
        return self.value if self.value is not None and time.monotonic() - self.at < self.ttl else None

    def set(self, value: Any) -> Any:
        self.value, self.at = value, time.monotonic()
        return value


_claude_cache = _Cache(ttl=45)
_browser_cache = _Cache(ttl=600)


def claude_status(settings: Settings, *, refresh: bool = False) -> LoginCheck:
    if not refresh and (cached := _claude_cache.get()) is not None:
        return cached
    return _claude_cache.set(check_login(settings))


def claude_installed(settings: Settings) -> bool:
    try:
        find_claude(settings.claude_bin)
        return True
    except Exception:
        return False


async def browser_status(*, refresh: bool = False) -> Check:
    """Ist Playwrights Chromium installiert? (ohne den Browser zu starten)"""
    if not refresh and (cached := _browser_cache.get()) is not None:
        return cached
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            path = Path(p.chromium.executable_path)
        ok = await asyncio.to_thread(path.exists)
        result = Check(ok, "Chromium bereit" if ok else "Chromium fehlt noch", {"path": str(path)})
    except Exception as exc:
        result = Check(False, f"Playwright nicht verfügbar: {exc}")
    return _browser_cache.set(result)


class BrowserInstaller:
    """Installiert Chromium im Hintergrund (``playwright install chromium``) und merkt sich die Ausgabe."""

    def __init__(self) -> None:
        self.proc: asyncio.subprocess.Process | None = None
        self.log: list[str] = []
        self.returncode: int | None = None
        self._pump_task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self.proc is not None and self.returncode is None

    async def start(self) -> None:
        if self.running:
            return
        self.log, self.returncode = [], None
        self.proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "playwright",
            "install",
            "chromium",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        self._pump_task = asyncio.create_task(self._pump())

    async def _pump(self) -> None:
        assert self.proc and self.proc.stdout
        async for raw in self.proc.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip()
            if line:
                self.log = [*self.log[-30:], line]
        self.returncode = await self.proc.wait()
        _browser_cache.value = None

    def state(self) -> dict[str, Any]:
        return {"running": self.running, "returncode": self.returncode, "log": self.log[-8:]}


def profile_status(settings: Settings, profile: Profile) -> dict[str, Any]:
    cv = profile.cv_path(settings.profile_path.parent)
    return {
        "exists": settings.profile_path.exists(),
        "missing": profile.missing_fields(),
        "cv": str(cv) if cv else "",
        "cv_ok": bool(cv and cv.exists()),
        "name": profile.personal.full_name,
    }


def open_terminal(command: list[str], title: str = "jobslop") -> bool:
    """Öffnet ein sichtbares Terminalfenster mit einem festen Befehl (z. B. Claude-Login). Kein Shell-Input von außen."""
    try:
        if sys.platform == "win32":
            line = subprocess.list2cmdline(command)
            subprocess.Popen(["cmd.exe", "/c", "start", title, "cmd.exe", "/k", line])
            return True
        line = shlex.join(command)
        if sys.platform == "darwin":
            script = f'tell application "Terminal" to do script "{line}"'
            subprocess.Popen(["osascript", "-e", script, "-e", 'tell application "Terminal" to activate'])
            return True
        for term in ("x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal", "xterm"):
            if shutil.which(term):
                args = [term, "--", *command] if term == "gnome-terminal" else [term, "-e", line]
                subprocess.Popen(args)
                return True
    except OSError as exc:
        log.warning("Terminal ließ sich nicht öffnen: %s", exc)
    return False


def open_claude_login(settings: Settings) -> dict[str, Any]:
    """Startet `claude` in einem Terminal (Login per Browser). Ohne Claude Code: Installationsbefehl zurückgeben."""
    install = CLAUDE_INSTALL.get(sys.platform, CLAUDE_INSTALL["default"])
    try:
        cmd = find_claude(settings.claude_bin)
    except Exception:
        return {"opened": False, "installed": False, "install_command": install}
    opened = open_terminal([*cmd], title="Claude Code Login")
    _claude_cache.value = None
    return {"opened": opened, "installed": True, "install_command": install, "command": "claude"}


def open_claude_install() -> dict[str, Any]:
    if sys.platform == "win32":
        command = ["powershell", "-NoExit", "-Command", CLAUDE_INSTALL["win32"]]
    else:
        command = ["bash", "-lc", CLAUDE_INSTALL["default"] + "; exec $SHELL"]
    return {"opened": open_terminal(command, title="Claude Code installieren")}


def open_folder(path: Path) -> bool:
    with contextlib.suppress(OSError):
        if sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
            return True
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])
        return True
    return False


async def system_report(settings: Settings, profile: Profile, *, refresh: bool = False) -> dict[str, Any]:
    login = await asyncio.to_thread(claude_status, settings, refresh=refresh)
    browser = await browser_status(refresh=refresh)
    return {
        "claude": {
            "installed": claude_installed(settings),
            "ok": login.ok,
            "message": login.message,
            "method": login.method,
            "version": login.version,
            "account": login.raw.get("email") or "",
            "plan": login.raw.get("subscriptionType") or "",
        },
        "browser": asdict(browser),
        "profile": profile_status(settings, profile),
        "home": str(settings.home),
        "setup_completed": settings.setup_completed,
    }

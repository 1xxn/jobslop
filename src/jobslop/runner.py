"""Bewerbungsläufe als eigener Prozess (``jobslop apply --via-dashboard``).

Ein separater Prozess hält Browser und Claude-Aufrufe vom Dashboard-Server fern: hängt eine Seite, bleibt das
Dashboard bedienbar, und „Stopp“ beendet den Lauf sauber.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import ApplyMode, Settings, ensure_not_demo
from .db import utcnow


def process_group() -> dict[str, Any]:
    """Popen-Argumente: Kindprozess in eigener Prozessgruppe, damit „Stopp“ den ganzen Baum beenden kann."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def kill_tree(proc: subprocess.Popen[Any], timeout: float = 10) -> None:
    """Beendet den Prozess samt Kindern (Playwright-Treiber, Chromium). Sonst bleiben unter Windows Browser
    zurück, die das Browserprofil sperren – der nächste Lauf startet dann nicht."""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGTERM)
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        if sys.platform == "win32":
            proc.kill()
        else:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=5)


class Runner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.proc: subprocess.Popen[bytes] | None = None
        self.started_at: datetime | None = None
        self.finished_at: datetime | None = None
        self.label = ""
        self.mode = ""
        self.returncode: int | None = None
        self.stopped = False  # per „Stopp“ beendet – ein Exit-Code ungleich 0 ist dann kein Absturz

    @property
    def log_path(self) -> Path:
        return self.settings.home / "runner.log"

    @property
    def active(self) -> bool:
        if self.proc is None:
            return False
        code = self.proc.poll()
        if code is not None and self.returncode is None:
            self.returncode, self.finished_at = code, utcnow()
        return code is None

    def start(
        self,
        job_ids: list[int] | None = None,
        *,
        mode: ApplyMode,
        max_count: int | None = None,
        force: bool = False,
        unattended: bool = False,
        label: str = "",
    ) -> bool:
        if self.active:
            return False
        ensure_not_demo(self.settings, "Bewerben")
        args = [sys.executable, "-m", "jobslop", "apply", "--mode", mode]
        args += ["--unattended"] if unattended else ["--via-dashboard"]
        args += [str(i) for i in job_ids] if job_ids else ["--queue"]
        if max_count:
            args += ["--max", str(max_count)]
        if force:
            args.append("--force")
        env = os.environ | {
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
            "JOBSLOP_HOME": str(self.settings.home),
            "COLUMNS": "120",
            "NO_COLOR": "1",
            "TERM": "dumb",
        }
        self.settings.home.mkdir(parents=True, exist_ok=True)
        log = self.log_path.open("wb")
        self.proc = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, env=env, **process_group())
        log.close()  # der Kindprozess hat das Handle geerbt
        self.started_at, self.finished_at, self.returncode, self.stopped = utcnow(), None, None, False
        self.label = label or (f"{len(job_ids)} Stelle(n)" if job_ids else "Warteschlange")
        self.mode = mode
        return True

    def stop(self) -> bool:
        if not self.active or self.proc is None:
            return False
        self.stopped = True
        kill_tree(self.proc)
        return True

    def tail(self, lines: int = 80) -> str:
        """Die letzten Zeilen des Protokolls – nur das Dateiende wird gelesen (Abruf alle paar Sekunden, das
        Protokoll eines langen Laufs hat schnell einige MB)."""
        if lines <= 0 or not self.log_path.exists():
            return ""
        with self.log_path.open("rb") as f:
            start = max(0, f.seek(0, os.SEEK_END) - lines * 400)
            f.seek(start)
            data = f.read().decode("utf-8", errors="replace").splitlines()
        if start and data:
            data = data[1:]  # angeschnittene erste Zeile
        return "\n".join(data[-lines:])

    def state(self, lines: int = 80) -> dict[str, Any]:
        return {
            "active": self.active,
            "label": self.label,
            "mode": self.mode,
            "started_at": self.started_at.isoformat() + "Z" if self.started_at else None,
            "finished_at": self.finished_at.isoformat() + "Z" if self.finished_at else None,
            "returncode": self.returncode,
            "stopped": self.stopped,
            "log": self.tail(lines),
        }

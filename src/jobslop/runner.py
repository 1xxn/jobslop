"""Bewerbungsläufe als eigener Prozess (``jobslop apply --via-dashboard``).

Ein separater Prozess hält Browser und Claude-Aufrufe vom Dashboard-Server fern: hängt eine Seite, bleibt das
Dashboard bedienbar, und „Stopp“ beendet den Lauf sauber.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import ApplyMode, Settings
from .db import utcnow


class Runner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.proc: subprocess.Popen[bytes] | None = None
        self.started_at: datetime | None = None
        self.finished_at: datetime | None = None
        self.label = ""
        self.mode = ""
        self.returncode: int | None = None

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
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        self.proc = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, env=env, creationflags=flags)
        log.close()  # der Kindprozess hat das Handle geerbt
        self.started_at, self.finished_at, self.returncode = utcnow(), None, None
        self.label = label or (f"{len(job_ids)} Stelle(n)" if job_ids else "Warteschlange")
        self.mode = mode
        return True

    def stop(self) -> bool:
        if not self.active or self.proc is None:
            return False
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        return True

    def tail(self, lines: int = 80) -> str:
        if not self.log_path.exists():
            return ""
        data = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(data[-lines:])

    def state(self, lines: int = 80) -> dict[str, Any]:
        return {
            "active": self.active,
            "label": self.label,
            "mode": self.mode,
            "started_at": self.started_at.isoformat() + "Z" if self.started_at else None,
            "finished_at": self.finished_at.isoformat() + "Z" if self.finished_at else None,
            "returncode": self.returncode,
            "log": self.tail(lines),
        }

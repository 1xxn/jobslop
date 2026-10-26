"""Claude über das lokale Claude Code (Abo-Login) – keine API-Schlüssel, keine API-Kosten.

Jeder Aufruf startet ``claude -p`` mit eigenem System-Prompt und einem JSON-Schema (``--json-schema``).
Claude Code liefert das Ergebnis validiert im Feld ``structured_output``. Bilder und Dateien legt
jobpilot in einen temporären Arbeitsordner, aus dem Claude sie mit dem Read-Tool liest.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import re
import shutil
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from .config import Settings

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

# Trennt im System-Prompt den stabilen (cachebaren) Teil vom variablen Teil. Claude Code ≥ 2.1.275.
DYNAMIC_BOUNDARY = "__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__"

_LIMIT_RX = re.compile(
    r"usage limit|limit reached|hit your \w*\s?limit|rate.?limit|too many requests|weekly limit|"
    r"session limit|out of (extra )?usage|limit will reset|resets at",
    re.I,
)
_AUTH_RX = re.compile(
    r"not logged in|please run /login|invalid api key|authentication|oauth|unauthori[sz]ed|log ?in", re.I
)


class LLMUnavailable(RuntimeError):
    """Claude Code fehlt oder ist nicht angemeldet."""


class LLMLimitReached(RuntimeError):
    """Das Nutzungslimit des Abos ist erreicht – später weitermachen."""


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    seconds: float = 0.0
    by_model: dict[str, int] = field(default_factory=dict)

    def add(self, model: str, data: dict[str, Any], seconds: float) -> None:
        usage = data.get("usage") or {}
        self.calls += 1
        self.input_tokens += int(usage.get("input_tokens") or 0)
        self.output_tokens += int(usage.get("output_tokens") or 0)
        self.cache_read_tokens += int(usage.get("cache_read_input_tokens") or 0)
        self.cache_write_tokens += int(usage.get("cache_creation_input_tokens") or 0)
        self.seconds += seconds
        self.by_model[model] = self.by_model.get(model, 0) + 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "seconds": round(self.seconds, 1),
            "by_model": dict(self.by_model),
        }


# --------------------------------------------------------------------------- Inhaltsblöcke


def text_block(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def image_block(data: bytes, media_type: str = "image/jpeg") -> dict[str, Any]:
    return {"type": "image", "data": data, "media_type": media_type}


def file_block(path: Path) -> dict[str, Any]:
    return {"type": "file", "path": Path(path)}


# --------------------------------------------------------------------------- Schema


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic-Schema, bei dem jedes Objekt ``additionalProperties: false`` trägt und alle Felder Pflicht sind."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:  # $defs inline auflösen – flache Schemas sind für Claude Code am robustesten
                return walk(copy.deepcopy(defs[node["$ref"].rsplit("/", 1)[-1]]))
            props = node.get("properties")
            node = {k: walk(v) for k, v in node.items() if k not in ("title", "properties")}
            if isinstance(props, dict):  # Feldnamen (auch ein Feld namens "title") bleiben erhalten
                node["properties"] = {name: walk(sub) for name, sub in props.items()}
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"].keys())
            return node
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    return walk(schema)


# --------------------------------------------------------------------------- Claude Code finden


def find_claude(explicit: str = "") -> list[str]:
    """Kommando, mit dem sich Claude Code starten lässt. Wirft LLMUnavailable, wenn nichts gefunden wird."""
    candidates = [explicit] if explicit else []
    candidates += [shutil.which("claude") or ""]
    home = Path.home()
    if sys.platform == "win32":
        candidates += [
            str(home / ".local" / "bin" / "claude.exe"),
            str(Path(os.environ.get("APPDATA", "")) / "npm" / "claude.cmd"),
        ]
    else:
        candidates += [str(home / ".local" / "bin" / "claude"), str(home / ".claude" / "local" / "claude")]
    for cand in candidates:
        if not cand or not Path(cand).exists():
            continue
        if cand.lower().endswith((".cmd", ".bat")):
            # npm-Installation unter Windows: Über cmd.exe würden die JSON-Argumente zerlegt.
            # Das npm-Paket bringt dieselbe native claude.exe mit – die wird direkt gestartet.
            pkg = Path(cand).parent / "node_modules" / "@anthropic-ai"
            native = sorted(pkg.glob("claude-code*/**/claude.exe")) if pkg.is_dir() else []
            if native:
                return [str(native[0])]
            cli = pkg / "claude-code" / "cli.js"  # sehr alte npm-Versionen
            node = shutil.which("node")
            if cli.exists() and node:
                return [node, str(cli)]
            continue
        return [cand]
    raise LLMUnavailable(
        "Claude Code wurde nicht gefunden. Installieren (https://code.claude.com), dann einmal `claude` starten "
        "und mit deinem Claude-Abo anmelden. Alternativ JOBPILOT_CLAUDE_BIN auf den Pfad setzen."
    )


def subscription_env() -> dict[str, str]:
    """Umgebung ohne API-Schlüssel, damit Claude Code garantiert den Abo-Login nutzt und nichts über die API abrechnet."""
    env = dict(os.environ)
    for key in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_CODE_USE_FOUNDRY",
        "CLAUDE_CODE_SIMPLE",
    ):
        env.pop(key, None)
    env.setdefault("CLAUDE_CODE_SKIP_PROMPT_HISTORY", "1")
    return env


SUBSCRIPTION_METHODS = {"claude.ai", "oauth_token", "oauth"}


@dataclass
class LoginCheck:
    ok: bool
    message: str
    method: str = ""
    version: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


def check_login(settings: Settings) -> LoginCheck:
    """Prüft synchron: Claude Code vorhanden, angemeldet und mit Abo (nicht per API-Schlüssel)."""
    import subprocess

    try:
        cmd = find_claude(settings.claude_bin)
    except LLMUnavailable as exc:
        return LoginCheck(False, str(exc))
    env = subscription_env()
    try:
        ver = subprocess.run(
            [*cmd, "--version"],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
            encoding="utf-8",
            errors="replace",
        )
        version = (ver.stdout or "").strip().split("\n")[0].replace("(Claude Code)", "").strip()
        res = subprocess.run(
            [*cmd, "auth", "status"],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return LoginCheck(False, f"Claude Code startet nicht: {exc}")
    try:
        data = json.loads(res.stdout or "{}")
    except json.JSONDecodeError:
        data = {"loggedIn": res.returncode == 0, "raw": (res.stdout or res.stderr)[:300]}
    method = str(data.get("authMethod") or "")
    if not data.get("loggedIn"):
        return LoginCheck(
            False,
            "Claude Code ist nicht angemeldet – im Terminal `claude` starten und mit dem Abo einloggen",
            method,
            version,
            data,
        )
    if method and method not in SUBSCRIPTION_METHODS:
        return LoginCheck(
            False,
            f"Claude Code ist per {method} angemeldet, nicht mit dem Abo – `claude` starten, "
            "/logout und /login mit deinem Claude-Konto",
            method,
            version,
            data,
        )
    who = data.get("email") or data.get("orgName") or ""
    plan = data.get("subscriptionType") or ""
    detail = " · ".join(x for x in (method, str(plan), str(who)) if x)
    return LoginCheck(True, f"Claude Code {version} angemeldet ({detail})", method, version, data)


# --------------------------------------------------------------------------- Client


class LLM:
    """Gleiche Schnittstelle wie ein API-Client: ``await llm.parse(Schema, system=…, content=…)``."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.command = find_claude(settings.claude_bin)
        self.usage = Usage()
        self._sem: asyncio.Semaphore | None = None
        self.workroot = settings.home / "claude-work"

    @property
    def sem(self) -> asyncio.Semaphore:
        if self._sem is None:
            self._sem = asyncio.Semaphore(max(1, self.settings.claude_parallel))
        return self._sem

    async def parse(
        self,
        schema: type[T],
        *,
        system: str,
        content: list[dict[str, Any]] | str,
        model: str | None = None,
        max_tokens: int = 4096,  # Claude Code steuert die Länge selbst; Parameter bleibt für Kompatibilität
        cache_system: bool = True,
    ) -> T:
        model = model or self.settings.llm_model
        blocks = [text_block(content)] if isinstance(content, str) else list(content)
        workdir = self.workroot / uuid.uuid4().hex[:12]
        workdir.mkdir(parents=True, exist_ok=True)
        try:
            prompt, files = self._materialize(blocks, workdir)
            system_file = workdir / "system.txt"
            system_file.write_text(system, encoding="utf-8")
            cmd = [
                *self.command,
                "-p",
                "--output-format",
                "json",
                "--model",
                model,
                "--system-prompt-file",
                str(system_file),
                "--json-schema",
                json.dumps(strict_schema(schema), ensure_ascii=False),
                "--tools",
                "Read" if files else "",
                "--permission-mode",
                "dontAsk",
                "--strict-mcp-config",
                "--disable-slash-commands",
                "--setting-sources",
                "",
                "--no-session-persistence",
                "--max-turns",
                str(8 if files else 4),
            ]
            if files:
                cmd += ["--allowedTools", "Read"]
            if self.settings.claude_effort:
                cmd += ["--effort", self.settings.claude_effort]
            async with self.sem:
                data, seconds = await self._run(cmd, prompt, workdir)
            self.usage.add(model, data, seconds)
            output = data.get("structured_output")
            if output is None:
                try:
                    output = json.loads(data.get("result") or "")
                except (TypeError, json.JSONDecodeError) as exc:
                    raise RuntimeError(
                        f"Claude Code lieferte keine strukturierte Antwort: {str(data.get('result'))[:300]}"
                    ) from exc
            return schema.model_validate(output)
        finally:
            if not self.settings.keep_llm_workdirs:
                shutil.rmtree(workdir, ignore_errors=True)

    @staticmethod
    def _materialize(blocks: list[dict[str, Any]], workdir: Path) -> tuple[str, list[str]]:
        texts: list[str] = []
        files: list[str] = []
        for i, block in enumerate(blocks, start=1):
            kind = block.get("type")
            if kind == "text":
                texts.append(block["text"])
            elif kind == "image":
                ext = ".png" if block.get("media_type") == "image/png" else ".jpg"
                name = f"screenshot-{i}{ext}"
                (workdir / name).write_bytes(block["data"])
                files.append(name)
            elif kind == "file":
                src = Path(block["path"])
                name = f"datei-{i}{src.suffix.lower()}"
                shutil.copyfile(src, workdir / name)
                files.append(name)
        if files:
            texts.append(
                "Zusätzliche Dateien im Arbeitsordner – öffne jede mit dem Read-Tool, bevor du antwortest: "
                + ", ".join(files)
            )
        return "\n\n".join(texts), files

    async def _run(self, cmd: list[str], prompt: str, workdir: Path) -> tuple[dict[str, Any], float]:
        started = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(workdir),
            env=subscription_env(),
        )
        try:
            out, err = await asyncio.wait_for(
                proc.communicate(prompt.encode("utf-8")), timeout=self.settings.claude_timeout_s
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError(
                f"Claude Code hat nach {self.settings.claude_timeout_s}s nicht geantwortet"
            ) from None
        seconds = time.monotonic() - started
        stdout = out.decode("utf-8", errors="replace").strip()
        stderr = err.decode("utf-8", errors="replace").strip()
        data: dict[str, Any] | None = None
        for line in reversed(stdout.splitlines() or [""]):
            line = line.strip()
            if line.startswith("{"):
                try:
                    data = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
        if data is None:
            try:
                data = json.loads(stdout)
            except json.JSONDecodeError:
                message = (stderr or stdout)[:400]
                self._raise_for(message, None)
                raise RuntimeError(f"Claude Code-Fehler (Exit {proc.returncode}): {message}") from None
        if data.get("is_error") or data.get("subtype") not in (None, "success"):
            message = str(data.get("result") or data.get("subtype") or stderr)[:400]
            self._raise_for(message, data.get("api_error_status"))
            raise RuntimeError(f"Claude Code meldet einen Fehler: {message}")
        return data, seconds

    @staticmethod
    def _raise_for(message: str, status: Any) -> None:
        if status == 429 or _LIMIT_RX.search(message):
            raise LLMLimitReached(f"Claude-Nutzungslimit erreicht: {message}")
        if status in (401, 403) or _AUTH_RX.search(message):
            raise LLMUnavailable(
                f"Claude Code ist nicht angemeldet – im Terminal `claude` starten und /login ausführen. ({message})"
            )


def try_llm(settings: Settings) -> LLM | None:
    try:
        return LLM(settings)
    except LLMUnavailable as exc:
        log.warning("Claude nicht verfügbar: %s", exc)
        return None

"""Claude-Code-Anbindung mit einer CLI-Attrappe: Aufrufparameter, Abo-Umgebung, Dateien, Limits, Login-Prüfung."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

from jobslop.config import Settings
from jobslop.llm import (
    LLM,
    LLMLimitReached,
    LLMUnavailable,
    check_login,
    file_block,
    find_claude,
    image_block,
    strict_schema,
)

FAKE = Path(__file__).parent / "fake_claude.py"


class Item(BaseModel):
    title: str  # Feldname "title" darf beim Aufbereiten des Schemas nicht verloren gehen
    tags: list[str]


class Answer(BaseModel):
    verdict: str
    items: list[Item]


@pytest.fixture
def fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Die Attrappe läuft über den Python-Interpreter – so auch unter Windows, wo Shebang-Skripte nicht starten.
    monkeypatch.setattr("jobslop.llm.find_claude", lambda explicit="": [sys.executable, str(FAKE)])
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    monkeypatch.setenv(
        "FAKE_CLAUDE_OUTPUT", json.dumps({"verdict": "ok", "items": [{"title": "a", "tags": []}]})
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-sollte-nie-ankommen")
    settings = Settings(home=tmp_path / "home")

    def calls() -> list[dict]:
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    return settings, calls


def test_strict_schema_inlines_refs_and_keeps_title_field():
    schema = strict_schema(Answer)
    assert "$defs" not in json.dumps(schema)
    item = schema["properties"]["items"]["items"]
    assert item["additionalProperties"] is False and item["required"] == ["title", "tags"]
    assert "title" in item["properties"]
    assert schema["additionalProperties"] is False


async def test_parse_uses_subscription_cli(fake):
    settings, calls = fake
    llm = LLM(settings)
    result = await llm.parse(Answer, system="SYSTEM-REGELN", content="Bitte prüfen", model="haiku")
    assert result.verdict == "ok" and result.items[0].title == "a"
    call = calls()[0]
    args = call["args"]
    assert args[0] == "-p" and args[args.index("--output-format") + 1] == "json"
    assert args[args.index("--model") + 1] == "haiku"
    assert args[args.index("--tools") + 1] == ""  # ohne Dateien keine Tools
    assert args[args.index("--setting-sources") + 1] == ""
    for flag in ("--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence"):
        assert flag in args
    assert "--bare" not in args  # --bare würde das Abo nicht nutzen
    assert json.loads(args[args.index("--json-schema") + 1]) == strict_schema(Answer)
    assert call["system"] == "SYSTEM-REGELN" and call["stdin"] == "Bitte prüfen"
    assert call["api_key_seen"] is False  # API-Schlüssel wird nie durchgereicht
    assert not os.path.exists(call["cwd"])  # noqa: ASYNC240 – Arbeitsordner wird aufgeräumt
    assert llm.usage.calls == 1 and llm.usage.input_tokens == 100 and llm.usage.cache_read_tokens == 50


async def test_parse_with_files_enables_read(fake, tmp_path):
    settings, calls = fake
    cv = tmp_path / "Lebenslauf.pdf"
    cv.write_bytes(b"%PDF-1.4")
    llm = LLM(settings)
    await llm.parse(
        Answer,
        system="s",
        content=[file_block(cv), {"type": "text", "text": "Seite"}, image_block(b"\xff\xd8jpeg")],
    )
    call = calls()[0]
    args = call["args"]
    assert args[args.index("--tools") + 1] == "Read"
    assert args[args.index("--allowedTools") + 1] == "Read(./**)"  # nur der Arbeitsordner, nie ~/.ssh & Co.
    assert "datei-1.pdf" in call["files"] and "screenshot-3.jpg" in call["files"]
    assert "datei-1.pdf" in call["stdin"] and "screenshot-3.jpg" in call["stdin"]


async def test_text_only_result_fallback(fake, monkeypatch):
    settings, _calls = fake
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "text_only")
    result = await LLM(settings).parse(Answer, system="s", content="x")
    assert result.items[0].title == "a"


@pytest.mark.parametrize(
    ("mode", "error"), [("limit", LLMLimitReached), ("auth", LLMUnavailable), ("crash", RuntimeError)]
)
async def test_errors_are_classified(fake, monkeypatch, mode, error):
    settings, _calls = fake
    monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
    with pytest.raises(error):
        await LLM(settings).parse(Answer, system="s", content="x")


@pytest.mark.parametrize(("mode", "ok"), [("ok", True), ("api_key", False), ("logged_out", False)])
def test_check_login(fake, monkeypatch, mode, ok):
    settings, _calls = fake
    monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
    result = check_login(settings)
    assert result.ok is ok
    if ok:
        assert "2.1.310" in result.message and "pro" in result.message


def test_find_claude_prefers_explicit_path(tmp_path):
    exe = tmp_path / ("claude.exe" if sys.platform == "win32" else "claude")
    exe.write_bytes(b"")
    assert find_claude(str(exe)) == [str(exe)]


def test_missing_binary(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    settings = Settings(home=tmp_path / "home", claude_bin=str(tmp_path / "gibt-es-nicht"))
    assert not check_login(settings).ok
    with pytest.raises(LLMUnavailable):
        LLM(settings)


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("JOBSLOP_LIVE") != "1", reason="nur mit JOBSLOP_LIVE=1 (nutzt das Abo)")
async def test_live_claude_code(tmp_path):
    """Echter Aufruf gegen das installierte Claude Code (kleines Modell, ein Aufruf)."""
    settings = Settings(home=tmp_path / "home", llm_model="haiku")
    login = check_login(settings)
    assert login.ok, login.message
    result = await LLM(settings).parse(
        Answer,
        system="Antworte ausschließlich über das vorgegebene Schema.",
        content="verdict='bereit'; items: ein Element mit title='SRE' und tags=['k8s','gcp']",
    )
    assert result.items and result.items[0].title.upper() == "SRE"

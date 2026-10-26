"""Claude-Anbindung mit Structured Outputs, Prompt-Caching und Verbrauchszählung."""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from .config import Settings

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class LLMUnavailable(RuntimeError):
    """Kein API-Schlüssel oder SDK nicht nutzbar."""


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    by_model: dict[str, int] = field(default_factory=dict)

    def add(self, model: str, usage: Any) -> None:
        self.calls += 1
        self.input_tokens += getattr(usage, "input_tokens", 0) or 0
        self.output_tokens += getattr(usage, "output_tokens", 0) or 0
        self.cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
        self.cache_write_tokens += getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.by_model[model] = self.by_model.get(model, 0) + 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "by_model": dict(self.by_model),
        }


def image_block(png_or_jpeg: bytes, media_type: str = "image/jpeg") -> dict[str, Any]:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": base64.b64encode(png_or_jpeg).decode(),
        },
    }


def pdf_block(path: Path) -> dict[str, Any]:
    return {
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": "application/pdf",
            "data": base64.b64encode(path.read_bytes()).decode(),
        },
    }


class LLM:
    """Dünner, asynchroner Wrapper um ``AsyncAnthropic.messages.parse``.

    * Antworten werden über Pydantic-Modelle als JSON-Schema erzwungen (Structured Outputs).
    * Der lange, stabile Teil des Prompts (Profil, Regeln) liegt im System-Prompt und wird gecacht.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.usage = Usage()
        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:  # pragma: no cover
            raise LLMUnavailable("Das Paket 'anthropic' ist nicht installiert.") from exc
        import os

        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise LLMUnavailable("ANTHROPIC_API_KEY ist nicht gesetzt (Umgebung oder .env).")
        self._client = AsyncAnthropic(max_retries=settings.llm_max_retries)

    async def parse(
        self,
        schema: type[T],
        *,
        system: str,
        content: list[dict[str, Any]] | str,
        model: str | None = None,
        max_tokens: int = 4096,
        cache_system: bool = True,
    ) -> T:
        model = model or self.settings.llm_model
        system_blocks: list[dict[str, Any]] = [{"type": "text", "text": system}]
        if cache_system:
            system_blocks[0]["cache_control"] = {"type": "ephemeral"}
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        response = await self._client.messages.parse(
            model=model,
            max_tokens=max_tokens,
            system=system_blocks,
            messages=[{"role": "user", "content": content}],
            output_format=schema,
        )
        self.usage.add(model, response.usage)
        parsed = response.parsed_output
        if parsed is None:  # pragma: no cover - defensive
            raise RuntimeError(
                f"Modell lieferte keine gültige Struktur (stop_reason={response.stop_reason})."
            )
        return parsed


def try_llm(settings: Settings) -> LLM | None:
    try:
        return LLM(settings)
    except LLMUnavailable as exc:
        log.warning("LLM nicht verfügbar: %s", exc)
        return None

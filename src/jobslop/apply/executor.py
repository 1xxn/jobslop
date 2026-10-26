"""Führt geplante Aktionen robust aus – native Felder, Custom-Dropdowns, Radios, Uploads."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .extract import PageState
from .planner import FieldAction
from .prepare import robust_click

log = logging.getLogger(__name__)


class ElementGone(RuntimeError):
    """Das geplante Element existiert nicht mehr (Seite hat sich inzwischen verändert)."""


@dataclass
class ActionResult:
    field_id: str
    action: str
    ok: bool
    label: str = ""
    value: str = ""
    detail: str = ""


@dataclass
class Files:
    """Auflösung von Platzhaltern wie @cv auf echte Dateien bzw. Texte."""

    cv: Path | None = None
    cv_en: Path | None = None
    cover_letter_pdf: Path | None = None
    cover_letter_text: str = ""
    certificates: list[Path] = field(default_factory=list)

    def resolve_upload(self, token: str) -> list[Path]:
        token = token.strip().lower()
        if token in ("@cv", "cv"):
            return [self.cv] if self.cv else []
        if token in ("@cv_en", "cv_en"):
            return [self.cv_en or self.cv] if (self.cv_en or self.cv) else []
        if token in ("@cover_letter_pdf", "@cover_letter", "cover_letter"):
            return [self.cover_letter_pdf] if self.cover_letter_pdf else []
        if token in ("@certificates", "certificates"):
            return list(self.certificates)
        return []


def similarity(a: str, b: str) -> float:
    a, b = a.lower().strip(), b.lower().strip()
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.9 * min(len(a), len(b)) / max(len(a), len(b)) + 0.1
    return SequenceMatcher(None, a, b).ratio()


def best_option(options: list[str], wanted: str) -> tuple[int, float]:
    scores = [similarity(o, wanted) for o in options]
    if not scores:
        return -1, 0.0
    idx = max(range(len(scores)), key=scores.__getitem__)
    return idx, scores[idx]


def to_iso_date(value: str) -> str:
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return value


class Executor:
    def __init__(self, page: Any, files: Files) -> None:
        self.page = page
        self.files = files

    def _loc(self, state: PageState, element_id: str) -> Any:
        frame = state.frame_for(element_id) or self.page.main_frame
        return frame.locator(f'[data-jp="{element_id}"]').first

    async def run(self, state: PageState, actions: list[FieldAction]) -> list[ActionResult]:
        results: list[ActionResult] = []
        for action in actions:
            if action.action == "skip":
                continue
            f = state.field(action.field_id)
            label = (f or {}).get("label", "") or ((state.button(action.field_id) or {}).get("text", ""))
            try:
                detail = await self._run_one(state, action, f)
                results.append(
                    ActionResult(action.field_id, action.action, True, label, action.value, detail)
                )
            except Exception as exc:  # jede Aktion einzeln absichern
                msg = f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}"
                log.info("Aktion %s auf %s fehlgeschlagen: %s", action.action, action.field_id, msg)
                results.append(ActionResult(action.field_id, action.action, False, label, action.value, msg))
            await asyncio.sleep(0.15)
        return results

    async def _run_one(self, state: PageState, a: FieldAction, f: dict[str, Any] | None) -> str:
        kind = (f or {}).get("kind", "")
        value = a.value
        if a.action == "fill" and value.strip().lower() == "@cover_letter":
            value = self.files.cover_letter_text
            if not value:
                raise RuntimeError("Kein Anschreiben-Text verfügbar")

        if a.action == "click":
            loc = self._loc(state, a.field_id)
            if await loc.count() == 0:
                raise ElementGone(f"Element {a.field_id} ist nicht mehr auf der Seite")
            await robust_click(loc)
            return "geklickt"
        if a.action == "upload":
            return await self._upload(state, a, f)
        if f is None:
            raise RuntimeError(f"Unbekannte Feld-ID {a.field_id}")

        if kind in ("radio", "checkbox_group"):
            return await self._choose_options(state, f, value, a.action)
        if kind in ("checkbox", "aria_checkbox", "aria_radio"):
            return await self._set_checked(state, a.field_id, a.action != "uncheck")
        if kind == "select":
            return await self._select_native(state, f, value)
        if kind == "combobox":
            return await self._combobox(state, f, value)
        if kind == "richtext":
            loc = self._loc(state, a.field_id)
            await loc.click()
            await loc.press("ControlOrMeta+a")
            await loc.press("Delete")
            await loc.press_sequentially(value, delay=5)
            return "eingegeben"
        if kind in ("text", "textarea", "date"):
            return await self._fill_text(state, f, value)
        raise RuntimeError(f"Feldtyp {kind or '?'} nicht unterstützt")

    # ------------------------------------------------------------------ text
    async def _fill_text(self, state: PageState, f: dict[str, Any], value: str) -> str:
        loc = self._loc(state, f["id"])
        if f.get("input_type") == "date" or f["kind"] == "date":
            value = to_iso_date(value)
        if f.get("max_length") and len(value) > f["max_length"]:
            value = value[: f["max_length"]]
        await loc.scroll_into_view_if_needed(timeout=5000)
        await loc.fill(value, timeout=8000)
        current = await loc.input_value()
        if current.strip() != value.strip():
            # Manche Masken (Telefon, Datum) formatieren um – dann tippen statt einfügen
            await loc.fill("")
            await loc.press_sequentially(value, delay=20)
            current = await loc.input_value()
        if not current.strip():
            raise RuntimeError("Feld blieb leer")
        await loc.dispatch_event("blur")
        return "ok" if current.strip() == value.strip() else f"umformatiert zu '{current[:60]}'"

    # ------------------------------------------------------------------ select
    async def _select_native(self, state: PageState, f: dict[str, Any], value: str) -> str:
        loc = self._loc(state, f["id"])
        labels = [o["label"] for o in f.get("options", [])]
        idx, score = best_option(labels, value)
        if idx < 0 or score < 0.55:
            values = [o.get("value", "") for o in f.get("options", [])]
            vidx, vscore = best_option(values, value)
            if vidx < 0 or vscore < 0.8:
                raise RuntimeError(f"Option '{value}' nicht gefunden")
            idx = vidx
        await loc.select_option(index=idx, timeout=8000)
        return f"gewählt: {labels[idx]}"

    # ------------------------------------------------------------------ radio/checkbox groups
    async def _choose_options(self, state: PageState, f: dict[str, Any], value: str, action: str) -> str:
        options = f.get("options", [])
        wanted = [v.strip() for v in re.split(r";|\n", value) if v.strip()] or [value]
        chosen = []
        for w in wanted:
            idx, score = best_option([o["label"] for o in options], w)
            if idx < 0 or score < 0.5:
                raise RuntimeError(f"Option '{w}' nicht gefunden")
            opt = options[idx]
            await self._set_checked(state, opt["id"], action != "uncheck")
            chosen.append(opt["label"])
        return "gewählt: " + ", ".join(chosen)

    async def _set_checked(self, state: PageState, element_id: str, checked: bool) -> str:
        loc = self._loc(state, element_id)
        tag = await loc.evaluate("e => e.tagName")
        if tag == "INPUT":
            try:
                await loc.set_checked(checked, timeout=5000)
            except Exception:
                # Visuell versteckte Inputs: über das Label klicken
                await loc.evaluate(
                    "e => ((e.labels && e.labels[0]) || e.closest('label') || e.parentElement || e).click()"
                )
            now = await loc.is_checked()
        else:
            current = (await loc.get_attribute("aria-checked")) == "true"
            if current != checked:
                await loc.click(timeout=5000)
            now = (await loc.get_attribute("aria-checked")) == "true"
        if now != checked:
            raise RuntimeError("Status ließ sich nicht setzen")
        return "an" if checked else "aus"

    # ------------------------------------------------------------------ custom dropdowns
    async def _combobox(self, state: PageState, f: dict[str, Any], value: str) -> str:
        loc = self._loc(state, f["id"])
        frame = state.frame_for(f["id"]) or self.page.main_frame
        await loc.scroll_into_view_if_needed(timeout=5000)
        await loc.click(timeout=8000)
        tag = await loc.evaluate("e => e.tagName")
        if tag == "INPUT":
            await loc.fill("")
            await loc.press_sequentially(value[:40], delay=25)
        await asyncio.sleep(0.6)
        options = frame.locator('[role="option"]:visible, li[role="option"], [class*="option"]:visible')
        count = await options.count()
        texts = []
        for i in range(min(count, 150)):
            try:
                texts.append((await options.nth(i).inner_text(timeout=1000)).strip())
            except Exception:
                texts.append("")
        idx, score = best_option(texts, value)
        if idx >= 0 and score >= 0.5:
            await options.nth(idx).click(timeout=5000)
            return f"gewählt: {texts[idx]}"
        if tag == "INPUT":
            await loc.press("Enter")
            return "per Enter übernommen"
        await self.page.keyboard.press("Escape")
        raise RuntimeError(f"Option '{value}' im Dropdown nicht gefunden")

    # ------------------------------------------------------------------ uploads
    async def _upload(self, state: PageState, a: FieldAction, f: dict[str, Any] | None) -> str:
        paths = [p for p in self.files.resolve_upload(a.value) if p and p.exists()]
        if not paths:
            raise RuntimeError(f"Keine Datei für {a.value} vorhanden")
        loc = self._loc(state, a.field_id)
        is_file_input = await loc.evaluate("e => e.tagName === 'INPUT' && e.type === 'file'")
        if is_file_input:
            multiple = await loc.evaluate("e => e.multiple")
            await loc.set_input_files([str(p) for p in (paths if multiple else paths[:1])], timeout=10_000)
        else:
            async with self.page.expect_file_chooser(timeout=8000) as fc_info:
                await loc.click()
            chooser = await fc_info.value
            await chooser.set_files([str(p) for p in (paths if chooser.is_multiple() else paths[:1])])
        await asyncio.sleep(1.2)  # Upload-Parser (z. B. Lebenslauf-Autofill) arbeiten lassen
        return "hochgeladen: " + ", ".join(p.name for p in paths)


async def click_element(page: Any, state: PageState, element_id: str) -> Any:
    """Klickt einen Button/Link. Öffnet sich ein neuer Tab, wird dieser zurückgegeben, sonst die Seite selbst."""
    context = page.context
    before = list(context.pages)
    frame = state.frame_for(element_id) or page.main_frame
    loc = frame.locator(f'[data-jp="{element_id}"]').first
    if await loc.count() == 0:
        raise ElementGone(f"Button {element_id} ist nicht mehr auf der Seite")
    await robust_click(loc, wait_ms=10_000)
    await asyncio.sleep(1.5)
    new_pages = [p for p in context.pages if p not in before]
    if new_pages:
        new = new_pages[-1]
        with contextlib.suppress(Exception):
            await new.wait_for_load_state("domcontentloaded", timeout=20_000)
        return new
    return page

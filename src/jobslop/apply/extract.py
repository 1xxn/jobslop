"""Seitenzustand über alle Frames hinweg erfassen."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

log = logging.getLogger(__name__)

_JS = resources.files(__package__).joinpath("extract.js").read_text(encoding="utf-8")

CAPTCHA_HOST_HINTS = ("recaptcha", "hcaptcha", "challenges.cloudflare.com", "turnstile", "captcha")


@dataclass
class PageState:
    url: str
    title: str
    fields: list[dict[str, Any]] = field(default_factory=list)
    buttons: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    headings: list[str] = field(default_factory=list)
    text: str = ""
    captcha_visible: bool = False
    captcha_present: bool = False
    frames: dict[str, Any] = field(default_factory=dict)  # id-Präfix -> Frame

    def field(self, fid: str) -> dict[str, Any] | None:
        for f in self.fields:
            if f["id"] == fid:
                return f
            for opt in f.get("options", []) or []:
                if opt.get("id") == fid:
                    return f
        return None

    def button(self, bid: str) -> dict[str, Any] | None:
        return next((b for b in self.buttons if b["id"] == bid), None)

    def frame_for(self, element_id: str) -> Any:
        prefix = element_id.split("-", 1)[0]
        return self.frames.get(prefix)

    @property
    def has_password(self) -> bool:
        return any(f["kind"] == "password" for f in self.fields)

    @property
    def form_fields(self) -> list[dict[str, Any]]:
        return [f for f in self.fields if f["kind"] != "password"]

    def missing_required(self) -> list[dict[str, Any]]:
        return [f for f in self.form_fields if f.get("required") and not f.get("value")]

    def compact(self, max_options: int = 60) -> str:
        """Kompakte JSON-Darstellung der Felder und Buttons für den Prompt."""
        rows = []
        for f in self.fields:
            row = {k: v for k, v in f.items() if v not in ("", None, False, [], 0) and k != "options"}
            if f.get("options"):
                opts = f["options"]
                row["options"] = [
                    {"id": o["id"], "label": o["label"]} if "id" in o else o["label"]
                    for o in opts[:max_options]
                ]
                if len(opts) > max_options:
                    row["options_truncated"] = len(opts)
            rows.append(row)
        buttons = [{k: v for k, v in b.items() if v not in ("", None, False)} for b in self.buttons]
        return json.dumps({"fields": rows, "buttons": buttons}, ensure_ascii=False)


async def extract_state(page: Any) -> PageState:
    state = PageState(url=page.url, title="")
    frames = [page.main_frame] + [f for f in page.frames if f is not page.main_frame]
    for index, frame in enumerate(frames):
        url = (frame.url or "").lower()
        if index > 0 and any(h in url for h in CAPTCHA_HOST_HINTS):
            state.captcha_present = True
            try:
                el = await frame.frame_element()
                box = await el.bounding_box()
                visible = await el.is_visible()
                interactive = "size=invisible" not in url and any(
                    k in url for k in ("bframe", "challenge", "anchor", "hcaptcha", "turnstile")
                )
                if visible and box and box["width"] > 60 and box["height"] > 60 and interactive:
                    state.captcha_visible = True
            except Exception:
                pass
            continue
        if index > 0 and (not url or url == "about:blank"):
            # leere Frames können trotzdem per JS befüllte Formulare enthalten
            pass
        try:
            data = await frame.evaluate(_JS, index)
        except Exception as exc:  # Frame während Navigation weg, fremde Sandbox, …
            log.debug("Frame %s nicht auswertbar: %s", frame.url, exc)
            continue
        state.frames[str(index)] = frame
        if index == 0:
            state.url = data["url"]
            state.title = data["title"]
            state.text = data["text"]
            state.headings = data["headings"]
        elif data["fields"] or data["text"].strip():
            state.text += f"\n\n[Frame {index}: {data['url'][:120]}]\n{data['text']}"
        for f in data["fields"]:
            f["frame"] = index
        state.fields += data["fields"]
        state.buttons += data["buttons"]
        state.errors += [e for e in data["errors"] if e not in state.errors]
        for c in data["captcha"]:
            state.captcha_present = True
            if c.get("visible") and c.get("challenge"):
                state.captcha_visible = True
    return state

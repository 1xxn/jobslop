"""Screenshots mit eingezeichneten Element-IDs ("Set-of-Mark") für den Vision-Fallback."""

from __future__ import annotations

import io
import logging
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .extract import PageState

log = logging.getLogger(__name__)

MAX_HEIGHT = 9000
CHUNK_HEIGHT = 1500
TARGET_WIDTH = 1100


async def annotated_screenshots(page: Any, state: PageState, max_chunks: int = 3) -> list[bytes]:
    await page.evaluate("() => window.scrollTo(0, 0)")
    boxes: list[tuple[str, dict[str, float]]] = []
    ids = [f["id"] for f in state.fields] + [b["id"] for b in state.buttons]
    for f in state.fields:
        ids += [o["id"] for o in f.get("options", []) if isinstance(o, dict) and "id" in o]
    for element_id in dict.fromkeys(ids):
        frame = state.frame_for(element_id)
        if frame is None:
            continue
        try:
            box = await frame.locator(f'[data-jp="{element_id}"]').first.bounding_box(timeout=1000)
        except Exception:
            box = None
        if box and box["width"] > 0 and box["height"] > 0:
            boxes.append((element_id, box))

    png = await page.screenshot(full_page=True, type="png")
    img = Image.open(io.BytesIO(png)).convert("RGB")
    if img.height > MAX_HEIGHT:
        img = img.crop((0, 0, img.width, MAX_HEIGHT))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=14)
    except TypeError:  # ältere Pillow-Versionen
        font = ImageFont.load_default()
    for element_id, b in boxes:
        x0, y0, x1, y1 = b["x"], b["y"], b["x"] + b["width"], b["y"] + b["height"]
        draw.rectangle((x0, y0, x1, y1), outline=(220, 38, 38), width=2)
        tw = draw.textlength(element_id, font=font)
        draw.rectangle((x0, max(0, y0 - 17), x0 + tw + 6, max(17, y0)), fill=(220, 38, 38))
        draw.text((x0 + 3, max(0, y0 - 16)), element_id, fill=(255, 255, 255), font=font)

    scale = min(1.0, TARGET_WIDTH / img.width)
    if scale < 1.0:
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    chunk = int(CHUNK_HEIGHT * scale) if scale < 1 else CHUNK_HEIGHT
    out: list[bytes] = []
    for top in range(0, img.height, chunk):
        if len(out) >= max_chunks:
            break
        part = img.crop((0, top, img.width, min(img.height, top + chunk)))
        buf = io.BytesIO()
        part.save(buf, format="JPEG", quality=72)
        out.append(buf.getvalue())
    return out


async def save_screenshot(page: Any, path: Any, full_page: bool = True) -> None:
    try:
        await page.screenshot(path=str(path), full_page=full_page, type="jpeg", quality=70)
    except Exception as exc:  # Screenshots sind Beweismittel, aber kein Abbruchgrund
        log.info("Screenshot fehlgeschlagen: %s", exc)

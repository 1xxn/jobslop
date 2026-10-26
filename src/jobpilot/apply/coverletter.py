"""Anschreiben pro Stelle: Text mit Claude, Layout als PDF über Chromium."""

from __future__ import annotations

import html
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from ..llm import LLM
from ..profile import Profile
from .planner import JobContext


class CoverLetter(BaseModel):
    language: Literal["de", "en"]
    subject: str
    salutation: str
    paragraphs: list[str]
    closing: str


SYSTEM = """Du schreibst Anschreiben für eine Person, deren Profil und Lebenslauf unten stehen.

Regeln:
- Nur belegbare Fakten aus Profil und Lebenslauf. Keine erfundenen Zahlen, Projekte, Zertifikate oder Jahre.
- 3 bis 4 Absätze, zusammen 220–320 Wörter. Konkreter Bezug auf 2–3 Anforderungen der Stelle.
- Ton: {tone}. Keine Floskeln wie "hiermit bewerbe ich mich", keine Superlative.
- Sprache: {language_rule}
- Anrede: Ansprechperson nur nennen, wenn sie in der Anzeige steht, sonst neutral ("Liebes <Firma>-Team" bzw. "Dear <Company> team").
- closing: nur die Grußformel (z. B. "Viele Grüße" / "Kind regards"), ohne Namen.

Profil:
{profile}
"""


async def write_cover_letter(
    llm: LLM, profile: Profile, job: JobContext, language_pref: str, cv_block: Any = None
) -> CoverLetter:
    if language_pref in ("de", "en"):
        rule = "Deutsch" if language_pref == "de" else "Englisch"
    else:
        rule = "Sprache der Stellenanzeige (Deutsch oder Englisch)"
    system = SYSTEM.format(tone=profile.preferences.tone, language_rule=rule, profile=profile.to_prompt())
    content: list[dict[str, Any]] = []
    if cv_block:
        content.append(cv_block)
    content.append(
        {
            "type": "text",
            "text": f"Stelle: {job.title}\nFirma: {job.company}\nOrt: {job.location}\n\nAnzeige:\n{job.description[:9000]}",
        }
    )
    return await llm.parse(CoverLetter, system=system, content=content, max_tokens=2500)


def cover_letter_text(letter: CoverLetter, profile: Profile) -> str:
    body = "\n\n".join(letter.paragraphs)
    return f"{letter.salutation}\n\n{body}\n\n{letter.closing}\n{profile.personal.full_name}"


def cover_letter_html(letter: CoverLetter, profile: Profile, job: JobContext) -> str:
    p = profile.personal
    e = html.escape
    today = (
        date.today().strftime("%d.%m.%Y") if letter.language == "de" else date.today().strftime("%B %d, %Y")
    )
    contact = " · ".join(e(x) for x in (p.email, p.phone, p.linkedin.replace("https://", "")) if x)
    address = ", ".join(e(x) for x in (p.street, f"{p.postal_code} {p.city}".strip()) if x.strip())
    paragraphs = "".join(f"<p>{e(par)}</p>" for par in letter.paragraphs)
    return f"""<!doctype html><html lang="{letter.language}"><head><meta charset="utf-8">
<style>
  @page {{ size: A4; margin: 22mm 22mm 20mm 25mm; }}
  body {{ font-family: "Helvetica Neue", Arial, sans-serif; font-size: 10.5pt; line-height: 1.5; color: #1a1a1a; }}
  .sender {{ display: flex; justify-content: space-between; align-items: flex-end; border-bottom: 1.5px solid #1a1a1a;
             padding-bottom: 6mm; margin-bottom: 14mm; }}
  .name {{ font-size: 18pt; font-weight: 700; letter-spacing: -0.01em; }}
  .contact {{ font-size: 9pt; color: #444; text-align: right; }}
  .meta {{ display: flex; justify-content: space-between; margin-bottom: 10mm; }}
  .recipient {{ font-size: 10pt; }}
  .date {{ font-size: 10pt; color: #444; }}
  h1 {{ font-size: 11pt; font-weight: 700; margin: 0 0 7mm; }}
  p {{ margin: 0 0 4mm; text-align: left; hyphens: auto; }}
  .closing {{ margin-top: 8mm; }}
</style></head><body>
  <div class="sender"><div class="name">{e(p.full_name)}</div><div class="contact">{contact}<br>{address}</div></div>
  <div class="meta"><div class="recipient">{e(job.company)}</div><div class="date">{e(p.city)}, {today}</div></div>
  <h1>{e(letter.subject)}</h1>
  <p>{e(letter.salutation)}</p>
  {paragraphs}
  <div class="closing">{e(letter.closing)}<br><br>{e(p.full_name)}</div>
</body></html>"""


async def render_pdf(context: Any, html_doc: str, out: Path) -> Path:
    page = await context.new_page()
    try:
        await page.set_content(html_doc, wait_until="load")
        await page.pdf(path=str(out), format="A4", print_background=True, prefer_css_page_size=True)
    finally:
        await page.close()
    return out

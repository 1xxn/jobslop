"""Lebenslauf je Stelle: Claude wählt, ordnet und gewichtet die eigenen Angaben für eine Anzeige.

Eine Faktenprüfung ohne Claude lässt nur durch, was in Profil oder Lebenslauf steht: Zahlen, Jahre, Firmen,
Fähigkeiten, Zertifikate und keine höhere Seniorität als belegt. Was danach noch unbelegt ist, wird entfernt –
betrifft es Firma, Titel oder Zusammenfassung, bleibt es beim Original-Lebenslauf. Layout als PDF über Chromium,
wie beim Anschreiben. Ergebnis pro Stelle in ``<home>/tailored/job-<id>/`` – die Vorschau im Dashboard ist genau
die Datei, die später hochgeladen wird.
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import re
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..cvtext import cv_text
from ..llm import LLM
from ..profile import Profile
from .coverletter import render_pdf
from .executor import Files
from .planner import JobContext

log = logging.getLogger(__name__)

CV_TOKENS = ("@cv", "@cv_en", "cv", "cv_en")


class CvEntry(BaseModel):
    title: str = Field(description="Rolle bzw. Abschluss, wie in den Quellen (übersetzen erlaubt)")
    org: str = Field(description="Firma bzw. Hochschule, genau wie in den Quellen")
    location: str = ""
    period: str = Field("", description="Zeitraum wörtlich aus den Quellen")
    bullets: list[str] = Field(default_factory=list)


class TailoredCv(BaseModel):
    language: Literal["de", "en"]
    headline: str = Field(description="Berufsbezeichnung, belegt durch die Quellen")
    summary: str
    skills: list[str]
    experience: list[CvEntry]
    education: list[CvEntry] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    matched_keywords: list[str] = Field(
        default_factory=list, description="Begriffe der Anzeige, die durch die Quellen belegt sind"
    )


SYSTEM = """Du stellst einen Lebenslauf für eine bestimmte Stelle zusammen – ausschließlich aus Profil und
Lebenslauf unten.

Regeln:
- Erfinde nichts: keine neuen Zahlen, Jahre, Firmen, Titel, Abschlüsse, Zertifikate, Werkzeuge oder Projekte.
  Jede Zahl und jeder Name muss so in den Quellen stehen.
- Erlaubt: auswählen, kürzen, umformulieren, nach Relevanz für die Stelle ordnen und Begriffe der Anzeige
  verwenden, wenn die Quellen genau diese Sache belegen.
- Titel, Firmen und Zeiträume wie in den Quellen (übersetzen ist erlaubt, die Seniorität ändern nicht).
- Alle Stationen behalten, damit keine Lücken entstehen; weniger relevante bekommen 1–2 Stichpunkte,
  relevante 3–5. Stichpunkte beginnen mit einem Verb, ohne „ich“.
- skills: nur Fähigkeiten aus den Quellen, die wichtigsten für die Stelle zuerst, höchstens 18.
- summary: 2–3 sachliche Sätze mit Bezug zur Stelle.
- Sprache: {language_rule}

Profil:
{profile}

Lebenslauf:
{cv}
"""

# Wörter, die eine Seniorität behaupten – nur erlaubt, wenn die Quellen sie auch enthalten
_SENIORITY = (
    "senior",
    "lead",
    "principal",
    "staff",
    "head",
    "chief",
    "director",
    "manager",
    "leiter",
    "leitung",
    "architect",
    "architekt",
)
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _numbers(text: str) -> set[str]:
    """Zahlen vergleichbar machen: 30 %, 30,0 und 030 sind dieselbe Angabe."""
    out = set()
    for n in _NUMBER.findall(text):
        n = n.replace(",", ".").lstrip("0") or "0"
        out.add(n.removesuffix(".0"))
    return out


def mentions(sources: str, phrase: str) -> bool:
    """Steht die Angabe in den Quellen – wörtlich oder mit allen ihren Wörtern?"""
    p = _norm(phrase)
    if not p or p in sources:
        return True
    words = [w for w in re.split(r"[^\w+#]+", p) if len(w) > 1]
    return bool(words) and all(w in sources for w in words)


@dataclass
class Problem:
    kind: Literal["number", "skill", "org", "title", "summary"]
    text: str
    where: str

    def __str__(self) -> str:
        return f"{self.where}: {self.text}"


def fact_check(cv: TailoredCv, sources: str) -> list[Problem]:
    src = _norm(sources)
    known = _numbers(src)
    problems: list[Problem] = []

    def numbers(text: str, kind: Literal["number", "summary"], where: str) -> None:
        problems.extend(Problem(kind, n, where) for n in sorted(_numbers(text) - known))

    def seniority(text: str, where: str) -> None:
        for word in _SENIORITY:
            if re.search(rf"\b{word}", text.lower()) and word not in src:
                problems.append(Problem("title", text, where))
                return

    numbers(cv.summary, "summary", "Zusammenfassung")
    if _numbers(cv.headline) - known:
        problems.append(Problem("title", cv.headline, "Berufsbezeichnung"))
    seniority(cv.headline, "Berufsbezeichnung")
    for entry in [*cv.experience, *cv.education]:
        if not mentions(src, entry.org):
            problems.append(Problem("org", entry.org, "Station"))
        seniority(entry.title, entry.org)
        problems.extend(Problem("org", y, entry.org) for y in _YEAR.findall(entry.period) if y not in src)
        for bullet in entry.bullets:
            numbers(bullet, "number", bullet)
    for skill in [*cv.skills, *cv.certifications]:
        if not mentions(src, skill):
            problems.append(Problem("skill", skill, "Fähigkeit"))
    return problems


def strip_unverified(cv: TailoredCv, problems: list[Problem]) -> TailoredCv | None:
    """Unbelegte Fähigkeiten, Stichpunkte und eine Zusammenfassung mit unbelegter Zahl entfernen – weglassen ist
    immer sicher. Betrifft ein Problem Firma, Titel oder Zeitraum, gibt es keinen sicheren Rest: None."""
    if any(p.kind in ("org", "title") for p in problems):
        return None
    bad_skills = {p.text for p in problems if p.kind == "skill"}
    bad_bullets = {p.where for p in problems if p.kind == "number"}
    out = cv.model_copy(deep=True)
    if any(p.kind == "summary" for p in problems):
        out.summary = ""
    out.skills = [s for s in out.skills if s not in bad_skills]
    out.certifications = [c for c in out.certifications if c not in bad_skills]
    for entry in [*out.experience, *out.education]:
        entry.bullets = [b for b in entry.bullets if b not in bad_bullets]
    return out


def sources_for(profile: Profile, base: Path) -> str:
    """Alles, was als Beleg zählt: Profil und beide Lebensläufe als Text."""
    texts = [profile.to_prompt()]
    for language in ("de", "en"):
        path = profile.cv_path(base, language)
        if path and path.exists() and (text := cv_text(path)) and text not in texts:
            texts.append(text)
    return "\n\n".join(texts)


async def write_tailored_cv(llm: LLM, profile: Profile, job: JobContext, sources: str) -> TailoredCv:
    language = job.language if job.language in ("de", "en") else "de"
    rule = "Deutsch" if language == "de" else "Englisch"
    system = SYSTEM.format(language_rule=rule, profile=profile.to_prompt(), cv=sources)
    content = f"Stelle: {job.title}\nFirma: {job.company}\nOrt: {job.location}\n\nAnzeige:\n{job.description[:9000]}"
    cv = await llm.parse(TailoredCv, system=system, content=content, max_tokens=4000)
    problems = fact_check(cv, sources)
    if not problems:
        return cv
    # Ein zweiter Versuch mit den Funden – meist reicht das
    retry = (
        f"{content}\n\nDein letzter Entwurf enthielt Angaben, die nicht in den Quellen stehen: "
        + "; ".join(str(p) for p in problems[:20])
        + ". Lass sie weg oder übernimm sie genau wie in den Quellen."
    )
    cv = await llm.parse(TailoredCv, system=system, content=retry, max_tokens=4000)
    problems = fact_check(cv, sources)
    if not problems:
        return cv
    safe = strip_unverified(cv, problems)
    if safe is None:
        raise ValueError("Faktenprüfung nicht bestanden: " + "; ".join(str(p) for p in problems[:5]))
    log.info("Unbelegte Angaben entfernt: %s", "; ".join(str(p) for p in problems))
    return safe


def tailored_cv_html(cv: TailoredCv, profile: Profile) -> str:
    """Einspaltig und ohne Tabellen/Grafiken – so lesen ATS-Systeme den Text zuverlässig."""
    p = profile.personal
    e = html.escape
    de = cv.language == "de"
    contact = " · ".join(
        e(x.replace("https://", "")) for x in (p.email, p.phone, p.city, p.linkedin, p.github, p.website) if x
    )

    def entries(items: list[CvEntry]) -> str:
        out = []
        for it in items:
            meta = " · ".join(e(x) for x in (it.org, it.location) if x)
            bullets = "".join(f"<li>{e(b)}</li>" for b in it.bullets)
            out.append(
                f'<div class="entry"><div class="row"><strong>{e(it.title)}</strong>'
                f'<span class="period">{e(it.period)}</span></div><div class="org">{meta}</div>'
                + (f"<ul>{bullets}</ul>" if bullets else "")
                + "</div>"
            )
        return "".join(out)

    def section(title: str, body: str) -> str:
        return f"<h2>{title}</h2>{body}" if body else ""

    return f"""<!doctype html><html lang="{cv.language}"><head><meta charset="utf-8">
<title>{e(p.full_name)}</title>
<style>
  @page {{ size: A4; margin: 16mm 18mm 16mm 18mm; }}
  body {{ font-family: "Helvetica Neue", Arial, sans-serif; font-size: 10pt; line-height: 1.42; color: #1a1a1a; }}
  h1 {{ font-size: 19pt; margin: 0; letter-spacing: -0.01em; }}
  .headline {{ font-size: 11.5pt; margin: 1mm 0 2mm; }}
  .contact {{ font-size: 9pt; color: #444; padding-bottom: 4mm; border-bottom: 1.5px solid #1a1a1a; }}
  h2 {{ font-size: 10.5pt; text-transform: uppercase; letter-spacing: 0.06em; margin: 6mm 0 2mm; }}
  .entry {{ margin-bottom: 3.5mm; break-inside: avoid; }}
  .row {{ display: flex; justify-content: space-between; gap: 6mm; }}
  .period, .org {{ color: #444; font-size: 9.5pt; }}
  ul {{ margin: 1mm 0 0; padding-left: 4.5mm; }}
  li {{ margin-bottom: 0.6mm; }}
  p {{ margin: 0; }}
</style></head><body>
  <h1>{e(p.full_name)}</h1>
  <div class="headline">{e(cv.headline)}</div>
  <div class="contact">{contact}</div>
  {section("Profil" if de else "Profile", f"<p>{e(cv.summary)}</p>" if cv.summary else "")}
  {section("Kenntnisse" if de else "Skills", f"<p>{', '.join(e(s) for s in cv.skills)}</p>" if cv.skills else "")}
  {section("Berufserfahrung" if de else "Experience", entries(cv.experience))}
  {section("Ausbildung" if de else "Education", entries(cv.education))}
  {section("Zertifikate" if de else "Certifications", f"<p>{', '.join(e(c) for c in cv.certifications)}</p>" if cv.certifications else "")}
  {section("Sprachen" if de else "Languages", f"<p>{', '.join(e(x) for x in cv.languages)}</p>" if cv.languages else "")}
</body></html>"""


# --------------------------------------------------------------------------- Ablage pro Stelle


def tailored_dir(home: Path, job_id: int) -> Path:
    return home / "tailored" / f"job-{job_id}"


def fingerprint(profile: Profile, job: JobContext, sources: str) -> str:
    """Ändern sich Lebenslauf, Profil oder Anzeige, wird neu zugeschnitten."""
    raw = json.dumps([sources, job.title, job.description, job.language, profile.personal.model_dump()])
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def cached_cv(home: Path, job_id: int) -> tuple[Path, dict[str, Any]] | None:
    """Vorhandener Lebenslauf für die Stelle samt Metadaten (Schlagwörter, entfernte Angaben)."""
    folder = tailored_dir(home, job_id)
    meta_file = folder / "meta.json"
    if not meta_file.is_file():
        return None
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    pdf = folder / meta.get("file", "")
    return (pdf, meta) if pdf.is_file() else None


async def ensure_tailored_cv(
    llm: LLM | None,
    profile: Profile,
    job: JobContext,
    home: Path,
    profile_base: Path,
    files: Files,
    pdf_context: Callable[[], AbstractAsyncContextManager[Any]],
    *,
    force: bool = False,
) -> tuple[Path | None, str]:
    """Lebenslauf für die Stelle bereitstellen und für @cv/@cv_en einsetzen.

    Rückgabe: (PDF oder None, Hinweis). Ohne Claude oder bei nicht bestandener Faktenprüfung bleibt es beim
    Original – der Hinweis sagt warum. Engine, Browser-Erweiterung und Vorschau teilen sich diese Funktion.
    """
    if not profile.documents.tailor_cv and not force:
        return None, ""
    sources = sources_for(profile, profile_base)
    stamp = fingerprint(profile, job, sources)
    cached = cached_cv(home, job.id)
    if cached and cached[1].get("fingerprint") == stamp and not force:
        files.cv = files.cv_en = cached[0]
        return cached[0], ""
    if llm is None:
        return None, "Lebenslauf je Stelle braucht Claude Code – Original-Lebenslauf verwendet"
    try:
        cv = await write_tailored_cv(llm, profile, job, sources)
    except ValueError as exc:
        return None, f"{exc} – Original-Lebenslauf verwendet"
    folder = tailored_dir(home, job.id)
    folder.mkdir(parents=True, exist_ok=True)
    name = "".join(ch for ch in profile.personal.full_name.replace(" ", "_") if ch.isalnum() or ch in "_-")
    pdf = folder / f"{'Lebenslauf' if cv.language == 'de' else 'CV'}_{name or 'jobslop'}.pdf"
    async with pdf_context() as ctx:
        await render_pdf(ctx, tailored_cv_html(cv, profile), pdf)
    meta = {
        "file": pdf.name,
        "fingerprint": stamp,
        "language": cv.language,
        "matched_keywords": cv.matched_keywords,
        "cv": cv.model_dump(mode="json"),
    }
    (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    files.cv = files.cv_en = pdf
    return pdf, ""


def wants_cv(actions: list[Any]) -> bool:
    return any(a.action == "upload" and a.value.strip().lower() in CV_TOKENS for a in actions)

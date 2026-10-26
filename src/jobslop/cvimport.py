"""Lebenslauf (PDF) mit Claude in ein Profil übersetzen."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from .cvtext import cv_text
from .llm import LLM, file_block
from .profile import Education, Experience, Language, Profile


class _Personal(BaseModel):
    first_name: str
    last_name: str
    email: str
    phone: str
    city: str
    linkedin: str
    github: str
    website: str


class _Exp(BaseModel):
    company: str
    title: str
    start: str
    end: str
    location: str
    highlights: list[str]


class _Edu(BaseModel):
    institution: str
    degree: str
    start: str
    end: str
    location: str


class _Lang(BaseModel):
    language: str
    level: str


class CVExtract(BaseModel):
    personal: _Personal
    current_title: str
    current_employer: str
    summary: str
    skills: list[str]
    languages: list[_Lang]
    experience: list[_Exp]
    education: list[_Edu]
    certifications: list[str]


SYSTEM = """Extrahiere die Angaben aus dem Lebenslauf exakt. Nichts ergänzen oder schönen.
Unbekanntes als leeren String. Datumsangaben als JJJJ-MM, laufende Stellen mit end="heute".
Skills als kurze Einträge, wie sie im Lebenslauf stehen."""


async def import_cv(llm: LLM, cv: Path, profile: Profile, *, overwrite: bool = False) -> Profile:
    text = cv_text(cv)
    if text:
        content: list[dict] = [{"type": "text", "text": f"Lebenslauf:\n\n{text}\n\nBitte extrahieren."}]
    else:  # Bild-PDF: Claude liest die Datei selbst
        content = [file_block(cv), {"type": "text", "text": "Bitte extrahieren."}]
    data = await llm.parse(CVExtract, system=SYSTEM, content=content, max_tokens=6000, cache_system=False)
    p = profile.model_copy(deep=True)

    def take(current: str, new: str) -> str:
        return new if (overwrite or not current) and new else current

    for attr in ("first_name", "last_name", "email", "phone", "city", "linkedin", "github", "website"):
        setattr(p.personal, attr, take(getattr(p.personal, attr), getattr(data.personal, attr)))
    p.work.current_title = take(p.work.current_title, data.current_title)
    p.work.current_employer = take(p.work.current_employer, data.current_employer)
    p.summary = take(p.summary, data.summary)
    if overwrite or not p.skills:
        p.skills = data.skills
    if overwrite or not p.languages:
        p.languages = [Language(**lang.model_dump()) for lang in data.languages]
    if overwrite or not p.experience:
        p.experience = [Experience(**e.model_dump()) for e in data.experience]
    if overwrite or not p.education:
        p.education = [Education(**e.model_dump()) for e in data.education]
    if overwrite or not p.certifications:
        p.certifications = data.certifications
    if not p.documents.cv:
        p.documents.cv = str(cv)
    return p

"""Bewerberprofil: persönliche Daten, Dokumente und Standardantworten."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

TODO = "TODO"


class _Model(BaseModel):
    # In der YAML stehen Zahlen oft ohne Anführungszeichen (75000, 10115) – als Text übernehmen.
    model_config = ConfigDict(coerce_numbers_to_str=True)


class Personal(_Model):
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    street: str = ""
    postal_code: str = ""
    city: str = ""
    country: str = "Deutschland"
    linkedin: str = ""
    github: str = ""
    website: str = ""
    date_of_birth: str = ""
    pronouns: str = ""

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class Work(_Model):
    current_title: str = ""
    current_employer: str = ""
    years_experience_total: str = TODO
    years_experience_relevant: str = TODO
    notice_period: str = TODO
    earliest_start: str = TODO
    salary_expectation_eur: str = TODO
    work_authorization_eu: bool = True
    requires_visa_sponsorship: bool = False
    nationality: str = ""
    willing_to_relocate: bool = False
    workplace_preference: str = "Hybrid in Berlin oder Remote in Deutschland"
    security_clearance: str = ""
    drivers_license: str = ""


class Language(_Model):
    language: str
    level: str


class Experience(_Model):
    company: str
    title: str
    start: str
    end: str = "heute"
    location: str = ""
    highlights: list[str] = Field(default_factory=list)


class Education(_Model):
    institution: str
    degree: str
    start: str = ""
    end: str = ""
    location: str = ""
    grade: str = ""


class Documents(_Model):
    cv: str = ""
    cv_en: str = ""
    certificates: list[str] = Field(default_factory=list)
    cover_letter: Literal["auto", "none"] | str = "auto"

    def resolve(self, value: str, base: Path) -> Path | None:
        if not value or value in ("auto", "none"):
            return None
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = base / path
        return path


class Preferences(_Model):
    cover_letter_language: Literal["auto", "de", "en"] = "auto"
    diversity_questions: Literal["decline", "answer"] = "decline"
    diversity_answers: dict[str, str] = Field(default_factory=dict)
    consent_privacy: bool = True
    consent_talent_pool: bool = False
    newsletter: bool = False
    how_did_you_hear: str = "Karriereseite des Unternehmens"
    tone: str = "sachlich, freundlich, konkret, ohne Floskeln"


class Profile(_Model):
    personal: Personal = Field(default_factory=Personal)
    work: Work = Field(default_factory=Work)
    summary: str = ""
    skills: list[str] = Field(default_factory=list)
    languages: list[Language] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    documents: Documents = Field(default_factory=Documents)
    preferences: Preferences = Field(default_factory=Preferences)
    standard_answers: dict[str, str] = Field(
        default_factory=dict,
        description="Feste Antworten auf wiederkehrende Fragen, z. B. 'Warum wechseln?'",
    )

    # ------------------------------------------------------------------ io
    @classmethod
    def load(cls, path: Path) -> Profile:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls.model_validate(data)

    def save(self, path: Path) -> None:
        path.write_text(
            yaml.safe_dump(self.model_dump(mode="json"), sort_keys=False, allow_unicode=True, width=110),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------ helpers
    def cv_path(self, base: Path, language: str = "de") -> Path | None:
        if language == "en" and self.documents.cv_en:
            return self.documents.resolve(self.documents.cv_en, base)
        return self.documents.resolve(self.documents.cv, base)

    def missing_fields(self) -> list[str]:
        """Felder, die für die meisten Formulare gebraucht werden, aber leer oder TODO sind."""
        checks = {
            "personal.first_name": self.personal.first_name,
            "personal.last_name": self.personal.last_name,
            "personal.email": self.personal.email,
            "personal.phone": self.personal.phone,
            "personal.city": self.personal.city,
            "work.notice_period": self.work.notice_period,
            "work.earliest_start": self.work.earliest_start,
            "work.salary_expectation_eur": self.work.salary_expectation_eur,
            "work.years_experience_total": self.work.years_experience_total,
            "documents.cv": self.documents.cv,
        }
        return [key for key, value in checks.items() if not value or value == TODO]

    def to_prompt(self) -> str:
        """Kompakte, für das Modell gut lesbare Darstellung. TODO-Felder werden als unbekannt markiert."""
        data = self.model_dump(mode="json", exclude={"documents"})

        def clean(value: object) -> object:
            if isinstance(value, dict):
                return {k: clean(v) for k, v in value.items() if v not in ("", [], {}, None)}
            if isinstance(value, list):
                return [clean(v) for v in value]
            if value == TODO:
                return "UNBEKANNT – nicht raten, nachfragen"
            return value

        docs = {
            "cv_verfuegbar": bool(self.documents.cv),
            "cv_englisch_verfuegbar": bool(self.documents.cv_en),
            "zertifikate_anzahl": len(self.documents.certificates),
            "anschreiben": "wird pro Stelle erzeugt"
            if self.documents.cover_letter == "auto"
            else self.documents.cover_letter,
        }
        payload = {"profil": clean(data), "dokumente": docs}
        return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=110)


def normalize_question(text: str) -> str:
    """Schlüssel für die Antwortbank: Kleinbuchstaben, ohne Satzzeichen und Pflichtsternchen."""
    import re

    text = text.lower().replace("*", " ")
    text = re.sub(r"\(optional\)|\(required\)|\(pflichtfeld\)", " ", text)
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:300]

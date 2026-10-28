"""Lebenslauf-Import: Claudes Auszug wird aufbereitet (Ort, PLZ, Links) und überschreibt nichts ungefragt."""

from __future__ import annotations

from typing import Any

from jobslop.cvimport import CVExtract, import_cv
from jobslop.profile import Profile

EXTRACT = {
    "personal": {
        "first_name": "Max",
        "last_name": "Mustermann",
        "email": "neu@example.com",
        "phone": "+49 30 1234567",
        "city": "10115 Berlin, Deutschland",
        "linkedin": "linkedin.com/in/max-mustermann",
        "github": "https://github.com/maxm",
        "website": "",
    },
    "current_title": "Site Reliability Engineer",
    "current_employer": "Beispiel GmbH",
    "summary": "SRE mit Fokus auf Kubernetes.",
    "skills": ["Kubernetes", "Terraform"],
    "languages": [{"language": "Deutsch", "level": "Muttersprache"}],
    "experience": [
        {
            "company": "Beispiel GmbH",
            "title": "SRE",
            "start": "2022-01",
            "end": "heute",
            "location": "Berlin",
            "highlights": ["On-Call aufgebaut"],
        }
    ],
    "education": [],
    "certifications": ["CKA"],
}


class FakeLLM:
    def __init__(self) -> None:
        self.content: list[dict[str, Any]] = []

    async def parse(self, schema, *, system: str, content: list[dict[str, Any]], **_kw: Any):
        self.content = content
        return schema.model_validate(EXTRACT)


async def test_import_fills_gaps_and_normalizes(tmp_path):
    cv = tmp_path / "Max_CV.pdf"
    cv.write_bytes(b"%PDF-1.4\n")  # ohne Textebene: Claude bekommt die Datei selbst
    profile = Profile()
    profile.personal.email = "alt@example.com"
    llm = FakeLLM()
    result = await import_cv(llm, cv, profile)  # type: ignore[arg-type]
    assert llm.content[0]["type"] == "file"
    p = result.personal
    assert (p.first_name, p.last_name) == ("Max", "Mustermann")
    assert p.email == "alt@example.com"  # vorhandene Angabe bleibt
    assert (p.city, p.postal_code) == ("Berlin", "10115")
    assert p.linkedin == "https://linkedin.com/in/max-mustermann" and p.github == "https://github.com/maxm"
    assert result.skills == ["Kubernetes", "Terraform"] and result.certifications == ["CKA"]
    assert result.experience[0].end == "heute"
    assert result.documents.cv == str(cv)
    assert profile.personal.first_name == ""  # das übergebene Profil bleibt unverändert


async def test_import_overwrite_replaces_existing(tmp_path):
    cv = tmp_path / "Max_CV.pdf"
    cv.write_bytes(b"%PDF-1.4\n")
    profile = Profile()
    profile.personal.email = "alt@example.com"
    profile.skills = ["COBOL"]
    profile.documents.cv = str(tmp_path / "alt.pdf")
    result = await import_cv(FakeLLM(), cv, profile, overwrite=True)  # type: ignore[arg-type]
    assert result.personal.email == "neu@example.com"
    assert result.skills == ["Kubernetes", "Terraform"]
    assert result.documents.cv == str(tmp_path / "alt.pdf")  # das gewählte Dokument bleibt


def test_extract_schema_is_strict_enough_for_claude():
    # Jedes Feld Pflicht – Claude soll Unbekanntes als "" liefern statt Felder wegzulassen
    assert set(CVExtract.model_json_schema()["required"]) == set(CVExtract.model_fields)

"""Lebenslauf je Stelle: Faktenprüfung, Ablage pro Stelle und API – mit gefälschtem Claude, ohne Chromium."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from conftest import add_job
from jobslop.apply.executor import Files
from jobslop.apply.planner import JobContext
from jobslop.apply.tailor import (
    CvEntry,
    TailoredCv,
    cached_cv,
    ensure_tailored_cv,
    fact_check,
    sources_for,
    strip_unverified,
    tailored_cv_html,
)
from jobslop.runtime import Runtime
from jobslop.web.app import create_app

JOB = JobContext(
    id=1,
    company="Beispiel GmbH",
    title="Site Reliability Engineer",
    location="Berlin",
    url="https://example.com/jobs/1",
    description="Wir suchen SRE mit Kubernetes, Terraform und Prometheus.",
    language="de",
)


def good_cv(**changes: Any) -> TailoredCv:
    cv = TailoredCv(
        language="de",
        headline="Site Reliability Engineer",
        summary="Site Reliability Engineer mit Schwerpunkt Kubernetes und Terraform auf GCP.",
        skills=["Kubernetes", "Terraform", "Prometheus", "Grafana"],
        experience=[
            CvEntry(
                title="Site Reliability Engineer",
                org="Beispiel Cloud GmbH",
                period="2023-01 – heute",
                bullets=["Betrieb von Kubernetes-Clustern auf GCP", "Terraform-Module gebaut"],
            ),
            CvEntry(title="Linux System Engineer", org="Muster Hosting AG", period="2020-01 – 2022-12"),
        ],
        education=[CvEntry(title="B.Sc. Informatik", org="Beispiel-Universität Berlin", period="2016-10")],
        matched_keywords=["Kubernetes", "Terraform"],
    )
    return cv.model_copy(update=changes)


class FakeLLM:
    """Gibt der Reihe nach die vorgegebenen Entwürfe zurück und merkt sich die Aufrufe."""

    def __init__(self, *drafts: TailoredCv) -> None:
        self.drafts = list(drafts)
        self.calls: list[str] = []

    async def parse(self, schema: type, *, system: str, content: Any, **_kw: Any) -> Any:
        self.calls.append(content if isinstance(content, str) else str(content))
        return self.drafts.pop(0)


class _Page:
    async def set_content(self, html: str, **_kw: Any) -> None:
        self.html = html

    async def pdf(self, path: str, **_kw: Any) -> None:
        Path(path).write_bytes(b"%PDF-1.4\n" + self.html.encode())  # noqa: ASYNC240 (Testattrappe)

    async def close(self) -> None:
        pass


class _Context:
    async def new_page(self) -> _Page:
        return _Page()


@contextlib.asynccontextmanager
async def fake_pdf_context() -> AsyncIterator[Any]:
    yield _Context()


def test_fact_check_accepts_what_the_sources_say(profile, settings):
    sources = sources_for(profile, settings.profile_path.parent)
    assert fact_check(good_cv(), sources) == []


def test_fact_check_catches_inventions(profile, settings):
    sources = sources_for(profile, settings.profile_path.parent)
    cv = good_cv(
        headline="Senior Site Reliability Engineer",  # Seniorität steht nirgends
        skills=["Kubernetes", "AWS Lambda"],  # AWS kommt im Profil nicht vor
    )
    cv.experience[0].bullets.append("Kosten um 37 % gesenkt")  # erfundene Zahl
    kinds = {(p.kind, p.text) for p in fact_check(cv, sources)}
    assert ("title", "Senior Site Reliability Engineer") in kinds
    assert ("skill", "AWS Lambda") in kinds
    assert ("number", "37") in kinds
    other = good_cv()
    other.experience[1].org = "Erfundene Firma KG"
    other.experience[1].period = "2019-01 – 2022-12"
    assert {p.kind for p in fact_check(other, sources)} == {"org"}


def test_strip_removes_only_what_is_unverified(profile, settings):
    sources = sources_for(profile, settings.profile_path.parent)
    cv = good_cv(skills=["Kubernetes", "AWS Lambda"])
    cv.experience[0].bullets.append("Kosten um 37 % gesenkt")
    safe = strip_unverified(cv, fact_check(cv, sources))
    assert safe is not None and safe.skills == ["Kubernetes"]
    assert "Kosten um 37 % gesenkt" not in safe.experience[0].bullets
    assert fact_check(safe, sources) == []
    # Firma oder Titel falsch: kein sicherer Rest
    assert (
        strip_unverified(
            good_cv(headline="Head of SRE"), fact_check(good_cv(headline="Head of SRE"), sources)
        )
        is None
    )


async def test_ensure_tailored_cv_retries_strips_and_caches(profile, settings):
    profile.documents.tailor_cv = True
    bad = good_cv(skills=["Kubernetes", "AWS Lambda"])
    llm = FakeLLM(bad, bad)  # auch der zweite Versuch erfindet – dann wird gekürzt
    files = Files.from_profile(profile, settings.profile_path.parent)
    original = files.cv
    pdf, note = await ensure_tailored_cv(
        llm, profile, JOB, settings.home, settings.profile_path.parent, files, fake_pdf_context
    )
    assert note == "" and pdf is not None and pdf.is_file()
    assert files.cv == files.cv_en == pdf != original
    assert len(llm.calls) == 2 and "AWS Lambda" in llm.calls[1]  # Rückmeldung im zweiten Versuch
    assert b"AWS Lambda" not in pdf.read_bytes() and b"Kubernetes" in pdf.read_bytes()
    _, meta = cached_cv(settings.home, JOB.id)
    assert meta["matched_keywords"] == ["Kubernetes", "Terraform"]
    # zweiter Aufruf: aus der Ablage, ohne Claude
    files2 = Files.from_profile(profile, settings.profile_path.parent)
    again, _ = await ensure_tailored_cv(
        FakeLLM(), profile, JOB, settings.home, settings.profile_path.parent, files2, fake_pdf_context
    )
    assert again == pdf and files2.cv == pdf


async def test_failed_check_keeps_the_original_cv(profile, settings):
    profile.documents.tailor_cv = True
    wrong = good_cv(headline="Head of Platform")
    files = Files.from_profile(profile, settings.profile_path.parent)
    original = files.cv
    pdf, note = await ensure_tailored_cv(
        FakeLLM(wrong, wrong),
        profile,
        JOB,
        settings.home,
        settings.profile_path.parent,
        files,
        fake_pdf_context,
    )
    assert pdf is None and "Original-Lebenslauf" in note and files.cv == original
    # abgeschaltet: nichts passiert, kein Claude-Aufruf
    profile.documents.tailor_cv = False
    assert await ensure_tailored_cv(
        FakeLLM(), profile, JOB, settings.home, settings.profile_path.parent, files, fake_pdf_context
    ) == (None, "")


def test_cv_html_is_plain_and_escaped(profile):
    cv = good_cv(summary="<script>x</script> SRE")
    page = tailored_cv_html(cv, profile)
    assert "<script>x" not in page and "&lt;script&gt;" in page
    assert "<table" not in page and "Berufserfahrung" in page


def test_tailored_cv_api(settings, config, profile, monkeypatch):
    job_id = add_job(settings, "https://example.com/jobs/7", title="Site Reliability Engineer")
    profile.save(settings.profile_path)
    app = create_app(Runtime(settings=settings, config=config, profile=profile))
    client = TestClient(app, headers={"X-Jobslop": "1"})
    assert client.get(f"/api/jobs/{job_id}/cv").json() == {
        "enabled": False,
        "file": None,
        "url": None,
        "matched_keywords": [],
    }
    monkeypatch.setattr("jobslop.web.app.headless_pdf_context", fake_pdf_context)
    app.state.ctx.llm = lambda: FakeLLM(good_cv())
    r = client.post(f"/api/jobs/{job_id}/cv").json()
    assert r["file"].startswith("Lebenslauf_") and r["matched_keywords"] == ["Kubernetes", "Terraform"]
    pdf = client.get(r["url"])
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    # Faktenprüfung nicht bestanden: verständlicher Fehler mit Code
    app.state.ctx.llm = lambda: FakeLLM(good_cv(headline="Head of SRE"), good_cv(headline="Head of SRE"))
    r = client.post(f"/api/jobs/{job_id}/cv")
    assert r.status_code == 422 and r.json()["code"] == "api.cv_rejected"

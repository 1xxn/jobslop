"""Fuzz-Ziele: Funktionen, die fremde Eingaben lesen (Job-Quellen, Bewerbungsseiten, Uploads, Browser-Erweiterung).

Jedes Ziel bekommt Bytes und prüft Eigenschaften, die für jede Eingabe gelten müssen – nicht nur „stürzt nicht ab“.
Atheris mutiert die Eingaben abdeckungsgesteuert (``fuzz/fuzz.py``, Linux, Workflow „Fuzz“); als normaler Test
laufen alle Ziele über ihren Seed-Korpus und über Zufallseingaben (``tests/test_fuzz_targets.py``, jede Plattform).

Meldungen nennen nie die Eingabe: Fuzz-Läufe auf GitHub sind öffentlich, ein Fund gehört nicht ins Log.
"""

from __future__ import annotations

import re
import time
import unicodedata
from collections.abc import Callable

from pydantic import ValidationError

from jobslop.apply.extract import state_from_frames
from jobslop.assist import StepIn, _fetched_from_page
from jobslop.classify import html_to_text
from jobslop.guard import MAX_TITLE, regex_problem
from jobslop.jobpage import FetchedJob, parse_html
from jobslop.web.app import WINDOWS_RESERVED, safe_filename

_SLOW_S = (
    0.5  # ein zulässiger Ausschluss braucht für einen Titel Millisekunden; Sekunden heißt Rückverfolgung
)
_SAFE_NAME = re.compile(r"[\w.\- ]+")
_LD = '<script type="application/ld+json">{}</script>'
_TEXT_FIELDS = ("url", "title", "company", "location", "description", "posted", "via")


def _text(data: bytes) -> str:
    return data.decode("utf-8", "replace")


def html_text(data: bytes) -> None:
    """classify.html_to_text: Stellenbeschreibungen und Mails – Text, nie länger als das HTML."""
    raw = _text(data)
    text = html_to_text(raw)
    assert isinstance(text, str), "kein Text"
    assert len(text) <= len(raw), "Text länger als das HTML"


def job_page(data: bytes) -> None:
    """jobpage.parse_html („Stelle per Link“, Erweiterung): jede Seite und jedes JSON-LD ergibt eine Stelle."""
    raw = _text(data)
    for html in (raw, _LD.format(raw)):
        job = parse_html("https://jobs.example.com/1", html)
        assert isinstance(job, FetchedJob), "keine Stelle"
        assert all(isinstance(getattr(job, name), str) for name in _TEXT_FIELDS), "Feld ist kein Text"
        assert isinstance(job.remote, bool), "remote ist kein Wahrheitswert"


def _hard_titles(pattern: str) -> list[str]:
    """Titel, an denen Rückverfolgung explodiert: Läufe der Zeichen aus dem Ausdruck in vielen Längen, mit und ohne
    fremdes Zeichen am Ende (der Ausdruck passt dann fast, aber nicht ganz)."""
    chars = sorted({c for c in pattern.lower() if c.isalnum() or c == " "})[:4] or ["a"]
    runs = ["".join(chars), *chars]
    titles = []
    for run in runs:
        for size in (8, 16, 24, 32, 48, 64, 100, 150, MAX_TITLE):
            body = (run * size)[:size]
            titles += [body, body[:-1] + "!"]
    return titles


def title_regex(data: bytes) -> None:
    """guard.regex_problem: ein zulässiger Titel-Ausschluss bleibt gegen jeden Titel (≤ 200 Zeichen) schnell."""
    pattern = _text(data)[:300]
    problem = regex_problem(pattern)
    assert isinstance(problem, str), "kein Prüfergebnis"
    if problem:
        return
    rx = re.compile(pattern, re.I)
    for title in _hard_titles(pattern):
        start = time.perf_counter()
        rx.search(title[:MAX_TITLE])
        assert time.perf_counter() - start < _SLOW_S, "zulässiger Ausschluss braucht für einen Titel zu lange"


def upload_name(data: bytes) -> None:
    """web.app.safe_filename: jeder Upload-Name wird ein Dateiname, den jedes System so speichert, wie er ist."""
    name = safe_filename(_text(data))
    assert name, "leerer Name"
    assert _SAFE_NAME.fullmatch(name), "Zeichen außerhalb von Buchstaben, Ziffern, _ . - und Leerzeichen"
    assert name == name.strip(" ."), "Punkt oder Leerzeichen am Rand (Windows entfernt sie stillschweigend)"
    # Windows liest Gerätenamen ohne Leerzeichen davor und mit hochgestellten Ziffern (COM¹ = COM1)
    device = unicodedata.normalize("NFKC", name.split(".")[0].rstrip(" ")).upper()
    assert device not in WINDOWS_RESERVED, "reservierter Windows-Gerätename"
    assert len(name) <= 131, "Name zu lang"
    assert safe_filename(name) == name, "zweiter Durchlauf ändert den Namen"


def extension_step(data: bytes) -> None:
    """assist: Schritt der Browser-Erweiterung – Grenzen im Modell, dann Seitenzustand und Stelle aus der Seite."""
    try:
        body = StepIn.model_validate_json(data)
    except ValidationError:
        return
    state = state_from_frames({frame.index: frame.data.model_dump() for frame in body.frames})
    fetched = _fetched_from_page(state, body.ld_json)
    assert isinstance(fetched, FetchedJob), "keine Stelle"
    assert fetched.title and isinstance(fetched.title, str), "Stelle ohne Titel"


TARGETS: dict[str, Callable[[bytes], None]] = {
    "html_text": html_text,
    "job_page": job_page,
    "title_regex": title_regex,
    "upload_name": upload_name,
    "extension_step": extension_step,
}

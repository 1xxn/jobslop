"""Lebenslauf als Text – einmal lokal aus dem PDF gelesen, damit nicht jeder Claude-Aufruf die Datei öffnen muss."""

from __future__ import annotations

import logging
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)
logging.getLogger("pypdf").setLevel(logging.ERROR)  # Warnungen zu kaputten PDFs behandeln wir selbst


@lru_cache(maxsize=8)
def _extract(path: str, mtime: float) -> str:  # mtime im Schlüssel = Cache wird bei Änderung ungültig
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in (".txt", ".md"):
        return p.read_text(encoding="utf-8", errors="replace").strip()
    if suffix != ".pdf":
        return ""
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(p))
        pages = []
        for page in reader.pages:
            try:  # Layout-Modus trennt Spalten (Firma | Zeitraum) sauberer
                pages.append(page.extract_text(extraction_mode="layout") or "")
            except Exception:
                pages.append(page.extract_text() or "")
    except Exception as exc:  # beschädigtes/verschlüsseltes PDF
        log.warning("Lebenslauf %s nicht lesbar: %s", p, exc)
        return ""
    return clean("\n\n".join(pages))


_UMLAUT = {"a": "ä", "o": "ö", "u": "ü", "A": "Ä", "O": "Ö", "U": "Ü", "e": "ë", "i": "ï"}


def clean(text: str) -> str:
    """Typische PDF-Artefakte (v. a. aus LaTeX) glätten: getrennte Umlaute, Ligaturen, Spalten-Leerraum."""
    text = re.sub(r"¨\s*([aouAOUei])", lambda m: _UMLAUT[m.group(1)], text)
    text = unicodedata.normalize("NFKC", text)  # ﬁ → fi, ﬂ → fl
    lines = []
    for line in text.splitlines():
        line = re.sub(r"\s{3,}", "  ", line.strip())
        lines.append(line)
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def cv_text(path: Path | None) -> str:
    """Text des Lebenslaufs oder "" (z. B. bei eingescannten PDFs – dann liest Claude die Datei selbst)."""
    if not path or not path.exists():
        return ""
    text = _extract(str(path.resolve()), path.stat().st_mtime)
    # Unter ~200 Zeichen ist es fast sicher ein Bild-PDF ohne Textebene.
    return text if len(text) >= 200 else ""

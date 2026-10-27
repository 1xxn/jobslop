"""Regelbasierte Einordnung: Rolle, Level, Ort, Segment, Stack-Match und Prioritäts-Score."""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from html.parser import HTMLParser
from typing import ClassVar

from .config import FilterConfig, RoleConfig, SearchConfig

LEVEL_LABEL = {"J": "Junior", "M": "Mid", "O": "Level offen", "S": "Stretch"}
OTHER = "Other"


def categorize(title: str, roles: list[RoleConfig]) -> str:
    """Erste Zielrolle, deren Stichwort im Titel vorkommt (Reihenfolge = Priorität)."""
    t = title.lower()
    for role in roles:
        if any(_contains_term(t, kw) for kw in role.keywords):
            return role.name
    return OTHER


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text.lower()).strip()


def _contains_term(text: str, term: str) -> bool:
    term = term.lower().strip()
    if not term:
        return False
    if re.fullmatch(r"[a-z0-9]+", term) and len(term) <= 4:
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None
    if len(re.split(r"[\s\-]", term, maxsplit=1)[0]) <= 3:
        # "it engineer" darf nicht in "audit engineer" treffen; lange Begriffe dürfen in Komposita stecken
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}", text) is not None
    return term in text


def level_of(title: str, filters: FilterConfig) -> str:
    t = title.lower()
    if any(m in t for m in filters.stretch_markers):
        return "S"
    if re.search(r"\bjunior\b|\bjr\.?\b|einsteiger|entry|graduate|associate", t):
        return "J"
    if re.search(r"\bmid\b|\bii\b|professional", t):
        return "M"
    return "O"


def title_allowed(title: str, config: SearchConfig) -> tuple[bool, str]:
    t = title.lower()
    filters = config.filters
    if not any(_contains_term(t, inc) for inc in config.title_terms()):
        return False, "Titel passt zu keiner Zielrolle"
    stretch = any(m in t for m in filters.stretch_markers)
    probe = t
    for marker in filters.stretch_markers:
        probe = probe.replace(marker, " ")
    for exc in filters.exclude_titles:
        if _contains_term(probe, exc):
            return False, f"Ausschlussbegriff im Titel: {exc}"
    if stretch and not filters.keep_stretch:
        return False, "Stretch-Rolle (Senior in Klammern)"
    return True, ""


def where_of(location: str, filters: FilterConfig, remote_flag: bool = False) -> str | None:
    """B = vor Ort in einer Wunschstadt (auch hybrid), R = Remote in der Wunschregion, BR = beides. None = passt nicht."""
    loc = _norm(location)
    onsite = any(_norm(city) in loc for city in filters.onsite_locations)
    remote_word = filters.allow_remote and (remote_flag or any(k in loc for k in filters.remote_keywords))
    remote_region = any(_contains_term(loc, r) for r in filters.remote_regions) or loc in ("", "remote")
    remote = remote_word and remote_region
    if onsite and remote:
        return "BR"
    if onsite:
        return "B"
    if remote:
        return "R"
    # Ganz Deutschland ohne Remote-Hinweis (z. B. "Germany") zählt nicht als Remote.
    return None


def stack_fit(text: str, skills: list[str]) -> int:
    t = _norm(text)
    hits = sum(1 for s in skills if _contains_term(t, s))
    if hits >= 6:
        return 3
    if hits >= 3:
        return 2
    return 1


SEGMENT_POINTS = {"big": 3, "tech": 2, "corp": 1, "cons": 0.5, "agency": 0}
LEVEL_POINTS = {"J": 1, "M": 1, "O": 0.5, "S": -4}
SCORE_MAX = 10 + 3 * 2 + 3 + 1 + 1  # erste Zielrolle, Stack ●●●, große Firma, passendes Level, in der Nähe


def score_parts(
    category: str, fit: int, segment: str, level: str, near: bool, where: str, roles: list[str]
) -> list[tuple[str, float]]:
    """Woraus sich der Score zusammensetzt – (Teil, Punkte); das Dashboard erklärt damit jede Zahl."""
    n = max(len(roles), 1)
    idx = roles.index(category) if category in roles else n
    parts = [
        ("role", round(10 * (1 - idx / n), 2)),
        ("stack", float(fit * 2)),
        ("company", float(SEGMENT_POINTS.get(segment, 1))),
        ("level", float(LEVEL_POINTS.get(level, 0))),
    ]
    if near:
        parts.append(("near", 1.0))
    if where == "R":
        parts.append(("remote", -0.5))
    return parts


def score(
    category: str, fit: int, segment: str, level: str, near: bool, where: str, roles: list[str]
) -> float:
    """Priorität: Zielrolle (bis 10 Punkte, erste Rolle am meisten) + Stack-Match + Firma + Level + Ort."""
    return round(sum(p for _, p in score_parts(category, fit, segment, level, near, where, roles)), 2)


def detect_language(text: str) -> str:
    sample = _norm(text[:4000])
    de = len(re.findall(r"\b(und|wir|sie|du|der|die|das|mit|für|fur|erfahrung|kenntnisse)\b", sample))
    en = len(re.findall(r"\b(and|we|you|the|with|for|experience|skills|our)\b", sample))
    return "de" if de > en else "en"


# --------------------------------------------------------------------------- normalization


def match_key(company: str, title: str) -> str:
    comp = _norm(company)
    comp = re.sub(r"\b(gmbh|ag|se|kg|co|inc|ltd|llc|group|gruppe|deutschland|germany)\b", " ", comp)
    tit = _norm(title)
    tit = re.sub(
        r"\((m|w|f|d|x|gn|all|all genders|w/m/d|m/w/d|f/m/d|m/f/d|d/f/m|w/d/m|m/f/x|x/f/m)[^)]*\)", " ", tit
    )
    tit = re.sub(r"[^a-z0-9/ ]", " ", tit)
    comp = re.sub(r"[^a-z0-9 ]", " ", comp)
    return f"{' '.join(comp.split())}|{' '.join(tit.split())}"


def fingerprint(*parts: str) -> str:
    return hashlib.sha1("\x1f".join(parts).encode()).hexdigest()


def content_hash(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(p.strip() for p in parts).encode()).hexdigest()[:32]


class _TextExtractor(HTMLParser):
    BLOCK: ClassVar[set[str]] = {
        "p",
        "div",
        "li",
        "br",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "tr",
        "section",
        "ul",
        "ol",
    }

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "li":
            self.parts.append("\n• ")
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(raw: str) -> str:
    if not raw:
        return ""
    raw = html.unescape(raw) if "&lt;" in raw else raw
    parser = _TextExtractor()
    parser.feed(raw)
    text = "".join(parser.parts)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def classify(
    *, company: str, title: str, description: str, where: str, near: bool, config: SearchConfig
) -> dict[str, object]:
    category = categorize(title, config.roles)
    level = level_of(title, config.filters)
    segment = config.segment_for(company)
    fit = stack_fit(f"{title}\n{description}", config.skills) if description else 1
    return {
        "category": category,
        "level": level,
        "segment": segment,
        "fit": fit,
        "score": score(category, fit, segment, level, near, where, config.role_names),
        "language": detect_language(description or title),
    }

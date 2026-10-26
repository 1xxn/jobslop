"""Regelbasierte Einordnung: Rolle, Level, Ort, Segment, Stack-Match und Prioritäts-Score."""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from html.parser import HTMLParser
from typing import ClassVar

from .config import FilterConfig, SearchConfig

CATEGORIES = ["SRE", "Platform", "DevOps", "Cloud", "System", "Other"]
LEVEL_LABEL = {"J": "Junior", "M": "Mid", "O": "Level offen", "S": "Stretch"}

_CATEGORY_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("SRE", re.compile(r"site reliability|\bsre\b|reliability engineer|observability", re.I)),
    (
        "Platform",
        re.compile(r"platform|plattform|infrastructure engineer|infra engineer|developer platform", re.I),
    ),
    ("DevOps", re.compile(r"devops|dev ops|devsecops|ci/cd|release engineer", re.I)),
    ("Cloud", re.compile(r"cloud|kubernetes|k8s|container", re.I)),
    (
        "System",
        re.compile(
            r"system(s)? (engineer|administrator|admin)|linux|operations engineer|infrastruktur", re.I
        ),
    ),
]


def categorize(title: str) -> str:
    for name, rx in _CATEGORY_RULES:
        if rx.search(title):
            return name
    return "Other"


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text.lower()).strip()


def _contains_term(text: str, term: str) -> bool:
    term = term.lower().strip()
    if not term:
        return False
    if re.fullmatch(r"[a-z0-9]+", term) and len(term) <= 4:
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None
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


def title_allowed(title: str, filters: FilterConfig) -> tuple[bool, str]:
    t = title.lower()
    if not any(_contains_term(t, inc) for inc in filters.include_titles):
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
    """B = Berlin vor Ort/hybrid, R = Remote in Deutschland, BR = beides. None = passt nicht."""
    loc = _norm(location)
    onsite = any(city in loc for city in filters.onsite_locations)
    remote_word = remote_flag or any(k in loc for k in filters.remote_keywords)
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


def score(category: str, fit: int, segment: str, level: str, near: bool, where: str) -> float:
    cat_idx = CATEGORIES.index(category) if category in CATEGORIES else 5
    s = (5 - min(cat_idx, 5)) * 2 + fit * 2
    s += {"big": 3, "tech": 2, "corp": 1, "cons": 0.5, "agency": 0}.get(segment, 1)
    s += {"J": 1, "M": 1, "O": 0.5, "S": -4}.get(level, 0)
    if near:
        s += 1
    if where == "R":
        s -= 0.5
    return round(s, 2)


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
    category = categorize(title)
    level = level_of(title, config.filters)
    segment = config.segment_for(company)
    fit = stack_fit(f"{title}\n{description}", config.skills) if description else 1
    return {
        "category": category,
        "level": level,
        "segment": segment,
        "fit": fit,
        "score": score(category, fit, segment, level, near, where),
        "language": detect_language(description or title),
    }

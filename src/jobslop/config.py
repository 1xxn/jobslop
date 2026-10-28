"""Einstellungen und Suchkonfiguration.

- Laufzeit-Einstellungen (``Settings``): Standardwerte < ``~/.jobslop/settings.toml`` (vom Dashboard gepflegt)
  < ``.env`` < Umgebungsvariablen mit Präfix ``JOBSLOP_``.
- Suchkonfiguration (``SearchConfig``): ``~/.jobslop/search.toml`` – Zielrollen, Filter, Quellen, Limits.
"""

from __future__ import annotations

import logging
import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import tomli_w
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .presets import COMMON_EXCLUDES, LEADERSHIP_EXCLUDES, preset
from .profile import split_city

log = logging.getLogger(__name__)

ApplyMode = Literal["review", "auto", "dry-run"]
ENV_PREFIX = "JOBSLOP_"
LEGACY_ENV_PREFIX = "JOBPILOT_"


class Settings(BaseSettings):
    """Globale Einstellungen. Im Dashboard unter Einstellungen editierbar."""

    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, env_file=".env", extra="ignore")

    home: Path = Field(default_factory=lambda: Path.home() / ".jobslop")
    # Claude Code (Abo-Login). Modelle als Alias: sonnet | opus | haiku – oder ein voller Modellname.
    llm_model: str = "sonnet"
    llm_model_fast: str = "haiku"
    claude_bin: str = ""  # leer = automatisch suchen (PATH, ~/.local/bin/claude[.exe], npm)
    claude_parallel: int = 2  # gleichzeitige Claude-Aufrufe (schont das Abo-Limit)
    claude_timeout_s: int = 300
    claude_effort: str = ""  # optional: low | medium | high
    keep_llm_workdirs: bool = False  # Arbeitsordner der Claude-Aufrufe zum Debuggen behalten
    apply_mode: ApplyMode = "review"
    headless: bool = False
    vision: Literal["auto", "always", "never"] = "auto"
    autofill: bool = True  # Autofill-Buttons der Formulare nutzen (Lebenslauf-Parser, Portal-Profile)
    max_steps_per_application: int = 14
    navigation_timeout_ms: int = 45_000
    user_wait_timeout_s: int = 900
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8765
    # Autopilot: läuft, solange das Dashboard offen ist (oder per `jobslop autopilot` aus dem OS-Planer)
    autopilot_enabled: bool = False
    autopilot_days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])  # 0 = Montag
    autopilot_time: str = "08:00"
    autopilot_apply: bool = True
    autopilot_apply_max: int = 5
    autopilot_apply_mode: ApplyMode = "review"
    # Benachrichtigungen
    notify_desktop: bool = True
    notify_ntfy_url: str = ""  # z. B. https://ntfy.sh/mein-geheimes-thema
    notify_webhook_url: str = ""  # Discord-/Slack-kompatibel (JSON mit "content" und "text")
    follow_up_days: int = 10  # Nachfassen-Erinnerung nach dem Absenden
    # Antworten aus dem Postfach (IMAP, nur lesend; inbox.py). Passwort = App-Passwort, liegt lokal in settings.toml
    inbox_enabled: bool = False
    inbox_host: str = ""  # z. B. imap.gmail.com, outlook.office365.com, imap.web.de
    inbox_port: int = 993
    inbox_user: str = ""
    inbox_password: str = ""
    inbox_folder: str = "INBOX"
    inbox_interval_min: int = 30
    inbox_lookback_days: int = 30  # beim ersten Mal so weit zurück
    setup_completed: bool = False
    # Browser-Erweiterung: LinkedIn/Indeed in deinem eigenen Chrome ausfüllen (Nutzungsbedingungen der Portale!)
    extension_portals: bool = False
    extension_portal_daily_limit: int = 15
    # Demo-Ordner (scripts/demo_data.py): nichts darf echt crawlen, bewerben oder Nachrichten verschicken
    demo: bool = False

    @property
    def db_path(self) -> Path:
        return self.home / "jobslop.db"

    @property
    def profile_path(self) -> Path:
        return self.home / "profile.yaml"

    @property
    def search_path(self) -> Path:
        return self.home / "search.toml"

    @property
    def settings_path(self) -> Path:
        return self.home / "settings.toml"

    @property
    def artifacts_dir(self) -> Path:
        return self.home / "artifacts"

    @property
    def documents_dir(self) -> Path:
        return self.home / "documents"

    @property
    def browser_profile_dir(self) -> Path:
        return self.home / "browser-profile"

    def ensure_dirs(self) -> None:
        for path in (self.home, self.artifacts_dir, self.documents_dir, self.browser_profile_dir):
            path.mkdir(parents=True, exist_ok=True)


class DemoModeError(RuntimeError):
    """Aktion mit echten Folgen (Crawl, Bewerbung, Nachricht) in einem Demo-Ordner."""


def ensure_not_demo(settings: Settings, action: str) -> None:
    if settings.demo:
        raise DemoModeError(
            f"Demo-Modus: {action} ist gesperrt – die Daten in {settings.home} sind erfunden."
        )


# Felder, die das Dashboard ändern darf (Rest nur über Umgebung/.env)
EDITABLE_SETTINGS = {
    "llm_model",
    "llm_model_fast",
    "claude_parallel",
    "claude_effort",
    "apply_mode",
    "headless",
    "vision",
    "autofill",
    "max_steps_per_application",
    "autopilot_enabled",
    "autopilot_days",
    "autopilot_time",
    "autopilot_apply",
    "autopilot_apply_max",
    "autopilot_apply_mode",
    "notify_desktop",
    "notify_ntfy_url",
    "notify_webhook_url",
    "follow_up_days",
    "inbox_enabled",
    "inbox_host",
    "inbox_port",
    "inbox_user",
    "inbox_password",
    "inbox_folder",
    "inbox_interval_min",
    "inbox_lookback_days",
    "setup_completed",
    "extension_portals",
    "extension_portal_daily_limit",
}


def load_env_files(*paths: Path) -> None:
    """Übernimmt KEY=VALUE aus .env-Dateien in die Umgebung, ohne Gesetztes zu überschreiben."""
    for path in paths:
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.removeprefix("export ").split("=", 1)
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def _adopt_legacy_env() -> None:
    """``JOBPILOT_*`` (alter Projektname) weiter verstehen."""
    for key, value in list(os.environ.items()):
        if key.startswith(LEGACY_ENV_PREFIX):
            os.environ.setdefault(ENV_PREFIX + key[len(LEGACY_ENV_PREFIX) :], value)


def migrate_legacy_home() -> Path | None:
    """Zieht ``~/.jobpilot`` einmalig nach ``~/.jobslop`` um. Gibt den neuen Ordner zurück, falls umgezogen."""
    if os.environ.get(ENV_PREFIX + "HOME"):
        return None
    old, new = Path.home() / ".jobpilot", Path.home() / ".jobslop"
    if not old.is_dir() or new.exists():
        return None
    try:
        old.rename(new)
    except OSError as exc:  # z. B. Browser hält Dateien offen – dann am alten Ort weiterarbeiten
        log.warning("Konnte %s nicht nach %s umbenennen (%s) – nutze den alten Ordner", old, new, exc)
        os.environ[ENV_PREFIX + "HOME"] = str(old)
        return None
    legacy_db, db = new / "jobpilot.db", new / "jobslop.db"
    if legacy_db.exists() and not db.exists():
        for suffix in ("", "-wal", "-shm"):
            src = new / f"jobpilot.db{suffix}"
            if src.exists():
                src.rename(new / f"jobslop.db{suffix}")
    profile = new / "profile.yaml"
    if profile.exists():
        text = profile.read_text(encoding="utf-8")
        profile.write_text(
            text.replace(str(old), str(new)).replace(".jobpilot", ".jobslop"), encoding="utf-8"
        )
        settings_file = new / "settings.toml"
        if (
            not settings_file.exists()
        ):  # bestehende Installation: nicht noch einmal durch die Einrichtung schicken
            settings_file.write_text("setup_completed = true\n", encoding="utf-8")
    return new


def read_settings_file(home: Path) -> dict[str, Any]:
    path = home / "settings.toml"
    if not path.is_file():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        log.warning("settings.toml ist ungültig und wird ignoriert: %s", exc)
        return {}
    return {k: v for k, v in data.items() if k in Settings.model_fields}


def load_settings() -> Settings:
    """Einstellungen frisch laden: settings.toml, überlagert von .env und Umgebung."""
    load_env_files(Path.cwd() / ".env")
    _adopt_legacy_env()
    migrate_legacy_home()
    base = Settings()
    load_env_files(base.home / ".env")
    file_values = read_settings_file(base.home)
    overrides = {k: v for k, v in file_values.items() if ENV_PREFIX + k.upper() not in os.environ}
    return Settings(**overrides) if overrides else Settings()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


def save_settings(settings: Settings, updates: dict[str, Any]) -> Settings:
    """Änderungen aus dem Dashboard in settings.toml schreiben und die neuen Einstellungen zurückgeben."""
    unknown = set(updates) - EDITABLE_SETTINGS
    if unknown:
        raise ValueError(f"Nicht änderbar: {', '.join(sorted(unknown))}")
    merged = read_settings_file(settings.home) | updates
    new = settings.model_copy(update=updates)
    Settings.model_validate(new.model_dump())  # Typen prüfen
    settings.home.mkdir(parents=True, exist_ok=True)
    serializable = {k: (str(v) if isinstance(v, Path) else v) for k, v in merged.items()}
    settings.settings_path.write_text(
        "# jobslop – Einstellungen (vom Dashboard verwaltet; Umgebungsvariablen JOBSLOP_* haben Vorrang)\n"
        + tomli_w.dumps(serializable),
        encoding="utf-8",
    )
    get_settings.cache_clear()
    return new


# --------------------------------------------------------------------------- search.toml


class RoleConfig(BaseModel):
    name: str
    keywords: list[str] = Field(default_factory=list)


class FilterConfig(BaseModel):
    include_titles: list[str] = Field(default_factory=list)  # leer = Stichwörter aller Zielrollen
    exclude_titles: list[str] = Field(default_factory=list)
    stretch_markers: list[str] = Field(
        default_factory=lambda: ["(senior)", "(sr.)", "(expert)", "senior/mid", "mid/senior", "senior", "sr."]
    )
    onsite_locations: list[str] = Field(default_factory=lambda: ["berlin"])
    remote_regions: list[str] = Field(default_factory=lambda: ["germany", "deutschland"])
    remote_keywords: list[str] = Field(
        default_factory=lambda: ["remote", "home based", "home-based", "homeoffice"]
    )
    allow_remote: bool = True
    keep_stretch: bool = True


class LimitConfig(BaseModel):
    max_per_company_window: int = 2
    company_window_days: int = 30
    max_applications_per_run: int = 15
    min_delay_seconds: int = 40
    min_score_for_auto_queue: float = 14.0
    max_enrich_per_crawl: int = 60  # Claude-Bewertungen pro Crawl (schont das Abo)


class WorkdaySite(BaseModel):
    company: str
    host: str  # z. B. "sap.wd3.myworkdayjobs.com"
    tenant: str
    site: str
    search_text: str = ""


class GenericPage(BaseModel):
    company: str
    url: str


Portal = Literal["linkedin", "indeed", "glassdoor"]


class SourceConfig(BaseModel):
    # Firmen-Boards (Bewerbungssysteme mit öffentlicher API)
    greenhouse: list[str] = Field(default_factory=list)
    ashby: list[str] = Field(default_factory=list)
    lever: list[str] = Field(default_factory=list)
    smartrecruiters: list[str] = Field(default_factory=list)
    personio: list[str] = Field(default_factory=list)
    recruitee: list[str] = Field(default_factory=list)  # <name>.recruitee.com
    workable: list[str] = Field(default_factory=list)  # apply.workable.com/<name>
    workday: list[WorkdaySite] = Field(default_factory=list)
    amazon_queries: list[str] = Field(default_factory=list)
    amazon_country: str = "DEU"
    # Jobbörsen mit Stichwortsuche: gemeinsame Suchbegriffe; Orte kommen aus filters.onsite_locations
    queries: list[str] = Field(default_factory=list)
    arbeitnow: bool = False
    arbeitnow_max_pages: int = 25
    himalayas: bool = True
    himalayas_country: str = "Germany"
    # Bundesagentur für Arbeit: offizielle Jobsuche, ganz Deutschland, alle Branchen
    arbeitsagentur: bool = True
    arbeitsagentur_radius_km: int = 30
    arbeitsagentur_skip_agencies: bool = True  # Zeitarbeit und private Arbeitsvermittlung auslassen
    # Große Portale über JobSpy (öffentliche Suche ohne Login; Nutzungsbedingungen der Portale beachten)
    portals: list[Portal] = Field(default_factory=lambda: ["linkedin", "indeed"])
    portal_country: str = "germany"
    portal_results: int = 25  # pro Suchbegriff, Ort und Portal
    portal_hours_old: int = 336  # nur Anzeigen der letzten zwei Wochen
    # Firmen aus Jobbörsen auf eigene Boards (Greenhouse, Ashby, Lever …) prüfen und diese direkt abfragen
    discover_boards: bool = True
    discover_max_per_crawl: int = 40
    generic: list[GenericPage] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _legacy_queries(cls, data: Any) -> Any:
        """Bis 1.0 hießen die Suchbegriffe ``himalayas_queries`` und galten nur für Himalayas."""
        if isinstance(data, dict) and "himalayas_queries" in data:
            data = dict(data)
            legacy = data.pop("himalayas_queries") or []
            if not data.get("queries"):
                data["queries"] = legacy
            data.setdefault("himalayas", bool(legacy))
        return data


def _default_roles() -> list[RoleConfig]:
    return [RoleConfig(**r) for r in preset("cloud")["roles"]]


class SearchConfig(BaseModel):
    roles: list[RoleConfig] = Field(default_factory=_default_roles)
    filters: FilterConfig = Field(default_factory=FilterConfig)
    limits: LimitConfig = Field(default_factory=LimitConfig)
    sources: SourceConfig = Field(default_factory=SourceConfig)
    segments: dict[str, list[str]] = Field(default_factory=dict)
    skills: list[str] = Field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> SearchConfig:
        if not path.exists():
            return default_search_config()
        return cls.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self.model_dump(mode="json", exclude_defaults=False)
        path.write_text(SEARCH_HEADER + tomli_w.dumps(data), encoding="utf-8")

    @property
    def role_names(self) -> list[str]:
        return [r.name for r in self.roles]

    def title_terms(self) -> list[str]:
        """Begriffe, von denen ein Titel mindestens einen enthalten muss."""
        if self.filters.include_titles:
            return self.filters.include_titles
        return [kw for role in self.roles for kw in role.keywords]

    def segment_for(self, company: str) -> str:
        name = company.lower()
        for segment, companies in self.segments.items():
            if any(c.lower() in name for c in companies):
                return segment
        return "tech"


SEARCH_HEADER = """# jobslop – Suchkonfiguration (im Dashboard unter Einstellungen → Suche editierbar)
# roles: Zielrollen in Prioritätsreihenfolge, jeweils mit Titel-Stichwörtern.
# filters.include_titles: leer = Stichwörter aller Rollen. exclude_titles: Titel mit diesen Begriffen fliegen raus.
# "Senior" & Co. (stretch_markers) fliegen nicht raus, sondern landen mit niedrigerem Score weiter unten.

"""

DEFAULT_SEGMENTS = {
    "big": ["amazon", "aws", "google", "microsoft", "sap", "sony", "meta", "apple", "netflix"],
    "corp": [
        "bundesdruckerei",
        "deutsche bahn",
        "gematik",
        "50hertz",
        "bwi",
        "kfw",
        "toll collect",
        "thales",
        "deutsche bank",
        "allianz",
        "telekom",
        "siemens",
        "bosch",
        "volkswagen",
        "bmw",
        "mercedes",
    ],
    "cons": [
        "sii",
        "prodyna",
        "capgemini",
        "adesso",
        "pwc",
        "computacenter",
        "reply",
        "exxeta",
        "inovex",
        "materna",
        "t-systems",
        "deloitte",
        "cgi",
        "bechtle",
        "accenture",
        "msg systems",
        "sopra steria",
        "kpmg",
        "ey ",
    ],
    "agency": [
        "build & hire",
        "digital waffle",
        "xpertdirect",
        "instaffo",
        "vesterling",
        "computer futures",
        "robert walters",
        "hays",
        "randstad",
        "michael page",
        "gulp",
    ],
}

DEFAULT_SOURCES = SourceConfig(
    greenhouse=[
        "n26",
        "hellofresh",
        "getyourguide",
        "contentful",
        "sumup",
        "wolt",
        "celonis",
        "raisin",
        "solarisbank",
        "soundcloud71",
        "grafanalabs",
        "gitlab",
        "elastic",
        "canonical",
        "datadog",
        "cloudflare",
        "mongodb",
        "databricks",
        "doctolib",
        "helsing",
        "parloa",
        "trivago",
        "coinbase",
        "vercel",
        "ionos",
        "traderepublicbank",
        "jetbrains",
        "commercetools",
        "zattoo",
        "emnify",
        "talonone",
        "nebius",
        "stripe",
        "cockroachlabs",
        "chainguard",
        "flix",
        "moonfare",
        "grover",
        "thoughtworks",
        "bitpanda",
    ],
    ashby=[
        "n8n",
        "deepl",
        "upvest",
        "enpal",
        "moss",
        "pliant",
        "qonto",
        "elevenlabs",
        "langdock",
        "knowunity",
        "tacto",
        "clark",
        "tourlane",
        "flink",
        "buena",
        "black-forest-labs",
        "zenjob",
        "forto",
        "langchain",
        "billie",
        "heyjobs",
    ],
    lever=["unzer", "spotify"],
    smartrecruiters=["DeliveryHero", "Auto1", "BoschGroup", "Sixt", "Canva", "Continental", "ServiceNow"],
    personio=["ottonova", "tado", "gridx"],
    amazon_queries=["engineer", "devops", "site reliability", "systems engineer"],
    arbeitnow=True,
    queries=list(preset("cloud")["search_queries"]),
    generic=[GenericPage(company="Zalando", url="https://jobs.zalando.com/en/jobs?search=engineer")],
)


def search_config_from_preset(
    names: list[str],
    *,
    cities: list[str] | None = None,
    remote: bool = True,
    exclude_leadership: bool = True,
) -> SearchConfig:
    """Suchkonfiguration aus einer oder mehreren Vorlagen (Einrichtungsassistent)."""
    names = names or ["cloud"]
    roles: list[RoleConfig] = []
    excludes = list(COMMON_EXCLUDES) + (list(LEADERSHIP_EXCLUDES) if exclude_leadership else [])
    skills: list[str] = []
    queries: list[str] = []
    wanted_terms: set[str] = set()
    for name in names:
        p = preset(name)
        roles += [RoleConfig(**r) for r in p["roles"]]
        wanted_terms |= {kw for r in p["roles"] for kw in r["keywords"]}
        skills += p["skills"]
        queries += p["search_queries"]
    for name in names:  # Ausschlüsse einer Vorlage dürfen Zielrollen einer anderen nicht blockieren
        excludes += [e for e in preset(name)["excludes"] if e.strip() not in wanted_terms]
    sources = DEFAULT_SOURCES.model_copy(deep=True)
    sources.queries = list(dict.fromkeys(queries))
    remote_regions = ["germany", "deutschland", "europe", "europa", "european union", "eu", "emea", "dach"]
    return SearchConfig(
        roles=roles,
        filters=FilterConfig(
            exclude_titles=list(dict.fromkeys(excludes)),
            # „Berlin, Deutschland“ (so steht es oft im Profil) muss als „berlin“ filtern, sonst passt keine Stelle
            onsite_locations=list(
                dict.fromkeys(city.lower() for c in (cities or ["berlin"]) if (city := split_city(c)[0]))
            ),
            remote_regions=[*remote_regions, "worldwide", "anywhere"],
            allow_remote=remote,
        ),
        sources=sources,
        segments=DEFAULT_SEGMENTS,
        skills=list(dict.fromkeys(skills)),
    )


def default_search_config() -> SearchConfig:
    return search_config_from_preset(["cloud"], cities=["berlin", "potsdam"])

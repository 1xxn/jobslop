"""Laufzeit-Einstellungen (Umgebung/.env) und Suchkonfiguration (search.toml)."""

from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ApplyMode = Literal["review", "auto", "dry-run"]


class Settings(BaseSettings):
    """Globale Einstellungen. Werte kommen aus Umgebungsvariablen (Präfix ``JOBPILOT_``) oder ``.env``."""

    model_config = SettingsConfigDict(env_prefix="JOBPILOT_", env_file=".env", extra="ignore")

    home: Path = Field(default_factory=lambda: Path.home() / ".jobpilot")
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
    max_steps_per_application: int = 14
    navigation_timeout_ms: int = 45_000
    user_wait_timeout_s: int = 900
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8765

    @property
    def db_path(self) -> Path:
        return self.home / "jobpilot.db"

    @property
    def profile_path(self) -> Path:
        return self.home / "profile.yaml"

    @property
    def search_path(self) -> Path:
        return self.home / "search.toml"

    @property
    def artifacts_dir(self) -> Path:
        return self.home / "artifacts"

    @property
    def browser_profile_dir(self) -> Path:
        return self.home / "browser-profile"

    def ensure_dirs(self) -> None:
        for path in (self.home, self.artifacts_dir, self.browser_profile_dir):
            path.mkdir(parents=True, exist_ok=True)


def load_env_files(*paths: Path) -> None:
    """Übernimmt KEY=VALUE aus .env-Dateien in die Umgebung (JOBPILOT_*), ohne Gesetztes zu überschreiben."""
    import os

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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_env_files(Path.cwd() / ".env")
    settings = Settings()
    load_env_files(settings.home / ".env")
    return settings


# --------------------------------------------------------------------------- search.toml


class FilterConfig(BaseModel):
    include_titles: list[str] = Field(default_factory=list)
    exclude_titles: list[str] = Field(default_factory=list)
    stretch_markers: list[str] = Field(
        default_factory=lambda: ["(senior)", "(sr.)", "(expert)", "senior/mid", "mid/senior"]
    )
    onsite_locations: list[str] = Field(default_factory=lambda: ["berlin"])
    remote_regions: list[str] = Field(default_factory=lambda: ["germany", "deutschland"])
    remote_keywords: list[str] = Field(
        default_factory=lambda: ["remote", "home based", "home-based", "homeoffice"]
    )
    keep_stretch: bool = True


class LimitConfig(BaseModel):
    max_per_company_window: int = 2
    company_window_days: int = 30
    max_applications_per_run: int = 15
    min_delay_seconds: int = 40
    min_score_for_auto_queue: float = 14.0


class WorkdaySite(BaseModel):
    company: str
    host: str  # z. B. "sap.wd3.myworkdayjobs.com"
    tenant: str
    site: str
    search_text: str = ""


class GenericPage(BaseModel):
    company: str
    url: str


class SourceConfig(BaseModel):
    greenhouse: list[str] = Field(default_factory=list)
    ashby: list[str] = Field(default_factory=list)
    lever: list[str] = Field(default_factory=list)
    smartrecruiters: list[str] = Field(default_factory=list)
    personio: list[str] = Field(default_factory=list)
    workday: list[WorkdaySite] = Field(default_factory=list)
    amazon_queries: list[str] = Field(default_factory=list)
    amazon_country: str = "DEU"
    generic: list[GenericPage] = Field(default_factory=list)


class SearchConfig(BaseModel):
    filters: FilterConfig = Field(default_factory=FilterConfig)
    limits: LimitConfig = Field(default_factory=LimitConfig)
    sources: SourceConfig = Field(default_factory=SourceConfig)
    segments: dict[str, list[str]] = Field(default_factory=dict)
    skills: list[str] = Field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> SearchConfig:
        if not path.exists():
            return cls.model_validate(tomllib.loads(DEFAULT_SEARCH_TOML))
        return cls.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))

    def segment_for(self, company: str) -> str:
        name = company.lower()
        for segment, companies in self.segments.items():
            if any(c.lower() in name for c in companies):
                return segment
        return "tech"


DEFAULT_SEARCH_TOML = r"""# jobpilot – Suchkonfiguration
# Alles hier ist editierbar. Nach Änderungen einfach `jobpilot crawl` erneut ausführen.

# Stack-Begriffe für den Stack-Match (0–3). Zählt Treffer in der Stellenbeschreibung.
skills = ["gcp", "google cloud", "kubernetes", "k8s", "terraform", "helm", "docker", "python", "bash",
          "go", "golang", "prometheus", "grafana", "gitlab", "ci/cd", "observability", "sre", "slo", "linux"]

[filters]
# Titel müssen mindestens einen dieser Begriffe enthalten (Kleinschreibung egal).
include_titles = ["site reliability", "sre", "platform", "plattform", "devops", "dev ops", "cloud",
                  "infrastructure", "infrastruktur", "kubernetes", "k8s", "systems engineer", "system engineer",
                  "production engineer", "operations engineer", "observability"]
# Titel mit diesen Begriffen fliegen raus. "(Senior)" in Klammern bleibt als Stretch erhalten.
exclude_titles = ["senior", "sr.", "staff", "principal", "lead", "head of", "manager", "director", "architect",
                  "intern", "internship", "werkstudent", "working student", "praktik", "thesis", "sales",
                  "account", "data engineer", "data platform", "machine learning", "frontend", "android", "ios",
                  "duales studium", "ausbildung", "teamleit"]
onsite_locations = ["berlin"]
remote_regions = ["germany", "deutschland", "europe", "european union", "emea", "dach"]
keep_stretch = true

[limits]
max_per_company_window = 2      # höchstens 2 Bewerbungen pro Firma …
company_window_days = 30        # … innerhalb von 30 Tagen
max_applications_per_run = 15
min_delay_seconds = 40          # Pause zwischen zwei Bewerbungen
min_score_for_auto_queue = 14.0 # `jobpilot queue add --top` nimmt nur Jobs ab diesem Score

[segments]
big = ["amazon", "aws", "google", "microsoft", "sap", "sony", "meta", "apple", "netflix"]
corp = ["bundesdruckerei", "deutsche bahn", "gematik", "50hertz", "bwi", "kfw", "toll collect", "thales",
        "bew ", "ewe", "trox", "drees", "gsk stockmann", "breuninger", "deutsche bank", "allianz", "telekom"]
cons = ["sii", "prodyna", "capgemini", "adesso", "pwc", "computacenter", "reply", "exxeta", "seitenbau",
        "pta", "mgm", "inovex", "materna", "t-systems", "deloitte", "cgi", "bechtle", "sva", "hcltech",
        "accenture", "msg systems", "sopra steria", "glueckkanja", "group24", "virtual7", "adfinis"]
agency = ["build & hire", "digital waffle", "xpertdirect", "instaffo", "vesterling", "whybrilliant", "jobster",
          "computer futures", "robert walters", "hays", "randstad"]

[sources]
# Öffentliche Job-Board-APIs der Bewerbungssysteme. Board-Namen stehen in der URL der Karriereseite,
# z. B. job-boards.greenhouse.io/<board> oder jobs.ashbyhq.com/<board>.
greenhouse = ["n26", "hellofresh", "getyourguide", "contentful", "sumup", "wolt", "celonis", "raisin",
              "solarisbank", "soundcloud71", "grafanalabs", "gitlab", "elastic", "canonical", "datadog",
              "cloudflare", "mongodb", "databricks", "doctolib", "helsing", "parloa", "trivago", "coinbase",
              "vercel", "ionos", "traderepublicbank", "jetbrains", "commercetools", "zattoo", "emnify",
              "talonone", "nebius", "stripe", "cockroachlabs"]
ashby = ["n8n", "deepl", "upvest", "enpal", "moss", "pliant", "qonto", "elevenlabs", "langdock", "knowunity",
         "tacto", "clark", "tourlane", "flink"]
lever = []                       # z. B. "company-slug" aus jobs.lever.co/<slug>
smartrecruiters = ["DeliveryHero", "Auto1", "BoschGroup", "Sixt", "Canva"]
personio = []                    # z. B. "firma" aus firma.jobs.personio.de
amazon_queries = ["engineer", "devops", "site reliability", "systems engineer"]
amazon_country = "DEU"

# Workday-Karriereseiten: host/tenant/site stehen in der URL, z. B.
# https://<tenant>.wd3.myworkdayjobs.com/<site>
# [[sources.workday]]
# company = "Beispiel AG"
# host = "beispiel.wd3.myworkdayjobs.com"
# tenant = "beispiel"
# site = "Careers"
# search_text = "devops"

# Beliebige Karriereseiten: Seite wird im Browser gerendert, Claude liest die Stellen heraus.
[[sources.generic]]
company = "Zalando"
url = "https://jobs.zalando.com/en/jobs?search=reliability"

[[sources.generic]]
company = "Zalando"
url = "https://jobs.zalando.com/en/jobs?search=platform"
"""

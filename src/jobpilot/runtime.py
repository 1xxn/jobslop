"""Gemeinsamer Aufbau für CLI und Dashboard: Einstellungen, Profil, LLM, Planer, Engine."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .apply.engine import ApplyEngine, BrowserSession, load_answers
from .apply.interact import Interactor
from .apply.planner import HeuristicPlanner, LLMPlanner, Planner
from .config import DEFAULT_SEARCH_TOML, ApplyMode, SearchConfig, Settings, get_settings
from .db import get_engine
from .llm import LLM, try_llm
from .profile import Profile

log = logging.getLogger(__name__)

EXAMPLE_PROFILE = Path(__file__).parent / "examples" / "profile.yaml"


@dataclass
class Runtime:
    settings: Settings
    config: SearchConfig
    profile: Profile

    @classmethod
    def load(cls, settings: Settings | None = None) -> Runtime:
        settings = settings or get_settings()
        settings.ensure_dirs()
        get_engine(settings.db_path)
        config = SearchConfig.load(settings.search_path)
        profile = Profile.load(settings.profile_path) if settings.profile_path.exists() else Profile()
        return cls(settings=settings, config=config, profile=profile)

    def llm(self) -> LLM | None:
        return try_llm(self.settings)

    def planner(self, llm: LLM | None, *, offline: bool = False) -> Planner:
        answers = load_answers(self.settings.db_path)
        if llm is None or offline:
            return HeuristicPlanner(self.profile, answers)
        return LLMPlanner(
            llm,
            self.profile,
            self.settings.profile_path.parent,
            answers,
            cover_letter_auto=self.profile.documents.cover_letter == "auto",
        )

    def engine(
        self,
        *,
        browser: BrowserSession,
        interactor: Interactor,
        mode: ApplyMode,
        offline: bool = False,
        on_event: Callable[[str], None] | None = None,
    ) -> ApplyEngine:
        llm = None if offline else self.llm()
        return ApplyEngine(
            settings=self.settings,
            config=self.config,
            profile=self.profile,
            planner=self.planner(llm, offline=offline),
            interactor=interactor,
            browser=browser,
            llm=llm,
            mode=mode,
            on_event=on_event,
        )


def init_home(settings: Settings, *, force: bool = False) -> list[str]:
    """Legt Arbeitsverzeichnis, search.toml und profile.yaml an. Gibt die erstellten Dateien zurück."""
    settings.ensure_dirs()
    created = []
    if force or not settings.search_path.exists():
        settings.search_path.write_text(DEFAULT_SEARCH_TOML, encoding="utf-8")
        created.append(str(settings.search_path))
    if force or not settings.profile_path.exists():
        settings.profile_path.write_text(EXAMPLE_PROFILE.read_text(encoding="utf-8"), encoding="utf-8")
        created.append(str(settings.profile_path))
    get_engine(settings.db_path)
    return created

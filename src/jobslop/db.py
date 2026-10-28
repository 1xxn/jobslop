"""SQLite-Datenbank: Jobs mit Snapshot-History, Crawl-Läufe, Bewerbungen, Ausschlüsse, Antwortbank."""

from __future__ import annotations

import sqlite3
import threading
import weakref
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
    event,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker
from sqlalchemy.schema import CreateIndex


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: JSON, list[Any]: JSON}


class CrawlRun(Base):
    __tablename__ = "crawl_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="running")
    sources: Mapped[list[Any]] = mapped_column(JSON, default=list)
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    errors: Mapped[list[Any]] = mapped_column(JSON, default=list)

    snapshots: Mapped[list[JobSnapshot]] = relationship(back_populates="crawl_run")


class Job(Base):
    __tablename__ = "jobs"
    # Die Beschreibung (mehrere KB) liegt vor status/queued/first_seen – ohne Index liest SQLite für jeden Filter
    # die Überlaufseiten aller Zeilen. Mit Index beantworten Zähler und Ansichten das aus dem Index.
    __table_args__ = (
        Index("ix_jobs_state", "status", "queued", "starred"),
        Index("ix_jobs_first_seen", "first_seen"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    match_key: Mapped[str] = mapped_column(String(300), index=True)
    source: Mapped[str] = mapped_column(String(40))
    external_id: Mapped[str] = mapped_column(String(200), default="")
    company: Mapped[str] = mapped_column(String(200), index=True)
    title: Mapped[str] = mapped_column(String(400))
    location: Mapped[str] = mapped_column(String(400), default="")
    where: Mapped[str] = mapped_column(String(4), default="B")  # B, R, BR
    workplace: Mapped[str] = mapped_column(String(20), default="")  # Hybrid, Vor Ort, Remote
    url: Mapped[str] = mapped_column(Text)
    apply_url: Mapped[str] = mapped_column(Text, default="")
    alt_urls: Mapped[list[Any]] = mapped_column(JSON, default=list)
    category: Mapped[str] = mapped_column(String(20), default="Other")
    level: Mapped[str] = mapped_column(String(2), default="O")  # J, M, O, S
    segment: Mapped[str] = mapped_column(String(20), default="tech")
    fit: Mapped[int] = mapped_column(Integer, default=1)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    language: Mapped[str] = mapped_column(String(5), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    posted: Mapped[str] = mapped_column(String(40), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    near: Mapped[str] = mapped_column(String(100), default="")
    origin: Mapped[str] = mapped_column(String(20), default="crawl")  # seed, crawl, manual
    status: Mapped[str] = mapped_column(String(20), default="open")  # open, closed
    queued: Mapped[bool] = mapped_column(default=False)
    starred: Mapped[bool] = mapped_column(default=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    enrichment: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    snapshots: Mapped[list[JobSnapshot]] = relationship(back_populates="job", order_by="JobSnapshot.id")
    applications: Mapped[list[Application]] = relationship(back_populates="job", order_by="Application.id")

    @property
    def target_url(self) -> str:
        return self.apply_url or self.url


class JobSnapshot(Base):
    __tablename__ = "job_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    crawl_run_id: Mapped[int | None] = mapped_column(ForeignKey("crawl_runs.id"), index=True)
    seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    change: Mapped[str] = mapped_column(String(20))  # new, unchanged, updated, closed, reopened, imported
    title: Mapped[str] = mapped_column(String(400))
    location: Mapped[str] = mapped_column(String(400), default="")
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    diff: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    job: Mapped[Job] = relationship(back_populates="snapshots")
    crawl_run: Mapped[CrawlRun | None] = relationship(back_populates="snapshots")


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)
    # running, needs_input, needs_review, ready, paused (Abo-Limit), submitted, failed, skipped, manual, interview, rejected, offer
    origin: Mapped[str] = mapped_column(String(20), default="jobslop")  # jobslop, manual, import
    mode: Mapped[str] = mapped_column(String(10), default="review")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    artifacts_dir: Mapped[str] = mapped_column(Text, default="")
    final_url: Mapped[str] = mapped_column(Text, default="")
    confirmation: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    open_questions: Mapped[list[Any]] = mapped_column(JSON, default=list)
    filled: Mapped[list[Any]] = mapped_column(JSON, default=list)
    usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    notes: Mapped[str] = mapped_column(Text, default="")
    follow_up_at: Mapped[datetime | None] = mapped_column(DateTime)
    stage_changed_at: Mapped[datetime | None] = mapped_column(DateTime)

    job: Mapped[Job] = relationship(back_populates="applications")
    events: Mapped[list[ApplicationEvent]] = relationship(
        back_populates="application", order_by="ApplicationEvent.id", cascade="all, delete-orphan"
    )


class ApplicationEvent(Base):
    __tablename__ = "application_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    kind: Mapped[str] = mapped_column(String(30))
    message: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    application: Mapped[Application] = relationship(back_populates="events")


class Exclusion(Base):
    __tablename__ = "exclusions"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))  # company, job, title, url
    value: Mapped[str] = mapped_column(String(400))
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Board(Base):
    """Firmen-Board, das jobslop selbst gesucht hat (kind leer = keins gefunden, wird später erneut geprüft)."""

    __tablename__ = "boards"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    company: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), default="")  # greenhouse, ashby, lever, recruitee …
    slug: Mapped[str] = mapped_column(String(200), default="")
    jobs: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(default=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Answer(Base):
    __tablename__ = "answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_key: Mapped[str] = mapped_column(String(300), unique=True, index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    uses: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class InboxMessage(Base):
    """Mail aus dem Postfach, die zu einer Bewerbung gehört (inbox.py). Absage, Einladung und Angebot warten als
    Vorschlag (open), bis du sie übernimmst (applied) oder verwirfst (dismissed); Bestätigungen sind „logged“."""

    __tablename__ = "inbox_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[str] = mapped_column(String(300), unique=True, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    sender: Mapped[str] = mapped_column(String(300), default="")
    subject: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(20))  # confirmation, rejection, interview, offer
    summary: Mapped[str] = mapped_column(Text, default="")
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    application: Mapped[Application] = relationship()


class Prompt(Base):
    """Offene Rückfrage eines laufenden Bewerbungsprozesses (Fragen, Freigabe, Übergabe an den Menschen)."""

    __tablename__ = "prompts"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # questions, confirm, handoff
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    response: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)  # open, answered, expired
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime)


class Activity(Base):
    """Feed für die Übersicht: Crawls, Autopilot, Bewerbungsläufe, Statuswechsel."""

    __tablename__ = "activity"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    kind: Mapped[str] = mapped_column(String(30))  # crawl, autopilot, run, status, setup
    message: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


# --------------------------------------------------------------------------- engine/session

_engines: dict[Path, Engine] = {}
MMAP_SIZE = 256 * 1024 * 1024  # größere Datenbanken lesen den Rest wie bisher


def get_engine(db_path: Path) -> Engine:
    if db_path not in _engines:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(f"sqlite:///{db_path}", future=True)

        @event.listens_for(engine, "connect")
        def _pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            # FULL ist auch der Standard – hier fest, weil „abgeschickt“ einen Stromausfall überleben muss (sonst droht
            # eine zweite Bewerbung). Nicht für Tempo lockern.
            cur.execute("PRAGMA synchronous=FULL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=5000")
            # Lesen über Memory-Mapping statt read(): Listen, Zähler und Crawl lesen jede Zeile, das war unter Windows
            # der größte Posten (gemessen bei 20.000 Stellen: Faktor 3). Schreiben geht weiter über das WAL.
            cur.execute(f"PRAGMA mmap_size={MMAP_SIZE}")
            cur.close()

        Base.metadata.create_all(engine)
        _add_missing_columns(engine)
        _add_missing_indexes(engine)
        _engines[db_path] = engine
    return _engines[db_path]


def _add_missing_columns(engine: Engine) -> None:
    """Leichte Migration: neue Spalten in bestehenden Datenbanken ergänzen (SQLite: ALTER TABLE ADD COLUMN)."""
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {row[1] for row in conn.exec_driver_sql(f'PRAGMA table_info("{table.name}")')}
            for column in table.columns:
                if column.name in existing:
                    continue
                ddl_type = column.type.compile(dialect=engine.dialect)
                default = (
                    getattr(column.default, "arg", None)
                    if column.default is not None and column.default.is_scalar
                    else None
                )
                clause = ""
                if isinstance(default, bool):
                    clause = f" DEFAULT {int(default)}"
                elif isinstance(default, int | float):
                    clause = f" DEFAULT {default}"
                elif isinstance(default, str):
                    clause = " DEFAULT '" + default.replace("'", "''") + "'"
                conn.exec_driver_sql(
                    f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {ddl_type}{clause}'
                )
        # Pfade aus der Zeit vor der Umbenennung (~/.jobpilot → ~/.jobslop)
        conn.exec_driver_sql(
            "UPDATE applications SET artifacts_dir = REPLACE(artifacts_dir, '.jobpilot', '.jobslop') "
            "WHERE artifacts_dir LIKE '%.jobpilot%'"
        )


def _add_missing_indexes(engine: Engine) -> None:
    """``create_all`` legt Indizes nur mit neuen Tabellen an – bestehende Datenbanken bekommen sie hier. Nur
    Indizes für Tempo: ein nachträglicher UNIQUE-Index scheiterte an alten Dubletten und verhinderte den Start.
    ``IF NOT EXISTS``, weil Dashboard und Bewerbungslauf gleichzeitig starten können."""
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            for index in table.indexes:
                if not index.unique:
                    conn.execute(CreateIndex(index, if_not_exists=True))


class ChangeCounter:
    """Ändert sich, sobald irgendwer in die Datenbank schreibt – Dashboard, Bewerbungslauf oder CLI.

    ``PRAGMA data_version`` einer eigenen Verbindung zählt jedes Commit aller anderen Verbindungen (auch aus
    anderen Prozessen). Damit lassen sich teure Auswertungen zwischen zwei Abrufen wiederverwenden, solange sich
    nichts geändert hat."""

    def __init__(self, db_path: Path) -> None:
        get_engine(db_path)  # Datei und Schema anlegen
        conn = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self._conn = conn
        self._lock = threading.Lock()
        self._close = weakref.finalize(self, conn.close)  # spätestens beim Aufräumen schließen

    def value(self) -> int:
        with self._lock:
            return int(self._conn.execute("PRAGMA data_version").fetchone()[0])

    def close(self) -> None:
        """Verbindung schließen (unter Windows hält sie sonst die Datenbankdatei offen)."""
        with self._lock:
            self._close()


@contextmanager
def session_scope(db_path: Path) -> Iterator[Session]:
    factory = sessionmaker(bind=get_engine(db_path), expire_on_commit=False)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def first(session: Session, stmt):  # small helper for scalar lookups
    return session.execute(stmt).scalars().first()


__all__ = [
    "Activity",
    "Answer",
    "Application",
    "ApplicationEvent",
    "Base",
    "CrawlRun",
    "Exclusion",
    "Job",
    "JobSnapshot",
    "Prompt",
    "first",
    "get_engine",
    "select",
    "session_scope",
    "utcnow",
]

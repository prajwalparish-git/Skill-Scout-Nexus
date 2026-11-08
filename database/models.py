"""Telemetry tables as SQLAlchemy 2 typed models, portable across PostgreSQL and SQLite.

Only portable column types are used (JSON, DateTime, Text, Integer, Float), so the same
metadata creates the same tables on either engine. Ranges are enforced twice: by crud.py with a
readable message, and by CHECK constraints as the last line of defence. Timestamps are stored
in UTC and always read back timezone-aware (UTCDateTime), whichever engine holds them.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Engine,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    TypeDecorator,
    UniqueConstraint,
    func,
    inspect,
    text,
)
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from piq.config import VOICE_CRITERION_MAX, VOICE_RUBRIC_MAX


def utc_now() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """A UTC timestamp that reads back timezone-aware on PostgreSQL and SQLite alike. SQLite
    has no zone, so it stores naive UTC; a naive value written by a caller counts as UTC."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        value = (value if value.tzinfo else value.replace(tzinfo=UTC)).astimezone(UTC)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class Base(DeclarativeBase):
    pass


def _student_fk() -> Mapped[int]:
    return mapped_column(Integer, ForeignKey("student_profiles.id", ondelete="CASCADE"), index=True)


class Organization(Base):
    """An organization's public profile (a university, a college, a corporate L&D team). The
    admin's password hash, verification state and lockout counters are sign-in state: they stay
    in piq's own file and never reach this table or the cloud copy. Matched across machines by
    `org_code`."""

    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_code: Mapped[str] = mapped_column(String(30), unique=True)  # DBIT-BLR-2027
    name: Mapped[str] = mapped_column(String(200))
    org_type: Mapped[str] = mapped_column(String(40))
    official_domain: Mapped[str | None] = mapped_column(String(120))
    admin_name: Mapped[str] = mapped_column(String(120))
    admin_email: Mapped[str] = mapped_column(String(254))
    contact_phone: Mapped[str | None] = mapped_column(String(30))
    location: Mapped[str | None] = mapped_column(String(120))
    academic_batch: Mapped[str | None] = mapped_column(String(20))
    quiz_cutoff_pct: Mapped[int] = mapped_column(Integer, default=70)
    voice_cutoff_score: Mapped[int] = mapped_column(Integer, default=10)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)


class StudentProfile(Base):
    __tablename__ = "student_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(20), unique=True)  # lower-cased, as piq keeps it
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(254))
    stream: Mapped[str] = mapped_column(String(40), index=True)  # Engineering, Commerce, ...
    department: Mapped[str | None] = mapped_column(String(120))
    target_role: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    # Organization columns (added later: ADDED_COLUMNS migrates an older database in place).
    # org_id is NULL for an individual learner.
    org_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("organizations.id", ondelete="SET NULL"), index=True
    )
    main_domain: Mapped[str | None] = mapped_column(String(40))  # Engineering, Commerce, ...
    subdomain: Mapped[str | None] = mapped_column(String(120))  # Computer Science, ...
    account_status: Mapped[str] = mapped_column(String(12), default="active")


class ResumeAnalysis(Base):
    __tablename__ = "resume_analyses"
    __table_args__ = (
        CheckConstraint("match_percentage BETWEEN 0 AND 100", name="ck_resume_match_pct"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = _student_fk()
    matched_skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    missing_skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    match_percentage: Mapped[float] = mapped_column(Float)


class StudyPlan(Base):
    __tablename__ = "study_plans"
    __table_args__ = (
        UniqueConstraint("student_id", "week_number", name="uq_plan_week"),
        CheckConstraint("week_number >= 1", name="ck_plan_week"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = _student_fk()
    week_number: Mapped[int] = mapped_column(Integer)
    plan_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    completed_tasks: Mapped[list[str]] = mapped_column(JSON, default=list)


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"
    __table_args__ = (
        CheckConstraint("total_questions > 0", name="ck_quiz_total"),
        CheckConstraint("score BETWEEN 0 AND total_questions", name="ck_quiz_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = _student_fk()
    stream: Mapped[str] = mapped_column(String(40), index=True)
    domain: Mapped[str] = mapped_column(String(80), index=True)
    score: Mapped[int] = mapped_column(Integer)  # questions answered correctly
    total_questions: Mapped[int] = mapped_column(Integer)
    critique_notes: Mapped[str | None] = mapped_column(Text)
    proctor_flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)


class VoiceInterviewSession(Base):
    """Text and scores of a spoken interview. Nothing in the app records audio or proctors a
    session yet (voice is out of scope); this only gives such data a place to live."""

    __tablename__ = "voice_interview_sessions"
    __table_args__ = (
        CheckConstraint(f"rubric_score BETWEEN 0 AND {VOICE_RUBRIC_MAX}", name="ck_voice_rubric"),
        CheckConstraint(
            f"verbal_clarity_score BETWEEN 0 AND {VOICE_CRITERION_MAX}", name="ck_voice_clarity"
        ),
        CheckConstraint(
            f"relevance_score BETWEEN 0 AND {VOICE_CRITERION_MAX}", name="ck_voice_relevance"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = _student_fk()
    role: Mapped[str] = mapped_column(String(160), index=True)
    audio_transcript: Mapped[str] = mapped_column(Text)
    rubric_score: Mapped[int] = mapped_column(Integer)
    verbal_clarity_score: Mapped[float] = mapped_column(Float)
    relevance_score: Mapped[float] = mapped_column(Float)
    feedback: Mapped[str] = mapped_column(Text)
    proctor_flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)


# --- synchronisation with the cloud copy (database/connection.py) ----------------------------


class SyncOutbox(Base):
    """Local only. One row per write, added in the same transaction as the write itself, so a
    record made while offline is never lost: pending until `synced_at` is set. Rows the cloud
    rejected SYNC_MAX_ATTEMPTS times stay pending-but-set-aside and are reported."""

    __tablename__ = "sync_outbox"
    __table_args__ = (Index("ix_sync_outbox_pending", "synced_at", "id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity: Mapped[str] = mapped_column(String(20))  # a key of ENTITIES
    local_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)


class SyncMeta(Base):
    """Local only: this database's device id (it names its records in the cloud) and flags."""

    __tablename__ = "sync_meta"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class SyncReceipt(Base):
    """Cloud only: which device record already arrived, so a retry never inserts it twice.
    Local ids repeat across machines; "<device>:<entity>:<local id>" does not."""

    __tablename__ = "sync_receipts"

    source_key: Mapped[str] = mapped_column(String(120), primary_key=True)
    cloud_id: Mapped[int] = mapped_column(Integer)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)


# Which model each outbox entity names, and which tables each side holds.
ENTITIES: dict[str, type[Base]] = {
    "organization": Organization,  # first: a student's organization arrives before the student
    "student": StudentProfile,
    "resume": ResumeAnalysis,
    "plan": StudyPlan,
    "quiz": QuizAttempt,
    "voice": VoiceInterviewSession,
}
DATA_TABLES: list[Table] = [m.__table__ for m in ENTITIES.values()]  # type: ignore[misc]
LOCAL_TABLES: list[Table] = [*DATA_TABLES, SyncOutbox.__table__, SyncMeta.__table__]  # type: ignore[list-item]
CLOUD_TABLES: list[Table] = [*DATA_TABLES, SyncReceipt.__table__]  # type: ignore[list-item]


def migrate_identity(engine: Engine) -> bool:
    """A telemetry database from before accounts (SQLite or PostgreSQL): its student_profiles.usn
    becomes the lower-cased username, in place, keeping its unique constraint and every row.
    True when it migrated; a no-op on an up-to-date or empty database. Runs before create_all,
    which never alters an existing table. The DDL names fixed identifiers only."""
    inspector = inspect(engine)
    if "student_profiles" not in inspector.get_table_names():
        return False
    cols = {c["name"] for c in inspector.get_columns("student_profiles")}
    if "usn" not in cols or "username" in cols:
        return False
    table = StudentProfile.__table__
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE student_profiles RENAME COLUMN usn TO username"))
        conn.execute(table.update().values(username=func.lower(table.c.username)))
    return True


# Columns added to a table that may already exist. create_all never alters a table, so
# migrate_columns adds each missing one (nullable or defaulted: every row is kept).
ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("student_profiles", "org_id", "INTEGER REFERENCES organizations (id) ON DELETE SET NULL"),
    ("student_profiles", "main_domain", "VARCHAR(40)"),
    ("student_profiles", "subdomain", "VARCHAR(120)"),
    ("student_profiles", "account_status", "VARCHAR(12) NOT NULL DEFAULT 'active'"),
    ("quiz_attempts", "proctor_flags", "JSON DEFAULT '[]'"),
)
ADDED_INDEXES = (("ix_student_profiles_org_id", "student_profiles", "org_id"),)


def migrate_columns(engine: Engine) -> list[str]:
    """Add the columns an older database lacks (ADDED_COLUMNS) and their indexes, in place, on
    SQLite or PostgreSQL. Returns "table.column" for each one added; a no-op when up to date.
    Runs after create_all (the organizations table must exist for the foreign key). The DDL
    names fixed identifiers only."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    added: list[str] = []
    with engine.begin() as conn:
        for table, column, ddl in ADDED_COLUMNS:
            if table not in tables:
                continue
            if column not in {c["name"] for c in inspector.get_columns(table)}:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
                added.append(f"{table}.{column}")
        for name, table, column in ADDED_INDEXES:
            if table in tables:
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({column})"))
    return added

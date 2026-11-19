"""Database access: one schema, SQLite or Postgres.

`DATABASE_URL` selects the database (e.g. `postgresql+psycopg://user:pass@host/db`). Without it,
`DATABASE_PATH` (a SQLite file, default `workflowos.db`) is used, so existing installs keep working.
Repositories take an optional `db_path` that may be a SQLAlchemy URL, a SQLite file path or
`:memory:`.

Most records are stored as one JSON document (`JSONB` on Postgres, JSON text on SQLite, which is
exactly what older SQLite files already contain) next to the few columns that are filtered or
sorted on. Timestamps are ISO-8601 UTC strings, as before.

The schema is managed by Alembic migrations (`app/migrations`, applied by `app.migrate.upgrade()`,
which the API runs on start). Tables are only auto-created when AUTO_CREATE_TABLES is set, which the
test suite does so each throwaway test database is ready instantly.
"""

import os
import threading
from typing import Any, Callable, Dict, Iterable, List, Optional
import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Float,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.pool import NullPool, StaticPool

from app import config

Document = JSON().with_variant(JSONB(), "postgresql")

metadata = MetaData()

# ------------------------------------------------------------------ observation

activity_events = Table(
    "activity_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("event_id", Text, nullable=False, unique=True),
    Column("event_type", Text, nullable=False),
    Column("timestamp", Text, nullable=False),
    Column("application", Text),
    Column("source", Text, nullable=False),
    Column("metadata", Document, nullable=False),
)

# -------------------------------------------------------------------- workflows

canonical_workflows = Table(
    "canonical_workflows",
    metadata,
    Column("workflow_id", Text, primary_key=True),
    Column("source_dna_id", Text, nullable=False, index=True),
    Column("source_semantic_workflow_id", Text, nullable=False, index=True),
    Column("title", Text, nullable=False),
    Column("approval_state", Text, nullable=False),
    Column("overall_risk_level", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    Column("spec_json", Document, nullable=False),
)

execution_plans = Table(
    "execution_plans",
    metadata,
    Column("plan_id", Text, primary_key=True),
    Column("source_workflow_id", Text, nullable=False, index=True),
    Column("status", Text, nullable=False),
    Column("dry_run_status", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    Column("plan_json", Document, nullable=False),
)

execution_records = Table(
    "execution_records",
    metadata,
    Column("execution_id", Text, primary_key=True),
    Column("workflow_id", Text, nullable=False, index=True),
    Column("execution_plan_id", Text, nullable=False, index=True),
    Column("idempotency_key", Text, index=True),
    Column("status", Text, nullable=False),
    Column("execution_mode", Text, nullable=False),
    Column("start_time", Text, nullable=False),
    Column("end_time", Text),
    Column("record_json", Document, nullable=False),
)

workflow_verifications = Table(
    "workflow_verifications",
    metadata,
    Column("verification_run_id", Text, primary_key=True),
    Column("execution_id", Text, nullable=False, index=True),
    Column("workflow_id", Text, nullable=False),
    Column("execution_plan_id", Text, nullable=False),
    Column("overall_status", Text, nullable=False),
    Column("verified_count", Integer, nullable=False),
    Column("failed_count", Integer, nullable=False),
    Column("unknown_count", Integer, nullable=False),
    Column("started_at", Text, nullable=False),
    Column("completed_at", Text),
    Column("result_json", Document, nullable=False),
)

verification_checks = Table(
    "verification_checks",
    metadata,
    Column("verification_id", Text, primary_key=True),
    Column("verification_run_id", Text, nullable=False, index=True),
    Column("execution_id", Text, nullable=False),
    Column("planned_step_id", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("check_json", Document, nullable=False),
)

workflow_reliability_profiles = Table(
    "workflow_reliability_profiles",
    metadata,
    Column("workflow_id", Text, primary_key=True),
    Column("profile_id", Text, nullable=False),
    Column("total_executions", Integer, nullable=False),
    Column("reliability_rate", Float, nullable=False),
    Column("computed_at", Text, nullable=False),
    Column("profile_json", Document, nullable=False),
)

workflow_learning_events = Table(
    "workflow_learning_events",
    metadata,
    Column("event_id", Text, primary_key=True),
    Column("workflow_id", Text, nullable=False, index=True),
    Column("event_type", Text, nullable=False),
    Column("timestamp", Text, nullable=False, index=True),
    Column("event_json", Document, nullable=False),
)

# ------------------------------------------------------------------- automation

email_triggers = Table(
    "email_triggers",
    metadata,
    Column("trigger_id", Text, primary_key=True),
    Column("workflow_id", Text, nullable=False),
    Column("enabled", Boolean, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("record_json", Document, nullable=False),
)

workflow_runs = Table(
    "workflow_runs",
    metadata,
    Column("run_id", Text, primary_key=True),
    Column("trigger_id", Text, nullable=False),
    Column("workflow_id", Text, nullable=False),
    Column("message_id", Text, nullable=False),
    Column("status", Text, nullable=False, index=True),
    Column("created_at", Text, nullable=False),
    Column("record_json", Document, nullable=False),
    # Also the processed-email ledger: one run per message per trigger
    UniqueConstraint("trigger_id", "message_id", name="uq_workflow_runs_trigger_message"),
)

# ------------------------------------------------------------------------- auth

users = Table(
    "users",
    metadata,
    Column("user_id", Text, primary_key=True),
    Column("email", Text, nullable=False),
    Column("password_hash", Text, nullable=False),
    Column("record_json", Document, nullable=False),
)
# Emails are unique regardless of case
Index("uq_users_email_lower", func.lower(users.c.email), unique=True)

sessions = Table(
    "sessions",
    metadata,
    Column("token_hash", Text, primary_key=True),
    Column("user_id", Text, nullable=False, index=True),
    Column("created_at", Text, nullable=False),
    Column("expires_at", Text, nullable=False),
)

api_keys = Table(
    "api_keys",
    metadata,
    Column("key_id", Text, primary_key=True),
    Column("key_hash", Text, nullable=False, unique=True),
    Column("record_json", Document, nullable=False),
)

# ----------------------------------------------------------------- credentials

integration_credentials = Table(
    "integration_credentials",
    metadata,
    Column("name", Text, primary_key=True),
    Column("ciphertext", LargeBinary, nullable=False),
    Column("metadata_json", Document, nullable=False),
    Column("updated_at", Text, nullable=False),
    Column("updated_by", Text),
)

oauth_states = Table(
    "oauth_states",
    metadata,
    Column("state_hash", Text, primary_key=True),
    Column("ciphertext", LargeBinary, nullable=False),
    Column("expires_at", Text, nullable=False),
)


# ------------------------------------------------------------------------ jobs

jobs = Table(
    "jobs",
    metadata,
    Column("job_id", Text, primary_key=True),
    Column("kind", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("payload", Document, nullable=False),
    Column("result", Document),
    Column("attempts", Integer, nullable=False),
    Column("max_attempts", Integer, nullable=False),
    # ISO-8601 UTC with fixed microsecond precision, so text comparison orders correctly
    Column("run_after", Text, nullable=False),
    Column("locked_by", Text),
    Column("locked_until", Text),
    # Set before the first step that may change something outside WorkFlowOS; such a job is never retried.
    Column("side_effects_started", Boolean, nullable=False),
    # At most one active job per key (e.g. the email poll). Cleared when the job finishes.
    Column("dedupe_key", Text),
    Column("last_error", Text),
    Column("created_by", Text),
    Column("created_at", Text, nullable=False),
    Column("started_at", Text),
    Column("finished_at", Text),
    UniqueConstraint("dedupe_key", name="uq_jobs_dedupe_key"),
    Index("ix_jobs_status_run_after", "status", "run_after"),
)


# ---------------------------------------------------------------------- engines

# Test hook: create missing tables directly from `metadata` instead of running migrations.
AUTO_CREATE_TABLES = False
# Test hook: maps a resolved URL to another one (the suite uses it to run on Postgres).
url_mapper: Optional[Callable[[str], str]] = None
# Test hook: extra create_engine() keyword arguments for non-SQLite engines.
engine_options: Dict[str, Any] = {}

_engines: Dict[str, Engine] = {}
_tables_created: set = set()
_lock = threading.Lock()


def database_url(target: Optional[str] = None) -> str:
    """SQLAlchemy URL for a URL, a SQLite file path or ':memory:' (default: the configured database)."""
    value = target or os.getenv("DATABASE_URL") or config.DATABASE_PATH
    if "://" in value:
        url = value
    elif value == ":memory:":
        url = f"sqlite:///file:mem-{uuid.uuid4().hex}?mode=memory&cache=shared&uri=true"
    else:
        url = "sqlite:///" + os.path.abspath(value).replace("\\", "/")
    return url_mapper(url) if url_mapper else url


def _new_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        if "mode=memory" in url:
            # One shared connection keeps the in-memory database alive for the engine's lifetime.
            return create_engine(url, poolclass=StaticPool, connect_args={"check_same_thread": False})
        # A connection per use (no pool), as before: SQLite connections are cheap, and pooled ones
        # would keep the file open (Windows cannot delete or move an open file).
        return create_engine(url, poolclass=NullPool, connect_args={"timeout": 10, "check_same_thread": False})
    # Fail fast if the database is unreachable instead of hanging (the worker retries its tick).
    options: Dict[str, Any] = {"pool_pre_ping": True, "connect_args": {"connect_timeout": 10}}
    options.update(engine_options)
    if options.get("poolclass") is NullPool:
        options.pop("pool_pre_ping", None)
    return create_engine(url, **options)


def sqlite_file_engine(path: str) -> Engine:
    """Engine for a specific SQLite file, never redirected by test hooks (e.g. an import source)."""
    return engine_for_url("sqlite:///" + os.path.abspath(path).replace("\\", "/"), create_tables=False)


def get_engine(target: Optional[str] = None, create_tables: Optional[bool] = None) -> Engine:
    """Engine for `target` (cached per URL). Creates missing tables only if asked (tests)."""
    return engine_for_url(database_url(target), create_tables)


def engine_for_url(url: str, create_tables: Optional[bool] = None) -> Engine:
    create = AUTO_CREATE_TABLES if create_tables is None else create_tables
    with _lock:
        engine = _engines.get(url)
        if engine is None:
            engine = _new_engine(url)
            _engines[url] = engine
        if create and url not in _tables_created:
            metadata.create_all(engine)
            _tables_created.add(url)
        return engine


def dispose_engines() -> None:
    with _lock:
        for engine in _engines.values():
            engine.dispose()
        _engines.clear()
        _tables_created.clear()


# --------------------------------------------------------------------- helpers


def _insert(conn: Connection, table: Table):
    if conn.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif conn.dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:  # pragma: no cover - only SQLite and Postgres are supported
        raise RuntimeError(f"Unsupported database: {conn.dialect.name}")
    return insert(table)


def upsert(conn: Connection, table: Table, values: Dict[str, Any], key: Iterable[str], update: Optional[List[str]] = None):
    """INSERT ... ON CONFLICT (key) DO UPDATE SET <update columns> (default: every non-key column)."""
    key = list(key)
    stmt = _insert(conn, table).values(**values)
    columns = update if update is not None else [c for c in values if c not in key]
    stmt = stmt.on_conflict_do_update(index_elements=key, set_={c: stmt.excluded[c] for c in columns})
    return conn.execute(stmt)


def insert_ignore(conn: Connection, table: Table, values: Dict[str, Any]) -> bool:
    """INSERT ... ON CONFLICT DO NOTHING. Returns True if a row was inserted.

    Uses RETURNING rather than rowcount, which some drivers (psycopg) report as -1 here.
    """
    pk = list(table.primary_key.columns)[0]
    stmt = _insert(conn, table).values(**values).on_conflict_do_nothing().returning(pk)
    return conn.execute(stmt).first() is not None


class Repository:
    """Base for repositories: resolves the database once and hands out transactions."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or os.getenv("DATABASE_URL") or config.DATABASE_PATH
        self.engine = get_engine(db_path)

    def begin(self):
        """Transaction context: commits on success, rolls back on error."""
        return self.engine.begin()

    def connect(self):
        """Read-only connection context."""
        return self.engine.connect()

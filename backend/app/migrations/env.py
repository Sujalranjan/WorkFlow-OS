"""Alembic environment for WorkFlowOS.

Run through `python -m app.cli db upgrade` (or automatically when the API starts). The target
database is the configured one (DATABASE_URL / DATABASE_PATH) unless a connection is passed in via
`config.attributes["connection"]` (app.migrate does that).

On Postgres, migrations take an advisory lock so an API and a worker starting together cannot
migrate at the same time.
"""

from alembic import context
from sqlalchemy import text

from app.db import get_engine, metadata

config = context.config
target_metadata = metadata

# Arbitrary constant identifying "WorkFlowOS schema migration" in pg_advisory_lock.
_MIGRATION_LOCK_ID = 7_340_112_001


def _configure(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite cannot ALTER most things in place; batch mode copies the table instead.
        render_as_batch=connection.dialect.name == "sqlite",
        compare_type=True,
    )


def _run(connection) -> None:
    is_pg = connection.dialect.name == "postgresql"
    if is_pg:
        connection.execute(text("SELECT pg_advisory_lock(:id)"), {"id": _MIGRATION_LOCK_ID})
    try:
        _configure(connection)
        with context.begin_transaction():
            context.run_migrations()
    finally:
        if is_pg:
            connection.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": _MIGRATION_LOCK_ID})
            connection.commit()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    with get_engine(create_tables=False).connect() as connection:
        _run(connection)


if context.is_offline_mode():
    raise SystemExit("Offline (SQL script) migrations are not supported; run them against a database.")
run_migrations_online()

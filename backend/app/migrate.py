"""Apply and inspect database migrations (Alembic) from code.

    upgrade()            bring the configured database (or `target`) to the latest schema
    current_revision()   the revision a database is at (None if never migrated)
    pending_changes()    differences between the code's tables and the database (empty = in sync)

The API runs upgrade() on start-up (MIGRATE_ON_START, default on); `python -m app.cli db upgrade`
does the same by hand.
"""

import logging
import os
from typing import List, Optional

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory

from app.db import get_engine, metadata

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations")


def alembic_config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", MIGRATIONS_DIR)
    return cfg


def head_revision() -> str:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def upgrade(target: Optional[str] = None, revision: str = "head") -> str:
    """Migrate `target` (default: the configured database) and return the revision it ends at."""
    engine = get_engine(target, create_tables=False)
    cfg = alembic_config()
    with engine.connect() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, revision)
        connection.commit()
    current = current_revision(target)
    logger.info("Database schema at revision %s", current)
    return current


def current_revision(target: Optional[str] = None) -> Optional[str]:
    with get_engine(target, create_tables=False).connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def pending_changes(target: Optional[str] = None) -> List:
    """Differences between the tables defined in app.db and the database. Empty means in sync."""
    with get_engine(target, create_tables=False).connect() as connection:
        ctx = MigrationContext.configure(
            connection, opts={"compare_type": True, "render_as_batch": connection.dialect.name == "sqlite"}
        )
        return compare_metadata(ctx, metadata)

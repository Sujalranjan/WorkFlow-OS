"""Database migrations (Alembic): fresh databases, databases from before migrations, start-up."""

import sqlite3

from alembic import command
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import inspect

from app import db, migrate
from app.repositories.auth_repository import AuthRepository
from app.repositories.automation_repository import AutomationRepository


def _fresh(tmp_path, name="m.db") -> str:
    return str(tmp_path / name)


def test_fresh_database_migrates_to_head_and_matches_the_code(tmp_path):
    target = _fresh(tmp_path)
    assert migrate.current_revision(target) is None
    assert migrate.upgrade(target) == migrate.head_revision()

    tables = set(inspect(db.get_engine(target, create_tables=False)).get_table_names())
    assert set(db.metadata.tables) <= tables
    assert migrate.pending_changes(target) == []  # the migrations describe exactly app.db's tables

    # Running again is a no-op
    assert migrate.upgrade(target) == migrate.head_revision()


def test_migrated_database_rejects_emails_differing_only_in_case(tmp_path):
    from sqlalchemy.exc import IntegrityError

    from app.models.auth import User

    target = _fresh(tmp_path)
    migrate.upgrade(target)
    repo = AuthRepository(target)
    repo.insert_user(User(email="Ops@Example.com", name="Ops"), "hash")
    with pytest.raises(IntegrityError):
        repo.insert_user(User(email="ops@example.COM", name="Dup"), "hash")


def test_database_from_before_migrations_is_adopted_without_losing_data(tmp_path):
    """Installs created by the old sqlite3 code: keep tables and rows, add what is missing."""
    if db.url_mapper is not None:
        pytest.skip("builds a real SQLite file the old way")
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE users (user_id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                            password_hash TEXT NOT NULL, record_json TEXT NOT NULL);
        CREATE TABLE email_triggers (trigger_id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL,
                                     enabled INTEGER NOT NULL, created_at TEXT NOT NULL, record_json TEXT NOT NULL);
        CREATE TABLE execution_plans (plan_id TEXT PRIMARY KEY, source_workflow_id TEXT NOT NULL, status TEXT NOT NULL,
                                      dry_run_status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                                      plan_json TEXT NOT NULL);
        CREATE INDEX idx_plan_workflow_id ON execution_plans(source_workflow_id);
        """
    )
    conn.execute(
        "INSERT INTO users VALUES (?, ?, ?, ?)",
        ("usr-1", "Ops@Example.com", "$argon2id$x", '{"user_id": "usr-1", "email": "Ops@Example.com", "name": "Ops", "role": "admin"}'),
    )
    conn.commit()
    conn.close()

    target = str(path)
    assert migrate.upgrade(target) == migrate.head_revision()

    engine = db.get_engine(target, create_tables=False)
    insp = inspect(engine)
    assert set(db.metadata.tables) <= set(insp.get_table_names())  # missing tables were added
    assert "ix_execution_plans_source_workflow_id" in {ix["name"] for ix in insp.get_indexes("execution_plans")}

    repo = AuthRepository(target)
    user, password_hash = repo.get_user_with_hash("ops@example.com")
    assert user.name == "Ops" and password_hash == "$argon2id$x"
    assert AutomationRepository(target).list_triggers() == []
    assert migrate.upgrade(target) == migrate.head_revision()  # idempotent


def test_baseline_refuses_to_downgrade(tmp_path):
    target = _fresh(tmp_path)
    migrate.upgrade(target)
    cfg = migrate.alembic_config()
    with db.get_engine(target, create_tables=False).connect() as connection:
        cfg.attributes["connection"] = connection
        with pytest.raises(RuntimeError, match="cannot be downgraded"):
            command.downgrade(cfg, "base")
    assert migrate.current_revision(target) == migrate.head_revision()


def test_api_applies_migrations_on_start(monkeypatch):
    import app.main as main

    calls = []
    monkeypatch.setattr(main, "MIGRATE_ON_START", True)
    monkeypatch.setattr(migrate, "upgrade", lambda *a, **k: calls.append(1) or "0001")
    with TestClient(main.create_app()) as client:
        assert client.get("/health").status_code == 200
    assert calls == [1]


def test_cli_db_commands(tmp_path, monkeypatch, capsys):
    from app import cli

    target = _fresh(tmp_path, "cli.db")
    monkeypatch.setenv("DATABASE_URL", db.database_url(target))
    assert cli.main(["db", "current"]) == 0
    assert "never migrated" in capsys.readouterr().out
    assert cli.main(["db", "upgrade"]) == 0
    assert cli.main(["db", "check"]) == 0
    assert "matches the code" in capsys.readouterr().out

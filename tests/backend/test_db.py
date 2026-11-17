"""The shared database layer behaves the same on SQLite and Postgres."""

import sqlite3

import pytest
from sqlalchemy import select

from app import db
from app.models.auth import ApiKey, User
from app.repositories.auth_repository import AuthRepository
from app.repositories.event_repository import EventRepository
from app.models.event import ActivityEvent, ActivityEventType


def test_database_url_accepts_urls_paths_and_memory(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "url_mapper", None)
    assert db.database_url("postgresql+psycopg://u:p@h/x") == "postgresql+psycopg://u:p@h/x"
    assert db.database_url(str(tmp_path / "a.db")).startswith("sqlite:///")
    first, second = db.database_url(":memory:"), db.database_url(":memory:")
    assert "mode=memory" in first and first != second  # each :memory: is its own database


def test_memory_databases_are_isolated():
    a, b = EventRepository(":memory:"), EventRepository(":memory:")
    a.create(ActivityEvent(event_type=ActivityEventType.WINDOW_FOCUSED, application="X"))
    assert len(a.list_recent()) == 1 and b.list_recent() == []


def test_upsert_and_insert_ignore(tmp_path):
    repo = AuthRepository(str(tmp_path / "x.db"))
    table = db.api_keys
    with repo.begin() as conn:
        assert db.insert_ignore(conn, table, {"key_id": "k1", "key_hash": "h1", "record_json": {"v": 1}})
        assert not db.insert_ignore(conn, table, {"key_id": "k1", "key_hash": "h2", "record_json": {"v": 2}})
        db.upsert(conn, table, {"key_id": "k1", "key_hash": "h1", "record_json": {"v": 3}}, key=["key_id"])
        rows = conn.execute(select(table)).all()
    assert len(rows) == 1 and rows[0].record_json == {"v": 3}


def test_emails_are_unique_and_matched_case_insensitively(tmp_path):
    repo = AuthRepository(str(tmp_path / "x.db"))
    repo.insert_user(User(email="Ops@Example.com", name="Ops"), "hash")
    assert repo.get_user_with_hash("ops@example.COM")[0].name == "Ops"
    with pytest.raises(Exception):
        repo.insert_user(User(email="OPS@example.com", name="Dup"), "hash")


def test_event_get_by_id_works():
    """Regression: the old query had no FROM clause and failed whenever it was called."""
    repo = EventRepository(":memory:")
    evt = repo.create(ActivityEvent(event_type=ActivityEventType.FILE_CREATED, application="Explorer", metadata={"k": "v"}))
    assert repo.get_by_id(evt.event_id).metadata == {"k": "v"}
    assert repo.get_by_id("missing") is None


def test_existing_sqlite_files_from_before_sqlalchemy_still_read(tmp_path):
    """Databases written by the old sqlite3 code (JSON as TEXT, ints for booleans) keep working."""
    if db.url_mapper is not None:
        pytest.skip("checks a real SQLite file")
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE api_keys (key_id TEXT PRIMARY KEY, key_hash TEXT NOT NULL UNIQUE, record_json TEXT NOT NULL)"
    )
    key = ApiKey(name="laptop", prefix="wfos_abc", created_by="admin")
    conn.execute("INSERT INTO api_keys VALUES (?, ?, ?)", (key.key_id, "h", key.model_dump_json()))
    conn.commit()
    conn.close()
    assert AuthRepository(str(path)).get_api_key(key.key_id).name == "laptop"

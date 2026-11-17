"""`db import-sqlite`: copying an existing SQLite install into the configured database.

On the Postgres test leg the target really is Postgres; on the SQLite leg it is another file.
"""

import json
import sqlite3

from cryptography.fernet import Fernet
import pytest

from app import db
from app.models.automation import EmailTrigger
from app.db_import import ImportErrorReport, import_sqlite, summary
from app.models.event import ActivityEvent, ActivityEventType
from app.repositories.auth_repository import AuthRepository
from app.repositories.automation_repository import AutomationRepository
from app.repositories.event_repository import EventRepository
from app.services.credential_store import CredentialStore

KEY = Fernet.generate_key()


def _legacy_source(path) -> None:
    """A database as the pre-SQLAlchemy code wrote it: JSON as TEXT, booleans as 0/1, BLOB secrets."""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE activity_events (id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE NOT NULL,
            event_type TEXT NOT NULL, timestamp TEXT NOT NULL, application TEXT, source TEXT NOT NULL, metadata TEXT NOT NULL);
        CREATE TABLE users (user_id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL, record_json TEXT NOT NULL);
        CREATE TABLE email_triggers (trigger_id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL, enabled INTEGER NOT NULL,
            created_at TEXT NOT NULL, record_json TEXT NOT NULL);
        CREATE TABLE integration_credentials (name TEXT PRIMARY KEY, ciphertext BLOB NOT NULL, metadata_json TEXT NOT NULL,
            updated_at TEXT NOT NULL, updated_by TEXT);
        """
    )
    for i in range(1, 4):
        conn.execute(
            "INSERT INTO activity_events (event_id, event_type, timestamp, application, source, metadata) VALUES (?,?,?,?,?,?)",
            (f"evt-{i}", "window_focused", f"2026-11-0{i}T10:00:00+00:00", "Gmail", "desktop_agent", json.dumps({"n": i})),
        )
    conn.execute(
        "INSERT INTO users VALUES (?,?,?,?)",
        ("usr-1", "Ops@Example.com", "$argon2id$hash",
         json.dumps({"user_id": "usr-1", "email": "Ops@Example.com", "name": "Ops", "role": "admin"})),
    )
    trigger = EmailTrigger(trigger_id="trg-1", workflow_id="wf-1", name="Invoices", gmail_query="has:attachment")
    conn.execute(
        "INSERT INTO email_triggers VALUES (?,?,?,?,?)",
        ("trg-1", "wf-1", 1, trigger.created_at, trigger.model_dump_json()),
    )
    secret = Fernet(KEY).encrypt(json.dumps({"refresh_token": "1//r"}).encode())
    conn.execute(
        "INSERT INTO integration_credentials VALUES (?,?,?,?,?)",
        ("gmail", secret, json.dumps({"account": "ops@example.com"}), "2026-11-12T00:00:00+00:00", "ops@example.com"),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "old.db"
    _legacy_source(path)
    return str(path)


def test_import_copies_everything_and_data_stays_usable(source, tmp_path):
    target = str(tmp_path / "target.db")
    reports = {r.table: r for r in import_sqlite(source, target)}

    assert reports["activity_events"].copied == 3 and reports["users"].copied == 1
    assert "Every source row is in the target" in summary(list(reports.values()))

    events = EventRepository(target).list_recent()
    assert [e.metadata for e in events] == [{"n": 3}, {"n": 2}, {"n": 1}]
    user, password_hash = AuthRepository(target).get_user_with_hash("ops@example.com")
    assert user.name == "Ops" and password_hash == "$argon2id$hash"
    assert AutomationRepository(target).get_trigger("trg-1").enabled is True

    # Encrypted credentials are copied byte for byte: same key, same secret (Gmail stays connected)
    stored = CredentialStore(target, key=KEY).get("gmail")
    assert stored.secret == {"refresh_token": "1//r"} and stored.metadata == {"account": "ops@example.com"}

    # New rows after the import get fresh ids (Postgres id sequence moved past the copied rows)
    EventRepository(target).create(ActivityEvent(event_type=ActivityEventType.FILE_CREATED, application="X"))
    assert len(EventRepository(target).list_recent()) == 4


def test_import_is_safe_to_rerun_and_never_overwrites(source, tmp_path):
    target = str(tmp_path / "target.db")
    import_sqlite(source, target)
    repo = AuthRepository(target)
    user, _ = repo.get_user_with_hash("ops@example.com")
    user.name = "Renamed after import"
    repo.save_user(user)

    again = {r.table: r for r in import_sqlite(source, target)}
    assert all(r.copied == 0 for r in again.values())
    assert again["activity_events"].already_present == 3
    assert repo.get_user_with_hash("ops@example.com")[0].name == "Renamed after import"


def test_import_refuses_bad_sources_and_same_database(tmp_path, source):
    with pytest.raises(ImportErrorReport, match="No SQLite file"):
        import_sqlite(str(tmp_path / "missing.db"), str(tmp_path / "t.db"))
    with pytest.raises(ImportErrorReport, match="path of the SQLite file"):
        import_sqlite("postgresql+psycopg://x/y", str(tmp_path / "t.db"))
    if db.url_mapper is None:
        with pytest.raises(ImportErrorReport, match="same database"):
            import_sqlite(source, source)
    # The source is never modified
    conn = sqlite3.connect(source)
    assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'alembic_version'").fetchone() is None
    conn.close()


def test_cli_import(source, tmp_path, monkeypatch, capsys):
    from app import cli

    monkeypatch.setenv("DATABASE_URL", db.database_url(str(tmp_path / "cli-target.db")))
    assert cli.main(["db", "import-sqlite", source]) == 0
    out = capsys.readouterr().out
    assert "activity_events" in out and "Copied 6 of 6 rows" in out
    with pytest.raises(SystemExit, match="No SQLite file"):
        cli.main(["db", "import-sqlite", str(tmp_path / "nope.db")])

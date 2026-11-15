"""Encrypted storage for integration credentials (Gmail OAuth, Slack bot token).

Secrets are encrypted with Fernet (AES-128-CBC + HMAC-SHA256) before they reach SQLite, so a copy
of the database alone does not reveal them. The key comes from WORKFLOWOS_SECRET_KEY, or from a key
file created on first use next to the database (SECRET_KEY_PATH). Keep that key out of backups that
also contain the database; losing it means reconnecting the integrations.

Each record has an encrypted `secret` and plain, non-secret `metadata` (account name, channel,
who connected it) that status pages can show without decrypting anything.

Also stores short-lived OAuth sign-in states (single use, encrypted, 10 minute lifetime).
"""

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import os
import sqlite3
import threading
from typing import Any, Dict, Generator, Optional

from cryptography.fernet import Fernet, InvalidToken

from app import config

logger = logging.getLogger(__name__)

GMAIL_TOKEN = "gmail"
GMAIL_OAUTH_CLIENT = "gmail_oauth_client"
SLACK = "slack"
OAUTH_STATE_TTL = timedelta(minutes=10)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class CredentialStoreError(Exception):
    pass


def load_or_create_key(key_path: Optional[str] = None) -> bytes:
    """Fernet key from WORKFLOWOS_SECRET_KEY, else from (or newly written to) the key file."""
    env_key = os.getenv("WORKFLOWOS_SECRET_KEY", "").strip()
    if env_key:
        try:
            Fernet(env_key.encode())
        except (ValueError, TypeError) as e:
            raise CredentialStoreError(
                "WORKFLOWOS_SECRET_KEY is not a valid key. Generate one with: "
                'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
            ) from e
        return env_key.encode()

    path = key_path or config.secret_key_path()
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read().strip()

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    key = Fernet.generate_key()
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:  # another process (API / worker) created it first
        with open(path, "rb") as f:
            return f.read().strip()
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    logger.info("Created a new credential encryption key", extra={"path": path})
    return key


@dataclass
class StoredCredential:
    name: str
    secret: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None


class CredentialStore:
    def __init__(self, db_path: Optional[str] = None, key: Optional[bytes] = None) -> None:
        self.db_path = db_path or config.DATABASE_PATH
        self._fernet = Fernet(key or load_or_create_key())
        self._init_db()

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn, conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS integration_credentials (
                    name TEXT PRIMARY KEY,
                    ciphertext BLOB NOT NULL,
                    metadata_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    updated_by TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS oauth_states (
                    state_hash TEXT PRIMARY KEY,
                    ciphertext BLOB NOT NULL,
                    expires_at TEXT NOT NULL
                )
                """
            )

    def _encrypt(self, data: Dict[str, Any]) -> bytes:
        return self._fernet.encrypt(json.dumps(data).encode("utf-8"))

    def _decrypt(self, blob: bytes) -> Dict[str, Any]:
        return json.loads(self._fernet.decrypt(blob).decode("utf-8"))

    # ------------------------------------------------------------- credentials

    def put(self, name: str, secret: Dict[str, Any], metadata: Optional[Dict[str, Any]] = None, actor: Optional[str] = None) -> None:
        with self._conn() as conn, conn:
            conn.execute(
                """
                INSERT INTO integration_credentials (name, ciphertext, metadata_json, updated_at, updated_by)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET ciphertext = excluded.ciphertext,
                    metadata_json = excluded.metadata_json, updated_at = excluded.updated_at,
                    updated_by = excluded.updated_by
                """,
                (name, self._encrypt(secret), json.dumps(metadata or {}), _now().isoformat(), actor),
            )

    def update_secret(self, name: str, secret: Dict[str, Any]) -> None:
        """Replace only the secret (e.g. a refreshed access token), keeping metadata and audit fields."""
        with self._conn() as conn, conn:
            conn.execute("UPDATE integration_credentials SET ciphertext = ? WHERE name = ?", (self._encrypt(secret), name))

    def get(self, name: str) -> Optional[StoredCredential]:
        """The decrypted record, or None if absent or unreadable with the current key."""
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM integration_credentials WHERE name = ?", (name,)).fetchone()
        if not row:
            return None
        try:
            secret = self._decrypt(row["ciphertext"])
        except InvalidToken:
            logger.error("Stored credential cannot be decrypted with the current key", extra={"credential": name})
            return None
        return StoredCredential(name, secret, json.loads(row["metadata_json"]), row["updated_at"], row["updated_by"])

    def info(self, name: str) -> Optional[StoredCredential]:
        """Metadata and audit fields only; the secret is left empty and never decrypted."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT metadata_json, updated_at, updated_by FROM integration_credentials WHERE name = ?", (name,)
            ).fetchone()
        if not row:
            return None
        return StoredCredential(name, {}, json.loads(row["metadata_json"]), row["updated_at"], row["updated_by"])

    def delete(self, name: str) -> bool:
        with self._conn() as conn, conn:
            return conn.execute("DELETE FROM integration_credentials WHERE name = ?", (name,)).rowcount > 0

    # ------------------------------------------------------------ oauth states

    def save_oauth_state(self, state: str, data: Dict[str, Any]) -> None:
        with self._conn() as conn, conn:
            conn.execute("DELETE FROM oauth_states WHERE expires_at < ?", (_now().isoformat(),))
            conn.execute(
                "INSERT INTO oauth_states (state_hash, ciphertext, expires_at) VALUES (?, ?, ?)",
                (_sha256(state), self._encrypt(data), (_now() + OAUTH_STATE_TTL).isoformat()),
            )

    def pop_oauth_state(self, state: str) -> Optional[Dict[str, Any]]:
        """Consume a sign-in state: returns its data once, or None if unknown, used or expired."""
        if not state:
            return None
        with self._conn() as conn, conn:
            row = conn.execute(
                "SELECT ciphertext, expires_at FROM oauth_states WHERE state_hash = ?", (_sha256(state),)
            ).fetchone()
            conn.execute("DELETE FROM oauth_states WHERE state_hash = ?", (_sha256(state),))
        if not row or datetime.fromisoformat(row["expires_at"]) < _now():
            return None
        try:
            return self._decrypt(row["ciphertext"])
        except InvalidToken:
            return None


_store: Optional[CredentialStore] = None
_override: Optional[CredentialStore] = None
_store_lock = threading.Lock()


def get_credential_store() -> CredentialStore:
    """Process-wide store for the configured database (or the one set by set_credential_store)."""
    global _store
    with _store_lock:
        if _override is not None:
            return _override
        if _store is None or _store.db_path != config.DATABASE_PATH:
            _store = CredentialStore()
        return _store


def set_credential_store(store: Optional[CredentialStore]) -> None:
    """Override the process-wide store (tests); None restores the default."""
    global _override
    with _store_lock:
        _override = store

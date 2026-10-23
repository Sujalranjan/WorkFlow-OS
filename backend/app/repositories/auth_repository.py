"""SQLite persistence for users, sessions and API keys.

Session tokens and API keys are stored only as SHA-256 hashes, so a copy of the database cannot be
used to sign in or send events. Password hashes are Argon2 and never leave this module except for
verification.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import sqlite3
from typing import Generator, List, Optional, Tuple

from app.config import DATABASE_PATH
from app.models.auth import ApiKey, User


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuthRepository:
    def __init__(self, db_path: str = DATABASE_PATH) -> None:
        self.db_path = db_path
        self._memory_conn: Optional[sqlite3.Connection] = None
        if db_path == ":memory:":
            self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._memory_conn.row_factory = sqlite3.Row
        self._init_db()

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        if self._memory_conn is not None:
            yield self._memory_conn
            return
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
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    record_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS api_keys (
                    key_id TEXT PRIMARY KEY,
                    key_hash TEXT NOT NULL UNIQUE,
                    record_json TEXT NOT NULL
                )
                """
            )

    # ------------------------------------------------------------------ users

    def count_users(self) -> int:
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def insert_user(self, user: User, password_hash: str) -> User:
        with self._conn() as conn, conn:
            conn.execute(
                "INSERT INTO users (user_id, email, password_hash, record_json) VALUES (?, ?, ?, ?)",
                (user.user_id, user.email, password_hash, user.model_dump_json()),
            )
        return user

    def save_user(self, user: User, password_hash: Optional[str] = None) -> User:
        with self._conn() as conn, conn:
            if password_hash:
                conn.execute(
                    "UPDATE users SET email = ?, record_json = ?, password_hash = ? WHERE user_id = ?",
                    (user.email, user.model_dump_json(), password_hash, user.user_id),
                )
            else:
                conn.execute(
                    "UPDATE users SET email = ?, record_json = ? WHERE user_id = ?",
                    (user.email, user.model_dump_json(), user.user_id),
                )
        return user

    def get_user(self, user_id: str) -> Optional[User]:
        with self._conn() as conn:
            row = conn.execute("SELECT record_json FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return User(**json.loads(row["record_json"])) if row else None

    def get_user_with_hash(self, email: str) -> Optional[Tuple[User, str]]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT record_json, password_hash FROM users WHERE email = ? COLLATE NOCASE", (email,)
            ).fetchone()
        return (User(**json.loads(row["record_json"])), row["password_hash"]) if row else None

    def list_users(self) -> List[User]:
        with self._conn() as conn:
            rows = conn.execute("SELECT record_json FROM users ORDER BY email").fetchall()
        return [User(**json.loads(r["record_json"])) for r in rows]

    # --------------------------------------------------------------- sessions

    def insert_session(self, token_hash: str, user_id: str, expires_at: str) -> None:
        with self._conn() as conn, conn:
            conn.execute(
                "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (token_hash, user_id, _now(), expires_at),
            )

    def get_session(self, token_hash: str) -> Optional[Tuple[str, str]]:
        """Returns (user_id, expires_at)."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT user_id, expires_at FROM sessions WHERE token_hash = ?", (token_hash,)
            ).fetchone()
        return (row["user_id"], row["expires_at"]) if row else None

    def delete_session(self, token_hash: str) -> None:
        with self._conn() as conn, conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))

    def delete_user_sessions(self, user_id: str) -> None:
        with self._conn() as conn, conn:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    def delete_expired_sessions(self) -> None:
        with self._conn() as conn, conn:
            conn.execute("DELETE FROM sessions WHERE expires_at < ?", (_now(),))

    # --------------------------------------------------------------- api keys

    def insert_api_key(self, key: ApiKey, key_hash: str) -> ApiKey:
        with self._conn() as conn, conn:
            conn.execute(
                "INSERT INTO api_keys (key_id, key_hash, record_json) VALUES (?, ?, ?)",
                (key.key_id, key_hash, key.model_dump_json()),
            )
        return key

    def get_api_key_by_hash(self, key_hash: str) -> Optional[ApiKey]:
        with self._conn() as conn:
            row = conn.execute("SELECT record_json FROM api_keys WHERE key_hash = ?", (key_hash,)).fetchone()
        return ApiKey(**json.loads(row["record_json"])) if row else None

    def get_api_key(self, key_id: str) -> Optional[ApiKey]:
        with self._conn() as conn:
            row = conn.execute("SELECT record_json FROM api_keys WHERE key_id = ?", (key_id,)).fetchone()
        return ApiKey(**json.loads(row["record_json"])) if row else None

    def save_api_key(self, key: ApiKey) -> ApiKey:
        with self._conn() as conn, conn:
            conn.execute("UPDATE api_keys SET record_json = ? WHERE key_id = ?", (key.model_dump_json(), key.key_id))
        return key

    def list_api_keys(self) -> List[ApiKey]:
        with self._conn() as conn:
            rows = conn.execute("SELECT record_json FROM api_keys").fetchall()
        keys = [ApiKey(**json.loads(r["record_json"])) for r in rows]
        return sorted(keys, key=lambda k: k.created_at, reverse=True)

"""Encrypted storage for integration credentials (Gmail OAuth, Slack bot token).

Secrets are encrypted with Fernet (AES-128-CBC + HMAC-SHA256) before they reach SQLite, so a copy
of the database alone does not reveal them. The key comes from WORKFLOWOS_SECRET_KEY, or from a key
file created on first use next to the database (SECRET_KEY_PATH). Keep that key out of backups that
also contain the database; losing it means reconnecting the integrations.

Each record has an encrypted `secret` and plain, non-secret `metadata` (account name, channel,
who connected it) that status pages can show without decrypting anything.

Also stores short-lived OAuth sign-in states (single use, encrypted, 10 minute lifetime).
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import os
import threading
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, insert, select, update

from app import config
from app.db import Repository, get_engine, integration_credentials, oauth_states, upsert

logger = logging.getLogger(__name__)

GMAIL_TOKEN = "gmail"
GMAIL_OAUTH_CLIENT = "gmail_oauth_client"
SLACK = "slack"
HUBSPOT = "hubspot"
GMAIL_OPTIONS = "gmail_options"  # non-secret: {"allow_labels": bool, "allow_sheets": bool}
SHEETS = "sheets"
SLACK_OAUTH_CLIENT = "slack_oauth_client"  # Slack app client id + secret for "Add to Slack"  # non-secret: {"spreadsheet_id", "title", "sheet", "columns"}
SHARED_FOLDER = "files"  # non-secret: only metadata {"folder"}
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


class CredentialStore(Repository):
    def __init__(self, db_path: Optional[str] = None, key: Optional[bytes] = None) -> None:
        super().__init__(db_path)
        self._fernet = Fernet(key or load_or_create_key())

    def _encrypt(self, data: Dict[str, Any]) -> bytes:
        return self._fernet.encrypt(json.dumps(data).encode("utf-8"))

    def _decrypt(self, blob: bytes) -> Dict[str, Any]:
        return json.loads(self._fernet.decrypt(bytes(blob)).decode("utf-8"))

    # ------------------------------------------------------------- credentials

    def put(self, name: str, secret: Dict[str, Any], metadata: Optional[Dict[str, Any]] = None, actor: Optional[str] = None) -> None:
        with self.begin() as conn:
            upsert(
                conn,
                integration_credentials,
                {
                    "name": name,
                    "ciphertext": self._encrypt(secret),
                    "metadata_json": metadata or {},
                    "updated_at": _now().isoformat(),
                    "updated_by": actor,
                },
                key=["name"],
            )

    def update_secret(self, name: str, secret: Dict[str, Any]) -> None:
        """Replace only the secret (e.g. a refreshed access token), keeping metadata and audit fields."""
        with self.begin() as conn:
            conn.execute(
                update(integration_credentials)
                .where(integration_credentials.c.name == name)
                .values(ciphertext=self._encrypt(secret))
            )

    def update_metadata(self, name: str, changes: Dict[str, Any], actor: Optional[str] = None) -> bool:
        """Merge non-secret settings into an existing record (the secret is untouched)."""
        current = self.info(name)
        if current is None:
            return False
        merged = {**current.metadata, **changes}
        with self.begin() as conn:
            conn.execute(
                update(integration_credentials)
                .where(integration_credentials.c.name == name)
                .values(metadata_json=merged, updated_at=_now().isoformat(), updated_by=actor or current.updated_by)
            )
        return True

    def get(self, name: str) -> Optional[StoredCredential]:
        """The decrypted record, or None if absent or unreadable with the current key."""
        with self.connect() as conn:
            row = conn.execute(select(integration_credentials).where(integration_credentials.c.name == name)).first()
        if not row:
            return None
        try:
            secret = self._decrypt(row.ciphertext)
        except InvalidToken:
            logger.error("Stored credential cannot be decrypted with the current key", extra={"credential": name})
            return None
        return StoredCredential(name, secret, row.metadata_json, row.updated_at, row.updated_by)

    def info(self, name: str) -> Optional[StoredCredential]:
        """Metadata and audit fields only; the secret is left empty and never decrypted."""
        t = integration_credentials
        with self.connect() as conn:
            row = conn.execute(select(t.c.metadata_json, t.c.updated_at, t.c.updated_by).where(t.c.name == name)).first()
        if not row:
            return None
        return StoredCredential(name, {}, row.metadata_json, row.updated_at, row.updated_by)

    def delete(self, name: str) -> bool:
        with self.begin() as conn:
            return conn.execute(delete(integration_credentials).where(integration_credentials.c.name == name)).rowcount > 0

    # ------------------------------------------------------------ oauth states

    def save_oauth_state(self, state: str, data: Dict[str, Any]) -> None:
        with self.begin() as conn:
            conn.execute(delete(oauth_states).where(oauth_states.c.expires_at < _now().isoformat()))
            conn.execute(
                insert(oauth_states).values(
                    state_hash=_sha256(state),
                    ciphertext=self._encrypt(data),
                    expires_at=(_now() + OAUTH_STATE_TTL).isoformat(),
                )
            )

    def pop_oauth_state(self, state: str) -> Optional[Dict[str, Any]]:
        """Consume a sign-in state: returns its data once, or None if unknown, used or expired.

        DELETE ... RETURNING makes "read and remove" one atomic step, so two concurrent callbacks
        cannot both use the same state.
        """
        if not state:
            return None
        with self.begin() as conn:
            row = conn.execute(
                delete(oauth_states)
                .where(oauth_states.c.state_hash == _sha256(state))
                .returning(oauth_states.c.ciphertext, oauth_states.c.expires_at)
            ).first()
        if not row or datetime.fromisoformat(row.expires_at) < _now():
            return None
        try:
            return self._decrypt(row.ciphertext)
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
        if _store is None or _store.engine.url != get_engine().url:
            _store = CredentialStore()
        return _store


def set_credential_store(store: Optional[CredentialStore]) -> None:
    """Override the process-wide store (tests); None restores the default."""
    global _override
    with _store_lock:
        _override = store

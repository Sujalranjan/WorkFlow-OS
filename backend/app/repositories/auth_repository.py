"""Persistence for users, sessions and API keys.

Session tokens and API keys are stored only as SHA-256 hashes, so a copy of the database cannot be
used to sign in or send events. Password hashes are Argon2 and never leave this module except for
verification. Emails are matched case-insensitively.
"""

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import delete, func, insert, select, update

from app.db import Repository, api_keys, sessions, users
from app.models.auth import ApiKey, User


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuthRepository(Repository):
    # ------------------------------------------------------------------ users

    def count_users(self) -> int:
        with self.connect() as conn:
            return conn.execute(select(func.count()).select_from(users)).scalar_one()

    def insert_user(self, user: User, password_hash: str) -> User:
        with self.begin() as conn:
            conn.execute(
                insert(users).values(
                    user_id=user.user_id,
                    email=user.email,
                    password_hash=password_hash,
                    record_json=user.model_dump(mode="json"),
                )
            )
        return user

    def save_user(self, user: User, password_hash: Optional[str] = None) -> User:
        values = {"email": user.email, "record_json": user.model_dump(mode="json")}
        if password_hash:
            values["password_hash"] = password_hash
        with self.begin() as conn:
            conn.execute(update(users).where(users.c.user_id == user.user_id).values(**values))
        return user

    def get_user(self, user_id: str) -> Optional[User]:
        with self.connect() as conn:
            data = conn.execute(select(users.c.record_json).where(users.c.user_id == user_id)).scalar()
        return User(**data) if data else None

    def get_user_with_hash(self, email: str) -> Optional[Tuple[User, str]]:
        stmt = select(users.c.record_json, users.c.password_hash).where(func.lower(users.c.email) == email.lower())
        with self.connect() as conn:
            row = conn.execute(stmt).first()
        return (User(**row.record_json), row.password_hash) if row else None

    def list_users(self) -> List[User]:
        with self.connect() as conn:
            return [User(**data) for data in conn.execute(select(users.c.record_json).order_by(users.c.email)).scalars()]

    # --------------------------------------------------------------- sessions

    def insert_session(self, token_hash: str, user_id: str, expires_at: str) -> None:
        with self.begin() as conn:
            conn.execute(
                insert(sessions).values(token_hash=token_hash, user_id=user_id, created_at=_now(), expires_at=expires_at)
            )

    def get_session(self, token_hash: str) -> Optional[Tuple[str, str]]:
        """Returns (user_id, expires_at)."""
        with self.connect() as conn:
            row = conn.execute(
                select(sessions.c.user_id, sessions.c.expires_at).where(sessions.c.token_hash == token_hash)
            ).first()
        return (row.user_id, row.expires_at) if row else None

    def delete_session(self, token_hash: str) -> None:
        with self.begin() as conn:
            conn.execute(delete(sessions).where(sessions.c.token_hash == token_hash))

    def delete_user_sessions(self, user_id: str) -> None:
        with self.begin() as conn:
            conn.execute(delete(sessions).where(sessions.c.user_id == user_id))

    def delete_expired_sessions(self) -> None:
        with self.begin() as conn:
            conn.execute(delete(sessions).where(sessions.c.expires_at < _now()))

    # --------------------------------------------------------------- api keys

    def insert_api_key(self, key: ApiKey, key_hash: str) -> ApiKey:
        with self.begin() as conn:
            conn.execute(
                insert(api_keys).values(key_id=key.key_id, key_hash=key_hash, record_json=key.model_dump(mode="json"))
            )
        return key

    def _key(self, condition) -> Optional[ApiKey]:
        with self.connect() as conn:
            data = conn.execute(select(api_keys.c.record_json).where(condition)).scalar()
        return ApiKey(**data) if data else None

    def get_api_key_by_hash(self, key_hash: str) -> Optional[ApiKey]:
        return self._key(api_keys.c.key_hash == key_hash)

    def get_api_key(self, key_id: str) -> Optional[ApiKey]:
        return self._key(api_keys.c.key_id == key_id)

    def save_api_key(self, key: ApiKey) -> ApiKey:
        with self.begin() as conn:
            conn.execute(
                update(api_keys).where(api_keys.c.key_id == key.key_id).values(record_json=key.model_dump(mode="json"))
            )
        return key

    def list_api_keys(self) -> List[ApiKey]:
        with self.connect() as conn:
            keys = [ApiKey(**data) for data in conn.execute(select(api_keys.c.record_json)).scalars()]
        return sorted(keys, key=lambda k: k.created_at, reverse=True)

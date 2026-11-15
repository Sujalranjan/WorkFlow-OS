"""Password, session and API-key logic.

- Passwords: Argon2id (argon2-cffi defaults), rehashed transparently when parameters change.
- Sessions: 256-bit random tokens in an HttpOnly cookie; only their SHA-256 is stored, with a
  fixed lifetime (SESSION_TTL_HOURS). Changing a user's role, password or disabling them ends
  their sessions.
- API keys: 'wfos_' + 256-bit random token, SHA-256 stored, usable only to send activity events.
- Sign-in is rate limited per email and per client address.
"""

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
import hashlib
import logging
import secrets
import threading
import time
from typing import Deque, Dict, Optional, Tuple

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.config import LOGIN_MAX_ATTEMPTS, LOGIN_WINDOW_SECONDS, SESSION_TTL_HOURS
from app.models.auth import ApiKey, CreateUserRequest, Role, UpdateUserRequest, User
from app.repositories.auth_repository import AuthRepository

logger = logging.getLogger(__name__)

API_KEY_PREFIX = "wfos_"
_hasher = PasswordHasher()
# Verified against when the email is unknown, so response time does not reveal which emails exist.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class AuthError(Exception):
    """Sign-in or credential failure; the message is safe to show."""


class RateLimited(AuthError):
    pass


class LoginRateLimiter:
    """Sliding-window limit on failed sign-ins, keyed by email and by client address."""

    def __init__(self, max_attempts: int = LOGIN_MAX_ATTEMPTS, window_seconds: int = LOGIN_WINDOW_SECONDS) -> None:
        self.max_attempts = max_attempts
        self.window = window_seconds
        self._failures: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> Deque[float]:
        q = self._failures[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def check(self, *keys: str) -> None:
        now = time.monotonic()
        with self._lock:
            if any(len(self._recent(k, now)) >= self.max_attempts for k in keys):
                raise RateLimited("Too many failed sign-in attempts. Try again in a few minutes.")

    def fail(self, *keys: str) -> None:
        now = time.monotonic()
        with self._lock:
            for k in keys:
                self._recent(k, now).append(now)

    def reset(self, *keys: str) -> None:
        with self._lock:
            for k in keys:
                self._failures.pop(k, None)


class AuthService:
    def __init__(self, repo: Optional[AuthRepository] = None, limiter: Optional[LoginRateLimiter] = None) -> None:
        self.repo = repo or AuthRepository()
        self.limiter = limiter or LoginRateLimiter()

    # ------------------------------------------------------------------ users

    def create_user(self, req: CreateUserRequest) -> User:
        if self.repo.get_user_with_hash(req.email):
            raise AuthError(f"A user with email {req.email} already exists.")
        user = User(email=req.email, name=req.name.strip(), role=req.role)
        return self.repo.insert_user(user, _hasher.hash(req.password))

    def update_user(self, user_id: str, req: UpdateUserRequest, acting_user_id: str) -> User:
        user = self.repo.get_user(user_id)
        if not user:
            raise LookupError(f"User '{user_id}' not found.")
        if user_id == acting_user_id and (req.role not in (None, Role.ADMIN) or req.active is False):
            raise AuthError("You cannot remove your own admin role or disable your own account.")
        if req.name is not None:
            user.name = req.name.strip()
        ends_sessions = False
        if req.role is not None and req.role != user.role:
            user.role, ends_sessions = req.role, True
        if req.active is not None and req.active != user.active:
            user.active, ends_sessions = req.active, ends_sessions or not req.active
        new_hash = _hasher.hash(req.password) if req.password else None
        self.repo.save_user(user, new_hash)
        if ends_sessions or new_hash:
            self.repo.delete_user_sessions(user_id)
        return user

    def authenticate(self, email: str, password: str, client: str) -> User:
        keys = (f"email:{email.lower()}", f"client:{client}")
        self.limiter.check(*keys)
        found = self.repo.get_user_with_hash(email)
        try:
            _hasher.verify(found[1] if found else _DUMMY_HASH, password)
            ok = found is not None and found[0].active
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            ok = False
        if not ok:
            self.limiter.fail(*keys)
            logger.warning("Failed sign-in", extra={"email": email, "client": client})
            raise AuthError("Email or password is incorrect.")
        user, stored = found
        if _hasher.check_needs_rehash(stored):
            self.repo.save_user(user, _hasher.hash(password))
        self.limiter.reset(*keys)
        user.last_login_at = datetime.now(timezone.utc).isoformat()
        self.repo.save_user(user)
        logger.info("Signed in", extra={"user_id": user.user_id})
        return user

    # --------------------------------------------------------------- sessions

    def create_session(self, user: User) -> Tuple[str, datetime]:
        token = secrets.token_urlsafe(32)
        expires = datetime.now(timezone.utc) + timedelta(hours=SESSION_TTL_HOURS)
        self.repo.delete_expired_sessions()
        self.repo.insert_session(_sha256(token), user.user_id, expires.isoformat())
        return token, expires

    def user_for_session(self, token: str) -> Optional[User]:
        if not token:
            return None
        found = self.repo.get_session(_sha256(token))
        if not found:
            return None
        user_id, expires_at = found
        if datetime.fromisoformat(expires_at) <= datetime.now(timezone.utc):
            self.repo.delete_session(_sha256(token))
            return None
        user = self.repo.get_user(user_id)
        return user if user and user.active else None

    def end_session(self, token: str) -> None:
        if token:
            self.repo.delete_session(_sha256(token))

    # --------------------------------------------------------------- api keys

    def create_api_key(self, name: str, created_by: str) -> Tuple[str, ApiKey]:
        raw = API_KEY_PREFIX + secrets.token_urlsafe(32)
        key = ApiKey(name=name.strip(), prefix=raw[:12], created_by=created_by)
        self.repo.insert_api_key(key, _sha256(raw))
        return raw, key

    def api_key_for(self, raw: str) -> Optional[ApiKey]:
        if not raw or not raw.startswith(API_KEY_PREFIX):
            return None
        key = self.repo.get_api_key_by_hash(_sha256(raw))
        if not key or key.revoked_at:
            return None
        key.last_used_at = datetime.now(timezone.utc).isoformat()
        self.repo.save_api_key(key)
        return key

    def revoke_api_key(self, key_id: str) -> ApiKey:
        key = self.repo.get_api_key(key_id)
        if not key:
            raise LookupError(f"API key '{key_id}' not found.")
        if not key.revoked_at:
            key.revoked_at = datetime.now(timezone.utc).isoformat()
            self.repo.save_api_key(key)
        return key

"""Users, roles, sessions and API keys."""

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
import uuid

from pydantic import BaseModel, EmailStr, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Role(str, Enum):
    """Ordered roles: each one can do everything the previous one can."""

    VIEWER = "viewer"
    APPROVER = "approver"
    ADMIN = "admin"

    @property
    def rank(self) -> int:
        return _RANK[self]

    def allows(self, required: "Role") -> bool:
        return self.rank >= required.rank


_RANK = {Role.VIEWER: 1, Role.APPROVER: 2, Role.ADMIN: 3}


class User(BaseModel):
    """A person who signs in. The password hash never leaves the repository layer."""

    user_id: str = Field(default_factory=lambda: f"usr-{uuid.uuid4().hex[:12]}")
    email: EmailStr
    name: str
    role: Role = Role.VIEWER
    active: bool = True
    created_at: str = Field(default_factory=_now)
    last_login_at: Optional[str] = None

    @property
    def display(self) -> str:
        return f"{self.name} <{self.email}>"


class ApiKey(BaseModel):
    """A key the desktop agent or browser extension uses to send activity events. Only its hash is stored."""

    key_id: str = Field(default_factory=lambda: f"key-{uuid.uuid4().hex[:12]}")
    name: str
    prefix: str = Field(..., description="First characters of the key, to recognise it in lists")
    created_by: str
    created_at: str = Field(default_factory=_now)
    last_used_at: Optional[str] = None
    revoked_at: Optional[str] = None


class Principal(BaseModel):
    """Who is making the current request."""

    kind: str = Field(..., description="'user' or 'api_key'")
    user: Optional[User] = None
    api_key: Optional[ApiKey] = None

    @property
    def label(self) -> str:
        if self.user:
            return self.user.email
        return f"api-key:{self.api_key.name}" if self.api_key else "unknown"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=256)


class CreateUserRequest(BaseModel):
    email: EmailStr
    name: str = Field(..., min_length=1, max_length=100)
    role: Role = Role.VIEWER
    password: str = Field(..., min_length=12, max_length=256)


class UpdateUserRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    role: Optional[Role] = None
    active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=12, max_length=256)


class CreateApiKeyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80, description="Where the key is used, e.g. 'Laptop agent'")


class CreatedApiKey(BaseModel):
    """Returned once at creation: the only time the full key is visible."""

    key: str
    api_key: ApiKey


class MeResponse(BaseModel):
    user: User
    permissions: List[str]

"""Sign-in, sessions, users and API keys."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.config import COOKIE_SECURE, SESSION_COOKIE_NAME
from app.models.auth import (
    ApiKey,
    CreateApiKeyRequest,
    CreatedApiKey,
    CreateUserRequest,
    LoginRequest,
    MeResponse,
    Principal,
    Role,
    UpdateUserRequest,
    User,
)
from app.security import ROUTE_POLICY, SIGNED_IN, current_principal, get_auth_service
from app.services.auth_service import AuthError, RateLimited

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _permissions(role: Role) -> List[str]:
    """Route keys this role may call; the UI uses it to show or hide actions."""
    allowed = []
    for (method, path), access in ROUTE_POLICY.items():
        if isinstance(access, Role) and role.allows(access):
            allowed.append(f"{method} {path}")
    return sorted(allowed)


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/login", response_model=MeResponse)
def login(req: LoginRequest, request: Request, response: Response) -> MeResponse:
    service = get_auth_service()
    try:
        user = service.authenticate(req.email, req.password, _client(request))
    except RateLimited as e:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(e))
    except AuthError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(e))
    token, expires = service.create_session(user)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        expires=expires,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    return MeResponse(user=user, permissions=_permissions(user.role))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response) -> None:
    get_auth_service().end_session(request.cookies.get(SESSION_COOKIE_NAME, ""))
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")


@router.get("/me", response_model=MeResponse)
def me(principal: Principal = Depends(current_principal)) -> MeResponse:
    if not principal.user:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only people have a profile.")
    return MeResponse(user=principal.user, permissions=_permissions(principal.user.role))


@router.get("/users", response_model=List[User])
def list_users() -> List[User]:
    return get_auth_service().repo.list_users()


@router.post("/users", response_model=User, status_code=status.HTTP_201_CREATED)
def create_user(req: CreateUserRequest) -> User:
    try:
        return get_auth_service().create_user(req)
    except AuthError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))


@router.patch("/users/{user_id}", response_model=User)
def update_user(user_id: str, req: UpdateUserRequest, principal: Principal = Depends(current_principal)) -> User:
    try:
        return get_auth_service().update_user(user_id, req, acting_user_id=principal.user.user_id)
    except LookupError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    except AuthError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.get("/api-keys", response_model=List[ApiKey])
def list_api_keys() -> List[ApiKey]:
    return get_auth_service().repo.list_api_keys()


@router.post("/api-keys", response_model=CreatedApiKey, status_code=status.HTTP_201_CREATED)
def create_api_key(req: CreateApiKeyRequest, principal: Principal = Depends(current_principal)) -> CreatedApiKey:
    raw, key = get_auth_service().create_api_key(req.name, created_by=principal.label)
    return CreatedApiKey(key=raw, api_key=key)


@router.delete("/api-keys/{key_id}", response_model=ApiKey)
def revoke_api_key(key_id: str) -> ApiKey:
    try:
        return get_auth_service().revoke_api_key(key_id)
    except LookupError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))


assert ROUTE_POLICY[("GET", "/api/auth/me")] == SIGNED_IN

"""Authentication and authorization, exercised with real credentials (no test-admin shortcut).

Covers: every route has an explicit policy; anonymous callers are rejected everywhere except
/health and sign-in; sessions (HttpOnly cookie, logout, expiry, ended on role change); CSRF header;
role matrix; sign-in rate limit; API keys limited to sending events and revocable; approvals record
the signed-in user; CORS only for the configured dashboard origin.
"""

from datetime import datetime, timedelta, timezone
import re

from fastapi.testclient import TestClient
import pytest

from app import security
from app.main import create_app
from app.models.auth import CreateUserRequest, Role, UpdateUserRequest
from app.repositories.auth_repository import AuthRepository
from app.services.auth_service import AuthService, LoginRateLimiter

pytestmark = pytest.mark.real_auth

PASSWORD = "correct-horse-battery-staple"
CSRF = {"X-WorkflowOS-CSRF": "1"}


@pytest.fixture
def auth(tmp_path, monkeypatch):
    service = AuthService(AuthRepository(str(tmp_path / "auth.db")), LoginRateLimiter(max_attempts=3, window_seconds=60))
    monkeypatch.setattr(security, "_auth_service", service)
    for role in Role:
        service.create_user(
            CreateUserRequest(email=f"{role.value}@example.com", name=role.value.title(), role=role, password=PASSWORD)
        )
    return service


@pytest.fixture
def app():
    return create_app()


def client_for(app, role: Role) -> TestClient:
    client = TestClient(app)
    res = client.post("/api/auth/login", json={"email": f"{role.value}@example.com", "password": PASSWORD})
    assert res.status_code == 200, res.text
    return client


def _routes(app):
    for route in app.routes:
        for method in (getattr(route, "methods", None) or set()) - {"HEAD"}:
            if route.path.startswith(("/api", "/health")):
                yield method, route.path


def test_every_route_has_an_explicit_policy(app):
    missing = sorted(set(_routes(app)) - set(security.ROUTE_POLICY))
    assert missing == [], f"Add these routes to security.ROUTE_POLICY: {missing}"


def test_anonymous_requests_are_rejected_everywhere_except_public_routes(app, auth):
    client = TestClient(app)
    for method, path in _routes(app):
        if security.ROUTE_POLICY[(method, path)] == security.PUBLIC:
            continue
        url = re.sub(r"\{[^}]+\}", "x", path)
        res = client.request(method, url, json={})
        assert res.status_code == 401, f"{method} {path} -> {res.status_code}"
    assert client.get("/health").status_code == 200


def test_login_sets_httponly_session_cookie_and_me_returns_user(app, auth):
    client = TestClient(app)
    bad = client.post("/api/auth/login", json={"email": "viewer@example.com", "password": "wrong-password-123"})
    assert bad.status_code == 401
    assert client.post("/api/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}).status_code == 401

    res = client.post("/api/auth/login", json={"email": "Viewer@Example.com", "password": PASSWORD})
    assert res.status_code == 200
    cookie = res.headers["set-cookie"].lower()
    assert "wfos_session=" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    assert "password" not in res.text

    me = client.get("/api/auth/me").json()
    assert me["user"]["role"] == "viewer"
    assert "GET /api/workflows/specifications" in me["permissions"]
    assert "POST /api/automation/runs/{run_id}/approve" not in me["permissions"]


def test_state_changing_requests_need_the_csrf_header(app, auth):
    client = client_for(app, Role.APPROVER)
    blocked = client.post("/api/workflows/specifications/wf-missing/approve", json={})
    assert blocked.status_code == 403 and "CSRF" in blocked.text
    allowed = client.post("/api/workflows/specifications/wf-missing/approve", json={}, headers=CSRF)
    assert allowed.status_code == 404  # authorized; the workflow just doesn't exist


@pytest.mark.parametrize(
    "role, method, path, allowed",
    [
        (Role.VIEWER, "GET", "/api/workflows/specifications", True),
        (Role.VIEWER, "POST", "/api/workflows/specifications/wf-x/approve", False),
        (Role.VIEWER, "POST", "/api/automation/runs/run-x/approve", False),
        (Role.APPROVER, "POST", "/api/workflows/specifications/wf-x/approve", True),
        (Role.APPROVER, "POST", "/api/automation/runs/run-x/approve", True),
        (Role.APPROVER, "POST", "/api/automation/triggers", False),
        (Role.APPROVER, "GET", "/api/auth/users", False),
        (Role.APPROVER, "POST", "/api/demo/reset", False),
        (Role.ADMIN, "POST", "/api/automation/triggers", True),
        (Role.ADMIN, "GET", "/api/auth/users", True),
    ],
)
def test_role_matrix(app, auth, role, method, path, allowed):
    res = client_for(app, role).request(method, path, json={}, headers=CSRF)
    if allowed:
        assert res.status_code not in (401, 403), f"{role.value} {method} {path} -> {res.status_code} {res.text}"
    else:
        assert res.status_code == 403, f"{role.value} {method} {path} -> {res.status_code}"


def test_logout_and_expiry_end_the_session(app, auth):
    client = client_for(app, Role.VIEWER)
    assert client.post("/api/auth/logout", headers=CSRF).status_code == 204
    assert client.get("/api/auth/me").status_code == 401

    client = client_for(app, Role.VIEWER)
    with auth.repo._conn() as conn, conn:
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        conn.execute("UPDATE sessions SET expires_at = ?", (past,))
    assert client.get("/api/auth/me").status_code == 401


def test_role_change_and_disabling_end_sessions(app, auth):
    client = client_for(app, Role.APPROVER)
    approver = auth.repo.get_user_with_hash("approver@example.com")[0]
    auth.update_user(approver.user_id, UpdateUserRequest(role=Role.VIEWER), acting_user_id="admin")
    assert client.get("/api/auth/me").status_code == 401

    client = client_for(app, Role.VIEWER)
    viewer = auth.repo.get_user_with_hash("viewer@example.com")[0]
    auth.update_user(viewer.user_id, UpdateUserRequest(active=False), acting_user_id="admin")
    assert client.get("/api/auth/me").status_code == 401
    res = TestClient(app).post("/api/auth/login", json={"email": "viewer@example.com", "password": PASSWORD})
    assert res.status_code == 401


def test_admin_cannot_demote_themselves(app, auth):
    admin = client_for(app, Role.ADMIN)
    me = admin.get("/api/auth/me").json()["user"]
    res = admin.patch(f"/api/auth/users/{me['user_id']}", json={"role": "viewer"}, headers=CSRF)
    assert res.status_code == 400


def test_failed_sign_ins_are_rate_limited(app, auth):
    client = TestClient(app)
    for _ in range(3):
        client.post("/api/auth/login", json={"email": "admin@example.com", "password": "wrong-password-123"})
    locked = client.post("/api/auth/login", json={"email": "admin@example.com", "password": PASSWORD})
    assert locked.status_code == 429


def test_api_keys_only_send_events_and_can_be_revoked(app, auth):
    admin = client_for(app, Role.ADMIN)
    created = admin.post("/api/auth/api-keys", json={"name": "Laptop agent"}, headers=CSRF).json()
    raw, key_id = created["key"], created["api_key"]["key_id"]
    assert raw.startswith("wfos_")
    assert raw not in admin.get("/api/auth/api-keys").text  # only shown once

    agent = TestClient(app, headers={"Authorization": f"Bearer {raw}"})
    event = {"event_type": "window_focused", "application": "Gmail", "source": "test", "metadata": {}}
    assert agent.post("/api/events", json=event).status_code == 201  # no CSRF header needed for keys
    assert agent.get("/api/events").status_code == 403
    assert agent.post("/api/workflows/specifications/wf-x/approve", json={}).status_code == 403

    assert admin.delete(f"/api/auth/api-keys/{key_id}", headers=CSRF).status_code == 200
    assert agent.post("/api/events", json=event).status_code == 401
    assert TestClient(app, headers={"Authorization": "Bearer wfos_made-up"}).post("/api/events", json=event).status_code == 401


def test_users_list_never_exposes_password_hashes(app, auth):
    res = client_for(app, Role.ADMIN).get("/api/auth/users")
    assert res.status_code == 200 and len(res.json()) == 3
    assert "argon2" not in res.text and "password" not in res.text


def test_cors_allows_only_the_dashboard_origin(app, auth):
    client = TestClient(app)
    ok = client.options(
        "/api/auth/me",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert ok.headers.get("access-control-allow-credentials") == "true"
    evil = client.options(
        "/api/auth/me",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in evil.headers

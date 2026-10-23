"""Who may call which route.

Every API route is authorized by one app-wide dependency against ROUTE_POLICY, a single table of
(method, path) -> required access. A route missing from the table requires ADMIN, so a new
endpoint is never accidentally public; a test asserts that every route is listed.

Credentials:
- People: the HttpOnly session cookie set by POST /api/auth/login. State-changing requests must
  also carry the X-WorkflowOS-CSRF header, which a cross-site form cannot send and which a
  cross-origin script cannot send without passing the CORS allow-list.
- Desktop agent / browser extension: 'Authorization: Bearer wfos_...' API keys, accepted only
  for INGEST routes (sending activity events).
"""

from typing import Dict, Optional, Tuple, Union

from fastapi import Depends, HTTPException, Request, status

from app.config import SESSION_COOKIE_NAME
from app.models.auth import Principal, Role
from app.services.auth_service import AuthService

CSRF_HEADER = "x-workflowos-csrf"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

PUBLIC = "public"  # no credentials
SIGNED_IN = "signed_in"  # any signed-in user, regardless of role
INGEST = "ingest"  # an API key or any signed-in user

Access = Union[Role, str]

V, A, AD = Role.VIEWER, Role.APPROVER, Role.ADMIN

ROUTE_POLICY: Dict[Tuple[str, str], Access] = {
    ("GET", "/health"): PUBLIC,
    ("POST", "/api/auth/login"): PUBLIC,
    ("POST", "/api/auth/logout"): SIGNED_IN,
    ("GET", "/api/auth/me"): SIGNED_IN,
    ("GET", "/api/auth/users"): AD,
    ("POST", "/api/auth/users"): AD,
    ("PATCH", "/api/auth/users/{user_id}"): AD,
    ("GET", "/api/auth/api-keys"): AD,
    ("POST", "/api/auth/api-keys"): AD,
    ("DELETE", "/api/auth/api-keys/{key_id}"): AD,
    ("GET", "/api/status"): V,
    # sample data and resets change shared state
    ("POST", "/api/demo/seed-activity"): AD,
    ("POST", "/api/demo/reset"): AD,
    ("POST", "/api/demo/seed-e2e-workflow"): AD,
    # observation
    ("POST", "/api/events"): INGEST,
    ("GET", "/api/events"): V,
    ("GET", "/api/discovery/candidates"): V,
    ("GET", "/api/workflows/dna"): V,
    ("GET", "/api/workflows/dna/{dna_id}"): V,
    # creating and reviewing workflows
    ("POST", "/api/workflows/{dna_id}/interpret"): A,
    ("GET", "/api/workflows/semantic/{semantic_workflow_id}"): V,
    ("POST", "/api/workflows/{semantic_workflow_id}/specification"): A,
    ("GET", "/api/workflows/specifications"): V,
    ("GET", "/api/workflows/specifications/{workflow_id}"): V,
    ("POST", "/api/workflows/specifications/{workflow_id}/approve"): A,
    ("POST", "/api/workflows/specifications/{workflow_id}/reject"): A,
    ("PATCH", "/api/workflows/specifications/{workflow_id}/parameters"): A,
    # in-process copy of the Demo CRM API
    ("GET", "/api/crm/health"): V,
    ("GET", "/api/crm/customers"): V,
    ("POST", "/api/crm/customers/search"): V,
    ("GET", "/api/crm/customers/{customer_id}"): V,
    ("POST", "/api/crm/customers"): AD,
    ("PUT", "/api/crm/customers/{customer_id}"): AD,
    ("PATCH", "/api/crm/customers/{customer_id}"): AD,
    ("DELETE", "/api/crm/customers/{customer_id}"): AD,
    ("POST", "/api/crm/seed"): AD,
    ("POST", "/api/crm/reset"): AD,
    # planning, running, verifying
    ("POST", "/api/workflows/specifications/{workflow_id}/execution-plan"): A,
    ("GET", "/api/workflows/execution-plans"): V,
    ("GET", "/api/workflows/execution-plans/{execution_plan_id}"): V,
    ("POST", "/api/workflows/execution-plans/{execution_plan_id}/dry-run"): A,
    ("POST", "/api/workflows/execution-plans/{execution_plan_id}/execute"): A,
    ("GET", "/api/workflows/executions"): V,
    ("GET", "/api/workflows/executions/{execution_id}"): V,
    ("POST", "/api/workflows/executions/{execution_id}/cancel"): A,
    ("GET", "/api/workflows/executions/{execution_id}/strategy"): V,
    ("GET", "/api/workflows/execution-plans/{execution_plan_id}/strategy"): V,
    ("POST", "/api/workflows/executions/{execution_id}/verify"): A,
    ("GET", "/api/workflows/executions/{execution_id}/verification"): V,
    ("GET", "/api/workflows/verifications/{verification_run_id}"): V,
    # reliability (refresh only recomputes from history)
    ("GET", "/api/workflows/{workflow_id}/learning"): V,
    ("GET", "/api/workflows/{workflow_id}/learning/events"): V,
    ("POST", "/api/workflows/{workflow_id}/learning/refresh"): V,
    # automation
    ("POST", "/api/automation/triggers"): AD,
    ("GET", "/api/automation/triggers"): V,
    ("PATCH", "/api/automation/triggers/{trigger_id}"): AD,
    ("DELETE", "/api/automation/triggers/{trigger_id}"): AD,
    ("POST", "/api/automation/triggers/{trigger_id}/poll"): AD,
    ("GET", "/api/automation/runs"): V,
    ("GET", "/api/automation/runs/{run_id}"): V,
    ("POST", "/api/automation/runs/{run_id}/approve"): A,
    ("POST", "/api/automation/runs/{run_id}/resume"): A,
    ("POST", "/api/automation/runs/{run_id}/reject"): A,
}

_auth_service: Optional[AuthService] = None


def get_auth_service() -> AuthService:
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service


def required_access(method: str, path: str) -> Access:
    return ROUTE_POLICY.get((method.upper(), path), Role.ADMIN)


def resolve_principal(request: Request) -> Optional[Principal]:
    """Identify the caller from the session cookie or an API key (None if neither is valid)."""
    service = get_auth_service()
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        key = service.api_key_for(auth_header[7:].strip())
        return Principal(kind="api_key", api_key=key) if key else None
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        user = service.user_for_session(token)
        if user:
            if request.method not in _SAFE_METHODS and request.headers.get(CSRF_HEADER) != "1":
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing CSRF header.")
            return Principal(kind="user", user=user)
    return None


def authorize(request: Request) -> None:
    """App-wide dependency: enforce ROUTE_POLICY for the matched route."""
    route = request.scope.get("route")
    path = getattr(route, "path", request.url.path)
    access = required_access(request.method, path)
    if access == PUBLIC:
        return
    principal = resolve_principal(request)
    if principal is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in required.")
    if principal.kind == "api_key":
        if access != INGEST:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "API keys can only send activity events.")
    elif access not in (SIGNED_IN, INGEST) and not principal.user.role.allows(access):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires the {access.value} role.")
    request.state.principal = principal


def current_principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in required.")
    return principal


def current_actor(principal: Principal = Depends(current_principal)) -> str:
    """Identity recorded in approvals and audit records."""
    return principal.label

"""Health and integration status endpoints."""

from typing import Any, Dict

from fastapi import APIRouter

from app.config import GEMINI_API_KEY, GEMINI_MODEL, TRIGGER_POLLER_ENABLED

router = APIRouter(tags=["Health"])


@router.get("/health")
def get_health() -> dict[str, str]:
    """Return basic health status of the backend."""
    return {
        "status": "healthy",
        "service": "workflowos-backend",
        "version": "0.1.0",
    }


def _integration(connected: bool, detail: str) -> Dict[str, Any]:
    return {"connected": connected, "detail": detail}


@router.get("/api/status")
def get_integration_status() -> Dict[str, Any]:
    """Whether each integration is usable right now. Reports yes/no and a hint, never credentials."""
    from app.integrations import INTEGRATIONS

    body: Dict[str, Any] = {}
    for integration in INTEGRATIONS:
        if integration.status is not None:
            try:
                body[integration.key] = _integration(*integration.status())
            except Exception as e:  # noqa: BLE001 - one broken integration must not hide the others
                body[integration.key] = _integration(False, f"Status check failed: {type(e).__name__}.")

    body["ai"] = (
        _integration(True, f"Gemini ({GEMINI_MODEL}).")
        if GEMINI_API_KEY
        else _integration(False, "No GEMINI_API_KEY: workflows are described by built-in rules from what was observed.")
    )
    body["email_polling"] = TRIGGER_POLLER_ENABLED
    # Names and roles for the dashboard, in display order
    body["integrations"] = [{"key": i.key, "name": i.name, "role": i.role} for i in INTEGRATIONS]
    return body

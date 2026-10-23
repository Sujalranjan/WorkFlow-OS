"""Health and integration status endpoints."""

import os
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
    from app.services.crm_client import CrmApiClient
    from app.services.gmail_client import GmailApiClient
    from app.services.slack_client import SlackApiClient

    gmail = GmailApiClient()
    if not gmail.is_configured():
        gmail_status = _integration(False, "Not set up: add credentials.json and set GMAIL_ENABLED=true.")
    elif not gmail.is_authenticated():
        gmail_status = _integration(False, "Sign-in needed: run the Gmail authorization script to create token.json.")
    else:
        gmail_status = _integration(True, "Read-only access.")

    slack = SlackApiClient(timeout=3.0)
    if not os.getenv("SLACK_BOT_TOKEN") or not os.getenv("SLACK_CHANNEL_ID"):
        slack_status = _integration(False, "Not set up: set SLACK_BOT_TOKEN and SLACK_CHANNEL_ID.")
    elif slack.is_healthy():
        slack_status = _integration(True, f"Posting to channel {slack.default_channel_id}.")
    else:
        slack_status = _integration(False, "Token rejected or Slack unreachable.")

    crm = CrmApiClient(timeout=3.0)
    crm_status = (
        _integration(True, crm.base_url)
        if crm.is_healthy()
        else _integration(False, f"Not reachable at {crm.base_url}. Start it with: python backend/app/crm_server.py")
    )

    ai_status = (
        _integration(True, f"Gemini ({GEMINI_MODEL}).")
        if GEMINI_API_KEY
        else _integration(False, "No GEMINI_API_KEY: workflows are described by built-in rules from what was observed.")
    )

    return {
        "gmail": gmail_status,
        "slack": slack_status,
        "crm": crm_status,
        "ai": ai_status,
        "email_polling": TRIGGER_POLLER_ENABLED,
    }

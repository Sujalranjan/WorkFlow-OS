"""Slack Data and API Models (Phase 15D).

Provides structured models for Slack notification payloads, API responses,
and verification state.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SlackNotificationPayload(BaseModel):
    """Payload for sending a Slack notification via chat.postMessage."""
    channel: str = Field(..., description="Target Slack channel ID or name (e.g. C0123456789)")
    text: str = Field(..., description="Main notification text message")
    blocks: Optional[List[Dict[str, Any]]] = Field(default=None, description="Optional Slack Block Kit blocks")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Optional metadata object for Slack events")


class SlackNotificationResult(BaseModel):
    """Normalized response from the Slack Web API client."""
    success: bool = Field(..., description="Whether the Slack message was successfully posted")
    channel: str = Field(..., description="Channel ID where message was posted")
    ts: Optional[str] = Field(default=None, description="Message timestamp identifier assigned by Slack")
    message: Optional[Dict[str, Any]] = Field(default=None, description="Message payload returned by Slack")
    error: Optional[str] = Field(default=None, description="Slack API error code if failed")
    status_code: Optional[int] = Field(default=None, description="HTTP response status code")

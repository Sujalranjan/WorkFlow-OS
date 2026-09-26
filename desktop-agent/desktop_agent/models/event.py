"""Canonical Activity Event Model for WorkFlowOS Desktop Agent."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
import uuid
from pydantic import BaseModel, Field


class ActivityEventType(str, Enum):
    """Controlled set of activity event types supported in WorkFlowOS."""
    APPLICATION_OPENED = "application_opened"
    APPLICATION_CLOSED = "application_closed"
    WINDOW_FOCUSED = "window_focused"
    BROWSER_NAVIGATION = "browser_navigation"
    FILE_CREATED = "file_created"
    FILE_OPENED = "file_opened"
    FILE_DOWNLOADED = "file_downloaded"
    FILE_MOVED = "file_moved"
    FORM_SUBMITTED = "form_submitted"
    GENERIC_UI_ACTION = "generic_ui_action"


class ActivityEvent(BaseModel):
    """Structured activity event representation."""
    event_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for the activity event",
    )
    event_type: ActivityEventType = Field(
        ...,
        description="Type of activity event",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp representing when the event occurred",
    )
    application: Optional[str] = Field(
        default=None,
        description="Application associated with the event (e.g., 'Chrome', 'Notepad')",
    )
    source: str = Field(
        default="desktop_agent",
        description="Origin source of the event",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary event-specific contextual metadata",
    )

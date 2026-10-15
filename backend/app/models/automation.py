"""Automation models: email triggers and the workflow runs they create.

An EmailTrigger watches Gmail (read-only) for new messages matching a query and links them
to an APPROVED CanonicalWorkflowSpec. Each new message becomes exactly one WorkflowRun in
PENDING_APPROVAL; nothing executes until a person approves that run.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, Field

MIN_POLL_INTERVAL_SECONDS = 30


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class EmailTrigger(BaseModel):
    """Watches Gmail for new messages matching `gmail_query` and queues runs of `workflow_id`."""

    trigger_id: str = Field(default_factory=lambda: f"trg-{uuid.uuid4().hex[:12]}")
    workflow_id: str = Field(..., description="APPROVED CanonicalWorkflowSpec this trigger starts")
    name: str = Field(..., description="Human-readable trigger name")
    gmail_query: str = Field(..., description="Gmail search query a new message must match")
    enabled: bool = Field(default=True)
    poll_interval_seconds: int = Field(default=60, ge=MIN_POLL_INTERVAL_SECONDS)
    active_since: int = Field(
        default_factory=lambda: int(datetime.now(timezone.utc).timestamp()),
        description="Unix seconds; only messages received after this are considered",
    )
    created_at: str = Field(default_factory=_now)
    last_polled_at: Optional[str] = Field(default=None)
    last_error: Optional[str] = Field(default=None)


class RunStatus(str, Enum):
    """Lifecycle of a triggered workflow run."""

    PENDING_APPROVAL = "PENDING_APPROVAL"
    RUNNING = "RUNNING"
    NEEDS_INPUT = "NEEDS_INPUT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    REJECTED = "REJECTED"


ACTIVE_RUN_STATUSES = (RunStatus.PENDING_APPROVAL, RunStatus.RUNNING, RunStatus.NEEDS_INPUT)


class SourceEmail(BaseModel):
    """Minimal metadata of the message that started a run (never the body)."""

    message_id: str
    thread_id: Optional[str] = None
    subject: Optional[str] = None
    sender: Optional[str] = None
    snippet: Optional[str] = None
    received_at: Optional[str] = None
    attachment_names: List[str] = Field(default_factory=list)


class WorkflowRun(BaseModel):
    """One execution request created by a trigger for one incoming email."""

    run_id: str = Field(default_factory=lambda: f"run-{uuid.uuid4().hex[:12]}")
    trigger_id: str
    workflow_id: str
    source_email: SourceEmail
    gmail_query: str = Field(..., description="Trigger query the email matched (used as the run's search_query)")
    status: RunStatus = Field(default=RunStatus.PENDING_APPROVAL)
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    decided_by: Optional[str] = Field(default=None, description="Who approved or rejected the run")
    execution_plan_id: Optional[str] = None
    execution_id: Optional[str] = None
    verification_status: Optional[str] = None
    intervention: Optional[Dict[str, Any]] = Field(
        default=None, description="What the paused step needs (parameter, reason, candidates)"
    )
    error: Optional[str] = None


class CreateTriggerRequest(BaseModel):
    workflow_id: str
    gmail_query: str = Field(..., min_length=1)
    name: Optional[str] = None
    poll_interval_seconds: int = Field(default=60, ge=MIN_POLL_INTERVAL_SECONDS)
    include_existing_since: Optional[int] = Field(
        default=None,
        description="Optional Unix seconds to also pick up messages received before the trigger was created",
    )


class UpdateTriggerRequest(BaseModel):
    enabled: Optional[bool] = None
    gmail_query: Optional[str] = Field(default=None, min_length=1)
    poll_interval_seconds: Optional[int] = Field(default=None, ge=MIN_POLL_INTERVAL_SECONDS)


class PollResult(BaseModel):
    trigger_id: str
    polled_at: str
    matched: int = 0
    new_runs: List[WorkflowRun] = Field(default_factory=list)
    error: Optional[str] = None


class RunDecisionRequest(BaseModel):
    decided_by: str = Field(default="operator", min_length=1)


class ResumeRunRequest(BaseModel):
    inputs: Dict[str, str] = Field(..., description="Values for the parameter the paused step asked for")
    decided_by: str = Field(default="operator", min_length=1)

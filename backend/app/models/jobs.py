"""Background jobs: slow or external work (running a workflow, verifying it, polling Gmail)."""

from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    # Interrupted after it may have changed something outside WorkFlowOS (CRM, Slack, files).
    # Never retried automatically: a person checks the outside systems, then dismisses it.
    NEEDS_ATTENTION = "needs_attention"
    DISMISSED = "dismissed"


ACTIVE_JOB_STATUSES = (JobStatus.QUEUED, JobStatus.RUNNING)
FINISHED_JOB_STATUSES = (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.NEEDS_ATTENTION, JobStatus.DISMISSED)


class Job(BaseModel):
    job_id: str
    kind: str
    status: JobStatus
    payload: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None
    attempts: int = 0
    max_attempts: int = 1
    run_after: str
    locked_by: Optional[str] = None
    locked_until: Optional[str] = None
    side_effects_started: bool = False
    dedupe_key: Optional[str] = None
    last_error: Optional[str] = None
    created_by: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None

    @property
    def finished(self) -> bool:
        return self.status in FINISHED_JOB_STATUSES

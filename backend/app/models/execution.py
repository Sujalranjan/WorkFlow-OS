"""Execution models for Phase 8: Execution Engine Foundation + Controlled Local Execution.

Defines:
- ExecutionMode (DRY_RUN, LIVE)
- ExecutionStepStatus (PENDING, RUNNING, SUCCESS, FAILED, BLOCKED, SKIPPED, CANCELLED)
- ExecutionOverallStatus (PENDING, RUNNING, COMPLETED, FAILED, CANCELLED, BLOCKED)
- ExecutionContext
- ExecutionStepResult
- ExecutionAuditRecord / ExecutionRecord
- ExecutePlanRequest
- ExecutionListResponse
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field

from app.models.execution_plan import ExecutionStrategy


class ExecutionMode(str, Enum):
    """Mode of execution."""
    DRY_RUN = "DRY_RUN"
    LIVE = "LIVE"

    @classmethod
    def _missing_(cls, value: object) -> Optional["ExecutionMode"]:
        if isinstance(value, str):
            for member in cls:
                if member.value.upper() == value.upper():
                    return member
        return None


class ExecutionStepStatus(str, Enum):
    """Status of an individual executed step."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"

    @classmethod
    def _missing_(cls, value: object) -> Optional["ExecutionStepStatus"]:
        if isinstance(value, str):
            for member in cls:
                if member.value.upper() == value.upper():
                    return member
        return None


class ExecutionOverallStatus(str, Enum):
    """Aggregate lifecycle status of a workflow execution."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"

    @classmethod
    def _missing_(cls, value: object) -> Optional["ExecutionOverallStatus"]:
        if isinstance(value, str):
            for member in cls:
                if member.value.upper() == value.upper():
                    return member
        return None


class ExecutionStepResult(BaseModel):
    """Structured record of a single step execution outcome."""
    execution_step_id: str = Field(default_factory=lambda: f"exec-step-{uuid.uuid4().hex[:12]}")
    planned_step_id: str = Field(..., description="ID of the PlannedStep")
    action_name: str = Field(..., description="Action title executed or attempted")
    target_application: str = Field(..., description="Target application or system")
    strategy: ExecutionStrategy = Field(..., description="Execution strategy used")
    executor_name: str = Field(..., description="Name of the Executor implementation that handled this step")
    status: ExecutionStepStatus = Field(default=ExecutionStepStatus.PENDING)
    parameters_used: Dict[str, Any] = Field(default_factory=dict)
    output: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = Field(default=None)
    affected_resources: List[str] = Field(default_factory=list, description="Files, artifacts, or entities created/modified")
    start_time: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    end_time: Optional[str] = Field(default=None)
    # Phase 10: Multi-strategy & capability audit fields
    selected_strategy: Optional[str] = Field(default=None, description="Canonical strategy type selected")
    selection_reason: Optional[str] = Field(default=None, description="Deterministic strategy selection reason")
    candidate_strategies: List[str] = Field(default_factory=list, description="Candidate strategies evaluated")
    fallback_used: bool = Field(default=False, description="Whether fallback selection was used")
    policy_decision: Optional[str] = Field(default=None, description="Policy check outcome: ALLOWED or BLOCKED")
    blocked_reason: Optional[str] = Field(default=None, description="Standardized block reason if step was not executable")



class ExecutionContext(BaseModel):
    """Runtime context passed to executors."""
    execution_id: str = Field(..., description="Unique execution run identifier")
    workflow_id: str = Field(..., description="CanonicalWorkflowSpec workflow_id")
    workflow_version: str = Field(default="1.0.0")
    execution_plan_id: str = Field(..., description="ID of the source ExecutionPlan")
    resolved_parameters: Dict[str, Any] = Field(default_factory=dict)
    sandbox_root: str = Field(..., description="Absolute path to strictly isolated sandbox folder")
    execution_mode: ExecutionMode = Field(default=ExecutionMode.LIVE)
    current_step_number: int = Field(default=1)
    execution_start_time: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    dry_run: bool = Field(default=False)


class ExecutionAuditRecord(BaseModel):
    """Comprehensive, immutable audit record of a workflow execution run."""
    execution_id: str = Field(
        default_factory=lambda: f"exec-{uuid.uuid4().hex[:12]}",
        description="Unique execution ID",
    )
    workflow_id: str = Field(..., description="Source CanonicalWorkflowSpec ID")
    workflow_version: str = Field(default="1.0.0")
    execution_plan_id: str = Field(..., description="Source ExecutionPlan ID")
    approval_state: str = Field(..., description="Approval state of the workflow (must be 'approved')")
    approved_by: Optional[str] = Field(default=None)
    execution_mode: ExecutionMode = Field(default=ExecutionMode.LIVE)
    status: ExecutionOverallStatus = Field(default=ExecutionOverallStatus.PENDING)
    sandbox_root: str = Field(..., description="Absolute directory of the execution sandbox")
    start_time: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    end_time: Optional[str] = Field(default=None)
    step_results: List[ExecutionStepResult] = Field(default_factory=list)
    affected_resources: List[str] = Field(default_factory=list)
    error_summary: Optional[str] = Field(default=None)
    executed_by: str = Field(default="workflowos-engine", description="Initiator of execution")
    idempotency_key: Optional[str] = Field(default=None, description="Client or plan idempotency token")
    verification_status: Optional[str] = Field(default=None, description="Aggregated verification status (VERIFIED, FAILED, UNKNOWN, NOT_APPLICABLE)")
    verification_id: Optional[str] = Field(default=None, description="Linked VerificationResult ID")


class ExecutePlanRequest(BaseModel):
    """Request payload to initiate execution of an approved execution plan."""
    idempotency_key: Optional[str] = Field(default=None, description="Optional key to prevent duplicate runs")
    execution_mode: ExecutionMode = Field(default=ExecutionMode.LIVE)
    sandbox_dir: Optional[str] = Field(default=None, description="Optional custom sandbox subfolder inside allowed sandbox root")


class ExecutionListResponse(BaseModel):
    """Response payload listing execution audit records."""
    total_count: int
    executions: List[ExecutionAuditRecord]

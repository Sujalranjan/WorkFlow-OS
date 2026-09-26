"""Verification models for Phase 9: Post-Execution Verification + Evidence Engine.

Defines:
- VerificationStatus (PENDING, VERIFIED, FAILED, UNKNOWN, NOT_APPLICABLE)
- VerificationStrategyType (FILE_SYSTEM, STRUCTURED_OUTPUT, RESOURCE_EXISTENCE, STATE_MATCH, NOT_APPLICABLE)
- VerificationCheck (individual atomic check for a planned step)
- VerificationResult (workflow-level verification run result with aggregated counts & evidence)
- VerifyExecutionRequest & VerificationListResponse
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field


class VerificationStatus(str, Enum):
    """Lifecycle status of a verification check or overall verification run."""
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"

    @classmethod
    def _missing_(cls, value: object) -> Optional["VerificationStatus"]:
        if isinstance(value, str):
            for member in cls:
                if member.value.upper() == value.upper():
                    return member
        return None


class VerificationStrategyType(str, Enum):
    """Strategy mechanism used to inspect post-execution state."""
    FILE_SYSTEM = "FILE_SYSTEM"
    STRUCTURED_OUTPUT = "STRUCTURED_OUTPUT"
    RESOURCE_EXISTENCE = "RESOURCE_EXISTENCE"
    STATE_MATCH = "STATE_MATCH"
    NOT_APPLICABLE = "NOT_APPLICABLE"

    @classmethod
    def _missing_(cls, value: object) -> Optional["VerificationStrategyType"]:
        if isinstance(value, str):
            for member in cls:
                if member.value.upper() == value.upper():
                    return member
        return None


class VerificationCheck(BaseModel):
    """Formal atomic verification check evaluating expected vs actual state."""
    verification_id: str = Field(
        default_factory=lambda: f"vcheck-{uuid.uuid4().hex[:12]}",
        description="Unique verification check identifier",
    )
    execution_id: str = Field(..., description="ID of the execution run")
    execution_step_id: str = Field(..., description="ID of the executed step result")
    planned_step_id: str = Field(..., description="ID of the source planned step")
    check_type: str = Field(..., description="Type of verification check (e.g., file_exists, non_empty_file, structured_json_field)")
    strategy_type: VerificationStrategyType = Field(
        default=VerificationStrategyType.FILE_SYSTEM,
        description="Verification strategy employed",
    )
    target: str = Field(..., description="Target file path, entity, or resource checked")
    expected_state: Any = Field(..., description="State or outcome expected to exist")
    actual_state: Any = Field(..., description="State empirically observed by verification engine")
    status: VerificationStatus = Field(default=VerificationStatus.PENDING)
    evidence: Dict[str, Any] = Field(
        default_factory=dict,
        description="Empirical evidence (path, file size, sha256 hash, timestamps)",
    )
    reason: str = Field(..., description="Explainable reason describing WHY check verified or failed")
    checked_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class VerificationResult(BaseModel):
    """Aggregated verification outcome for an entire workflow execution run."""
    verification_run_id: str = Field(
        default_factory=lambda: f"vrun-{uuid.uuid4().hex[:12]}",
        description="Unique identifier for this verification evaluation",
    )
    execution_id: str = Field(..., description="ID of the verified execution run")
    workflow_id: str = Field(..., description="Source CanonicalWorkflowSpec ID")
    execution_plan_id: str = Field(..., description="Source ExecutionPlan ID")
    overall_status: VerificationStatus = Field(
        default=VerificationStatus.PENDING,
        description="Aggregated workflow verification status",
    )
    checks: List[VerificationCheck] = Field(default_factory=list)
    verified_count: int = Field(default=0, description="Count of passed verification checks")
    failed_count: int = Field(default=0, description="Count of failed verification checks")
    unknown_count: int = Field(default=0, description="Count of unknown/inconclusive checks")
    not_applicable_count: int = Field(default=0, description="Count of non-applicable checks (skipped, external)")
    evidence: Dict[str, Any] = Field(default_factory=dict, description="Consolidated evidence payload")
    started_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = Field(default=None)


class VerifyExecutionRequest(BaseModel):
    """Request payload to initiate deterministic verification of an execution run."""
    force_recheck: bool = Field(default=False, description="Whether to re-evaluate and create a new verification run")
    custom_expectations: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional explicit verification expectations for testing mismatch scenarios",
    )


class VerificationListResponse(BaseModel):
    """Response payload listing verification results."""
    total_count: int
    verifications: List[VerificationResult]

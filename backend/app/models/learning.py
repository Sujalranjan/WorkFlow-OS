"""Workflow Learning & Reliability Intelligence Models (Phase 11).

Defines:
- FailureCategory (EXECUTION_FAILURE, VERIFICATION_FAILURE, POLICY_BLOCK, UNSUPPORTED_STRATEGY, PARAMETER_PROBLEM, UNKNOWN_OUTCOME)
- LearningEventType (EXECUTION_SUCCESS_OBSERVED, EXECUTION_FAILURE_OBSERVED, VERIFICATION_FAILURE_OBSERVED, STRATEGY_BLOCK_OBSERVED, PARAMETER_PROBLEM_OBSERVED, RELIABILITY_THRESHOLD_REACHED, IMPROVEMENT_SUGGESTED)
- LearningThresholds (deterministic thresholds for insights)
- WorkflowLearningEvent (audit event of an observed execution/verification outcome)
- StepReliability (step-level empirical reliability metrics)
- DetectedPattern (repeated failure or success patterns with supporting evidence)
- ImprovementSuggestion (advisory, evidence-backed human-in-the-loop suggestion)
- WorkflowReliabilityProfile (comprehensive workflow-level reliability metrics & intelligence)
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field


class FailureCategory(str, Enum):
    """Deterministic failure classification based on empirical execution and verification evidence."""
    EXECUTION_FAILURE = "EXECUTION_FAILURE"
    VERIFICATION_FAILURE = "VERIFICATION_FAILURE"
    POLICY_BLOCK = "POLICY_BLOCK"
    UNSUPPORTED_STRATEGY = "UNSUPPORTED_STRATEGY"
    PARAMETER_PROBLEM = "PARAMETER_PROBLEM"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"

    @classmethod
    def _missing_(cls, value: object) -> Optional["FailureCategory"]:
        if isinstance(value, str):
            for member in cls:
                if member.value.upper() == value.upper():
                    return member
        return None


class LearningEventType(str, Enum):
    """Types of learning events recorded during execution and verification aggregation."""
    EXECUTION_SUCCESS_OBSERVED = "EXECUTION_SUCCESS_OBSERVED"
    EXECUTION_FAILURE_OBSERVED = "EXECUTION_FAILURE_OBSERVED"
    VERIFICATION_FAILURE_OBSERVED = "VERIFICATION_FAILURE_OBSERVED"
    STRATEGY_BLOCK_OBSERVED = "STRATEGY_BLOCK_OBSERVED"
    PARAMETER_PROBLEM_OBSERVED = "PARAMETER_PROBLEM_OBSERVED"
    RELIABILITY_THRESHOLD_REACHED = "RELIABILITY_THRESHOLD_REACHED"
    IMPROVEMENT_SUGGESTED = "IMPROVEMENT_SUGGESTED"

    @classmethod
    def _missing_(cls, value: object) -> Optional["LearningEventType"]:
        if isinstance(value, str):
            for member in cls:
                if member.value.upper() == value.upper():
                    return member
        return None


class LearningThresholds(BaseModel):
    """Configurable, deterministic thresholds for reliability intelligence and pattern detection."""
    min_executions_for_reliability_insight: int = Field(
        default=1,
        description="Minimum total executions required to emit reliability insights",
    )
    repeated_failure_threshold: int = Field(
        default=2,
        description="Consecutive or repeated verification/execution failures required to trigger pattern",
    )
    repeated_block_threshold: int = Field(
        default=2,
        description="Number of unsupported strategy blocks required to trigger pattern",
    )
    repeated_parameter_problem_threshold: int = Field(
        default=2,
        description="Number of parameter resolution issues required to trigger pattern",
    )
    high_reliability_threshold: int = Field(
        default=2,
        description="Number of consecutive verified executions required to trigger high reliability milestone",
    )


class WorkflowLearningEvent(BaseModel):
    """Empirical event recorded by the Learning Engine during history analysis."""
    event_id: str = Field(
        default_factory=lambda: f"levent-{uuid.uuid4().hex[:12]}",
        description="Unique identifier for the learning event",
    )
    workflow_id: str = Field(..., description="Target CanonicalWorkflowSpec ID")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Timestamp of observation",
    )
    event_type: LearningEventType = Field(..., description="Type of learning event observed")
    execution_id: Optional[str] = Field(default=None, description="Linked execution audit ID")
    verification_id: Optional[str] = Field(default=None, description="Linked verification run ID")
    planned_step_id: Optional[str] = Field(default=None, description="Affected step ID")
    step_action: Optional[str] = Field(default=None, description="Affected step action")
    observed_evidence: Dict[str, Any] = Field(
        default_factory=dict,
        description="Empirical data (execution outcome, error message, verification check state)",
    )
    insight: str = Field(..., description="Deterministic, evidence-grounded insight description")
    confidence: float = Field(
        default=1.0,
        description="Deterministic confidence score between 0.0 and 1.0",
    )


class StepReliability(BaseModel):
    """Step-level empirical reliability metrics traceable to canonical workflow steps."""
    planned_step_id: str = Field(..., description="Canonical or planned step identifier")
    action: str = Field(..., description="Action name executed or planned")
    target: str = Field(..., description="Target application or subsystem")
    selected_strategy: Optional[str] = Field(
        default=None,
        description="Canonical strategy type used or evaluated",
    )
    total_executions: int = Field(default=0, description="Total execution attempts")
    successful_executions: int = Field(default=0, description="Executor reported SUCCESS")
    failed_executions: int = Field(default=0, description="Executor reported FAILED")
    blocked_executions: int = Field(default=0, description="Step was safely BLOCKED")
    verified_success_count: int = Field(default=0, description="Step verified successfully post-execution")
    verification_failure_count: int = Field(default=0, description="Step failed post-execution verification")
    last_outcome: str = Field(default="UNKNOWN", description="Outcome of most recent execution")
    failure_pattern: Optional[str] = Field(
        default=None,
        description="Detected failure pattern string if one exists",
    )


class DetectedPattern(BaseModel):
    """Deterministic failure or success pattern discovered across historical executions."""
    pattern_id: str = Field(
        default_factory=lambda: f"pat-{uuid.uuid4().hex[:12]}",
        description="Unique pattern identifier",
    )
    pattern_type: str = Field(
        ...,
        description="Pattern category (e.g., REPEATED_VERIFICATION_FAILURE, REPEATED_UNSUPPORTED_STRATEGY)",
    )
    description: str = Field(..., description="Human-understandable factual pattern description")
    affected_step_id: Optional[str] = Field(default=None, description="Affected step identifier")
    affected_action: Optional[str] = Field(default=None, description="Affected step action")
    occurrence_count: int = Field(default=0, description="Number of times pattern was observed")
    evidence_execution_ids: List[str] = Field(
        default_factory=list,
        description="Execution IDs exhibiting this pattern",
    )
    evidence_verification_ids: List[str] = Field(
        default_factory=list,
        description="Verification IDs exhibiting this pattern",
    )


class ImprovementSuggestion(BaseModel):
    """Advisory, evidence-backed improvement suggestion for human review."""
    suggestion_id: str = Field(
        default_factory=lambda: f"sug-{uuid.uuid4().hex[:12]}",
        description="Unique suggestion identifier",
    )
    workflow_id: str = Field(..., description="Target workflow specification ID")
    affected_step_id: Optional[str] = Field(default=None, description="Affected step identifier")
    affected_step_action: Optional[str] = Field(default=None, description="Affected action")
    category: str = Field(
        ...,
        description="Category: VERIFICATION_DEFINITION, STRATEGY_REQUIREMENT, PARAMETER_CONFIG, HIGH_RELIABILITY",
    )
    title: str = Field(..., description="Brief suggestion summary")
    suggestion: str = Field(..., description="Actionable recommendation for human consideration")
    evidence: Dict[str, Any] = Field(
        default_factory=dict,
        description="Traceable empirical evidence supporting this recommendation",
    )
    is_advisory: bool = Field(
        default=True,
        description="Guarantees suggestion is purely advisory and requires human action",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Timestamp of generation",
    )


class WorkflowReliabilityProfile(BaseModel):
    """Comprehensive, deterministic reliability intelligence profile for a workflow."""
    profile_id: str = Field(
        default_factory=lambda: f"rel-prof-{uuid.uuid4().hex[:12]}",
        description="Unique reliability profile identifier",
    )
    workflow_id: str = Field(..., description="Target CanonicalWorkflowSpec ID")
    total_executions: int = Field(default=0, description="Total execution attempts recorded")
    successful_executions: int = Field(default=0, description="Completed executable executions")
    failed_executions: int = Field(default=0, description="Failed execution attempts")
    blocked_executions: int = Field(default=0, description="Safely blocked executions")
    verified_executions: int = Field(default=0, description="Executions verified successfully (VERIFIED)")
    verification_failures: int = Field(
        default=0,
        description="Executions where executor succeeded but verification FAILED",
    )
    unknown_verifications: int = Field(
        default=0,
        description="Executions with inconclusive verification (UNKNOWN)",
    )
    execution_success_rate: float = Field(
        default=0.0,
        description="successful_executions / executable_attempts (0.0 - 1.0)",
    )
    verification_rate: float = Field(
        default=0.0,
        description="verified_executions / successful_executions (0.0 - 1.0)",
    )
    blocked_rate: float = Field(
        default=0.0,
        description="blocked_executions / total_executions (0.0 - 1.0)",
    )
    reliability_rate: float = Field(
        default=0.0,
        description="verified_executions / completed_executable_executions (0.0 - 1.0)",
    )
    last_execution_at: Optional[str] = Field(default=None, description="Timestamp of latest execution")
    last_success_at: Optional[str] = Field(default=None, description="Timestamp of latest verified success")
    last_failure_at: Optional[str] = Field(default=None, description="Timestamp of latest failure/block")
    step_reliabilities: List[StepReliability] = Field(
        default_factory=list,
        description="Step-level reliability metrics",
    )
    detected_patterns: List[DetectedPattern] = Field(
        default_factory=list,
        description="Discovered empirical patterns",
    )
    suggestions: List[ImprovementSuggestion] = Field(
        default_factory=list,
        description="Advisory improvement suggestions",
    )
    latest_events: List[WorkflowLearningEvent] = Field(
        default_factory=list,
        description="Recent learning audit events",
    )
    computed_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Timestamp of profile computation",
    )

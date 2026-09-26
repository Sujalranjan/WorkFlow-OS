"""Execution Plan & Dry Run Simulation Models (Phase 7).

Represents:
- Deterministic execution plan derived from an APPROVED CanonicalWorkflowSpec.
- Strategy selection with explainable reasoning (API, App Integration, Semantic UI, Browser, Fallback).
- Explicit parameter resolution (Definition vs Observed vs Runtime vs Unresolved).
- Expected state changes (Before vs Expected After vs Actual Untouched).
- Precondition verification (Satisfied, Unsatisfied, Unknown).
- Dry-run / shadow mode simulation reporting SIMULATED with ZERO real actions.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field

from app.models.canonical import RiskAssessment, StepRisk
from app.models.dna import WorkflowBoundaries


class ExecutionStrategy(str, Enum):
    """Supported execution strategy categories."""
    API = "api"
    APPLICATION_INTEGRATION = "application_integration"
    ACCESSIBILITY_SEMANTIC_UI = "accessibility_semantic_ui"
    BROWSER_AUTOMATION = "browser_automation"
    UI_FALLBACK = "ui_fallback"
    CONTROLLED_LOCAL = "controlled_local"



class ParameterResolutionStatus(str, Enum):
    """Resolution state of a workflow parameter for execution."""
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    DEFAULT_SAMPLE = "default_sample"


class ResolvedParameter(BaseModel):
    """Explicitly tracks runtime parameter resolution without LLM invention."""
    source_parameter: str = Field(..., description="Immutable source parameter from WorkflowDNA")
    semantic_name: str = Field(..., description="Human-assigned semantic name")
    source_field: str = Field(..., description="Source field in event metadata")
    inferred_type: str = Field(..., description="Inferred variable type")
    sample_observed_values: List[str] = Field(default_factory=list, description="Sample values from observations")
    runtime_value: Optional[str] = Field(default=None, description="Actual resolved runtime value")
    resolution_status: ParameterResolutionStatus = Field(
        default=ParameterResolutionStatus.UNRESOLVED,
        description="Whether parameter was resolved, unresolved, or defaulted to sample",
    )
    is_required: bool = Field(default=True, description="Whether this parameter is required for execution")


class PreconditionStatus(str, Enum):
    """Status of workflow preconditions during planning / dry run."""
    SATISFIED = "satisfied"
    UNSATISFIED = "unsatisfied"
    UNKNOWN = "unknown"


class PreconditionCheck(BaseModel):
    """Evaluation of a single structural precondition."""
    condition: str = Field(..., description="Precondition statement")
    status: PreconditionStatus = Field(default=PreconditionStatus.UNKNOWN, description="Evaluation status")
    evaluation_reason: str = Field(..., description="Explainable reason for this status evaluation")


class ExpectedStateChange(BaseModel):
    """Clear contrast between expected state change and untouched actual state."""
    target_system: str = Field(..., description="Target system (e.g. 'CRM', 'Slack', 'File System')")
    entity_or_property: str = Field(..., description="Entity or property affected")
    before_state: str = Field(..., description="State prior to step execution")
    expected_after_state: str = Field(..., description="Expected state after step would execute")
    actual_state: str = Field(
        default="UNTOUCHED (Simulation Mode - No Real Actions Executed)",
        description="Actual state in real environment (strictly untouched in Phase 7)",
    )


class StepExecutionStrategy(BaseModel):
    """Strategy selection and explainability for a single planned step."""
    strategy: ExecutionStrategy = Field(..., description="Selected execution strategy")
    reason: str = Field(..., description="Explainable reason for selecting this strategy")
    target_technology: str = Field(..., description="Underlying mechanism or integration technology")
    # Phase 10: Multi-strategy & capability enrichment
    canonical_strategy: Optional[str] = Field(default=None, description="Canonical ExecutionStrategyType token")
    selection_reason: Optional[str] = Field(default=None, description="Deterministic strategy selection reason")
    available_strategies_considered: List[str] = Field(default_factory=list, description="All strategies evaluated")
    rejected_strategies: List[str] = Field(default_factory=list, description="Strategies rejected")
    rejection_reasons: Dict[str, str] = Field(default_factory=dict, description="Reasons for rejection of candidate strategies")
    fallback_used: bool = Field(default=False, description="Whether fallback selection was invoked")
    executor_implemented: bool = Field(default=False, description="Whether the selected executor is implemented")
    blocked_reason: Optional[str] = Field(default=None, description="Block reason code if step is unexecutable")
    policy_decision: str = Field(default="ALLOWED", description="Security policy decision: ALLOWED or BLOCKED")



class PlannedStep(BaseModel):
    """A planned workflow step preserving 100% traceability back to observation."""
    plan_step_id: str = Field(..., description="Planned step ID (e.g. 'plan-step-1')")
    source_canonical_step_id: str = Field(..., description="Traceability link to CanonicalStep")
    source_semantic_step_id: str = Field(..., description="Traceability link to SemanticStep")
    source_dna_step_key: str = Field(..., description="Traceability link to InvariantStep")
    application: str = Field(..., description="Target application name")
    action: str = Field(..., description="Action title")
    description: str = Field(..., description="Detailed action intent")
    resolved_parameters: Dict[str, Optional[str]] = Field(
        default_factory=dict,
        description="Map of parameter names to resolved values",
    )
    execution_strategy: StepExecutionStrategy = Field(..., description="Planned strategy and rationale")
    risk: StepRisk = Field(..., description="Inherited risk classification from Phase 6")
    expected_result: str = Field(..., description="What this step is expected to accomplish")
    external_change: bool = Field(default=False, description="Whether this step would mutate external state")
    requires_confirmation: bool = Field(default=False, description="Whether explicit human confirmation is required")
    evidence_reference: str = Field(..., description="Citation to empirical evidence")
    state_change: ExpectedStateChange = Field(..., description="Expected state transition")


class DryRunStepResult(BaseModel):
    """Outcome of simulating a single step in dry-run mode."""
    plan_step_id: str
    application: str
    action: str
    strategy: ExecutionStrategy
    simulation_status: str = Field(default="SIMULATED", description="'SIMULATED' or 'BLOCKED_UNRESOLVED'")
    risk_level: str
    risk_category: str
    external_mutation_prevented: bool = True
    expected_state_transition: str
    simulated_output: Dict[str, Any] = Field(default_factory=dict)
    notes: str
    # Phase 10: Multi-strategy & capability fields
    selected_strategy: Optional[str] = Field(default=None, description="Selected strategy or 'NONE'")
    candidate_strategies: List[str] = Field(default_factory=list, description="Strategies considered")
    selection_reason: Optional[str] = Field(default=None, description="Why this strategy was selected or blocked")
    fallback_used: bool = Field(default=False, description="Whether fallback strategy was used")
    policy_decision: str = Field(default="ALLOWED", description="'ALLOWED' or 'BLOCKED'")
    is_executable: bool = Field(default=True, description="Whether step has a compatible implemented executor")



class DryRunResult(BaseModel):
    """Comprehensive outcome of a dry-run / shadow simulation."""
    dry_run_id: str = Field(default_factory=lambda: f"dry-run-{uuid.uuid4().hex[:12]}")
    simulated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    overall_simulation_status: str = Field(default="SIMULATED", description="'SIMULATED' or 'SIMULATION_BLOCKED'")
    step_simulations: List[DryRunStepResult] = Field(default_factory=list)
    precondition_checks: List[PreconditionCheck] = Field(default_factory=list)
    real_actions_performed: int = Field(default=0, description="Guaranteed ZERO real actions performed")
    external_mutations_prevented: int = Field(default=0)
    summary: str = Field(..., description="Human-readable dry run summary")


class ExecutionPlan(BaseModel):
    """The canonical, deterministic execution plan ready for dry run simulation."""
    execution_plan_id: str = Field(
        default_factory=lambda: f"exec-plan-{uuid.uuid4().hex[:12]}",
        description="Unique execution plan ID",
    )
    source_workflow_id: str = Field(..., description="Source CanonicalWorkflowSpec ID")
    workflow_version: str = Field(default="1.0.0", description="Workflow version")
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source_approval_state: str = Field(..., description="Approval state of source specification (must be 'approved')")
    resolved_parameters: List[ResolvedParameter] = Field(default_factory=list)
    planned_steps: List[PlannedStep] = Field(default_factory=list)
    preconditions: List[PreconditionCheck] = Field(default_factory=list)
    boundaries: WorkflowBoundaries = Field(..., description="Workflow duration and step boundaries")
    risk_assessment: RiskAssessment = Field(..., description="Inherited Phase 6 risk assessment")
    expected_effects: List[ExpectedStateChange] = Field(default_factory=list)
    dry_run_status: str = Field(default="not_started", description="'not_started', 'simulated', 'simulation_failed'")
    dry_run_result: Optional[DryRunResult] = Field(default=None)


class CreateExecutionPlanRequest(BaseModel):
    """Request payload to generate an execution plan."""
    runtime_parameters: Optional[Dict[str, str]] = Field(
        default=None,
        description="Optional runtime parameter values (semantic_name -> value or source_parameter -> value)",
    )


class ExecutionPlanListResponse(BaseModel):
    """Response payload listing execution plans."""
    total_count: int
    plans: List[ExecutionPlan]

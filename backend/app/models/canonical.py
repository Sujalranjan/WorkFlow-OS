"""Canonical Workflow Specification Models (Phase 6).

Represents the formal, executable-ready workflow contract combining:
- Deterministic structural constraints from WorkflowDNA
- Validated semantic intent from SemanticWorkflow
- Explicit parameter bindings with deterministic type inference
- Explainable risk analysis per step
- Human approval lifecycle state machine

STRICT PRINCIPLE:
No executable code is produced. Approval signifies human acceptance of
the workflow specification, NOT automated execution.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field

from app.models.dna import DNAEvidence, OrderingConstraint, WorkflowBoundaries


class VariableType(str, Enum):
    """Deterministically inferred variable data types."""
    STRING = "string"
    FILENAME = "filename"
    APPLICATION = "application"
    IDENTIFIER = "identifier"
    TIMESTAMP = "timestamp"
    UNKNOWN = "unknown"


class ParameterBinding(BaseModel):
    """Explicit, traceable binding between a structural parameter and a semantic name."""
    binding_id: str = Field(
        default_factory=lambda: f"bind-{uuid.uuid4().hex[:8]}",
        description="Unique identifier for this parameter binding",
    )
    source_parameter: str = Field(
        ...,
        description="Immutable deterministic parameter identifier from WorkflowDNA (e.g. 'window_title_variable_1')",
    )
    semantic_name: str = Field(
        ...,
        description="Human-intelligible semantic name (e.g. 'customer_name', 'client_name')",
    )
    source_field: str = Field(
        ...,
        description="Underlying metadata field location (e.g. 'metadata.window_title')",
    )
    associated_step_key: str = Field(
        ...,
        description="Action key of the step generating this parameter (e.g. 'crm:window_focused')",
    )
    associated_application: str = Field(
        ...,
        description="Application where the variable is observed",
    )
    observed_values: List[str] = Field(
        default_factory=list,
        description="Values observed across supporting sessions",
    )
    inferred_type: VariableType = Field(
        default=VariableType.UNKNOWN,
        description="Deterministically inferred data type based on metadata evidence (never LLM-generated)",
    )
    binding_status: str = Field(
        default="bound",
        description="Binding status: 'bound', 'unbound', or 'user_modified'",
    )
    user_override: bool = Field(
        default=False,
        description="Whether the semantic name was customized by a human user",
    )
    confidence: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Confidence score inherited from semantic variable interpretation",
    )


class RiskCategory(str, Enum):
    """Standardized deterministic risk classification categories."""
    READ_ONLY = "read_only"
    LOCAL_CHANGE = "local_change"
    EXTERNAL_CHANGE = "external_change"
    COMMUNICATION = "communication"
    POTENTIALLY_SENSITIVE = "potentially_sensitive"


class RiskLevel(str, Enum):
    """Risk severity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class StepRisk(BaseModel):
    """Deterministic risk analysis and explainability for a single workflow step."""
    step_id: str = Field(..., description="Canonical step identifier")
    application: str = Field(..., description="Application targeted by this step")
    action: str = Field(..., description="Action description")
    risk_level: RiskLevel = Field(..., description="Calculated risk severity level")
    risk_category: RiskCategory = Field(..., description="Risk category classification")
    reason: str = Field(..., description="Explainable justification for this risk classification")
    requires_confirmation: bool = Field(
        default=False,
        description="Whether an eventual executor should require explicit human confirmation for this step",
    )


class RiskAssessment(BaseModel):
    """Comprehensive workflow-level risk assessment."""
    overall_risk_level: RiskLevel = Field(..., description="Highest or aggregated workflow risk level")
    primary_risk_category: RiskCategory = Field(..., description="Dominant risk category")
    requires_human_confirmation: bool = Field(
        default=True,
        description="Whether human review is recommended prior to any future automated execution",
    )
    step_risks: List[StepRisk] = Field(default_factory=list, description="Per-step risk breakdown")
    summary: str = Field(..., description="Human-readable risk assessment summary")
    sensitive_factors_detected: List[str] = Field(
        default_factory=list,
        description="List of detected sensitive keywords or external mutations",
    )


class ApprovalState(str, Enum):
    """Formal lifecycle states for workflow approval."""
    DRAFT = "draft"
    REQUIRES_REVIEW = "requires_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalMetadata(BaseModel):
    """Tracks human review status and governance metadata."""
    state: ApprovalState = Field(
        default=ApprovalState.REQUIRES_REVIEW,
        description="Current approval state. Newly generated workflows always require review.",
    )
    reviewed_by: Optional[str] = Field(
        default=None,
        description="Identifier of the human reviewer who approved or rejected the specification",
    )
    reviewed_at: Optional[str] = Field(
        default=None,
        description="ISO 8601 timestamp when review action occurred",
    )
    rejection_reason: Optional[str] = Field(
        default=None,
        description="Explanation provided if the workflow was rejected",
    )
    comments: Optional[str] = Field(
        default=None,
        description="Optional reviewer notes or instructions",
    )


class CanonicalStep(BaseModel):
    """Formal workflow step preserving complete end-to-end traceability."""
    canonical_step_id: str = Field(..., description="Canonical step ID (e.g. 'can-step-1')")
    source_semantic_step_id: str = Field(..., description="Pointer to source SemanticStep ID")
    source_dna_step_key: str = Field(..., description="Pointer to source WorkflowDNA InvariantStep key")
    application: str = Field(..., description="Canonical application name")
    event_type: str = Field(..., description="Activity event type")
    action: str = Field(..., description="Semantic action title")
    description: str = Field(..., description="Detailed semantic intent description")
    input_variables: List[str] = Field(default_factory=list, description="Semantic variables consumed")
    output_variables: List[str] = Field(default_factory=list, description="Semantic variables produced")
    evidence_reference: str = Field(..., description="Direct citation to empirical session evidence")
    risk: StepRisk = Field(..., description="Step risk classification and explanation")
    occurrence_ratio: float = Field(default=1.0, description="Empirical occurrence ratio across sessions")
    classification: str = Field(default="invariant", description="Step classification")


class CanonicalOptionalStep(BaseModel):
    """Optional branch step in canonical specification."""
    canonical_step_id: str = Field(..., description="Canonical optional step ID")
    source_semantic_step_id: str = Field(..., description="Pointer to source SemanticOptionalStep ID")
    source_dna_step_key: str = Field(..., description="Pointer to source WorkflowDNA OptionalStep key")
    application: str = Field(..., description="Application name")
    event_type: str = Field(..., description="Activity event type")
    condition_or_trigger: str = Field(..., description="Trigger condition for this branch")
    description: str = Field(..., description="Semantic description of optional step")
    risk: StepRisk = Field(..., description="Risk classification")
    occurrence_ratio: float = Field(..., description="Observed occurrence ratio")
    classification: str = Field(default="optional", description="Step classification")


class CanonicalWorkflowSpec(BaseModel):
    """The canonical, executable-ready workflow specification.

    Combines deterministic WorkflowDNA ground truth with validated SemanticWorkflow
    intent, explicit parameter bindings, risk analysis, and human approval governance.
    """
    workflow_id: str = Field(
        default_factory=lambda: f"wf-spec-{uuid.uuid4().hex[:12]}",
        description="Unique identifier for this canonical workflow specification",
    )
    source_dna_id: str = Field(..., description="ID of source WorkflowDNA")
    source_semantic_workflow_id: str = Field(..., description="ID of source SemanticWorkflow")
    title: str = Field(..., description="Human-understandable workflow title")
    intent: str = Field(..., description="High-level operational business intent")
    description: str = Field(..., description="Comprehensive workflow executive summary")
    version: str = Field(default="1.0.0", description="Specification version")
    status: str = Field(default="specification_ready", description="Lifecycle specification status")
    steps: List[CanonicalStep] = Field(default_factory=list, description="Ordered canonical steps")
    variables: List[ParameterBinding] = Field(default_factory=list, description="Bound workflow parameters")
    optional_steps: List[CanonicalOptionalStep] = Field(default_factory=list, description="Optional steps")
    preconditions: List[str] = Field(default_factory=list, description="Prerequisite conditions")
    boundaries: WorkflowBoundaries = Field(..., description="Empirical workflow boundaries")
    ordering_constraints: List[OrderingConstraint] = Field(default_factory=list, description="Ordering precedence rules")
    evidence: DNAEvidence = Field(..., description="Underlying empirical session evidence")
    parameter_bindings: List[ParameterBinding] = Field(
        default_factory=list,
        description="Explicit parameter bindings list",
    )
    risk_assessment: RiskAssessment = Field(..., description="Comprehensive risk assessment")
    approval_state: ApprovalMetadata = Field(
        default_factory=ApprovalMetadata,
        description="Human governance and approval state machine",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Timestamp of creation",
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Timestamp of last update",
    )


class ParameterUpdateItem(BaseModel):
    """Single parameter update payload."""
    source_parameter: str = Field(..., description="Target deterministic source parameter (must exist)")
    semantic_name: str = Field(..., description="New human-chosen semantic name")


class ParameterUpdateRequest(BaseModel):
    """Payload for updating parameter bindings."""
    updates: List[ParameterUpdateItem] = Field(..., description="List of parameter updates")


class ApprovalActionRequest(BaseModel):
    """Payload for approving or rejecting a workflow specification."""
    reviewer: Optional[str] = Field(default="user", description="Name or identifier of the reviewer")
    comments: Optional[str] = Field(default=None, description="Optional reviewer comments")
    reason: Optional[str] = Field(default=None, description="Reason for rejection if rejecting")


class SpecificationListResponse(BaseModel):
    """Response containing multiple workflow specifications."""
    total_count: int
    specifications: List[CanonicalWorkflowSpec]

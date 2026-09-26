"""Canonical Workflow DNA Models (Phase 4).

Represents the extracted structural DNA of a discovered workflow candidate:
- Invariant steps (occur across 100% of supporting sessions)
- Variable parameters (changing values across executions with structural templates)
- Optional steps (appear in a subset of supporting sessions)
- Ordering constraints (pairwise before/after relationships)
- Preconditions (structural requirements for workflow validity)
- Boundaries (first/last steps, timing boundaries)
- Explainable evidence and statistical provenance
"""

from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field


class InvariantStep(BaseModel):
    """A workflow step that consistently occurs across all valid supporting executions."""
    step_key: str = Field(..., description="Normalized action key (e.g. 'gmail:window_focused')")
    application: str = Field(..., description="Canonical application name")
    event_type: str = Field(..., description="Activity event type")
    occurrences: int = Field(..., description="Count of supporting sessions containing this step")
    total_sessions: int = Field(..., description="Total supporting sessions analyzed")
    occurrence_ratio: float = Field(..., description="Occurrence ratio (1.0 for true invariants)")
    classification: str = Field(default="invariant", description="Classification label")


class OptionalStep(BaseModel):
    """A workflow step that occurs in only a subset of supporting executions."""
    step_key: str = Field(..., description="Normalized action key (e.g. 'excel:window_focused')")
    application: str = Field(..., description="Canonical application name")
    event_type: str = Field(..., description="Activity event type")
    occurrences: int = Field(..., description="Count of supporting sessions containing this step")
    total_sessions: int = Field(..., description="Total supporting sessions analyzed")
    occurrence_ratio: float = Field(..., description="Ratio of sessions containing this step (< 1.0)")
    supporting_session_ids: List[str] = Field(default_factory=list, description="Session IDs where step was observed")
    classification: str = Field(default="optional", description="Classification label")


class VariableParameter(BaseModel):
    """A dynamic parameter candidate extracted from changing metadata across executions."""
    parameter_name: str = Field(..., description="Deterministic parameter identifier (e.g. 'filename_variable_1')")
    source_field: str = Field(..., description="Metadata field location (e.g. 'metadata.file_name')")
    associated_step_key: str = Field(..., description="Action key of the step generating this parameter")
    associated_application: str = Field(..., description="Application where variable is observed")
    observed_values: List[str] = Field(default_factory=list, description="Unique values observed across sessions")
    distinct_value_count: int = Field(..., description="Number of distinct values observed")
    total_observations: int = Field(..., description="Total observations across supporting sessions")
    variation_ratio: float = Field(..., description="Ratio of distinct values to total observations")
    pattern_template: Optional[str] = Field(
        default=None,
        description="Structural pattern template if identified (e.g. 'invoice_{variable}.pdf')",
    )


class OrderingConstraint(BaseModel):
    """Pairwise precedence constraint consistently observed across supporting sessions."""
    predecessor: str = Field(..., description="Step that consistently executes earlier")
    successor: str = Field(..., description="Step that consistently executes later")
    consistency_ratio: float = Field(default=1.0, description="Fraction of sessions respecting this order")
    description: str = Field(..., description="Human-readable constraint description")


class WorkflowBoundaries(BaseModel):
    """Structural and temporal boundaries of the workflow."""
    first_step: str = Field(..., description="Earliest consistent step in the workflow")
    last_step: str = Field(..., description="Final consistent step in the workflow")
    min_duration_seconds: float = Field(..., description="Shortest observed session duration")
    max_duration_seconds: float = Field(..., description="Longest observed session duration")
    average_duration_seconds: float = Field(..., description="Mean observed session duration")
    total_supporting_sessions: int = Field(..., description="Total number of supporting sessions")


class DNAEvidence(BaseModel):
    """Explainable evidence detailing how and why each DNA element was derived."""
    supporting_session_count: int
    invariant_evidence: str
    variable_evidence: str
    optional_step_evidence: str
    ordering_evidence: str
    boundary_evidence: str


class WorkflowDNA(BaseModel):
    """Canonical Workflow DNA: The structured, explainable blueprint of a discovered workflow."""
    dna_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for the Workflow DNA record",
    )
    source_candidate_id: str = Field(..., description="ID of the source DiscoveryCandidate")
    normalized_signature: str = Field(..., description="Canonical signature of the workflow")
    version: str = Field(default="1.0.0", description="DNA schema specification version")
    invariant_steps: List[InvariantStep] = Field(default_factory=list, description="Core invariant steps")
    variable_parameters: List[VariableParameter] = Field(default_factory=list, description="Dynamic variable parameters")
    optional_steps: List[OptionalStep] = Field(default_factory=list, description="Optional or branch steps")
    ordering_constraints: List[OrderingConstraint] = Field(default_factory=list, description="Pairwise ordering rules")
    preconditions: List[str] = Field(default_factory=list, description="Structural preconditions for validity")
    boundaries: WorkflowBoundaries = Field(..., description="Structural and temporal boundaries")
    evidence: DNAEvidence = Field(..., description="Explainable evidence model")
    statistics: Dict[str, Any] = Field(default_factory=dict, description="Numerical metrics and summary statistics")

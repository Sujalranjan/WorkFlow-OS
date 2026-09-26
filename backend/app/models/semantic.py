"""Canonical Pydantic models for Semantic Understanding & Intent Translation (Phase 5).

Represents the validated semantic interpretation of a deterministic WorkflowDNA.
"""

from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field
from app.models.dna import WorkflowBoundaries, WorkflowDNA


class SemanticStep(BaseModel):
    """Human-understandable semantic interpretation of an observed WorkflowDNA step."""
    step_id: str = Field(
        default_factory=lambda: f"sem-step-{uuid.uuid4().hex[:8]}",
        description="Identifier for this semantic step",
    )
    source_dna_step_key: str = Field(
        ...,
        description="Corresponding deterministic action key from WorkflowDNA (e.g. 'gmail:window_focused')",
    )
    application: str = Field(
        ...,
        description="Application name corresponding to this step",
    )
    action: str = Field(
        ...,
        description="Concise semantic action description (e.g. 'Open customer replacement request')",
    )
    description: str = Field(
        ...,
        description="Detailed explanation of the semantic purpose and intent of this step",
    )
    input_variables: List[str] = Field(
        default_factory=list,
        description="Semantic variable names consumed or referenced as inputs in this step",
    )
    output_variables: List[str] = Field(
        default_factory=list,
        description="Semantic variable names produced, updated, or extracted by this step",
    )
    evidence_reference: str = Field(
        ...,
        description="Reference to observed DNA evidence supporting this semantic step interpretation",
    )


class SemanticVariable(BaseModel):
    """Semantic mapping of a deterministic structural variable parameter."""
    source_parameter: str = Field(
        ...,
        description="Original deterministic parameter identifier (e.g. 'window_title_variable_1')",
    )
    semantic_name: str = Field(
        ...,
        description="Evidence-grounded semantic entity name (e.g. 'customer_name', 'request_document')",
    )
    source_field: str = Field(
        ...,
        description="Underlying metadata source field (e.g. 'metadata.window_title')",
    )
    observed_values: List[str] = Field(
        default_factory=list,
        description="Sample observed values from supporting session evidence",
    )
    reason: str = Field(
        ...,
        description="Detailed justification explaining why this semantic name was chosen based on evidence",
    )
    model_interpretation_confidence: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="LLM-estimated confidence score (0.0 to 1.0). Explicitly labeled as an LLM estimate, not ground truth.",
    )


class SemanticOptionalStep(BaseModel):
    """Semantic interpretation of an optional workflow step."""
    step_id: str = Field(
        default_factory=lambda: f"sem-opt-{uuid.uuid4().hex[:8]}",
        description="Identifier for this optional semantic step",
    )
    source_dna_step_key: str = Field(
        ...,
        description="Corresponding deterministic action key from WorkflowDNA optional steps",
    )
    application: str = Field(
        ...,
        description="Application name for this optional step",
    )
    condition_or_trigger: str = Field(
        ...,
        description="Semantic condition, trigger, or branch context under which this step appears",
    )
    description: str = Field(
        ...,
        description="Explanation of the optional step's intent",
    )


class SemanticWorkflow(BaseModel):
    """Canonical representation of a validated, human-understandable semantic workflow.

    Derived from a deterministic WorkflowDNA via LLM semantic interpretation and validated
    against deterministic structural invariants.
    """
    semantic_workflow_id: str = Field(
        default_factory=lambda: f"sem-wf-{uuid.uuid4().hex[:12]}",
        description="Unique identifier for this semantic workflow",
    )
    source_dna_id: str = Field(
        ...,
        description="ID of the underlying deterministic WorkflowDNA",
    )
    title: str = Field(
        ...,
        description="High-level human-readable workflow title (e.g. 'Customer Replacement Request Processing')",
    )
    intent: str = Field(
        ...,
        description="Core operational objective and business purpose of the workflow",
    )
    summary: str = Field(
        ...,
        description="Concise multi-step executive summary of the routine",
    )
    semantic_steps: List[SemanticStep] = Field(
        ...,
        description="Ordered semantic steps mapped 1-to-1 with observed WorkflowDNA invariants",
    )
    semantic_variables: List[SemanticVariable] = Field(
        default_factory=list,
        description="Semantic parameters mapped to structural variable candidates",
    )
    optional_steps: List[SemanticOptionalStep] = Field(
        default_factory=list,
        description="Optional semantic steps mapped to DNA optional steps",
    )
    preconditions: List[str] = Field(
        default_factory=list,
        description="Human-intelligible prerequisite conditions for starting this workflow",
    )
    boundaries: WorkflowBoundaries = Field(
        ...,
        description="Empirical workflow boundary metrics from underlying DNA",
    )
    evidence_mapping: Dict[str, str] = Field(
        default_factory=dict,
        description="Direct mapping between semantic claims and underlying deterministic evidence",
    )
    interpretation_notes: str = Field(
        ...,
        description="Explanatory notes regarding ambiguities, assumptions, or reasoning from the interpreter",
    )
    model_provider: str = Field(
        default="gemini-1.5-flash",
        description="Identifier of the model or provider that generated this interpretation",
    )
    status: str = Field(
        default="interpreted",
        description="Status of semantic processing: 'interpreted', 'fallback', or 'error'",
    )


class InterpretationResponse(BaseModel):
    """API response model for workflow semantic interpretation."""
    status: str = Field(
        ...,
        description="Processing outcome: 'success', 'fallback', or 'error'",
    )
    semantic_workflow: Optional[SemanticWorkflow] = Field(
        default=None,
        description="The validated SemanticWorkflow if interpretation succeeded",
    )
    source_dna: WorkflowDNA = Field(
        ...,
        description="The underlying deterministic WorkflowDNA",
    )
    message: str = Field(
        ...,
        description="Human-readable outcome or fallback diagnostic message",
    )
    validation_passed: bool = Field(
        default=False,
        description="Whether deterministic semantic validation passed",
    )
    validation_errors: List[str] = Field(
        default_factory=list,
        description="List of validation error messages if validation failed",
    )

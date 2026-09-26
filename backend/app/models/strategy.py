"""Execution Strategy and Capability Models for WorkFlowOS (Phase 10).

Defines:
- ExecutionStrategyType: Canonical execution strategy categories.
- ExecutorCapability: Deterministic capability metadata exposed by executors.
- StrategyCandidate: Evaluation record for an executor candidate during selection.
- StrategySelectionResult: Deterministic outcome of strategy selection for a step.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ExecutionStrategyType(str, Enum):
    """Canonical execution strategy types in WorkFlowOS."""
    CONTROLLED_LOCAL = "CONTROLLED_LOCAL"
    API_INTEGRATION = "API_INTEGRATION"
    APPLICATION_INTEGRATION = "APPLICATION_INTEGRATION"
    ACCESSIBILITY_UI = "ACCESSIBILITY_UI"
    BROWSER_AUTOMATION = "BROWSER_AUTOMATION"
    UI_FALLBACK = "UI_FALLBACK"

    @classmethod
    def is_implemented(cls, strategy: "ExecutionStrategyType") -> bool:
        """Determines if this strategy type has a working, implemented executor in Phase 10."""
        return strategy == cls.CONTROLLED_LOCAL


class ExecutorCapability(BaseModel):
    """Deterministic capability metadata exposed by an executor."""
    strategy_type: ExecutionStrategyType = Field(..., description="Canonical strategy type handled by this executor")
    executor_name: str = Field(..., description="Unique executor implementation identifier")
    supported_actions: List[str] = Field(default_factory=list, description="Allowlisted actions supported by this executor")
    supported_targets: List[str] = Field(default_factory=list, description="Allowlisted target applications or systems")
    supported_risk_levels: List[str] = Field(default_factory=list, description="Risk levels permitted (e.g. 'LOW', 'MEDIUM')")
    implemented: bool = Field(default=False, description="Whether this executor is actually implemented in the system")
    requires_external_access: bool = Field(default=False, description="Whether this executor requires outbound network or external access")
    supports_verification: bool = Field(default=True, description="Whether actions performed by this executor support post-verification")
    priority: int = Field(default=100, description="Fallback priority order (lower number = higher priority)")
    description: str = Field(default="", description="Human-readable capability description")


class StrategyCandidate(BaseModel):
    """Evaluation record for a potential executor candidate during deterministic selection."""
    strategy: ExecutionStrategyType = Field(..., description="Strategy evaluated")
    executor_name: str = Field(..., description="Candidate executor name")
    is_implemented: bool = Field(..., description="Whether executor is implemented")
    is_supported: bool = Field(..., description="Whether step action/target match executor capabilities")
    is_policy_allowed: bool = Field(..., description="Whether step passes security policy for this executor")
    priority: int = Field(default=100, description="Fallback priority rank")
    rejection_reason: Optional[str] = Field(default=None, description="Detailed reason if candidate was rejected")


class StrategySelectionResult(BaseModel):
    """Deterministic outcome of strategy selection for a single planned step."""
    plan_step_id: str = Field(..., description="ID of the planned step")
    action: str = Field(..., description="Action title evaluated")
    target: str = Field(..., description="Target application evaluated")
    selected_strategy: Optional[ExecutionStrategyType] = Field(
        default=None,
        description="Selected canonical execution strategy, or None if no supported executor exists",
    )
    selected_executor: Optional[str] = Field(
        default=None,
        description="Name of the selected executor, or None if blocked",
    )
    is_executable: bool = Field(
        default=False,
        description="True if an implemented, authorized executor was selected; False if blocked",
    )
    selection_reason: str = Field(..., description="Deterministic, explainable rationale for the selection or block")
    fallback_used: bool = Field(default=False, description="Whether a secondary/fallback strategy was selected")
    blocked_reason: Optional[str] = Field(
        default=None,
        description="Standardized block token (e.g. 'UNSUPPORTED_EXECUTION_STRATEGY', 'POLICY_REJECTED_RISK')",
    )
    policy_decision: str = Field(default="ALLOWED", description="'ALLOWED' or 'BLOCKED'")
    candidates_considered: List[StrategyCandidate] = Field(
        default_factory=list,
        description="All candidate strategies evaluated in priority order",
    )
    rejected_strategies: List[str] = Field(
        default_factory=list,
        description="List of strategy names that were rejected",
    )
    rejection_reasons: Dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of rejected strategy names to their respective rejection reasons",
    )

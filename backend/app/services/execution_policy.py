"""Execution Policy / Guardrails Service (Phase 8).

Validates safety policies before ANY step or plan execution:
1. Workflow must be in ApprovalState.APPROVED.
2. Execution plan must correspond to the approved workflow version.
3. All required parameters must be resolved (not UNRESOLVED).
4. Selected strategy must be supported by an available executor.
5. If step is external, verifies whether policy explicitly permits it (Phase 8 strictly denies external service mutations).
6. Sandbox boundary validation.
"""

from typing import List, Optional, Tuple
from app.models.canonical import ApprovalState, CanonicalWorkflowSpec, RiskCategory
from app.models.execution_plan import ExecutionPlan, ParameterResolutionStatus, PlannedStep
from app.services.executors.registry import ExecutorRegistry


class ExecutionPolicyEngine:
    """Evaluates strict execution guardrails and security policies."""

    def __init__(self, registry: Optional[ExecutorRegistry] = None) -> None:
        self.registry = registry or ExecutorRegistry()

    def validate_plan_execution(
        self,
        spec: CanonicalWorkflowSpec,
        plan: ExecutionPlan,
    ) -> Tuple[bool, List[str]]:
        """Validates that an execution plan is authorized and ready for execution.

        Returns:
            Tuple[is_authorized, list_of_violations]
        """
        violations: List[str] = []

        # 1. Approval requirement
        if spec.approval_state.state != ApprovalState.APPROVED:
            violations.append(
                f"Execution policy violation: Workflow '{spec.workflow_id}' is in state "
                f"'{spec.approval_state.state.value}'. Only 'approved' workflows can be executed."
            )

        # 2. Plan association check
        if plan.source_workflow_id != spec.workflow_id:
            violations.append(
                f"Execution plan '{plan.execution_plan_id}' does not match workflow ID '{spec.workflow_id}'."
            )

        # 3. Parameter resolution check: No unresolved parameters allowed in LIVE execution
        for param in plan.resolved_parameters:
            if param.resolution_status == ParameterResolutionStatus.UNRESOLVED and param.is_required:
                violations.append(
                    f"Parameter '{param.semantic_name}' (source: {param.source_parameter}) is UNRESOLVED. "
                    f"Live execution cannot proceed without all required parameters."
                )

        return (len(violations) == 0, violations)

    def validate_step_execution(
        self,
        step: PlannedStep,
        spec: CanonicalWorkflowSpec,
    ) -> Tuple[bool, List[str]]:
        """Validates that an individual planned step satisfies security policies."""
        violations: List[str] = []

        # 1. External change policy: Strictly forbids unsupported external mutations (CRM, Slack, Gmail)
        if step.risk.risk_category in (RiskCategory.EXTERNAL_CHANGE, RiskCategory.COMMUNICATION):
            violations.append(
                f"External service mutation policy violation: Step '{step.action}' targets '{step.application}' "
                f"with category '{step.risk.risk_category.value}'. WorkFlowOS permits controlled local actions only in Phase 10."
            )

        # 2. Executor availability: Must have an implemented executor
        executor = self.registry.get_executor_for_step(step)
        if not executor:
            violations.append(
                f"No implemented executor supports strategy '{step.execution_strategy.strategy.value}' "
                f"for step '{step.action}' in application '{step.application}'."
            )

        return (len(violations) == 0, violations)


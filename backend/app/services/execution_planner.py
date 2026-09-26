"""Execution Planner Service (Phase 7).

Converts an APPROVED CanonicalWorkflowSpec into a deterministic ExecutionPlan:
1. Validates that the workflow specification is formally approved.
2. Resolves runtime parameters without LLM invention.
3. Selects execution strategies with explainable rationale (API, App Integration, Accessibility, Browser, Fallback).
4. Derives expected state transitions (Before vs Expected After vs Actual Untouched).
5. Evaluates structural preconditions (Satisfied, Unsatisfied, Unknown).
6. Inherits deterministic Phase 6 risk classifications and confirmation requirements.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional
import uuid

from app.models.canonical import ApprovalState, CanonicalStep, CanonicalWorkflowSpec, RiskCategory
from app.models.execution_plan import (
    ExecutionPlan,
    ExecutionStrategy,
    ExpectedStateChange,
    ParameterResolutionStatus,
    PlannedStep,
    PreconditionCheck,
    PreconditionStatus,
    ResolvedParameter,
    StepExecutionStrategy,
)


from app.services.strategy_selector import StrategySelector


class ExecutionPlanner:
    """Creates deterministic execution plans from approved canonical specifications."""

    def __init__(self, strategy_selector: Optional[StrategySelector] = None) -> None:
        self.strategy_selector = strategy_selector or StrategySelector()

    def select_strategy(self, app_name: str, action: str, risk_cat: RiskCategory) -> StepExecutionStrategy:
        """Select an execution strategy deterministically and provide an explainable reason."""
        app_lower = app_name.lower()

        action_lower = action.lower()

        # 1. External enterprise applications (CRM, ERP, Database)
        if any(crm in app_lower for crm in ["crm", "salesforce", "hubspot", "database"]):
            if risk_cat == RiskCategory.EXTERNAL_CHANGE or any(w in action_lower for w in ["update", "modify", "save"]):
                return StepExecutionStrategy(
                    strategy=ExecutionStrategy.APPLICATION_INTEGRATION,
                    reason="External CRM record mutation requires a controlled application integration boundary with transactional rollback safeguards.",
                    target_technology="Enterprise CRM Connector / REST SDK",
                )
            return StepExecutionStrategy(
                strategy=ExecutionStrategy.ACCESSIBILITY_SEMANTIC_UI,
                reason="Read-only CRM inspection utilizes OS semantic accessibility tree to locate window controls.",
                target_technology="Windows UI Automation (UIA)",
            )

        # 2. Team Communication & Alerts (Slack, Teams, Webhook)
        if any(comm in app_lower for comm in ["slack", "teams", "webhook"]):
            return StepExecutionStrategy(
                strategy=ExecutionStrategy.API,
                reason="Outbound team notifications can be reliably executed through a direct service API or webhook without UI interaction.",
                target_technology="Slack Webhook / Incoming API",
            )

        # 3. Web Browsers (Chrome, Firefox, Edge)
        if any(b in app_lower for b in ["chrome", "firefox", "edge", "browser"]):
            return StepExecutionStrategy(
                strategy=ExecutionStrategy.BROWSER_AUTOMATION,
                reason="Web application navigation and interaction requires controlled browser automation.",
                target_technology="Web Browser DOM Automation",
            )

        # 4. Local File System & Office
        if any(f in app_lower for f in ["file system", "folder", "download", "excel"]):
            return StepExecutionStrategy(
                strategy=ExecutionStrategy.APPLICATION_INTEGRATION,
                reason="File download verification and disk access operates through local OS filesystem integration APIs.",
                target_technology="Local OS File System API",
            )

        # 5. Default Desktop Accessibility (e.g. Gmail desktop / window focus)
        return StepExecutionStrategy(
            strategy=ExecutionStrategy.ACCESSIBILITY_SEMANTIC_UI,
            reason="Window activation and observation utilizes native Windows Accessibility API.",
            target_technology="Windows UI Automation (UIA)",
        )

    def resolve_parameters(
        self,
        spec: CanonicalWorkflowSpec,
        runtime_inputs: Optional[Dict[str, str]] = None,
    ) -> List[ResolvedParameter]:
        """Resolve parameters deterministically from runtime inputs or observed samples.

        Enforces:
        - DNA source parameter names remain immutable.
        - Unresolved parameters are explicitly marked as UNRESOLVED.
        - Never allows the LLM to invent missing values.
        """
        runtime_inputs = runtime_inputs or {}
        resolved: List[ResolvedParameter] = []

        for b in spec.variables:
            # Check runtime input by source_parameter first, then by semantic_name
            val = runtime_inputs.get(b.source_parameter)
            if val is None:
                val = runtime_inputs.get(b.semantic_name)

            if val is not None and str(val).strip():
                status = ParameterResolutionStatus.RESOLVED
                runtime_val = str(val).strip()
            elif b.observed_values and len(b.observed_values) > 0:
                # Fall back to observed sample value if available
                status = ParameterResolutionStatus.DEFAULT_SAMPLE
                runtime_val = b.observed_values[0]
            else:
                status = ParameterResolutionStatus.UNRESOLVED
                runtime_val = None

            resolved.append(
                ResolvedParameter(
                    source_parameter=b.source_parameter,
                    semantic_name=b.semantic_name,
                    source_field=b.source_field,
                    inferred_type=b.inferred_type.value,
                    sample_observed_values=list(b.observed_values),
                    runtime_value=runtime_val,
                    resolution_status=status,
                    is_required=True,
                )
            )

        return resolved

    def build_expected_state_change(
        self,
        step: CanonicalStep,
        resolved_params: Dict[str, Optional[str]],
    ) -> ExpectedStateChange:
        """Derive explicit before/after expected state transitions."""
        app = step.application
        action_lower = step.action.lower()

        # Find helpful parameter values for context
        cust_name = next((v for k, v in resolved_params.items() if "customer" in k or "client" in k or "name" in k), "target customer")
        file_name = next((v for k, v in resolved_params.items() if "file" in k or "invoice" in k), "downloaded file")

        if "crm" in app.lower():
            return ExpectedStateChange(
                target_system=app,
                entity_or_property=f"Customer Record for '{cust_name}'",
                before_state=f"Customer record '{cust_name}' in CRM has previous status without replacement processing details",
                expected_after_state=f"Customer record '{cust_name}' in CRM updated with replacement status and reference to '{file_name}'",
            )

        if "slack" in app.lower():
            return ExpectedStateChange(
                target_system=app,
                entity_or_property="Operations Notification Channel",
                before_state=f"No notification exists in Slack for '{cust_name}' replacement request",
                expected_after_state=f"Notification message broadcast in Slack with summary and replacement status for '{cust_name}'",
            )

        if "file" in app.lower():
            return ExpectedStateChange(
                target_system=app,
                entity_or_property=f"Local Disk Folder / '{file_name}'",
                before_state=f"File '{file_name}' does not exist in local target destination folder",
                expected_after_state=f"File '{file_name}' downloaded and saved to local destination folder",
            )

        if "gmail" in app.lower() or "mail" in app.lower():
            return ExpectedStateChange(
                target_system=app,
                entity_or_property="Desktop Window Focus & Active Message",
                before_state="Gmail window may be unfocused or in background",
                expected_after_state=f"Gmail window focused displaying replacement request for '{cust_name}'",
            )

        # Generic fallback
        return ExpectedStateChange(
            target_system=app,
            entity_or_property=f"{app} Interface State",
            before_state=f"{app} in idle state prior to step execution",
            expected_after_state=f"{step.action} completed in {app}",
        )

    def evaluate_preconditions(self, preconditions: List[str]) -> List[PreconditionCheck]:
        """Evaluate structural preconditions, explicitly distinguishing satisfied from unknown."""
        checks: List[PreconditionCheck] = []
        for cond in preconditions:
            # In Phase 7 shadow mode without live desktop automation, preconditions requiring
            # runtime environment checks must be marked as UNKNOWN rather than assumed satisfied.
            checks.append(
                PreconditionCheck(
                    condition=cond,
                    status=PreconditionStatus.UNKNOWN,
                    evaluation_reason="Requires active desktop environment inspection prior to execution; unverified in shadow simulation mode.",
                )
            )
        return checks

    def create_execution_plan(
        self,
        spec: CanonicalWorkflowSpec,
        runtime_inputs: Optional[Dict[str, str]] = None,
    ) -> ExecutionPlan:
        """Generate a deterministic ExecutionPlan from an approved CanonicalWorkflowSpec.

        Raises ValueError if the workflow is not approved.
        """
        # Strict Governance Requirement: Only approved workflows can generate execution plans!
        if spec.approval_state.state != ApprovalState.APPROVED:
            raise ValueError(
                f"Cannot create execution plan: Workflow specification '{spec.workflow_id}' is in state "
                f"'{spec.approval_state.state.value.upper()}'. It must be APPROVED by a human reviewer before planning execution."
            )

        # 1. Parameter Resolution
        resolved_params_list = self.resolve_parameters(spec, runtime_inputs)
        resolved_param_map = {
            p.semantic_name: p.runtime_value for p in resolved_params_list
        }
        # Also map by source_parameter for disambiguation
        for p in resolved_params_list:
            resolved_param_map[p.source_parameter] = p.runtime_value

        # 2. Plan Steps with Strategies and Expected State Changes
        planned_steps: List[PlannedStep] = []
        expected_effects: List[ExpectedStateChange] = []

        for idx, step in enumerate(spec.steps, 1):
            plan_step_id = f"plan-step-{idx}"
            strategy = self.select_strategy(
                app_name=step.application,
                action=step.action,
                risk_cat=step.risk.risk_category,
            )
            state_change = self.build_expected_state_change(step, resolved_param_map)
            expected_effects.append(state_change)

            # Map parameters relevant to this step
            step_params: Dict[str, Optional[str]] = {}
            for var_name in step.input_variables + step.output_variables:
                step_params[var_name] = resolved_param_map.get(var_name)

            is_external = step.risk.risk_category in (RiskCategory.EXTERNAL_CHANGE, RiskCategory.COMMUNICATION)

            planned_step = PlannedStep(
                plan_step_id=plan_step_id,
                source_canonical_step_id=step.canonical_step_id,
                source_semantic_step_id=step.source_semantic_step_id,
                source_dna_step_key=step.source_dna_step_key,
                application=step.application,
                action=step.action,
                description=step.description,
                resolved_parameters=step_params,
                execution_strategy=strategy,
                risk=step.risk,
                expected_result=f"Simulated execution of '{step.action}' in {step.application}",
                external_change=is_external,
                requires_confirmation=step.risk.requires_confirmation,
                evidence_reference=step.evidence_reference,
                state_change=state_change,
            )

            # Phase 10: Multi-strategy selection evaluation
            sel_res = self.strategy_selector.select_strategy(planned_step, spec)
            planned_step.execution_strategy.canonical_strategy = sel_res.selected_strategy.value if sel_res.selected_strategy else None
            planned_step.execution_strategy.selection_reason = sel_res.selection_reason
            planned_step.execution_strategy.available_strategies_considered = [c.strategy.value for c in sel_res.candidates_considered]
            planned_step.execution_strategy.rejected_strategies = sel_res.rejected_strategies
            planned_step.execution_strategy.rejection_reasons = sel_res.rejection_reasons
            planned_step.execution_strategy.fallback_used = sel_res.fallback_used
            planned_step.execution_strategy.executor_implemented = sel_res.is_executable
            planned_step.execution_strategy.blocked_reason = sel_res.blocked_reason
            planned_step.execution_strategy.policy_decision = sel_res.policy_decision

            planned_steps.append(planned_step)


        # 3. Preconditions
        precondition_checks = self.evaluate_preconditions(spec.preconditions)

        return ExecutionPlan(
            execution_plan_id=f"exec-plan-{uuid.uuid4().hex[:12]}",
            source_workflow_id=spec.workflow_id,
            workflow_version=spec.version,
            created_at=datetime.now(timezone.utc).isoformat(),
            source_approval_state=spec.approval_state.state.value,
            resolved_parameters=resolved_params_list,
            planned_steps=planned_steps,
            preconditions=precondition_checks,
            boundaries=spec.boundaries,
            risk_assessment=spec.risk_assessment,
            expected_effects=expected_effects,
            dry_run_status="not_started",
            dry_run_result=None,
        )

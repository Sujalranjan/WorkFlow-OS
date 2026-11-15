"""Execution Planner Service.

Converts an APPROVED CanonicalWorkflowSpec into a deterministic ExecutionPlan:
1. Validates that the workflow specification is formally approved.
2. Resolves runtime parameters without LLM invention.
3. Selects execution strategies with explainable rationale (API, App Integration, Accessibility, Browser, Fallback).
4. Derives expected state transitions (Before vs Expected After vs Actual Untouched).
5. Evaluates structural preconditions (Satisfied, Unsatisfied, Unknown).
6. Inherits deterministic risk classifications and confirmation requirements.
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
from app.models.strategy import ExecutionStrategyType
from app.services.action_catalog import CatalogAction, get_action, get_action_by_step_key
from app.services.strategy_selector import StrategySelector


def _catalog_param_name(source_field: str) -> Optional[str]:
    """'action.search_query' -> 'search_query' (bindings extracted from catalog actions)."""
    if source_field.startswith("action."):
        return source_field.split(".", 1)[1]
    return None


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
            return StepExecutionStrategy(
                strategy=ExecutionStrategy.API,
                reason="Customer lookup and record mutation executes through the WorkFlowOS Demo CRM REST API.",
                target_technology="CRM REST API / HTTP Client",
            )

        # 2. Email Services (Gmail, Google Mail)
        if any(gm in app_lower for gm in ["gmail", "google mail", "email"]):
            return StepExecutionStrategy(
                strategy=ExecutionStrategy.API,
                reason="Read-only email operations execute through the Google Gmail REST API.",
                target_technology="Google Gmail API (read-only)",
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

            catalog = get_action_by_step_key(b.associated_step_key)
            param_name = _catalog_param_name(b.source_field)
            catalog_param = catalog.parameter(param_name) if catalog and param_name else None
            if val is None and param_name:
                val = runtime_inputs.get(param_name)

            if val is not None and str(val).strip():
                status = ParameterResolutionStatus.RESOLVED
                runtime_val = str(val).strip()
            elif catalog_param is not None and len(set(b.observed_values)) > 1:
                # The value changed between observed runs, so a past sample would act on the
                # wrong record. Derive it from upstream step outputs, or require runtime input.
                if catalog_param.upstream_template:
                    status = ParameterResolutionStatus.FROM_UPSTREAM
                    runtime_val = catalog_param.upstream_template
                else:
                    status = ParameterResolutionStatus.UNRESOLVED
                    runtime_val = None
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
                    is_required=catalog_param.required if catalog_param else True,
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

    @staticmethod
    def _catalog_step_parameters(
        catalog: CatalogAction,
        step_key: str,
        spec: CanonicalWorkflowSpec,
        resolved: List[ResolvedParameter],
        runtime_inputs: Dict[str, str],
    ) -> Dict[str, Optional[str]]:
        """Bind each catalog parameter for one step: runtime input > resolved binding > upstream template."""
        by_binding = {
            (b.associated_step_key, _catalog_param_name(b.source_field)): r
            for b, r in zip(spec.variables, resolved)
        }
        params: Dict[str, Optional[str]] = {}
        for p in catalog.parameters:
            runtime = runtime_inputs.get(p.name)
            res = by_binding.get((step_key, p.name))
            if runtime is not None and str(runtime).strip():
                params[p.name] = str(runtime).strip()
            elif res is not None:
                params[p.name] = res.runtime_value
            elif p.upstream_template:
                params[p.name] = p.upstream_template
            elif p.required:
                params[p.name] = None
        return params

    def evaluate_preconditions(self, preconditions: List[str]) -> List[PreconditionCheck]:
        """Evaluate structural preconditions, explicitly distinguishing satisfied from unknown."""
        checks: List[PreconditionCheck] = []
        for cond in preconditions:
            # In shadow mode without live desktop automation, preconditions requiring
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
        excluded_steps: List[Dict[str, str]] = []
        has_catalog_steps = any(s.catalog_action for s in spec.steps)

        for step in spec.steps:
            catalog = get_action(step.catalog_action)
            if has_catalog_steps and catalog is None:
                # Observational context (e.g. window focus) next to executable actions: there is
                # nothing to perform, so it is recorded but not planned.
                excluded_steps.append(
                    {
                        "canonical_step_id": step.canonical_step_id,
                        "source_dna_step_key": step.source_dna_step_key,
                        "reason": "Observational step with no ActionCatalog match; not executed.",
                    }
                )
                continue

            plan_step_id = f"plan-step-{len(planned_steps) + 1}"
            step_params: Dict[str, Optional[str]] = {}
            if catalog:
                strategy = StepExecutionStrategy(
                    strategy=ExecutionStrategy.API,
                    reason=f"ActionCatalog '{catalog.action_id}' routes exactly to {catalog.executor_name}.",
                    target_technology=catalog.executor_name,
                )
                step_params = self._catalog_step_parameters(
                    catalog, step.source_dna_step_key, spec, resolved_params_list, runtime_inputs or {}
                )
            else:
                strategy = self.select_strategy(
                    app_name=step.application,
                    action=step.action,
                    risk_cat=step.risk.risk_category,
                )
                # Map parameters relevant to this step
                for var_name in step.input_variables + step.output_variables:
                    step_params[var_name] = resolved_param_map.get(var_name)

            state_change = self.build_expected_state_change(step, resolved_param_map)
            expected_effects.append(state_change)

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
                catalog_action=step.catalog_action,
            )

            # Multi-strategy selection evaluation
            sel_res = self.strategy_selector.select_strategy(planned_step, spec)
            if sel_res.is_executable and sel_res.selected_strategy:
                if sel_res.selected_strategy == ExecutionStrategyType.API_INTEGRATION:
                    planned_step.execution_strategy.strategy = ExecutionStrategy.API
                elif sel_res.selected_strategy == ExecutionStrategyType.CONTROLLED_LOCAL:
                    planned_step.execution_strategy.strategy = ExecutionStrategy.CONTROLLED_LOCAL
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
            excluded_steps=excluded_steps,
            dry_run_status="not_started",
            dry_run_result=None,
        )

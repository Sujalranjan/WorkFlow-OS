"""Deterministic Strategy Selector Service for WorkFlowOS (Phase 10).

Responsible for:
1. Inspecting step action, target, risk, and parameter requirements.
2. Querying registered executor capabilities from ExecutorRegistry.
3. Applying execution policy and risk restrictions (no bypass).
4. Evaluating deterministic fallback ordering.
5. Distinguishing IMPLEMENTED executors from ARCHITECTURALLY REPRESENTED executors.
6. Safely blocking unsupported steps with explainable reasons.

STRICT DETERMINISM GUARANTEE:
- ZERO LLM involvement in strategy selection.
- ZERO random selection.
- Completely reproducible candidate evaluation.
"""

import logging
from typing import Dict, List, Optional, Tuple

from app.models.canonical import ApprovalState, CanonicalWorkflowSpec, RiskCategory
from app.models.execution_plan import PlannedStep
from app.models.strategy import (
    ExecutionStrategyType,
    ExecutorCapability,
    StrategyCandidate,
    StrategySelectionResult,
)
from app.services.execution_policy import ExecutionPolicyEngine
from app.services.executors.registry import ExecutorRegistry

logger = logging.getLogger(__name__)


class StrategySelector:
    """Deterministic, risk-aware strategy selector for WorkFlowOS execution steps."""

    # Deterministic fallback chain order for general actions
    DEFAULT_FALLBACK_CHAIN: List[ExecutionStrategyType] = [
        ExecutionStrategyType.API_INTEGRATION,
        ExecutionStrategyType.APPLICATION_INTEGRATION,
        ExecutionStrategyType.ACCESSIBILITY_UI,
        ExecutionStrategyType.BROWSER_AUTOMATION,
        ExecutionStrategyType.UI_FALLBACK,
    ]

    def __init__(
        self,
        registry: Optional[ExecutorRegistry] = None,
        policy_engine: Optional[ExecutionPolicyEngine] = None,
    ) -> None:
        self.registry = registry or ExecutorRegistry()
        self.policy_engine = policy_engine or ExecutionPolicyEngine(registry=self.registry)

    def _determine_candidate_strategies(self, step: PlannedStep) -> List[ExecutionStrategyType]:
        """Determines the prioritized list of candidate strategies to evaluate for a step."""
        app_lower = step.application.lower().strip()
        act_lower = step.action.lower().strip().replace(" ", "_")

        # 1. Local Filesystem / Disk / Sandbox Actions
        # E.g. save_file, write_file, create_file, read_file, copy_file, generate_report, download_file
        local_keywords = ["file", "disk", "folder", "download", "report", "sandbox", "summary", "excel", "csv", "json"]
        is_local_target = any(k in app_lower for k in ["file system", "filesystem", "file", "folder", "sandbox", "local", "disk"])
        is_local_action = any(k in act_lower for k in ["file", "report", "summary", "download", "save", "write", "create_file", "read"])

        if is_local_target or (is_local_action and not any(ext in app_lower for ext in ["slack", "teams", "crm", "salesforce", "hubspot", "gmail"])):
            return [
                ExecutionStrategyType.CONTROLLED_LOCAL,
                ExecutionStrategyType.APPLICATION_INTEGRATION,
                ExecutionStrategyType.UI_FALLBACK,
            ]

        # 2. Team Communication & Messaging (Slack, Teams, Webhook, Notification)
        if any(comm in app_lower for comm in ["slack", "teams", "webhook", "chat", "email", "gmail"]):
            return [
                ExecutionStrategyType.API_INTEGRATION,
                ExecutionStrategyType.APPLICATION_INTEGRATION,
                ExecutionStrategyType.ACCESSIBILITY_UI,
                ExecutionStrategyType.BROWSER_AUTOMATION,
                ExecutionStrategyType.UI_FALLBACK,
            ]

        # 3. Enterprise Applications (CRM, ERP, Database, Salesforce, HubSpot)
        if any(crm in app_lower for crm in ["crm", "salesforce", "hubspot", "database", "erp"]):
            return [
                ExecutionStrategyType.API_INTEGRATION,
                ExecutionStrategyType.APPLICATION_INTEGRATION,
                ExecutionStrategyType.ACCESSIBILITY_UI,
                ExecutionStrategyType.BROWSER_AUTOMATION,
                ExecutionStrategyType.UI_FALLBACK,
            ]

        # 4. Web Browsers (Chrome, Firefox, Edge, Safari)
        if any(b in app_lower for b in ["chrome", "firefox", "edge", "safari", "browser", "web"]):
            return [
                ExecutionStrategyType.BROWSER_AUTOMATION,
                ExecutionStrategyType.ACCESSIBILITY_UI,
                ExecutionStrategyType.UI_FALLBACK,
            ]

        # 5. Default Desktop UI Fallback Chain
        return [
            ExecutionStrategyType.ACCESSIBILITY_UI,
            ExecutionStrategyType.UI_FALLBACK,
        ]

    def select_strategy(
        self,
        step: PlannedStep,
        spec: Optional[CanonicalWorkflowSpec] = None,
    ) -> StrategySelectionResult:
        """Deterministically evaluates and selects an execution strategy for a planned step.

        Strict Rules:
        1. Only IMPLEMENTED executors may be selected for execution.
        2. Execution policy and risk boundaries are strictly enforced.
        3. External changes / communications are blocked safely if no implemented executor exists.
        4. Completely reproducible candidate evaluation with full audit explainability.
        """
        candidates_to_eval = self._determine_candidate_strategies(step)
        candidates_considered: List[StrategyCandidate] = []
        rejected_strategies: List[str] = []
        rejection_reasons: Dict[str, str] = {}


        # 1. Spec Approval Policy Check (if spec is provided)
        if spec is not None and spec.approval_state.state != ApprovalState.APPROVED:
            reason = (
                f"Workflow '{spec.workflow_id}' is in state '{spec.approval_state.state.value}'. "
                f"Only 'approved' workflows can select an executable strategy."
            )
            return StrategySelectionResult(
                plan_step_id=step.plan_step_id,
                action=step.action,
                target=step.application,
                selected_strategy=None,
                selected_executor=None,
                is_executable=False,
                selection_reason=reason,
                fallback_used=False,
                blocked_reason="POLICY_NOT_APPROVED",
                policy_decision="BLOCKED",
                candidates_considered=[],
                rejected_strategies=[s.value for s in candidates_to_eval],
                rejection_reasons={s.value: reason for s in candidates_to_eval},
            )

        # 2. Evaluate candidates in deterministic priority order
        selected_cand: Optional[StrategyCandidate] = None
        selected_index: int = -1

        for idx, strat in enumerate(candidates_to_eval):
            executor = self.registry.get_executor_for_strategy(strat, step=step)
            if not executor:
                cand = StrategyCandidate(
                    strategy=strat,
                    executor_name="None",
                    is_implemented=False,
                    is_supported=False,
                    is_policy_allowed=False,
                    priority=100 + idx,
                    rejection_reason=f"No executor registered for strategy '{strat.value}'.",
                )
                candidates_considered.append(cand)
                rejected_strategies.append(strat.value)
                rejection_reasons[strat.value] = cand.rejection_reason
                continue

            cap = executor.capability
            is_implemented = cap.implemented
            rejection: Optional[str] = None
            is_supported = True
            is_policy_allowed = True

            # Check Implementation Status
            if not is_implemented:
                is_supported = False
                is_policy_allowed = False
                rejection = (
                    f"Strategy '{strat.value}' (executor '{executor.name}') is architecturally represented "
                    f"but NOT implemented."
                )

            # Check Action & Target Support
            if is_implemented and is_supported:
                act_norm = step.action.lower().strip().replace(" ", "_")
                action_matched = any(supp in act_norm or act_norm in supp for supp in cap.supported_actions)
                if not action_matched:
                    is_supported = False
                    rejection = f"Action '{step.action}' is not in executor '{executor.name}' supported actions."
                else:
                    app_norm = step.application.lower().strip().replace(" ", "_")
                    target_matched = any(
                        supp.lower() in app_norm or app_norm in supp.lower()
                        for supp in cap.supported_targets
                    )
                    if not target_matched:
                        is_supported = False
                        rejection = f"Target system '{step.application}' is not in executor '{executor.name}' supported targets."

            # Check Risk Restrictions & Execution Policy
            if is_implemented and is_supported:
                # External mutations policy: Controlled local executor cannot perform external mutations
                if step.risk.risk_category in (RiskCategory.EXTERNAL_CHANGE, RiskCategory.COMMUNICATION):
                    if not cap.requires_external_access:
                        is_policy_allowed = False
                        rejection = (
                            f"Policy violation: Step '{step.action}' has risk category '{step.risk.risk_category.value}', "
                            f"which requires external access, but executor '{executor.name}' is strictly local."
                        )

                # Risk level check
                risk_lvl = step.risk.risk_level.value.upper()
                if risk_lvl not in [r.upper() for r in cap.supported_risk_levels]:
                    is_policy_allowed = False
                    rejection = (
                        f"Step risk level '{risk_lvl}' exceeds executor '{executor.name}' "
                        f"supported levels: {cap.supported_risk_levels}."
                    )

            cand = StrategyCandidate(
                strategy=strat,
                executor_name=executor.name,
                is_implemented=is_implemented,
                is_supported=is_supported,
                is_policy_allowed=is_policy_allowed,
                priority=cap.priority,
                rejection_reason=rejection,
            )
            candidates_considered.append(cand)

            if is_implemented and is_supported and is_policy_allowed:
                if selected_cand is None:
                    selected_cand = cand
                    selected_index = idx
            else:
                rejected_strategies.append(strat.value)
                rejection_reasons[strat.value] = rejection or "Rejected during capability matching"

        # 3. Final Selection Decision
        if selected_cand is not None:
            fallback_used = (selected_index > 0)
            reason = (
                f"Selected implemented executor '{selected_cand.executor_name}' for strategy '{selected_cand.strategy.value}'. "
                f"Matched action '{step.action}' and verified sandbox guardrails."
            )
            if fallback_used:
                reason = f"Fallback selected: {reason}"

            return StrategySelectionResult(
                plan_step_id=step.plan_step_id,
                action=step.action,
                target=step.application,
                selected_strategy=selected_cand.strategy,
                selected_executor=selected_cand.executor_name,
                is_executable=True,
                selection_reason=reason,
                fallback_used=fallback_used,
                blocked_reason=None,
                policy_decision="ALLOWED",
                candidates_considered=candidates_considered,
                rejected_strategies=rejected_strategies,
                rejection_reasons=rejection_reasons,
            )

        # 4. Blocked Outcome (No implemented executor supports this action / policy rejected)
        blocked_code = "UNSUPPORTED_EXECUTION_STRATEGY"
        if any(not cand.is_policy_allowed and cand.is_supported and cand.is_implemented for cand in candidates_considered):
            blocked_code = "POLICY_REJECTED_RISK"
        elif any("Policy violation" in (cand.rejection_reason or "") for cand in candidates_considered):
            blocked_code = "POLICY_REJECTED_RISK"


        block_explanation = (
            f"No implemented executor supports action '{step.action}' on target '{step.application}' "
            f"with risk category '{step.risk.risk_category.value}'. "
            f"Evaluated strategies: {[c.strategy.value for c in candidates_considered]}."
        )

        return StrategySelectionResult(
            plan_step_id=step.plan_step_id,
            action=step.action,
            target=step.application,
            selected_strategy=None,
            selected_executor=None,
            is_executable=False,
            selection_reason=block_explanation,
            fallback_used=False,
            blocked_reason=blocked_code,
            policy_decision="BLOCKED",
            candidates_considered=candidates_considered,
            rejected_strategies=rejected_strategies,
            rejection_reasons=rejection_reasons,
        )

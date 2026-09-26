"""Dry Run Simulator Service (Phase 7).

Simulates workflow execution in shadow mode without performing ANY real actions:
1. Validates planned steps and parameters.
2. Simulates each planned step in order.
3. Checks for unresolved parameters and flags blocked steps.
4. Records prevented external mutations.
5. Produces a detailed simulation report labeled 'SIMULATED' (NOT 'SUCCESSFUL').
6. Formally guarantees ZERO real external or desktop actions performed.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional
import uuid

from app.models.canonical import RiskCategory
from app.models.execution_plan import (
    DryRunResult,
    DryRunStepResult,
    ExecutionPlan,
    ParameterResolutionStatus,
)


class DryRunSimulator:
    """Simulates workflow execution plans deterministically in shadow mode."""

    def simulate(self, plan: ExecutionPlan) -> DryRunResult:
        """Run a shadow dry-run simulation of the execution plan.

        STRICT SAFETY GUARANTEE:
        Performs ZERO real actions (no clicking, typing, network mutations, file writes,
        API calls, Playwright, Selenium, or shell execution).
        """
        step_simulations: List[DryRunStepResult] = []
        prevented_mutations = 0
        has_blocked_steps = False

        # Identify any completely unresolved parameters (by semantic_name and source_parameter)
        unresolved_params = set()
        for p in plan.resolved_parameters:
            if p.resolution_status == ParameterResolutionStatus.UNRESOLVED:
                unresolved_params.add(p.semantic_name)
                unresolved_params.add(p.source_parameter)

        for step in plan.planned_steps:
            # Phase 10: Multi-strategy analysis
            strat_info = step.execution_strategy
            is_implemented = strat_info.executor_implemented
            is_supported = is_implemented and (strat_info.blocked_reason is None)
            selected_strat_str = strat_info.canonical_strategy if is_supported else "NONE"
            decision = strat_info.policy_decision if is_supported else "BLOCKED"
            why_selected = strat_info.selection_reason or (
                f"Selected {selected_strat_str}" if is_supported else "No implemented executor supports this action."
            )

            # Check if this step requires an unresolved parameter
            step_unresolved = [
                param_name
                for param_name, val in step.resolved_parameters.items()
                if val is None and param_name in unresolved_params
            ]

            if step_unresolved:
                has_blocked_steps = True
                status_label = "BLOCKED_UNRESOLVED"
                decision = "BLOCKED"
                notes = (
                    f"Step cannot execute: required parameter(s) {step_unresolved} are unresolved. "
                    f"The system refused to invent a synthetic value."
                )
            else:
                status_label = "SIMULATED"
                if is_supported:
                    notes = (
                        f"Simulated successfully via {selected_strat_str}. "
                        f"Actual external action was NOT performed."
                    )
                else:
                    notes = (
                        f"Dry run shadow evaluation: Decision {decision}. {why_selected} "
                        f"Actual external action was NOT performed."
                    )

            # Count prevented external changes / communications
            if step.external_change or step.risk.risk_category in (RiskCategory.EXTERNAL_CHANGE, RiskCategory.COMMUNICATION):
                prevented_mutations += 1

            sim_step = DryRunStepResult(
                plan_step_id=step.plan_step_id,
                application=step.application,
                action=step.action,
                strategy=step.execution_strategy.strategy,
                simulation_status=status_label,
                risk_level=step.risk.risk_level.value,
                risk_category=step.risk.risk_category.value,
                external_mutation_prevented=step.external_change,
                expected_state_transition=(
                    f"Expected transition from '{step.state_change.before_state}' "
                    f"to '{step.state_change.expected_after_state}'. Real state untouched."
                ),
                selected_strategy=selected_strat_str,
                candidate_strategies=strat_info.available_strategies_considered,
                selection_reason=why_selected,
                fallback_used=strat_info.fallback_used,
                policy_decision=decision,
                is_executable=is_supported,
                simulated_output={
                    "simulated_target": step.application,
                    "simulated_action": step.action,
                    "parameters_used": step.resolved_parameters,
                    "strategy_planned": step.execution_strategy.strategy.value,
                    "candidate_strategies": strat_info.available_strategies_considered,
                    "selected_strategy": selected_strat_str,
                    "why_selected": why_selected,
                    "fallback_used": strat_info.fallback_used,
                    "risk": f"{step.risk.risk_level.value} / {step.risk.risk_category.value}",
                    "policy_decision": decision,
                    "expected_result": step.expected_result,
                    "real_action_executed": False,
                },
                notes=notes,
            )
            step_simulations.append(sim_step)


        overall_status = "SIMULATION_BLOCKED" if (has_blocked_steps or len(unresolved_params) > 0) else "SIMULATED"
        summary = (
            f"Dry run shadow simulation completed with status '{overall_status}'. "
            f"Evaluated {len(step_simulations)} step(s). "
            f"Prevented {prevented_mutations} external mutation(s). "
            f"Real actions performed: 0."
        )

        return DryRunResult(
            dry_run_id=f"dry-run-{uuid.uuid4().hex[:12]}",
            simulated_at=datetime.now(timezone.utc).isoformat(),
            overall_simulation_status=overall_status,
            step_simulations=step_simulations,
            precondition_checks=list(plan.preconditions),
            real_actions_performed=0,  # ALWAYS 0
            external_mutations_prevented=prevented_mutations,
            summary=summary,
        )

"""Executor Registry for WorkFlowOS (Phase 8 & 10).

Decouples the execution engine from concrete executor implementations.
Allows discovery and lookup of registered executors by strategy, action, and capabilities.
Supports capability matching and clearly distinguishes implemented from represented executors.
"""

from typing import Any, Dict, List, Optional, Union
from app.models.execution_plan import ExecutionStrategy, PlannedStep
from app.models.strategy import ExecutionStrategyType, ExecutorCapability
from app.services.executors.base import BaseExecutor
from app.services.executors.controlled_local import ControlledLocalExecutor
from app.services.executors.crm_executor import CrmApiExecutor
from app.services.executors.gmail_executor import GmailApiExecutor
from app.services.executors.slack_executor import SlackApiExecutor
from app.services.executors.unimplemented import (
    AccessibilityUiExecutor,
    ApiIntegrationExecutor,
    ApplicationIntegrationExecutor,
    BrowserAutomationExecutor,
    UiFallbackExecutor,
)


class ExecutorRegistry:
    """Registry maintaining available executors and their capability metadata."""

    def __init__(self) -> None:
        self._executors: Dict[str, BaseExecutor] = {}
        # 1. Register Phase 8 implemented executor (local filesystem sandbox)
        self.register(ControlledLocalExecutor())

        # 2. Register Phase 12 & 15A implemented external executor (Gmail API)
        self.register(GmailApiExecutor())

        # 3. Register Phase 15B implemented external executor (CRM API)
        self.register(CrmApiExecutor())

        # 4. Register Phase 15D implemented external executor (Slack API)
        self.register(SlackApiExecutor())

        # 5. Register Phase 10 architecturally represented (unimplemented) executors
        self.register(ApiIntegrationExecutor())
        self.register(ApplicationIntegrationExecutor())
        self.register(AccessibilityUiExecutor())
        self.register(BrowserAutomationExecutor())
        self.register(UiFallbackExecutor())

    def register(self, executor: BaseExecutor) -> None:
        """Registers an executor instance."""
        self._executors[executor.name] = executor

    def get_executor_for_step(self, step: PlannedStep) -> Optional[BaseExecutor]:
        """Finds an IMPLEMENTED executor that supports the step's execution strategy and action.

        Strictly excludes executors that are represented but not implemented.
        """
        strat_val = step.execution_strategy.strategy
        return self.get_executor_for_strategy(strat_val, implemented_only=True, step=step)

    def get_capable_executors(
        self,
        step: PlannedStep,
        implemented_only: bool = True,
    ) -> List[BaseExecutor]:
        """Finds all executors whose capabilities match the step's action, target, and risk.

        Args:
            step: The planned step to inspect.
            implemented_only: If True, filters out represented but unimplemented executors.

        Returns:
            List[BaseExecutor]: Compatible executors ordered by priority.
        """
        action_norm = step.action.lower().strip().replace(" ", "_")
        app_norm = step.application.lower().strip().replace(" ", "_")
        risk_level = step.risk.risk_level.value.upper()

        matching: List[BaseExecutor] = []

        for executor in self._executors.values():
            cap = executor.capability
            if implemented_only and not cap.implemented:
                continue

            # 1. Action compatibility
            action_match = False
            for supp_act in cap.supported_actions:
                if supp_act in action_norm or action_norm in supp_act:
                    action_match = True
                    break

            # 2. Target compatibility
            target_match = False
            for supp_target in cap.supported_targets:
                if supp_target in app_norm or app_norm in supp_target:
                    target_match = True
                    break

            # 3. Risk level compatibility
            risk_match = risk_level in [r.upper() for r in cap.supported_risk_levels]

            # If action or target matches and risk is compatible, candidate is capable
            if (action_match or target_match) and risk_match:
                matching.append(executor)

        # Sort matching executors by priority (lower number = higher priority)
        matching.sort(key=lambda e: e.capability.priority)
        return matching

    def get_executor_for_strategy(
        self,
        strategy: Union[ExecutionStrategy, ExecutionStrategyType, str],
        implemented_only: bool = False,
        step: Optional[PlannedStep] = None,
    ) -> Optional[BaseExecutor]:
        """Retrieves executor by its strategy type, optionally matching specific step capabilities."""
        strat_str = str(strategy.value if hasattr(strategy, "value") else strategy).upper()
        candidates: List[BaseExecutor] = [
            e for e in self._executors.values() if e.capability.strategy_type.value == strat_str
        ]
        if not candidates:
            return None

        # If a step is provided, check if any candidate specifically matches action or target
        if step is not None:
            action_norm = step.action.lower().strip().replace(" ", "_")
            app_norm = step.application.lower().strip().replace(" ", "_")
            for executor in candidates:
                if implemented_only and not executor.capability.implemented:
                    continue
                cap = executor.capability
                act_match = any(supp in action_norm or action_norm in supp for supp in cap.supported_actions)
                tgt_match = any(supp.lower() in app_norm or app_norm in supp.lower() for supp in cap.supported_targets)
                if act_match or tgt_match:
                    return executor
            # If a step was provided but did NOT match specialized executor (like GmailApiExecutor):
            # If implemented_only was requested, return None
            if implemented_only:
                return None
            # Return generic unspecialized executor if available
            for e in candidates:
                if not e.capability.supported_targets or "*" in e.capability.supported_targets:
                    return e
            return candidates[0]

        # If no step provided:
        # Prefer the generic/unimplemented executor for the strategy category (e.g. ApiIntegrationExecutor)
        for e in candidates:
            if not e.capability.implemented or e.name == "ApiIntegrationExecutor":
                return e

        # Otherwise return first candidate
        return candidates[0]

    def get_all_capabilities(self) -> List[ExecutorCapability]:
        """Returns capabilities of all registered executors."""
        return [executor.capability for executor in self._executors.values()]

    def get_by_name(self, name: str) -> Optional[BaseExecutor]:
        """Retrieves executor by its unique name."""
        return self._executors.get(name)

    def list_executors(self) -> List[str]:
        """Lists names of all registered executors."""
        return list(self._executors.keys())

    def list_implemented_executors(self) -> List[str]:
        """Lists names of only currently implemented executors."""
        return [e.name for e in self._executors.values() if e.capability.implemented]

    def get_implemented_executors(self) -> List[str]:
        """Alias for list_implemented_executors."""
        return self.list_implemented_executors()


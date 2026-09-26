"""Architecturally Represented (Unimplemented) Executors for WorkFlowOS (Phase 10).

Phase 10 explicitly defines the canonical multi-strategy execution architecture,
distinguishing between SUPPORTED/IMPLEMENTED executors and KNOWN/REPRESENTED executors.

The following executors represent future integration boundaries:
- ApiIntegrationExecutor (API_INTEGRATION)
- ApplicationIntegrationExecutor (APPLICATION_INTEGRATION)
- AccessibilityUiExecutor (ACCESSIBILITY_UI)
- BrowserAutomationExecutor (BROWSER_AUTOMATION)
- UiFallbackExecutor (UI_FALLBACK)

STRICT SAFETY GUARANTEE:
All executors here declare `implemented=False`.
They NEVER execute external mutations, never make HTTP/API calls, never spawn browsers,
and never control real mouse/keyboard automation.
"""

from typing import Any, List, Tuple
from app.models.execution import ExecutionContext, ExecutionStepResult, ExecutionStepStatus
from app.models.execution_plan import ExecutionStrategy, PlannedStep
from app.models.strategy import ExecutionStrategyType, ExecutorCapability
from app.services.executors.base import BaseExecutor


class RepresentedUnimplementedExecutor(BaseExecutor):
    """Base class for architecturally represented but non-executable strategies."""

    def __init__(
        self,
        name: str,
        strategy_type: ExecutionStrategyType,
        supported_actions: List[str],
        supported_targets: List[str],
        supported_risk_levels: List[str],
        priority: int,
        requires_external_access: bool,
        description: str,
    ) -> None:
        self._name = name
        self._capability = ExecutorCapability(
            strategy_type=strategy_type,
            executor_name=name,
            supported_actions=supported_actions,
            supported_targets=supported_targets,
            supported_risk_levels=supported_risk_levels,
            implemented=False,  # STRICT: Never true in Phase 10
            requires_external_access=requires_external_access,
            supports_verification=False,
            priority=priority,
            description=description,
        )

    @property
    def name(self) -> str:
        return self._name

    @property
    def capability(self) -> ExecutorCapability:
        return self._capability

    def supports(self, strategy: Any) -> bool:
        strat_str = str(strategy.value if hasattr(strategy, "value") else strategy).upper()
        return strat_str == self._capability.strategy_type.value

    def validate(self, step: PlannedStep, context: ExecutionContext) -> Tuple[bool, List[str]]:
        return (
            False,
            [
                f"Executor '{self.name}' for strategy '{self._capability.strategy_type.value}' "
                f"is architecturally represented but NOT implemented in Phase 10."
            ],
        )

    def execute(self, step: PlannedStep, context: ExecutionContext) -> ExecutionStepResult:
        raise NotImplementedError(
            f"Executor '{self.name}' cannot execute step '{step.action}': "
            f"Strategy '{self._capability.strategy_type.value}' is NOT implemented."
        )


class ApiIntegrationExecutor(RepresentedUnimplementedExecutor):
    """Direct API / webhook strategy (e.g. Slack Webhook, REST endpoints). Represented but not implemented."""

    def __init__(self) -> None:
        super().__init__(
            name="ApiIntegrationExecutor",
            strategy_type=ExecutionStrategyType.API_INTEGRATION,
            supported_actions=["send_slack_notification", "post_webhook", "api_call", "send_notification"],
            supported_targets=["slack", "teams", "webhook", "api", "rest"],
            supported_risk_levels=["LOW", "MEDIUM", "HIGH"],
            priority=1,
            requires_external_access=True,
            description="Direct API integration (e.g. Slack Webhook, REST APIs). Architectural stub.",
        )


class ApplicationIntegrationExecutor(RepresentedUnimplementedExecutor):
    """Enterprise application connector strategy (e.g. CRM, ERP). Represented but not implemented."""

    def __init__(self) -> None:
        super().__init__(
            name="ApplicationIntegrationExecutor",
            strategy_type=ExecutionStrategyType.APPLICATION_INTEGRATION,
            supported_actions=["update_crm_record", "create_lead", "modify_record", "sync_database"],
            supported_targets=["crm", "salesforce", "hubspot", "erp", "database"],
            supported_risk_levels=["LOW", "MEDIUM", "HIGH"],
            priority=2,
            requires_external_access=True,
            description="Enterprise application connector (e.g. Salesforce, HubSpot). Architectural stub.",
        )


class AccessibilityUiExecutor(RepresentedUnimplementedExecutor):
    """OS Accessibility tree / UIA automation strategy. Represented but not implemented."""

    def __init__(self) -> None:
        super().__init__(
            name="AccessibilityUiExecutor",
            strategy_type=ExecutionStrategyType.ACCESSIBILITY_UI,
            supported_actions=["inspect_window", "read_control", "focus_window", "activate_window"],
            supported_targets=["desktop", "window", "native_app"],
            supported_risk_levels=["LOW"],
            priority=3,
            requires_external_access=False,
            description="OS semantic accessibility tree automation (Windows UIA). Architectural stub.",
        )


class BrowserAutomationExecutor(RepresentedUnimplementedExecutor):
    """Web browser automation strategy (DOM / CDP). Represented but not implemented."""

    def __init__(self) -> None:
        super().__init__(
            name="BrowserAutomationExecutor",
            strategy_type=ExecutionStrategyType.BROWSER_AUTOMATION,
            supported_actions=["navigate_page", "click_element", "fill_form", "read_dom"],
            supported_targets=["chrome", "firefox", "edge", "browser", "web"],
            supported_risk_levels=["LOW", "MEDIUM"],
            priority=4,
            requires_external_access=True,
            description="Web browser DOM automation. Architectural stub (no Playwright/Selenium in Phase 10).",
        )


class UiFallbackExecutor(RepresentedUnimplementedExecutor):
    """Computer-vision or coordinate-based UI fallback strategy. Represented but not implemented."""

    def __init__(self) -> None:
        super().__init__(
            name="UiFallbackExecutor",
            strategy_type=ExecutionStrategyType.UI_FALLBACK,
            supported_actions=["click_coordinate", "type_keys", "visual_anchor"],
            supported_targets=["desktop", "screen"],
            supported_risk_levels=["LOW"],
            priority=5,
            requires_external_access=False,
            description="Computer-vision / coordinate-based UI fallback. Architectural stub (no PyAutoGUI in Phase 10).",
        )

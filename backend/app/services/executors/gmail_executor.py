"""Gmail API Executor (Phase 12).

Implements the first real external execution integration in WorkFlowOS.
Strictly supports ONE read-only operation:
    search_email

Declares:
- strategy_type: API_INTEGRATION
- implemented: True
- requires_external_access: True
- supports_verification: True
- priority: 1

SECURITY BOUNDARIES:
- Read-only search: zero state mutations on Gmail.
- Never falls back to ControlledLocalExecutor.
- Fails closed with standardized codes (INTEGRATION_UNAVAILABLE, AUTHENTICATION_REQUIRED, INVALID_PARAMETER).
- Never leaks or logs OAuth tokens or client secrets.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional, Tuple

from app.models.canonical import RiskLevel
from app.models.execution import (
    ExecutionContext,
    ExecutionStepResult,
    ExecutionStepStatus,
)
from app.models.execution_plan import ExecutionStrategy, PlannedStep
from app.models.strategy import ExecutionStrategyType, ExecutorCapability
from app.services.executors.base import BaseExecutor
from app.services.gmail_client import (
    GmailApiClient,
    GmailAuthenticationError,
    GmailConfigurationError,
)

logger = logging.getLogger(__name__)


class GmailApiExecutor(BaseExecutor):
    """Executor executing verified read-only search operations against Google Gmail API."""

    def __init__(self, client: Optional[GmailApiClient] = None) -> None:
        self.client = client or GmailApiClient()

    @property
    def name(self) -> str:
        return "GmailApiExecutor"

    @property
    def strategy(self) -> ExecutionStrategy:
        return ExecutionStrategy.API

    @property
    def capability(self) -> ExecutorCapability:
        return ExecutorCapability(
            executor_name=self.name,
            strategy_type=ExecutionStrategyType.API_INTEGRATION,
            supported_actions=["search_email"],
            supported_targets=["Gmail", "gmail", "Google Mail"],
            supported_risk_levels=[RiskLevel.LOW.value, RiskLevel.MEDIUM.value],
            implemented=True,
            requires_external_access=True,
            supports_verification=True,
            priority=1,
            description="Gmail API executor for deterministic read-only search operations.",
        )

    def supports(self, strategy: Any) -> bool:
        strat_str = str(strategy.value if hasattr(strategy, "value") else strategy).upper()
        return strat_str in ("API", "API_INTEGRATION", ExecutionStrategyType.API_INTEGRATION.value)

    def validate(self, step: PlannedStep, context: ExecutionContext) -> Tuple[bool, List[str]]:
        """Strictly validates safety guardrails on the planned step before Gmail execution."""
        errors: List[str] = []

        # 1. Action check
        act_norm = step.action.lower().strip().replace(" ", "_")
        if act_norm != "search_email":
            errors.append(f"GmailApiExecutor only supports 'search_email' action. Given: '{step.action}'")

        # 2. Target check
        app_norm = step.application.lower().strip()
        if not any(t in app_norm for t in ["gmail", "google mail"]):
            errors.append(f"GmailApiExecutor only targets Gmail. Given application: '{step.application}'")

        # 3. Parameter check
        resolved_params = context.resolved_parameters or {}
        query = (
            resolved_params.get("query")
            or resolved_params.get("search_query")
            or resolved_params.get("q")
        )
        if not query or not str(query).strip():
            errors.append("Missing required 'query' parameter for Gmail search")

        return len(errors) == 0, errors

    def execute(self, step: PlannedStep, context: ExecutionContext) -> ExecutionStepResult:
        """Executes a single read-only search_email operation via the Gmail API."""
        start_time = datetime.now(timezone.utc).isoformat()
        act_norm = step.action.lower().strip().replace(" ", "_")

        # 1. Action Validation
        if act_norm != "search_email":
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.BLOCKED,
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                blocked_reason="UNSUPPORTED_ACTION",
                error=f"GmailApiExecutor only supports 'search_email'. Action '{step.action}' is not supported.",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )

        # 2. Extract and Validate Query Parameter
        resolved_params = context.resolved_parameters or {}
        query = (
            resolved_params.get("query")
            or resolved_params.get("search_query")
            or resolved_params.get("q")
        )

        if not query or not str(query).strip():
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.BLOCKED,
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                blocked_reason="INVALID_PARAMETER",
                error="Required parameter 'query' is missing or empty for search_email operation.",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )

        query_str = str(query).strip()

        # 3. Check Configuration & Authentication (Fail-Closed)
        if not self.client.is_configured():
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.BLOCKED,
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                blocked_reason="INTEGRATION_UNAVAILABLE",
                error="Gmail API integration is not configured. Provide GMAIL_CREDENTIALS_PATH or GMAIL_TOKEN_PATH.",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )

        if not self.client.is_authenticated():
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.BLOCKED,
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                blocked_reason="AUTHENTICATION_REQUIRED",
                error="Gmail OAuth 2.0 authorization is required. Valid credentials or token not found.",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )

        # 4. Perform Live Search Operation
        try:
            max_results = int(resolved_params.get("max_results", 10))
            search_result = self.client.search_messages(query=query_str, max_results=max_results)

            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.SUCCESS,
                parameters_used={"query": query_str, "max_results": max_results},
                output={
                    "query": query_str,
                    "total_found": search_result.total_found,
                    "messages": [m.model_dump() for m in search_result.messages],
                    "searched_at": search_result.searched_at,
                    "operation": "search_email",
                    "status": "COMPLETED",
                },
                affected_resources=[],  # Strictly read-only: no resources mutated
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                selection_reason="Executed read-only search via Gmail API",
                fallback_used=False,
                policy_decision="ALLOWED",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )

        except GmailConfigurationError as e:
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.BLOCKED,
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                blocked_reason="INTEGRATION_UNAVAILABLE",
                error=f"Gmail configuration error: {str(e)}",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )
        except GmailAuthenticationError as e:
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.BLOCKED,
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                blocked_reason="AUTHENTICATION_REQUIRED",
                error=f"Gmail authentication required: {str(e)}",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as e:
            logger.error("GmailApiExecutor execution failed: %s", str(e))
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.FAILED,
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                error=f"Gmail API execution error: {str(e)}",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )

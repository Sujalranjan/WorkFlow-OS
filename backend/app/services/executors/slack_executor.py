"""Slack API Executor.

Executes approved team notifications via the official Slack Web API (chat.postMessage).
Integrates with the WorkFlowOS Execution Policy and Verification Engine.

SECURITY & GOVERNANCE:
- Strategy: API_INTEGRATION
- Implemented: True
- Requires external access: True
- Supports verification: True
- Risk: COMMUNICATION (requires explicit human approval before execution)
- Dry-run: Guarantees 0 external API calls and 0 real actions.
- Audit records: Never include bot tokens or raw Authorization headers.
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from app.models.canonical import RiskLevel
from app.models.execution import (
    ExecutionContext,
    ExecutionMode,
    ExecutionStepResult,
    ExecutionStepStatus,
)
from app.models.execution_plan import ExecutionStrategy, PlannedStep
from app.models.strategy import ExecutionStrategyType, ExecutorCapability
from app.services.executors.base import BaseExecutor
from app.services.slack_client import (
    SlackApiClient,
    SlackApiError,
    SlackClientError,
    SlackConfigurationError,
    SlackConnectionError,
    SlackValidationError,
)

logger = logging.getLogger(__name__)



def _default_message(params: dict) -> str:
    """Status message built from what this run actually did."""
    customer = params.get("customer_name") or params.get("customer_id") or params.get("customer_email") or "the customer"
    lines = [f"Request processed for {customer}"]
    if params.get("email_subject"):
        lines.append(f"Email: {params['email_subject']}")
    if params.get("customer_status"):
        lines.append(f"CRM status: {params['customer_status']}")
    if params.get("filename"):
        lines.append(f"Attachment: {params['filename']}")
    if params.get("saved_file_name"):
        lines.append(f"Saved to the shared folder as: {params['saved_file_name']}")
    return "\n".join(lines)


def _reply_message(params: dict) -> str:
    """Follow-up for the thread: what happened after the first message (default reply text)."""
    lines = ["Update: the run finished."]
    if params.get("customer_status"):
        lines.append(f"CRM status: {params['customer_status']}")
    if params.get("hubspot_updated"):
        lines.append("HubSpot contact updated.")
    if params.get("note_id"):
        lines.append("Note added in HubSpot.")
    if params.get("saved_file_name"):
        lines.append(f"Saved to the shared folder as: {params['saved_file_name']}")
    return "\n".join(lines)


def _unresolved(value: Any) -> bool:
    text = str(value or "").strip()
    return not text or (text.startswith("{") and text.endswith("}"))


ACTIONS = ("send_notification", "reply_in_thread")


class SlackApiExecutor(BaseExecutor):
    """Executor executing verified Slack team notifications via SlackApiClient."""

    def __init__(self, client: Optional[SlackApiClient] = None) -> None:
        self.client = client or SlackApiClient()

    @property
    def name(self) -> str:
        return "SlackApiExecutor"

    @property
    def strategy(self) -> ExecutionStrategy:
        return ExecutionStrategy.API

    @property
    def capability(self) -> ExecutorCapability:
        return ExecutorCapability(
            executor_name=self.name,
            strategy_type=ExecutionStrategyType.API_INTEGRATION,
            supported_actions=list(ACTIONS),
            supported_targets=["Slack", "slack", "Slack API", "Slack Web API"],
            supported_risk_levels=[RiskLevel.LOW.value, RiskLevel.MEDIUM.value],
            implemented=True,
            requires_external_access=True,
            supports_verification=True,
            priority=1,
            description="Slack API executor for team notifications via official Web API (chat.postMessage).",
        )

    def supports(self, strategy: Any) -> bool:
        strat_str = str(strategy.value if hasattr(strategy, "value") else strategy).upper()
        return strat_str in (
            "API",
            "API_INTEGRATION",
            "APPLICATION_INTEGRATION",
            ExecutionStrategyType.API_INTEGRATION.value,
        )

    def validate(self, step: PlannedStep, context: ExecutionContext) -> Tuple[bool, List[str]]:
        errors: List[str] = []
        act_norm = step.action.lower().strip().replace(" ", "_")

        if act_norm not in ACTIONS:
            errors.append(f"SlackApiExecutor does not support action '{step.action}'. Supported: {list(ACTIONS)}")
            return False, errors

        merged = dict(context.resolved_parameters or {})
        for k, v in (step.resolved_parameters or {}).items():
            if v is not None:
                merged[k] = v
        params = merged
        if act_norm == "reply_in_thread":
            # The default reply always has text; what it needs is a message of this run to reply under.
            if not context.dry_run and _unresolved(params.get("thread_ts")) and _unresolved(params.get("slack_ts")):
                errors.append("No Slack message was posted earlier in this run to reply under.")
            return (len(errors) == 0, errors)
        msg = params.get("message") or params.get("text") or params.get("content")
        # Without an explicit message, the default one describes what this run did; it needs something to say.
        has_context_entity = any(
            params.get(k)
            for k in ("customer_id", "customer_name", "customer", "customer_email", "email_subject", "filename", "saved_file_name")
        )
        if not msg and not context.dry_run and not has_context_entity:
            errors.append("Required parameter 'message' or 'text' is missing for send_notification.")

        return (len(errors) == 0, errors)

    def execute(self, step: PlannedStep, context: ExecutionContext) -> ExecutionStepResult:
        start_time = datetime.now(timezone.utc).isoformat()
        act_norm = step.action.lower().strip().replace(" ", "_")

        # 1. Validation
        is_valid, validation_errors = self.validate(step, context)
        if not is_valid:
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.BLOCKED,
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                blocked_reason="VALIDATION_FAILED",
                error="; ".join(validation_errors),
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )

        resolved_params = dict(context.resolved_parameters or {})
        for k, v in (step.resolved_parameters or {}).items():
            if v is not None:
                resolved_params[k] = v

        # The team's configured channel wins over a channel id copied from recorded sessions:
        # a recording (or sample data) can name a channel this bot cannot post to.
        is_reply = act_norm == "reply_in_thread"
        thread_ts = None
        if is_reply:
            # Reply under this run's own message, in that message's channel (never the default one).
            thread_ts = resolved_params.get("thread_ts")
            if _unresolved(thread_ts):
                thread_ts = resolved_params.get("slack_ts")
            thread_ts = None if _unresolved(thread_ts) else str(thread_ts)
            channel_param = resolved_params.get("slack_channel")
            explicit = resolved_params.get("reply_message")
            message_text = explicit if not _unresolved(explicit) else _reply_message(resolved_params)
            if not context.dry_run and not (thread_ts and channel_param):
                return ExecutionStepResult(
                    planned_step_id=step.plan_step_id,
                    action_name=step.action,
                    target_application=step.application,
                    strategy=self.strategy,
                    executor_name=self.name,
                    status=ExecutionStepStatus.BLOCKED,
                    selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                    blocked_reason="INVALID_PARAMETER",
                    error="No Slack message was posted earlier in this run to reply under.",
                    start_time=start_time,
                    end_time=datetime.now(timezone.utc).isoformat(),
                )
        else:
            channel_param = (
                getattr(self.client, "default_channel_id", None)
                or resolved_params.get("channel")
                or resolved_params.get("channel_id")
            )
            message_text = (
                resolved_params.get("message")
                or resolved_params.get("text")
                or resolved_params.get("content")
                or _default_message(resolved_params)
            )
        operation = "reply_in_thread" if is_reply else "send_notification"

        # 2. DRY RUN MODE: Guarantee 0 external API calls and 0 real actions
        is_dry_run = context.dry_run or (context.execution_mode == ExecutionMode.DRY_RUN)
        if is_dry_run:
            target_channel = channel_param or self.client.default_channel_id or "C-SIMULATED-CHANNEL"
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.SUCCESS,
                parameters_used={"channel": target_channel, "message": message_text},
                output={
                    "operation": operation,
                    "target": "Slack",
                    "channel": target_channel,
                    "thread_ts": thread_ts,
                    "message_preview": message_text,
                    "status": "SIMULATED",
                    "external_api_calls": 0,
                    "real_actions": 0,
                    "execution_strategy": "SIMULATED_LOCAL",
                },
                affected_resources=[],
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                selection_reason="Simulated team notification via Slack API (dry run: 0 external API calls)",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )

        # 3. REAL LIVE EXECUTION
        try:
            res = self.client.send_notification(
                channel=channel_param,
                text=str(message_text),
                blocks=resolved_params.get("blocks"),
                metadata=resolved_params.get("metadata"),
                thread_ts=thread_ts,
            )

            # Compute SHA-256 over message output
            msg_fingerprint = f"{res.channel}:{res.ts}:{message_text}"
            sha256_hash = hashlib.sha256(msg_fingerprint.encode("utf-8")).hexdigest()

            output = {
                "operation": operation,
                "channel": res.channel,
                "ts": res.ts,
                "thread_ts": thread_ts,
                "sha256": sha256_hash,
                "status": "COMPLETED",
            }

            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.SUCCESS,
                parameters_used={"channel": res.channel, "message": message_text},
                output=output,
                affected_resources=[f"slack:channel:{res.channel}:ts:{res.ts}"],
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                selection_reason=(
                    f"Reply posted in the thread of {thread_ts} in channel '{res.channel}' (ts: {res.ts})"
                    if is_reply
                    else f"Notification delivered to Slack channel '{res.channel}' (ts: {res.ts})"
                ),
                fallback_used=False,
                policy_decision="ALLOWED",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )

        except SlackConfigurationError as e:
            logger.error("Slack execution failed: missing configuration: %s", str(e))
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.FAILED,
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                error=f"Slack configuration error: {str(e)}",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )

        except SlackValidationError as e:
            logger.error("Slack execution failed: validation error: %s", str(e))
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.BLOCKED,
                blocked_reason="INVALID_PARAMETER",
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                error=f"Slack validation error: {str(e)}",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )

        except SlackApiError as e:
            logger.error("Slack execution failed: Slack API error '%s': %s", e.error_code, str(e))
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.FAILED,
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                error=f"Slack API error: {e.error_code}",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )

        except SlackConnectionError as e:
            logger.error("Slack execution connection failed: %s", str(e))
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.FAILED,
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                error=f"Slack connection failed: {str(e)}",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )

        except Exception as e:
            # General fallback ensuring no credential leak
            logger.error("SlackApiExecutor unexpected error: %s", type(e).__name__)
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.FAILED,
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                error=f"Slack API notification error: {type(e).__name__}",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )

"""gmail.add_label: label the email this run processed (opt-in; see services/gmail_labels.py).

The message comes from this run's Gmail search (`{message_id}`), never from a recording. The label
is the user label chosen when the routine was recorded (or given at run time). A missing opt-in,
permission or label is BLOCKED before anything changes; a dry run makes no Gmail calls.
"""

from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple

from app.models.canonical import RiskLevel
from app.models.execution import ExecutionContext, ExecutionStepResult, ExecutionStepStatus
from app.models.execution_plan import ExecutionStrategy, PlannedStep
from app.models.strategy import ExecutionStrategyType, ExecutorCapability
from app.services.executors.base import BaseExecutor
from app.services.gmail_labels import GmailLabelError, GmailLabeler

ACTIONS = ("add_label",)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _unresolved(value: Any) -> bool:
    text = str(value or "").strip()
    return not text or (text.startswith("{") and text.endswith("}"))


class GmailLabelExecutor(BaseExecutor):
    def __init__(self, labeler: Optional[GmailLabeler] = None) -> None:
        self.labeler = labeler or GmailLabeler()

    @property
    def name(self) -> str:
        return "GmailLabelExecutor"

    @property
    def strategy(self) -> ExecutionStrategy:
        return ExecutionStrategy.API

    @property
    def capability(self) -> ExecutorCapability:
        return ExecutorCapability(
            executor_name=self.name,
            strategy_type=ExecutionStrategyType.API_INTEGRATION,
            supported_actions=list(ACTIONS),
            supported_targets=["Gmail"],
            supported_risk_levels=[RiskLevel.LOW.value, RiskLevel.MEDIUM.value],
            implemented=True,
            requires_external_access=True,
            supports_verification=True,
            priority=1,
            description="Adds a user label to the processed email (opt-in gmail.modify; adds only, never removes).",
        )

    def supports(self, strategy: Any) -> bool:
        value = str(strategy.value if hasattr(strategy, "value") else strategy).upper()
        return value in ("API", ExecutionStrategyType.API_INTEGRATION.value)

    def validate(self, step: PlannedStep, context: ExecutionContext) -> Tuple[bool, List[str]]:
        if step.action not in ACTIONS:
            return False, [f"GmailLabelExecutor does not support '{step.action}'."]
        return True, []

    def _result(self, step: PlannedStep, start: str, status: ExecutionStepStatus, **fields) -> ExecutionStepResult:
        return ExecutionStepResult(
            planned_step_id=step.plan_step_id,
            action_name=step.action,
            target_application=step.application,
            strategy=self.strategy,
            executor_name=self.name,
            status=status,
            selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
            policy_decision="BLOCKED" if status == ExecutionStepStatus.BLOCKED else "ALLOWED",
            start_time=start,
            end_time=_now(),
            **fields,
        )

    def _blocked(self, step, start, reason: str, error: str) -> ExecutionStepResult:
        return self._result(step, start, ExecutionStepStatus.BLOCKED, blocked_reason=reason, error=error)

    def execute(self, step: PlannedStep, context: ExecutionContext) -> ExecutionStepResult:
        start = _now()
        if step.action not in ACTIONS:
            return self._blocked(step, start, "UNSUPPORTED_ACTION", f"Gmail labeling cannot '{step.action}'.")
        # A step value still holding its template ('{message_id}') never hides the value this run produced.
        params = {
            **(context.resolved_parameters or {}),
            **{k: v for k, v in (step.resolved_parameters or {}).items() if not _unresolved(v)},
        }
        message_id = params.get("message_id")
        if _unresolved(message_id):
            message_id = params.get("msg_id")
        label = params.get("label")
        if _unresolved(label):
            return self._blocked(step, start, "INVALID_PARAMETER", "No Gmail label to add.")
        label = str(label).strip()

        if context.dry_run:
            return self._result(
                step, start, ExecutionStepStatus.SUCCESS,
                parameters_used={"dry_run": True, "label": label},
                output={"operation": "add_label", "label": label, "message_id": None if _unresolved(message_id) else str(message_id),
                        "status": "SIMULATED"},
                selection_reason="Dry run: no Gmail calls were made.",
            )
        if _unresolved(message_id):
            return self._blocked(step, start, "INVALID_PARAMETER", "No email from this run to label (search Gmail first).")

        try:
            found = self.labeler.find_label(label)
            label_ids = self.labeler.add_label(str(message_id), found["id"])
        except GmailLabelError as e:
            return self._blocked(step, start, e.code, str(e))
        except Exception as e:  # Google API / network errors: nothing is retried after a possible change
            status = getattr(getattr(e, "resp", None), "status", None)
            if status == 403:
                return self._blocked(step, start, "MISSING_SCOPE", "Google refused labeling: reconnect Gmail and allow it.")
            if status == 404:
                return self._result(step, start, ExecutionStepStatus.FAILED, error="The email no longer exists in Gmail.")
            return self._result(step, start, ExecutionStepStatus.FAILED, error=f"Gmail labeling failed: {type(e).__name__}")

        return self._result(
            step, start, ExecutionStepStatus.SUCCESS,
            parameters_used={"message_id": str(message_id), "label": found["name"]},
            output={
                "operation": "add_label",
                "message_id": str(message_id),
                "label": found["name"],
                "label_id": found["id"],
                "label_ids_after": label_ids,
                "status": "COMPLETED",
            },
            affected_resources=[f"gmail:message:{message_id}:label:{found['id']}"],
            selection_reason=f"Added label '{found['name']}' to the email",
        )

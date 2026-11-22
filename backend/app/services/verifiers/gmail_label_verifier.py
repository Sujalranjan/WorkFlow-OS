"""Independent check for gmail.add_label: re-read the message and confirm the label is on it."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

from app.models.execution import ExecutionStepResult, ExecutionStepStatus
from app.models.execution_plan import PlannedStep
from app.models.verification import VerificationCheck, VerificationStatus, VerificationStrategyType
from app.services.gmail_labels import GmailLabelError, GmailLabeler
from app.services.verifiers.base import BaseVerificationStrategy


class GmailLabelVerificationStrategy(BaseVerificationStrategy):
    def __init__(self, labeler: Optional[GmailLabeler] = None) -> None:
        self.labeler = labeler or GmailLabeler()

    @property
    def name(self) -> str:
        return "GmailLabelVerificationStrategy"

    @property
    def strategy_type(self) -> VerificationStrategyType:
        return VerificationStrategyType.STATE_MATCH

    def supports(self, step: PlannedStep, step_result: ExecutionStepResult) -> bool:
        return step_result.executor_name == "GmailLabelExecutor"

    def build_checks(
        self,
        execution_id: str,
        step: PlannedStep,
        step_result: ExecutionStepResult,
        sandbox_root: str,
        custom_expectations: Optional[Dict[str, Any]] = None,
    ) -> List[VerificationCheck]:
        output = step_result.output or {}
        return [
            VerificationCheck(
                verification_id=f"vchk-glabel-{uuid.uuid4().hex[:8]}",
                execution_id=execution_id,
                execution_step_id=step_result.execution_step_id,
                planned_step_id=step.plan_step_id,
                check_type="gmail_label_added",
                strategy_type=self.strategy_type,
                target=f"Gmail:message:{output.get('message_id') or 'unknown'}:label:{output.get('label') or 'unknown'}",
                expected_state={k: output.get(k) for k in ("message_id", "label", "label_id")},
                actual_state={"status": step_result.status.value, "error": step_result.error, "output": output},
                status=VerificationStatus.PENDING,
                reason="Re-reading the email's labels in Gmail",
            )
        ]

    def verify(self, check: VerificationCheck, sandbox_root: str) -> VerificationCheck:
        check.checked_at = datetime.now(timezone.utc).isoformat()
        state = check.actual_state if isinstance(check.actual_state, dict) else {}
        expected = check.expected_state if isinstance(check.expected_state, dict) else {}
        if state.get("status") == ExecutionStepStatus.BLOCKED.value:
            return self._set(check, VerificationStatus.NOT_APPLICABLE, "The step was blocked, so no label was added.")
        if state.get("status") == ExecutionStepStatus.FAILED.value:
            return self._set(check, VerificationStatus.FAILED, f"Labeling failed: {state.get('error')}")
        if (state.get("output") or {}).get("status") == "SIMULATED":
            return self._set(check, VerificationStatus.NOT_APPLICABLE, "Dry run: no label was added.")
        message_id, label_id = expected.get("message_id"), expected.get("label_id")
        if not message_id or not label_id:
            return self._set(check, VerificationStatus.FAILED, "The step reported no message or label.")
        try:
            label_ids = self.labeler.message_label_ids(str(message_id))
        except GmailLabelError as e:
            return self._set(check, VerificationStatus.UNKNOWN, str(e))
        except Exception as e:
            return self._set(check, VerificationStatus.UNKNOWN, f"Could not read the email from Gmail: {type(e).__name__}")
        check.evidence = {"message_id": message_id, "label_ids": label_ids}
        if label_id in label_ids:
            return self._set(check, VerificationStatus.VERIFIED, f"Gmail shows the label '{expected.get('label')}' on the email.")
        return self._set(check, VerificationStatus.FAILED, f"The label '{expected.get('label')}' is not on the email.")

    @staticmethod
    def _set(check: VerificationCheck, status: VerificationStatus, reason: str) -> VerificationCheck:
        check.status = status
        check.reason = reason
        return check

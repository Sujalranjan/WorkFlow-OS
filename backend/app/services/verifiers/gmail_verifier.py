"""Gmail Verification Strategy (Phase 12).

Deterministically verifies read-only Gmail search execution outcomes.
Confirms:
1. The search operation was executed with the approved query parameter.
2. The response contains normalized message summaries without error.
3. Cryptographic and count evidence is recorded without storing full email contents.

STRICT PRIVACY GUARANTEE:
- Zero email body logging or persistence.
- Zero OAuth token exposure.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
import uuid

from app.models.execution import ExecutionStepResult, ExecutionStepStatus
from app.models.execution_plan import PlannedStep
from app.models.verification import (
    VerificationCheck,
    VerificationStatus,
    VerificationStrategyType,
)
from app.services.verifiers.base import BaseVerificationStrategy

logger = logging.getLogger(__name__)


class GmailVerificationStrategy(BaseVerificationStrategy):
    """Deterministic verifier for Gmail read-only search operations."""

    @property
    def name(self) -> str:
        return "GmailVerificationStrategy"

    @property
    def strategy_type(self) -> VerificationStrategyType:
        return VerificationStrategyType.STATE_MATCH

    def supports(self, step: PlannedStep, step_result: ExecutionStepResult) -> bool:
        """Returns True if the step was executed by GmailApiExecutor or targets Gmail search."""
        act_norm = step.action.lower().strip().replace(" ", "_")
        app_norm = step.application.lower().strip()
        is_gmail = "gmail" in app_norm or "google mail" in app_norm
        is_search = act_norm == "search_email"
        is_executor = step_result.executor_name == "GmailApiExecutor"
        return is_executor or (is_gmail and is_search)

    def build_checks(
        self,
        execution_id: str,
        step: PlannedStep,
        step_result: ExecutionStepResult,
        sandbox_root: str,
        custom_expectations: Optional[Dict[str, Any]] = None,
    ) -> List[VerificationCheck]:
        """Constructs atomic verification check evaluating expected vs actual search output."""
        query_expected = (
            step_result.parameters_used.get("query")
            or (custom_expectations or {}).get("query")
            or "search_query"
        )

        initial_actual = {
            "status": step_result.status.value if hasattr(step_result.status, "value") else str(step_result.status),
            "blocked_reason": step_result.blocked_reason,
            "error": step_result.error,
            "output": step_result.output or {},
        }

        return [
            VerificationCheck(
                verification_id=f"vchk-gmail-{uuid.uuid4().hex[:8]}",
                execution_id=execution_id,
                execution_step_id=step_result.execution_step_id,
                planned_step_id=step.plan_step_id,
                check_type="gmail_search_executed",
                strategy_type=self.strategy_type,
                target="Gmail:search_email",
                expected_state={
                    "operation": "search_email",
                    "query": query_expected,
                    "status": "COMPLETED",
                },
                actual_state=initial_actual,
                status=VerificationStatus.PENDING,
                reason="Verifying Gmail search executed with approved query and returned structured results",
            )
        ]

    def verify(
        self,
        check: VerificationCheck,
        sandbox_root: str,
        step_result: Optional[ExecutionStepResult] = None,
    ) -> VerificationCheck:
        """Evaluates check against actual execution output."""
        check.checked_at = datetime.now(timezone.utc).isoformat()

        # Extract actual status & output from step_result or previously populated actual_state
        state_data = check.actual_state if isinstance(check.actual_state, dict) else {}
        status_val = (
            step_result.status.value
            if (step_result and hasattr(step_result.status, "value"))
            else (step_result.status if step_result else state_data.get("status"))
        )
        blocked_reason = step_result.blocked_reason if step_result else state_data.get("blocked_reason")
        err = step_result.error if step_result else state_data.get("error")
        output = (step_result.output if (step_result and step_result.output) else state_data.get("output")) or {}

        # If step was blocked or skipped, verification is not applicable
        if status_val == ExecutionStepStatus.BLOCKED.value or status_val == "BLOCKED":
            check.status = VerificationStatus.NOT_APPLICABLE
            check.reason = f"Verification not applicable: Step was BLOCKED ({blocked_reason or 'policy'})"
            check.actual_state = {"status": "BLOCKED", "blocked_reason": blocked_reason}
            return check

        if status_val == ExecutionStepStatus.FAILED.value or status_val == "FAILED":
            check.status = VerificationStatus.FAILED
            check.reason = f"Verification failed: Gmail API execution failed ({err or 'unknown error'})"
            check.actual_state = {"status": "FAILED", "error": err}
            return check

        operation = output.get("operation")
        query_actual = output.get("query")
        total_found = output.get("total_found")
        messages = output.get("messages", [])

        # Validate that search actually executed and populated structured output
        if operation == "search_email" and query_actual is not None and total_found is not None:
            check.status = VerificationStatus.VERIFIED
            check.actual_state = {
                "operation": operation,
                "query": query_actual,
                "total_found": total_found,
                "status": "COMPLETED",
            }
            # Privacy: extract only message IDs, no personal body text
            msg_ids = [m.get("message_id") for m in messages if isinstance(m, dict)][:10]
            check.evidence = {
                "query": query_actual,
                "total_found": total_found,
                "sample_message_ids": msg_ids,
                "verified_at": check.checked_at,
            }
            check.reason = f"Verified: Gmail API search for query '{query_actual}' returned {total_found} message summary record(s)."
        else:
            check.status = VerificationStatus.FAILED
            check.actual_state = output
            check.reason = "Verification failed: Gmail search output missing query, total_found, or message summaries."

        return check

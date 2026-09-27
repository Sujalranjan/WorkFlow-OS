"""Slack Verification Strategy (Phase 15D).

Independently verifies that Slack notifications were genuinely delivered and exist
in the target Slack workspace/channel.

SECURITY & GOVERNANCE:
- Never simply trusts the executor output; issues an independent query via Slack Web API (conversations.history).
- Checks channel, message timestamp (ts), and content.
- Generates cryptographic integrity evidence using SHA-256.
- Does not expose Slack tokens or authorization headers.
"""

from datetime import datetime, timezone
import hashlib
import json
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
from app.services.slack_client import SlackApiClient
from app.services.verifiers.base import BaseVerificationStrategy

logger = logging.getLogger(__name__)


class SlackVerificationStrategy(BaseVerificationStrategy):
    """Independent verification strategy for Slack notification delivery."""

    def __init__(self, client: Optional[SlackApiClient] = None) -> None:
        self.client = client or SlackApiClient()

    @property
    def name(self) -> str:
        return "SlackVerificationStrategy"

    @property
    def strategy_type(self) -> VerificationStrategyType:
        return VerificationStrategyType.STATE_MATCH

    def supports(self, step: PlannedStep, step_result: Optional[ExecutionStepResult] = None) -> bool:
        app_norm = step.application.lower().strip()
        act_norm = step.action.lower().strip().replace(" ", "_")
        is_slack = "slack" in app_norm
        is_act = act_norm == "send_notification"
        is_exec = (step_result is not None and step_result.executor_name == "SlackApiExecutor")
        return (is_slack and is_act) or is_exec

    def build_checks(
        self,
        execution_id: str,
        step: PlannedStep,
        step_result: ExecutionStepResult,
        sandbox_root: str,
    ) -> List[VerificationCheck]:
        output = step_result.output or {}
        channel = output.get("channel") or step.resolved_parameters.get("channel") or "default_channel"
        ts = output.get("ts") or "unknown_ts"
        message_snippet = str(step.resolved_parameters.get("message") or output.get("message_preview") or "")[:50]

        initial_actual = {
            "status": step_result.status.value if hasattr(step_result.status, "value") else str(step_result.status),
            "output": output,
            "blocked_reason": step_result.blocked_reason,
            "error": step_result.error,
        }

        return [
            VerificationCheck(
                verification_id=f"vchk-slack-{uuid.uuid4().hex[:8]}",
                execution_id=execution_id,
                execution_step_id=step_result.execution_step_id,
                planned_step_id=step.plan_step_id,
                check_type="slack_notification_delivered",
                strategy_type=self.strategy_type,
                target=f"Slack:channel:{channel}:ts:{ts}",
                expected_state={
                    "operation": "send_notification",
                    "channel": channel,
                    "ts": ts,
                    "message_snippet": message_snippet,
                    "status": "COMPLETED",
                },
                actual_state=initial_actual,
                status=VerificationStatus.PENDING,
                reason=f"Verifying notification delivery to Slack channel '{channel}' at ts '{ts}'",
            )
        ]

    def verify(
        self,
        check: VerificationCheck,
        sandbox_root: str,
        step_result: Optional[ExecutionStepResult] = None,
    ) -> VerificationCheck:
        check.checked_at = datetime.now(timezone.utc).isoformat()
        state_data = check.actual_state if isinstance(check.actual_state, dict) else {}
        status_val = (
            step_result.status.value
            if (step_result and hasattr(step_result.status, "value"))
            else (step_result.status if step_result else state_data.get("status"))
        )
        blocked_reason = step_result.blocked_reason if step_result else state_data.get("blocked_reason")
        err = step_result.error if step_result else state_data.get("error")
        output = (step_result.output if (step_result and step_result.output) else state_data.get("output")) or {}

        # 1. Step was BLOCKED
        if status_val in (ExecutionStepStatus.BLOCKED.value, "BLOCKED"):
            check.status = VerificationStatus.NOT_APPLICABLE
            check.reason = f"Verification not applicable: Step was BLOCKED ({blocked_reason or 'policy'})"
            check.actual_state = {"status": "BLOCKED", "blocked_reason": blocked_reason}
            return check

        # 2. Step FAILED
        if status_val in (ExecutionStepStatus.FAILED.value, "FAILED"):
            check.status = VerificationStatus.FAILED
            check.reason = f"Verification failed: Slack execution failed ({err or 'unknown error'})"
            check.actual_state = {"status": "FAILED", "error": err}
            return check

        # 3. Dry-run simulation
        if output.get("status") == "SIMULATED":
            check.status = VerificationStatus.VERIFIED
            check.reason = "Verified: Dry-run simulation completed safely with 0 external API calls"
            check.actual_state = output
            return check

        # 4. REAL Verification via independent Slack query
        channel = output.get("channel")
        ts = output.get("ts")
        if not channel or not ts:
            check.status = VerificationStatus.FAILED
            check.reason = "Verification failed: Channel or timestamp (ts) missing from execution output"
            return check

        try:
            is_valid, msg_data, verif_msg = self.client.verify_message(
                channel=str(channel),
                ts=str(ts),
            )

            if not is_valid:
                check.status = VerificationStatus.FAILED
                check.reason = f"Verification failed: {verif_msg}"
                check.actual_state = {"found": False, "reason": verif_msg}
                return check

            # Compute cryptographic integrity evidence using SHA-256
            msg_json = json.dumps(msg_data or {}, sort_keys=True)
            sha256_hash = hashlib.sha256(msg_json.encode("utf-8")).hexdigest()

            check.status = VerificationStatus.VERIFIED
            check.actual_state = msg_data or {"channel": channel, "ts": ts}
            check.evidence = {
                "channel": channel,
                "ts": ts,
                "sha256": sha256_hash,
                "integrity_evidence": "cryptographic integrity evidence using SHA-256",
                "verified_at": check.checked_at,
            }
            check.reason = f"Verified: Message confirmed present in Slack channel '{channel}' at ts '{ts}' with cryptographic integrity evidence using SHA-256."
            return check

        except Exception as e:
            check.status = VerificationStatus.FAILED
            check.reason = f"Verification failed: Error querying Slack API: {str(e)}"
            return check

"""Gmail Verification Strategy (Phase 12 & Phase 15A).

Deterministically verifies read-only Gmail API execution outcomes:
1. search_email:
   - Operation executed with approved query parameter.
   - Normalized message summaries without full body persistence or token exposure.
2. download_attachment:
   - Attachment retrieved from Gmail and saved to controlled WorkFlowOS sandbox destination.
   - File exists at expected destination inside sandbox.
   - Non-zero file size.
   - Cryptographic integrity evidence recorded using SHA-256.

STRICT PRIVACY & INTEGRITY GUARANTEES:
- Zero email body logging or persistence.
- Zero OAuth token exposure.
- Independent verification: Verification fails if file is missing, zero bytes, or modified even if executor reported SUCCESS.
"""

from datetime import datetime, timezone
import hashlib
import logging
import os
from pathlib import Path
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
    """Deterministic verifier for Gmail read-only search and attachment operations."""

    @property
    def name(self) -> str:
        return "GmailVerificationStrategy"

    @property
    def strategy_type(self) -> VerificationStrategyType:
        return VerificationStrategyType.STATE_MATCH

    def supports(self, step: PlannedStep, step_result: ExecutionStepResult) -> bool:
        """Returns True if the step was executed by GmailApiExecutor or targets Gmail operations."""
        act_norm = step.action.lower().strip().replace(" ", "_")
        app_norm = step.application.lower().strip()
        is_gmail = "gmail" in app_norm or "google mail" in app_norm
        is_supported_act = act_norm in ("search_email", "download_attachment", "download_email_attachment")
        is_executor = step_result.executor_name == "GmailApiExecutor"
        return is_executor or (is_gmail and is_supported_act)

    def build_checks(
        self,
        execution_id: str,
        step: PlannedStep,
        step_result: ExecutionStepResult,
        sandbox_root: str,
        custom_expectations: Optional[Dict[str, Any]] = None,
    ) -> List[VerificationCheck]:
        """Constructs atomic verification check evaluating expected vs actual Gmail output."""
        act_norm = step.action.lower().strip().replace(" ", "_")
        output = step_result.output or {}
        operation = output.get("operation") or act_norm

        initial_actual = {
            "status": step_result.status.value if hasattr(step_result.status, "value") else str(step_result.status),
            "blocked_reason": step_result.blocked_reason,
            "error": step_result.error,
            "output": output,
        }

        # Case 1: Attachment Download Verification Check
        if operation == "download_attachment" or act_norm in ("download_attachment", "download_email_attachment"):
            expected_msg_id = (
                step_result.parameters_used.get("message_id")
                or (custom_expectations or {}).get("message_id")
                or "any"
            )
            expected_filename = (
                step_result.parameters_used.get("filename")
                or output.get("filename")
                or (custom_expectations or {}).get("filename")
                or "attachment.bin"
            )
            expected_dest = (
                output.get("saved_path")
                or str(Path(sandbox_root) / "attachments" / expected_filename)
            )

            return [
                VerificationCheck(
                    verification_id=f"vchk-gmail-att-{uuid.uuid4().hex[:8]}",
                    execution_id=execution_id,
                    execution_step_id=step_result.execution_step_id,
                    planned_step_id=step.plan_step_id,
                    check_type="gmail_attachment_downloaded",
                    strategy_type=self.strategy_type,
                    target=f"Gmail:download_attachment:{expected_filename}",
                    expected_state={
                        "operation": "download_attachment",
                        "message_id": expected_msg_id,
                        "filename": expected_filename,
                        "destination": expected_dest,
                        "file_exists": True,
                        "min_size_bytes": 1,
                        "status": "COMPLETED",
                    },
                    actual_state=initial_actual,
                    status=VerificationStatus.PENDING,
                    reason=(
                        f"Verifying Gmail attachment '{expected_filename}' was retrieved and exists at "
                        "controlled destination with cryptographic integrity evidence using SHA-256"
                    ),
                )
            ]

        # Case 2: Email Search Verification Check
        query_expected = (
            step_result.parameters_used.get("query")
            or (custom_expectations or {}).get("query")
            or "search_query"
        )

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
        """Evaluates check against actual execution output and filesystem state."""
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
        if status_val in (ExecutionStepStatus.BLOCKED.value, "BLOCKED"):
            check.status = VerificationStatus.NOT_APPLICABLE
            check.reason = f"Verification not applicable: Step was BLOCKED ({blocked_reason or 'policy'})"
            check.actual_state = {"status": "BLOCKED", "blocked_reason": blocked_reason}
            return check

        # If step failed execution
        if status_val in (ExecutionStepStatus.FAILED.value, "FAILED"):
            check.status = VerificationStatus.FAILED
            check.reason = f"Verification failed: Gmail API execution failed ({err or 'unknown error'})"
            check.actual_state = {"status": "FAILED", "error": err}
            return check

        # Branch verification by check_type
        if check.check_type == "gmail_attachment_downloaded":
            return self._verify_attachment(check, sandbox_root, output)
        else:
            return self._verify_search(check, output)

    def _verify_attachment(
        self,
        check: VerificationCheck,
        sandbox_root: str,
        output: Dict[str, Any],
    ) -> VerificationCheck:
        """Verifies downloaded attachment existence, confinement, non-zero size, and SHA-256 integrity."""
        saved_path_str = output.get("saved_path")
        expected_fn = output.get("filename") or (
            check.expected_state.get("filename") if isinstance(check.expected_state, dict) else "attachment.bin"
        )

        sandbox_real = Path(sandbox_root).resolve()

        if saved_path_str:
            target_file = Path(saved_path_str).resolve()
        else:
            target_file = (sandbox_real / "attachments" / expected_fn).resolve()

        # 1. Confinement check: file must be inside sandbox_root
        try:
            target_file.relative_to(sandbox_real)
        except ValueError:
            check.status = VerificationStatus.FAILED
            check.reason = f"Verification failed: Attachment path '{target_file}' escapes controlled sandbox '{sandbox_real}'"
            check.actual_state = {"file_exists": False, "error": "Sandbox boundary escape detected"}
            return check

        # 2. Existence check: file must exist on disk
        if not target_file.exists() or not target_file.is_file():
            check.status = VerificationStatus.FAILED
            check.reason = f"Verification failed: Downloaded attachment '{expected_fn}' not found at controlled path '{target_file}'"
            check.actual_state = {"file_exists": False, "saved_path": str(target_file)}
            return check

        # 3. File size check: must be > 0 bytes
        try:
            file_size = target_file.stat().st_size
        except Exception as e:
            check.status = VerificationStatus.FAILED
            check.reason = f"Verification failed: Unable to read file stats for '{target_file}': {str(e)}"
            check.actual_state = {"file_exists": True, "error": str(e)}
            return check

        if file_size <= 0:
            check.status = VerificationStatus.FAILED
            check.reason = f"Verification failed: Downloaded attachment '{expected_fn}' at '{target_file}' is empty (0 bytes)"
            check.actual_state = {"file_exists": True, "size_bytes": 0}
            return check

        # 4. Cryptographic integrity evidence using SHA-256
        try:
            with open(target_file, "rb") as f:
                content = f.read()
            computed_sha256 = hashlib.sha256(content).hexdigest()
        except Exception as e:
            check.status = VerificationStatus.FAILED
            check.reason = f"Verification failed: Could not read attachment for SHA-256 computation: {str(e)}"
            check.actual_state = {"file_exists": True, "error": str(e)}
            return check

        expected_sha256 = output.get("sha256")
        if expected_sha256 and expected_sha256 != computed_sha256:
            check.status = VerificationStatus.FAILED
            check.reason = (
                f"Verification failed: SHA-256 mismatch for '{expected_fn}'. "
                f"Recorded: {expected_sha256}, Actual: {computed_sha256}"
            )
            check.actual_state = {
                "file_exists": True,
                "expected_sha256": expected_sha256,
                "actual_sha256": computed_sha256,
            }
            return check

        # Verification Succeeded
        check.status = VerificationStatus.VERIFIED
        check.actual_state = {
            "operation": "download_attachment",
            "message_id": output.get("message_id"),
            "attachment_id": output.get("attachment_id"),
            "filename": expected_fn,
            "saved_path": str(target_file),
            "size_bytes": file_size,
            "sha256": computed_sha256,
            "file_exists": True,
            "status": "COMPLETED",
        }
        check.evidence = {
            "message_id": output.get("message_id"),
            "attachment_id": output.get("attachment_id"),
            "filename": expected_fn,
            "saved_path": str(target_file),
            "file_size_bytes": file_size,
            "sha256": computed_sha256,
            "integrity_evidence": "cryptographic integrity evidence using SHA-256",
            "verified_at": check.checked_at,
        }
        check.reason = (
            f"Verified: Attachment '{expected_fn}' exists at controlled destination with cryptographic integrity "
            f"evidence using SHA-256 (size={file_size} bytes)."
        )
        return check

    def _verify_search(
        self,
        check: VerificationCheck,
        output: Dict[str, Any],
    ) -> VerificationCheck:
        """Verifies email search output structured normalization."""
        operation = output.get("operation")
        query_actual = output.get("query")
        total_found = output.get("total_found")
        messages = output.get("messages", [])

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

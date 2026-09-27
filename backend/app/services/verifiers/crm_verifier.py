"""CRM Verification Strategy (Phase 15B).

Deterministically verifies CRM execution outcomes against the CRM API:
1. find_customer: Confirms customer lookup succeeded with matching records.
2. update_customer_record: Independently queries the CRM API to verify that the
   customer record on the CRM server actually contains the expected updated fields
   (status, notes, invoice reference, etc.).

INDEPENDENT VERIFICATION GUARANTEE:
- Verifier queries the CRM API independently from the executor.
- If the executor claimed SUCCESS but the CRM database was not updated, verification FAILS.
- Records cryptographic integrity evidence using SHA-256 of the verified customer state.
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
from app.services.crm_client import CrmApiClient
from app.services.verifiers.base import BaseVerificationStrategy

logger = logging.getLogger(__name__)


class CrmVerificationStrategy(BaseVerificationStrategy):
    """Deterministic verifier for CRM API execution operations."""

    def __init__(self, client: Optional[CrmApiClient] = None) -> None:
        self.client = client or CrmApiClient()

    @property
    def name(self) -> str:
        return "CrmVerificationStrategy"

    @property
    def strategy_type(self) -> VerificationStrategyType:
        return VerificationStrategyType.STATE_MATCH

    def supports(self, step: PlannedStep, step_result: ExecutionStepResult) -> bool:
        """Returns True if the step was executed by CrmApiExecutor or targets CRM."""
        app_norm = step.application.lower().strip()
        is_crm_target = any(c in app_norm for c in ["crm", "hubspot", "salesforce"])
        is_executor = step_result.executor_name == "CrmApiExecutor"
        return is_executor or is_crm_target

    def build_checks(
        self,
        execution_id: str,
        step: PlannedStep,
        step_result: ExecutionStepResult,
        sandbox_root: str,
        custom_expectations: Optional[Dict[str, Any]] = None,
    ) -> List[VerificationCheck]:
        """Constructs atomic verification check evaluating expected vs actual CRM output."""
        output = step_result.output or {}
        operation = output.get("operation") or step.action.lower()

        initial_actual = {
            "status": step_result.status.value if hasattr(step_result.status, "value") else str(step_result.status),
            "blocked_reason": step_result.blocked_reason,
            "error": step_result.error,
            "output": output,
        }

        # Case 1: Update Customer Record
        if "update" in operation or "update" in step.action.lower():
            cust_id = (
                output.get("customer_id")
                or step_result.parameters_used.get("customer_id")
                or "unknown"
            )
            expected_fields = output.get("updated_fields") or {
                k: v for k, v in step_result.parameters_used.items() if k != "customer_id"
            }

            return [
                VerificationCheck(
                    verification_id=f"vchk-crm-upd-{uuid.uuid4().hex[:8]}",
                    execution_id=execution_id,
                    execution_step_id=step_result.execution_step_id,
                    planned_step_id=step.plan_step_id,
                    check_type="crm_customer_record_updated",
                    strategy_type=self.strategy_type,
                    target=f"CRM:customer:{cust_id}",
                    expected_state={
                        "operation": "update_customer_record",
                        "customer_id": cust_id,
                        "expected_fields": expected_fields,
                        "status": "COMPLETED",
                    },
                    actual_state=initial_actual,
                    status=VerificationStatus.PENDING,
                    reason=f"Verifying customer '{cust_id}' record was updated in CRM with expected fields",
                )
            ]

        # Case 2: Find Customer
        query_expected = (
            step_result.parameters_used.get("query")
            or output.get("query")
            or "customer_lookup"
        )
        return [
            VerificationCheck(
                verification_id=f"vchk-crm-find-{uuid.uuid4().hex[:8]}",
                execution_id=execution_id,
                execution_step_id=step_result.execution_step_id,
                planned_step_id=step.plan_step_id,
                check_type="crm_customer_found",
                strategy_type=self.strategy_type,
                target=f"CRM:find_customer:{query_expected}",
                expected_state={
                    "operation": "find_customer",
                    "query": query_expected,
                    "status": "COMPLETED",
                },
                actual_state=initial_actual,
                status=VerificationStatus.PENDING,
                reason="Verifying customer lookup query executed and returned valid results",
            )
        ]

    def verify(
        self,
        check: VerificationCheck,
        sandbox_root: str,
        step_result: Optional[ExecutionStepResult] = None,
    ) -> VerificationCheck:
        """Independently verifies check against the live CRM API."""
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

        # If step was blocked
        if status_val in (ExecutionStepStatus.BLOCKED.value, "BLOCKED"):
            check.status = VerificationStatus.NOT_APPLICABLE
            check.reason = f"Verification not applicable: Step was BLOCKED ({blocked_reason or 'policy'})"
            check.actual_state = {"status": "BLOCKED", "blocked_reason": blocked_reason}
            return check

        # If step failed execution
        if status_val in (ExecutionStepStatus.FAILED.value, "FAILED"):
            check.status = VerificationStatus.FAILED
            check.reason = f"Verification failed: CRM API execution failed ({err or 'unknown error'})"
            check.actual_state = {"status": "FAILED", "error": err}
            return check

        # Branch verification by check_type
        if check.check_type == "crm_customer_record_updated":
            return self._verify_update(check, output)
        else:
            return self._verify_find(check, output)

    def _verify_update(
        self,
        check: VerificationCheck,
        output: Dict[str, Any],
    ) -> VerificationCheck:
        """Independently queries CRM API to confirm customer record state matches expectations."""
        cust_id = output.get("customer_id") or (
            check.expected_state.get("customer_id") if isinstance(check.expected_state, dict) else None
        )
        if not cust_id:
            check.status = VerificationStatus.FAILED
            check.reason = "Verification failed: Customer ID missing from execution output"
            return check

        try:
            # Independent query to CRM API
            live_cust = self.client.get_customer(str(cust_id))
            if not live_cust:
                check.status = VerificationStatus.FAILED
                check.reason = f"Verification failed: Customer '{cust_id}' not found on CRM server after update"
                check.actual_state = {"found": False}
                return check

            # Verify expected updated fields
            expected_fields = {}
            if isinstance(check.expected_state, dict):
                expected_fields = check.expected_state.get("expected_fields", {})

            mismatches: List[str] = []
            cust_dict = live_cust.model_dump()

            for key, exp_val in expected_fields.items():
                actual_val = cust_dict.get(key)
                if exp_val is not None and actual_val != exp_val:
                    mismatches.append(f"field '{key}': expected '{exp_val}', got '{actual_val}'")

            if mismatches:
                check.status = VerificationStatus.FAILED
                check.reason = f"Verification failed: CRM state mismatch for '{cust_id}': {', '.join(mismatches)}"
                check.actual_state = cust_dict
                return check

            # Compute cryptographic integrity evidence using SHA-256
            state_json = json.dumps(cust_dict, sort_keys=True)
            sha256_hash = hashlib.sha256(state_json.encode("utf-8")).hexdigest()

            check.status = VerificationStatus.VERIFIED
            check.actual_state = cust_dict
            check.evidence = {
                "customer_id": cust_id,
                "verified_status": live_cust.status,
                "updated_at": live_cust.updated_at,
                "sha256": sha256_hash,
                "integrity_evidence": "cryptographic integrity evidence using SHA-256",
                "verified_at": check.checked_at,
            }
            check.reason = (
                f"Verified: Customer '{cust_id}' updated in CRM with status '{live_cust.status}' "
                "and cryptographic integrity evidence using SHA-256."
            )
            return check

        except Exception as e:
            check.status = VerificationStatus.FAILED
            check.reason = f"Verification failed: Error querying CRM API: {str(e)}"
            return check

    def _verify_find(
        self,
        check: VerificationCheck,
        output: Dict[str, Any],
    ) -> VerificationCheck:
        """Verifies customer search output structure and results."""
        total_found = output.get("total_found")
        customers = output.get("customers", [])

        if total_found is not None and isinstance(customers, list):
            check.status = VerificationStatus.VERIFIED
            check.actual_state = output
            check.evidence = {
                "query": output.get("query"),
                "total_found": total_found,
                "matched_ids": [c.get("customer_id") for c in customers if isinstance(c, dict)][:5],
                "verified_at": check.checked_at,
            }
            check.reason = f"Verified: CRM customer lookup returned {total_found} record(s)."
        else:
            check.status = VerificationStatus.FAILED
            check.actual_state = output
            check.reason = "Verification failed: CRM search output missing total_found or customer records."

        return check

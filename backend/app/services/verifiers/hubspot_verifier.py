"""Independent post-run checks for HubSpot steps: re-read the contact or note through the API.

- find_contact   -> the contact still exists
- update_contact -> the property now has the written value
- add_note       -> the note exists, has the written body and is attached to the contact
"""

from datetime import datetime, timezone
import uuid
from typing import Any, Dict, List, Optional

import httpx

from app.models.execution import ExecutionStepResult, ExecutionStepStatus
from app.models.execution_plan import PlannedStep
from app.models.verification import VerificationCheck, VerificationStatus, VerificationStrategyType
from app.services.hubspot_client import HubSpotClient, HubSpotError
from app.services.verifiers.base import BaseVerificationStrategy


class HubSpotVerificationStrategy(BaseVerificationStrategy):
    def __init__(self, client: Optional[HubSpotClient] = None) -> None:
        self.client = client or HubSpotClient()

    @property
    def name(self) -> str:
        return "HubSpotVerificationStrategy"

    @property
    def strategy_type(self) -> VerificationStrategyType:
        return VerificationStrategyType.STATE_MATCH

    def supports(self, step: PlannedStep, step_result: ExecutionStepResult) -> bool:
        return step_result.executor_name == "HubSpotApiExecutor"

    def build_checks(
        self,
        execution_id: str,
        step: PlannedStep,
        step_result: ExecutionStepResult,
        sandbox_root: str,
        custom_expectations: Optional[Dict[str, Any]] = None,
    ) -> List[VerificationCheck]:
        output = step_result.output or {}
        operation = output.get("operation") or step.action
        check_type = {
            "find_contact": "hubspot_contact_found",
            "update_contact": "hubspot_contact_updated",
            "add_note": "hubspot_note_created",
        }.get(operation, "hubspot_contact_found")
        target = output.get("note_id") or output.get("contact_id") or (output.get("contact") or {}).get("contact_id") or "unknown"
        return [
            VerificationCheck(
                verification_id=f"vchk-hs-{uuid.uuid4().hex[:8]}",
                execution_id=execution_id,
                execution_step_id=step_result.execution_step_id,
                planned_step_id=step.plan_step_id,
                check_type=check_type,
                strategy_type=self.strategy_type,
                target=f"HubSpot:{operation}:{target}",
                expected_state={"operation": operation, **{k: output.get(k) for k in ("contact_id", "property", "value", "note_id", "note_body")}},
                actual_state={"status": step_result.status.value, "error": step_result.error, "output": output},
                status=VerificationStatus.PENDING,
                reason=f"Re-reading HubSpot to confirm {operation}",
            )
        ]

    def verify(self, check: VerificationCheck, sandbox_root: str) -> VerificationCheck:
        check.checked_at = datetime.now(timezone.utc).isoformat()
        state = check.actual_state if isinstance(check.actual_state, dict) else {}
        status = state.get("status")
        output = state.get("output") or {}
        expected = check.expected_state if isinstance(check.expected_state, dict) else {}

        if status == ExecutionStepStatus.BLOCKED.value:
            return self._set(check, VerificationStatus.NOT_APPLICABLE, "The step was blocked, so nothing changed in HubSpot.")
        if status == ExecutionStepStatus.FAILED.value:
            return self._set(check, VerificationStatus.FAILED, f"The HubSpot step failed: {state.get('error')}")
        if output.get("status") == "SIMULATED":
            return self._set(check, VerificationStatus.NOT_APPLICABLE, "Dry run: nothing was written to HubSpot.")

        try:
            if check.check_type == "hubspot_contact_updated":
                prop, value = expected.get("property"), expected.get("value")
                contact = self.client.get_contact(str(expected.get("contact_id")), properties=[str(prop)])
                actual = contact.properties.get(prop)
                check.evidence = {"contact_id": contact.contact_id, "property": prop, "actual_value": actual}
                if str(actual) == str(value):
                    return self._set(check, VerificationStatus.VERIFIED, f"HubSpot shows {prop} = '{actual}' on contact {contact.contact_id}.")
                return self._set(check, VerificationStatus.FAILED, f"HubSpot shows {prop} = '{actual}', expected '{value}'.")

            if check.check_type == "hubspot_note_created":
                note = self.client.get_note(str(expected.get("note_id")))
                body = (note.get("properties") or {}).get("hs_note_body")
                linked = {
                    str(r.get("id") or r.get("toObjectId"))
                    for r in ((note.get("associations") or {}).get("contacts") or {}).get("results", [])
                }
                check.evidence = {"note_id": note.get("id"), "linked_contacts": sorted(linked)}
                if body != expected.get("note_body"):
                    return self._set(check, VerificationStatus.FAILED, "The note exists but its text differs from what was written.")
                if expected.get("contact_id") and linked and str(expected["contact_id"]) not in linked:
                    return self._set(check, VerificationStatus.FAILED, "The note is not attached to the expected contact.")
                return self._set(check, VerificationStatus.VERIFIED, f"Note {note.get('id')} exists on the contact.")

            contact_id = (output.get("contact") or {}).get("contact_id")
            contact = self.client.get_contact(str(contact_id))
            check.evidence = {"contact_id": contact.contact_id}
            return self._set(check, VerificationStatus.VERIFIED, f"Contact {contact.contact_id} exists in HubSpot.")
        except HubSpotError as e:
            return self._set(check, VerificationStatus.FAILED if e.status_code == 404 else VerificationStatus.UNKNOWN, str(e))
        except httpx.HTTPError as e:
            return self._set(check, VerificationStatus.UNKNOWN, f"HubSpot unreachable: {type(e).__name__}")

    @staticmethod
    def _set(check: VerificationCheck, status: VerificationStatus, reason: str) -> VerificationCheck:
        check.status = status
        check.reason = reason
        return check

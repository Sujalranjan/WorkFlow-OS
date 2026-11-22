"""HubSpot executor: find a contact, update one property, add a note.

- find_contact: exact email match (or text search). No match or several matches pause the run for
  a person to choose (the same Inbox picker as the Demo CRM); never guessed.
- update_contact: sets the contact property chosen in Settings (or the step's `contact_property`)
  to `property_value`. High risk; requires workflow approval like every external change.
- add_note: attaches a note to the contact (association type 202).

Dry runs make no HubSpot calls. Missing setup, a rejected token and missing scopes are reported
as BLOCKED with the reason, before anything changes.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.models.canonical import RiskLevel
from app.models.execution import ExecutionContext, ExecutionStepResult, ExecutionStepStatus
from app.models.execution_plan import ExecutionStrategy, PlannedStep
from app.models.strategy import ExecutionStrategyType, ExecutorCapability
from app.services.executors.base import BaseExecutor
from app.services.hubspot_client import HubSpotClient, HubSpotContact, HubSpotError, HubSpotNotConfigured

logger = logging.getLogger(__name__)

ACTIONS = ("find_contact", "update_contact", "add_note")
# Inputs a person may supply when find_contact pauses (same names as the Demo CRM, so the Inbox picker works).
CONTACT_INTERVENTION_INPUTS = ["selected_customer_id", "customer_query"]
_MAX_CANDIDATES = 10


def hubspot_settings() -> Dict[str, Any]:
    """Non-secret HubSpot settings from Settings (e.g. which property update_contact writes)."""
    try:
        from app.services.credential_store import HUBSPOT, get_credential_store

        info = get_credential_store().info(HUBSPOT)
    except Exception:
        logger.exception("Could not read HubSpot settings")
        return {}
    return info.metadata if info else {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class HubSpotApiExecutor(BaseExecutor):
    def __init__(self, client: Optional[HubSpotClient] = None) -> None:
        self.client = client or HubSpotClient()

    @property
    def name(self) -> str:
        return "HubSpotApiExecutor"

    @property
    def strategy(self) -> ExecutionStrategy:
        return ExecutionStrategy.API

    @property
    def capability(self) -> ExecutorCapability:
        return ExecutorCapability(
            executor_name=self.name,
            strategy_type=ExecutionStrategyType.API_INTEGRATION,
            supported_actions=list(ACTIONS),
            supported_targets=["HubSpot"],
            supported_risk_levels=[RiskLevel.LOW.value, RiskLevel.MEDIUM.value, RiskLevel.HIGH.value],
            implemented=True,
            requires_external_access=True,
            supports_verification=True,
            priority=1,
            description="HubSpot CRM contacts and notes through the HubSpot API.",
        )

    def supports(self, strategy: Any) -> bool:
        value = str(strategy.value if hasattr(strategy, "value") else strategy).upper()
        return value in ("API", ExecutionStrategyType.API_INTEGRATION.value)

    # ---------------------------------------------------------------- helpers

    def _result(self, step: PlannedStep, start: str, status: ExecutionStepStatus, **fields) -> ExecutionStepResult:
        return ExecutionStepResult(
            planned_step_id=step.plan_step_id,
            action_name=step.action,
            target_application=step.application,
            strategy=self.strategy,
            executor_name=self.name,
            status=status,
            selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
            policy_decision="ALLOWED" if status != ExecutionStepStatus.BLOCKED else "BLOCKED",
            start_time=start,
            end_time=_now(),
            **fields,
        )

    def _blocked(self, step, start, reason: str, error: str) -> ExecutionStepResult:
        return self._result(step, start, ExecutionStepStatus.BLOCKED, blocked_reason=reason, error=error)

    @staticmethod
    def _params(step: PlannedStep, context: ExecutionContext) -> Dict[str, Any]:
        return {**(context.resolved_parameters or {}), **(step.resolved_parameters or {})}

    @staticmethod
    def _unresolved(value: Any) -> bool:
        """Empty, or a template like '{customer_email}' that nothing upstream filled in."""
        text = str(value or "").strip()
        return not text or (text.startswith("{") and text.endswith("}"))

    # ------------------------------------------------------------- interface

    def validate(self, step: PlannedStep, context: ExecutionContext) -> Tuple[bool, List[str]]:
        if step.action not in ACTIONS:
            return False, [f"HubSpotApiExecutor does not support '{step.action}'."]
        return True, []

    def execute(self, step: PlannedStep, context: ExecutionContext) -> ExecutionStepResult:
        start = _now()
        if step.action not in ACTIONS:
            return self._blocked(step, start, "UNSUPPORTED_ACTION", f"HubSpot cannot '{step.action}'.")
        params = self._params(step, context)
        if context.dry_run:
            return self._simulate(step, start, params)
        try:
            if step.action == "find_contact":
                return self._find(step, start, params)
            if step.action == "update_contact":
                return self._update(step, start, params)
            return self._add_note(step, start, params)
        except HubSpotNotConfigured as e:
            return self._blocked(step, start, "INTEGRATION_UNAVAILABLE", str(e))
        except HubSpotError as e:
            if e.status_code == 401:
                return self._blocked(step, start, "AUTHENTICATION_REQUIRED", str(e))
            if e.status_code == 403:
                return self._blocked(step, start, "MISSING_SCOPE", str(e))
            return self._result(step, start, ExecutionStepStatus.FAILED, error=str(e), parameters_used=self._safe(params))
        except httpx.HTTPError as e:
            return self._result(step, start, ExecutionStepStatus.FAILED, error=f"HubSpot unreachable: {type(e).__name__}")

    @staticmethod
    def _safe(params: Dict[str, Any]) -> Dict[str, Any]:
        keys = ("contact_query", "contact_id", "contact_property", "property_value", "selected_customer_id")
        return {k: params[k] for k in keys if params.get(k) is not None}

    # ----------------------------------------------------------------- find

    def _find(self, step, start, params) -> ExecutionStepResult:
        selected = params.get("selected_customer_id")
        if selected and str(selected).strip():
            contact = self.client.get_contact(str(selected).strip())
            return self._found(step, start, contact, query=f"id:{contact.contact_id}", total=1)

        query = params.get("contact_query") or params.get("customer_query")
        if self._unresolved(query):
            query = params.get("customer_email")
        if self._unresolved(query):
            return self._blocked(step, start, "INVALID_PARAMETER", "No email or search text to look the contact up by.")
        query = str(query).strip()
        if query.isdigit():  # a HubSpot record id (what a contact page URL shows)
            return self._found(step, start, self.client.get_contact(query), query=f"id:{query}", total=1)

        contacts = self.client.find_contacts(query)
        exact = [c for c in contacts if (c.email or "").lower() == query.lower()]
        chosen = contacts[0] if len(contacts) == 1 else (exact[0] if len(exact) == 1 else None)
        if chosen is None:
            return self._needs_choice(step, start, query, contacts)
        return self._found(step, start, chosen, query=query, total=len(contacts))

    def _found(self, step, start, contact: HubSpotContact, query: str, total: int) -> ExecutionStepResult:
        record = {**contact.as_candidate(), "contact_id": contact.contact_id}
        return self._result(
            step,
            start,
            ExecutionStepStatus.SUCCESS,
            parameters_used={"query": query},
            output={"operation": "find_contact", "query": query, "total_found": total, "contact": record, "status": "COMPLETED"},
            selection_reason=f"Found HubSpot contact {contact.contact_id}",
        )

    def _needs_choice(self, step, start, query: str, contacts: List[HubSpotContact]) -> ExecutionStepResult:
        if not contacts:
            reason = f"No HubSpot contact matched '{query}'. Choose the contact or enter a different search."
            code = "NO_MATCH"
        else:
            reason = f"{len(contacts)} HubSpot contacts matched '{query}'. Choose which one this request is for."
            code = "MULTIPLE_MATCHES"
        return self._result(
            step,
            start,
            ExecutionStepStatus.NEEDS_INPUT,
            parameters_used={"query": query},
            output={"operation": "find_contact", "query": query, "total_found": len(contacts)},
            error=reason,
            intervention={
                "parameter": "customer",
                "reason": reason,
                "code": code,
                "accepted_inputs": list(CONTACT_INTERVENTION_INPUTS),
                "candidates": [c.as_candidate() for c in contacts[:_MAX_CANDIDATES]],
            },
            selection_reason=f"HubSpot lookup was not conclusive ({code}); paused for a person",
        )

    # --------------------------------------------------------------- update

    def _update(self, step, start, params) -> ExecutionStepResult:
        contact_id = params.get("contact_id")
        if self._unresolved(contact_id):
            return self._blocked(step, start, "INVALID_PARAMETER", "No HubSpot contact to update (find the contact first).")
        prop = params.get("contact_property") or hubspot_settings().get("status_property")
        if self._unresolved(prop):
            return self._blocked(
                step, start, "NOT_CONFIGURED", "Choose which HubSpot contact property to update in Settings > Integrations."
            )
        value = params.get("property_value")
        if self._unresolved(value):
            value = hubspot_settings().get("status_value")
        if self._unresolved(value):
            return self._blocked(step, start, "INVALID_PARAMETER", f"No value to write to HubSpot property '{prop}'.")
        updated = self.client.update_contact(str(contact_id), {str(prop): str(value)})
        return self._result(
            step,
            start,
            ExecutionStepStatus.SUCCESS,
            parameters_used={"contact_id": str(contact_id), "contact_property": str(prop), "property_value": str(value)},
            output={
                "operation": "update_contact",
                "contact_id": str(contact_id),
                "property": str(prop),
                "value": str(value),
                "status": "COMPLETED",
            },
            affected_resources=[f"hubspot:contact:{contact_id}"],
            selection_reason=f"Updated HubSpot contact {updated.contact_id}",
        )

    # ----------------------------------------------------------------- note

    def _add_note(self, step, start, params) -> ExecutionStepResult:
        contact_id = params.get("contact_id")
        if self._unresolved(contact_id):
            return self._blocked(step, start, "INVALID_PARAMETER", "No HubSpot contact to add the note to (find the contact first).")
        body = params.get("note_body")
        if self._unresolved(body):
            subject = params.get("email_subject")
            body = f"WorkFlowOS processed the email '{subject}'." if subject else "Processed by WorkFlowOS."
        note = self.client.create_note(str(contact_id), str(body))
        note_id = str(note.get("id"))
        return self._result(
            step,
            start,
            ExecutionStepStatus.SUCCESS,
            parameters_used={"contact_id": str(contact_id)},
            output={"operation": "add_note", "contact_id": str(contact_id), "note_id": note_id, "note_body": str(body), "status": "COMPLETED"},
            affected_resources=[f"hubspot:note:{note_id}"],
            selection_reason=f"Added note {note_id} to HubSpot contact {contact_id}",
        )

    # ------------------------------------------------------------- dry run

    def _simulate(self, step, start, params) -> ExecutionStepResult:
        if step.action == "find_contact":
            query = params.get("contact_query") or params.get("customer_email") or "contact@example.com"
            if self._unresolved(query):
                query = "contact@example.com"
            record = {"contact_id": "hs-simulated", "customer_id": "hs-simulated", "name": "Simulated contact", "email": str(query)}
            output = {"operation": "find_contact", "query": str(query), "total_found": 1, "contact": record, "status": "SIMULATED"}
        elif step.action == "update_contact":
            output = {
                "operation": "update_contact",
                "contact_id": str(params.get("contact_id") or "hs-simulated"),
                "property": str(params.get("contact_property") or hubspot_settings().get("status_property") or "(not chosen yet)"),
                "status": "SIMULATED",
            }
        else:
            output = {"operation": "add_note", "contact_id": str(params.get("contact_id") or "hs-simulated"), "status": "SIMULATED"}
        return self._result(
            step,
            start,
            ExecutionStepStatus.SUCCESS,
            parameters_used={"dry_run": True},
            output=output,
            selection_reason="Dry run: no HubSpot calls were made.",
        )

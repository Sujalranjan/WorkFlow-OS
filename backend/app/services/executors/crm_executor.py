"""CRM API Executor (Phase 15B).

Implements real API-driven execution for CRM operations in WorkFlowOS:
- find_customer: Search or lookup customer record in CRM by email/name/ID.
- update_customer_record: Update lifecycle status, notes, invoice reference in CRM.
- get_customer: Retrieve single customer record.

ARCHITECTURAL BOUNDARY:
- Executes strictly via CrmApiClient -> CRM REST API -> CRM Database.
- Zero direct database / SQL execution inside the executor.
- Enforces dry-run shadow simulation with 0 external mutations.
"""

from datetime import datetime, timezone
import hashlib
import json
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
from app.services.crm_client import (
    CrmApiClient,
    CrmApiError,
    CrmClientError,
    CrmConnectionError,
    CrmCustomerNotFoundError,
)
from app.services.executors.base import BaseExecutor

logger = logging.getLogger(__name__)


class CrmApiExecutor(BaseExecutor):
    """Executor executing verified CRM operations via the CRM REST API client."""

    def __init__(self, client: Optional[CrmApiClient] = None) -> None:
        self.client = client or CrmApiClient()

    @property
    def name(self) -> str:
        return "CrmApiExecutor"

    @property
    def strategy(self) -> ExecutionStrategy:
        return ExecutionStrategy.API

    @property
    def capability(self) -> ExecutorCapability:
        return ExecutorCapability(
            executor_name=self.name,
            strategy_type=ExecutionStrategyType.API_INTEGRATION,
            supported_actions=["find_customer", "update_customer_record", "get_customer"],
            supported_targets=["CRM", "crm", "Demo CRM", "HubSpot", "Salesforce"],
            supported_risk_levels=[RiskLevel.LOW.value, RiskLevel.MEDIUM.value],
            implemented=True,
            requires_external_access=True,
            supports_verification=True,
            priority=1,
            description="CRM API executor for customer lookup and record updates via dedicated REST API.",
        )

    def supports(self, strategy: Any) -> bool:
        strat_str = str(strategy.value if hasattr(strategy, "value") else strategy).upper()
        return strat_str in (
            "API",
            "API_INTEGRATION",
            "APPLICATION_INTEGRATION",
            ExecutionStrategyType.API_INTEGRATION.value,
            ExecutionStrategyType.APPLICATION_INTEGRATION.value,
        )

    def _normalize_action(self, action: str) -> str:
        act = action.lower().strip().replace(" ", "_")
        if any(term in act for term in ["find", "search", "lookup"]):
            return "find_customer"
        if any(term in act for term in ["update", "modify", "patch", "edit"]):
            return "update_customer_record"
        if "get" in act:
            return "get_customer"
        return act

    def validate(self, step: PlannedStep, context: ExecutionContext) -> Tuple[bool, List[str]]:
        """Validates safety guardrails and required parameters before CRM execution."""
        errors: List[str] = []
        act_norm = self._normalize_action(step.action)

        if act_norm not in ("find_customer", "update_customer_record", "get_customer"):
            errors.append(f"CrmApiExecutor only supports 'find_customer' and 'update_customer_record'. Given: '{step.action}'")

        app_norm = step.application.lower().strip()
        if not any(t in app_norm for t in ["crm", "hubspot", "salesforce"]):
            errors.append(f"CrmApiExecutor only targets CRM systems. Given application: '{step.application}'")

        resolved_params = context.resolved_parameters or {}

        if act_norm == "find_customer":
            query = (
                resolved_params.get("query")
                or resolved_params.get("search_query")
                or resolved_params.get("email")
                or resolved_params.get("customer_email")
                or resolved_params.get("customer_id")
                or resolved_params.get("customer_name")
            )
            if not query or not str(query).strip():
                errors.append("Missing search parameter ('query', 'email', or 'customer_id') for find_customer")

        elif act_norm == "update_customer_record":
            cust_id = (
                resolved_params.get("customer_id")
                or resolved_params.get("id")
                or resolved_params.get("cust_id")
            )
            if not cust_id or not str(cust_id).strip():
                errors.append("Missing required 'customer_id' parameter for update_customer_record")

        return len(errors) == 0, errors

    def execute(self, step: PlannedStep, context: ExecutionContext) -> ExecutionStepResult:
        """Executes a single CRM operation via the CrmApiClient."""
        start_time = datetime.now(timezone.utc).isoformat()
        act_norm = self._normalize_action(step.action)
        resolved_params = context.resolved_parameters or {}

        # 1. Action Check
        if act_norm not in ("find_customer", "update_customer_record", "get_customer"):
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.BLOCKED,
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                blocked_reason="UNSUPPORTED_ACTION",
                error=f"CrmApiExecutor only supports 'find_customer' and 'update_customer_record'. Action '{step.action}' is not supported.",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )

        # 2. Dry-run Mode Check (0 real actions, 0 API calls)
        if context.dry_run:
            if act_norm == "find_customer":
                q_sim = str(
                    resolved_params.get("query")
                    or resolved_params.get("email")
                    or "simulated_customer"
                )
                return ExecutionStepResult(
                    planned_step_id=step.plan_step_id,
                    action_name=step.action,
                    target_application=step.application,
                    strategy=self.strategy,
                    executor_name=self.name,
                    status=ExecutionStepStatus.SUCCESS,
                    parameters_used={"query": q_sim, "dry_run": True},
                    output={
                        "operation": "find_customer",
                        "query": q_sim,
                        "total_found": 1,
                        "status": "SIMULATED",
                    },
                    affected_resources=[],
                    selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                    selection_reason="Simulated customer lookup via CRM API (dry run)",
                    start_time=start_time,
                    end_time=datetime.now(timezone.utc).isoformat(),
                )
            else:
                cid_sim = str(resolved_params.get("customer_id") or "cust-simulated")
                status_sim = str(resolved_params.get("status") or "PROCESSED")
                return ExecutionStepResult(
                    planned_step_id=step.plan_step_id,
                    action_name=step.action,
                    target_application=step.application,
                    strategy=self.strategy,
                    executor_name=self.name,
                    status=ExecutionStepStatus.SUCCESS,
                    parameters_used={"customer_id": cid_sim, "status": status_sim, "dry_run": True},
                    output={
                        "operation": "update_customer_record",
                        "customer_id": cid_sim,
                        "expected_status": status_sim,
                        "status": "SIMULATED",
                    },
                    affected_resources=[],
                    selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                    selection_reason="Simulated customer record update via CRM API (dry run)",
                    start_time=start_time,
                    end_time=datetime.now(timezone.utc).isoformat(),
                )

        # 3. Branch by Action
        if act_norm == "find_customer":
            return self._execute_find_customer(step, context, start_time)
        else:
            return self._execute_update_customer(step, context, start_time)

    def _execute_find_customer(
        self,
        step: PlannedStep,
        context: ExecutionContext,
        start_time: str,
    ) -> ExecutionStepResult:
        """Executes find_customer via the CRM API client."""
        resolved_params = context.resolved_parameters or {}
        query = (
            resolved_params.get("query")
            or resolved_params.get("search_query")
            or resolved_params.get("customer_name")
            or resolved_params.get("customer_id")
        )
        email = resolved_params.get("email") or resolved_params.get("customer_email")

        if not query and not email:
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.BLOCKED,
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                blocked_reason="INVALID_PARAMETER",
                error="Required search parameter ('query' or 'email') missing for find_customer.",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )

        try:
            search_res = self.client.find_customer(
                query=str(query).strip() if query else None,
                email=str(email).strip() if email else None,
            )

            cust_dumps = [c.model_dump() for c in search_res.customers]
            matched_customer = cust_dumps[0] if cust_dumps else None

            output = {
                "operation": "find_customer",
                "query": search_res.query,
                "total_found": search_res.total_found,
                "customers": cust_dumps,
                "matched_customer": matched_customer,
                "status": "COMPLETED",
            }

            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.SUCCESS,
                parameters_used={"query": search_res.query},
                output=output,
                affected_resources=[],
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                selection_reason=f"Found {search_res.total_found} customer record(s) via CRM API",
                fallback_used=False,
                policy_decision="ALLOWED",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )
        except CrmConnectionError as e:
            logger.error("CrmApiExecutor find_customer failed (connection): %s", str(e))
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.FAILED,
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                error=f"CRM API unavailable: {str(e)}",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as e:
            logger.error("CrmApiExecutor find_customer failed: %s", str(e))
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.FAILED,
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                error=f"CRM API find_customer error: {str(e)}",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )

    def _execute_update_customer(
        self,
        step: PlannedStep,
        context: ExecutionContext,
        start_time: str,
    ) -> ExecutionStepResult:
        """Executes update_customer_record via the CRM API client."""
        resolved_params = context.resolved_parameters or {}
        cust_id = (
            resolved_params.get("customer_id")
            or resolved_params.get("id")
            or resolved_params.get("cust_id")
        )

        if not cust_id or not str(cust_id).strip():
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.BLOCKED,
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                blocked_reason="INVALID_PARAMETER",
                error="Required parameter 'customer_id' missing for update_customer_record.",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )

        cid_clean = str(cust_id).strip()

        # Build update fields from parameters
        updates: Dict[str, Any] = {}
        for key in ["status", "notes", "invoice_reference", "recent_attachment_sha256", "company", "name"]:
            if key in resolved_params and resolved_params[key] is not None:
                updates[key] = resolved_params[key]

        # If no explicit status was given, set a sensible lifecycle status default
        if "status" not in updates:
            updates["status"] = "INVOICE_PROCESSED"

        try:
            updated_cust = self.client.update_customer(cid_clean, updates)
            state_json = json.dumps(updated_cust.model_dump(), sort_keys=True)
            state_sha256 = hashlib.sha256(state_json.encode("utf-8")).hexdigest()

            output = {
                "operation": "update_customer_record",
                "customer_id": cid_clean,
                "updated_fields": updates,
                "customer": updated_cust.model_dump(),
                "sha256": state_sha256,
                "status": "COMPLETED",
            }

            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.SUCCESS,
                parameters_used={"customer_id": cid_clean, **updates},
                output=output,
                affected_resources=[f"crm:customer:{cid_clean}"],
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                selection_reason=f"Updated customer record '{cid_clean}' via CRM API",
                fallback_used=False,
                policy_decision="ALLOWED",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )
        except CrmCustomerNotFoundError as e:
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.FAILED,
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                error=f"Customer record not found: {str(e)}",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )
        except CrmConnectionError as e:
            logger.error("CrmApiExecutor update_customer failed (connection): %s", str(e))
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.FAILED,
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                error=f"CRM API unavailable: {str(e)}",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as e:
            logger.error("CrmApiExecutor update_customer failed: %s", str(e))
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.FAILED,
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                error=f"CRM API update error: {str(e)}",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )

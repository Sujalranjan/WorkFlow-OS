"""Post-Execution Verification and Evidence Engine (Phase 9).

Orchestrates deterministic post-execution verification:
- Evaluates whether executed steps produced their expected state/results
- Strictly distinguishes EXECUTOR SUCCESS from VERIFIED SUCCESS
- Enforces sandbox isolation (zero external requests, zero arbitrary filesystem inspection)
- NO LLM involvement: 100% deterministic verification rules
- Aggregates step-level checks into workflow-level verification status
- Persists verification runs, atomic checks, and cryptographic integrity evidence in SQLite
- Updates execution audit record with verification outcome
"""

from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.models.execution import ExecutionAuditRecord, ExecutionStepResult, ExecutionStepStatus
from app.models.execution_plan import ExecutionPlan, PlannedStep
from app.models.verification import (
    VerificationCheck,
    VerificationResult,
    VerificationStatus,
    VerificationStrategyType,
)
from app.repositories.execution_plan_repository import ExecutionPlanRepository
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.verification_repository import VerificationRepository
from app.services.verifiers.registry import VerificationStrategyRegistry

logger = logging.getLogger(__name__)


class VerificationEngine:
    """Deterministic post-execution verification engine."""

    def __init__(
        self,
        exec_repo: Optional[ExecutionRepository] = None,
        plan_repo: Optional[ExecutionPlanRepository] = None,
        verif_repo: Optional[VerificationRepository] = None,
        strategy_registry: Optional[VerificationStrategyRegistry] = None,
    ) -> None:
        self.exec_repo = exec_repo or ExecutionRepository()
        self.plan_repo = plan_repo or ExecutionPlanRepository()
        self.verif_repo = verif_repo or VerificationRepository()
        self.strategy_registry = strategy_registry or VerificationStrategyRegistry()

    def verify_execution(
        self,
        execution_id: str,
        force_recheck: bool = False,
        custom_expectations: Optional[Dict[str, Any]] = None,
    ) -> VerificationResult:
        """Verifies all steps in an execution run deterministically.

        Idempotency:
        If force_recheck=False and custom_expectations is None, returns the latest
        existing VerificationResult without re-evaluating.
        If force_recheck=True, performs a fresh deterministic evaluation, records a new
        verification run, and updates the execution audit record.
        """
        # 1. Retrieve execution record
        exec_record = self.exec_repo.get_by_id(execution_id)
        if not exec_record:
            raise ValueError(f"Execution record '{execution_id}' not found.")

        # 2. Check existing verification (Idempotency)
        if not force_recheck and not custom_expectations:
            existing = self.verif_repo.get_latest_by_execution_id(execution_id)
            if existing:
                logger.info(f"Returning cached verification result '{existing.verification_run_id}' for execution '{execution_id}'")
                return existing

        # 3. Retrieve source execution plan
        plan = self.plan_repo.get_by_id(exec_record.execution_plan_id)
        if not plan:
            raise ValueError(f"Execution plan '{exec_record.execution_plan_id}' associated with execution not found.")

        start_time = datetime.now(timezone.utc).isoformat()
        verification_result = VerificationResult(
            execution_id=execution_id,
            workflow_id=exec_record.workflow_id,
            execution_plan_id=exec_record.execution_plan_id,
            overall_status=VerificationStatus.PENDING,
            checks=[],
            evidence={},
            started_at=start_time,
        )

        step_results_map: Dict[str, ExecutionStepResult] = {
            s.planned_step_id: s for s in exec_record.step_results
        }

        all_checks: List[VerificationCheck] = []
        consolidated_evidence: Dict[str, Any] = {}

        # 4. Step-by-Step Deterministic Verification Loop
        for step in plan.planned_steps:
            step_res = step_results_map.get(step.plan_step_id)

            # Case A: Step was not executed (SKIPPED, BLOCKED, CANCELLED)
            if not step_res or step_res.status in (ExecutionStepStatus.SKIPPED, ExecutionStepStatus.CANCELLED, ExecutionStepStatus.BLOCKED):
                status_val = step_res.status.value if step_res else "NOT_FOUND"
                all_checks.append(
                    VerificationCheck(
                        execution_id=execution_id,
                        execution_step_id=step_res.execution_step_id if step_res else f"missing-{step.plan_step_id}",
                        planned_step_id=step.plan_step_id,
                        check_type="step_execution_skipped",
                        strategy_type=VerificationStrategyType.NOT_APPLICABLE,
                        target=step.action,
                        expected_state="Step executed and verified",
                        actual_state=f"Step was not executed ({status_val})",
                        status=VerificationStatus.NOT_APPLICABLE,
                        reason=f"Verification not applicable: Step '{step.action}' was {status_val}",
                    )
                )
                continue

            # Case B: Step represents an external application (Gmail, CRM, Slack)
            app_lower = step.application.lower()
            if any(ext in app_lower for ext in ["gmail", "crm", "salesforce", "hubspot", "slack", "teams"]):
                # GmailApiExecutor (Phase 12/15A), CrmApiExecutor (Phase 15B), and SlackApiExecutor (Phase 15D) are supported.
                # Teams or Gmail mutations remain prohibited.
                act_norm = step.action.lower().strip().replace(" ", "_")
                is_gmail_allowed = ("gmail" in app_lower) and (
                    act_norm in ("search_email", "download_attachment", "download_email_attachment")
                    or (step_res and step_res.executor_name == "GmailApiExecutor")
                )
                is_crm_allowed = any(c in app_lower for c in ["crm", "hubspot", "salesforce"]) and (
                    act_norm in ("find_customer", "search_customer", "update_customer_record", "update_customer", "get_customer")
                    or (step_res and step_res.executor_name == "CrmApiExecutor")
                )
                is_slack_allowed = ("slack" in app_lower) and (
                    act_norm == "send_notification"
                    or (step_res and step_res.executor_name == "SlackApiExecutor")
                )
                if not (is_gmail_allowed or is_crm_allowed or is_slack_allowed):
                    all_checks.append(
                        VerificationCheck(
                            execution_id=execution_id,
                            execution_step_id=step_res.execution_step_id,
                            planned_step_id=step.plan_step_id,
                            check_type="external_verification_boundary",
                            strategy_type=VerificationStrategyType.NOT_APPLICABLE,
                            target=step.application,
                            expected_state="External state modification",
                            actual_state="External mutation prohibited",
                            status=VerificationStatus.NOT_APPLICABLE,
                            reason="External service verification (e.g. Teams, Gmail mutation) is explicitly prohibited",
                        )
                    )
                    continue

            # Case C: Executor reported failure
            if step_res.status == ExecutionStepStatus.FAILED:
                all_checks.append(
                    VerificationCheck(
                        execution_id=execution_id,
                        execution_step_id=step_res.execution_step_id,
                        planned_step_id=step.plan_step_id,
                        check_type="executor_outcome_check",
                        strategy_type=VerificationStrategyType.STATE_MATCH,
                        target=step.action,
                        expected_state="Executor success",
                        actual_state=f"Executor failed: {step_res.error}",
                        status=VerificationStatus.FAILED,
                        reason=f"Step execution failed prior to state verification: {step_res.error}",
                        evidence={"executor_error": step_res.error},
                    )
                )
                continue

            # Case D: Local execution step with executor SUCCESS
            strategies = self.strategy_registry.get_strategies_for_step(step, step_res)
            if not strategies:
                all_checks.append(
                    VerificationCheck(
                        execution_id=execution_id,
                        execution_step_id=step_res.execution_step_id,
                        planned_step_id=step.plan_step_id,
                        check_type="unsupported_verification_strategy",
                        strategy_type=VerificationStrategyType.NOT_APPLICABLE,
                        target=step.action,
                        expected_state=step.state_change.expected_after_state if step.state_change else "State updated",
                        actual_state="No local verification strategy found",
                        status=VerificationStatus.UNKNOWN,
                        reason=f"No registered verification strategy supports step '{step.action}' in application '{step.application}'",
                    )
                )
                continue

            # Run all supporting strategies
            for strategy in strategies:
                built_checks = strategy.build_checks(
                    execution_id=execution_id,
                    step=step,
                    step_result=step_res,
                    sandbox_root=exec_record.sandbox_root,
                    custom_expectations=custom_expectations,
                )
                for built_chk in built_checks:
                    # Deterministically evaluate the check
                    evaluated_chk = strategy.verify(built_chk, exec_record.sandbox_root)
                    all_checks.append(evaluated_chk)
                    if evaluated_chk.evidence:
                        consolidated_evidence[f"{step.plan_step_id}_{evaluated_chk.check_type}"] = evaluated_chk.evidence

        # 5. Aggregate Workflow-Level Verification Status
        # Rules:
        # - Any required check FAILED -> WORKFLOW FAILED (VERIFICATION_FAILED)
        # - Any required check UNKNOWN -> WORKFLOW UNKNOWN (EXECUTED_UNVERIFIED)
        # - All executable checks VERIFIED -> WORKFLOW VERIFIED
        # - All checks NOT_APPLICABLE -> WORKFLOW NOT_APPLICABLE
        verified_cnt = sum(1 for c in all_checks if c.status == VerificationStatus.VERIFIED)
        failed_cnt = sum(1 for c in all_checks if c.status == VerificationStatus.FAILED)
        unknown_cnt = sum(1 for c in all_checks if c.status == VerificationStatus.UNKNOWN)
        na_cnt = sum(1 for c in all_checks if c.status == VerificationStatus.NOT_APPLICABLE)

        overall_status = self.aggregate_status(all_checks)

        completed_time = datetime.now(timezone.utc).isoformat()
        verification_result.checks = all_checks
        verification_result.verified_count = verified_cnt
        verification_result.failed_count = failed_cnt
        verification_result.unknown_count = unknown_cnt
        verification_result.not_applicable_count = na_cnt
        verification_result.overall_status = overall_status
        verification_result.evidence = consolidated_evidence
        verification_result.completed_at = completed_time

        # 6. Save in SQLite VerificationRepository
        self.verif_repo.save(verification_result)

        # 7. Update ExecutionAuditRecord with verification metadata
        exec_record.verification_status = overall_status.value
        exec_record.verification_id = verification_result.verification_run_id
        self.exec_repo.save(exec_record)

        return verification_result

    @staticmethod
    def aggregate_status(checks: List[VerificationCheck]) -> VerificationStatus:
        """Determines workflow-level verification status by aggregating individual checks:
        - Any required check FAILED -> FAILED
        - No FAILED, Any UNKNOWN -> UNKNOWN
        - At least one VERIFIED and no FAILED/UNKNOWN -> VERIFIED
        - All NOT_APPLICABLE -> NOT_APPLICABLE
        """
        failed_cnt = sum(1 for c in checks if c.status == VerificationStatus.FAILED)
        unknown_cnt = sum(1 for c in checks if c.status == VerificationStatus.UNKNOWN)
        verified_cnt = sum(1 for c in checks if c.status == VerificationStatus.VERIFIED)

        if failed_cnt > 0:
            return VerificationStatus.FAILED
        elif unknown_cnt > 0:
            return VerificationStatus.UNKNOWN
        elif verified_cnt > 0:
            return VerificationStatus.VERIFIED
        else:
            return VerificationStatus.NOT_APPLICABLE

    # Alias for internal/test callers
    _aggregate_status = aggregate_status


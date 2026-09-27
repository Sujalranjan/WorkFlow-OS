"""Execution Engine for WorkFlowOS (Phase 8).

Responsible for:
1. Validating execution policy & human approval status.
2. Setting up isolated execution context with a dedicated sandbox directory.
3. Looking up executors via ExecutorRegistry.
4. Enforcing step-by-step fail-closed execution.
5. Idempotency and duplicate execution protection.
6. Recording complete ExecutionAuditRecord and updating repository.
"""

from datetime import datetime, timezone
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional
import uuid

from app.models.canonical import ApprovalState, CanonicalWorkflowSpec
from app.models.execution import (
    ExecutionAuditRecord,
    ExecutionContext,
    ExecutionMode,
    ExecutionOverallStatus,
    ExecutionStepResult,
    ExecutionStepStatus,
)
from app.models.execution_plan import ExecutionPlan, PlannedStep
from app.services.execution_policy import ExecutionPolicyEngine
from app.services.executors.registry import ExecutorRegistry
from app.services.strategy_selector import StrategySelector

if TYPE_CHECKING:
    from app.repositories.canonical_repository import CanonicalWorkflowRepository
    from app.repositories.execution_plan_repository import ExecutionPlanRepository
    from app.repositories.execution_repository import ExecutionRepository

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """Orchestrates controlled workflow execution with strict guardrails."""

    def __init__(
        self,
        canonical_repo: Optional["CanonicalWorkflowRepository"] = None,
        plan_repo: Optional["ExecutionPlanRepository"] = None,
        exec_repo: Optional["ExecutionRepository"] = None,
        registry: Optional[ExecutorRegistry] = None,
        policy_engine: Optional[ExecutionPolicyEngine] = None,
        strategy_selector: Optional[StrategySelector] = None,
        default_sandbox_base: Optional[str] = None,
    ) -> None:
        if canonical_repo is None:
            from app.repositories.canonical_repository import CanonicalWorkflowRepository
            canonical_repo = CanonicalWorkflowRepository()
        if plan_repo is None:
            from app.repositories.execution_plan_repository import ExecutionPlanRepository
            plan_repo = ExecutionPlanRepository()
        if exec_repo is None:
            from app.repositories.execution_repository import ExecutionRepository
            exec_repo = ExecutionRepository()

        self.canonical_repo = canonical_repo
        self.plan_repo = plan_repo
        self.exec_repo = exec_repo
        self.registry = registry or ExecutorRegistry()
        self.policy_engine = policy_engine or ExecutionPolicyEngine(registry=self.registry)
        self.strategy_selector = strategy_selector or StrategySelector(
            registry=self.registry,
            policy_engine=self.policy_engine,
        )
        self.default_sandbox_base = default_sandbox_base or os.getenv("WORKFLOWOS_SANDBOX_DIR", "workflowos_sandbox")

    def execute_plan(
        self,
        execution_plan_id: str,
        idempotency_key: Optional[str] = None,
        execution_mode: ExecutionMode = ExecutionMode.LIVE,
        custom_sandbox_dir: Optional[str] = None,
    ) -> ExecutionAuditRecord:
        """Executes an approved execution plan through controlled executors."""
        # 1. Idempotency Check
        if idempotency_key:
            existing = self.exec_repo.get_by_idempotency_key(idempotency_key)
            if existing:
                logger.info(f"Idempotent execution hit for key '{idempotency_key}': returning existing {existing.execution_id}")
                return existing

        # 2. Retrieve execution plan
        plan = self.plan_repo.get_by_id(execution_plan_id)
        if not plan:
            raise ValueError(f"Execution plan '{execution_plan_id}' not found.")

        # 3. Retrieve and verify CanonicalWorkflowSpec approval
        spec = self.canonical_repo.get_by_id(plan.source_workflow_id)
        if not spec:
            raise ValueError(f"Source canonical workflow specification '{plan.source_workflow_id}' not found.")

        # 4. Evaluate Plan-Level Execution Policy
        is_plan_valid, plan_violations = self.policy_engine.validate_plan_execution(spec, plan)
        if not is_plan_valid:
            raise ValueError(f"Execution rejected by security policy: {'; '.join(plan_violations)}")

        # 5. Initialize Execution Audit Record and Context
        execution_id = f"exec-{uuid.uuid4().hex[:12]}"
        start_time = datetime.now(timezone.utc).isoformat()

        # Build dedicated sandbox directory for this execution
        base_path = Path(self.default_sandbox_base).resolve()
        sandbox_path = (base_path / (custom_sandbox_dir or execution_id)).resolve()
        sandbox_path.mkdir(parents=True, exist_ok=True)

        audit_record = ExecutionAuditRecord(
            execution_id=execution_id,
            workflow_id=spec.workflow_id,
            workflow_version=spec.version,
            execution_plan_id=plan.execution_plan_id,
            approval_state=spec.approval_state.state.value,
            approved_by=spec.approval_state.reviewed_by,
            execution_mode=execution_mode,
            status=ExecutionOverallStatus.RUNNING,
            sandbox_root=str(sandbox_path),
            start_time=start_time,
            end_time=None,
            step_results=[],
            affected_resources=[],
            error_summary=None,
            idempotency_key=idempotency_key,
        )
        self.exec_repo.save(audit_record)

        # Build flattened dictionary of resolved parameters
        resolved_params_map: Dict[str, str] = {}
        for p in plan.resolved_parameters:
            if p.runtime_value is not None:
                resolved_params_map[p.semantic_name] = p.runtime_value
                resolved_params_map[p.source_parameter] = p.runtime_value

        context = ExecutionContext(
            execution_id=execution_id,
            workflow_id=spec.workflow_id,
            workflow_version=spec.version,
            execution_plan_id=plan.execution_plan_id,
            resolved_parameters=resolved_params_map,
            sandbox_root=str(sandbox_path),
            execution_mode=execution_mode,
            current_step_number=1,
            execution_start_time=start_time,
            dry_run=(execution_mode == ExecutionMode.DRY_RUN),
        )

        # 6. Step-by-Step Fail-Closed Execution Loop with Strategy Selection
        overall_status = ExecutionOverallStatus.COMPLETED
        error_summary: Optional[str] = None
        executed_steps: List[ExecutionStepResult] = []
        all_affected: List[str] = []

        for idx, step in enumerate(plan.planned_steps, 1):
            context.current_step_number = idx

            # Phase 10: Deterministic Strategy Selection & Capability Evaluation
            sel_res = self.strategy_selector.select_strategy(step, spec)

            # If no implemented executor or blocked by policy/risk
            if not sel_res.is_executable or sel_res.selected_executor is None:
                step_res = ExecutionStepResult(
                    planned_step_id=step.plan_step_id,
                    action_name=step.action,
                    target_application=step.application,
                    strategy=step.execution_strategy.strategy,
                    executor_name="StrategySelector",
                    status=ExecutionStepStatus.BLOCKED,
                    parameters_used=dict(step.resolved_parameters),
                    error=f"Blocked: {sel_res.blocked_reason or 'UNSUPPORTED_EXECUTION_STRATEGY'} - {sel_res.selection_reason}",
                    affected_resources=[],
                    start_time=datetime.now(timezone.utc).isoformat(),
                    end_time=datetime.now(timezone.utc).isoformat(),
                    selected_strategy=sel_res.selected_strategy.value if sel_res.selected_strategy else "NONE",
                    selection_reason=sel_res.selection_reason,
                    candidate_strategies=[c.strategy.value for c in sel_res.candidates_considered],
                    fallback_used=sel_res.fallback_used,
                    policy_decision="BLOCKED",
                    blocked_reason=sel_res.blocked_reason or "UNSUPPORTED_EXECUTION_STRATEGY",
                )
                executed_steps.append(step_res)
                overall_status = ExecutionOverallStatus.BLOCKED
                error_summary = f"Execution blocked at step {idx} ('{step.action}'): {sel_res.selection_reason}"

                # Mark remaining steps as SKIPPED
                for remaining in plan.planned_steps[idx:]:
                    executed_steps.append(
                        ExecutionStepResult(
                            planned_step_id=remaining.plan_step_id,
                            action_name=remaining.action,
                            target_application=remaining.application,
                            strategy=remaining.execution_strategy.strategy,
                            executor_name="ExecutionEngine",
                            status=ExecutionStepStatus.SKIPPED,
                            parameters_used={},
                            error="Skipped due to preceding step policy block",
                            affected_resources=[],
                            start_time=datetime.now(timezone.utc).isoformat(),
                            end_time=datetime.now(timezone.utc).isoformat(),
                            selected_strategy="NONE",
                            selection_reason="Preceding step was blocked",
                            candidate_strategies=[],
                            fallback_used=False,
                            policy_decision="BLOCKED",
                            blocked_reason="PRECEDING_STEP_BLOCKED",
                        )
                    )
                break

            # Find matching implemented executor
            executor = self.registry.get_by_name(sel_res.selected_executor)
            if not executor or not executor.capability.implemented:
                raise RuntimeError(
                    f"Selected executor '{sel_res.selected_executor}' for strategy "
                    f"'{sel_res.selected_strategy.value}' is not implemented."
                )

            # Resolve template placeholders and populate unset parameters using context
            effective_step_params = dict(step.resolved_parameters or {})
            for k, v in list(effective_step_params.items()):
                if (v is None or v == "") and k in context.resolved_parameters and context.resolved_parameters[k] is not None:
                    effective_step_params[k] = context.resolved_parameters[k]
                    v = effective_step_params[k]
                if isinstance(v, str):
                    val_str = v
                    for ctx_k, ctx_v in context.resolved_parameters.items():
                        if ctx_v is not None and not isinstance(ctx_v, (dict, list)):
                            val_str = val_str.replace(f"{{{{{ctx_k}}}}}", str(ctx_v))
                            val_str = val_str.replace(f"{{{ctx_k}}}", str(ctx_v))
                    effective_step_params[k] = val_str
            for ctx_k, ctx_v in context.resolved_parameters.items():
                if ctx_k not in effective_step_params or effective_step_params[ctx_k] is None:
                    effective_step_params[ctx_k] = ctx_v
            step.resolved_parameters = effective_step_params

            # Validate step against executor guardrails
            step_context = context.model_copy(update={"resolved_parameters": effective_step_params})
            is_valid, validation_errors = executor.validate(step, step_context)
            if not is_valid:
                step_res = ExecutionStepResult(
                    planned_step_id=step.plan_step_id,
                    action_name=step.action,
                    target_application=step.application,
                    strategy=step.execution_strategy.strategy,
                    executor_name=executor.name,
                    status=ExecutionStepStatus.BLOCKED,
                    parameters_used=dict(step.resolved_parameters),
                    error=f"Executor guardrail validation failed: {'; '.join(validation_errors)}",
                    affected_resources=[],
                    start_time=datetime.now(timezone.utc).isoformat(),
                    end_time=datetime.now(timezone.utc).isoformat(),
                    selected_strategy=sel_res.selected_strategy.value if sel_res.selected_strategy else None,
                    selection_reason=sel_res.selection_reason,
                    candidate_strategies=[c.strategy.value for c in sel_res.candidates_considered],
                    fallback_used=sel_res.fallback_used,
                    policy_decision="BLOCKED",
                    blocked_reason="EXECUTOR_VALIDATION_FAILED",
                )
                executed_steps.append(step_res)
                overall_status = ExecutionOverallStatus.BLOCKED
                error_summary = f"Step {idx} ('{step.action}') validation failed: {'; '.join(validation_errors)}"
                break

            # Execute step with selected executor
            step_result = executor.execute(step, step_context)
            step_result.selected_strategy = sel_res.selected_strategy.value if sel_res.selected_strategy else None
            step_result.selection_reason = sel_res.selection_reason
            step_result.candidate_strategies = [c.strategy.value for c in sel_res.candidates_considered]
            step_result.fallback_used = sel_res.fallback_used
            step_result.policy_decision = "ALLOWED"

            executed_steps.append(step_result)

            if step_result.affected_resources:
                all_affected.extend(step_result.affected_resources)

            # Phase 16: Propagate successful step outputs to context.resolved_parameters for downstream steps
            if step_result.status == ExecutionStepStatus.SUCCESS and step_result.output:
                act_norm = step.action.lower().strip().replace(" ", "_")
                # 1. Namespaced outputs
                for out_k, out_v in step_result.output.items():
                    if out_v is not None:
                        context.resolved_parameters[f"{step.plan_step_id}.{out_k}"] = out_v
                        context.resolved_parameters[f"{act_norm}.{out_k}"] = out_v

                # 2. Domain-specific parameter bindings
                if act_norm == "search_email":
                    messages = step_result.output.get("messages") or []
                    if messages and isinstance(messages, list) and isinstance(messages[0], dict):
                        first_msg = messages[0]
                        msg_id = first_msg.get("message_id") or first_msg.get("id") or first_msg.get("msg_id")
                        if msg_id:
                            context.resolved_parameters["message_id"] = msg_id
                            context.resolved_parameters["msg_id"] = msg_id
                        if first_msg.get("subject"):
                            context.resolved_parameters["email_subject"] = first_msg.get("subject")
                        sender = first_msg.get("sender") or first_msg.get("sender_email") or first_msg.get("from")
                        if sender:
                            context.resolved_parameters["email"] = sender
                            context.resolved_parameters["customer_email"] = sender
                        attachments = first_msg.get("attachments") or []
                        if attachments and isinstance(attachments, list) and isinstance(attachments[0], dict):
                            context.resolved_parameters["attachment_id"] = attachments[0].get("id") or attachments[0].get("attachment_id")
                            context.resolved_parameters["filename"] = attachments[0].get("filename")

                elif act_norm in ("download_attachment", "download_email_attachment"):
                    saved_p = step_result.output.get("saved_path") or step_result.output.get("destination_path")
                    if saved_p:
                        context.resolved_parameters["downloaded_file"] = saved_p
                        context.resolved_parameters["attachment_path"] = saved_p
                    if step_result.output.get("filename"):
                        context.resolved_parameters["filename"] = step_result.output.get("filename")
                    if step_result.output.get("sha256"):
                        context.resolved_parameters["attachment_sha256"] = step_result.output.get("sha256")

                elif act_norm in ("find_customer", "get_customer"):
                    cust = step_result.output.get("customer")
                    if cust and isinstance(cust, dict):
                        context.resolved_parameters["customer_id"] = cust.get("customer_id")
                        context.resolved_parameters["customer_name"] = cust.get("name")
                        context.resolved_parameters["customer_company"] = cust.get("company")
                        context.resolved_parameters["customer_status"] = cust.get("status")
                        if cust.get("email"):
                            context.resolved_parameters["customer_email"] = cust.get("email")

                elif act_norm in ("update_customer_record", "update_customer"):
                    cust = step_result.output.get("customer")
                    if cust and isinstance(cust, dict):
                        context.resolved_parameters["customer_status"] = cust.get("status")
                    context.resolved_parameters["crm_updated"] = True

                elif act_norm in ("send_notification", "notify"):
                    if step_result.output.get("ts"):
                        context.resolved_parameters["slack_ts"] = step_result.output.get("ts")

            # Fail-closed check
            if step_result.status == ExecutionStepStatus.FAILED:
                overall_status = ExecutionOverallStatus.FAILED
                error_summary = f"Step {idx} ('{step.action}') failed: {step_result.error}"

                # Mark remaining steps as SKIPPED
                for remaining in plan.planned_steps[idx:]:
                    executed_steps.append(
                        ExecutionStepResult(
                            planned_step_id=remaining.plan_step_id,
                            action_name=remaining.action,
                            target_application=remaining.application,
                            strategy=remaining.execution_strategy.strategy,
                            executor_name="ExecutionEngine",
                            status=ExecutionStepStatus.SKIPPED,
                            parameters_used={},
                            error="Skipped due to preceding step failure",
                            affected_resources=[],
                            start_time=datetime.now(timezone.utc).isoformat(),
                            end_time=datetime.now(timezone.utc).isoformat(),
                        )
                    )
                break

        # 7. Finalize and Persist Execution Audit Record


        audit_record.status = overall_status
        audit_record.step_results = executed_steps
        audit_record.affected_resources = all_affected
        audit_record.error_summary = error_summary
        audit_record.end_time = datetime.now(timezone.utc).isoformat()

        self.exec_repo.save(audit_record)
        return audit_record

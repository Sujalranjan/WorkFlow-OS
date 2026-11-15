"""Execution Engine for WorkFlowOS.

Responsible for:
1. Validating execution policy & human approval status.
2. Setting up isolated execution context with a dedicated sandbox directory.
3. Looking up executors via ExecutorRegistry.
4. Enforcing step-by-step fail-closed execution.
5. Idempotency and duplicate execution protection.
6. Recording complete ExecutionAuditRecord and updating repository.
"""

from datetime import datetime, timezone
from email.utils import parseaddr
import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional
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
        executed_by: str = "workflowos-engine",
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
            executed_by=executed_by,
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

        return self._run_steps(plan, spec, context, audit_record, start_index=0)

    def resume_execution(
        self,
        execution_id: str,
        inputs: Dict[str, str],
        resumed_by: str = "operator",
    ) -> ExecutionAuditRecord:
        """Continue a NEEDS_INPUT execution from its paused step with the values a person supplied.

        Approval and plan-level policy are re-checked, so a workflow that was rejected or
        changed while the run was paused cannot continue.
        """
        record = self.exec_repo.get_by_id(execution_id)
        if not record:
            raise ValueError(f"Execution '{execution_id}' not found.")
        if record.status != ExecutionOverallStatus.NEEDS_INPUT or record.paused_step_index is None:
            raise ValueError(
                f"Execution '{execution_id}' is {record.status.value}; only NEEDS_INPUT executions can be resumed."
            )
        clean_inputs = {k: str(v).strip() for k, v in (inputs or {}).items() if v is not None and str(v).strip()}
        if not clean_inputs:
            raise ValueError("Resume requires at least one non-empty input value.")

        plan = self.plan_repo.get_by_id(record.execution_plan_id)
        if not plan:
            raise ValueError(f"Execution plan '{record.execution_plan_id}' not found.")
        spec = self.canonical_repo.get_by_id(plan.source_workflow_id)
        if not spec:
            raise ValueError(f"Source canonical workflow specification '{plan.source_workflow_id}' not found.")
        is_plan_valid, plan_violations = self.policy_engine.validate_plan_execution(spec, plan)
        if not is_plan_valid:
            raise ValueError(f"Resume rejected by security policy: {'; '.join(plan_violations)}")

        paused_step = plan.planned_steps[record.paused_step_index]
        allowed = set(self._intervention_parameters(record, paused_step.plan_step_id))
        unexpected = sorted(set(clean_inputs) - allowed)
        if unexpected:
            raise ValueError(
                f"Inputs {unexpected} are not accepted by step '{paused_step.action}'. Allowed: {sorted(allowed)}"
            )

        context = ExecutionContext(
            execution_id=record.execution_id,
            workflow_id=record.workflow_id,
            workflow_version=record.workflow_version,
            execution_plan_id=record.execution_plan_id,
            resolved_parameters={**record.runtime_context, **clean_inputs},
            sandbox_root=record.sandbox_root,
            execution_mode=record.execution_mode,
            current_step_number=record.paused_step_index + 1,
            execution_start_time=record.start_time,
            dry_run=(record.execution_mode == ExecutionMode.DRY_RUN),
        )
        # The person's answer replaces the paused step's own binding (e.g. the {customer_email} template).
        paused_step.resolved_parameters = {**(paused_step.resolved_parameters or {}), **clean_inputs}

        record.status = ExecutionOverallStatus.RUNNING
        record.error_summary = None
        record.end_time = None
        self.exec_repo.save(record)
        logger.info("Resuming execution %s at step %s (by %s)", execution_id, record.paused_step_index + 1, resumed_by)
        return self._run_steps(plan, spec, context, record, start_index=record.paused_step_index)

    @staticmethod
    def _intervention_parameters(record: ExecutionAuditRecord, plan_step_id: str) -> List[str]:
        """Inputs the paused step declared it accepts (from its NEEDS_INPUT intervention)."""
        for res in reversed(record.step_results):
            if res.planned_step_id == plan_step_id and res.status == ExecutionStepStatus.NEEDS_INPUT:
                return list((res.intervention or {}).get("accepted_inputs") or [])
        return []

    def _run_steps(
        self,
        plan: ExecutionPlan,
        spec: CanonicalWorkflowSpec,
        context: ExecutionContext,
        audit_record: ExecutionAuditRecord,
        start_index: int,
    ) -> ExecutionAuditRecord:
        """Step-by-step fail-closed execution loop with strategy selection, from `start_index` (0-based)."""
        overall_status = ExecutionOverallStatus.COMPLETED
        error_summary: Optional[str] = None
        executed_steps: List[ExecutionStepResult] = list(audit_record.step_results)
        all_affected: List[str] = list(audit_record.affected_resources)
        paused_step_index: Optional[int] = None

        for idx, step in enumerate(plan.planned_steps, 1):
            if idx - 1 < start_index:
                continue
            context.current_step_number = idx

            # Deterministic Strategy Selection & Capability Evaluation
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

            # Propagate successful step outputs to context.resolved_parameters for downstream steps
            if step_result.status == ExecutionStepStatus.SUCCESS and step_result.output:
                act_norm = step.action.lower().strip().replace(" ", "_")
                # 1. Namespaced outputs
                for out_k, out_v in step_result.output.items():
                    if out_v is not None:
                        context.resolved_parameters[f"{step.plan_step_id}.{out_k}"] = out_v
                        context.resolved_parameters[f"{act_norm}.{out_k}"] = out_v

                # 2. Domain-specific parameter bindings
                if act_norm == "search_email":
                    # Prioritize deterministically selected message, falling back to messages[0]
                    sel_msg = step_result.output.get("selected_message")
                    if not sel_msg:
                        messages = step_result.output.get("messages") or []
                        if messages and isinstance(messages, list) and isinstance(messages[0], dict):
                            sel_msg = messages[0]

                    if sel_msg and isinstance(sel_msg, dict):
                        msg_id = sel_msg.get("message_id") or sel_msg.get("id") or sel_msg.get("msg_id")
                        if msg_id:
                            context.resolved_parameters["message_id"] = msg_id
                            context.resolved_parameters["msg_id"] = msg_id
                        if sel_msg.get("subject"):
                            context.resolved_parameters["email_subject"] = sel_msg.get("subject")
                        sender = sel_msg.get("sender") or sel_msg.get("sender_email") or sel_msg.get("from")
                        if sender:
                            # 'Rahul Sharma <rahul@example.com>' -> 'rahul@example.com'
                            sender_addr = parseaddr(str(sender))[1] or str(sender)
                            context.resolved_parameters["email"] = sender_addr
                            context.resolved_parameters["customer_email"] = sender_addr
                        attachments = sel_msg.get("attachments") or []
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

            # Human intervention: the step could not decide safely on its own (e.g. no CRM customer,
            # or several). Pause here; remaining steps are neither run nor skipped, so the run can
            # resume from this step once a person supplies the missing input.
            if step_result.status == ExecutionStepStatus.NEEDS_INPUT:
                overall_status = ExecutionOverallStatus.NEEDS_INPUT
                paused_step_index = idx - 1
                reason = (step_result.intervention or {}).get("reason") or step_result.error
                error_summary = f"Step {idx} ('{step.action}') needs input: {reason}"
                break

            # Fail-closed check: a failed OR blocked step (e.g. missing auth) stops the run, so later
            # steps never act on outputs that were not produced.
            if step_result.status in (ExecutionStepStatus.FAILED, ExecutionStepStatus.BLOCKED):
                if step_result.status == ExecutionStepStatus.FAILED:
                    overall_status = ExecutionOverallStatus.FAILED
                    error_summary = f"Step {idx} ('{step.action}') failed: {step_result.error}"
                else:
                    overall_status = ExecutionOverallStatus.BLOCKED
                    error_summary = f"Step {idx} ('{step.action}') blocked: {step_result.blocked_reason} - {step_result.error}"

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
                            error=f"Skipped due to preceding step {step_result.status.value.lower()}",
                            affected_resources=[],
                            start_time=datetime.now(timezone.utc).isoformat(),
                            end_time=datetime.now(timezone.utc).isoformat(),
                        )
                    )
                break

        # 7. Finalize and persist the execution audit record
        audit_record.status = overall_status
        audit_record.step_results = executed_steps
        audit_record.affected_resources = all_affected
        audit_record.error_summary = error_summary
        audit_record.paused_step_index = paused_step_index
        audit_record.runtime_context = _json_safe(context.resolved_parameters)
        audit_record.end_time = (
            None if overall_status == ExecutionOverallStatus.NEEDS_INPUT else datetime.now(timezone.utc).isoformat()
        )

        self.exec_repo.save(audit_record)
        return audit_record


def _json_safe(params: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only JSON-serializable context values so the paused context can be persisted."""
    safe: Dict[str, Any] = {}
    for k, v in params.items():
        try:
            json.dumps(v)
        except (TypeError, ValueError):
            continue
        safe[k] = v
    return safe

from datetime import datetime, timezone
import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.models.execution import (
    ExecutePlanRequest,
    ExecutionAuditRecord,
    ExecutionListResponse,
    ExecutionMode,
    ExecutionOverallStatus,
    ExecutionStepStatus,
)
from app.models.execution_plan import (
    CreateExecutionPlanRequest,
    DryRunResult,
    ExecutionPlan,
    ExecutionPlanListResponse,
)
from app.models.verification import (
    VerificationCheck,
    VerificationListResponse,
    VerificationResult,
    VerificationStatus,
    VerifyExecutionRequest,
)


class StepStrategySummary(BaseModel):
    step_id: str
    action: str
    target: str
    selected_strategy: Optional[str] = None
    is_supported: bool = False
    selection_reason: str
    candidate_strategies: List[str] = Field(default_factory=list)
    fallback_used: bool = False
    policy_decision: str = "ALLOWED"
    blocked_reason: Optional[str] = None


class ExecutionStrategyResponse(BaseModel):
    execution_id: str
    workflow_id: str
    execution_plan_id: str
    steps: List[StepStrategySummary] = Field(default_factory=list)


class PlanStrategyResponse(BaseModel):
    execution_plan_id: str
    source_workflow_id: str
    steps: List[StepStrategySummary] = Field(default_factory=list)

from app.repositories.canonical_repository import CanonicalWorkflowRepository
from app.repositories.execution_plan_repository import ExecutionPlanRepository
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.verification_repository import VerificationRepository
from app.services.dry_run_simulator import DryRunSimulator
from app.services.execution_engine import ExecutionEngine
from app.services.execution_planner import ExecutionPlanner
from app.services.verification_engine import VerificationEngine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workflows", tags=["execution-planning"])

# Shared repositories and services
spec_repo = CanonicalWorkflowRepository()
plan_repo = ExecutionPlanRepository()
planner = ExecutionPlanner()
simulator = DryRunSimulator()


@router.post(
    "/specifications/{workflow_id}/execution-plan",
    response_model=ExecutionPlan,
    status_code=status.HTTP_201_CREATED,
    summary="Create an execution plan for an approved canonical workflow specification",
)
async def create_execution_plan(
    workflow_id: str,
    request: Optional[CreateExecutionPlanRequest] = None,
) -> ExecutionPlan:
    """Creates a deterministic execution plan from an APPROVED CanonicalWorkflowSpec.

    If the workflow is not approved, rejects with HTTP 400.
    """
    runtime_params = request.runtime_parameters if request else {}

    spec = spec_repo.get_by_id(workflow_id)
    if not spec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Canonical workflow specification '{workflow_id}' not found",
        )

    try:
        plan = planner.create_execution_plan(
            spec=spec,
            runtime_inputs=runtime_params,
        )
        plan_repo.save(plan)
        return plan
    except ValueError as e:
        err_msg = str(e)
        logger.warning(f"Failed to create execution plan for workflow {workflow_id}: {err_msg}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err_msg)
    except Exception as e:
        logger.exception(f"Unexpected error creating execution plan: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal error creating execution plan: {str(e)}",
        )


@router.get(
    "/execution-plans",
    response_model=ExecutionPlanListResponse,
    summary="List all execution plans",
)
async def list_execution_plans(
    workflow_id: Optional[str] = None,
    limit: int = 100,
) -> ExecutionPlanListResponse:
    """Lists saved execution plans, optionally filtered by workflow ID."""
    if workflow_id:
        single_plan = plan_repo.get_by_workflow_id(workflow_id)
        plans = [single_plan] if single_plan else []
    else:
        plans = plan_repo.list_all(limit=limit)
    return ExecutionPlanListResponse(plans=plans, total_count=len(plans))


@router.get(
    "/execution-plans/{execution_plan_id}",
    response_model=ExecutionPlan,
    summary="Retrieve an execution plan by ID",
)
async def get_execution_plan(execution_plan_id: str) -> ExecutionPlan:
    """Retrieves an execution plan by its unique ID."""
    plan = plan_repo.get_by_id(execution_plan_id)
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution plan '{execution_plan_id}' not found",
        )
    return plan


@router.post(
    "/execution-plans/{execution_plan_id}/dry-run",
    response_model=DryRunResult,
    summary="Execute dry-run simulation of an execution plan without real actions",
)
async def run_dry_run(execution_plan_id: str) -> DryRunResult:
    """Runs a deterministic dry-run / shadow simulation of the execution plan.

    Guarantees that ZERO real desktop, OS, or external actions are performed.
    """
    plan = plan_repo.get_by_id(execution_plan_id)
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution plan '{execution_plan_id}' not found",
        )

    dry_run_result = simulator.simulate(plan)
    plan_repo.update_dry_run_result(execution_plan_id, dry_run_result)
    return dry_run_result


# -------------------------------------------------------------------------
# Phase 8: Execution Engine Endpoints
# -------------------------------------------------------------------------

exec_repo = ExecutionRepository()
execution_engine = ExecutionEngine(
    canonical_repo=spec_repo,
    plan_repo=plan_repo,
    exec_repo=exec_repo,
)


@router.post(
    "/execution-plans/{execution_plan_id}/execute",
    response_model=ExecutionAuditRecord,
    status_code=status.HTTP_200_OK,
    summary="Execute an approved execution plan through controlled local executor",
)
async def execute_plan(
    execution_plan_id: str,
    request: Optional[ExecutePlanRequest] = None,
) -> ExecutionAuditRecord:
    """Executes an approved ExecutionPlan with strict backend security guardrails.

    Requires source CanonicalWorkflowSpec to be in ApprovalState.APPROVED.
    Rejects any unapproved workflows or unsupported external mutations.
    """
    idempotency_key = request.idempotency_key if request else None
    execution_mode = request.execution_mode if request else ExecutionMode.LIVE
    custom_sandbox = request.sandbox_dir if request else None

    try:
        record = execution_engine.execute_plan(
            execution_plan_id=execution_plan_id,
            idempotency_key=idempotency_key,
            execution_mode=execution_mode,
            custom_sandbox_dir=custom_sandbox,
        )
        return record
    except ValueError as e:
        err_msg = str(e)
        logger.warning(f"Execution validation rejected: {err_msg}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err_msg)
    except Exception as e:
        logger.exception(f"Unexpected error executing plan: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Execution error: {str(e)}",
        )


@router.get(
    "/executions",
    response_model=ExecutionListResponse,
    summary="List all workflow execution records",
)
async def list_executions(
    workflow_id: Optional[str] = None,
    limit: int = 50,
) -> ExecutionListResponse:
    """Lists execution audit records."""
    records = exec_repo.list_all(workflow_id=workflow_id, limit=limit)
    return ExecutionListResponse(total_count=len(records), executions=records)


@router.get(
    "/executions/{execution_id}",
    response_model=ExecutionAuditRecord,
    summary="Retrieve an execution audit record by ID",
)
async def get_execution(execution_id: str) -> ExecutionAuditRecord:
    """Retrieves a specific execution record."""
    record = exec_repo.get_by_id(execution_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution record '{execution_id}' not found",
        )
    return record


@router.post(
    "/executions/{execution_id}/cancel",
    response_model=ExecutionAuditRecord,
    summary="Cancel an active or pending workflow execution",
)
async def cancel_execution(execution_id: str) -> ExecutionAuditRecord:
    """Cancels an execution record if it is running or pending."""
    record = exec_repo.get_by_id(execution_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution record '{execution_id}' not found",
        )

    if record.status in (ExecutionOverallStatus.RUNNING, ExecutionOverallStatus.PENDING):
        record.status = ExecutionOverallStatus.CANCELLED
        record.end_time = datetime.now(timezone.utc).isoformat()
        record.error_summary = "Execution cancelled by user or operator."
        exec_repo.save(record)

    return record


@router.get(
    "/executions/{execution_id}/strategy",
    response_model=ExecutionStrategyResponse,
    summary="Retrieve strategy selection breakdown for an execution run",
)
async def get_execution_strategy(execution_id: str) -> ExecutionStrategyResponse:
    """Retrieves deterministic strategy selection details for each step in an execution."""
    record = exec_repo.get_by_id(execution_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution record '{execution_id}' not found",
        )
    steps: List[StepStrategySummary] = []
    for s in record.step_results:
        is_supp = (s.status != ExecutionStepStatus.BLOCKED and s.selected_strategy not in (None, "NONE"))
        steps.append(
            StepStrategySummary(
                step_id=s.planned_step_id,
                action=s.action_name,
                target=s.target_application,
                selected_strategy=s.selected_strategy,
                is_supported=is_supp,
                selection_reason=s.selection_reason or (s.error if not is_supp else "Executed successfully"),
                candidate_strategies=s.candidate_strategies,
                fallback_used=s.fallback_used,
                policy_decision=s.policy_decision or ("BLOCKED" if not is_supp else "ALLOWED"),
                blocked_reason=s.blocked_reason,
            )
        )
    return ExecutionStrategyResponse(
        execution_id=record.execution_id,
        workflow_id=record.workflow_id,
        execution_plan_id=record.execution_plan_id,
        steps=steps,
    )


@router.get(
    "/execution-plans/{execution_plan_id}/strategy",
    response_model=PlanStrategyResponse,
    summary="Retrieve strategy selection breakdown for an execution plan",
)
async def get_plan_strategy(execution_plan_id: str) -> PlanStrategyResponse:
    """Retrieves deterministic strategy selection details for each step in an execution plan."""
    plan = plan_repo.get_by_id(execution_plan_id)
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution plan '{execution_plan_id}' not found",
        )
    steps: List[StepStrategySummary] = []
    for s in plan.planned_steps:
        strat = s.execution_strategy
        is_supp = strat.executor_implemented and (strat.blocked_reason is None)
        steps.append(
            StepStrategySummary(
                step_id=s.plan_step_id,
                action=s.action,
                target=s.application,
                selected_strategy=strat.canonical_strategy if is_supp else "NONE",
                is_supported=is_supp,
                selection_reason=strat.selection_reason or "Deterministic evaluation completed",
                candidate_strategies=strat.available_strategies_considered,
                fallback_used=strat.fallback_used,
                policy_decision=strat.policy_decision,
                blocked_reason=strat.blocked_reason,
            )
        )
    return PlanStrategyResponse(
        execution_plan_id=plan.execution_plan_id,
        source_workflow_id=plan.source_workflow_id,
        steps=steps,
    )



# -------------------------------------------------------------------------
# Phase 9: Post-Execution Verification Endpoints
# -------------------------------------------------------------------------

verif_repo = VerificationRepository()
verification_engine = VerificationEngine(
    exec_repo=exec_repo,
    plan_repo=plan_repo,
    verif_repo=verif_repo,
)


@router.post(
    "/executions/{execution_id}/verify",
    response_model=VerificationResult,
    status_code=status.HTTP_200_OK,
    summary="Run deterministic post-execution verification on an execution run",
)
async def verify_execution(
    execution_id: str,
    request: Optional[VerifyExecutionRequest] = None,
) -> VerificationResult:
    """Evaluates whether executed steps produced their expected state/result.

    Strictly distinguishes EXECUTOR SUCCESS from VERIFIED SUCCESS.
    Guarantees zero external mutations.
    """
    force_recheck = request.force_recheck if request else False
    custom_expectations = request.custom_expectations if request else None

    try:
        result = verification_engine.verify_execution(
            execution_id=execution_id,
            force_recheck=force_recheck,
            custom_expectations=custom_expectations,
        )
        return result
    except ValueError as e:
        err_msg = str(e)
        logger.warning(f"Verification rejected: {err_msg}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err_msg)
    except Exception as e:
        logger.exception(f"Unexpected error running verification: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Verification error: {str(e)}",
        )


@router.get(
    "/executions/{execution_id}/verification",
    response_model=VerificationResult,
    summary="Retrieve latest verification result for an execution run",
)
async def get_latest_verification(execution_id: str) -> VerificationResult:
    """Retrieves the latest verification result for an execution run."""
    result = verif_repo.get_latest_by_execution_id(execution_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No verification results found for execution '{execution_id}'",
        )
    return result


@router.get(
    "/verifications/{verification_run_id}",
    response_model=VerificationResult,
    summary="Retrieve a specific verification run by ID",
)
async def get_verification(verification_run_id: str) -> VerificationResult:
    """Retrieves a specific verification result by its run ID."""
    result = verif_repo.get_by_id(verification_run_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Verification run '{verification_run_id}' not found",
        )
    return result


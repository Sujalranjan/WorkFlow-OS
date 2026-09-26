"""API Integration Tests for Phase 11: Workflow Learning & Reliability Endpoints.

Tests:
- GET /api/workflows/{workflow_id}/learning
- GET /api/workflows/{workflow_id}/learning/events
- POST /api/workflows/{workflow_id}/learning/refresh
"""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models.canonical import (
    ApprovalMetadata,
    ApprovalState,
    CanonicalStep,
    CanonicalWorkflowSpec,
    RiskAssessment,
    RiskCategory,
    RiskLevel,
    StepRisk,
)
from app.models.dna import DNAEvidence, WorkflowBoundaries
from app.models.execution import (
    ExecutionAuditRecord,
    ExecutionOverallStatus,
    ExecutionStepResult,
    ExecutionStepStatus,
)
from app.models.execution_plan import ExecutionStrategy
from app.models.verification import (
    VerificationCheck,
    VerificationResult,
    VerificationStatus,
    VerificationStrategyType,
)
from app.repositories.canonical_repository import CanonicalWorkflowRepository
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.learning_repository import LearningRepository
from app.repositories.verification_repository import VerificationRepository


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def test_get_learning_profile_empty(client):
    res = client.get("/api/workflows/wf-empty-api-test/learning")
    assert res.status_code == 200
    data = res.json()
    assert data["workflow_id"] == "wf-empty-api-test"
    assert data["total_executions"] == 0
    assert data["reliability_rate"] == 0.0


def test_refresh_learning_profile(client):
    workflow_id = "wf-refresh-api-test"

    # Seed execution
    exec_repo = ExecutionRepository()
    verif_repo = VerificationRepository()

    exec_id = "exec-api-refresh-1"
    step_res = ExecutionStepResult(
        planned_step_id="step-api-1",
        action_name="save_file",
        target_application="File System",
        strategy=ExecutionStrategy.CONTROLLED_LOCAL,
        executor_name="ControlledLocalExecutor",
        status=ExecutionStepStatus.SUCCESS,
        selected_strategy="CONTROLLED_LOCAL",
    )
    exec_rec = ExecutionAuditRecord(
        execution_id=exec_id,
        workflow_id=workflow_id,
        execution_plan_id="plan-api-1",
        approval_state="approved",
        status=ExecutionOverallStatus.COMPLETED,
        sandbox_root="/tmp/sandbox",
        step_results=[step_res],
        verification_status="VERIFIED",
    )
    exec_repo.save(exec_rec)

    v_run = VerificationResult(
        verification_run_id="vrun-api-refresh-1",
        execution_id=exec_id,
        workflow_id=workflow_id,
        execution_plan_id="plan-api-1",
        overall_status=VerificationStatus.VERIFIED,
        verified_count=1,
        checks=[
            VerificationCheck(
                execution_id=exec_id,
                execution_step_id=step_res.execution_step_id,
                planned_step_id="step-api-1",
                check_type="file_exists",
                strategy_type=VerificationStrategyType.FILE_SYSTEM,
                target="output.txt",
                expected_state=True,
                actual_state=True,
                status=VerificationStatus.VERIFIED,
                reason="File exists",
            )
        ],
    )
    verif_repo.save(v_run)

    # Call refresh endpoint
    res = client.post(f"/api/workflows/{workflow_id}/learning/refresh")
    assert res.status_code == 200
    data = res.json()
    assert data["workflow_id"] == workflow_id
    assert data["total_executions"] == 1
    assert data["verified_executions"] == 1
    assert data["reliability_rate"] == 1.0

    # Call get endpoint to confirm persistence
    res_get = client.get(f"/api/workflows/{workflow_id}/learning")
    assert res_get.status_code == 200
    assert res_get.json()["total_executions"] == 1

    # Call events endpoint
    res_events = client.get(f"/api/workflows/{workflow_id}/learning/events")
    assert res_events.status_code == 200
    events = res_events.json()
    assert len(events) >= 1
    assert events[0]["event_type"] == "EXECUTION_SUCCESS_OBSERVED"

"""Integration tests for Phase 9 Verification API endpoints:
- POST /api/workflows/executions/{execution_id}/verify
- GET /api/workflows/executions/{execution_id}/verification
- GET /api/workflows/verifications/{verification_run_id}
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import app
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
from app.models.execution_plan import (
    ExecutionPlan,
    ExecutionStrategy,
    ExpectedStateChange,
    ParameterResolutionStatus,
    PlannedStep,
    PreconditionCheck,
    PreconditionStatus,
    ResolvedParameter,
    StepExecutionStrategy,
)
from app.repositories.canonical_repository import CanonicalWorkflowRepository
from app.repositories.execution_plan_repository import ExecutionPlanRepository
from app.repositories.execution_repository import ExecutionRepository
from app.services.execution_engine import ExecutionEngine


@pytest.fixture
def api_client():
    return TestClient(app)


@pytest.fixture
def executed_plan_in_db():
    wf_id = f"wf-api-verif-{datetime.now(timezone.utc).timestamp()}"
    plan_id = f"plan-api-verif-{datetime.now(timezone.utc).timestamp()}"

    spec = CanonicalWorkflowSpec(
        workflow_id=wf_id,
        source_dna_id="dna-api-001",
        source_semantic_workflow_id="sem-api-001",
        title="API Verification Workflow",
        intent="Write and verify sandbox file",
        description="Write and verify sandbox file",
        version="1.0.0",
        status="specification_ready",
        steps=[],
        variables=[],
        optional_steps=[],
        preconditions=["Sandbox folder ready"],
        boundaries=WorkflowBoundaries(
            first_step="File System:save_file",
            last_step="File System:save_file",
            min_duration_seconds=1.0,
            max_duration_seconds=10.0,
            average_duration_seconds=5.0,
            total_supporting_sessions=2,
        ),
        ordering_constraints=[],
        evidence=DNAEvidence(
            supporting_session_count=2,
            invariant_evidence="Local step",
            variable_evidence="filename",
            optional_step_evidence="None",
            ordering_evidence="Sequential",
            boundary_evidence="Boundaries established",
        ),
        parameter_bindings=[],
        risk_assessment=RiskAssessment(
            overall_risk_level=RiskLevel.LOW,
            primary_risk_category=RiskCategory.LOCAL_CHANGE,
            requires_human_confirmation=False,
            step_risks=[],
            summary="Low risk",
            sensitive_factors_detected=[],
        ),
        approval_state=ApprovalMetadata(
            state=ApprovalState.APPROVED,
            reviewed_by="admin@workflowos.local",
            comments="Approved for API test",
        ),
    )

    planned_step = PlannedStep(
        plan_step_id="pstep-1",
        source_canonical_step_id="can-step-1",
        source_semantic_step_id="sem-step-1",
        source_dna_step_key="dna-step-1",
        application="File System",
        action="save_file",
        description="Save api verif file",
        resolved_parameters={"file_name": "api_verif_output.json"},
        execution_strategy=StepExecutionStrategy(
            strategy=ExecutionStrategy.APPLICATION_INTEGRATION,
            reason="Local file persistence",
            target_technology="Local OS File System API",
        ),
        risk=StepRisk(
            step_id="can-step-1",
            application="File System",
            action="save_file",
            risk_level=RiskLevel.LOW,
            risk_category=RiskCategory.LOCAL_CHANGE,
            reason="Sandbox file write",
            requires_confirmation=False,
        ),
        expected_result="Saved api_verif_output.json",
        external_change=False,
        requires_confirmation=False,
        evidence_reference="evidence-api",
        state_change=ExpectedStateChange(
            target_system="File System",
            entity_or_property="api_verif_output.json",
            before_state="Does not exist",
            expected_after_state="api_verif_output.json exists",
            actual_state="UNTOUCHED",
        ),
    )

    plan = ExecutionPlan(
        execution_plan_id=plan_id,
        source_workflow_id=wf_id,
        workflow_version="1.0.0",
        source_approval_state="approved",
        resolved_parameters=[
            ResolvedParameter(
                source_parameter="file_param_1",
                semantic_name="file_name",
                source_field="metadata.file_name",
                inferred_type="filename",
                runtime_value="api_verif_output.json",
                resolution_status=ParameterResolutionStatus.RESOLVED,
                is_required=True,
            )
        ],
        planned_steps=[planned_step],
        preconditions=[
            PreconditionCheck(
                condition="sandbox_ready",
                status=PreconditionStatus.SATISFIED,
                evaluation_reason="Ready",
            )
        ],
        boundaries=WorkflowBoundaries(
            first_step="File System:save_file",
            last_step="File System:save_file",
            min_duration_seconds=1.0,
            max_duration_seconds=10.0,
            average_duration_seconds=5.0,
            total_supporting_sessions=2,
        ),
        risk_assessment=RiskAssessment(
            overall_risk_level=RiskLevel.LOW,
            primary_risk_category=RiskCategory.LOCAL_CHANGE,
            requires_human_confirmation=False,
            step_risks=[],
            summary="Low risk",
            sensitive_factors_detected=[],
        ),
        expected_effects=[
            ExpectedStateChange(
                target_system="File System",
                entity_or_property="api_verif_output.json",
                before_state="Does not exist",
                expected_after_state="api_verif_output.json exists",
                actual_state="UNTOUCHED",
            )
        ],
        dry_run_status="SIMULATED",
    )

    CanonicalWorkflowRepository().save(spec)
    ExecutionPlanRepository().save(plan)

    engine = ExecutionEngine()
    audit = engine.execute_plan(plan_id)
    return audit


def test_api_verify_execution_success(api_client, executed_plan_in_db):
    """POST /api/workflows/executions/{execution_id}/verify triggers verification."""
    exec_id = executed_plan_in_db.execution_id
    resp = api_client.post(
        f"/api/workflows/executions/{exec_id}/verify",
        json={"force_recheck": True},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert "verification_run_id" in data
    assert data["execution_id"] == exec_id
    assert data["overall_status"] == "VERIFIED"
    assert data["verified_count"] >= 1
    assert data["failed_count"] == 0
    assert len(data["checks"]) >= 1

    check = data["checks"][0]
    assert check["status"] == "VERIFIED"
    assert check["strategy_type"] == "RESOURCE_EXISTENCE"
    assert "evidence" in check
    assert "sha256" in check["evidence"]


def test_api_get_execution_verification(api_client, executed_plan_in_db):
    """GET /api/workflows/executions/{execution_id}/verification retrieves latest verification."""
    exec_id = executed_plan_in_db.execution_id

    # Verify first
    post_resp = api_client.post(
        f"/api/workflows/executions/{exec_id}/verify",
        json={"force_recheck": True},
    )
    assert post_resp.status_code == 200
    vrun_id = post_resp.json()["verification_run_id"]

    # Retrieve by execution ID
    get_resp = api_client.get(f"/api/workflows/executions/{exec_id}/verification")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["verification_run_id"] == vrun_id
    assert data["overall_status"] == "VERIFIED"


def test_api_get_verification_by_run_id(api_client, executed_plan_in_db):
    """GET /api/workflows/verifications/{verification_run_id} retrieves verification run."""
    exec_id = executed_plan_in_db.execution_id

    post_resp = api_client.post(
        f"/api/workflows/executions/{exec_id}/verify",
        json={"force_recheck": True},
    )
    assert post_resp.status_code == 200
    vrun_id = post_resp.json()["verification_run_id"]

    get_resp = api_client.get(f"/api/workflows/verifications/{vrun_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["verification_run_id"] == vrun_id


def test_api_verify_nonexistent_execution_404(api_client):
    """POST /api/workflows/executions/{execution_id}/verify with unknown id returns 404."""
    resp = api_client.post("/api/workflows/executions/non-existent-exec-id/verify")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_api_get_nonexistent_verification_404(api_client):
    """GET /api/workflows/verifications/{id} with unknown id returns 404."""
    resp = api_client.get("/api/workflows/verifications/vrun-unknown-404")
    assert resp.status_code == 404

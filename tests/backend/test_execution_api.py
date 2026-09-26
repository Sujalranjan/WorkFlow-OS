"""Integration tests for Phase 7 Execution API endpoints:
- POST /api/workflows/specifications/{workflow_id}/execution-plan
- GET /api/workflows/execution-plans
- GET /api/workflows/execution-plans/{execution_plan_id}
- POST /api/workflows/execution-plans/{execution_plan_id}/dry-run
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.canonical import ApprovalMetadata, ApprovalState
from app.repositories.canonical_repository import CanonicalWorkflowRepository
from app.repositories.execution_plan_repository import ExecutionPlanRepository
from app.services.canonical_factory import CanonicalWorkflowFactory
from app.services.semantic_engine import SemanticUnderstandingEngine
from app.services.semantic_provider import MockSemanticProvider
from app.services.workflow_discovery import WorkflowDiscoveryEngine
from app.services.workflow_dna_extractor import WorkflowDNAExtractor
from app.services.workflow_segmenter import WorkflowSegmenter
from tests.fixtures.discovery_fixtures import generate_deterministic_dataset


@pytest.fixture
def api_client():
    return TestClient(app)


@pytest.fixture
def approved_spec_in_db():
    events = generate_deterministic_dataset()
    sessions = WorkflowSegmenter(session_inactivity_timeout_seconds=120.0).segment(events)
    discovery = WorkflowDiscoveryEngine(min_occurrences=2, similarity_threshold=0.65)
    candidates = discovery.discover_candidates(sessions)
    session_map = {s.session_id: s for s in sessions}
    supporting = [session_map[sid] for sid in candidates[0].supporting_session_ids]
    extractor = WorkflowDNAExtractor()
    dna = extractor.extract_dna(candidates[0], supporting)

    engine = SemanticUnderstandingEngine(provider=MockSemanticProvider(mode="valid"))
    resp = engine.interpret_dna(dna)
    assert resp.status == "success"

    factory = CanonicalWorkflowFactory()
    spec = factory.create_specification(dna=dna, semantic_wf=resp.semantic_workflow)
    spec.approval_state = ApprovalMetadata(
        state=ApprovalState.APPROVED,
        reviewed_by="admin",
        comments="Approved for API testing",
    )

    repo = CanonicalWorkflowRepository()
    repo.save(spec)
    return spec


def test_api_create_execution_plan(api_client, approved_spec_in_db):
    """POST /api/workflows/specifications/{workflow_id}/execution-plan creates plan."""
    resp = api_client.post(
        f"/api/workflows/specifications/{approved_spec_in_db.workflow_id}/execution-plan",
        json={"runtime_parameters": {"customer_name": "Test User"}},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["source_workflow_id"] == approved_spec_in_db.workflow_id
    assert data["source_approval_state"] == "approved"
    assert len(data["planned_steps"]) == len(approved_spec_in_db.steps)
    assert data["dry_run_status"] == "not_started"


def test_api_unapproved_spec_rejected(api_client, approved_spec_in_db):
    """POST /api/workflows/specifications/{workflow_id}/execution-plan rejects unapproved spec."""
    approved_spec_in_db.approval_state.state = ApprovalState.REQUIRES_REVIEW
    repo = CanonicalWorkflowRepository()
    repo.save(approved_spec_in_db)

    resp = api_client.post(
        f"/api/workflows/specifications/{approved_spec_in_db.workflow_id}/execution-plan",
        json={},
    )
    assert resp.status_code == 400
    assert "APPROVED" in resp.json()["detail"]


def test_api_get_execution_plans(api_client, approved_spec_in_db):
    """GET /api/workflows/execution-plans returns list of plans."""
    # Create a plan first
    create_resp = api_client.post(
        f"/api/workflows/specifications/{approved_spec_in_db.workflow_id}/execution-plan",
        json={},
    )
    assert create_resp.status_code == 201
    plan_id = create_resp.json()["execution_plan_id"]

    # List all
    list_resp = api_client.get("/api/workflows/execution-plans")
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert list_data["total_count"] >= 1
    assert any(p["execution_plan_id"] == plan_id for p in list_data["plans"])

    # Get single
    single_resp = api_client.get(f"/api/workflows/execution-plans/{plan_id}")
    assert single_resp.status_code == 200
    assert single_resp.json()["execution_plan_id"] == plan_id


def test_api_run_dry_run_simulation(api_client, approved_spec_in_db):
    """POST /api/workflows/execution-plans/{execution_plan_id}/dry-run runs shadow simulation."""
    create_resp = api_client.post(
        f"/api/workflows/specifications/{approved_spec_in_db.workflow_id}/execution-plan",
        json={},
    )
    plan_id = create_resp.json()["execution_plan_id"]

    dry_run_resp = api_client.post(f"/api/workflows/execution-plans/{plan_id}/dry-run")
    assert dry_run_resp.status_code == 200
    sim_data = dry_run_resp.json()

    assert sim_data["overall_simulation_status"] == "SIMULATED"
    # STRICT SAFETY GUARANTEE: zero real actions
    assert sim_data["real_actions_performed"] == 0
    assert len(sim_data["step_simulations"]) == len(approved_spec_in_db.steps)
    assert "SIMULATED" in sim_data["summary"]

    # Verify plan record updated
    plan_resp = api_client.get(f"/api/workflows/execution-plans/{plan_id}")
    assert plan_resp.json()["dry_run_status"] == "simulated"
    assert plan_resp.json()["dry_run_result"] is not None


def test_api_execute_plan_and_audit_endpoints(api_client, approved_spec_in_db):
    """Test POST /execute, GET /executions, GET /executions/{id}, and POST /cancel."""
    # 1. Create plan
    create_resp = api_client.post(
        f"/api/workflows/specifications/{approved_spec_in_db.workflow_id}/execution-plan",
        json={},
    )
    assert create_resp.status_code == 201
    plan_id = create_resp.json()["execution_plan_id"]

    import uuid
    unique_key = f"test-api-key-{uuid.uuid4().hex[:8]}"

    # 2. Execute plan
    exec_resp = api_client.post(
        f"/api/workflows/execution-plans/{plan_id}/execute",
        json={"idempotency_key": unique_key},
    )
    assert exec_resp.status_code == 200
    exec_data = exec_resp.json()
    assert "execution_id" in exec_data
    execution_id = exec_data["execution_id"]
    assert exec_data["execution_plan_id"] == plan_id

    # 3. List executions
    list_resp = api_client.get("/api/workflows/executions")
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert list_data["total_count"] >= 1
    assert any(e["execution_id"] == execution_id for e in list_data["executions"])

    # 4. Get single execution
    single_resp = api_client.get(f"/api/workflows/executions/{execution_id}")
    assert single_resp.status_code == 200
    assert single_resp.json()["execution_id"] == execution_id

    # 5. Cancel execution endpoint
    cancel_resp = api_client.post(f"/api/workflows/executions/{execution_id}/cancel")
    assert cancel_resp.status_code == 200


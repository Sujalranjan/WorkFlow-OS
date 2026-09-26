"""API Integration tests for Canonical Workflow Specification endpoints (Phase 6)."""

import tempfile
import pytest
from fastapi.testclient import TestClient

from app.api.canonical import get_canonical_repository
from app.api.events import get_event_service
from app.api.semantic import get_semantic_engine
from app.main import create_app
from app.models.canonical import ApprovalState
from app.repositories.canonical_repository import CanonicalWorkflowRepository
from app.repositories.event_repository import EventRepository
from app.services.event_service import EventService
from app.services.semantic_engine import SemanticUnderstandingEngine
from app.services.semantic_provider import MockSemanticProvider
from tests.fixtures.discovery_fixtures import generate_deterministic_dataset


@pytest.fixture
def test_client_and_setup():
    """Sets up an isolated test database and FastAPI TestClient."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        temp_db_path = tf.name

    event_repo = EventRepository(db_path=temp_db_path)
    canonical_repo = CanonicalWorkflowRepository(db_path=temp_db_path)
    event_service = EventService(repository=event_repo)

    # Ingest test dataset
    events = generate_deterministic_dataset()
    for evt in events:
        event_service.record_event(evt)

    # Setup mock semantic engine
    mock_provider = MockSemanticProvider(mode="valid")
    engine = SemanticUnderstandingEngine(provider=mock_provider)

    app = create_app()
    app.dependency_overrides[get_event_service] = lambda: event_service
    app.dependency_overrides[get_canonical_repository] = lambda: canonical_repo
    app.dependency_overrides[get_semantic_engine] = lambda: engine

    client = TestClient(app)
    yield client, engine, canonical_repo, temp_db_path

    app.dependency_overrides.clear()


def test_canonical_api_workflow_lifecycle(test_client_and_setup) -> None:
    """Test full API lifecycle: DNA -> Semantic -> Canonical Spec -> Edit Param -> Approve -> List."""
    client, engine, canonical_repo, _ = test_client_and_setup

    # 1. Fetch DNA
    dna_resp = client.get("/api/workflows/dna?inactivity_timeout=120&min_occurrences=2&similarity_threshold=0.65")
    assert dna_resp.status_code == 200
    dna_data = dna_resp.json()
    assert dna_data["dna_count"] >= 1
    dna_id = dna_data["dna_items"][0]["dna_id"]

    # 2. Trigger Semantic Interpretation
    interp_resp = client.post(f"/api/workflows/{dna_id}/interpret?provider_type=mock")
    assert interp_resp.status_code == 200
    interp_data = interp_resp.json()
    assert interp_data["status"] == "success"
    semantic_wf_id = interp_data["semantic_workflow"]["semantic_workflow_id"]

    # 3. Create Canonical Specification
    spec_resp = client.post(f"/api/workflows/{semantic_wf_id}/specification")
    assert spec_resp.status_code == 201
    spec_data = spec_resp.json()
    workflow_id = spec_data["workflow_id"]
    assert spec_data["source_dna_id"] == dna_id
    assert spec_data["source_semantic_workflow_id"] == semantic_wf_id
    assert spec_data["approval_state"]["state"] == "requires_review"
    assert len(spec_data["steps"]) >= 4
    assert len(spec_data["variables"]) >= 2
    assert "risk_assessment" in spec_data
    assert spec_data["risk_assessment"]["overall_risk_level"] in ("low", "medium", "high")

    # 4. Get Specification by ID
    get_resp = client.get(f"/api/workflows/specifications/{workflow_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["workflow_id"] == workflow_id

    # 5. List Specifications
    list_resp = client.get("/api/workflows/specifications")
    assert list_resp.status_code == 200
    assert list_resp.json()["total_count"] >= 1

    # 6. Update Parameter Binding
    source_param = spec_data["variables"][0]["source_parameter"]
    patch_resp = client.patch(
        f"/api/workflows/specifications/{workflow_id}/parameters",
        json={
            "updates": [
                {
                    "source_parameter": source_param,
                    "semantic_name": "custom_client_identifier",
                }
            ]
        },
    )
    assert patch_resp.status_code == 200
    updated_spec = patch_resp.json()
    updated_var = next(v for v in updated_spec["variables"] if v["source_parameter"] == source_param)
    assert updated_var["semantic_name"] == "custom_client_identifier"
    assert updated_var["user_override"] is True
    assert updated_var["binding_status"] == "user_modified"

    # 7. Approve Specification
    approve_resp = client.post(
        f"/api/workflows/specifications/{workflow_id}/approve",
        json={
            "reviewer": "operations_lead@company.com",
            "comments": "Specification verified against process documentation.",
        },
    )
    assert approve_resp.status_code == 200
    approved_data = approve_resp.json()
    assert approved_data["approval_state"]["state"] == "approved"
    assert approved_data["approval_state"]["reviewed_by"] == "operations_lead@company.com"
    assert approved_data["approval_state"]["reviewed_at"] is not None

    # 8. Reject Endpoint test on a second copy
    reject_resp = client.post(
        f"/api/workflows/specifications/{workflow_id}/reject",
        json={
            "reviewer": "compliance_officer",
            "reason": "Needs re-verification.",
        },
    )
    assert reject_resp.status_code == 200
    assert reject_resp.json()["approval_state"]["state"] == "rejected"
    assert reject_resp.json()["approval_state"]["rejection_reason"] == "Needs re-verification."


def test_canonical_api_404_handling(test_client_and_setup) -> None:
    """Test 404 error responses for non-existent workflows or specifications."""
    client, _, _, _ = test_client_and_setup

    res1 = client.post("/api/workflows/non-existent-sem-id/specification")
    assert res1.status_code == 404

    res2 = client.get("/api/workflows/specifications/non-existent-wf-id")
    assert res2.status_code == 404

    res3 = client.post("/api/workflows/specifications/non-existent-wf-id/approve", json={})
    assert res3.status_code == 404

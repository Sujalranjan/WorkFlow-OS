"""Integration tests for Semantic Understanding API endpoints (Phase 5)."""

import os
import tempfile
from fastapi.testclient import TestClient
from app.api.events import get_event_service
from app.api.semantic import get_semantic_engine
from app.main import app
from app.repositories.event_repository import EventRepository
from app.services.event_service import EventService
from app.services.semantic_engine import SemanticUnderstandingEngine
from app.services.semantic_provider import MockSemanticProvider
from tests.fixtures.discovery_fixtures import generate_deterministic_dataset


def test_semantic_api_endpoints() -> None:
    temp_dir = tempfile.mkdtemp()
    test_db_path = os.path.join(temp_dir, "test_semantic_api.db")

    try:
        repo = EventRepository(db_path=test_db_path)
        service = EventService(repository=repo)

        events = generate_deterministic_dataset()
        for evt in events:
            service.record_event(evt)

        mock_provider = MockSemanticProvider(mode="valid")
        engine = SemanticUnderstandingEngine(provider=mock_provider)

        app.dependency_overrides[get_event_service] = lambda: service
        app.dependency_overrides[get_semantic_engine] = lambda: engine
        client = TestClient(app)

        # 1. Fetch DNA items to obtain a valid dna_id
        dna_resp = client.get("/api/workflows/dna")
        assert dna_resp.status_code == 200
        dna_data = dna_resp.json()
        assert dna_data["dna_count"] >= 1
        dna_id = dna_data["dna_items"][0]["dna_id"]

        # 2. Test POST /api/workflows/{dna_id}/interpret
        interpret_resp = client.post(f"/api/workflows/{dna_id}/interpret?provider_type=mock")
        assert interpret_resp.status_code == 200
        interpret_data = interpret_resp.json()

        assert interpret_data["status"] == "success"
        assert interpret_data["validation_passed"] is True
        sem_wf = interpret_data["semantic_workflow"]
        assert sem_wf is not None
        assert sem_wf["title"] == "Customer Replacement Request Processing"
        sem_wf_id = sem_wf["semantic_workflow_id"]

        # 3. Test GET /api/workflows/semantic/{semantic_workflow_id}
        fetch_resp = client.get(f"/api/workflows/semantic/{sem_wf_id}")
        assert fetch_resp.status_code == 200
        fetch_data = fetch_resp.json()
        assert fetch_data["semantic_workflow_id"] == sem_wf_id
        assert fetch_data["title"] == sem_wf["title"]

        # 4. Test 404 for invalid semantic ID
        not_found_resp = client.get("/api/workflows/semantic/non_existent_sem_id")
        assert not_found_resp.status_code == 404

        # 5. Test 404 for invalid DNA ID during interpret
        invalid_dna_resp = client.post("/api/workflows/invalid_dna_id/interpret")
        assert invalid_dna_resp.status_code == 404

    finally:
        app.dependency_overrides.clear()
        if os.path.exists(test_db_path):
            try:
                os.remove(test_db_path)
                os.rmdir(temp_dir)
            except OSError:
                pass

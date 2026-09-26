"""Integration tests for Workflow DNA API endpoints (Phase 4)."""

import os
import tempfile
from fastapi.testclient import TestClient
from app.api.events import get_event_service
from app.main import app
from app.repositories.event_repository import EventRepository
from app.services.event_service import EventService
from tests.fixtures.discovery_fixtures import generate_deterministic_dataset


def test_workflow_dna_api_endpoints() -> None:
    temp_dir = tempfile.mkdtemp()
    test_db_path = os.path.join(temp_dir, "test_dna_api.db")

    try:
        repo = EventRepository(db_path=test_db_path)
        service = EventService(repository=repo)

        events = generate_deterministic_dataset()
        for evt in events:
            service.record_event(evt)

        app.dependency_overrides[get_event_service] = lambda: service
        client = TestClient(app)

        # 1. Test GET /api/workflows/dna
        response = client.get("/api/workflows/dna")
        assert response.status_code == 200
        data = response.json()

        assert data["dna_count"] >= 1
        top_dna = data["dna_items"][0]
        assert "dna_id" in top_dna
        assert "invariant_steps" in top_dna
        assert "variable_parameters" in top_dna
        assert "optional_steps" in top_dna
        assert "ordering_constraints" in top_dna
        assert "evidence" in top_dna

        # 2. Test GET /api/workflows/dna/{dna_id}
        dna_id = top_dna["dna_id"]
        detail_resp = client.get(f"/api/workflows/dna/{dna_id}")
        assert detail_resp.status_code == 200
        detail_data = detail_resp.json()
        assert detail_data["dna_id"] == dna_id
        assert len(detail_data["invariant_steps"]) >= 4

        # 3. Test 404 for invalid ID
        not_found_resp = client.get("/api/workflows/dna/non_existent_dna_id")
        assert not_found_resp.status_code == 404
    finally:
        app.dependency_overrides.clear()
        if os.path.exists(test_db_path):
            try:
                os.remove(test_db_path)
                os.rmdir(temp_dir)
            except OSError:
                pass

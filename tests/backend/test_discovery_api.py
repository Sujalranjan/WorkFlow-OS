"""Integration tests for GET /api/discovery/candidates endpoint."""

import os
import tempfile
from fastapi.testclient import TestClient
from app.api.events import get_event_service
from app.main import app
from app.repositories.event_repository import EventRepository
from app.services.event_service import EventService
from tests.fixtures.discovery_fixtures import generate_deterministic_dataset


def test_discovery_candidates_api_endpoint() -> None:
    """Verify that GET /api/discovery/candidates returns segmented sessions and discovered candidates."""
    temp_dir = tempfile.mkdtemp()
    test_db_path = os.path.join(temp_dir, "test_discovery_api.db")

    try:
        repo = EventRepository(db_path=test_db_path)
        service = EventService(repository=repo)

        # Populate repository with the deterministic dataset
        events = generate_deterministic_dataset()
        for evt in events:
            service.record_event(evt)

        # Override dependency
        app.dependency_overrides[get_event_service] = lambda: service
        client = TestClient(app)

        # Query candidates endpoint
        response = client.get(
            "/api/discovery/candidates",
            params={
                "inactivity_timeout": 120.0,
                "min_occurrences": 2,
                "similarity_threshold": 0.65,
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert data["total_events_analyzed"] == len(events)
        assert data["total_sessions_found"] == 5
        assert data["candidate_count"] >= 1

        top_cand = data["candidates"][0]
        assert top_cand["occurrences"] >= 2
        assert "representative_sequence" in top_cand
        assert len(top_cand["representative_sequence"]) > 0
        assert "evidence" in top_cand
    finally:
        app.dependency_overrides.clear()
        if os.path.exists(test_db_path):
            try:
                os.remove(test_db_path)
                os.rmdir(temp_dir)
            except OSError:
                pass

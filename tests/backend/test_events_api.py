"""Tests for the Activity Events backend API and persistence layer."""

import os
import tempfile
import time
from fastapi.testclient import TestClient
from app.api.events import get_event_service
from app.main import app
from app.models.event import ActivityEvent, ActivityEventType
from app.repositories.event_repository import EventRepository
from app.services.event_service import EventService


def test_create_and_fetch_event_api() -> None:
    """Verify POST /api/events and GET /api/events."""
    temp_dir = tempfile.mkdtemp()
    test_db_path = os.path.join(temp_dir, "test_events.db")

    try:
        repo = EventRepository(db_path=test_db_path)
        service = EventService(repository=repo)

        # Override dependency
        app.dependency_overrides[get_event_service] = lambda: service
        client = TestClient(app)

        # 1. Post application_opened event
        event_payload = {
            "event_type": "application_opened",
            "application": "Chrome",
            "source": "desktop_agent",
            "metadata": {"title": "Gmail - Inbox"},
        }
        post_resp = client.post("/api/events", json=event_payload)
        assert post_resp.status_code == 201
        data = post_resp.json()
        assert data["status"] == "success"
        created_event = data["event"]
        assert created_event["application"] == "Chrome"
        assert created_event["event_type"] == "application_opened"
        assert "event_id" in created_event

        # 2. Post file_downloaded event
        file_payload = {
            "event_type": "file_downloaded",
            "application": "Chrome",
            "source": "desktop_agent",
            "metadata": {"file_name": "customer_request.pdf", "file_size": 2048},
        }
        post_resp2 = client.post("/api/events", json=file_payload)
        assert post_resp2.status_code == 201

        # 3. Fetch events
        get_resp = client.get("/api/events")
        assert get_resp.status_code == 200
        events_list = get_resp.json()
        assert len(events_list) == 2
        # Most recent first
        assert events_list[0]["event_type"] == "file_downloaded"
        assert events_list[1]["event_type"] == "application_opened"
    finally:
        app.dependency_overrides.clear()
        if os.path.exists(test_db_path):
            try:
                os.remove(test_db_path)
                os.rmdir(temp_dir)
            except OSError:
                pass


def test_invalid_event_type_rejection() -> None:
    """Verify that an invalid event_type returns 422 Unprocessable Entity."""
    client = TestClient(app)
    bad_payload = {
        "event_type": "non_existent_event_type",
        "application": "Chrome",
    }
    response = client.post("/api/events", json=bad_payload)
    assert response.status_code == 422

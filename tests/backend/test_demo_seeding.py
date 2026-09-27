"""Focused tests for the Demo Activity Seeding API (Phase 13.3).

Verifies:
A. POST /api/demo/seed-activity successfully creates valid ActivityEvents.
B. Events are persisted using standard EventRepository.
C. The seeded events can be retrieved through GET /api/events.
D. The seeded events can be consumed by the existing discovery endpoint (GET /api/discovery/candidates).
E. No downstream workflow entities (specifications, plans, executions) are created merely by seeding.
F. Invalid scenario input is rejected with HTTP 400.
G. Standard event ingestion remains unchanged.
"""

import os
import tempfile
from fastapi.testclient import TestClient
import pytest

from app.api.events import get_event_service
from app.main import app
from app.repositories.canonical_repository import CanonicalWorkflowRepository
from app.repositories.event_repository import EventRepository
from app.repositories.execution_plan_repository import ExecutionPlanRepository
from app.repositories.execution_repository import ExecutionRepository
from app.services.event_service import EventService


@pytest.fixture
def isolated_client():
    temp_dir = tempfile.mkdtemp()
    test_db_path = os.path.join(temp_dir, "test_demo_seed.db")
    repo = EventRepository(db_path=test_db_path)
    service = EventService(repository=repo)

    app.dependency_overrides[get_event_service] = lambda: service
    client = TestClient(app)

    yield client, repo, test_db_path

    app.dependency_overrides.clear()
    if os.path.exists(test_db_path):
        try:
            os.remove(test_db_path)
            os.rmdir(temp_dir)
        except OSError:
            pass


def test_seed_activity_endpoint_success(isolated_client):
    """A & B: Endpoint creates valid ActivityEvents and persists them."""
    client, repo, _ = isolated_client

    # Initially empty
    assert len(repo.list_recent(limit=100)) == 0

    response = client.post("/api/demo/seed-activity", json={"scenario": "invoice_processing"})
    assert response.status_code == 201
    data = response.json()

    assert data["events_created"] == 20
    assert data["sessions_created"] == 5
    assert data["scenario"] == "invoice_processing"
    assert "Successfully seeded" in data["message"]

    # Verify persisted in repo
    persisted = repo.list_recent(limit=100)
    assert len(persisted) == 20
    assert all(evt.source == "demo_seed" for evt in persisted)


def test_seed_activity_retrieval_and_discovery(isolated_client):
    """C & D: Seeded events are retrievable via GET /api/events and discoverable."""
    client, _, _ = isolated_client

    # 1. Seed demo activity with invoice_processing scenario
    seed_resp = client.post("/api/demo/seed-activity", json={"scenario": "invoice_processing"})
    assert seed_resp.status_code == 201

    # 2. Retrieve via GET /api/events
    get_resp = client.get("/api/events?limit=50")
    assert get_resp.status_code == 200
    events = get_resp.json()
    assert len(events) == 20

    # Verify expected applications from invoice processing
    apps = {e["application"] for e in events if e["application"]}
    assert "Gmail" in apps
    assert "CRM" in apps
    assert "Slack" in apps
    assert "File System" in apps

    # 3. Discovery engine analyzes these seeded events
    disc_resp = client.get("/api/discovery/candidates?inactivity_timeout=120.0&min_occurrences=2&similarity_threshold=0.65")
    assert disc_resp.status_code == 200
    disc_data = disc_resp.json()

    assert disc_data["total_events_analyzed"] == 20
    assert disc_data["total_sessions_found"] == 5
    # The recurring invoice processing pattern is discovered
    assert disc_data["candidate_count"] >= 1
    discovered_candidate = disc_data["candidates"][0]
    assert discovered_candidate["occurrences"] >= 2
    assert "Gmail" in discovered_candidate["applications"]
    assert "CRM" in discovered_candidate["applications"]


def test_seed_local_file_automation_scenario(isolated_client):
    """Phase 15: Local file automation scenario creates coherent Controlled Local routine."""
    client, _, _ = isolated_client

    # 1. Seed default local_file_automation
    seed_resp = client.post("/api/demo/seed-activity", json={"scenario": "local_file_automation"})
    assert seed_resp.status_code == 201
    data = seed_resp.json()
    assert data["events_created"] == 14
    assert data["scenario"] == "local_file_automation"

    # 2. Retrieve events and verify only local filesystem applications
    get_resp = client.get("/api/events?limit=50")
    assert get_resp.status_code == 200
    events = get_resp.json()
    assert len(events) == 14

    # 3. Discovery produces candidate with File System actions
    disc_resp = client.get("/api/discovery/candidates?inactivity_timeout=120.0&min_occurrences=2&similarity_threshold=0.65")
    assert disc_resp.status_code == 200
    disc_data = disc_resp.json()
    assert disc_data["candidate_count"] >= 1
    local_candidate = disc_data["candidates"][0]
    # All recurring actions are local File System actions
    assert all(step["application"] == "File System" for step in local_candidate["representative_sequence"])
    assert len(local_candidate["representative_sequence"]) == 3


def test_demo_reset_endpoint(isolated_client):
    """Phase 15: POST /api/demo/reset clears demo entities and returns clean state."""
    client, repo, _ = isolated_client

    # Seed events
    client.post("/api/demo/seed-activity", json={"scenario": "local_file_automation"})
    assert len(repo.list_recent(limit=50)) == 14

    # Call reset
    reset_resp = client.post("/api/demo/reset")
    assert reset_resp.status_code == 200
    reset_data = reset_resp.json()
    assert reset_data["status"] == "reset"
    assert reset_data["events_deleted"] == 14
    assert "Demonstration state reset successfully" in reset_data["message"]

    # Verify repository is clean
    assert len(repo.list_recent(limit=50)) == 0


def test_no_downstream_entities_created_by_seeding(isolated_client):
    """E: No specs, plans, or executions are created by seeding."""
    client, _, db_path = isolated_client

    # Seed demo activity
    seed_resp = client.post("/api/demo/seed-activity")
    assert seed_resp.status_code == 201

    # Check specs
    spec_repo = CanonicalWorkflowRepository(db_path=db_path)
    assert len(spec_repo.list_all()) == 0

    # Check execution plans
    plan_repo = ExecutionPlanRepository(db_path=db_path)
    assert len(plan_repo.list_all()) == 0

    # Check executions
    exec_repo = ExecutionRepository(db_path=db_path)
    assert len(exec_repo.list_all()) == 0


def test_seed_activity_rejects_invalid_scenario(isolated_client):
    """F: Invalid scenario input is rejected with HTTP 400."""
    client, _, _ = isolated_client

    bad_resp = client.post("/api/demo/seed-activity", json={"scenario": "autonomous_takeover"})
    assert bad_resp.status_code == 400
    assert "Unsupported demo scenario" in bad_resp.json()["detail"]


def test_standard_event_ingestion_remains_intact(isolated_client):
    """G: Existing POST /api/events functionality is untouched."""
    client, repo, _ = isolated_client

    payload = {
        "event_type": "application_opened",
        "application": "TestApp",
        "source": "desktop_agent",
        "metadata": {"test": True},
    }
    resp = client.post("/api/events", json=payload)
    assert resp.status_code == 201
    assert resp.json()["status"] == "success"

    persisted = repo.list_recent(limit=10)
    assert len(persisted) == 1
    assert persisted[0].application == "TestApp"

"""Observation -> execution through the HTTP API the dashboard and browser extension use."""

from fastapi.testclient import TestClient
import pytest

from app.api.events import get_event_service
from app.main import app
from app.repositories.event_repository import EventRepository
from app.services.event_service import EventService
from tests.fixtures.observed_sessions import build_observed_events


@pytest.fixture
def client(tmp_path):
    service = EventService(repository=EventRepository(db_path=str(tmp_path / "events.db")))
    app.dependency_overrides[get_event_service] = lambda: service
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_event_service, None)


def test_recorded_browser_activity_becomes_an_approved_executable_workflow(client):
    # 1. The browser extension / window collector post events
    for evt in build_observed_events():
        res = client.post("/api/events", content=evt.model_dump_json(), headers={"Content-Type": "application/json"})
        assert res.status_code == 201

    # 2. Discovery + DNA
    dna_list = client.get("/api/workflows/dna").json()
    assert dna_list["dna_count"] == 1
    dna = dna_list["dna_items"][0]
    assert [s["catalog_action"] for s in dna["invariant_steps"] if s["catalog_action"]] == [
        "gmail.search_email",
        "gmail.download_attachment",
        "crm.find_customer",
        "crm.update_customer_record",
        "slack.send_notification",
    ]

    # 3. Semantic interpretation (offline provider) -> canonical spec
    interp = client.post(f"/api/workflows/{dna['dna_id']}/interpret", params={"provider_type": "mock", "force_refresh": True}).json()
    assert interp["status"] == "success", interp["validation_errors"]
    spec = client.post(f"/api/workflows/{interp['semantic_workflow']['semantic_workflow_id']}/specification").json()
    assert spec["approval_state"]["state"] == "requires_review"

    # 4. No plan before a human approves
    plan_res = client.post(f"/api/workflows/specifications/{spec['workflow_id']}/execution-plan")
    assert plan_res.status_code == 400

    client.post(f"/api/workflows/specifications/{spec['workflow_id']}/approve", json={"reviewer": "ops-lead"})
    plan = client.post(f"/api/workflows/specifications/{spec['workflow_id']}/execution-plan").json()
    assert [s["action"] for s in plan["planned_steps"]] == [
        "search_email", "download_attachment", "find_customer", "update_customer_record", "send_notification"
    ]
    assert len(plan["excluded_steps"]) == 2

    # 5. Dry run through the real executor registry: every step routes and simulates
    record = client.post(
        f"/api/workflows/execution-plans/{plan['execution_plan_id']}/execute", json={"execution_mode": "DRY_RUN"}
    ).json()
    assert record["execution_mode"] == "DRY_RUN"
    assert record["status"] == "COMPLETED", record.get("error_summary")
    assert [r["executor_name"] for r in record["step_results"]] == [
        "GmailApiExecutor", "GmailApiExecutor", "CrmApiExecutor", "CrmApiExecutor", "SlackApiExecutor"
    ]

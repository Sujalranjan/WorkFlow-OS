"""Backend support for the dashboard: offline interpreter, workflow reuse and integration status.

- RuleBasedSemanticProvider describes a routine only from its DNA and the ActionCatalog, and its
  output passes the same validation an LLM's output must pass.
- Creating a workflow from the same routine twice returns the same workflow (no duplicates),
  unless the earlier one was rejected.
- /api/status reports connected yes/no per integration and never echoes credentials.
"""

import tempfile

import pytest
from fastapi.testclient import TestClient

from app.api.canonical import get_canonical_repository
from app.api.events import get_event_service
from app.api.semantic import get_semantic_engine
from app.main import create_app
from app.repositories.canonical_repository import CanonicalWorkflowRepository
from app.repositories.event_repository import EventRepository
from app.services.action_catalog import get_action
from app.services.event_service import EventService
from app.services.observed_sessions import build_observed_events
from app.services.semantic_engine import SemanticUnderstandingEngine
from app.services.semantic_provider import RuleBasedSemanticProvider
from app.services.semantic_validator import SemanticWorkflowValidator


@pytest.fixture
def client_and_repo():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db = tf.name
    events = EventService(repository=EventRepository(db_path=db))
    for evt in build_observed_events():
        events.record_event(evt)
    repo = CanonicalWorkflowRepository(db_path=db)
    engine = SemanticUnderstandingEngine(provider=RuleBasedSemanticProvider())

    app = create_app()
    app.dependency_overrides[get_event_service] = lambda: events
    app.dependency_overrides[get_canonical_repository] = lambda: repo
    app.dependency_overrides[get_semantic_engine] = lambda: engine
    yield TestClient(app), repo
    app.dependency_overrides.clear()


def _dna(client):
    items = client.get("/api/workflows/dna").json()["dna_items"]
    assert items, "observed sessions should yield one routine"
    return items[0]


def test_rule_based_interpreter_is_grounded_in_observation(client_and_repo):
    client, _ = client_and_repo
    from app.models.dna import WorkflowDNA

    dna = WorkflowDNA(**_dna(client))
    payload = RuleBasedSemanticProvider().interpret_workflow_dna(dna)

    ok, errors = SemanticWorkflowValidator().validate(payload, dna)
    assert ok, errors
    assert payload["title"] == "Gmail → CRM → Slack routine"
    assert "spreadsheet" not in (payload["summary"] + payload["intent"]).lower()

    by_key = {s["source_dna_step_key"]: s for s in payload["semantic_steps"]}
    for inv in dna.invariant_steps:
        catalog = get_action(inv.catalog_action)
        if catalog:
            assert by_key[inv.step_key]["description"] == catalog.description
    names = {v["semantic_name"] for v in payload["semantic_variables"]}
    assert {"search_query", "customer_query"} <= names


def test_creating_workflow_twice_reuses_it_unless_rejected(client_and_repo):
    client, repo = client_and_repo
    dna_id = _dna(client)["dna_id"]

    def create():
        sem = client.post(f"/api/workflows/{dna_id}/interpret").json()["semantic_workflow"]
        res = client.post(f"/api/workflows/{sem['semantic_workflow_id']}/specification")
        assert res.status_code == 201, res.text
        return res.json()["workflow_id"]

    first = create()
    assert create() == first
    assert len(repo.list_all()) == 1

    assert client.post(f"/api/workflows/specifications/{first}/reject", json={"reason": "wrong"}).status_code == 200
    assert create() != first
    assert len(repo.list_all()) == 2


def test_status_reports_connections_without_secrets(monkeypatch):
    from app.services.crm_client import CrmApiClient
    from app.services.gmail_client import GmailApiClient
    from app.services.slack_client import SlackApiClient

    secret = "xoxb-test-secret-value"
    monkeypatch.setenv("SLACK_BOT_TOKEN", secret)
    monkeypatch.setenv("SLACK_CHANNEL_ID", "C0123456789")
    monkeypatch.setattr(SlackApiClient, "is_healthy", lambda self: False)
    monkeypatch.setattr(CrmApiClient, "is_healthy", lambda self: True)
    monkeypatch.setattr(GmailApiClient, "is_configured", lambda self: True)
    monkeypatch.setattr(GmailApiClient, "is_authenticated", lambda self: False)

    res = TestClient(create_app()).get("/api/status")
    assert res.status_code == 200
    body = res.json()
    assert set(body) >= {"gmail", "slack", "crm", "ai", "email_polling"}
    assert body["crm"]["connected"] is True
    assert body["slack"]["connected"] is False
    assert body["gmail"]["connected"] is False and "Sign-in needed" in body["gmail"]["detail"]
    assert secret not in res.text


def test_status_reports_expired_gmail_sign_in(monkeypatch):
    from app.services.crm_client import CrmApiClient
    from app.services.gmail_client import GmailApiClient

    monkeypatch.setattr(CrmApiClient, "is_healthy", lambda self: False)
    monkeypatch.setattr(GmailApiClient, "is_configured", lambda self: True)
    monkeypatch.setattr(GmailApiClient, "is_authenticated", lambda self: True)  # token file looks fine…
    monkeypatch.setattr(
        GmailApiClient,
        "check_access",
        lambda self: (False, "Sign-in expired: delete token.json and run the Gmail authorization script again."),
    )  # …but Google rejects it

    body = TestClient(create_app()).get("/api/status").json()
    assert body["gmail"] == {
        "connected": False,
        "detail": "Sign-in expired: delete token.json and run the Gmail authorization script again.",
    }


def test_slack_uses_configured_channel_over_recorded_one(tmp_path):
    from unittest.mock import MagicMock

    from app.models.execution import ExecutionContext, ExecutionMode, ExecutionStepStatus
    from app.models.slack import SlackNotificationResult
    from app.services.executors.slack_executor import SlackApiExecutor
    from app.services.slack_client import SlackApiClient
    from tests.backend.test_phase19_gmail_selection import make_test_step

    client = MagicMock(spec=SlackApiClient)
    client.default_channel_id = "C0REALTEAM1"
    client.send_notification.return_value = SlackNotificationResult(success=True, channel="C0REALTEAM1", ts="1.2")
    step = make_test_step("plan-step-5", "send_notification", application="Slack")
    step.resolved_parameters = {"channel": "C0123456789"}  # copied from recorded sample sessions
    ctx = ExecutionContext(
        execution_id="e",
        workflow_id="w",
        execution_plan_id="p",
        sandbox_root=str(tmp_path),
        execution_mode=ExecutionMode.LIVE,
        resolved_parameters={"customer_name": "Rahul", "email_subject": "Replacement request"},
    )

    res = SlackApiExecutor(client=client).execute(step, ctx)
    assert res.status == ExecutionStepStatus.SUCCESS, res.error
    kwargs = client.send_notification.call_args.kwargs
    assert kwargs["channel"] == "C0REALTEAM1"
    assert "Phase 16" not in kwargs["text"] and "Rahul" in kwargs["text"]

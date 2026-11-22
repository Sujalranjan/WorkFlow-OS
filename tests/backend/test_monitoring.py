"""Readiness, metrics, the System overview, worker heartbeats and Slack alerts."""

from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest

from app import config
import app.main as main
from app.services import alerts, monitoring
from app.services.credential_store import SLACK, CredentialStore, set_credential_store


@pytest.fixture
def repo(tmp_path):
    return monitoring.MonitoringRepository(str(tmp_path / "mon.db"))


def test_readiness_needs_a_live_worker_when_jobs_run_elsewhere(repo, monkeypatch):
    monkeypatch.setattr(config, "EMBEDDED_WORKER", False)
    ok, checks = monitoring.readiness(repo)
    assert checks["database"] is True and checks["worker"] is False and not ok
    repo.heartbeat("w1", "worker", {"pid": 1})
    assert monitoring.readiness(repo) == (True, {"database": True, "worker": True})

    # a worker that stopped reporting is down
    from app.db import service_heartbeats

    old = (datetime.now(timezone.utc) - timedelta(seconds=config.WORKER_STALE_SECONDS + 5)).isoformat()
    with repo.begin() as conn:
        conn.execute(service_heartbeats.update().values(last_seen=old))
    assert monitoring.readiness(repo)[0] is False

    monkeypatch.setattr(config, "EMBEDDED_WORKER", True)  # local development: the API runs jobs itself
    assert monitoring.readiness(repo)[0] is True


def test_worker_records_heartbeats(monkeypatch, tmp_path):
    from app.services.job_queue import JobQueue
    from app.worker import Worker

    db = str(tmp_path / "w.db")
    seen = []
    monkeypatch.setattr(monitoring.MonitoringRepository, "heartbeat", lambda self, name, kind, info=None: seen.append((name, kind)))
    w = Worker(queue=JobQueue(db), worker_id="worker-test", schedule_trigger_polls=False)
    w.tick()
    w.tick()  # throttled
    assert seen == [("worker-test", "worker")]


def test_ready_endpoint_and_metrics_are_protected(monkeypatch):
    client = TestClient(main.create_app())
    res = client.get("/health/ready")
    assert res.status_code in (200, 503) and set(res.json()) == {"status", "checks"}

    monkeypatch.setattr(config, "METRICS_TOKEN", "")
    assert client.get("/metrics").status_code == 404  # off unless configured
    monkeypatch.setattr(config, "METRICS_TOKEN", "metrics-secret-123")
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401

    client.get("/api/workflows/specifications/wf-does-not-exist")  # an id in the URL
    body = client.get("/metrics", headers={"Authorization": "Bearer metrics-secret-123"}).text
    assert "workflowos_http_requests_total" in body and "workflowos_jobs" in body and "workflowos_ready" in body
    # routes are reported by template, so ids (and anything personal) never become label values
    assert 'route="/api/workflows/specifications/{workflow_id}"' in body and "wf-does-not-exist" not in body
    assert "workflowos_http_request_duration_seconds_bucket" in body


def test_system_overview_lists_what_needs_attention():
    from app.services.job_queue import JobQueue, JobStatus

    queue = JobQueue()
    job = queue.enqueue("execute_plan", {"execution_plan_id": "p"}, created_by="t")
    claimed = queue.claim("w-sys", 60, job_id=job.job_id)
    queue.mark_side_effects(claimed.job_id)
    assert queue.fail(claimed.job_id, "w-sys", "boom", transient=True) == JobStatus.NEEDS_ATTENTION

    data = TestClient(main.create_app()).get("/api/system").json()
    assert {"ready", "checks", "workers", "jobs", "needs_attention", "triggers", "alerts"} <= set(data)
    assert any(j["job_id"] == job.job_id for j in data["needs_attention"])
    assert data["database"] in ("sqlite", "postgresql")


# --------------------------------------------------------------------- alerts


class _Recorder:
    sent = []

    def __init__(self, *a, **k):
        pass

    def send_notification(self, channel=None, text=""):
        _Recorder.sent.append((channel, text))


@pytest.fixture
def slack_alerts(tmp_path, monkeypatch):
    store = CredentialStore(str(tmp_path / "creds.db"), Fernet.generate_key())
    store.put(SLACK, {"bot_token": "xoxb-x"}, {"channel_id": "C0MAIN0001"})
    set_credential_store(store)
    _Recorder.sent = []
    import app.services.slack_client as slack_client

    monkeypatch.setattr(slack_client, "SlackApiClient", _Recorder)
    yield store
    set_credential_store(None)


def test_no_alerts_without_a_channel(slack_alerts):
    alerts.job_needs_attention("execute_plan", "job-1", "boom")
    assert _Recorder.sent == []


def test_alerts_go_to_the_alert_channel_without_personal_data(slack_alerts):
    slack_alerts.update_metadata(SLACK, {"alert_channel_id": "C0ALERTS01", "alert_on_pending": False})
    alerts.job_needs_attention("execute_run", "job-1", "worker died")
    alerts.run_problem("Replacement requests", "run-1", "FAILED", "CRM unreachable")
    alerts.runs_waiting("Invoices", 3)  # turned off
    assert [c for c, _ in _Recorder.sent] == ["C0ALERTS01", "C0ALERTS01"]
    assert "needs a person" in _Recorder.sent[0][1] and "#system" in _Recorder.sent[0][1]
    assert "'Replacement requests' ended failed" in _Recorder.sent[1][1]


def test_trigger_alerts_once_when_it_starts_failing(slack_alerts, tmp_path):
    from unittest.mock import MagicMock

    from app.models.automation import CreateTriggerRequest
    from app.repositories.automation_repository import AutomationRepository
    from app.repositories.canonical_repository import CanonicalWorkflowRepository
    from app.services.gmail_client import GmailApiClient
    from app.services.reference_workflow import build_reference_spec
    from app.services.trigger_service import TriggerService
    from app.models.canonical import ApprovalState

    slack_alerts.update_metadata(SLACK, {"alert_channel_id": "C0ALERTS01"})
    db = str(tmp_path / "t.db")
    specs = CanonicalWorkflowRepository(db)
    spec = specs.save(build_reference_spec(approval_state=ApprovalState.APPROVED, reviewed_by="a"))
    gmail = MagicMock(spec=GmailApiClient)
    gmail.is_configured.return_value = True
    gmail.is_authenticated.return_value = False  # disconnected
    svc = TriggerService(repo=AutomationRepository(db), spec_repo=specs, gmail_client=gmail)
    trigger = svc.create_trigger(CreateTriggerRequest(name="Invoices", workflow_id=spec.workflow_id, gmail_query="has:attachment"))
    svc.poll(trigger.trigger_id)
    svc.poll(trigger.trigger_id)  # still failing: no second alert
    assert len(_Recorder.sent) == 1 and "'Invoices' cannot check Gmail" in _Recorder.sent[0][1]


def test_alert_settings_api(slack_alerts, monkeypatch):
    from app.services import integrations as integrations_module

    monkeypatch.setattr(integrations_module, "_service", integrations_module.IntegrationService(store=slack_alerts))
    client = TestClient(main.create_app())
    assert client.put("/api/integrations/slack/alerts", json={"channel_id": "not a channel!"}).status_code == 400
    saved = client.put("/api/integrations/slack/alerts", json={"channel_id": "C0ALERTS01", "notify_pending": False}).json()
    assert saved["slack"]["alert_channel_id"] == "C0ALERTS01" and saved["slack"]["alert_on_pending"] is False
    assert slack_alerts.get(SLACK).secret["bot_token"] == "xoxb-x"  # the token is untouched
    off = client.put("/api/integrations/slack/alerts", json={"channel_id": ""}).json()
    assert off["slack"]["alert_channel_id"] is None

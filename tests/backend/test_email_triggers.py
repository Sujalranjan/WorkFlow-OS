"""Email triggers, per-run approval, and needs-intervention pause/resume.

Covers:
- Trigger creation is limited to approved workflows that start with a Gmail search.
- Polling only queues PENDING_APPROVAL runs (no execution), is scoped by `after:<active_since>`,
  and the runs table acts as a processed-email ledger (same email never queued twice).
- Approving a run plans it for the exact triggering message (TRIGGER_MESSAGE selection),
  executes it, verifies it and updates learning; a second approval cannot run it again.
- find_customer pauses the run (NEEDS_INPUT) when the CRM has no match or several matches;
  resuming with a person's choice continues the same execution from that step.
- Rejecting a paused run cancels its execution; resume re-checks workflow approval.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
import pytest

from app.models.automation import CreateTriggerRequest, RunStatus
from app.models.canonical import ApprovalMetadata, ApprovalState
from app.models.crm import CrmCustomer, CrmSearchResult
from app.models.execution import ExecutionOverallStatus, ExecutionStepStatus
from app.models.gmail import GmailAttachmentInfo, GmailMessageSummary, GmailSearchResult
from app.models.slack import SlackNotificationResult
from app.repositories.automation_repository import AutomationRepository
from app.services.crm_client import CrmApiClient
from app.services.executors.crm_executor import CrmApiExecutor, _pick_customer
from app.services.executors.gmail_executor import GmailApiExecutor
from app.services.executors.slack_executor import SlackApiExecutor
from app.services.gmail_client import GmailApiClient
from app.services.phase16_workflow import Phase16Orchestrator
from app.services.slack_client import SlackApiClient
from app.services.trigger_service import TriggerError, TriggerService
from app.services.verifiers.crm_verifier import CrmVerificationStrategy
from app.services.verifiers.gmail_verifier import GmailVerificationStrategy
from app.services.verifiers.slack_verifier import SlackVerificationStrategy

QUERY = 'subject:"Customer Replacement Request" has:attachment'


def _customer(cid="cust-001", email="rahul.sharma@example.com", status="pending_replacement"):
    return CrmCustomer(
        customer_id=cid,
        name="Rahul Sharma",
        email=email,
        company="Acme Corp",
        status=status,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-09-27T10:00:00Z",
    )


def _message(mid="msg-1", sender="Rahul Sharma <rahul.sharma@example.com>"):
    return GmailMessageSummary(
        message_id=mid,
        thread_id=f"thd-{mid}",
        subject="Customer Replacement Request - ORD-1",
        sender=sender,
        snippet="Please replace the damaged unit",
        has_attachments=True,
        attachments=[GmailAttachmentInfo(attachment_id=f"att-{mid}", filename="invoice.pdf", size_bytes=18)],
    )


class Harness:
    """Phase 16 workflow + TriggerService wired to mocked Gmail/CRM/Slack clients."""

    def __init__(self, tmp_path, approved=True):
        self.orch = Phase16Orchestrator()
        self.spec = self.orch.prepare_workflow(auto_approve=approved, reviewer="Ops Lead")

        self.gmail = MagicMock(spec=GmailApiClient)
        self.gmail.is_configured.return_value = True
        self.gmail.is_authenticated.return_value = True
        self.gmail.download_attachment.return_value = (
            b"%PDF-1.4 trigger test",
            {"filename": "invoice.pdf", "mime_type": "application/pdf"},
        )
        self.gmail.get_message_summary.side_effect = lambda mid: _message(mid)

        self.crm = MagicMock(spec=CrmApiClient)
        self.crm.find_customer.return_value = _customer()
        self.crm.update_customer.side_effect = lambda cid, upd: _customer(cid, status=upd.get("status", "x"))
        self.crm.get_customer.side_effect = lambda cid: _customer(cid, status="replacement_processed")

        self.slack = MagicMock(spec=SlackApiClient)
        self.slack.default_channel_id = "C0123456789"
        self.slack.send_notification.return_value = SlackNotificationResult(
            success=True, channel="C0123456789", ts="1710000000.000100"
        )
        self.slack.verify_message.return_value = (True, {"ts": "1710000000.000100"}, "Verified")

        reg = self.orch.engine.registry
        reg.register(GmailApiExecutor(client=self.gmail))
        reg.register(CrmApiExecutor(client=self.crm))
        reg.register(SlackApiExecutor(client=self.slack))
        vreg = self.orch.verification_engine.strategy_registry
        vreg.register(GmailVerificationStrategy())
        vreg.register(CrmVerificationStrategy(client=self.crm))
        vreg.register(SlackVerificationStrategy(client=self.slack))

        self.service = TriggerService(
            repo=AutomationRepository(db_path=str(tmp_path / "automation.db")),
            spec_repo=self.orch.canonical_repo,
            plan_repo=self.orch.plan_repo,
            exec_repo=self.orch.exec_repo,
            planner=self.orch.planner,
            engine=self.orch.engine,
            verification_engine=self.orch.verification_engine,
            learning_engine=self.orch.learning_engine,
            gmail_client=self.gmail,
        )

    def trigger(self):
        return self.service.create_trigger(CreateTriggerRequest(workflow_id=self.spec.workflow_id, gmail_query=QUERY))

    def queue(self, *messages):
        self.gmail.search_messages.return_value = GmailSearchResult(
            query=QUERY, total_found=len(messages), messages=list(messages)
        )
        trigger = self.trigger()
        result = self.service.poll(trigger.trigger_id)
        self.gmail.search_messages.reset_mock()
        return trigger, result


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path)


# ---------------------------------------------------------------- triggers


def test_trigger_requires_approved_workflow(tmp_path):
    h = Harness(tmp_path, approved=False)
    with pytest.raises(TriggerError, match="only approved workflows"):
        h.trigger()
    with pytest.raises(TriggerError, match="not found"):
        h.service.create_trigger(CreateTriggerRequest(workflow_id="wf-missing", gmail_query=QUERY))


def test_poll_queues_pending_runs_without_executing(h):
    trigger, result = h.queue(_message("msg-2"), _message("msg-1"))

    assert result.error is None and result.matched == 2
    assert [r.source_email.message_id for r in result.new_runs] == ["msg-1", "msg-2"]  # arrival order
    assert all(r.status == RunStatus.PENDING_APPROVAL for r in result.new_runs)
    assert result.new_runs[0].source_email.attachment_names == ["invoice.pdf"]

    # Nothing executed: no CRM/Slack calls, no execution records.
    h.crm.find_customer.assert_not_called()
    h.slack.send_notification.assert_not_called()
    assert h.orch.exec_repo.list_all(workflow_id=h.spec.workflow_id) == []


def test_poll_scopes_query_to_trigger_start_and_never_requeues(h):
    trigger, _ = h.queue(_message("msg-1"))
    h.gmail.search_messages.return_value = GmailSearchResult(
        query=QUERY, total_found=2, messages=[_message("msg-new"), _message("msg-1")]
    )
    second = h.service.poll(trigger.trigger_id)

    sent_query = h.gmail.search_messages.call_args.kwargs["query"]
    assert sent_query == f"({QUERY}) after:{trigger.active_since}"
    assert [r.source_email.message_id for r in second.new_runs] == ["msg-new"]
    assert len(h.service.repo.list_runs(trigger_id=trigger.trigger_id)) == 2


def test_poll_records_error_when_gmail_not_authorized(h):
    h.gmail.is_authenticated.return_value = False
    trigger = h.trigger()
    result = h.service.poll(trigger.trigger_id)
    assert result.new_runs == [] and "not authorized" in result.error
    assert h.service.repo.get_trigger(trigger.trigger_id).last_error == result.error
    h.gmail.search_messages.assert_not_called()


def test_poll_due_respects_interval_and_enabled_flag(h):
    h.gmail.search_messages.return_value = GmailSearchResult(query=QUERY, total_found=0, messages=[])
    trigger = h.trigger()
    assert len(h.service.poll_due()) == 1  # never polled yet
    assert h.service.poll_due() == []  # interval not elapsed
    trigger = h.service.repo.get_trigger(trigger.trigger_id)
    trigger.last_polled_at = "2000-01-01T00:00:00+00:00"
    trigger.enabled = False
    h.service.repo.save_trigger(trigger)
    assert h.service.poll_due() == []  # disabled


# -------------------------------------------------------------- approvals


def test_approve_runs_exact_triggering_email_then_verifies(h):
    _, polled = h.queue(_message("msg-target"))
    run = h.service.approve_run(polled.new_runs[0].run_id, "ops@example.com")

    assert run.status == RunStatus.COMPLETED, run.error
    assert run.decided_by == "ops@example.com"
    assert run.verification_status == "VERIFIED"

    record = h.orch.exec_repo.get_by_id(run.execution_id)
    search = record.step_results[0]
    assert search.output["selection_rule"] == "TRIGGER_MESSAGE"
    assert search.output["selected_message_id"] == "msg-target"
    assert record.step_results[1].output["message_id"] == "msg-target"
    h.gmail.get_message_summary.assert_called_once_with("msg-target")
    h.gmail.search_messages.assert_not_called()  # never re-searched, so it cannot drift to another email
    assert h.crm.find_customer.call_args.kwargs["email"] == "rahul.sharma@example.com"

    profile = h.orch.learning_repo.get_profile(h.spec.workflow_id)
    assert profile is not None and profile.total_executions >= 1


def test_run_cannot_be_approved_twice(h):
    _, polled = h.queue(_message())
    run_id = polled.new_runs[0].run_id
    h.service.approve_run(run_id, "ops")
    with pytest.raises(TriggerError, match="no longer awaiting approval"):
        h.service.approve_run(run_id, "ops")
    assert h.slack.send_notification.call_count == 1


def test_approve_fails_closed_when_workflow_was_unapproved(h):
    _, polled = h.queue(_message())
    spec = h.orch.canonical_repo.get_by_id(h.spec.workflow_id)
    spec.approval_state = ApprovalMetadata(state=ApprovalState.REJECTED, reviewed_by="sec")
    h.orch.canonical_repo.save(spec)

    run = h.service.approve_run(polled.new_runs[0].run_id, "ops")
    assert run.status == RunStatus.FAILED and "APPROVED" in run.error
    h.gmail.get_message_summary.assert_not_called()


# ---------------------------------------------------------- intervention


def test_unknown_customer_pauses_then_resumes_with_selected_record(h):
    h.crm.find_customer.return_value = CrmSearchResult(query="x", total_found=0, customers=[])
    _, polled = h.queue(_message(sender="unknown@nowhere.example"))
    run = h.service.approve_run(polled.new_runs[0].run_id, "ops")

    assert run.status == RunStatus.NEEDS_INPUT
    assert run.intervention["code"] == "NO_MATCH"
    assert run.intervention["step"] == "find_customer"
    assert "selected_customer_id" in run.intervention["accepted_inputs"]
    h.crm.update_customer.assert_not_called()
    h.slack.send_notification.assert_not_called()
    paused = h.orch.exec_repo.get_by_id(run.execution_id)
    assert paused.status == ExecutionOverallStatus.NEEDS_INPUT and paused.paused_step_index == 2
    assert paused.end_time is None

    resumed = h.service.resume_run(run.run_id, {"selected_customer_id": "cust-777"}, "ops")
    assert resumed.status == RunStatus.COMPLETED, resumed.error
    assert resumed.execution_id == run.execution_id  # same execution continued
    h.crm.update_customer.assert_called_once()
    assert h.crm.update_customer.call_args.args[0] == "cust-777"
    assert h.slack.send_notification.call_count == 1

    record = h.orch.exec_repo.get_by_id(run.execution_id)
    statuses = [(s.action_name, s.status) for s in record.step_results]
    assert ("find_customer", ExecutionStepStatus.NEEDS_INPUT) in statuses  # pause kept in the audit trail
    assert statuses[-1] == ("send_notification", ExecutionStepStatus.SUCCESS)
    assert sum(1 for _, st in statuses if st == ExecutionStepStatus.SUCCESS) == 5


def test_multiple_customers_pause_with_candidates_and_reject_bad_input(h):
    h.crm.find_customer.return_value = CrmSearchResult(
        query="acme",
        total_found=2,
        customers=[_customer("cust-a", "a@acme.example"), _customer("cust-b", "b@acme.example")],
    )
    _, polled = h.queue(_message(sender="someone@acme.example"))
    run = h.service.approve_run(polled.new_runs[0].run_id, "ops")

    assert run.status == RunStatus.NEEDS_INPUT and run.intervention["code"] == "MULTIPLE_MATCHES"
    assert [c["customer_id"] for c in run.intervention["candidates"]] == ["cust-a", "cust-b"]

    with pytest.raises(TriggerError, match="not accepted"):
        h.service.resume_run(run.run_id, {"customer_status": "closed"}, "ops")
    assert h.service.repo.get_run(run.run_id).status == RunStatus.NEEDS_INPUT
    h.crm.update_customer.assert_not_called()


def test_reject_paused_run_cancels_execution(h):
    h.crm.find_customer.return_value = CrmSearchResult(query="x", total_found=0, customers=[])
    _, polled = h.queue(_message())
    run = h.service.approve_run(polled.new_runs[0].run_id, "ops")

    rejected = h.service.reject_run(run.run_id, "ops")
    assert rejected.status == RunStatus.REJECTED
    assert h.orch.exec_repo.get_by_id(run.execution_id).status == ExecutionOverallStatus.CANCELLED
    with pytest.raises(TriggerError):
        h.service.resume_run(run.run_id, {"selected_customer_id": "cust-1"}, "ops")


def test_resume_rechecks_workflow_approval(h):
    h.crm.find_customer.return_value = CrmSearchResult(query="x", total_found=0, customers=[])
    _, polled = h.queue(_message())
    run = h.service.approve_run(polled.new_runs[0].run_id, "ops")

    spec = h.orch.canonical_repo.get_by_id(h.spec.workflow_id)
    spec.approval_state = ApprovalMetadata(state=ApprovalState.REJECTED, reviewed_by="sec")
    h.orch.canonical_repo.save(spec)

    with pytest.raises(TriggerError, match="policy"):
        h.service.resume_run(run.run_id, {"selected_customer_id": "cust-1"}, "ops")
    h.crm.update_customer.assert_not_called()


# ------------------------------------------------------------ CRM selection


def test_pick_customer_only_resolves_exact_matches():
    a = {"customer_id": "c-1", "email": "a@x.example"}
    b = {"customer_id": "c-2", "email": "ab@x.example"}
    assert _pick_customer([], "a@x.example", None) == (None, "NO_MATCH")
    assert _pick_customer([a], "anything", None) == (a, "")
    assert _pick_customer([a, b], None, "A@x.example") == (a, "")  # exact email wins over fuzzy hit
    assert _pick_customer([a, b], "x.example", None) == (None, "MULTIPLE_MATCHES")


# ------------------------------------------------------------------- API


def test_automation_api_validation_and_listing(h, monkeypatch):
    import app.api.automation as automation_api
    from app.main import app

    monkeypatch.setattr(automation_api, "_service", h.service)
    client = TestClient(app)

    res = client.post("/api/automation/triggers", json={"workflow_id": "wf-missing", "gmail_query": QUERY})
    assert res.status_code == 400

    res = client.post(
        "/api/automation/triggers",
        json={"workflow_id": h.spec.workflow_id, "gmail_query": QUERY, "poll_interval_seconds": 5},
    )
    assert res.status_code == 422  # below the 30s minimum

    h.gmail.search_messages.return_value = GmailSearchResult(query=QUERY, total_found=1, messages=[_message()])
    trig = client.post("/api/automation/triggers", json={"workflow_id": h.spec.workflow_id, "gmail_query": QUERY})
    assert trig.status_code == 201
    polled = client.post(f"/api/automation/triggers/{trig.json()['trigger_id']}/poll").json()
    run_id = polled["new_runs"][0]["run_id"]

    inbox = client.get("/api/automation/runs", params={"status": "PENDING_APPROVAL,NEEDS_INPUT"}).json()
    assert [r["run_id"] for r in inbox] == [run_id]
    assert client.get("/api/automation/runs", params={"status": "BOGUS"}).status_code == 400

    assert client.post(f"/api/automation/runs/{run_id}/reject", json={"decided_by": "ops"}).json()["status"] == "REJECTED"
    assert client.post(f"/api/automation/runs/{run_id}/approve").status_code == 409
    assert client.get("/api/automation/runs/run-missing").status_code == 404

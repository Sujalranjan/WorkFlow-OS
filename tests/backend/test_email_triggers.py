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
from app.services.reference_workflow import WorkflowOrchestrator
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
    """workflow + TriggerService wired to mocked Gmail/CRM/Slack clients."""

    def __init__(self, tmp_path, approved=True):
        self.orch = WorkflowOrchestrator()
        self.spec = self.orch.prepare_workflow(auto_approve=approved, reviewer="Ops Lead")

        self.gmail = MagicMock(spec=GmailApiClient)
        self.gmail.is_configured.return_value = True
        self.gmail.is_authenticated.return_value = True
        self.gmail.download_attachment.return_value = (
            b"%PDF-1.4 trigger test",
            {"filename": "invoice.pdf", "mime_type": "application/pdf"},
        )
        # A fake mailbox: ids newest first; the change log reports new mail whenever the mailbox changed.
        self.mail = {}
        self.history = 100
        self.gmail.get_message_summary.side_effect = lambda mid: self.mail.get(mid) or _message(mid)
        self.gmail.list_message_ids.side_effect = lambda query, limit=5000: list(self.mail)[:limit]
        self.gmail.current_history_id.side_effect = lambda: str(self.history)
        self.gmail.messages_added_since.side_effect = lambda start: (int(start) < self.history, str(self.history))

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

    def mailbox(self, *messages):
        """Set the messages matching the trigger query (newest first); counts as new mail arriving."""
        self.mail = {m.message_id: m for m in messages}
        self.history += 1

    def queue(self, *messages):
        self.mailbox(*messages)
        trigger = self.trigger()
        result = self.service.poll(trigger.trigger_id)
        self.gmail.list_message_ids.reset_mock()
        self.gmail.get_message_summary.reset_mock()
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
    trigger, first = h.queue(_message("msg-1"))
    assert h.service.repo.get_trigger(trigger.trigger_id).history_id == str(h.history)
    h.mailbox(_message("msg-new"), _message("msg-1"))
    second = h.service.poll(trigger.trigger_id)

    sent_query = h.gmail.list_message_ids.call_args.kwargs["query"]
    assert sent_query == f"({QUERY}) after:{trigger.active_since}"  # never earlier than the trigger's start
    assert [r.source_email.message_id for r in second.new_runs] == ["msg-new"]
    assert len(h.service.repo.list_runs(trigger_id=trigger.trigger_id)) == 2


def test_poll_without_new_mail_does_not_search(h):
    trigger, _ = h.queue(_message("msg-1"))
    quiet = h.service.poll(trigger.trigger_id)  # the change log reports nothing new
    assert quiet.unchanged is True and quiet.new_runs == []
    h.gmail.list_message_ids.assert_not_called()
    h.gmail.get_message_summary.assert_not_called()


def test_large_backlog_is_never_skipped(h):
    """Regression: polling used to read only the newest 25 matches, silently skipping older ones."""
    from app.services.trigger_service import MAX_NEW_RUNS_PER_POLL

    trigger, _ = h.queue()
    h.mailbox(*[_message(f"msg-{n:03d}") for n in range(119, -1, -1)])  # 120 new emails, newest first

    queued = []
    first = h.service.poll(trigger.trigger_id)
    queued += [r.source_email.message_id for r in first.new_runs]
    assert len(first.new_runs) == MAX_NEW_RUNS_PER_POLL and first.backlog == 120 - MAX_NEW_RUNS_PER_POLL
    assert "more matching email" in h.service.repo.get_trigger(trigger.trigger_id).last_note
    while True:
        result = h.service.poll(trigger.trigger_id)
        queued += [r.source_email.message_id for r in result.new_runs]
        if not result.backlog:
            break

    assert queued == [f"msg-{n:03d}" for n in range(120)]  # every email, once, oldest first
    assert h.service.poll(trigger.trigger_id).unchanged is True


def test_later_polls_search_only_since_the_last_sync(h, monkeypatch):
    import app.services.trigger_service as ts

    trigger, _ = h.queue(_message("msg-1"))
    synced = h.service.repo.get_trigger(trigger.trigger_id).synced_until
    assert synced is not None
    h.mailbox(_message("msg-2"), _message("msg-1"))
    h.service.poll(trigger.trigger_id)
    query = h.gmail.list_message_ids.call_args.kwargs["query"]
    expected_since = max(trigger.active_since, synced - ts.SYNC_OVERLAP_SECONDS)
    assert query == f"({QUERY}) after:{expected_since}"


def test_expired_gmail_history_falls_back_to_a_full_search(h):
    from app.services.gmail_client import GmailHistoryExpired

    trigger, _ = h.queue(_message("msg-1"))
    h.mailbox(_message("msg-2"), _message("msg-1"))
    h.gmail.messages_added_since.side_effect = GmailHistoryExpired("too old")
    result = h.service.poll(trigger.trigger_id)
    assert [r.source_email.message_id for r in result.new_runs] == ["msg-2"]
    assert "history had expired" in h.service.repo.get_trigger(trigger.trigger_id).last_note


def test_gmail_failure_mid_poll_keeps_the_sync_position(h):
    trigger, _ = h.queue(_message("msg-1"))
    before = h.service.repo.get_trigger(trigger.trigger_id)
    h.mailbox(_message("msg-2"), _message("msg-1"))
    h.gmail.get_message_summary.side_effect = RuntimeError("Gmail 503")
    failed = h.service.poll(trigger.trigger_id)
    after = h.service.repo.get_trigger(trigger.trigger_id)
    assert "Gmail search failed" in failed.error
    assert (after.history_id, after.synced_until) == (before.history_id, before.synced_until)

    h.gmail.get_message_summary.side_effect = lambda mid: h.mail.get(mid)
    assert [r.source_email.message_id for r in h.service.poll(trigger.trigger_id).new_runs] == ["msg-2"]


def test_poll_records_error_when_gmail_not_authorized(h):
    h.gmail.is_authenticated.return_value = False
    trigger = h.trigger()
    result = h.service.poll(trigger.trigger_id)
    assert result.new_runs == [] and "not connected" in result.error
    assert h.service.repo.get_trigger(trigger.trigger_id).last_error == result.error
    h.gmail.list_message_ids.assert_not_called()


def test_poll_due_respects_interval_and_enabled_flag(h):
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

    h.mailbox(_message())
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


# ---------------------------------------------------------- background jobs


def test_api_approval_is_claimed_in_the_request_and_executed_by_the_worker(h, monkeypatch):
    from app.api import automation as automation_api
    from app.main import app

    monkeypatch.setattr(automation_api, "_service", h.service)
    client = TestClient(app)
    _, result = h.queue(_message("msg-api"))
    run_id = result.new_runs[0].run_id

    res = client.post(f"/api/automation/runs/{run_id}/approve")
    assert res.status_code == 202
    # Tests run jobs inline, so the worker has already finished it.
    assert client.get(f"/api/automation/runs/{run_id}").json()["status"] == RunStatus.COMPLETED.value
    job = next(j for j in client.get("/api/jobs", params={"kind": "execute_run"}).json() if j["payload"]["run_id"] == run_id)
    assert job["status"] == "succeeded" and job["side_effects_started"] is True and job["max_attempts"] == 1
    assert client.post(f"/api/automation/runs/{run_id}/approve").status_code == 409  # cannot run twice
    assert client.post(f"/api/jobs/{job['job_id']}/dismiss").status_code == 409  # nothing to dismiss


def test_worker_dying_mid_run_flags_the_run_instead_of_replaying_it(h, monkeypatch):
    import time

    from app.api import automation as automation_api
    from app.main import app
    from app.models.jobs import JobStatus
    from app.services.job_queue import JobQueue
    from app.worker import Worker

    monkeypatch.setattr(automation_api, "_service", h.service)
    _, result = h.queue(_message("msg-crash"))
    run_id = result.new_runs[0].run_id
    h.service.claim_for_approval(run_id, "ops")

    queue = JobQueue()
    job = queue.enqueue("execute_run", {"run_id": run_id, "decided_by": "ops"}, max_attempts=1)
    queue.claim("worker-that-dies", lease_seconds=0.01, job_id=job.job_id)
    queue.mark_side_effects(job.job_id)  # it had started changing things
    time.sleep(0.05)

    Worker(queue=queue, worker_id="survivor", schedule_trigger_polls=False).tick()
    assert queue.get(job.job_id).status == JobStatus.NEEDS_ATTENTION
    run = h.service.repo.get_run(run_id)
    assert run.status == RunStatus.NEEDS_ATTENTION and "external systems" in run.error
    h.crm.update_customer.assert_not_called()  # nothing was replayed

    client = TestClient(app)
    assert client.post(f"/api/jobs/{job.job_id}/dismiss").json()["status"] == "dismissed"

"""slack.reply_in_thread: client, executor, verifier, observation, and a discovered Gmail -> Slack ->
shared folder -> Slack thread reply routine run end to end against an in-memory fake Slack API."""

import json
import os
from unittest.mock import MagicMock

from cryptography.fernet import Fernet
import httpx
import pytest

from app.integrations.slack import REPLY_IN_THREAD, SEND_NOTIFICATION, classify_send
from app.models.event import ActivityEvent, ActivityEventType
from app.models.execution import ExecutionContext, ExecutionMode, ExecutionOverallStatus, ExecutionStepStatus
from app.models.verification import VerificationStatus
from app.services.credential_store import SHARED_FOLDER, CredentialStore, set_credential_store
from app.services.executors.slack_executor import SlackApiExecutor
from app.services.slack_client import SlackApiClient
from app.services.verifiers.slack_verifier import SlackVerificationStrategy

TOKEN = "xoxb-test-thread-token"
DEFAULT_CHANNEL = "C0DEFAULT01"


class FakeSlack:
    """chat.postMessage, conversations.history and conversations.replies over an in-memory channel log."""

    def __init__(self):
        self.messages = []  # {"channel", "ts", "text", "thread_ts"?}
        self.posts = []
        self._next = 1000

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        path = request.url.path
        if path.endswith("/chat.postMessage"):
            body = json.loads(request.content)
            self.posts.append(body)
            parent = body.get("thread_ts")
            if parent and not any(m["ts"] == parent and m["channel"] == body["channel"] for m in self.messages):
                return httpx.Response(200, json={"ok": False, "error": "thread_not_found"})
            self._next += 1
            msg = {"channel": body["channel"], "ts": f"{self._next}.000100", "text": body["text"]}
            if parent:
                msg["thread_ts"] = parent
            self.messages.append(msg)
            return httpx.Response(200, json={"ok": True, "channel": body["channel"], "ts": msg["ts"], "message": msg})
        params = request.url.params
        if path.endswith("/conversations.history"):  # top-level messages only, like Slack
            found = [m for m in self.messages if m["channel"] == params["channel"] and m["ts"] == params["latest"] and "thread_ts" not in m]
            return httpx.Response(200, json={"ok": True, "messages": found})
        if path.endswith("/conversations.replies"):
            parent = params["ts"]
            thread = [m for m in self.messages if m["channel"] == params["channel"] and (m["ts"] == parent or m.get("thread_ts") == parent)]
            lo, hi = params.get("oldest"), params.get("latest")
            thread = [m for m in thread if (not lo or m["ts"] >= lo) and (not hi or m["ts"] <= hi)]
            return httpx.Response(200, json={"ok": True, "messages": thread})
        return httpx.Response(200, json={"ok": False, "error": "unknown_method"})

    def client(self, channel=DEFAULT_CHANNEL):
        return SlackApiClient(bot_token=TOKEN, default_channel_id=channel, http_client=httpx.Client(transport=httpx.MockTransport(self.handler)))


@pytest.fixture
def fake():
    return FakeSlack()


def _step(action, params=None):
    from app.models.canonical import RiskCategory, RiskLevel, StepRisk
    from app.models.execution_plan import ExecutionStrategy, ExpectedStateChange, PlannedStep, StepExecutionStrategy

    return PlannedStep(
        plan_step_id=f"plan-{action}",
        source_canonical_step_id="c",
        source_semantic_step_id="s",
        source_dna_step_key=f"slack:{action}",
        application="Slack",
        action=action,
        description=action,
        resolved_parameters=params or {},
        execution_strategy=StepExecutionStrategy(strategy=ExecutionStrategy.API, reason="t", target_technology="Slack"),
        risk=StepRisk(step_id="c", application="Slack", action=action, risk_level=RiskLevel.MEDIUM,
                      risk_category=RiskCategory.COMMUNICATION, reason="t"),
        expected_result="",
        evidence_reference="",
        state_change=ExpectedStateChange(target_system="Slack", entity_or_property="message", before_state="", expected_after_state=""),
        catalog_action=f"slack.{action}",
    )


def _ctx(tmp_path, dry_run=False, **params):
    return ExecutionContext(
        execution_id="exec-th", workflow_id="wf", execution_plan_id="plan", sandbox_root=str(tmp_path),
        execution_mode=ExecutionMode.DRY_RUN if dry_run else ExecutionMode.LIVE, dry_run=dry_run, resolved_parameters=params,
    )


def test_reply_goes_under_the_runs_own_message_in_its_channel(fake, tmp_path):
    client = fake.client()
    parent = client.send_notification(channel="C0OTHER0001", text="Received invoice_101.pdf")
    ex = SlackApiExecutor(client=client)

    res = ex.execute(_step("reply_in_thread", {"thread_ts": "{slack_ts}"}),
                     _ctx(tmp_path, slack_ts=parent.ts, slack_channel="C0OTHER0001", saved_file_name="invoice_101.pdf"))
    assert res.status == ExecutionStepStatus.SUCCESS, res.error
    assert fake.posts[-1]["thread_ts"] == parent.ts
    assert fake.posts[-1]["channel"] == "C0OTHER0001"  # the parent's channel, not the default one
    assert "Saved to the shared folder as: invoice_101.pdf" in fake.posts[-1]["text"]
    assert res.output["operation"] == "reply_in_thread" and res.output["thread_ts"] == parent.ts

    checker = SlackVerificationStrategy(client=client)
    [check] = checker.build_checks("exec-th", _step("reply_in_thread"), res, str(tmp_path))
    assert check.check_type == "slack_thread_reply_delivered"
    assert checker.verify(check, str(tmp_path)).status == VerificationStatus.VERIFIED


def test_reply_without_an_earlier_message_is_blocked(fake, tmp_path):
    ex = SlackApiExecutor(client=fake.client())
    res = ex.execute(_step("reply_in_thread", {"thread_ts": "{slack_ts}"}), _ctx(tmp_path, customer_name="Rahul"))
    assert res.status == ExecutionStepStatus.BLOCKED and "posted earlier" in res.error
    assert fake.posts == []  # never falls back to a new top-level message

    dry = ex.execute(_step("reply_in_thread", {"thread_ts": "{slack_ts}"}), _ctx(tmp_path, dry_run=True))
    assert dry.status == ExecutionStepStatus.SUCCESS and dry.output["status"] == "SIMULATED" and fake.posts == []


def test_verify_reply_rejects_missing_or_top_level_messages(fake):
    client = fake.client()
    parent = client.send_notification(text="parent")
    other = client.send_notification(text="not a reply")
    reply = client.send_notification(text="reply", thread_ts=parent.ts)
    assert client.verify_reply(DEFAULT_CHANNEL, parent.ts, reply.ts)[0] is True
    assert client.verify_reply(DEFAULT_CHANNEL, parent.ts, other.ts)[0] is False
    assert client.verify_reply(DEFAULT_CHANNEL, parent.ts, parent.ts)[0] is False  # the parent is not its own reply
    assert client.verify_reply(DEFAULT_CHANNEL, parent.ts, "9999.000100")[0] is False


def test_thread_replies_are_recognised_separately():
    url = "https://app.slack.com/client/T0WORKFLOW/C0123456789"
    reply = ActivityEvent(event_type=ActivityEventType.FORM_SUBMITTED, metadata={"url": url, "form_fields": {"kind": "thread_reply"}})
    send = ActivityEvent(event_type=ActivityEventType.FORM_SUBMITTED, metadata={"url": url, "form_fields": {}})
    assert classify_send(reply).action == REPLY_IN_THREAD and classify_send(reply).parameters == {}
    assert classify_send(send).action == SEND_NOTIFICATION
    look_alike = ActivityEvent(event_type=ActivityEventType.FORM_SUBMITTED,
                               metadata={"url": "https://app.slack.com.evil.example/client/T/C1", "form_fields": {"kind": "thread_reply"}})
    assert classify_send(look_alike) is None


def test_discovered_routine_posts_then_replies_in_the_thread(tmp_path, fake):
    from app.models.gmail import GmailAttachmentInfo, GmailMessageSummary, GmailSearchResult
    from app.repositories.canonical_repository import CanonicalWorkflowRepository
    from app.repositories.execution_plan_repository import ExecutionPlanRepository
    from app.repositories.execution_repository import ExecutionRepository
    from app.repositories.learning_repository import LearningRepository
    from app.repositories.verification_repository import VerificationRepository
    from app.services.canonical_factory import CanonicalWorkflowFactory
    from app.services.execution_engine import ExecutionEngine
    from app.services.execution_planner import ExecutionPlanner
    from app.services.executors.gmail_executor import GmailApiExecutor
    from app.services.gmail_client import GmailApiClient
    from app.services.learning_engine import LearningEngine
    from app.services.observed_sessions import GMAIL_SEARCH, build_observed_thread_events
    from app.services.reference_workflow import WorkflowOrchestrator
    from app.services.semantic_engine import SemanticUnderstandingEngine
    from app.services.semantic_provider import MockSemanticProvider
    from app.services.verification_engine import VerificationEngine
    from app.services.verifiers.gmail_verifier import GmailVerificationStrategy
    from app.services.workflow_discovery import WorkflowDiscoveryEngine
    from app.services.workflow_dna_extractor import WorkflowDNAExtractor
    from app.services.workflow_segmenter import WorkflowSegmenter

    sessions = WorkflowSegmenter().segment(build_observed_thread_events())
    [candidate] = WorkflowDiscoveryEngine().discover_candidates(sessions)
    dna = WorkflowDNAExtractor().extract_dna(candidate, [s for s in sessions if s.session_id in candidate.supporting_session_ids])
    assert [s.catalog_action for s in dna.invariant_steps if s.catalog_action] == [
        "gmail.search_email", "gmail.download_attachment", "slack.send_notification",
        "files.save_to_folder", "slack.reply_in_thread",
    ]
    semantic = SemanticUnderstandingEngine(provider=MockSemanticProvider()).interpret_dna(dna)
    assert semantic.status == "success", semantic.validation_errors
    spec = CanonicalWorkflowFactory().create_specification(dna, semantic.semantic_workflow)

    db = str(tmp_path / "th.db")
    repos = dict(canonical_repo=CanonicalWorkflowRepository(db), plan_repo=ExecutionPlanRepository(db), exec_repo=ExecutionRepository(db))
    verif_repo, learn_repo = VerificationRepository(db), LearningRepository(db)
    engine = ExecutionEngine(**repos, default_sandbox_base=str(tmp_path / "sandbox"))
    orch = WorkflowOrchestrator(
        **repos, verif_repo=verif_repo, learning_repo=learn_repo, engine=engine, planner=ExecutionPlanner(),
        verification_engine=VerificationEngine(exec_repo=repos["exec_repo"], plan_repo=repos["plan_repo"], verif_repo=verif_repo),
        learning_engine=LearningEngine(execution_repo=repos["exec_repo"], verification_repo=verif_repo, learning_repo=learn_repo),
    )
    orch.canonical_repo.save(spec)
    orch.approve_workflow(spec.workflow_id)
    plan = orch.create_plan(spec.workflow_id)
    [reply_step] = [s for s in plan.planned_steps if s.catalog_action == "slack.reply_in_thread"]
    assert reply_step.resolved_parameters == {"thread_ts": "{slack_ts}"}  # this run's own message, never a recorded one

    folder = tmp_path / "shared"
    folder.mkdir()
    store = CredentialStore(str(tmp_path / "creds.db"), Fernet.generate_key())
    store.put(SHARED_FOLDER, {}, {"folder": str(folder)})
    set_credential_store(store)
    try:
        gmail = MagicMock(spec=GmailApiClient)
        gmail.is_configured.return_value = gmail.is_authenticated.return_value = True
        gmail.search_messages.return_value = GmailSearchResult(
            query=GMAIL_SEARCH, total_found=1,
            messages=[GmailMessageSummary(
                message_id="msg-th", thread_id="t", subject="Replacement request", sender="Asha <asha@example.com>",
                has_attachments=True, attachments=[GmailAttachmentInfo(attachment_id="a1", filename="invoice_555.pdf", size_bytes=10)],
            )],
        )
        gmail.download_attachment.return_value = (b"%PDF-1.4 555", {"filename": "invoice_555.pdf", "mime_type": "application/pdf"})
        slack = fake.client()
        orch.engine.registry.register(GmailApiExecutor(client=gmail))
        orch.engine.registry.register(SlackApiExecutor(client=slack))
        orch.verification_engine.strategy_registry.register(GmailVerificationStrategy())
        orch.verification_engine.strategy_registry.register(SlackVerificationStrategy(client=slack))

        record = orch.execute_live(plan.execution_plan_id)
        assert record.status == ExecutionOverallStatus.COMPLETED, record.error_summary
        top, reply = fake.posts
        assert "thread_ts" not in top and top["channel"] == DEFAULT_CHANNEL
        parent_ts = fake.messages[0]["ts"]
        assert reply["thread_ts"] == parent_ts and reply["channel"] == DEFAULT_CHANNEL
        assert "invoice_555.pdf" in reply["text"] and os.listdir(folder) == ["invoice_555.pdf"]

        verification = orch.verify_execution(record.execution_id)
        slack_checks = {c.check_type: c.status for c in verification.checks if c.check_type.startswith("slack_")}
        assert slack_checks == {
            "slack_notification_delivered": VerificationStatus.VERIFIED,
            "slack_thread_reply_delivered": VerificationStatus.VERIFIED,
        }
    finally:
        set_credential_store(None)

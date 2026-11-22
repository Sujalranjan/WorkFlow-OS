"""gmail.add_label: opt-in permission, adds only user labels, executor/verifier, observation, and a
discovered Gmail -> label -> Slack routine run end to end against a fake Gmail API."""

from unittest.mock import MagicMock

from cryptography.fernet import Fernet
import pytest

from app import config
from app.integrations.gmail import ADD_LABEL, classify_label
from app.models.event import ActivityEvent, ActivityEventType
from app.models.execution import ExecutionContext, ExecutionMode, ExecutionOverallStatus, ExecutionStepStatus
from app.models.verification import VerificationStatus
from app.services.credential_store import GMAIL_OPTIONS, GMAIL_TOKEN, CredentialStore, set_credential_store
from app.services.executors.gmail_executor import GmailApiExecutor
from app.services.executors.gmail_label_executor import GmailLabelExecutor
from app.services.gmail_labels import GmailLabeler, labeling_status
from app.services.verifiers.gmail_label_verifier import GmailLabelVerificationStrategy

READONLY, MODIFY = config.GMAIL_SCOPES[0], config.GMAIL_MODIFY_SCOPE


class _Call:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return self._fn()


class FakeGmailService:
    """Stands in for the Gmail API resource: users().labels().list, users().messages().modify/get."""

    def __init__(self):
        self.labels = [
            {"id": "INBOX", "name": "INBOX", "type": "system"},
            {"id": "TRASH", "name": "TRASH", "type": "system"},
            {"id": "SPAM", "name": "SPAM", "type": "system"},
            {"id": "Label_7", "name": "Processed", "type": "user"},
            {"id": "Label_8", "name": "Clients/Acme", "type": "user"},
        ]
        self.message_labels = {"msg-1": ["INBOX", "UNREAD"], "msg-new": ["INBOX"]}
        self.modify_bodies = []

    def users(self):
        return _Users(self)


class _Users:
    def __init__(self, fake):
        self.fake = fake

    def labels(self):
        return _Labels(self.fake)

    def messages(self):
        return _Messages(self.fake)


class _Labels:
    def __init__(self, fake):
        self.fake = fake

    def list(self, userId):
        return _Call(lambda: {"labels": self.fake.labels})


class _Messages:
    def __init__(self, fake):
        self.fake = fake

    def modify(self, userId, id, body):
        def run():
            assert set(body) == {"addLabelIds"}  # never removeLabelIds
            self.fake.modify_bodies.append(body)
            current = self.fake.message_labels[id]
            self.fake.message_labels[id] = current + [i for i in body["addLabelIds"] if i not in current]
            return {"id": id, "labelIds": self.fake.message_labels[id]}

        return _Call(run)

    def get(self, userId, id, format):
        assert format == "minimal"  # never the email's content
        return _Call(lambda: {"id": id, "labelIds": list(self.fake.message_labels[id])})


@pytest.fixture
def gmail():
    return FakeGmailService()


@pytest.fixture
def store(tmp_path):
    s = CredentialStore(str(tmp_path / "creds.db"), Fernet.generate_key())
    set_credential_store(s)
    yield s
    set_credential_store(None)


def _allow(store, granted=(READONLY, MODIFY), opted_in=True):
    store.put(GMAIL_OPTIONS, {}, {"allow_labels": opted_in})
    store.put(GMAIL_TOKEN, {"refresh_token": "r"}, {"account": "ops@example.com", "scopes": list(granted)})


def _step(params=None):
    from app.models.canonical import RiskCategory, RiskLevel, StepRisk
    from app.models.execution_plan import ExecutionStrategy, ExpectedStateChange, PlannedStep, StepExecutionStrategy

    return PlannedStep(
        plan_step_id="plan-label",
        source_canonical_step_id="c",
        source_semantic_step_id="s",
        source_dna_step_key="gmail:add_label",
        application="Gmail",
        action="add_label",
        description="label",
        resolved_parameters=params or {},
        execution_strategy=StepExecutionStrategy(strategy=ExecutionStrategy.API, reason="t", target_technology="Gmail"),
        risk=StepRisk(step_id="c", application="Gmail", action="add_label", risk_level=RiskLevel.MEDIUM,
                      risk_category=RiskCategory.EXTERNAL_CHANGE, reason="t"),
        expected_result="",
        evidence_reference="",
        state_change=ExpectedStateChange(target_system="Gmail", entity_or_property="label", before_state="", expected_after_state=""),
        catalog_action="gmail.add_label",
    )


def _ctx(tmp_path, dry_run=False, **params):
    return ExecutionContext(
        execution_id="exec-gl", workflow_id="wf", execution_plan_id="plan", sandbox_root=str(tmp_path),
        execution_mode=ExecutionMode.DRY_RUN if dry_run else ExecutionMode.LIVE, dry_run=dry_run, resolved_parameters=params,
    )


# ---------------------------------------------------------------- permission


def test_labeling_needs_the_opt_in_and_the_granted_permission(store):
    assert "Labeling is off" in labeling_status()
    _allow(store, granted=(READONLY,), opted_in=False)
    assert "Labeling is off" in labeling_status()
    _allow(store, granted=(READONLY,))  # opted in, but not reconnected (or the box was unticked at Google)
    assert "Reconnect Gmail" in labeling_status()
    _allow(store)
    assert labeling_status() is None


def test_executor_is_blocked_until_labeling_is_allowed(store, gmail, tmp_path):
    ex = GmailLabelExecutor(labeler=GmailLabeler(service=gmail))
    res = ex.execute(_step({"message_id": "{message_id}", "label": "Processed"}), _ctx(tmp_path, message_id="msg-1"))
    assert res.status == ExecutionStepStatus.BLOCKED and res.blocked_reason == "MISSING_SCOPE"
    assert gmail.modify_bodies == []


# ------------------------------------------------------------------ executor


def test_adds_only_the_user_label_and_verifies(store, gmail, tmp_path):
    _allow(store)
    labeler = GmailLabeler(service=gmail)
    ex, checker = GmailLabelExecutor(labeler=labeler), GmailLabelVerificationStrategy(labeler=labeler)
    res = ex.execute(_step({"message_id": "{message_id}", "label": "processed"}), _ctx(tmp_path, message_id="msg-1"))
    assert res.status == ExecutionStepStatus.SUCCESS, res.error
    assert gmail.modify_bodies == [{"addLabelIds": ["Label_7"]}]  # adds one label; never removes anything
    assert gmail.message_labels["msg-1"] == ["INBOX", "UNREAD", "Label_7"]
    assert res.output["label"] == "Processed"

    [check] = checker.build_checks("exec-gl", _step(), res, str(tmp_path))
    assert checker.verify(check, str(tmp_path)).status == VerificationStatus.VERIFIED
    gmail.message_labels["msg-1"] = ["INBOX"]  # someone removed it afterwards
    [check] = checker.build_checks("exec-gl", _step(), res, str(tmp_path))
    assert checker.verify(check, str(tmp_path)).status == VerificationStatus.FAILED


@pytest.mark.parametrize("label", ["TRASH", "Spam", "INBOX", "Does not exist"])
def test_system_and_unknown_labels_are_never_applied(store, gmail, tmp_path, label):
    _allow(store)
    res = GmailLabelExecutor(labeler=GmailLabeler(service=gmail)).execute(
        _step({"message_id": "msg-1", "label": label}), _ctx(tmp_path)
    )
    assert res.status == ExecutionStepStatus.BLOCKED and res.blocked_reason == "NOT_CONFIGURED"
    assert gmail.modify_bodies == []


def test_needs_this_runs_email_and_dry_run_makes_no_calls(store, gmail, tmp_path):
    _allow(store)
    ex = GmailLabelExecutor(labeler=GmailLabeler(service=gmail))
    no_email = ex.execute(_step({"message_id": "{message_id}", "label": "Processed"}), _ctx(tmp_path))
    assert no_email.status == ExecutionStepStatus.BLOCKED and no_email.blocked_reason == "INVALID_PARAMETER"
    dry = ex.execute(_step({"message_id": "{message_id}", "label": "Processed"}), _ctx(tmp_path, dry_run=True))
    assert dry.status == ExecutionStepStatus.SUCCESS and dry.output["status"] == "SIMULATED"
    assert gmail.modify_bodies == []


def test_read_only_parts_stay_read_only():
    assert config.GMAIL_SCOPES == [READONLY]
    assert "add_label" not in GmailApiExecutor().capability.supported_actions
    from app.services import gmail_client

    assert "modify(" not in open(gmail_client.__file__, encoding="utf-8").read()


# --------------------------------------------------------------- observation


def test_label_events_are_recognised():
    url = "https://mail.google.com/mail/u/0/#search/invoice/FMfcgzQXJWDsKmpbvhzKlvWbNXsP"
    labeled = ActivityEvent(event_type=ActivityEventType.FORM_SUBMITTED,
                            metadata={"url": url, "form_fields": {"kind": "label_added", "label": "Processed"}})
    assert classify_label(labeled).action == ADD_LABEL and classify_label(labeled).parameters == {"label": "Processed"}
    other = ActivityEvent(event_type=ActivityEventType.FORM_SUBMITTED, metadata={"url": url, "form_fields": {}})
    look_alike = ActivityEvent(event_type=ActivityEventType.FORM_SUBMITTED,
                               metadata={"url": "https://mail.google.com.evil.example/", "form_fields": {"kind": "label_added", "label": "x"}})
    assert classify_label(other) is None and classify_label(look_alike) is None


# ------------------------------------------------- Settings and the sign-in


def test_sign_in_asks_for_labeling_only_after_opting_in(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from urllib.parse import parse_qs, urlparse

    from app.main import create_app
    from app.services import integrations as integrations_module
    from tests.backend.test_integrations import CLIENT_ID, CLIENT_SECRET, DASHBOARD, FakeGoogle

    store = CredentialStore(str(tmp_path / "c.db"), Fernet.generate_key())
    set_credential_store(store)
    try:
        google = FakeGoogle()
        svc = integrations_module.IntegrationService(store=store, http_factory=google.factory,
                                                     redirect_uri="http://localhost:8000/api/integrations/gmail/callback")
        monkeypatch.setattr(integrations_module, "_service", svc)
        monkeypatch.setattr(config, "GMAIL_CREDENTIALS_PATH", "does-not-exist.json")
        monkeypatch.setattr(config, "GMAIL_TOKEN_PATH", "does-not-exist-token.json")
        svc.save_gmail_client(CLIENT_ID, CLIENT_SECRET, "admin")
        client = TestClient(create_app())

        def connect(granted):
            google.token_response["scope"] = " ".join(granted)
            url = client.post("/api/integrations/gmail/connect", json={"return_to": DASHBOARD}).json()["authorization_url"]
            params = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
            client.get("/api/integrations/gmail/callback", params={"state": params["state"], "code": "c"}, follow_redirects=False)
            return params["scope"].split()

        assert connect([READONLY]) == [READONLY]  # default: read-only only
        assert client.get("/api/integrations").json()["gmail"]["can_label"] is False

        described = client.put("/api/integrations/gmail/options", json={"allow_labels": True}).json()["gmail"]
        assert described["labels_allowed"] is True and described["can_label"] is False  # until reconnected

        assert connect([READONLY]) == [READONLY, MODIFY]  # asked for, but unticked at Google
        assert client.get("/api/integrations").json()["gmail"]["can_label"] is False
        assert connect([READONLY, MODIFY]) == [READONLY, MODIFY]
        assert client.get("/api/integrations").json()["gmail"]["can_label"] is True
        assert store.info(GMAIL_TOKEN).metadata["scopes"] == sorted([READONLY, MODIFY])

        client.put("/api/integrations/gmail/options", json={"allow_labels": False})
        assert "Labeling is off" in labeling_status()  # stops at once, even before reconnecting
    finally:
        set_credential_store(None)


# ------------------------------------------- discovered workflow, end to end


def test_discovered_gmail_label_slack_workflow_runs(tmp_path, store, gmail):
    from app.models.gmail import GmailAttachmentInfo, GmailMessageSummary, GmailSearchResult
    from app.models.slack import SlackNotificationResult
    from app.repositories.canonical_repository import CanonicalWorkflowRepository
    from app.repositories.execution_plan_repository import ExecutionPlanRepository
    from app.repositories.execution_repository import ExecutionRepository
    from app.repositories.learning_repository import LearningRepository
    from app.repositories.verification_repository import VerificationRepository
    from app.services.canonical_factory import CanonicalWorkflowFactory
    from app.services.execution_engine import ExecutionEngine
    from app.services.execution_planner import ExecutionPlanner
    from app.services.executors.slack_executor import SlackApiExecutor
    from app.services.gmail_client import GmailApiClient
    from app.services.learning_engine import LearningEngine
    from app.services.observed_sessions import GMAIL_SEARCH, PROCESSED_LABEL, SLACK_CHANNEL, build_observed_label_events
    from app.services.reference_workflow import WorkflowOrchestrator
    from app.services.semantic_engine import SemanticUnderstandingEngine
    from app.services.semantic_provider import MockSemanticProvider
    from app.services.slack_client import SlackApiClient
    from app.services.verification_engine import VerificationEngine
    from app.services.verifiers.gmail_verifier import GmailVerificationStrategy
    from app.services.verifiers.slack_verifier import SlackVerificationStrategy
    from app.services.workflow_discovery import WorkflowDiscoveryEngine
    from app.services.workflow_dna_extractor import WorkflowDNAExtractor
    from app.services.workflow_segmenter import WorkflowSegmenter

    sessions = WorkflowSegmenter().segment(build_observed_label_events())
    [candidate] = WorkflowDiscoveryEngine().discover_candidates(sessions)
    dna = WorkflowDNAExtractor().extract_dna(candidate, [s for s in sessions if s.session_id in candidate.supporting_session_ids])
    assert [s.catalog_action for s in dna.invariant_steps if s.catalog_action] == [
        "gmail.search_email", "gmail.download_attachment", "gmail.add_label", "slack.send_notification",
    ]
    semantic = SemanticUnderstandingEngine(provider=MockSemanticProvider()).interpret_dna(dna)
    assert semantic.status == "success", semantic.validation_errors
    spec = CanonicalWorkflowFactory().create_specification(dna, semantic.semantic_workflow)

    db = str(tmp_path / "gl.db")
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
    [label_step] = [s for s in plan.planned_steps if s.catalog_action == "gmail.add_label"]
    # the email comes from this run's search; the label was the same in every recording
    assert label_step.resolved_parameters == {"message_id": "{message_id}", "label": PROCESSED_LABEL}

    _allow(store)
    reader = MagicMock(spec=GmailApiClient)
    reader.is_configured.return_value = reader.is_authenticated.return_value = True
    reader.search_messages.return_value = GmailSearchResult(
        query=GMAIL_SEARCH, total_found=1,
        messages=[GmailMessageSummary(
            message_id="msg-new", thread_id="t", subject="Replacement request", sender="Asha <asha@example.com>",
            has_attachments=True, attachments=[GmailAttachmentInfo(attachment_id="a1", filename="invoice_9.pdf", size_bytes=10)],
        )],
    )
    reader.download_attachment.return_value = (b"%PDF-1.4 9", {"filename": "invoice_9.pdf", "mime_type": "application/pdf"})
    slack = MagicMock(spec=SlackApiClient)
    slack.default_channel_id = SLACK_CHANNEL
    slack.send_notification.return_value = SlackNotificationResult(success=True, channel=SLACK_CHANNEL, ts="1.2")
    slack.verify_message.return_value = (True, {"ts": "1.2"}, "found")
    labeler = GmailLabeler(service=gmail)
    for ex in (GmailApiExecutor(client=reader), GmailLabelExecutor(labeler=labeler), SlackApiExecutor(client=slack)):
        orch.engine.registry.register(ex)
    for v in (GmailVerificationStrategy(), GmailLabelVerificationStrategy(labeler=labeler), SlackVerificationStrategy(client=slack)):
        orch.verification_engine.strategy_registry.register(v)

    record = orch.execute_live(plan.execution_plan_id)
    assert record.status == ExecutionOverallStatus.COMPLETED, record.error_summary
    assert gmail.message_labels["msg-new"] == ["INBOX", "Label_7"]  # the NEW email, nothing removed
    assert gmail.message_labels["msg-1"] == ["INBOX", "UNREAD"]  # other email untouched

    verification = orch.verify_execution(record.execution_id)
    [check] = [c for c in verification.checks if c.check_type == "gmail_label_added"]
    assert check.status == VerificationStatus.VERIFIED

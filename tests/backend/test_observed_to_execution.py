"""Observation -> execution bridge.

Feeds recorded browser sessions of the customer-replacement routine through the full pipeline
(segment -> discover -> DNA -> semantic -> canonical spec -> approval -> plan -> execute -> verify)
and checks that the discovered workflow is the same 5-step routine as the hand-written
reference spec, and that it actually runs.
"""

from unittest.mock import MagicMock

import pytest

from app.models.canonical import ApprovalState, RiskCategory
from app.models.crm import CrmCustomer
from app.models.event import ActivityEvent, ActivityEventType
from app.models.execution import ExecutionOverallStatus, ExecutionStepStatus
from app.models.execution_plan import ParameterResolutionStatus
from app.models.gmail import GmailAttachmentInfo, GmailMessageSummary, GmailSearchResult
from app.models.slack import SlackNotificationResult
from app.models.verification import VerificationStatus
from app.repositories.canonical_repository import CanonicalWorkflowRepository
from app.repositories.execution_plan_repository import ExecutionPlanRepository
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.learning_repository import LearningRepository
from app.repositories.verification_repository import VerificationRepository
from app.services.action_catalog import classify_event, step_key_for_event
from app.services.canonical_factory import CanonicalWorkflowFactory
from app.services.crm_client import CrmApiClient
from app.services.execution_engine import ExecutionEngine
from app.services.execution_planner import ExecutionPlanner
from app.services.executors.crm_executor import CrmApiExecutor
from app.services.executors.gmail_executor import GmailApiExecutor
from app.services.executors.slack_executor import SlackApiExecutor
from app.services.gmail_client import GmailApiClient
from app.services.learning_engine import LearningEngine
from app.services.phase16_workflow import Phase16Orchestrator, build_phase16_canonical_spec
from app.services.semantic_engine import SemanticUnderstandingEngine
from app.services.semantic_provider import MockSemanticProvider
from app.services.semantic_validator import SemanticWorkflowValidator
from app.services.slack_client import SlackApiClient
from app.services.verification_engine import VerificationEngine
from app.services.verifiers.crm_verifier import CrmVerificationStrategy
from app.services.verifiers.gmail_verifier import GmailVerificationStrategy
from app.services.verifiers.slack_verifier import SlackVerificationStrategy
from app.services.workflow_discovery import WorkflowDiscoveryEngine
from app.services.workflow_dna_extractor import WorkflowDNAExtractor
from app.services.workflow_segmenter import WorkflowSegmenter
from tests.fixtures.observed_sessions import GMAIL_SEARCH, SLACK_CHANNEL, build_observed_events

EXPECTED_ROUTINE = [
    ("gmail:search_email", "gmail.search_email"),
    ("gmail:download_attachment", "gmail.download_attachment"),
    ("crm:find_customer", "crm.find_customer"),
    ("crm:update_customer_record", "crm.update_customer_record"),
    ("slack:send_notification", "slack.send_notification"),
]


def _nav(url: str) -> ActivityEvent:
    return ActivityEvent(event_type=ActivityEventType.BROWSER_NAVIGATION, application="Google Chrome", metadata={"url": url})


# ---------------------------------------------------------------------------
# Event classification
# ---------------------------------------------------------------------------
class TestClassification:
    def test_gmail_search_route_extracts_query(self):
        c = classify_event(_nav("https://mail.google.com/mail/u/0/#search/from%3Aboss+has%3Aattachment"))
        assert c.action.action_id == "gmail.search_email"
        assert c.parameters == {"search_query": "from:boss has:attachment"}

    def test_opening_a_message_from_search_keeps_the_query(self):
        c = classify_event(_nav("https://mail.google.com/mail/u/0/#search/invoice/FMfcgzQXJWDsKmPqRtZvLhNb"))
        assert c.parameters == {"search_query": "invoice"}

    def test_gmail_inbox_is_not_an_action(self):
        assert classify_event(_nav("https://mail.google.com/mail/u/0/#inbox")) is None

    def test_lookalike_host_is_rejected(self):
        assert classify_event(_nav("https://mail.google.com.evil.example/#search/x")) is None

    def test_crm_customer_page_and_search(self):
        assert classify_event(_nav("http://127.0.0.1:8001/ui/customers/cust-009")).parameters == {"customer_query": "cust-009"}
        assert classify_event(_nav("http://127.0.0.1:8001/ui/customers?q=a%40b.com")).parameters == {"customer_query": "a@b.com"}
        assert classify_event(_nav("http://localhost:8001/ui/customers/cust-009")) is not None
        assert classify_event(_nav("http://127.0.0.1:9999/ui/customers/cust-009")) is None
        assert classify_event(_nav("http://127.0.0.1:8001/api/crm/customers/cust-009")) is None

    def test_crm_form_submission_is_an_update(self):
        evt = ActivityEvent(
            event_type=ActivityEventType.FORM_SUBMITTED,
            metadata={"url": "http://127.0.0.1:8001/ui/customers/cust-1", "form_fields": {"status": "closed"}},
        )
        c = classify_event(evt)
        assert c.action.action_id == "crm.update_customer_record"
        assert c.parameters == {"customer_status": "closed"}

    def test_slack_message_and_gmail_download(self):
        slack = ActivityEvent(
            event_type=ActivityEventType.FORM_SUBMITTED,
            metadata={"url": "https://app.slack.com/client/T1/C0ABCDEF12"},
        )
        assert classify_event(slack).parameters == {"channel": "C0ABCDEF12"}
        dl = ActivityEvent(
            event_type=ActivityEventType.FILE_DOWNLOADED,
            metadata={"url": "https://mail-attachment.googleusercontent.com/attachment/u/0/?ui=2", "file_name": "a.pdf"},
        )
        assert classify_event(dl).action.action_id == "gmail.download_attachment"
        other_dl = ActivityEvent(event_type=ActivityEventType.FILE_DOWNLOADED, metadata={"url": "https://example.com/a.pdf"})
        assert classify_event(other_dl) is None

    def test_explicit_workflow_action_metadata(self):
        evt = ActivityEvent(
            event_type=ActivityEventType.GENERIC_UI_ACTION,
            metadata={"workflow_action": "crm.find_customer", "action_parameters": {"customer_query": "x"}},
        )
        assert step_key_for_event(evt) == "crm:find_customer"
        unknown = ActivityEvent(event_type=ActivityEventType.GENERIC_UI_ACTION, application="X", metadata={"workflow_action": "rm.rf"})
        assert step_key_for_event(unknown) == "x:generic_ui_action"


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------
def discover_spec():
    events = build_observed_events()
    sessions = WorkflowSegmenter().segment(events)
    assert len(sessions) == 3

    candidates = WorkflowDiscoveryEngine().discover_candidates(sessions)
    assert len(candidates) == 1
    cand = candidates[0]
    supporting = [s for s in sessions if s.session_id in cand.supporting_session_ids]

    dna = WorkflowDNAExtractor().extract_dna(cand, supporting)
    resp = SemanticUnderstandingEngine(provider=MockSemanticProvider()).interpret_dna(dna)
    assert resp.status == "success", resp.validation_errors
    spec = CanonicalWorkflowFactory().create_specification(dna, resp.semantic_workflow)
    return dna, spec


def test_dna_marks_executable_steps_and_extracts_action_parameters():
    dna, _ = discover_spec()
    executable = [(s.step_key, s.catalog_action) for s in dna.invariant_steps if s.catalog_action]
    assert executable == EXPECTED_ROUTINE

    observational = {s.step_key for s in dna.invariant_steps if not s.catalog_action}
    assert observational == {"gmail:window_focused", "slack:window_focused"}

    params = {v.parameter_name: v for v in dna.variable_parameters}
    assert params["search_query"].observed_values == [GMAIL_SEARCH]
    assert params["customer_status"].observed_values == ["replacement_processed"]
    assert params["channel"].observed_values == [SLACK_CHANNEL]
    # Customer differs every session (emails while searching, ids when opening the record)
    assert len(params["customer_query"].observed_values) == 6
    # Raw URLs of classified steps are not duplicated as separate variables
    assert not any(v.source_field == "metadata.url" for v in dna.variable_parameters)


def test_discovered_spec_matches_reference_routine():
    _, spec = discover_spec()
    reference = build_phase16_canonical_spec()

    discovered = [(s.application, s.action, s.risk.risk_category, s.catalog_action) for s in spec.steps if s.catalog_action]
    expected = [(s.application, s.action, s.risk.risk_category, s.catalog_action) for s in reference.steps]
    assert discovered == expected
    assert spec.approval_state.state == ApprovalState.REQUIRES_REVIEW
    assert spec.risk_assessment.primary_risk_category == RiskCategory.EXTERNAL_CHANGE


def test_validator_rejects_semantic_output_that_drops_an_executable_step():
    dna, _ = discover_spec()
    payload = MockSemanticProvider().interpret_workflow_dna(dna)
    payload["semantic_steps"] = [s for s in payload["semantic_steps"] if s["source_dna_step_key"] != "crm:update_customer_record"]
    ok, errors = SemanticWorkflowValidator.validate(payload, dna)
    assert not ok
    assert any("crm:update_customer_record" in e for e in errors)


def test_llm_wording_cannot_change_routing():
    """Even if the model calls a step something else, the catalog decides the action."""
    dna, _ = discover_spec()
    payload = MockSemanticProvider().interpret_workflow_dna(dna)
    for s in payload["semantic_steps"]:
        s["action"] = "Handle the thing"
    from app.models.semantic import SemanticWorkflow

    spec = CanonicalWorkflowFactory().create_specification(dna, SemanticWorkflow(**payload))
    assert [s.action for s in spec.steps if s.catalog_action] == [
        "search_email", "download_attachment", "find_customer", "update_customer_record", "send_notification"
    ]


@pytest.fixture
def orchestrator(tmp_path):
    db = str(tmp_path / "bridge.db")
    can_repo = CanonicalWorkflowRepository(db_path=db)
    plan_repo = ExecutionPlanRepository(db_path=db)
    exec_repo = ExecutionRepository(db_path=db)
    ver_repo = VerificationRepository(db_path=db)
    lrn_repo = LearningRepository(db_path=db)
    engine = ExecutionEngine(
        canonical_repo=can_repo, plan_repo=plan_repo, exec_repo=exec_repo, default_sandbox_base=str(tmp_path / "sandbox")
    )
    return Phase16Orchestrator(
        canonical_repo=can_repo,
        plan_repo=plan_repo,
        exec_repo=exec_repo,
        verif_repo=ver_repo,
        learning_repo=lrn_repo,
        engine=engine,
        planner=ExecutionPlanner(),
        verification_engine=VerificationEngine(exec_repo=exec_repo, plan_repo=plan_repo, verif_repo=ver_repo),
        learning_engine=LearningEngine(execution_repo=exec_repo, verification_repo=ver_repo, learning_repo=lrn_repo),
    )


def test_plan_excludes_observation_steps_and_resolves_parameters_safely(orchestrator):
    _, spec = discover_spec()
    orchestrator.canonical_repo.save(spec)
    with pytest.raises(ValueError, match="APPROVED"):
        orchestrator.create_plan(spec.workflow_id)

    orchestrator.approve_workflow(spec.workflow_id, reviewer="ops-lead")
    plan = orchestrator.create_plan(spec.workflow_id)

    assert [(s.source_dna_step_key, s.catalog_action) for s in plan.planned_steps] == EXPECTED_ROUTINE
    assert {e["source_dna_step_key"] for e in plan.excluded_steps} == {"gmail:window_focused", "slack:window_focused"}
    for s in plan.planned_steps:
        assert s.execution_strategy.executor_implemented, s.execution_strategy.blocked_reason
        assert s.execution_strategy.canonical_strategy == "API_INTEGRATION"

    resolved = {p.source_parameter: p for p in plan.resolved_parameters}
    assert resolved["search_query"].runtime_value == GMAIL_SEARCH
    # A customer seen in a past session must never be reused: it comes from the email sender instead
    assert resolved["customer_query"].resolution_status == ParameterResolutionStatus.FROM_UPSTREAM
    assert plan.planned_steps[2].resolved_parameters["customer_query"] == "{customer_email}"
    assert plan.planned_steps[3].resolved_parameters["customer_status"] == "replacement_processed"


def test_dry_run_of_discovered_workflow_makes_no_external_calls(orchestrator):
    _, spec = discover_spec()
    orchestrator.canonical_repo.save(spec)
    orchestrator.approve_workflow(spec.workflow_id)
    plan = orchestrator.create_plan(spec.workflow_id)

    gmail, crm, slack = MagicMock(spec=GmailApiClient), MagicMock(spec=CrmApiClient), MagicMock(spec=SlackApiClient)
    orchestrator.engine.registry.register(GmailApiExecutor(client=gmail))
    orchestrator.engine.registry.register(CrmApiExecutor(client=crm))
    orchestrator.engine.registry.register(SlackApiExecutor(client=slack))

    record = orchestrator.run_dry_run(plan.execution_plan_id)
    assert record.status == ExecutionOverallStatus.COMPLETED
    assert [r.status for r in record.step_results] == [ExecutionStepStatus.SUCCESS] * 5
    gmail.search_messages.assert_not_called()
    crm.update_customer.assert_not_called()
    slack.send_notification.assert_not_called()


def test_discovered_workflow_executes_and_verifies(orchestrator):
    _, spec = discover_spec()
    orchestrator.canonical_repo.save(spec)
    orchestrator.approve_workflow(spec.workflow_id)
    plan = orchestrator.create_plan(spec.workflow_id)

    gmail = MagicMock(spec=GmailApiClient)
    gmail.is_configured.return_value = True
    gmail.is_authenticated.return_value = True
    gmail.search_messages.return_value = GmailSearchResult(
        query=GMAIL_SEARCH,
        total_found=1,
        messages=[
            GmailMessageSummary(
                message_id="msg-new-1",
                thread_id="th-1",
                snippet="Replacement needed",
                subject="Replacement request",
                sender="neha.singh@example.com",
                timestamp="2026-10-12T09:00:00Z",
                has_attachments=True,
                attachments=[GmailAttachmentInfo(attachment_id="att-1", filename="invoice_200.pdf", mime_type="application/pdf", size_bytes=40)],
            )
        ],
        searched_at="2026-10-12T09:00:01Z",
    )
    gmail.download_attachment.return_value = (b"%PDF-1.4 invoice 200", {"filename": "invoice_200.pdf", "mime_type": "application/pdf"})

    customer = dict(customer_id="cust-004", name="Neha Singh", email="neha.singh@example.com", company="Globex",
                    created_at="2026-01-01T00:00:00Z", updated_at="2026-01-01T00:00:00Z")
    crm = MagicMock(spec=CrmApiClient)
    crm.find_customer.return_value = CrmCustomer(status="pending_replacement", **customer)
    crm.update_customer.return_value = CrmCustomer(status="replacement_processed", **customer)
    crm.get_customer.return_value = crm.update_customer.return_value

    slack = MagicMock(spec=SlackApiClient)
    slack.default_channel_id = SLACK_CHANNEL
    slack.send_notification.return_value = SlackNotificationResult(success=True, channel=SLACK_CHANNEL, ts="1760000000.000100")
    slack.verify_message.return_value = (True, {"ts": "1760000000.000100", "text": "Neha Singh"}, "found")

    orchestrator.engine.registry.register(GmailApiExecutor(client=gmail))
    orchestrator.engine.registry.register(CrmApiExecutor(client=crm))
    orchestrator.engine.registry.register(SlackApiExecutor(client=slack))
    orchestrator.verification_engine.strategy_registry.register(GmailVerificationStrategy())
    orchestrator.verification_engine.strategy_registry.register(CrmVerificationStrategy(client=crm))
    orchestrator.verification_engine.strategy_registry.register(SlackVerificationStrategy(client=slack))

    record = orchestrator.execute_live(plan.execution_plan_id)
    assert record.status == ExecutionOverallStatus.COMPLETED, record.error_summary
    assert [r.status for r in record.step_results] == [ExecutionStepStatus.SUCCESS] * 5

    # The search used the observed query, and the CRM lookup used the NEW email's sender,
    # not any customer from the recorded sessions.
    gmail.search_messages.assert_called_once()
    assert gmail.search_messages.call_args.kwargs["query"] == GMAIL_SEARCH
    find_kwargs = crm.find_customer.call_args.kwargs
    assert "neha.singh@example.com" in (find_kwargs.get("query"), find_kwargs.get("email"))
    assert crm.update_customer.call_args.args[0] == "cust-004"
    assert crm.update_customer.call_args.args[1]["status"] == "replacement_processed"
    slack.send_notification.assert_called_once()

    verification = orchestrator.verify_execution(record.execution_id)
    assert verification.overall_status == VerificationStatus.VERIFIED


def test_blocked_step_stops_the_run(orchestrator):
    """If Gmail is not authorized, nothing downstream (CRM update, Slack) may run."""
    _, spec = discover_spec()
    orchestrator.canonical_repo.save(spec)
    orchestrator.approve_workflow(spec.workflow_id)
    plan = orchestrator.create_plan(spec.workflow_id)

    gmail = MagicMock(spec=GmailApiClient)
    gmail.is_configured.return_value = True
    gmail.is_authenticated.return_value = False
    crm, slack = MagicMock(spec=CrmApiClient), MagicMock(spec=SlackApiClient)
    orchestrator.engine.registry.register(GmailApiExecutor(client=gmail))
    orchestrator.engine.registry.register(CrmApiExecutor(client=crm))
    orchestrator.engine.registry.register(SlackApiExecutor(client=slack))

    record = orchestrator.execute_live(plan.execution_plan_id)
    assert record.status == ExecutionOverallStatus.BLOCKED
    assert [r.status for r in record.step_results] == [ExecutionStepStatus.BLOCKED] + [ExecutionStepStatus.SKIPPED] * 4
    assert "AUTHENTICATION_REQUIRED" in record.error_summary
    crm.find_customer.assert_not_called()
    crm.update_customer.assert_not_called()
    slack.send_notification.assert_not_called()

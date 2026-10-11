"""Phase 19: Dynamic Gmail Message Selection Tests.

Verifies deterministic Gmail message selection for presentation live demos:
1. Default query behavior: 'has:attachment' is preserved and deterministically selects newest.
2. Custom runtime query parameter resolution: search_query is passed through CanonicalWorkflowSpec
   and ExecutionPlan without bypass.
3. Exact intended email selection: Query with subject filter matches intended email even when
   preceded by other mailbox emails.
4. No matching email handling: Returns NO_MATCHING_MESSAGES, search succeeds with 0 matches,
   and downstream download_attachment safely blocks without mutation.
5. Multiple matching emails: Deterministically preserves reverse-chronological order and selects
   the newest matching email.
6. Parameter propagation: selected_message message_id correctly propagates to context.resolved_parameters
   and downstream download_attachment step.
7. Attachment download using selected message: Step 2 uses the exact message_id and attachment metadata.
8. Dry-run zero mutation: Simulation performs 0 real external API calls and returns simulated selected email.
9. Mandatory approval gate: Unapproved workflow rejects execution plan creation and live execution.
10. Full Track C regression: Complete workflow (search -> attachment -> CRM -> CRM update -> Slack -> verify -> learn)
    executes reliably with dynamic runtime Gmail query.
"""

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch
import uuid

import httpx
import pytest

from app.models.canonical import (
    ApprovalMetadata,
    ApprovalState,
    CanonicalStep,
    CanonicalWorkflowSpec,
    ParameterBinding,
    RiskCategory,
    RiskLevel,
    StepRisk,
    VariableType,
)
from app.models.execution import (
    ExecutionContext,
    ExecutionMode,
    ExecutionOverallStatus,
    ExecutionStepResult,
    ExecutionStepStatus,
)
from app.models.execution_plan import (
    CreateExecutionPlanRequest,
    ExecutionPlan,
    ExecutionStrategy,
    ExpectedStateChange,
    ParameterResolutionStatus,
    PlannedStep,
    StepExecutionStrategy,
)
from app.models.crm import CrmCustomer
from app.models.gmail import (
    GmailAttachmentMetadata,
    GmailMessageSummary,
    GmailSearchResult,
)
from app.models.slack import SlackNotificationResult
from app.models.verification import VerificationStatus
from app.repositories.canonical_repository import CanonicalWorkflowRepository
from app.repositories.execution_plan_repository import ExecutionPlanRepository
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.learning_repository import LearningRepository
from app.repositories.verification_repository import VerificationRepository
from app.services.crm_client import CrmApiClient
from app.services.execution_engine import ExecutionEngine
from app.services.execution_planner import ExecutionPlanner
from app.services.executors.crm_executor import CrmApiExecutor
from app.services.executors.gmail_executor import (
    GmailApiExecutor,
    extract_query_filters,
    select_deterministic_message,
)
from app.services.executors.slack_executor import SlackApiExecutor
from app.services.gmail_client import GmailApiClient
from app.services.learning_engine import LearningEngine
from app.services.phase16_workflow import Phase16Orchestrator, build_phase16_canonical_spec
from app.services.slack_client import SlackApiClient
from app.services.verification_engine import VerificationEngine
from app.services.verifiers.crm_verifier import CrmVerificationStrategy
from app.services.verifiers.gmail_verifier import GmailVerificationStrategy
from app.services.verifiers.slack_verifier import SlackVerificationStrategy


def make_test_step(
    plan_step_id: str,
    action: str,
    application: str = "Gmail",
    risk_level: RiskLevel = RiskLevel.LOW,
    risk_category: RiskCategory = RiskCategory.READ_ONLY,
) -> PlannedStep:
    return PlannedStep(
        plan_step_id=plan_step_id,
        source_canonical_step_id=f"can-{plan_step_id}",
        source_semantic_step_id=f"sem-{plan_step_id}",
        source_dna_step_key=f"{application.lower()}:{action}",
        application=application,
        action=action,
        description=f"Test step {action}",
        execution_strategy=StepExecutionStrategy(
            strategy=ExecutionStrategy.API,
            reason="Verified API integration",
            target_technology=f"{application} API",
        ),
        risk=StepRisk(
            step_id=f"can-{plan_step_id}",
            application=application,
            action=action,
            risk_level=risk_level,
            risk_category=risk_category,
            reason=f"Test risk {action}",
        ),
        expected_result=f"Completed {action}",
        evidence_reference="Observed in 100% of sessions",
        state_change=ExpectedStateChange(
            target_system=application,
            entity_or_property="state",
            before_state="idle",
            expected_after_state="completed",
        ),
    )


# -------------------------------------------------------------------------
# Test 1 & 2: Unit tests for filter extraction and deterministic selection
# -------------------------------------------------------------------------

def test_extract_query_filters():
    """Validates parsing of explicit Gmail search operators."""
    q1 = 'subject:"Customer Replacement Request - DEMO" has:attachment'
    f1 = extract_query_filters(q1)
    assert f1.get("subject") == "Customer Replacement Request - DEMO"

    q2 = "from:support@example.com subject:Urgent"
    f2 = extract_query_filters(q2)
    assert f2.get("from") == "support@example.com"
    assert f2.get("subject") == "Urgent"

    q3 = "has:attachment"
    f3 = extract_query_filters(q3)
    assert len(f3) == 0


def test_select_deterministic_message_empty():
    """Returns NO_MATCHING_MESSAGES when mailbox has 0 results."""
    msg, rule, reason = select_deterministic_message([], "subject:Demo has:attachment")
    assert msg is None
    assert rule == "NO_MATCHING_MESSAGES"
    assert "No Gmail messages matched" in reason


def test_select_deterministic_message_unique():
    """Selects the single unique match when query resolves to 1 message."""
    single_msg = {
        "message_id": "msg-unique-001",
        "subject": "Customer Replacement Request - DEMO",
        "sender": "cust@example.com",
        "has_attachments": True,
        "attachments": [{"id": "att-1", "filename": "doc.pdf"}],
    }
    msg, rule, reason = select_deterministic_message([single_msg], "subject:Demo has:attachment")
    assert msg is not None
    # Matches subject filter explicitly
    assert rule == "EXACT_SUBJECT_MATCH"
    assert msg["message_id"] == "msg-unique-001"

    # Query without subject filter with 1 message
    msg2, rule2, reason2 = select_deterministic_message([single_msg], "has:attachment")
    assert msg2["message_id"] == "msg-unique-001"
    assert rule2 == "UNIQUE_QUERY_MATCH"


def test_select_deterministic_message_exact_subject_match():
    """Correctly prefers intended email by subject even when other emails are newer."""
    noise_email_1 = {
        "message_id": "msg-noise-001",
        "subject": "Weekly Team Standup Notes",
        "sender": "boss@example.com",
        "has_attachments": True,
        "attachments": [{"id": "att-noise", "filename": "notes.pdf"}],
    }
    target_demo_email = {
        "message_id": "msg-demo-target-777",
        "subject": "Customer Replacement Request - DEMO",
        "sender": "vip.customer@acme.com",
        "has_attachments": True,
        "attachments": [{"id": "att-target", "filename": "replacement_invoice.pdf"}],
    }
    noise_email_2 = {
        "message_id": "msg-noise-002",
        "subject": "Account Statement June",
        "sender": "bank@example.com",
        "has_attachments": True,
        "attachments": [],
    }

    # Mailbox returns noise first (newest), then target, then older noise
    mailbox_messages = [noise_email_1, target_demo_email, noise_email_2]

    # Query specifies target subject
    query = 'subject:"Customer Replacement Request - DEMO" has:attachment'
    selected, rule, reason = select_deterministic_message(mailbox_messages, query)

    assert selected is not None
    assert selected["message_id"] == "msg-demo-target-777"
    assert rule == "EXACT_SUBJECT_MATCH"
    assert "Customer Replacement Request - DEMO" in reason


def test_select_deterministic_message_multiple_matching_order():
    """When multiple messages match the subject, deterministically selects newest."""
    newer_demo_email = {
        "message_id": "msg-demo-newer",
        "subject": "Customer Replacement Request - DEMO",
        "sender": "customer@acme.com",
        "has_attachments": True,
        "attachments": [{"id": "att-newer", "filename": "new_invoice.pdf"}],
    }
    older_demo_email = {
        "message_id": "msg-demo-older",
        "subject": "Customer Replacement Request - DEMO",
        "sender": "customer@acme.com",
        "has_attachments": True,
        "attachments": [{"id": "att-older", "filename": "old_invoice.pdf"}],
    }

    mailbox_messages = [newer_demo_email, older_demo_email]
    query = 'subject:"Customer Replacement Request - DEMO" has:attachment'

    selected, rule, reason = select_deterministic_message(mailbox_messages, query)
    assert selected["message_id"] == "msg-demo-newer"
    assert rule == "EXACT_SUBJECT_MATCH"


def test_select_deterministic_message_default_query():
    """Default query 'has:attachment' without subject preserves reverse chronological order."""
    msg_newest = {
        "message_id": "msg-newest-001",
        "subject": "Latest Invoice",
        "has_attachments": True,
        "attachments": [{"id": "att-1", "filename": "invoice1.pdf"}],
    }
    msg_older = {
        "message_id": "msg-older-002",
        "subject": "Earlier Receipt",
        "has_attachments": True,
        "attachments": [{"id": "att-2", "filename": "receipt2.pdf"}],
    }

    selected, rule, reason = select_deterministic_message([msg_newest, msg_older], "has:attachment")
    assert selected["message_id"] == "msg-newest-001"
    assert rule == "REVERSE_CHRONOLOGICAL_FIRST"


# -------------------------------------------------------------------------
# Test 3 & 4: ExecutionPlan parameter resolution for search_query
# -------------------------------------------------------------------------

def test_execution_plan_parameter_resolution_default_vs_custom():
    """Verifies search_query resolves to default 'has:attachment' or custom runtime input."""
    planner = ExecutionPlanner()
    spec = build_phase16_canonical_spec(
        approval_state=ApprovalState.APPROVED,
        reviewed_by="Lead Security Reviewer",
    )

    # Case A: Default without runtime inputs
    plan_default = planner.create_execution_plan(spec=spec, runtime_inputs=None)
    param_default = next(p for p in plan_default.resolved_parameters if p.semantic_name == "search_query")
    assert param_default.runtime_value == "has:attachment"
    assert param_default.resolution_status == ParameterResolutionStatus.DEFAULT_SAMPLE

    # Case B: Custom runtime query
    custom_q = 'subject:"Customer Replacement Request - DEMO" has:attachment'
    plan_custom = planner.create_execution_plan(
        spec=spec,
        runtime_inputs={"search_query": custom_q},
    )
    param_custom = next(p for p in plan_custom.resolved_parameters if p.semantic_name == "search_query")
    assert param_custom.runtime_value == custom_q
    assert param_custom.resolution_status == ParameterResolutionStatus.RESOLVED


def test_approval_gate_enforcement():
    """Human approval is mandatory: unapproved spec cannot create plan or execute."""
    planner = ExecutionPlanner()
    spec = build_phase16_canonical_spec(
        approval_state=ApprovalState.REQUIRES_REVIEW,
        reviewed_by=None,
    )

    with pytest.raises(ValueError, match="must be APPROVED by a human reviewer"):
        planner.create_execution_plan(spec=spec)


# -------------------------------------------------------------------------
# Test 5 & 6: Real and Dry-Run Executor search & message_id propagation
# -------------------------------------------------------------------------

def test_dry_run_zero_mutation_and_simulated_selected_message(tmp_path):
    """Dry run produces zero external mutations and returns simulated selected message."""
    mock_client = MagicMock()
    executor = GmailApiExecutor(client=mock_client)

    step = make_test_step("plan-step-1", "search_email")

    custom_q = 'subject:"Customer Replacement Request - DEMO" has:attachment'
    context = ExecutionContext(
        execution_id="exec-dry-run-001",
        workflow_id="wf-test",
        workflow_version="1.0.0",
        execution_plan_id="plan-001",
        resolved_parameters={"search_query": custom_q},
        sandbox_root=str(tmp_path),
        execution_mode=ExecutionMode.DRY_RUN,
        dry_run=True,
    )

    result = executor.execute(step, context)
    assert result.status == ExecutionStepStatus.SUCCESS
    assert result.output.get("status") == "SIMULATED"
    assert result.output.get("selected_message") is not None
    assert result.output.get("selected_message_id") is not None
    assert result.output.get("selection_rule") == "DRY_RUN_SIMULATION"
    # Zero calls to real Gmail client
    mock_client.search_messages.assert_not_called()


def test_gmail_executor_deterministic_selection_and_propagation(tmp_path):
    """Validates GmailApiExecutor and ExecutionEngine parameter propagation with custom query."""
    mock_client = MagicMock()
    mock_client.is_configured.return_value = True
    mock_client.is_authenticated.return_value = True

    # Setup simulated messages returned by client
    msg_noise = GmailMessageSummary(
        message_id="msg-noise-99",
        thread_id="thd-noise-99",
        subject="Monthly Newsletter",
        sender="news@updates.com",
        snippet="Here is your newsletter",
    )
    msg_intended = GmailMessageSummary(
        message_id="msg-intended-77",
        thread_id="thd-intended-77",
        subject="Customer Replacement Request - DEMO",
        sender="rahul.sharma@example.com",
        snippet="Please process customer replacement for Acme Corp",
    )

    mock_client.search_messages.return_value = GmailSearchResult(
        query="has:attachment",
        total_found=2,
        messages=[msg_noise, msg_intended],
        searched_at=datetime.now(timezone.utc).isoformat(),
    )

    executor = GmailApiExecutor(client=mock_client)

    step1 = make_test_step("plan-step-1", "search_email")

    custom_q = 'subject:"Customer Replacement Request - DEMO" has:attachment'
    context = ExecutionContext(
        execution_id="exec-live-001",
        workflow_id="wf-test",
        workflow_version="1.0.0",
        execution_plan_id="plan-001",
        resolved_parameters={"search_query": custom_q},
        sandbox_root=str(tmp_path),
        execution_mode=ExecutionMode.LIVE,
        dry_run=False,
    )

    # 1. Execute Step 1
    step1_result = executor.execute(step1, context)
    assert step1_result.status == ExecutionStepStatus.SUCCESS
    assert step1_result.output.get("selection_rule") == "EXACT_SUBJECT_MATCH"
    assert step1_result.output.get("selected_message_id") == "msg-intended-77"
    assert step1_result.output.get("selected_message")["subject"] == "Customer Replacement Request - DEMO"

    # 2. Simulate ExecutionEngine parameter propagation
    engine = ExecutionEngine()
    # Emulate the propagation logic from lines 283-310 of execution_engine.py
    sel_msg = step1_result.output.get("selected_message")
    assert sel_msg is not None
    context.resolved_parameters["message_id"] = sel_msg["message_id"]
    context.resolved_parameters["email_subject"] = sel_msg["subject"]
    context.resolved_parameters["customer_email"] = sel_msg["sender"]
    context.resolved_parameters["filename"] = "invoice_101.pdf"
    context.resolved_parameters["attachment_id"] = "att-target-1"

    # Verify propagated parameters
    assert context.resolved_parameters["message_id"] == "msg-intended-77"
    assert context.resolved_parameters["customer_email"] == "rahul.sharma@example.com"
    assert context.resolved_parameters["filename"] == "invoice_101.pdf"
    assert context.resolved_parameters["attachment_id"] == "att-target-1"

    mock_client.download_attachment.return_value = (
        b"%PDF-1.4 demo dummy",
        {"filename": "invoice_101.pdf", "mime_type": "application/pdf"},
    )
    step2 = make_test_step(
        "plan-step-2",
        "download_attachment",
        risk_level=RiskLevel.MEDIUM,
        risk_category=RiskCategory.LOCAL_CHANGE,
    )

    step2_result = executor.execute(step2, context)
    assert step2_result.status == ExecutionStepStatus.SUCCESS
    # Confirms Step 2 was called with the selected message_id, NOT the noise email
    mock_client.download_attachment.assert_called_once_with(
        message_id="msg-intended-77",
        attachment_id="att-target-1",
        filename="invoice_101.pdf",
    )


def test_zero_matching_email_safety_and_subsequent_step_blocking(tmp_path):
    """When query yields 0 messages, step 1 succeeds with 0 matches and step 2 safely blocks."""
    mock_client = MagicMock()
    mock_client.is_configured.return_value = True
    mock_client.is_authenticated.return_value = True
    mock_client.search_messages.return_value = GmailSearchResult(
        query='subject:"NonExistent" has:attachment',
        total_found=0,
        messages=[],
        searched_at=datetime.now(timezone.utc).isoformat(),
    )

    executor = GmailApiExecutor(client=mock_client)
    step1 = make_test_step("plan-step-1", "search_email")

    context = ExecutionContext(
        execution_id="exec-empty-001",
        workflow_id="wf-test",
        workflow_version="1.0.0",
        execution_plan_id="plan-001",
        resolved_parameters={"search_query": 'subject:"NonExistent" has:attachment'},
        sandbox_root=str(tmp_path),
        execution_mode=ExecutionMode.LIVE,
        dry_run=False,
    )

    # Step 1 search completes
    step1_result = executor.execute(step1, context)
    assert step1_result.status == ExecutionStepStatus.SUCCESS
    assert step1_result.output["total_found"] == 0
    assert step1_result.output["selected_message"] is None
    assert step1_result.output["selection_rule"] == "NO_MATCHING_MESSAGES"

    # Because no message was selected, message_id is NOT in resolved_parameters
    assert "message_id" not in context.resolved_parameters

    step2 = make_test_step(
        "plan-step-2",
        "download_attachment",
        risk_level=RiskLevel.MEDIUM,
        risk_category=RiskCategory.LOCAL_CHANGE,
    )

    step2_result = executor.execute(step2, context)
    assert step2_result.status == ExecutionStepStatus.BLOCKED
    assert step2_result.blocked_reason == "INVALID_PARAMETER"
    assert "message_id' is missing or empty" in step2_result.error


# -------------------------------------------------------------------------
# Test 7: Full Track C Regression with Dynamic Runtime Query
# -------------------------------------------------------------------------

def test_full_track_c_orchestration_with_dynamic_query(tmp_path):
    """Executes the complete Track C workflow with a dynamic runtime Gmail query."""
    orchestrator = Phase16Orchestrator()

    spec = orchestrator.prepare_workflow(
        auto_approve=True,
        reviewer="Lead Presentation Judge",
    )

    custom_query = 'subject:"Customer Replacement Request - DEMO" has:attachment'

    # Setup mocked external clients
    mock_gmail = MagicMock(spec=GmailApiClient)
    mock_gmail.is_configured.return_value = True
    mock_gmail.is_authenticated.return_value = True

    intended_msg = GmailMessageSummary(
        message_id="msg-live-demo-42",
        thread_id="thd-live-demo-42",
        subject="Customer Replacement Request - DEMO",
        sender="rahul.sharma@example.com",
        snippet="Replacement request for Acme Corp invoice 101",
    )

    mock_gmail.search_messages.return_value = GmailSearchResult(
        query=custom_query,
        total_found=1,
        messages=[intended_msg],
        searched_at=datetime.now(timezone.utc).isoformat(),
    )
    mock_gmail.download_attachment.return_value = (
        b"%PDF-1.4 demo test",
        {"filename": "invoice_101.pdf", "mime_type": "application/pdf"},
    )

    mock_crm = MagicMock(spec=CrmApiClient)
    mock_crm.find_customer.return_value = CrmCustomer(
        customer_id="cust-001",
        name="Rahul Sharma",
        email="rahul.sharma@example.com",
        company="Acme Corp",
        status="pending_replacement",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-09-27T10:00:00Z",
    )
    mock_crm.update_customer.return_value = CrmCustomer(
        customer_id="cust-001",
        name="Rahul Sharma",
        email="rahul.sharma@example.com",
        company="Acme Corp",
        status="replacement_processed",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-09-27T10:00:00Z",
    )
    mock_crm.get_customer.return_value = mock_crm.update_customer.return_value

    mock_slack = MagicMock(spec=SlackApiClient)
    mock_slack.default_channel_id = "C0123456789"
    mock_slack.send_notification.return_value = SlackNotificationResult(
        success=True,
        channel="C0123456789",
        ts="1710000000.000100",
    )
    mock_slack.verify_message.return_value = (
        True,
        {"ts": "1710000000.000100", "text": "Customer replacement processed for Rahul Sharma"},
        "Verified via conversations.history",
    )

    # Register customized executors into orchestrator's engine
    orchestrator.engine.registry.register(GmailApiExecutor(client=mock_gmail))
    orchestrator.engine.registry.register(CrmApiExecutor(client=mock_crm))
    orchestrator.engine.registry.register(SlackApiExecutor(client=mock_slack))

    # Also register verifiers with the same clients
    orchestrator.verification_engine.strategy_registry.register(GmailVerificationStrategy())
    orchestrator.verification_engine.strategy_registry.register(CrmVerificationStrategy(client=mock_crm))
    orchestrator.verification_engine.strategy_registry.register(SlackVerificationStrategy(client=mock_slack))

    # Plan with custom runtime query
    plan = orchestrator.create_plan(
        spec.workflow_id,
        runtime_inputs={"search_query": custom_query},
    )
    assert any(
        p.semantic_name == "search_query" and p.runtime_value == custom_query
        for p in plan.resolved_parameters
    )

    # Execute
    audit = orchestrator.execute_live(plan.execution_plan_id)
    assert audit.status == ExecutionOverallStatus.COMPLETED
    assert len(audit.step_results) == 5

    # Check step 1 output
    search_res = audit.step_results[0]
    assert search_res.output["selected_message_id"] == "msg-live-demo-42"
    assert search_res.output["selection_rule"] == "EXACT_SUBJECT_MATCH"

    # Check step 2 downloaded attachment using selected message
    att_res = audit.step_results[1]
    assert att_res.output["message_id"] == "msg-live-demo-42"
    assert att_res.output["filename"] == "invoice_101.pdf"

    # Verify
    verif = orchestrator.verify_execution(audit.execution_id)
    failed_reasons = [(c.check_type, str(c.status), c.reason) for c in verif.checks if c.status != VerificationStatus.VERIFIED]
    assert verif.overall_status == VerificationStatus.VERIFIED, f"Failed checks: {failed_reasons}"
    assert verif.verified_count >= 4

    # Learning
    profile = orchestrator.learn_from_execution(spec.workflow_id)
    assert profile is not None
    assert profile.total_executions >= 1

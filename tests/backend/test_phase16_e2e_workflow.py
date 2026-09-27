"""Phase 16: Full Live End-to-End Workflow Tests.

Orchestrates the hackathon problem statement's core routine:
Gmail search_email
    ↓
Gmail download_attachment
    ↓
CRM find_customer
    ↓
CRM update_customer_record
    ↓
Slack send_notification
    ↓
Independent verification (Gmail, FileSystem, CRM, Slack)
    ↓
Deterministic Learning

Tests include:
1. CanonicalWorkflowSpec construction and structure (5 explicit steps).
2. Governance Approval Gate: Unapproved workflow rejects plan creation and execution with 0 side effects.
3. Human approval transition from REQUIRES_REVIEW to APPROVED.
4. ExecutionPlan generation: StrategySelector assigns API_INTEGRATION to all 5 steps.
5. Dry-run simulation: ZERO external mutations or API calls, produces SIMULATED status.
6. Real Execution Path (Mocked clients for deterministic testing):
   - Validates parameter flow:
     Gmail search -> message_id -> attachment_id -> downloaded file -> CRM customer lookup -> customer record -> CRM update -> Slack notification.
7. Independent Verification:
   - Verifies Gmail search, Attachment file integrity (SHA-256), CRM update verification, and Slack delivery verification.
8. Deterministic Learning:
   - Evaluates workflow history, updates reliability metrics and profile.
9. Partial Failure Propagation:
   - Case A: Gmail failure -> CRM and Slack skipped.
   - Case B: CRM lookup failure -> CRM update and Slack skipped.
   - Case C: CRM update failure -> Slack skipped.
   - Case D: Slack failure after CRM success -> CRM remains SUCCESS, Slack FAILED, workflow NOT falsely verified.
10. Idempotency protection: Duplicate idempotency_key prevents re-execution.
11. Security: Verification and audit records exclude secrets and tokens.
12. Real Live E2E Test (Conditional on live Gmail, CRM, and Slack credentials).
"""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch
import uuid

import httpx
import pytest

import app.config  # Ensures .env is loaded
from app.models.canonical import (
    ApprovalMetadata,
    ApprovalState,
    CanonicalStep,
    CanonicalWorkflowSpec,
    RiskCategory,
    RiskLevel,
    StepRisk,
)
from app.models.crm import CrmCustomer, CrmCustomerUpdate
from app.models.execution import (
    ExecutionContext,
    ExecutionMode,
    ExecutionOverallStatus,
    ExecutionStepResult,
    ExecutionStepStatus,
)
from app.models.execution_plan import (
    ExecutionPlan,
    ExecutionStrategy,
    ExpectedStateChange,
    ParameterResolutionStatus,
    PlannedStep,
    ResolvedParameter,
    StepExecutionStrategy,
)
from app.models.gmail import GmailAttachmentMetadata, GmailMessageSummary, GmailSearchResult
from app.models.learning import FailureCategory, WorkflowReliabilityProfile
from app.models.slack import SlackNotificationPayload, SlackNotificationResult
from app.models.verification import VerificationResult, VerificationStatus
from app.repositories.canonical_repository import CanonicalWorkflowRepository
from app.repositories.crm_repository import CrmRepository
from app.repositories.execution_plan_repository import ExecutionPlanRepository
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.learning_repository import LearningRepository
from app.repositories.verification_repository import VerificationRepository
from app.services.crm_client import CrmApiClient
from app.services.dry_run_simulator import DryRunSimulator
from app.services.execution_engine import ExecutionEngine
from app.services.execution_planner import ExecutionPlanner
from app.services.executors.crm_executor import CrmApiExecutor
from app.services.executors.gmail_executor import GmailApiExecutor
from app.services.executors.registry import ExecutorRegistry
from app.services.executors.slack_executor import SlackApiExecutor
from app.services.gmail_client import GmailApiClient
from app.services.learning_engine import LearningEngine
from app.services.phase16_workflow import Phase16Orchestrator, build_phase16_canonical_spec
from app.services.slack_client import SlackApiClient
from app.services.verification_engine import VerificationEngine
from app.services.verifiers.crm_verifier import CrmVerificationStrategy
from app.services.verifiers.file_system import FileSystemVerificationStrategy
from app.services.verifiers.gmail_verifier import GmailVerificationStrategy
from app.services.verifiers.registry import VerificationStrategyRegistry
from app.services.verifiers.slack_verifier import SlackVerificationStrategy


@pytest.fixture
def isolated_orchestrator(tmp_path):
    """Sets up an isolated Phase16Orchestrator with in-memory SQLite repositories and sandbox."""
    db_file = str(tmp_path / "test_phase16.db")
    sandbox_dir = str(tmp_path / "sandbox")

    can_repo = CanonicalWorkflowRepository(db_path=db_file)
    plan_repo = ExecutionPlanRepository(db_path=db_file)
    exec_repo = ExecutionRepository(db_path=db_file)
    ver_repo = VerificationRepository(db_path=db_file)
    lrn_repo = LearningRepository(db_path=db_file)

    engine = ExecutionEngine(
        canonical_repo=can_repo,
        plan_repo=plan_repo,
        exec_repo=exec_repo,
        default_sandbox_base=sandbox_dir,
    )
    planner = ExecutionPlanner()
    ver_engine = VerificationEngine(
        exec_repo=exec_repo,
        plan_repo=plan_repo,
        verif_repo=ver_repo,
    )
    lrn_engine = LearningEngine(
        execution_repo=exec_repo,
        verification_repo=ver_repo,
        learning_repo=lrn_repo,
    )

    orch = Phase16Orchestrator(
        canonical_repo=can_repo,
        plan_repo=plan_repo,
        exec_repo=exec_repo,
        verif_repo=ver_repo,
        learning_repo=lrn_repo,
        engine=engine,
        planner=planner,
        verification_engine=ver_engine,
        learning_engine=lrn_engine,
    )
    return orch, tmp_path


# =========================================================================
# 1. Workflow Spec Construction & Structure
# =========================================================================
def test_phase16_canonical_spec_structure():
    """Validates that build_phase16_canonical_spec produces exactly 5 coherent steps."""
    spec = build_phase16_canonical_spec()
    assert spec.workflow_id is not None
    assert len(spec.steps) == 5

    step_actions = [(s.application, s.action) for s in spec.steps]
    assert step_actions == [
        ("Gmail", "search_email"),
        ("Gmail", "download_attachment"),
        ("CRM", "find_customer"),
        ("CRM", "update_customer_record"),
        ("Slack", "send_notification"),
    ]

    # Verify risk classifications
    assert spec.steps[0].risk.risk_category == RiskCategory.READ_ONLY
    assert spec.steps[1].risk.risk_category == RiskCategory.LOCAL_CHANGE
    assert spec.steps[2].risk.risk_category == RiskCategory.READ_ONLY
    assert spec.steps[3].risk.risk_category == RiskCategory.EXTERNAL_CHANGE
    assert spec.steps[4].risk.risk_category == RiskCategory.COMMUNICATION

    # Approval state defaults to requires_review
    assert spec.approval_state.state == ApprovalState.REQUIRES_REVIEW


# =========================================================================
# 2. Approval Gate Enforcement (Unapproved Spec Rejection)
# =========================================================================
def test_phase16_unapproved_workflow_rejected(isolated_orchestrator):
    """Unapproved workflow cannot create an execution plan or execute (0 side effects)."""
    orch, _ = isolated_orchestrator
    spec = orch.prepare_workflow(auto_approve=False)

    # 1. Plan creation is rejected
    with pytest.raises(ValueError, match="It must be APPROVED by a human reviewer"):
        orch.create_plan(spec.workflow_id)

    # Zero plans created
    assert len(orch.plan_repo.list_all()) == 0


def test_phase16_human_approval_enables_planning(isolated_orchestrator):
    """Human approval unlocks execution plan generation."""
    orch, _ = isolated_orchestrator
    spec = orch.prepare_workflow(auto_approve=False)

    # Approve
    approved_spec = orch.approve_workflow(spec.workflow_id, reviewer="Senior Reviewer")
    assert approved_spec.approval_state.state == ApprovalState.APPROVED
    assert approved_spec.approval_state.reviewed_by == "Senior Reviewer"

    # Plan creation now succeeds
    plan = orch.create_plan(spec.workflow_id)
    assert plan is not None
    assert len(plan.planned_steps) == 5
    assert plan.source_approval_state == ApprovalState.APPROVED.value


# =========================================================================
# 3. Dry-Run Execution (Guaranteed ZERO external calls / mutations)
# =========================================================================
def test_phase16_dry_run_simulation(isolated_orchestrator):
    """Dry run produces a plan simulation with ZERO mutations."""
    orch, _ = isolated_orchestrator
    spec = orch.prepare_workflow(auto_approve=True)
    plan = orch.create_plan(spec.workflow_id)

    # 1. Simulator service check
    simulator = DryRunSimulator()
    sim_res = simulator.simulate(plan)
    assert sim_res.overall_simulation_status == "SIMULATED"
    assert sim_res.real_actions_performed == 0
    assert len(sim_res.step_simulations) == 5
    for s in sim_res.step_simulations:
        assert s.simulation_status == "SIMULATED"
        assert s.external_mutation_prevented is not None

    # 2. Engine dry-run execution check
    audit_record = orch.run_dry_run(plan.execution_plan_id)
    assert audit_record.execution_mode == ExecutionMode.DRY_RUN
    assert audit_record.status == ExecutionOverallStatus.COMPLETED
    assert len(audit_record.step_results) == 5
    for step_res in audit_record.step_results:
        assert step_res.status == ExecutionStepStatus.SUCCESS
        assert step_res.output.get("status") == "SIMULATED" or step_res.parameters_used.get("dry_run") is True


# =========================================================================
# 4. Mocked Real Execution Path & Parameter Flow
# =========================================================================
def test_phase16_mocked_execution_parameter_flow(isolated_orchestrator):
    """Executes the complete 5-step workflow with mocked external clients and validates parameter flow."""
    orch, tmp_path = isolated_orchestrator
    spec = orch.prepare_workflow(auto_approve=True)
    plan = orch.create_plan(spec.workflow_id)

    # Setup mocked external clients
    mock_gmail = MagicMock(spec=GmailApiClient)
    mock_gmail.is_configured.return_value = True
    mock_gmail.is_authenticated.return_value = True
    mock_gmail.search_messages.return_value = GmailSearchResult(
        query="has:attachment",
        total_found=1,
        messages=[
            GmailMessageSummary(
                message_id="msg-e2e-101",
                thread_id="th-101",
                snippet="Please process replacement invoice",
                subject="Customer Replacement Request - Rahul",
                sender="rahul@example.com",
                timestamp="2026-09-27T10:00:00Z",
            )
        ],
        searched_at="2026-09-27T10:00:00Z",
    )
    dummy_pdf_bytes = b"%PDF-1.4 Dummy invoice content for Rahul replacement"
    mock_gmail.download_attachment.return_value = (dummy_pdf_bytes, {"filename": "invoice_101.pdf", "mime_type": "application/pdf"})

    mock_crm = MagicMock(spec=CrmApiClient)
    mock_crm.find_customer.return_value = CrmCustomer(
        customer_id="cust-001",
        name="Rahul Sharma",
        email="rahul@example.com",
        company="Acme Corp",
        status="active",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )
    mock_crm.update_customer.return_value = CrmCustomer(
        customer_id="cust-001",
        name="Rahul Sharma",
        email="rahul@example.com",
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
        ts="1711539999.000100",
    )
    mock_slack.verify_message.return_value = (
        True,
        {"ts": "1711539999.000100", "text": "WorkFlowOS Phase 16 E2E — Customer replacement processed for Rahul Sharma"},
        "Verified via conversations.history",
    )

    # Register customized executors into orchestrator's engine
    orch.engine.registry.register(GmailApiExecutor(client=mock_gmail))
    orch.engine.registry.register(CrmApiExecutor(client=mock_crm))
    orch.engine.registry.register(SlackApiExecutor(client=mock_slack))

    # Also register verifiers with the same clients
    orch.verification_engine.strategy_registry.register(GmailVerificationStrategy())
    orch.verification_engine.strategy_registry.register(CrmVerificationStrategy(client=mock_crm))
    orch.verification_engine.strategy_registry.register(SlackVerificationStrategy(client=mock_slack))

    # Execute Live Mode
    audit_record = orch.execute_live(plan.execution_plan_id)

    # 1. Audit status check
    assert audit_record.status == ExecutionOverallStatus.COMPLETED
    assert len(audit_record.step_results) == 5

    res1, res2, res3, res4, res5 = audit_record.step_results
    assert res1.status == ExecutionStepStatus.SUCCESS
    assert res2.status == ExecutionStepStatus.SUCCESS
    assert res3.status == ExecutionStepStatus.SUCCESS
    assert res4.status == ExecutionStepStatus.SUCCESS
    assert res5.status == ExecutionStepStatus.SUCCESS

    # 2. Parameter flow check
    # Step 1: Gmail search returned msg-e2e-101
    assert res1.output["messages"][0]["message_id"] == "msg-e2e-101"

    # Step 2: Download attachment received msg-e2e-101 dynamically
    mock_gmail.download_attachment.assert_called()
    assert res2.parameters_used["message_id"] == "msg-e2e-101"
    downloaded_file = res2.output["saved_path"]
    assert Path(downloaded_file).exists()

    # Step 3: CRM find_customer received query
    mock_crm.find_customer.assert_called()

    # Step 4: CRM update received customer_id="cust-001" dynamically
    mock_crm.update_customer.assert_called()
    assert res4.parameters_used["customer_id"] == "cust-001"

    # Step 5: Slack notification dispatched
    mock_slack.send_notification.assert_called()
    assert res5.output["ts"] == "1711539999.000100"

    # 3. Independent Verification
    verif_res = orch.verify_execution(audit_record.execution_id)
    assert verif_res.overall_status == VerificationStatus.VERIFIED
    assert len(verif_res.checks) == 5

    # 4. Learning Integration
    profile = orch.learn_from_execution(spec.workflow_id)
    assert profile.total_executions == 1
    assert profile.successful_executions == 1
    assert profile.verified_executions == 1
    assert profile.reliability_rate == 1.0


# =========================================================================
# 5. Partial Failure Propagation (Cases A, B, C, D)
# =========================================================================
def test_partial_failure_case_a_gmail_failure(isolated_orchestrator):
    """Case A: Gmail search fails -> subsequent steps (Attachment, CRM, Slack) are SKIPPED."""
    orch, _ = isolated_orchestrator
    spec = orch.prepare_workflow(auto_approve=True)
    plan = orch.create_plan(spec.workflow_id)

    mock_gmail = MagicMock(spec=GmailApiClient)
    mock_gmail.is_configured.return_value = True
    mock_gmail.is_authenticated.return_value = True
    mock_gmail.search_messages.side_effect = RuntimeError("Gmail API rate limit exceeded")

    mock_crm = MagicMock(spec=CrmApiClient)
    mock_slack = MagicMock(spec=SlackApiClient)

    orch.engine.registry.register(GmailApiExecutor(client=mock_gmail))
    orch.engine.registry.register(CrmApiExecutor(client=mock_crm))
    orch.engine.registry.register(SlackApiExecutor(client=mock_slack))

    audit = orch.execute_live(plan.execution_plan_id)
    assert audit.status == ExecutionOverallStatus.FAILED
    assert audit.step_results[0].status == ExecutionStepStatus.FAILED
    assert "rate limit" in audit.step_results[0].error

    # Subsequent steps were SKIPPED
    for s in audit.step_results[1:]:
        assert s.status == ExecutionStepStatus.SKIPPED

    mock_crm.find_customer.assert_not_called()
    mock_slack.send_notification.assert_not_called()


def test_partial_failure_case_b_crm_lookup_failure(isolated_orchestrator):
    """Case B: CRM lookup fails -> CRM update and Slack are SKIPPED."""
    orch, _ = isolated_orchestrator
    spec = orch.prepare_workflow(auto_approve=True)
    plan = orch.create_plan(spec.workflow_id)

    mock_gmail = MagicMock(spec=GmailApiClient)
    mock_gmail.is_configured.return_value = True
    mock_gmail.is_authenticated.return_value = True
    mock_gmail.search_messages.return_value = GmailSearchResult(
        query="has:attachment",
        total_found=1,
        messages=[GmailMessageSummary(message_id="msg-1", thread_id="t-1", snippet="s", subject="sub", sender="r@e.com", timestamp="2026-09-27T10:00:00Z")],
        searched_at="2026-09-27T10:00:00Z",
    )
    mock_gmail.download_attachment.return_value = (b"pdf bytes", {"filename": "inv.pdf", "mime_type": "application/pdf"})

    mock_crm = MagicMock(spec=CrmApiClient)
    mock_crm.find_customer.side_effect = RuntimeError("CRM database connection timeout")

    mock_slack = MagicMock(spec=SlackApiClient)

    orch.engine.registry.register(GmailApiExecutor(client=mock_gmail))
    orch.engine.registry.register(CrmApiExecutor(client=mock_crm))
    orch.engine.registry.register(SlackApiExecutor(client=mock_slack))

    audit = orch.execute_live(plan.execution_plan_id)
    assert audit.status == ExecutionOverallStatus.FAILED
    assert audit.step_results[0].status == ExecutionStepStatus.SUCCESS
    assert audit.step_results[1].status == ExecutionStepStatus.SUCCESS
    assert audit.step_results[2].status == ExecutionStepStatus.FAILED
    assert audit.step_results[3].status == ExecutionStepStatus.SKIPPED
    assert audit.step_results[4].status == ExecutionStepStatus.SKIPPED

    mock_crm.update_customer.assert_not_called()
    mock_slack.send_notification.assert_not_called()


def test_partial_failure_case_c_crm_update_failure(isolated_orchestrator):
    """Case C: CRM update fails -> Slack is SKIPPED."""
    orch, _ = isolated_orchestrator
    spec = orch.prepare_workflow(auto_approve=True)
    plan = orch.create_plan(spec.workflow_id)

    mock_gmail = MagicMock(spec=GmailApiClient)
    mock_gmail.is_configured.return_value = True
    mock_gmail.is_authenticated.return_value = True
    mock_gmail.search_messages.return_value = GmailSearchResult(
        query="has:attachment",
        total_found=1,
        messages=[GmailMessageSummary(message_id="msg-1", thread_id="t-1", snippet="s", subject="sub", sender="r@e.com", timestamp="2026-09-27T10:00:00Z")],
        searched_at="2026-09-27T10:00:00Z",
    )
    mock_gmail.download_attachment.return_value = (b"pdf bytes", {"filename": "inv.pdf", "mime_type": "application/pdf"})

    mock_crm = MagicMock(spec=CrmApiClient)
    mock_crm.find_customer.return_value = CrmCustomer(
        customer_id="cust-001", name="Rahul", email="r@e.com", company="Acme", status="active",
        created_at="d", updated_at="d"
    )
    mock_crm.update_customer.side_effect = RuntimeError("Conflict: Record locked by another transaction")

    mock_slack = MagicMock(spec=SlackApiClient)

    orch.engine.registry.register(GmailApiExecutor(client=mock_gmail))
    orch.engine.registry.register(CrmApiExecutor(client=mock_crm))
    orch.engine.registry.register(SlackApiExecutor(client=mock_slack))

    audit = orch.execute_live(plan.execution_plan_id)
    assert audit.status == ExecutionOverallStatus.FAILED
    assert audit.step_results[2].status == ExecutionStepStatus.SUCCESS
    assert audit.step_results[3].status == ExecutionStepStatus.FAILED
    assert audit.step_results[4].status == ExecutionStepStatus.SKIPPED
    mock_slack.send_notification.assert_not_called()


def test_partial_failure_case_d_slack_failure_after_crm_success(isolated_orchestrator):
    """Case D: Slack fails after CRM success -> CRM remains SUCCESS, Slack FAILED, verification is FAILED."""
    orch, _ = isolated_orchestrator
    spec = orch.prepare_workflow(auto_approve=True)
    plan = orch.create_plan(spec.workflow_id)

    mock_gmail = MagicMock(spec=GmailApiClient)
    mock_gmail.is_configured.return_value = True
    mock_gmail.is_authenticated.return_value = True
    mock_gmail.search_messages.return_value = GmailSearchResult(
        query="has:attachment",
        total_found=1,
        messages=[GmailMessageSummary(message_id="msg-1", thread_id="t-1", snippet="s", subject="sub", sender="r@e.com", timestamp="2026-09-27T10:00:00Z")],
        searched_at="2026-09-27T10:00:00Z",
    )
    mock_gmail.download_attachment.return_value = (b"pdf bytes", {"filename": "inv.pdf", "mime_type": "application/pdf"})

    mock_crm = MagicMock(spec=CrmApiClient)
    updated_cust = CrmCustomer(
        customer_id="cust-001", name="Rahul", email="r@e.com", company="Acme", status="replacement_processed",
        created_at="d", updated_at="d"
    )
    mock_crm.find_customer.return_value = updated_cust
    mock_crm.update_customer.return_value = updated_cust
    mock_crm.get_customer.return_value = updated_cust

    mock_slack = MagicMock(spec=SlackApiClient)
    mock_slack.default_channel_id = "C0123456789"
    mock_slack.send_notification.side_effect = RuntimeError("Slack channel archived")

    orch.engine.registry.register(GmailApiExecutor(client=mock_gmail))
    orch.engine.registry.register(CrmApiExecutor(client=mock_crm))
    orch.engine.registry.register(SlackApiExecutor(client=mock_slack))

    orch.verification_engine.strategy_registry.register(GmailVerificationStrategy())
    orch.verification_engine.strategy_registry.register(CrmVerificationStrategy(client=mock_crm))
    orch.verification_engine.strategy_registry.register(SlackVerificationStrategy(client=mock_slack))

    audit = orch.execute_live(plan.execution_plan_id)
    assert audit.status == ExecutionOverallStatus.FAILED
    assert audit.step_results[3].status == ExecutionStepStatus.SUCCESS  # CRM update succeeded
    assert audit.step_results[4].status == ExecutionStepStatus.FAILED   # Slack notification failed

    # Independent Verification confirms workflow is NOT falsely marked verified
    verif = orch.verify_execution(audit.execution_id)
    assert verif.overall_status == VerificationStatus.FAILED

    # Learning Engine records failure classification
    profile = orch.learn_from_execution(spec.workflow_id)
    assert profile.failed_executions == 1
    assert profile.verified_executions == 0


# =========================================================================
# 6. Idempotency Protection
# =========================================================================
def test_phase16_idempotency_protection(isolated_orchestrator):
    """Executing plan with an existing idempotency_key returns cached record without re-running."""
    orch, _ = isolated_orchestrator
    spec = orch.prepare_workflow(auto_approve=True)
    plan = orch.create_plan(spec.workflow_id)

    idemp_key = f"idemp-{uuid.uuid4().hex}"
    first_run = orch.engine.execute_plan(
        execution_plan_id=plan.execution_plan_id,
        idempotency_key=idemp_key,
        execution_mode=ExecutionMode.DRY_RUN,
    )

    # Subsequent execution with same key returns identical record
    second_run = orch.engine.execute_plan(
        execution_plan_id=plan.execution_plan_id,
        idempotency_key=idemp_key,
        execution_mode=ExecutionMode.DRY_RUN,
    )
    assert second_run.execution_id == first_run.execution_id


# =========================================================================
# 7. Security: Token Exclusion
# =========================================================================
def test_phase16_security_token_exclusion(isolated_orchestrator):
    """Confirms credentials, bearer tokens, and secrets are strictly excluded from audit records."""
    orch, _ = isolated_orchestrator
    spec = orch.prepare_workflow(auto_approve=True)
    plan = orch.create_plan(spec.workflow_id)

    audit = orch.run_dry_run(plan.execution_plan_id)
    audit_json = audit.model_dump_json()

    assert "xoxb" not in audit_json
    assert "Bearer" not in audit_json
    assert "token.json" not in audit_json


# =========================================================================
# 8. Real Live E2E Integration Test (Conditional on Live Environment)
# =========================================================================
def test_live_phase16_e2e_workflow_conditional(tmp_path):
    """Conditional real live demonstration exercising real Gmail API, real CRM API, and real Slack API.

    Only runs when:
    - SLACK_BOT_TOKEN and SLACK_CHANNEL_ID exist in root .env
    - token.json exists (Gmail OAuth)
    - WorkFlowOS Demo CRM is reachable or initialized
    """
    token = os.getenv("SLACK_BOT_TOKEN")
    channel = os.getenv("SLACK_CHANNEL_ID")
    token_json_exists = Path("token.json").exists()

    if not token or not channel or str(token).startswith("xoxb-placeholder") or not token_json_exists:
        pytest.skip(
            f"LIVE PHASE 16 E2E TEST: SKIPPED (live credentials not fully present: "
            f"slack_token={bool(token and not str(token).startswith('xoxb-placeholder'))}, "
            f"slack_channel={bool(channel)}, "
            f"gmail_token={token_json_exists})"
        )

    # 1. Initialize real clients
    gmail_client = GmailApiClient(credentials_path="credentials.json", token_path="token.json")
    if not gmail_client.is_authenticated():
        pytest.skip("LIVE PHASE 16 E2E TEST: SKIPPED — Gmail API client not authenticated.")

    crm_client = CrmApiClient(base_url="http://127.0.0.1:8001/api/crm")
    # Ensure CRM test customer exists and is in 'pending_replacement' state on port 8001
    try:
        cust = crm_client.get_customer("cust-001")
        if not cust:
            crm_client.create_customer(
                {
                    "customer_id": "cust-001",
                    "name": "Rahul Sharma",
                    "email": "rahul.sharma@example.com",
                    "company": "Acme Corp",
                    "status": "pending_replacement",
                    "notes": "Initial customer record for live E2E demo",
                }
            )
        else:
            crm_client.update_customer(
                "cust-001",
                {"status": "pending_replacement", "notes": "Reset for live E2E run"},
            )
    except Exception as e:
        pytest.skip(f"LIVE PHASE 16 E2E TEST: SKIPPED — Demo CRM service on port 8001 unavailable: {e}")

    slack_client = SlackApiClient(bot_token=token, default_channel_id=channel)

    # 2. Build and setup Phase 16 Orchestrator with real clients
    orch = Phase16Orchestrator()
    orch.engine.registry.register(GmailApiExecutor(client=gmail_client))
    orch.engine.registry.register(CrmApiExecutor(client=crm_client))
    orch.engine.registry.register(SlackApiExecutor(client=slack_client))

    orch.verification_engine.strategy_registry.register(GmailVerificationStrategy())
    orch.verification_engine.strategy_registry.register(CrmVerificationStrategy(client=crm_client))
    orch.verification_engine.strategy_registry.register(SlackVerificationStrategy(client=slack_client))

    # 3. Create approved canonical specification
    spec = orch.prepare_workflow(auto_approve=True, reviewer="Live Demo Operator")
    plan = orch.create_plan(
        spec.workflow_id,
        runtime_inputs={"search_query": "has:attachment", "customer_query": "cust-001"},
    )

    # 4. Dry Run first
    dry_audit = orch.run_dry_run(plan.execution_plan_id)
    assert dry_audit.status == ExecutionOverallStatus.COMPLETED
    assert dry_audit.execution_mode == ExecutionMode.DRY_RUN

    # 5. Real Live Execution
    audit = orch.execute_live(plan.execution_plan_id)
    assert audit.status == ExecutionOverallStatus.COMPLETED
    assert len(audit.step_results) == 5
    for s in audit.step_results:
        assert s.status == ExecutionStepStatus.SUCCESS

    # Step 1: Real Gmail search found messages
    assert audit.step_results[0].output.get("total_found") is not None

    # Step 2: Real attachment downloaded into sandbox
    downloaded_path = audit.step_results[1].output.get("saved_path")
    assert downloaded_path is not None and Path(downloaded_path).exists()

    # Step 3: Real CRM customer lookup
    assert audit.step_results[2].output.get("customer") is not None

    # Step 4: Real CRM record updated
    assert audit.step_results[3].output.get("updated_fields") is not None

    # Step 5: Real Slack notification sent
    slack_ts = audit.step_results[4].output.get("ts")
    assert slack_ts is not None

    # 6. Real Independent Verification
    verif = orch.verify_execution(audit.execution_id)
    assert verif.overall_status == VerificationStatus.VERIFIED
    assert len(verif.checks) == 5

    # 7. Real Learning update
    profile = orch.learn_from_execution(spec.workflow_id)
    assert profile.total_executions >= 1
    assert profile.verified_executions >= 1

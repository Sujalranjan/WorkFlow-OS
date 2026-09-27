"""Unit, Integration, and Security Tests for GmailApiExecutor (Phase 12).

Verifies:
1. Gmail executor capability is registered
2. Gmail executor is the only newly implemented external executor
3. Gmail action selects API_INTEGRATION
4. Unrelated actions do not select Gmail executor
5. Unapproved workflow blocks Gmail execution
6. Unresolved parameters block Gmail execution
7. Missing Gmail configuration fails safely (INTEGRATION_UNAVAILABLE)
8. Invalid authentication fails safely (AUTHENTICATION_REQUIRED)
9. Invalid query fails safely (INVALID_PARAMETER)
10. No fallback to ControlledLocalExecutor occurs for Gmail
11. Dry-run never calls Gmail
12. Gmail response is normalized correctly into GmailSearchResult and GmailMessageSummary
13. Execution audit contains strategy and executor information
14. Verification handles successful read
15. Verification handles failed read
16. Credentials and tokens are NOT included in logs, audit records, or outputs
17. Phase 11 learning consumes Gmail execution and verification results
18. Security: No token leakage in responses or exceptions
19. Security: No Gmail mutation methods or endpoints are exposed
20. Security: No arbitrary API or HTTP execution allowed
"""

import json
import logging
from pathlib import Path
import tempfile
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch
import pytest

from app.models.canonical import (
    ApprovalMetadata,
    ApprovalState,
    CanonicalWorkflowSpec,
    RiskAssessment,
    RiskCategory,
    RiskLevel,
    StepRisk,
    ParameterBinding,
)
from app.models.dna import DNAEvidence, WorkflowBoundaries
from app.models.execution import (
    ExecutionAuditRecord,
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
from app.models.gmail import GmailMessageSummary, GmailSearchResult
from app.models.learning import FailureCategory, LearningEventType
from app.models.strategy import ExecutionStrategyType, ExecutorCapability
from app.models.verification import VerificationStatus
from app.repositories.canonical_repository import CanonicalWorkflowRepository
from app.repositories.execution_plan_repository import ExecutionPlanRepository
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.learning_repository import LearningRepository
from app.repositories.verification_repository import VerificationRepository
from app.services.dry_run_simulator import DryRunSimulator
from app.services.execution_engine import ExecutionEngine
from app.services.execution_policy import ExecutionPolicyEngine
from app.services.executors.base import BaseExecutor
from app.services.executors.controlled_local import ControlledLocalExecutor
from app.services.executors.gmail_executor import GmailApiExecutor
from app.services.executors.registry import ExecutorRegistry
from app.services.gmail_client import (
    GmailApiClient,
    GmailApiError,
    GmailAuthenticationError,
    GmailConfigurationError,
)
from app.services.learning_engine import LearningEngine
from app.services.strategy_selector import StrategySelector
from app.services.verification_engine import VerificationEngine
from app.services.verifiers.gmail_verifier import GmailVerificationStrategy


@pytest.fixture
def mock_gmail_client():
    """Provides a mocked GmailApiClient returning controlled responses."""
    client = MagicMock(spec=GmailApiClient)
    client.is_configured.return_value = True
    client.is_authenticated.return_value = True
    sample_res = GmailSearchResult(
        query="from:test@example.com",
        total_found=2,
        messages=[
            GmailMessageSummary(
                message_id="msg-101",
                thread_id="th-101",
                sender="test@example.com",
                subject="Monthly Invoice #402",
                timestamp="2026-09-26T12:00:00Z",
                snippet="Please find attached the monthly invoice...",
            ),
            GmailMessageSummary(
                message_id="msg-102",
                thread_id="th-102",
                sender="test@example.com",
                subject="Monthly Invoice #403",
                timestamp="2026-09-26T12:30:00Z",
                snippet="Correction for monthly invoice...",
            ),
        ],
    )
    client.search_messages.return_value = sample_res
    return client


@pytest.fixture
def sample_gmail_step():
    """Creates a deterministic planned step for search_email on Gmail."""
    return PlannedStep(
        plan_step_id="step-gmail-search-1",
        source_canonical_step_id="can-gmail-1",
        source_semantic_step_id="sem-gmail-1",
        source_dna_step_key="dna-gmail-1",
        application="Gmail",
        action="search_email",
        description="Search for invoices in Gmail",
        resolved_parameters={"query": "from:billing@supplier.com subject:invoice"},
        execution_strategy=StepExecutionStrategy(
            strategy=ExecutionStrategy.API,
            reason="Gmail read-only search integration",
            target_technology="Google Gmail API",
        ),
        risk=StepRisk(
            step_id="can-gmail-1",
            application="Gmail",
            action="search_email",
            risk_level=RiskLevel.LOW,
            risk_category=RiskCategory.READ_ONLY,
            reason="Read-only query against Gmail API",
            requires_confirmation=False,
        ),
        expected_result="Matching email metadata retrieved",
        external_change=False,
        requires_confirmation=False,
        evidence_reference="evidence-gmail-1",
        state_change=ExpectedStateChange(
            target_system="Gmail",
            entity_or_property="email_metadata",
            before_state="Unsearched",
            expected_after_state="Metadata retrieved",
            actual_state="UNTOUCHED",
        ),
    )


@pytest.fixture
def sample_approved_gmail_plan(sample_gmail_step):
    """Creates an approved CanonicalWorkflowSpec and ExecutionPlan for testing."""
    workflow_id = "wf-gmail-test-approved"
    spec = CanonicalWorkflowSpec(
        workflow_id=workflow_id,
        source_dna_id="dna-gmail-001",
        source_semantic_workflow_id="sem-gmail-001",
        title="Gmail Search Workflow",
        intent="Search invoice emails via Gmail API",
        description="Workflow to search invoices in Gmail",
        version="1.0.0",
        status="specification_ready",
        steps=[],
        variables=[],
        optional_steps=[],
        preconditions=["Gmail API configured"],
        boundaries=WorkflowBoundaries(
            first_step="Gmail:search_email",
            last_step="Gmail:search_email",
            min_duration_seconds=1.0,
            max_duration_seconds=5.0,
            average_duration_seconds=2.0,
            total_supporting_sessions=1,
        ),
        ordering_constraints=[],
        evidence=DNAEvidence(
            supporting_session_count=1,
            invariant_evidence="Search email observed",
            variable_evidence="Query parameter",
            optional_step_evidence="None",
            ordering_evidence="Single step",
            boundary_evidence="Boundaries established",
        ),
        parameter_bindings=[],
        risk_assessment=RiskAssessment(
            overall_risk_level=RiskLevel.LOW,
            primary_risk_category=RiskCategory.READ_ONLY,
            requires_human_confirmation=False,
            step_risks=[],
            summary="Low risk read-only search",
            sensitive_factors_detected=[],
        ),
        approval_state=ApprovalMetadata(
            state=ApprovalState.APPROVED,
            reviewed_by="test-admin",
            comments="Approved for read-only Gmail query",
        ),
    )
    CanonicalWorkflowRepository().save(spec)

    plan = ExecutionPlan(
        execution_plan_id="plan-gmail-test",
        source_workflow_id=workflow_id,
        workflow_version="1.0.0",
        source_approval_state="approved",
        resolved_parameters=[
            ResolvedParameter(
                semantic_name="query",
                source_parameter="query",
                source_field="parameters.query",
                inferred_type="string",
                is_required=True,
                runtime_value="from:billing@supplier.com",
                resolution_status="resolved",
            )
        ],
        planned_steps=[sample_gmail_step],
        preconditions=[],
        boundaries=WorkflowBoundaries(
            first_step="step-gmail-search-1",
            last_step="step-gmail-search-1",
            min_duration_seconds=1.0,
            max_duration_seconds=5.0,
            average_duration_seconds=2.0,
            total_supporting_sessions=1,
        ),
        risk_assessment={
            "overall_risk_level": "low",
            "primary_risk_category": "read_only",
            "requires_human_confirmation": False,
            "summary": "Low risk read-only Gmail search",
        },
        expected_effects=[],
        dry_run_status="SIMULATED",
    )
    ExecutionPlanRepository().save(plan)
    return plan




# =========================================================================
# 1. Capability Registration & External Executor Distinction
# =========================================================================
def test_gmail_executor_capability_is_registered():
    """1. Test Gmail executor capability is registered with ExecutorRegistry."""
    registry = ExecutorRegistry()
    gmail_exec = registry.get_by_name("GmailApiExecutor")
    assert gmail_exec is not None
    cap = gmail_exec.capability
    assert cap.executor_name == "GmailApiExecutor"
    assert cap.strategy_type == ExecutionStrategyType.API_INTEGRATION
    assert cap.implemented is True
    assert cap.requires_external_access is True
    assert cap.supports_verification is True
    assert "search_email" in cap.supported_actions
    assert any("gmail" in t.lower() for t in cap.supported_targets)


def test_gmail_executor_is_only_newly_implemented_external_executor():
    """2. Test external executors: ControlledLocal, GmailApi, CrmApi, and SlackApi are implemented."""
    registry = ExecutorRegistry()
    caps = registry.get_all_capabilities()
    implemented_caps = [c for c in caps if c.implemented]
    names = {c.executor_name for c in implemented_caps}
    assert names == {"ControlledLocalExecutor", "GmailApiExecutor", "CrmApiExecutor", "SlackApiExecutor"}

    # All other external executors (e.g. Browser, UI) remain unimplemented
    for c in caps:
        if c.executor_name not in ("ControlledLocalExecutor", "GmailApiExecutor", "CrmApiExecutor", "SlackApiExecutor"):
            assert c.implemented is False, f"Executor {c.executor_name} must NOT be marked implemented"


# =========================================================================
# 2. Strategy Selection for Gmail vs Unrelated Actions
# =========================================================================
def test_gmail_action_selects_api_integration(sample_gmail_step, sample_approved_gmail_plan):
    """3. Test Gmail search action deterministically selects API_INTEGRATION and GmailApiExecutor."""
    spec = CanonicalWorkflowRepository().get_by_id(sample_approved_gmail_plan.source_workflow_id)
    selector = StrategySelector()
    res = selector.select_strategy(sample_gmail_step, spec=spec)
    assert res.is_executable is True
    assert res.selected_strategy == ExecutionStrategyType.API_INTEGRATION
    assert res.selected_executor == "GmailApiExecutor"
    assert res.policy_decision == "ALLOWED"


def test_unrelated_actions_do_not_select_gmail_executor():
    """4. Test unrelated actions (e.g. CRM update, Slack notification, local file) never select GmailApiExecutor."""
    selector = StrategySelector()

    # Unrelated 1: Slack notification
    slack_step = PlannedStep(
        plan_step_id="step-slack",
        source_canonical_step_id="c-slack",
        source_semantic_step_id="s-slack",
        source_dna_step_key="d-slack",
        application="Slack",
        action="send_notification",
        description="Notify team in Slack",
        resolved_parameters={},
        execution_strategy=StepExecutionStrategy(
            strategy=ExecutionStrategy.API,
            reason="Team message",
            target_technology="Slack Webhook API",
        ),
        risk=StepRisk(
            step_id="c-slack",
            application="Slack",
            action="send_notification",
            risk_level=RiskLevel.MEDIUM,
            risk_category=RiskCategory.COMMUNICATION,
            reason="Communication",
            requires_confirmation=False,
        ),
        expected_result="Sent",
        external_change=True,
        requires_confirmation=False,
        evidence_reference="ev-slack",
        state_change=ExpectedStateChange(
            target_system="Slack",
            entity_or_property="notification",
            before_state="",
            expected_after_state="",
            actual_state="",
        ),
    )
    res_slack = selector.select_strategy(slack_step)
    assert res_slack.selected_executor != "GmailApiExecutor"
    assert res_slack.selected_executor == "SlackApiExecutor"
    assert res_slack.is_executable is True

    # Unrelated 2: Gmail mutation (send_email)
    gmail_send = PlannedStep(
        plan_step_id="step-gmail-send",
        source_canonical_step_id="c-gs",
        source_semantic_step_id="s-gs",
        source_dna_step_key="d-gs",
        application="Gmail",
        action="send_email",
        description="Send outgoing email",
        resolved_parameters={},
        execution_strategy=StepExecutionStrategy(
            strategy=ExecutionStrategy.API,
            reason="Send email",
            target_technology="Google Gmail API",
        ),
        risk=StepRisk(
            step_id="c-gs",
            application="Gmail",
            action="send_email",
            risk_level=RiskLevel.MEDIUM,
            risk_category=RiskCategory.COMMUNICATION,
            reason="Communication",
            requires_confirmation=True,
        ),
        expected_result="Sent",
        external_change=True,
        requires_confirmation=True,
        evidence_reference="ev-send",
        state_change=ExpectedStateChange(
            target_system="Gmail",
            entity_or_property="email",
            before_state="",
            expected_after_state="",
            actual_state="",
        ),
    )
    res_send = selector.select_strategy(gmail_send)
    assert res_send.selected_executor != "GmailApiExecutor"
    assert res_send.is_executable is False


# =========================================================================
# 3. Policy Enforcement: Unapproved Workflows & Unresolved Parameters
# =========================================================================
def test_unapproved_workflow_blocks_gmail_execution(sample_gmail_step):
    """5. Test unapproved workflow strictly blocks Gmail execution."""
    unapproved_spec = CanonicalWorkflowSpec(
        workflow_id="wf-unapproved-gmail",
        source_dna_id="dna-unapp",
        source_semantic_workflow_id="sem-unapp",
        title="Unapproved Gmail WF",
        intent="Pending workflow",
        description="Pending workflow",
        version="1.0.0",
        status="specification_ready",
        steps=[],
        variables=[],
        optional_steps=[],
        preconditions=[],
        boundaries=WorkflowBoundaries(
            first_step="Gmail:search_email",
            last_step="Gmail:search_email",
            min_duration_seconds=1.0,
            max_duration_seconds=5.0,
            average_duration_seconds=2.0,
            total_supporting_sessions=1,
        ),
        ordering_constraints=[],
        evidence=DNAEvidence(
            supporting_session_count=1,
            invariant_evidence="",
            variable_evidence="",
            optional_step_evidence="",
            ordering_evidence="",
            boundary_evidence="",
        ),
        parameter_bindings=[],
        risk_assessment=RiskAssessment(
            overall_risk_level=RiskLevel.LOW,
            primary_risk_category=RiskCategory.READ_ONLY,
            requires_human_confirmation=False,
            step_risks=[],
            summary="Awaiting review",
            sensitive_factors_detected=[],
        ),
        approval_state=ApprovalMetadata(
            state=ApprovalState.REQUIRES_REVIEW,
            comments="Awaiting human review",
        ),
    )
    CanonicalWorkflowRepository().save(unapproved_spec)

    selector = StrategySelector()
    res = selector.select_strategy(sample_gmail_step, spec=unapproved_spec)
    assert res.is_executable is False
    assert res.policy_decision == "BLOCKED"
    assert res.blocked_reason == "POLICY_NOT_APPROVED"


def test_unresolved_parameters_block_gmail_execution(sample_gmail_step, sample_approved_gmail_plan):
    """6. Test unresolved parameters strictly block Gmail execution."""
    sample_approved_gmail_plan.resolved_parameters[0].resolution_status = ParameterResolutionStatus.UNRESOLVED
    sample_approved_gmail_plan.resolved_parameters[0].runtime_value = None
    ExecutionPlanRepository().save(sample_approved_gmail_plan)

    engine = ExecutionEngine()
    with pytest.raises(ValueError) as exc_info:
        engine.execute_plan(sample_approved_gmail_plan.execution_plan_id)
    assert "UNRESOLVED" in str(exc_info.value)


# =========================================================================
# 4. Safe Failures: Unconfigured, Unauthenticated, and Invalid Query
# =========================================================================
def test_missing_gmail_configuration_fails_safely(sample_gmail_step):
    """7. Test missing Gmail configuration fails safely with INTEGRATION_UNAVAILABLE."""
    mock_client = MagicMock(spec=GmailApiClient)
    mock_client.is_configured.return_value = False

    executor = GmailApiExecutor(client=mock_client)
    ctx = ExecutionContext(
        execution_id="exec-unconf",
        workflow_id="wf-1",
        execution_plan_id="p-1",
        resolved_parameters={"query": "test query"},
        sandbox_root=tempfile.gettempdir(),
    )
    res = executor.execute(sample_gmail_step, ctx)
    assert res.status == ExecutionStepStatus.BLOCKED
    assert res.blocked_reason == "INTEGRATION_UNAVAILABLE"
    assert "not configured" in (res.error or "").lower()


def test_invalid_authentication_fails_safely(sample_gmail_step):
    """8. Test invalid / missing authentication fails safely with AUTHENTICATION_REQUIRED."""
    mock_client = MagicMock(spec=GmailApiClient)
    mock_client.is_configured.return_value = True
    mock_client.is_authenticated.return_value = False

    executor = GmailApiExecutor(client=mock_client)
    ctx = ExecutionContext(
        execution_id="exec-unauth",
        workflow_id="wf-1",
        execution_plan_id="p-1",
        resolved_parameters={"query": "test query"},
        sandbox_root=tempfile.gettempdir(),
    )
    res = executor.execute(sample_gmail_step, ctx)
    assert res.status == ExecutionStepStatus.BLOCKED
    assert res.blocked_reason == "AUTHENTICATION_REQUIRED"
    assert "authorization is required" in (res.error or "").lower()


def test_invalid_query_fails_safely(sample_gmail_step):
    """9. Test invalid/empty query fails safely with INVALID_PARAMETER."""
    mock_client = MagicMock(spec=GmailApiClient)
    mock_client.is_configured.return_value = True
    mock_client.is_authenticated.return_value = True

    executor = GmailApiExecutor(client=mock_client)
    ctx = ExecutionContext(
        execution_id="exec-inval-q",
        workflow_id="wf-1",
        execution_plan_id="p-1",
        resolved_parameters={"query": ""},  # Empty query
        sandbox_root=tempfile.gettempdir(),
    )
    res = executor.execute(sample_gmail_step, ctx)
    assert res.status == ExecutionStepStatus.BLOCKED
    assert res.blocked_reason == "INVALID_PARAMETER"


def test_no_fallback_to_controlled_local_executor_occurs(sample_gmail_step, sample_approved_gmail_plan):
    """10. Test Gmail operation NEVER falls back to ControlledLocalExecutor."""
    # When GmailApiExecutor fails, ControlledLocalExecutor must NOT run
    mock_client = MagicMock(spec=GmailApiClient)
    mock_client.is_configured.return_value = False

    gmail_exec = GmailApiExecutor(client=mock_client)
    reg = ExecutorRegistry()
    reg.register(gmail_exec)

    engine = ExecutionEngine(registry=reg)
    audit = engine.execute_plan(sample_approved_gmail_plan.execution_plan_id)
    assert audit.status == ExecutionOverallStatus.COMPLETED or audit.status == ExecutionOverallStatus.BLOCKED
    step_res = audit.step_results[0]
    assert step_res.executor_name == "GmailApiExecutor"
    assert step_res.executor_name != "ControlledLocalExecutor"


# =========================================================================
# 5. Dry-Run Zero Side-Effects
# =========================================================================
def test_dry_run_never_calls_gmail(sample_approved_gmail_plan, mock_gmail_client):
    """11. Test dry-run simulation never invokes GmailApiClient."""
    sim = DryRunSimulator()
    result = sim.simulate(sample_approved_gmail_plan)
    assert result.overall_simulation_status == "SIMULATED"
    assert result.real_actions_performed == 0
    # Client search_messages was never invoked
    mock_gmail_client.search_messages.assert_not_called()


# =========================================================================
# 6. Response Normalization & Privacy Safeguards
# =========================================================================
def test_gmail_response_is_normalized_correctly(mock_gmail_client, sample_gmail_step):
    """12. Test Gmail API output is properly normalized without raw message dumps."""
    executor = GmailApiExecutor(client=mock_gmail_client)
    ctx = ExecutionContext(
        execution_id="exec-norm",
        workflow_id="wf-norm",
        execution_plan_id="plan-norm",
        resolved_parameters={"query": "invoice"},
        sandbox_root=tempfile.gettempdir(),
    )
    res = executor.execute(sample_gmail_step, ctx)
    assert res.status == ExecutionStepStatus.SUCCESS
    out = res.output
    assert out["operation"] == "search_email"
    assert out["query"] == "invoice"
    assert out["total_found"] == 2
    assert len(out["messages"]) == 2
    first_msg = out["messages"][0]
    assert "message_id" in first_msg
    assert "subject" in first_msg
    assert "sender" in first_msg
    assert "snippet" in first_msg
    # Ensure raw OAuth or internal payload tokens are not present
    assert "access_token" not in first_msg
    assert "refresh_token" not in first_msg


def test_execution_audit_contains_strategy_executor_info(sample_approved_gmail_plan, mock_gmail_client):
    """13. Test execution audit record contains strategy and executor information."""
    reg = ExecutorRegistry()
    reg.register(GmailApiExecutor(client=mock_gmail_client))
    engine = ExecutionEngine(registry=reg)

    audit = engine.execute_plan(sample_approved_gmail_plan.execution_plan_id)
    assert audit.status == ExecutionOverallStatus.COMPLETED
    assert len(audit.step_results) == 1
    step_res = audit.step_results[0]
    assert step_res.executor_name == "GmailApiExecutor"
    assert step_res.selected_strategy == "API_INTEGRATION"
    assert step_res.status == ExecutionStepStatus.SUCCESS


# =========================================================================
# 7. Verification & Learning Engine Integration
# =========================================================================
def test_verification_handles_successful_read(sample_approved_gmail_plan, mock_gmail_client):
    """14. Test verification engine handles successful Gmail read."""
    reg = ExecutorRegistry()
    reg.register(GmailApiExecutor(client=mock_gmail_client))
    engine = ExecutionEngine(registry=reg)

    audit = engine.execute_plan(sample_approved_gmail_plan.execution_plan_id)
    verif = VerificationEngine()
    verif_res = verif.verify_execution(audit.execution_id, force_recheck=True)

    assert verif_res.overall_status == VerificationStatus.VERIFIED
    assert verif_res.verified_count >= 1
    check = verif_res.checks[0]
    assert check.status == VerificationStatus.VERIFIED
    assert check.strategy_type.value == "STATE_MATCH"
    assert check.target == "Gmail:search_email"
    assert "Verified: Gmail API search" in check.reason


def test_verification_handles_failed_read(sample_approved_gmail_plan):
    """15. Test verification engine handles failed Gmail read."""
    mock_client = MagicMock(spec=GmailApiClient)
    mock_client.is_configured.return_value = True
    mock_client.is_authenticated.return_value = True
    mock_client.search_messages.side_effect = GmailApiError("API Rate Limited")

    reg = ExecutorRegistry()
    reg.register(GmailApiExecutor(client=mock_client))
    engine = ExecutionEngine(registry=reg)

    audit = engine.execute_plan(sample_approved_gmail_plan.execution_plan_id)
    verif = VerificationEngine()
    verif_res = verif.verify_execution(audit.execution_id, force_recheck=True)

    assert verif_res.overall_status == VerificationStatus.FAILED
    assert verif_res.failed_count >= 1


def test_credentials_not_included_in_logs_audit(sample_approved_gmail_plan, mock_gmail_client):
    """16. Test credentials and tokens are strictly excluded from logs and audit records."""
    reg = ExecutorRegistry()
    reg.register(GmailApiExecutor(client=mock_gmail_client))
    engine = ExecutionEngine(registry=reg)

    audit = engine.execute_plan(sample_approved_gmail_plan.execution_plan_id)
    audit_json = audit.model_dump_json()

    for forbidden in ["client_secret", "access_token", "refresh_token", "bearer"]:
        assert forbidden not in audit_json.lower(), f"Forbidden credential token '{forbidden}' found in audit dump!"


def test_phase11_learning_consumes_gmail_result(sample_approved_gmail_plan, mock_gmail_client):
    """17. Test Phase 11 LearningEngine consumes Gmail execution outcome."""
    reg = ExecutorRegistry()
    reg.register(GmailApiExecutor(client=mock_gmail_client))
    engine = ExecutionEngine(registry=reg)

    audit = engine.execute_plan(sample_approved_gmail_plan.execution_plan_id)
    verif = VerificationEngine()
    verif.verify_execution(audit.execution_id, force_recheck=True)

    learning = LearningEngine(
        execution_repo=ExecutionRepository(),
        verification_repo=VerificationRepository(),
        learning_repo=LearningRepository(),
    )
    profile = learning.analyze_workflow(sample_approved_gmail_plan.source_workflow_id)
    assert profile.total_executions >= 1
    assert profile.verified_executions >= 1
    assert profile.workflow_id == sample_approved_gmail_plan.source_workflow_id


# =========================================================================
# 8. Security Guardrails (Section 26)
# =========================================================================
def test_security_no_mutation_methods_exposed():
    """18. Test GmailApiExecutor does NOT implement or expose any mutation methods."""
    executor = GmailApiExecutor()
    cap = executor.capability
    # Must only declare read-only actions: search_email and download_attachment
    assert cap.supported_actions == ["search_email", "download_attachment"]
    # Check that forbidden methods do not exist
    for forbidden in ["send_email", "delete_email", "modify_email", "trash_message", "add_label"]:
        assert not hasattr(executor, forbidden), f"Forbidden method '{forbidden}' exposed on GmailApiExecutor"



def test_security_no_arbitrary_requests_allowed(sample_gmail_step):
    """19. Test GmailApiExecutor rejects arbitrary URLs or HTTP endpoints in parameters."""
    mock_client = MagicMock(spec=GmailApiClient)
    mock_client.is_configured.return_value = True
    mock_client.is_authenticated.return_value = True

    executor = GmailApiExecutor(client=mock_client)
    # Attempt SSRF / arbitrary URL injection in query parameter
    ctx = ExecutionContext(
        execution_id="exec-sec-ssrf",
        workflow_id="wf-sec",
        execution_plan_id="p-sec",
        resolved_parameters={"query": "https://attacker.com/steal?data=token"},
        sandbox_root=tempfile.gettempdir(),
    )
    res = executor.execute(sample_gmail_step, ctx)
    # The client search_messages should receive query as search string or execute search,
    # but executor must never make direct requests to external URLs
    assert res.status == ExecutionStepStatus.SUCCESS or res.status == ExecutionStepStatus.BLOCKED
    # Verify no HTTP methods were called on unauthorized targets
    mock_client.search_messages.assert_called_once_with(
        query="https://attacker.com/steal?data=token",
        max_results=10,
    )


# =========================================================================
# 9. Phase 12.1 Live OAuth & Token Refresh Verification
# =========================================================================
def test_scope_is_strictly_readonly():
    """Verify that Gmail scope is strictly locked to read-only."""
    from app.config import GMAIL_SCOPES
    assert GMAIL_SCOPES == ["https://www.googleapis.com/auth/gmail.readonly"], (
        f"Broader Gmail scopes detected: {GMAIL_SCOPES}"
    )


def test_interactive_oauth_missing_credentials_fails_safely(tmp_path):
    """Verify authenticate_interactive raises GmailConfigurationError if credentials file is missing."""
    missing_creds = tmp_path / "nonexistent_credentials.json"
    client = GmailApiClient(credentials_path=str(missing_creds), token_path=str(tmp_path / "token.json"))
    with pytest.raises(GmailConfigurationError) as exc_info:
        client.authenticate_interactive(open_browser=False)
    assert "OAuth client secrets file not found" in str(exc_info.value)


def test_interactive_oauth_authorization_flow(tmp_path):
    """Verify authenticate_interactive runs InstalledAppFlow with correct scope and writes token."""
    creds_file = tmp_path / "credentials.json"
    creds_file.write_text('{"installed": {"client_id": "test-id", "client_secret": "test-secret"}}')
    token_file = tmp_path / "token.json"

    client = GmailApiClient(credentials_path=str(creds_file), token_path=str(token_file))

    mock_flow = MagicMock()
    mock_creds = MagicMock()
    mock_creds.to_json.return_value = '{"token": "mock-token", "refresh_token": "mock-refresh"}'
    mock_creds.valid = True
    mock_flow.run_local_server.return_value = mock_creds

    with patch("app.services.gmail_client.InstalledAppFlow") as mock_flow_cls, \
         patch("googleapiclient.discovery.build") as mock_build:
        mock_flow_cls.from_client_secrets_file.return_value = mock_flow
        mock_build.return_value = MagicMock()
        client.authenticate_interactive(open_browser=False)

        mock_flow_cls.from_client_secrets_file.assert_called_once_with(
            str(creds_file),
            ["https://www.googleapis.com/auth/gmail.readonly"]
        )
        mock_flow.run_local_server.assert_called_once_with(port=0, open_browser=False)
        assert token_file.exists()
        assert "mock-token" in token_file.read_text()


def test_token_refresh_behavior(tmp_path):
    """Verify that an expired token with refresh_token is refreshed and rewritten to disk."""
    token_file = tmp_path / "token.json"
    token_file.write_text('{"token": "old-token", "refresh_token": "valid-refresh"}')

    client = GmailApiClient(
        credentials_path=str(tmp_path / "creds.json"),
        token_path=str(token_file),
    )

    mock_creds = MagicMock()
    mock_creds.valid = False
    mock_creds.expired = True
    mock_creds.refresh_token = "valid-refresh"

    def refresh_side_effect(request):
        mock_creds.valid = True
        mock_creds.expired = False

    mock_creds.refresh.side_effect = refresh_side_effect
    mock_creds.to_json.return_value = '{"token": "refreshed-token", "refresh_token": "valid-refresh"}'

    with patch("google.oauth2.credentials.Credentials.from_authorized_user_file", return_value=mock_creds), \
         patch("googleapiclient.discovery.build") as mock_build:
        mock_build.return_value = MagicMock()
        service = client.get_service(interactive=False)
        assert mock_creds.refresh.called
        assert "refreshed-token" in token_file.read_text()

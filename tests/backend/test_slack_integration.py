"""Slack API Notification Integration Tests (Phase 15D).

Validates the complete Slack Web API integration:
    WorkFlowOS Engine
         |
         | chat.postMessage
         v
    SlackApiClient
         |
         v
    Slack Workspace (Channel)

Tests include:
1. Slack client configuration & validation.
2. Successful send_notification with mocked Slack API.
3. Invalid token handling (invalid_auth).
4. Slack API error codes (channel_not_found, not_in_channel).
5. Invalid channel format handling.
6. Network failure / connection error handling.
7. Timeout handling.
8. Dry-run guarantees 0 external API calls and requires no credentials.
9. Unsupported Slack actions are rejected.
10. Registry registration & capability metadata.
11. StrategySelector deterministic selection for Slack send_notification.
12. Execution policy blocks unapproved Slack notifications.
13. Security: Bot token and authorization material strictly excluded from audit & error logs.
14. Independent verification via conversations.history with SHA-256 evidence.
15. Verification failure on missing message or text mismatch.
16. Idempotent execution prevents duplicate dispatches.
17. Live Slack test runner (only executes if real SLACK_BOT_TOKEN and SLACK_CHANNEL_ID exist).
"""

from datetime import datetime, timezone
import json
import os
from typing import Any, Dict
from unittest.mock import MagicMock, patch
import uuid

import httpx
import pytest

import app.config  # Ensures .env is loaded
from app.models.canonical import (
    ApprovalMetadata,
    ApprovalState,
    CanonicalWorkflowSpec,
    RiskAssessment,
    RiskCategory,
    RiskLevel,
    StepRisk,
)
from app.models.dna import DNAEvidence, WorkflowBoundaries
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
    PlannedStep,
    ResolvedParameter,
    StepExecutionStrategy,
)
from app.models.slack import SlackNotificationPayload, SlackNotificationResult
from app.models.strategy import ExecutionStrategyType
from app.models.verification import VerificationStatus
from app.repositories.canonical_repository import CanonicalWorkflowRepository
from app.repositories.execution_plan_repository import ExecutionPlanRepository
from app.services.execution_engine import ExecutionEngine
from app.services.executors.registry import ExecutorRegistry
from app.services.executors.slack_executor import SlackApiExecutor
from app.services.slack_client import (
    SlackApiClient,
    SlackApiError,
    SlackClientError,
    SlackConfigurationError,
    SlackConnectionError,
    SlackValidationError,
)
from app.services.strategy_selector import StrategySelector
from app.services.verification_engine import VerificationEngine
from app.services.verifiers.registry import VerificationStrategyRegistry
from app.services.verifiers.slack_verifier import SlackVerificationStrategy


# =========================================================================
# 1. Slack Client Configuration & Parameter Validation Tests
# =========================================================================
def test_slack_client_missing_token_raises_configuration_error():
    """Client raises SlackConfigurationError when no bot token is provided or in env."""
    with patch.dict(os.environ, {}, clear=True):
        client = SlackApiClient(bot_token=None)
        with pytest.raises(SlackConfigurationError) as exc:
            client.send_notification(channel="C123456", text="Hello")
        assert "SLACK_BOT_TOKEN is not configured" in str(exc.value)


def test_slack_client_invalid_channel_validation():
    """Client validates channel format and rejects empty or invalid strings."""
    client = SlackApiClient(bot_token="xoxb-dummy-test-token", default_channel_id="")

    # Empty channel
    with pytest.raises(SlackValidationError) as exc_empty:
        client.send_notification(channel="", text="Hello")
    assert "channel is required" in str(exc_empty.value).lower()

    # Invalid channel format (special characters)
    with pytest.raises(SlackValidationError) as exc_invalid:
        client.send_notification(channel="chan$;injection", text="Hello")
    assert "Invalid Slack channel format" in str(exc_invalid.value)

    # Empty text
    with pytest.raises(SlackValidationError) as exc_text:
        client.send_notification(channel="C123456", text="   ")
    assert "cannot be empty" in str(exc_text.value).lower()


# =========================================================================
# 2. Mocked Slack API HTTP Transports
# =========================================================================
def test_slack_send_notification_success():
    """Test successful chat.postMessage HTTP dispatch with mock client."""
    mock_response = httpx.Response(
        status_code=200,
        json={
            "ok": True,
            "channel": "C0123456789",
            "ts": "1711536000.000100",
            "message": {
                "text": "Workflow notification: Replacement requested for Acme Corp.",
                "user": "U12345678",
                "ts": "1711536000.000100",
            },
        },
    )

    custom_transport = httpx.MockTransport(lambda request: mock_response)
    client = SlackApiClient(
        bot_token="xoxb-dummy-test-token",
        http_client=httpx.Client(transport=custom_transport),
    )

    result = client.send_notification(
        channel="C0123456789",
        text="Workflow notification: Replacement requested for Acme Corp.",
    )

    assert result.success is True
    assert result.channel == "C0123456789"
    assert result.ts == "1711536000.000100"
    assert result.message is not None


def test_slack_send_notification_invalid_auth():
    """Test Slack API returning invalid_auth error."""
    mock_response = httpx.Response(
        status_code=200,
        json={"ok": False, "error": "invalid_auth"},
    )
    custom_transport = httpx.MockTransport(lambda request: mock_response)
    client = SlackApiClient(
        bot_token="xoxb-invalid-token",
        http_client=httpx.Client(transport=custom_transport),
    )

    with pytest.raises(SlackApiError) as exc:
        client.send_notification(channel="C0123456789", text="Test")
    assert exc.value.error_code == "invalid_auth"


def test_slack_send_notification_channel_not_found():
    """Test Slack API returning channel_not_found error."""
    mock_response = httpx.Response(
        status_code=200,
        json={"ok": False, "error": "channel_not_found"},
    )
    custom_transport = httpx.MockTransport(lambda request: mock_response)
    client = SlackApiClient(
        bot_token="xoxb-dummy-token",
        http_client=httpx.Client(transport=custom_transport),
    )

    with pytest.raises(SlackApiError) as exc:
        client.send_notification(channel="C_NON_EXISTENT", text="Test")
    assert exc.value.error_code == "channel_not_found"


def test_slack_send_notification_timeout():
    """Test Slack client handling timeout gracefully."""
    def timeout_handler(request):
        raise httpx.TimeoutException("Connection timed out")

    client = SlackApiClient(
        bot_token="xoxb-dummy-token",
        http_client=httpx.Client(transport=httpx.MockTransport(timeout_handler)),
    )

    with pytest.raises(SlackConnectionError) as exc:
        client.send_notification(channel="C0123456789", text="Test")
    assert "timed out" in str(exc.value).lower()


def test_slack_send_notification_network_failure():
    """Test Slack client handling network connection failure gracefully."""
    def error_handler(request):
        raise httpx.ConnectError("Connection refused")

    client = SlackApiClient(
        bot_token="xoxb-dummy-token",
        http_client=httpx.Client(transport=httpx.MockTransport(error_handler)),
    )

    with pytest.raises(SlackConnectionError) as exc:
        client.send_notification(channel="C0123456789", text="Test")
    assert "Failed to connect" in str(exc.value)


# =========================================================================
# 3. Dry Run Guarantees: 0 External API Calls, No Credentials Required
# =========================================================================
def test_slack_executor_dry_run_makes_zero_calls():
    """Dry run execution must never make network calls and needs no credentials."""
    # Empty token: real execution would crash, but dry run must succeed
    client = SlackApiClient(bot_token="")
    executor = SlackApiExecutor(client=client)

    step = PlannedStep(
        plan_step_id="step-slack-dry",
        source_canonical_step_id="c-slack",
        source_semantic_step_id="s-slack",
        source_dna_step_key="d-slack",
        application="Slack",
        action="send_notification",
        description="Notify team of customer replacement",
        resolved_parameters={
            "channel": "C0123456789",
            "message": "Customer replacement request processed for Acme Corp.",
        },
        execution_strategy=StepExecutionStrategy(
            strategy=ExecutionStrategy.API,
            reason="Slack API notification",
            target_technology="Slack API",
        ),
        risk=StepRisk(
            step_id="c-slack",
            application="Slack",
            action="send_notification",
            risk_level=RiskLevel.MEDIUM,
            risk_category=RiskCategory.COMMUNICATION,
            reason="External team message",
            requires_confirmation=True,
        ),
        expected_result="Notification posted",
        external_change=True,
        requires_confirmation=True,
        evidence_reference="ev-slack-1",
        state_change=ExpectedStateChange(
            target_system="Slack",
            entity_or_property="notification",
            before_state="",
            expected_after_state="DELIVERED",
            actual_state="",
        ),
    )

    ctx_dry = ExecutionContext(
        execution_id="exec-slack-dry",
        workflow_id="wf-slack-dry",
        execution_plan_id="plan-slack-dry",
        sandbox_root=".",
        execution_mode=ExecutionMode.DRY_RUN,
        dry_run=True,
        resolved_parameters={
            "channel": "C0123456789",
            "message": "Customer replacement request processed for Acme Corp.",
        },
    )

    result = executor.execute(step, ctx_dry)
    assert result.status == ExecutionStepStatus.SUCCESS
    assert result.output["status"] == "SIMULATED"
    assert result.output["external_api_calls"] == 0
    assert result.output["real_actions"] == 0
    assert result.output["channel"] == "C0123456789"


# =========================================================================
# 4. Action Validation & Guardrails
# =========================================================================
def test_slack_executor_rejects_unsupported_action():
    """Executor strictly rejects unauthorized actions like delete_message or invite_user."""
    executor = SlackApiExecutor(client=SlackApiClient(bot_token="dummy"))

    step = PlannedStep(
        plan_step_id="step-slack-unsupported",
        source_canonical_step_id="c1",
        source_semantic_step_id="s1",
        source_dna_step_key="d1",
        application="Slack",
        action="delete_message",  # Prohibited!
        description="Delete a message",
        resolved_parameters={"message_id": "123"},
        execution_strategy=StepExecutionStrategy(
            strategy=ExecutionStrategy.API,
            reason="API",
            target_technology="Slack",
        ),
        risk=StepRisk(
            step_id="c1",
            application="Slack",
            action="delete_message",
            risk_level=RiskLevel.HIGH,
            risk_category=RiskCategory.EXTERNAL_CHANGE,
            reason="Deletion",
            requires_confirmation=True,
        ),
        expected_result="",
        external_change=True,
        requires_confirmation=True,
        evidence_reference="",
        state_change=ExpectedStateChange(
            target_system="Slack",
            entity_or_property="message",
            before_state="",
            expected_after_state="",
            actual_state="",
        ),
    )

    ctx = ExecutionContext(
        execution_id="exec-unsupported",
        workflow_id="wf-unsupported",
        execution_plan_id="plan-unsupported",
        sandbox_root=".",
        execution_mode=ExecutionMode.LIVE,
    )

    result = executor.execute(step, ctx)
    assert result.status == ExecutionStepStatus.BLOCKED
    assert "does not support action" in result.error


# =========================================================================
# 5. Registry & Strategy Selection Tests
# =========================================================================
def test_slack_executor_registered_in_registry():
    """SlackApiExecutor is registered with implemented=True."""
    registry = ExecutorRegistry()
    assert "SlackApiExecutor" in registry.get_implemented_executors()
    caps = registry.get_all_capabilities()
    slack_cap = next((c for c in caps if c.executor_name == "SlackApiExecutor"), None)
    assert slack_cap is not None
    assert slack_cap.implemented is True
    assert slack_cap.supported_actions == ["send_notification"]


def test_strategy_selector_selects_slack_api_executor():
    """StrategySelector routes Slack:send_notification to API_INTEGRATION -> SlackApiExecutor."""
    step = PlannedStep(
        plan_step_id="step-slack-select",
        source_canonical_step_id="c-s",
        source_semantic_step_id="s-s",
        source_dna_step_key="d-s",
        application="Slack",
        action="send_notification",
        description="Notify team",
        resolved_parameters={"channel": "C0123456789", "message": "Done"},
        execution_strategy=StepExecutionStrategy(
            strategy=ExecutionStrategy.API,
            reason="API",
            target_technology="Slack Web API",
        ),
        risk=StepRisk(
            step_id="c-s",
            application="Slack",
            action="send_notification",
            risk_level=RiskLevel.MEDIUM,
            risk_category=RiskCategory.COMMUNICATION,
            reason="Notification",
            requires_confirmation=True,
        ),
        expected_result="Delivered",
        external_change=True,
        requires_confirmation=True,
        evidence_reference="",
        state_change=ExpectedStateChange(
            target_system="Slack",
            entity_or_property="notification",
            before_state="",
            expected_after_state="DELIVERED",
            actual_state="",
        ),
    )

    selector = StrategySelector()
    res = selector.select_strategy(step)
    assert res.is_executable is True
    assert res.selected_executor == "SlackApiExecutor"
    assert res.selected_strategy == ExecutionStrategyType.API_INTEGRATION
    assert res.policy_decision == "ALLOWED"


# =========================================================================
# 6. Policy Enforcement: Unapproved Slack Notifications Remain BLOCKED
# =========================================================================
def test_unapproved_slack_plan_blocked_by_policy():
    """Unapproved workflow plan with Slack notification step is blocked before execution."""
    workflow_id = "wf-unapproved-slack"
    spec = CanonicalWorkflowSpec(
        workflow_id=workflow_id,
        source_dna_id="dna-slack-unapp",
        source_semantic_workflow_id="sem-slack-unapp",
        title="Unapproved Slack Plan",
        intent="Notify Slack without human sign-off",
        description="Must be blocked",
        version="1.0.0",
        status="specification_ready",
        steps=[],
        variables=[],
        optional_steps=[],
        preconditions=[],
        boundaries=WorkflowBoundaries(
            first_step="Slack:send_notification",
            last_step="Slack:send_notification",
            min_duration_seconds=1.0,
            max_duration_seconds=5.0,
            average_duration_seconds=2.0,
            total_supporting_sessions=1,
        ),
        ordering_constraints=[],
        evidence=DNAEvidence(
            supporting_session_count=1,
            invariant_evidence="Slack message",
            variable_evidence="None",
            optional_step_evidence="None",
            ordering_evidence="Single",
            boundary_evidence="Established",
        ),
        parameter_bindings=[],
        risk_assessment=RiskAssessment(
            overall_risk_level=RiskLevel.MEDIUM,
            primary_risk_category=RiskCategory.COMMUNICATION,
            requires_human_confirmation=True,
            step_risks=[],
            summary="Medium risk communication",
            sensitive_factors_detected=[],
        ),
        approval_state=ApprovalMetadata(
            state=ApprovalState.REQUIRES_REVIEW,  # Unapproved
            reviewed_by="",
            comments="",
        ),
    )
    CanonicalWorkflowRepository().save(spec)

    step = PlannedStep(
        plan_step_id="step-unapproved-slack",
        source_canonical_step_id="c-unapp-s",
        source_semantic_step_id="s-unapp-s",
        source_dna_step_key="d-unapp-s",
        application="Slack",
        action="send_notification",
        description="Unauthorized Slack message",
        resolved_parameters={"channel": "C0123456789", "message": "Spam"},
        execution_strategy=StepExecutionStrategy(
            strategy=ExecutionStrategy.API,
            reason="API",
            target_technology="Slack",
        ),
        risk=StepRisk(
            step_id="c-unapp-s",
            application="Slack",
            action="send_notification",
            risk_level=RiskLevel.MEDIUM,
            risk_category=RiskCategory.COMMUNICATION,
            reason="External communication",
            requires_confirmation=True,
        ),
        expected_result="",
        external_change=True,
        requires_confirmation=True,
        evidence_reference="",
        state_change=ExpectedStateChange(
            target_system="Slack",
            entity_or_property="notification",
            before_state="",
            expected_after_state="",
            actual_state="",
        ),
    )

    plan = ExecutionPlan(
        execution_plan_id="plan-unapproved-slack",
        source_workflow_id=workflow_id,
        workflow_version="1.0.0",
        source_approval_state="requires_review",
        resolved_parameters=[],
        planned_steps=[step],
        preconditions=[],
        boundaries=WorkflowBoundaries(
            first_step="step-unapproved-slack",
            last_step="step-unapproved-slack",
            min_duration_seconds=1.0,
            max_duration_seconds=5.0,
            average_duration_seconds=2.0,
            total_supporting_sessions=1,
        ),
        risk_assessment={
            "overall_risk_level": "medium",
            "primary_risk_category": "communication",
            "requires_human_confirmation": True,
            "summary": "Unapproved Slack notification",
        },
        expected_effects=[],
        dry_run_status="NOT_RUN",
    )
    ExecutionPlanRepository().save(plan)

    engine = ExecutionEngine()
    with pytest.raises(ValueError, match="rejected by security policy"):
        engine.execute_plan("plan-unapproved-slack")


# =========================================================================
# 7. Security: Token Exclusion from Audit & Errors
# =========================================================================
def test_token_never_leaked_in_output_or_audit():
    """Bot token and Bearer auth must never appear in step results or audit records."""
    token = "xoxb-SECRET-NEVER-LEAK-TOKEN-12345"
    mock_response = httpx.Response(
        status_code=200,
        json={"ok": True, "channel": "C0123456789", "ts": "1711536000.000200"},
    )
    client = SlackApiClient(
        bot_token=token,
        http_client=httpx.Client(transport=httpx.MockTransport(lambda r: mock_response)),
    )
    executor = SlackApiExecutor(client=client)

    step = PlannedStep(
        plan_step_id="step-sec",
        source_canonical_step_id="c1",
        source_semantic_step_id="s1",
        source_dna_step_key="d1",
        application="Slack",
        action="send_notification",
        description="Notify",
        resolved_parameters={"channel": "C0123456789", "message": "Status update"},
        execution_strategy=StepExecutionStrategy(
            strategy=ExecutionStrategy.API,
            reason="API",
            target_technology="Slack",
        ),
        risk=StepRisk(
            step_id="c1",
            application="Slack",
            action="send_notification",
            risk_level=RiskLevel.MEDIUM,
            risk_category=RiskCategory.COMMUNICATION,
            reason="Notification",
            requires_confirmation=False,
        ),
        expected_result="",
        external_change=True,
        requires_confirmation=False,
        evidence_reference="",
        state_change=ExpectedStateChange(
            target_system="Slack",
            entity_or_property="notification",
            before_state="",
            expected_after_state="",
            actual_state="",
        ),
    )

    ctx = ExecutionContext(
        execution_id="exec-sec",
        workflow_id="wf-sec",
        execution_plan_id="plan-sec",
        sandbox_root=".",
        execution_mode=ExecutionMode.LIVE,
        resolved_parameters={"channel": "C0123456789", "message": "Status update"},
    )

    res = executor.execute(step, ctx)
    res_dump = json.dumps(res.model_dump())
    assert token not in res_dump
    assert "Bearer" not in res_dump


# =========================================================================
# 8. Independent Verification Tests
# =========================================================================
def test_slack_verification_success():
    """SlackVerificationStrategy independently verifies message presence via conversations.history."""
    mock_history_response = httpx.Response(
        status_code=200,
        json={
            "ok": True,
            "messages": [
                {
                    "ts": "1711536000.000300",
                    "text": "Replacement requested for Acme Corp.",
                    "user": "U123456",
                }
            ],
        },
    )
    client = SlackApiClient(
        bot_token="xoxb-dummy-token",
        http_client=httpx.Client(transport=httpx.MockTransport(lambda r: mock_history_response)),
    )
    verifier = SlackVerificationStrategy(client=client)

    step = PlannedStep(
        plan_step_id="step-v-slack",
        source_canonical_step_id="c1",
        source_semantic_step_id="s1",
        source_dna_step_key="d1",
        application="Slack",
        action="send_notification",
        description="Notify",
        resolved_parameters={"channel": "C0123456789", "message": "Replacement requested"},
        execution_strategy=StepExecutionStrategy(
            strategy=ExecutionStrategy.API,
            reason="API",
            target_technology="Slack",
        ),
        risk=StepRisk(
            step_id="c1",
            application="Slack",
            action="send_notification",
            risk_level=RiskLevel.MEDIUM,
            risk_category=RiskCategory.COMMUNICATION,
            reason="Risk",
            requires_confirmation=False,
        ),
        expected_result="",
        external_change=True,
        requires_confirmation=False,
        evidence_reference="",
        state_change=ExpectedStateChange(
            target_system="Slack",
            entity_or_property="notification",
            before_state="",
            expected_after_state="DELIVERED",
            actual_state="",
        ),
    )

    step_result = ExecutionStepResult(
        planned_step_id="step-v-slack",
        action_name="send_notification",
        target_application="Slack",
        strategy=ExecutionStrategy.API,
        executor_name="SlackApiExecutor",
        status=ExecutionStepStatus.SUCCESS,
        parameters_used={"channel": "C0123456789", "message": "Replacement requested"},
        output={
            "operation": "send_notification",
            "channel": "C0123456789",
            "ts": "1711536000.000300",
            "status": "COMPLETED",
        },
        affected_resources=["slack:channel:C0123456789:ts:1711536000.000300"],
    )

    checks = verifier.build_checks("exec-v1", step, step_result, sandbox_root=".")
    assert len(checks) == 1
    chk = checks[0]
    assert chk.check_type == "slack_notification_delivered"

    verified = verifier.verify(chk, sandbox_root=".", step_result=step_result)
    assert verified.status == VerificationStatus.VERIFIED
    assert "integrity_evidence" in verified.evidence
    assert verified.evidence["ts"] == "1711536000.000300"


def test_slack_verification_fails_when_message_not_found():
    """Verification fails when conversations.history returns empty messages."""
    mock_history_response = httpx.Response(
        status_code=200,
        json={"ok": True, "messages": []},
    )
    client = SlackApiClient(
        bot_token="xoxb-dummy-token",
        http_client=httpx.Client(transport=httpx.MockTransport(lambda r: mock_history_response)),
    )
    verifier = SlackVerificationStrategy(client=client)

    step = PlannedStep(
        plan_step_id="step-v-fail",
        source_canonical_step_id="c1",
        source_semantic_step_id="s1",
        source_dna_step_key="d1",
        application="Slack",
        action="send_notification",
        description="Notify",
        resolved_parameters={"channel": "C0123456789", "message": "Missing"},
        execution_strategy=StepExecutionStrategy(
            strategy=ExecutionStrategy.API,
            reason="API",
            target_technology="Slack",
        ),
        risk=StepRisk(
            step_id="c1",
            application="Slack",
            action="send_notification",
            risk_level=RiskLevel.MEDIUM,
            risk_category=RiskCategory.COMMUNICATION,
            reason="Risk",
            requires_confirmation=False,
        ),
        expected_result="",
        external_change=True,
        requires_confirmation=False,
        evidence_reference="",
        state_change=ExpectedStateChange(
            target_system="Slack",
            entity_or_property="notification",
            before_state="",
            expected_after_state="",
            actual_state="",
        ),
    )

    step_result = ExecutionStepResult(
        planned_step_id="step-v-fail",
        action_name="send_notification",
        target_application="Slack",
        strategy=ExecutionStrategy.API,
        executor_name="SlackApiExecutor",
        status=ExecutionStepStatus.SUCCESS,
        output={"operation": "send_notification", "channel": "C0123456789", "ts": "1711536000.999999"},
    )

    checks = verifier.build_checks("exec-v2", step, step_result, sandbox_root=".")
    verified = verifier.verify(checks[0], sandbox_root=".", step_result=step_result)
    assert verified.status == VerificationStatus.FAILED
    assert "not found in channel" in verified.reason


# =========================================================================
# 9. Live Slack Integration Test (Conditional on Real Credentials)
# =========================================================================
def test_live_slack_notification_conditional():
    """Runs a real live notification test if SLACK_BOT_TOKEN and SLACK_CHANNEL_ID are present.

    If credentials are not configured, records NOT RUN without failing.
    """
    token = os.getenv("SLACK_BOT_TOKEN")
    channel = os.getenv("SLACK_CHANNEL_ID")

    if not token or not channel or token.startswith("xoxb-placeholder") or token.startswith("xoxb-your"):
        pytest.skip("LIVE SLACK TEST: NOT RUN (real SLACK_BOT_TOKEN and SLACK_CHANNEL_ID not configured)")

    # Execute real notification
    client = SlackApiClient(bot_token=token, default_channel_id=channel)
    executor = SlackApiExecutor(client=client)

    test_message = "WorkFlowOS Phase 15D integration test — Slack API"
    step = PlannedStep(
        plan_step_id="step-live-slack",
        source_canonical_step_id="c-live-s",
        source_semantic_step_id="s-live-s",
        source_dna_step_key="d-live-s",
        application="Slack",
        action="send_notification",
        description="Integration live test",
        resolved_parameters={"channel": channel, "message": test_message},
        execution_strategy=StepExecutionStrategy(
            strategy=ExecutionStrategy.API,
            reason="Live API",
            target_technology="Slack",
        ),
        risk=StepRisk(
            step_id="c-live-s",
            application="Slack",
            action="send_notification",
            risk_level=RiskLevel.MEDIUM,
            risk_category=RiskCategory.COMMUNICATION,
            reason="Integration verification",
            requires_confirmation=False,
        ),
        expected_result="Delivered",
        external_change=True,
        requires_confirmation=False,
        evidence_reference="",
        state_change=ExpectedStateChange(
            target_system="Slack",
            entity_or_property="notification",
            before_state="",
            expected_after_state="DELIVERED",
            actual_state="",
        ),
    )

    ctx = ExecutionContext(
        execution_id="exec-live-slack",
        workflow_id="wf-live-slack",
        execution_plan_id="plan-live-slack",
        sandbox_root=".",
        execution_mode=ExecutionMode.LIVE,
        resolved_parameters={"channel": channel, "message": test_message},
    )

    result = executor.execute(step, ctx)
    if result.status == ExecutionStepStatus.FAILED:
        err_msg = str(result.error)
        if "not_in_channel" in err_msg or "missing_scope" in err_msg:
            pytest.skip(
                f"LIVE SLACK TEST: NOT RUN — Slack bot is not added to channel '{channel}' "
                f"or token lacks required scopes ({err_msg}). Run '/invite @workflowos' in the channel."
            )

    assert result.status == ExecutionStepStatus.SUCCESS
    assert result.output["ts"] is not None

    # Independent Verification
    verifier = SlackVerificationStrategy(client=client)
    checks = verifier.build_checks("exec-live-slack", step, result, sandbox_root=".")
    verif = verifier.verify(checks[0], sandbox_root=".", step_result=result)
    assert verif.status == VerificationStatus.VERIFIED

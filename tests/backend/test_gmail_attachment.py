"""Unit, Security, and Verification Tests for Gmail Attachment Download (Phase 15A).

Covers all 15 required verification targets:
1. attachment download success
2. Gmail API failure
3. missing message
4. missing attachment
5. malformed attachment data
6. invalid filename
7. path traversal attempt
8. absolute path attempt
9. destination confinement
10. dry-run never calls Gmail
11. audit excludes credentials
12. verification success
13. verification failure when artifact missing
14. SHA-256 evidence
15. unsupported Gmail mutation remains blocked
"""

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Dict
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
from app.models.strategy import ExecutionStrategyType
from app.models.verification import VerificationStatus
from app.repositories.canonical_repository import CanonicalWorkflowRepository
from app.repositories.execution_plan_repository import ExecutionPlanRepository
from app.repositories.execution_repository import ExecutionRepository
from app.services.dry_run_simulator import DryRunSimulator
from app.services.execution_engine import ExecutionEngine
from app.services.executors.gmail_executor import GmailApiExecutor
from app.services.executors.registry import ExecutorRegistry
from app.services.gmail_client import (
    GmailApiClient,
    GmailApiError,
    GmailAuthenticationError,
    GmailConfigurationError,
)
from app.services.strategy_selector import StrategySelector
from app.services.verification_engine import VerificationEngine
from app.services.verifiers.gmail_verifier import GmailVerificationStrategy


@pytest.fixture
def mock_gmail_client_attachment():
    """Provides a mocked GmailApiClient configured for attachment download tests."""
    client = MagicMock(spec=GmailApiClient)
    client.is_configured.return_value = True
    client.is_authenticated.return_value = True

    dummy_bytes = b"Invoice #INV-2026-999 PDF Content Data Bytes"
    meta = {
        "message_id": "msg-att-001",
        "attachment_id": "att-id-001",
        "filename": "invoice_999.pdf",
        "mime_type": "application/pdf",
        "size_bytes": len(dummy_bytes),
    }
    client.download_attachment.return_value = (dummy_bytes, meta)
    client.get_message_attachments.return_value = [meta]
    client.get_attachment_data.return_value = dummy_bytes
    return client


@pytest.fixture
def sample_attachment_step():
    """Creates a deterministic PlannedStep for download_attachment on Gmail."""
    return PlannedStep(
        plan_step_id="step-gmail-download-1",
        source_canonical_step_id="can-att-1",
        source_semantic_step_id="sem-att-1",
        source_dna_step_key="dna-att-1",
        application="Gmail",
        action="download_attachment",
        description="Download invoice attachment from customer email",
        resolved_parameters={
            "message_id": "msg-att-001",
            "attachment_id": "att-id-001",
            "filename": "invoice_999.pdf",
        },
        execution_strategy=StepExecutionStrategy(
            strategy=ExecutionStrategy.API,
            reason="Gmail read-only attachment download",
            target_technology="Google Gmail API",
        ),
        risk=StepRisk(
            step_id="can-att-1",
            application="Gmail",
            action="download_attachment",
            risk_level=RiskLevel.LOW,
            risk_category=RiskCategory.READ_ONLY,
            reason="Read-only attachment retrieval into sandbox",
            requires_confirmation=False,
        ),
        expected_result="Attachment downloaded into controlled sandbox",
        external_change=False,
        requires_confirmation=False,
        evidence_reference="ev-att-1",
        state_change=ExpectedStateChange(
            target_system="LocalSandbox",
            entity_or_property="downloaded_file",
            before_state="None",
            expected_after_state="File saved in sandbox",
            actual_state="UNTOUCHED",
        ),
    )


@pytest.fixture
def sample_approved_attachment_plan(sample_attachment_step):
    """Creates an approved workflow spec and execution plan for attachment testing."""
    workflow_id = "wf-gmail-att-approved"
    spec = CanonicalWorkflowSpec(
        workflow_id=workflow_id,
        source_dna_id="dna-att-001",
        source_semantic_workflow_id="sem-att-001",
        title="Download Invoice Workflow",
        intent="Download customer attachment",
        description="Workflow to download invoice attachment from Gmail",
        version="1.0.0",
        status="specification_ready",
        steps=[],
        variables=[],
        optional_steps=[],
        preconditions=["Gmail API configured"],
        boundaries=WorkflowBoundaries(
            first_step="Gmail:download_attachment",
            last_step="Gmail:download_attachment",
            min_duration_seconds=1.0,
            max_duration_seconds=5.0,
            average_duration_seconds=2.0,
            total_supporting_sessions=1,
        ),
        ordering_constraints=[],
        evidence=DNAEvidence(
            supporting_session_count=1,
            invariant_evidence="Attachment download observed",
            variable_evidence="Message ID parameter",
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
            summary="Low risk read-only attachment download",
            sensitive_factors_detected=[],
        ),
        approval_state=ApprovalMetadata(
            state=ApprovalState.APPROVED,
            reviewed_by="admin-user",
            comments="Approved for attachment download",
        ),
    )
    CanonicalWorkflowRepository().save(spec)

    plan = ExecutionPlan(
        execution_plan_id="plan-gmail-att-test",
        source_workflow_id=workflow_id,
        workflow_version="1.0.0",
        source_approval_state="approved",
        resolved_parameters=[
            ResolvedParameter(
                semantic_name="message_id",
                source_parameter="message_id",
                source_field="parameters.message_id",
                inferred_type="string",
                is_required=True,
                runtime_value="msg-att-001",
                resolution_status="resolved",
            ),
            ResolvedParameter(
                semantic_name="filename",
                source_parameter="filename",
                source_field="parameters.filename",
                inferred_type="string",
                is_required=False,
                runtime_value="invoice_999.pdf",
                resolution_status="resolved",
            ),
        ],
        planned_steps=[sample_attachment_step],
        preconditions=[],
        boundaries=WorkflowBoundaries(
            first_step="step-gmail-download-1",
            last_step="step-gmail-download-1",
            min_duration_seconds=1.0,
            max_duration_seconds=5.0,
            average_duration_seconds=2.0,
            total_supporting_sessions=1,
        ),
        risk_assessment={
            "overall_risk_level": "low",
            "primary_risk_category": "read_only",
            "requires_human_confirmation": False,
            "summary": "Low risk attachment download",
        },
        expected_effects=[],
        dry_run_status="SIMULATED",
    )
    ExecutionPlanRepository().save(plan)
    return plan


# =========================================================================
# 1. Attachment download success
# =========================================================================
def test_1_attachment_download_success(mock_gmail_client_attachment, sample_attachment_step, tmp_path):
    """1. Test successful attachment download saves file to sandbox with correct metadata and SHA-256."""
    executor = GmailApiExecutor(client=mock_gmail_client_attachment)
    ctx = ExecutionContext(
        execution_id="exec-att-1",
        workflow_id="wf-1",
        execution_plan_id="p-1",
        resolved_parameters={
            "message_id": "msg-att-001",
            "attachment_id": "att-id-001",
            "filename": "invoice_999.pdf",
        },
        sandbox_root=str(tmp_path),
    )

    res = executor.execute(sample_attachment_step, ctx)
    assert res.status == ExecutionStepStatus.SUCCESS
    assert res.output["operation"] == "download_attachment"
    assert res.output["message_id"] == "msg-att-001"
    assert res.output["attachment_id"] == "att-id-001"
    assert res.output["filename"] == "invoice_999.pdf"
    assert res.output["mime_type"] == "application/pdf"
    assert res.output["size_bytes"] > 0
    assert "saved_path" in res.output

    saved_file = Path(res.output["saved_path"])
    assert saved_file.exists()
    assert saved_file.is_file()

    # Check content and SHA-256 match
    content = saved_file.read_bytes()
    expected_hash = hashlib.sha256(content).hexdigest()
    assert res.output["sha256"] == expected_hash
    assert len(res.affected_resources) == 1
    assert res.affected_resources[0] == str(saved_file)


# =========================================================================
# 2. Gmail API failure
# =========================================================================
def test_2_gmail_api_failure(sample_attachment_step, tmp_path):
    """2. Test handling of Gmail API network or service failure."""
    client = MagicMock(spec=GmailApiClient)
    client.is_configured.return_value = True
    client.is_authenticated.return_value = True
    client.download_attachment.side_effect = GmailApiError("Gmail API 503 Backend Service Unavailable")

    executor = GmailApiExecutor(client=client)
    ctx = ExecutionContext(
        execution_id="exec-att-2",
        workflow_id="wf-1",
        execution_plan_id="p-1",
        resolved_parameters={"message_id": "msg-att-001"},
        sandbox_root=str(tmp_path),
    )

    res = executor.execute(sample_attachment_step, ctx)
    assert res.status == ExecutionStepStatus.FAILED
    assert "Backend Service Unavailable" in (res.error or "")


# =========================================================================
# 3. Missing message
# =========================================================================
def test_3_missing_message(sample_attachment_step, tmp_path):
    """3. Test missing message_id parameter fails closed with INVALID_PARAMETER."""
    client = MagicMock(spec=GmailApiClient)
    client.is_configured.return_value = True
    client.is_authenticated.return_value = True

    executor = GmailApiExecutor(client=client)
    ctx = ExecutionContext(
        execution_id="exec-att-3",
        workflow_id="wf-1",
        execution_plan_id="p-1",
        resolved_parameters={},  # Missing message_id
        sandbox_root=str(tmp_path),
    )

    res = executor.execute(sample_attachment_step, ctx)
    assert res.status == ExecutionStepStatus.BLOCKED
    assert res.blocked_reason == "INVALID_PARAMETER"
    assert "message_id" in (res.error or "")
    client.download_attachment.assert_not_called()


# =========================================================================
# 4. Missing attachment
# =========================================================================
def test_4_missing_attachment(sample_attachment_step, tmp_path):
    """4. Test error handling when requested attachment does not exist in message."""
    client = MagicMock(spec=GmailApiClient)
    client.is_configured.return_value = True
    client.is_authenticated.return_value = True
    client.download_attachment.side_effect = GmailApiError("No attachment matching filename='contract.pdf' found in message 'msg-001'")

    executor = GmailApiExecutor(client=client)
    ctx = ExecutionContext(
        execution_id="exec-att-4",
        workflow_id="wf-1",
        execution_plan_id="p-1",
        resolved_parameters={"message_id": "msg-001", "filename": "contract.pdf"},
        sandbox_root=str(tmp_path),
    )

    res = executor.execute(sample_attachment_step, ctx)
    assert res.status == ExecutionStepStatus.FAILED
    assert "No attachment matching" in (res.error or "")


# =========================================================================
# 5. Malformed attachment data
# =========================================================================
def test_5_malformed_attachment_data(sample_attachment_step, tmp_path):
    """5. Test handling of malformed base64 attachment data."""
    client = MagicMock(spec=GmailApiClient)
    client.is_configured.return_value = True
    client.is_authenticated.return_value = True
    client.download_attachment.side_effect = GmailApiError("Failed to decode base64 attachment data: Incorrect padding")

    executor = GmailApiExecutor(client=client)
    ctx = ExecutionContext(
        execution_id="exec-att-5",
        workflow_id="wf-1",
        execution_plan_id="p-1",
        resolved_parameters={"message_id": "msg-001", "attachment_id": "att-bad"},
        sandbox_root=str(tmp_path),
    )

    res = executor.execute(sample_attachment_step, ctx)
    assert res.status == ExecutionStepStatus.FAILED
    assert "Failed to decode base64" in (res.error or "")


# =========================================================================
# 6. Invalid filename
# =========================================================================
def test_6_invalid_filename(sample_attachment_step, tmp_path):
    """6. Test safe filename sanitization eliminates dangerous directory traversal."""
    client = MagicMock(spec=GmailApiClient)
    client.is_configured.return_value = True
    client.is_authenticated.return_value = True
    client.download_attachment.return_value = (
        b"data",
        {"message_id": "m1", "attachment_id": "a1", "filename": "unsafe/name.pdf", "size_bytes": 4},
    )

    executor = GmailApiExecutor(client=client)
    # Filename with leading path components sanitized
    safe_name = executor._sanitize_filename("../../etc/passwd")
    assert safe_name == "passwd"
    assert ".." not in safe_name
    assert "/" not in safe_name


# =========================================================================
# 7. Path traversal attempt
# =========================================================================
def test_7_path_traversal_attempt(sample_attachment_step, tmp_path):
    """7. Test explicit path traversal attempt is strictly blocked as SECURITY_VIOLATION."""
    client = MagicMock(spec=GmailApiClient)
    client.is_configured.return_value = True
    client.is_authenticated.return_value = True

    executor = GmailApiExecutor(client=client)
    ctx = ExecutionContext(
        execution_id="exec-att-7",
        workflow_id="wf-1",
        execution_plan_id="p-1",
        resolved_parameters={
            "message_id": "msg-001",
            "target_path": "../../evil_escape.sh",
        },
        sandbox_root=str(tmp_path),
    )

    res = executor.execute(sample_attachment_step, ctx)
    assert res.status == ExecutionStepStatus.BLOCKED
    assert res.blocked_reason == "SECURITY_VIOLATION"
    assert "Path traversal rejected" in (res.error or "")
    client.download_attachment.assert_not_called()


# =========================================================================
# 8. Absolute path attempt
# =========================================================================
def test_8_absolute_path_attempt(sample_attachment_step, tmp_path):
    """8. Test absolute path injection outside sandbox is strictly blocked."""
    client = MagicMock(spec=GmailApiClient)
    client.is_configured.return_value = True
    client.is_authenticated.return_value = True

    outside_dir = tempfile.mkdtemp()
    abs_target = os.path.join(outside_dir, "injected.exe")

    executor = GmailApiExecutor(client=client)
    ctx = ExecutionContext(
        execution_id="exec-att-8",
        workflow_id="wf-1",
        execution_plan_id="p-1",
        resolved_parameters={
            "message_id": "msg-001",
            "target_path": abs_target,
        },
        sandbox_root=str(tmp_path),
    )

    res = executor.execute(sample_attachment_step, ctx)
    assert res.status == ExecutionStepStatus.BLOCKED
    assert res.blocked_reason == "SECURITY_VIOLATION"
    assert "Absolute path injection rejected" in (res.error or "")
    client.download_attachment.assert_not_called()


# =========================================================================
# 9. Destination confinement
# =========================================================================
def test_9_destination_confinement(mock_gmail_client_attachment, sample_attachment_step, tmp_path):
    """9. Test that destination paths are strictly confined within the configured sandbox root."""
    executor = GmailApiExecutor(client=mock_gmail_client_attachment)
    ctx = ExecutionContext(
        execution_id="exec-att-9",
        workflow_id="wf-1",
        execution_plan_id="p-1",
        resolved_parameters={
            "message_id": "msg-att-001",
            "filename": "document.pdf",
        },
        sandbox_root=str(tmp_path),
    )

    res = executor.execute(sample_attachment_step, ctx)
    assert res.status == ExecutionStepStatus.SUCCESS
    saved_path = Path(res.output["saved_path"]).resolve()
    sandbox_path = Path(tmp_path).resolve()

    # Must be relative to sandbox (i.e. contained strictly inside)
    assert saved_path.is_relative_to(sandbox_path)
    assert saved_path.exists()


# =========================================================================
# 10. Dry-run never calls Gmail
# =========================================================================
def test_10_dry_run_never_calls_gmail(mock_gmail_client_attachment, sample_approved_attachment_plan, sample_attachment_step, tmp_path):
    """10. Test dry-run simulator and executor never invoke the Gmail API."""
    # Simulator verification
    sim = DryRunSimulator()
    result = sim.simulate(sample_approved_attachment_plan)
    assert result.overall_simulation_status == "SIMULATED"
    assert result.real_actions_performed == 0
    mock_gmail_client_attachment.download_attachment.assert_not_called()

    # Executor direct dry-run verification
    executor = GmailApiExecutor(client=mock_gmail_client_attachment)
    ctx = ExecutionContext(
        execution_id="exec-att-dry",
        workflow_id="wf-dry",
        execution_plan_id="p-dry",
        resolved_parameters={"message_id": "msg-att-001", "filename": "dry_test.pdf"},
        sandbox_root=str(tmp_path),
        dry_run=True,
    )
    res = executor.execute(sample_attachment_step, ctx)
    assert res.status == ExecutionStepStatus.SUCCESS
    assert res.output["status"] == "SIMULATED"
    assert "Simulated attachment download" in res.selection_reason
    mock_gmail_client_attachment.download_attachment.assert_not_called()



# =========================================================================
# 11. Audit excludes credentials
# =========================================================================
def test_11_audit_excludes_credentials(mock_gmail_client_attachment, sample_approved_attachment_plan):
    """11. Test that audit records never store access tokens, refresh tokens, or client secrets."""
    reg = ExecutorRegistry()
    reg.register(GmailApiExecutor(client=mock_gmail_client_attachment))
    engine = ExecutionEngine(registry=reg)

    audit = engine.execute_plan(sample_approved_attachment_plan.execution_plan_id)
    assert audit.status == ExecutionOverallStatus.COMPLETED
    audit_json = audit.model_dump_json().lower()

    for forbidden in ["client_secret", "access_token", "refresh_token", "bearer", "authorization"]:
        assert forbidden not in audit_json, f"Forbidden credential token '{forbidden}' detected in audit!"


# =========================================================================
# 12. Verification success
# =========================================================================
def test_12_verification_success(mock_gmail_client_attachment, sample_approved_attachment_plan):
    """12. Test verification passes when downloaded attachment exists with valid SHA-256 evidence."""
    reg = ExecutorRegistry()
    reg.register(GmailApiExecutor(client=mock_gmail_client_attachment))
    engine = ExecutionEngine(registry=reg)

    audit = engine.execute_plan(sample_approved_attachment_plan.execution_plan_id)
    verif = VerificationEngine()
    verif_res = verif.verify_execution(audit.execution_id, force_recheck=True)

    assert verif_res.overall_status == VerificationStatus.VERIFIED
    assert verif_res.verified_count >= 1
    chk = verif_res.checks[0]
    assert chk.status == VerificationStatus.VERIFIED
    assert chk.check_type == "gmail_attachment_downloaded"
    assert "cryptographic integrity evidence using SHA-256" in chk.evidence["integrity_evidence"]


# =========================================================================
# 13. Verification failure when artifact missing
# =========================================================================
def test_13_verification_failure_when_artifact_missing(mock_gmail_client_attachment, sample_approved_attachment_plan):
    """13. Test verification fails if the attachment file is missing, even though executor reported SUCCESS."""
    reg = ExecutorRegistry()
    reg.register(GmailApiExecutor(client=mock_gmail_client_attachment))
    engine = ExecutionEngine(registry=reg)

    audit = engine.execute_plan(sample_approved_attachment_plan.execution_plan_id)
    step_res = audit.step_results[0]
    assert step_res.status == ExecutionStepStatus.SUCCESS

    # Simulate artifact deletion / loss before verification
    saved_file = Path(step_res.output["saved_path"])
    if saved_file.exists():
        saved_file.unlink()

    verif = VerificationEngine()
    verif_res = verif.verify_execution(audit.execution_id, force_recheck=True)

    assert verif_res.overall_status == VerificationStatus.FAILED
    assert verif_res.failed_count >= 1
    chk = verif_res.checks[0]
    assert chk.status == VerificationStatus.FAILED
    assert "not found" in chk.reason


# =========================================================================
# 14. SHA-256 evidence
# =========================================================================
def test_14_sha256_evidence(mock_gmail_client_attachment, sample_approved_attachment_plan):
    """14. Test cryptographic integrity evidence using SHA-256 detects tampering."""
    reg = ExecutorRegistry()
    reg.register(GmailApiExecutor(client=mock_gmail_client_attachment))
    engine = ExecutionEngine(registry=reg)

    audit = engine.execute_plan(sample_approved_attachment_plan.execution_plan_id)
    step_res = audit.step_results[0]
    saved_file = Path(step_res.output["saved_path"])

    # Tamper with file content after execution
    saved_file.write_bytes(b"TAMPERED FILE CONTENT MODIFICATION")

    verif = VerificationEngine()
    verif_res = verif.verify_execution(audit.execution_id, force_recheck=True)

    assert verif_res.overall_status == VerificationStatus.FAILED
    chk = verif_res.checks[0]
    assert chk.status == VerificationStatus.FAILED
    assert "SHA-256 mismatch" in chk.reason


# =========================================================================
# 15. Unsupported Gmail mutation remains blocked
# =========================================================================
def test_15_unsupported_gmail_mutation_remains_blocked(tmp_path):
    """15. Test Gmail mutations (send, delete, modify, label) are strictly blocked."""
    executor = GmailApiExecutor()
    ctx = ExecutionContext(
        execution_id="exec-mut",
        workflow_id="wf-1",
        execution_plan_id="p-1",
        resolved_parameters={},
        sandbox_root=str(tmp_path),
    )

    for forbidden_action in ["send_email", "delete_email", "modify_email", "mark_as_read", "add_label"]:
        step = PlannedStep(
            plan_step_id=f"step-{forbidden_action}",
            source_canonical_step_id="c1",
            source_semantic_step_id="s1",
            source_dna_step_key="d1",
            application="Gmail",
            action=forbidden_action,
            description="Mutation attempt",
            resolved_parameters={},
            execution_strategy=StepExecutionStrategy(
                strategy=ExecutionStrategy.API,
                reason="Forbidden",
                target_technology="Gmail API",
            ),
            risk=StepRisk(
                step_id="c1",
                application="Gmail",
                action=forbidden_action,
                risk_level=RiskLevel.HIGH,
                risk_category=RiskCategory.EXTERNAL_CHANGE,
                reason="Forbidden mutation",
                requires_confirmation=True,
            ),
            expected_result="Blocked",
            external_change=True,
            requires_confirmation=True,
            evidence_reference="",
            state_change=ExpectedStateChange(
                target_system="Gmail",
                entity_or_property="email",
                before_state="",
                expected_after_state="",
                actual_state="",
            ),
        )

        # Validation must reject
        valid, errors = executor.validate(step, ctx)
        assert not valid
        assert "only supports" in errors[0]

        # Execution must return BLOCKED with UNSUPPORTED_ACTION
        res = executor.execute(step, ctx)
        assert res.status == ExecutionStepStatus.BLOCKED
        assert res.blocked_reason == "UNSUPPORTED_ACTION"

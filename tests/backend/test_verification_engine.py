"""Tests for Phase 9: Post-Execution Verification and Evidence Engine.

Covers:
1. Verification model creation
2. File existence verification
3. Missing file verification
4. Directory verification
5. Non-empty file verification
6. JSON structured field verification
7. Evidence generation (sha256, size, path, timestamp)
8. Executor SUCCESS + Verification VERIFIED
9. Executor SUCCESS + Verification FAILED
10. Executor SUCCESS + Verification UNKNOWN
11. Workflow-level status aggregation
12. Optional-step handling using existing semantics
13. Sandbox boundary enforcement
14. Arbitrary path rejection
15. External verification rejection
16. Verification persistence across database reload
17. Repeated verification behavior (idempotency vs force_recheck)
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import pytest

from app.models.canonical import (
    ApprovalMetadata,
    ApprovalState,
    CanonicalStep,
    CanonicalWorkflowSpec,
    RiskAssessment,
    RiskCategory,
    RiskLevel,
    StepRisk,
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
    PreconditionCheck,
    PreconditionStatus,
    ResolvedParameter,
    StepExecutionStrategy,
)
from app.models.verification import (
    VerificationCheck,
    VerificationResult,
    VerificationStatus,
    VerificationStrategyType,
)
from app.repositories.canonical_repository import CanonicalWorkflowRepository
from app.repositories.execution_plan_repository import ExecutionPlanRepository
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.verification_repository import VerificationRepository
from app.services.execution_engine import ExecutionEngine
from app.services.verification_engine import VerificationEngine
from app.services.verifiers.file_system import FileSystemVerificationStrategy
from app.services.verifiers.structured_output import StructuredOutputVerificationStrategy


@pytest.fixture
def temp_sandbox_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_approved_plan():
    """Constructs a deterministic approved ExecutionPlan for verification tests."""
    wf_id = f"wf-test-verif-{datetime.now(timezone.utc).timestamp()}"
    plan_id = f"plan-verif-{datetime.now(timezone.utc).timestamp()}"

    spec = CanonicalWorkflowSpec(
        workflow_id=wf_id,
        source_dna_id="dna-verif-001",
        source_semantic_workflow_id="sem-verif-001",
        title="Customer Replacement Workflow",
        intent="Generate customer replacement summary",
        description="Write customer replacement summary to sandbox",
        version="1.0.0",
        status="specification_ready",
        steps=[],
        variables=[],
        optional_steps=[],
        preconditions=["Sandbox folder ready"],
        boundaries=WorkflowBoundaries(
            first_step="File System:save_file",
            last_step="File System:save_file",
            min_duration_seconds=1.0,
            max_duration_seconds=10.0,
            average_duration_seconds=5.0,
            total_supporting_sessions=2,
        ),
        ordering_constraints=[],
        evidence=DNAEvidence(
            supporting_session_count=2,
            invariant_evidence="Local step",
            variable_evidence="filename",
            optional_step_evidence="None",
            ordering_evidence="Sequential",
            boundary_evidence="Boundaries established",
        ),
        parameter_bindings=[],
        risk_assessment=RiskAssessment(
            overall_risk_level=RiskLevel.LOW,
            primary_risk_category=RiskCategory.LOCAL_CHANGE,
            requires_human_confirmation=False,
            step_risks=[],
            summary="Low risk local workflow",
            sensitive_factors_detected=[],
        ),
        approval_state=ApprovalMetadata(
            state=ApprovalState.APPROVED,
            reviewed_by="admin@workflowos.local",
            comments="Approved for verification testing",
        ),
    )

    planned_step = PlannedStep(
        plan_step_id="pstep-1",
        source_canonical_step_id="can-step-1",
        source_semantic_step_id="sem-step-1",
        source_dna_step_key="dna-step-1",
        application="File System",
        action="save_file",
        description="Save customer summary in sandbox",
        resolved_parameters={"file_name": "customer_summary.json"},
        execution_strategy=StepExecutionStrategy(
            strategy=ExecutionStrategy.APPLICATION_INTEGRATION,
            reason="Local file persistence",
            target_technology="Local OS File System API",
        ),
        risk=StepRisk(
            step_id="can-step-1",
            application="File System",
            action="save_file",
            risk_level=RiskLevel.LOW,
            risk_category=RiskCategory.LOCAL_CHANGE,
            reason="Sandbox file write",
            requires_confirmation=False,
        ),
        expected_result="Summary file written",
        external_change=False,
        requires_confirmation=False,
        evidence_reference="evidence-1",
        state_change=ExpectedStateChange(
            target_system="File System",
            entity_or_property="customer_summary.json",
            before_state="Does not exist",
            expected_after_state="customer_summary.json exists",
            actual_state="UNTOUCHED",
        ),
    )

    plan = ExecutionPlan(
        execution_plan_id=plan_id,
        source_workflow_id=wf_id,
        workflow_version="1.0.0",
        source_approval_state="approved",
        resolved_parameters=[
            ResolvedParameter(
                source_parameter="file_param_1",
                semantic_name="file_name",
                source_field="metadata.file_name",
                inferred_type="filename",
                runtime_value="customer_summary.json",
                resolution_status=ParameterResolutionStatus.RESOLVED,
                is_required=True,
            )
        ],
        planned_steps=[planned_step],
        preconditions=[
            PreconditionCheck(
                condition="sandbox_ready",
                status=PreconditionStatus.SATISFIED,
                evaluation_reason="Ready",
            )
        ],
        boundaries=WorkflowBoundaries(
            first_step="File System:save_file",
            last_step="File System:save_file",
            min_duration_seconds=1.0,
            max_duration_seconds=10.0,
            average_duration_seconds=5.0,
            total_supporting_sessions=2,
        ),
        risk_assessment=RiskAssessment(
            overall_risk_level=RiskLevel.LOW,
            primary_risk_category=RiskCategory.LOCAL_CHANGE,
            requires_human_confirmation=False,
            step_risks=[],
            summary="Low risk",
            sensitive_factors_detected=[],
        ),
        expected_effects=[
            ExpectedStateChange(
                target_system="File System",
                entity_or_property="customer_summary.json",
                before_state="Does not exist",
                expected_after_state="customer_summary.json exists",
                actual_state="UNTOUCHED",
            )
        ],
        dry_run_status="SIMULATED",
    )

    CanonicalWorkflowRepository().save(spec)
    ExecutionPlanRepository().save(plan)
    return plan


def test_verification_model_creation():
    """1. Test formal verification models instantiate properly with all fields."""
    check = VerificationCheck(
        verification_id="chk-001",
        execution_id="exec-001",
        execution_step_id="estep-001",
        planned_step_id="pstep-001",
        check_type="file_exists",
        strategy_type=VerificationStrategyType.FILE_SYSTEM,
        target="summary.json",
        expected_state={"exists": True},
        actual_state={"exists": True},
        status=VerificationStatus.VERIFIED,
        evidence={"path": "summary.json", "size_bytes": 100},
        reason="File confirmed to exist",
    )
    assert check.verification_id == "chk-001"
    assert check.status == VerificationStatus.VERIFIED
    assert check.reason == "File confirmed to exist"

    result = VerificationResult(
        verification_run_id="vrun-001",
        execution_id="exec-001",
        workflow_id="wf-001",
        execution_plan_id="plan-001",
        overall_status=VerificationStatus.VERIFIED,
        checks=[check],
        verified_count=1,
        failed_count=0,
        unknown_count=0,
        not_applicable_count=0,
        evidence={"summary": "all passed"},
    )
    assert result.overall_status == VerificationStatus.VERIFIED
    assert result.verified_count == 1
    assert len(result.checks) == 1


def test_file_existence_and_evidence(temp_sandbox_dir):
    """2, 5, 7. Test file existence, non-empty validation, and evidence generation."""
    test_file = temp_sandbox_dir / "report.json"
    content = '{"status": "completed", "count": 42}'
    test_file.write_text(content, encoding="utf-8")

    strategy = FileSystemVerificationStrategy()

    # 1. file_exists check
    check = VerificationCheck(
        execution_id="exec-fs-1",
        execution_step_id="es-1",
        planned_step_id="ps-1",
        check_type="file_exists",
        strategy_type=VerificationStrategyType.RESOURCE_EXISTENCE,
        target="report.json",
        expected_state={"exists": True, "min_size_bytes": 1},
        actual_state={},
        status=VerificationStatus.PENDING,
        reason="",
    )
    eval_check = strategy.verify(check, str(temp_sandbox_dir))

    assert eval_check.status == VerificationStatus.VERIFIED
    assert eval_check.actual_state["exists"] is True
    assert eval_check.evidence["exists"] is True
    assert eval_check.evidence["size_bytes"] == len(content.encode("utf-8"))
    assert "sha256" in eval_check.evidence
    assert len(eval_check.evidence["sha256"]) == 64


def test_missing_file_verification(temp_sandbox_dir):
    """3. Test missing file verification fails deterministically."""
    strategy = FileSystemVerificationStrategy()

    check = VerificationCheck(
        execution_id="exec-fs-miss",
        execution_step_id="es-1",
        planned_step_id="ps-1",
        check_type="file_exists",
        strategy_type=VerificationStrategyType.RESOURCE_EXISTENCE,
        target="non_existent.json",
        expected_state={"exists": True},
        actual_state={},
        status=VerificationStatus.PENDING,
        reason="",
    )
    eval_check = strategy.verify(check, str(temp_sandbox_dir))

    assert eval_check.status == VerificationStatus.FAILED
    assert eval_check.actual_state["exists"] is False
    assert "does not exist inside sandbox" in eval_check.reason


def test_directory_verification(temp_sandbox_dir):
    """4. Test directory existence verification."""
    sub_dir = temp_sandbox_dir / "output_dir"
    sub_dir.mkdir(parents=True, exist_ok=True)

    strategy = FileSystemVerificationStrategy()

    check = VerificationCheck(
        execution_id="exec-fs-dir",
        execution_step_id="es-1",
        planned_step_id="ps-1",
        check_type="directory_exists",
        strategy_type=VerificationStrategyType.RESOURCE_EXISTENCE,
        target="output_dir",
        expected_state={"exists": True, "is_directory": True},
        actual_state={},
        status=VerificationStatus.PENDING,
        reason="",
    )
    eval_check = strategy.verify(check, str(temp_sandbox_dir))

    assert eval_check.status == VerificationStatus.VERIFIED
    assert eval_check.actual_state["is_directory"] is True
    assert eval_check.evidence["is_directory"] is True


def test_json_structured_field_verification(temp_sandbox_dir):
    """6. Test deterministic JSON structured field verification."""
    json_file = temp_sandbox_dir / "customer_summary.json"
    actual_data = {
        "customer": "Rahul",
        "status": "replacement_requested",
        "units": 2,
    }
    json_file.write_text(json.dumps(actual_data), encoding="utf-8")

    strategy = StructuredOutputVerificationStrategy()

    # A. Match case
    expected_matching = {
        "customer": "Rahul",
        "status": "replacement_requested",
    }
    check = VerificationCheck(
        execution_id="exec-struct-1",
        execution_step_id="es-1",
        planned_step_id="ps-1",
        check_type="structured_json_match",
        strategy_type=VerificationStrategyType.STRUCTURED_OUTPUT,
        target="customer_summary.json",
        expected_state=expected_matching,
        actual_state={},
        status=VerificationStatus.PENDING,
        reason="",
    )
    eval_check = strategy.verify(check, str(temp_sandbox_dir))
    assert eval_check.status == VerificationStatus.VERIFIED
    assert "expected structured fields matched" in eval_check.reason
    assert "customer" in eval_check.actual_state["matched_fields"]

    # B. Mismatch case
    expected_mismatch = {
        "customer": "Rahul",
        "status": "replacement_approved",  # Differs from actual
    }
    check_mismatch = VerificationCheck(
        execution_id="exec-struct-1",
        execution_step_id="es-1",
        planned_step_id="ps-1",
        check_type="structured_json_match",
        strategy_type=VerificationStrategyType.STRUCTURED_OUTPUT,
        target="customer_summary.json",
        expected_state=expected_mismatch,
        actual_state={},
        status=VerificationStatus.PENDING,
        reason="",
    )
    eval_fail = strategy.verify(check_mismatch, str(temp_sandbox_dir))
    assert eval_fail.status == VerificationStatus.FAILED
    assert "Structured value mismatch" in eval_fail.reason
    assert "status" in [m["field"] for m in eval_fail.actual_state["mismatched_fields"]]


def test_executor_success_and_verification_verified(sample_approved_plan):
    """8. Test normal path: Executor reports SUCCESS and verification reports VERIFIED."""
    exec_engine = ExecutionEngine()
    audit = exec_engine.execute_plan(sample_approved_plan.execution_plan_id)
    assert audit.status == ExecutionOverallStatus.COMPLETED
    assert audit.step_results[0].status == ExecutionStepStatus.SUCCESS

    verif_engine = VerificationEngine()
    verif_result = verif_engine.verify_execution(audit.execution_id)

    assert verif_result.overall_status == VerificationStatus.VERIFIED
    assert verif_result.verified_count >= 1
    assert verif_result.failed_count == 0

    # Verify audit record was updated with verification_status and verification_id
    updated_audit = ExecutionRepository().get_by_id(audit.execution_id)
    assert updated_audit.verification_status == "VERIFIED"
    assert updated_audit.verification_id == verif_result.verification_run_id


def test_executor_success_and_verification_failed(sample_approved_plan):
    """9. Test crucial distinction: Executor reports SUCCESS but Verification FAILED."""
    exec_engine = ExecutionEngine()
    audit = exec_engine.execute_plan(sample_approved_plan.execution_plan_id)
    assert audit.status == ExecutionOverallStatus.COMPLETED

    # Deliberately delete the generated file from the sandbox before verification
    created_file = Path(audit.sandbox_root) / "customer_summary.json"
    assert created_file.exists()
    created_file.unlink()

    verif_engine = VerificationEngine()
    verif_result = verif_engine.verify_execution(audit.execution_id, force_recheck=True)

    # Executor was SUCCESS, but verification must report FAILED
    assert verif_result.overall_status == VerificationStatus.FAILED
    assert verif_result.failed_count >= 1
    assert verif_result.verified_count == 0

    updated_audit = ExecutionRepository().get_by_id(audit.execution_id)
    assert updated_audit.status == ExecutionOverallStatus.COMPLETED  # Executor status untouched
    assert updated_audit.verification_status == "FAILED"  # Verification status distinct!


def test_executor_success_and_verification_unknown(sample_approved_plan):
    """10. Test Executor reports SUCCESS, but Step is UNKNOWN (e.g. unknown action/strategy)."""
    # Configure planned step as unsupported custom action with no verifiers
    sample_approved_plan.planned_steps[0].action = "unsupported_custom_action"
    sample_approved_plan.planned_steps[0].application = "ExternalDevice"
    sample_approved_plan.planned_steps[0].resolved_parameters = {}
    ExecutionPlanRepository().save(sample_approved_plan)

    audit = ExecutionAuditRecord(
        execution_id="exec-unknown-test",
        workflow_id="wf-1",
        workflow_version="1.0.0",
        execution_plan_id=sample_approved_plan.execution_plan_id,
        approval_state="approved",
        execution_mode=ExecutionMode.LIVE,
        status=ExecutionOverallStatus.COMPLETED,
        sandbox_root=str(Path(tempfile.gettempdir()) / "workflowos_sandbox" / "exec-unknown-test"),
        step_results=[
            ExecutionStepResult(
                execution_step_id="estep-unk",
                planned_step_id=sample_approved_plan.planned_steps[0].plan_step_id,
                action_name="unsupported_custom_action",
                target_application="ExternalDevice",
                strategy=ExecutionStrategy.APPLICATION_INTEGRATION,
                executor_name="ControlledLocalExecutor",
                status=ExecutionStepStatus.SUCCESS,
                parameters_used={},
                output={},
                affected_resources=[],
            )
        ],
    )
    Path(audit.sandbox_root).mkdir(parents=True, exist_ok=True)
    ExecutionRepository().save(audit)

    verif_engine = VerificationEngine()
    verif_result = verif_engine.verify_execution("exec-unknown-test", force_recheck=True)

    assert verif_result.overall_status == VerificationStatus.UNKNOWN
    assert verif_result.unknown_count == 1
    assert verif_result.checks[0].status == VerificationStatus.UNKNOWN

    updated_audit = ExecutionRepository().get_by_id("exec-unknown-test")
    assert updated_audit.verification_status == "UNKNOWN"


def test_workflow_level_aggregation():
    """11. Test deterministic workflow-level aggregation rules:
    - Any FAILED -> FAILED
    - No FAILED, Any UNKNOWN -> UNKNOWN
    - All VERIFIED -> VERIFIED
    - All NOT_APPLICABLE -> NOT_APPLICABLE
    """
    engine = VerificationEngine()

    c_v = VerificationCheck(
        verification_id="c1",
        execution_id="e1",
        execution_step_id="s1",
        planned_step_id="p1",
        check_type="file_exists",
        strategy_type=VerificationStrategyType.FILE_SYSTEM,
        target="f1",
        expected_state={},
        actual_state={},
        status=VerificationStatus.VERIFIED,
        evidence={},
        reason="ok",
    )
    c_f = VerificationCheck(
        verification_id="c2",
        execution_id="e1",
        execution_step_id="s2",
        planned_step_id="p2",
        check_type="file_exists",
        strategy_type=VerificationStrategyType.FILE_SYSTEM,
        target="f2",
        expected_state={},
        actual_state={},
        status=VerificationStatus.FAILED,
        evidence={},
        reason="missing",
    )
    c_u = VerificationCheck(
        verification_id="c3",
        execution_id="e1",
        execution_step_id="s3",
        planned_step_id="p3",
        check_type="custom",
        strategy_type=VerificationStrategyType.NOT_APPLICABLE,
        target="f3",
        expected_state={},
        actual_state={},
        status=VerificationStatus.UNKNOWN,
        evidence={},
        reason="unverifiable",
    )
    c_na = VerificationCheck(
        verification_id="c4",
        execution_id="e1",
        execution_step_id="s4",
        planned_step_id="p4",
        check_type="none",
        strategy_type=VerificationStrategyType.NOT_APPLICABLE,
        target="f4",
        expected_state={},
        actual_state={},
        status=VerificationStatus.NOT_APPLICABLE,
        evidence={},
        reason="skipped",
    )

    # 1. Any FAILED -> FAILED
    assert engine._aggregate_status([c_v, c_f, c_u]) == VerificationStatus.FAILED
    # 2. No FAILED, Any UNKNOWN -> UNKNOWN
    assert engine._aggregate_status([c_v, c_u]) == VerificationStatus.UNKNOWN
    # 3. All VERIFIED -> VERIFIED
    assert engine._aggregate_status([c_v]) == VerificationStatus.VERIFIED
    # 4. Mixed VERIFIED and NOT_APPLICABLE -> VERIFIED
    assert engine._aggregate_status([c_v, c_na]) == VerificationStatus.VERIFIED
    # 5. Only NOT_APPLICABLE -> NOT_APPLICABLE
    assert engine._aggregate_status([c_na]) == VerificationStatus.NOT_APPLICABLE


def test_optional_step_handling(sample_approved_plan):
    """12. Optional steps that were skipped or not applicable should not fail overall verification."""
    exec_engine = ExecutionEngine()
    audit = exec_engine.execute_plan(sample_approved_plan.execution_plan_id)

    # Add a skipped optional step to plan and audit
    opt_step = PlannedStep(
        plan_step_id="pstep-opt",
        source_canonical_step_id="can-step-opt",
        source_semantic_step_id="sem-step-opt",
        source_dna_step_key="dna-step-opt",
        application="Slack",
        action="send_notification",
        description="Notify on completion",
        resolved_parameters={},
        execution_strategy=StepExecutionStrategy(
            strategy=ExecutionStrategy.APPLICATION_INTEGRATION,
            reason="Communication",
            target_technology="Slack Webhook API",
        ),
        risk=StepRisk(
            step_id="can-step-opt",
            application="Slack",
            action="send_notification",
            risk_level=RiskLevel.LOW,
            risk_category=RiskCategory.COMMUNICATION,
            reason="Optional notification",
            requires_confirmation=False,
        ),
        expected_result="Notification sent",
        external_change=True,
        requires_confirmation=False,
        evidence_reference="evidence-opt",
        state_change=ExpectedStateChange(
            target_system="Slack",
            entity_or_property="notification",
            before_state="None",
            expected_after_state="Sent",
            actual_state="UNTOUCHED",
        ),
    )
    sample_approved_plan.planned_steps.append(opt_step)
    ExecutionPlanRepository().save(sample_approved_plan)

    audit.step_results.append(
        ExecutionStepResult(
            execution_step_id="estep-opt-skipped",
            planned_step_id="pstep-opt",
            action_name="send_notification",
            target_application="Slack",
            strategy=ExecutionStrategy.APPLICATION_INTEGRATION,
            executor_name="ControlledLocalExecutor",
            status=ExecutionStepStatus.SKIPPED,
            parameters_used={},
            output={},
            affected_resources=[],
        )
    )
    ExecutionRepository().save(audit)

    verif_engine = VerificationEngine()
    verif_result = verif_engine.verify_execution(audit.execution_id, force_recheck=True)

    # Skipped step should produce NOT_APPLICABLE check and not fail the overall run
    opt_check = next(c for c in verif_result.checks if c.execution_step_id == "estep-opt-skipped")
    assert opt_check.status == VerificationStatus.NOT_APPLICABLE
    assert verif_result.overall_status == VerificationStatus.VERIFIED


def test_sandbox_boundary_and_arbitrary_path_rejection(temp_sandbox_dir):
    """13, 14. Test sandbox boundary containment and rejection of path traversal."""
    strategy = FileSystemVerificationStrategy()

    check = VerificationCheck(
        execution_id="exec-sec",
        execution_step_id="es-1",
        planned_step_id="ps-1",
        check_type="file_exists",
        strategy_type=VerificationStrategyType.RESOURCE_EXISTENCE,
        target="../../Windows/System32/drivers/etc/hosts",
        expected_state={"exists": True},
        actual_state={},
        status=VerificationStatus.PENDING,
        reason="",
    )
    eval_check = strategy.verify(check, str(temp_sandbox_dir))

    assert eval_check.status == VerificationStatus.FAILED
    assert "Sandbox security violation" in eval_check.reason


def test_external_verification_rejection(sample_approved_plan):
    """15. Test external service actions are rejected from local verification strategies."""
    # Modify planned step to be Gmail
    gmail_step = PlannedStep(
        plan_step_id="pstep-gmail",
        source_canonical_step_id="can-step-gmail",
        source_semantic_step_id="sem-step-gmail",
        source_dna_step_key="dna-step-gmail",
        application="Gmail",
        action="send_email",
        description="Send email via Gmail",
        resolved_parameters={},
        execution_strategy=StepExecutionStrategy(
            strategy=ExecutionStrategy.APPLICATION_INTEGRATION,
            reason="External communication",
            target_technology="Gmail API",
        ),
        risk=StepRisk(
            step_id="can-step-gmail",
            application="Gmail",
            action="send_email",
            risk_level=RiskLevel.MEDIUM,
            risk_category=RiskCategory.COMMUNICATION,
            reason="External service",
            requires_confirmation=True,
        ),
        expected_result="Email sent",
        external_change=True,
        requires_confirmation=True,
        evidence_reference="evidence-gmail",
        state_change=ExpectedStateChange(
            target_system="Gmail",
            entity_or_property="email",
            before_state="None",
            expected_after_state="Sent",
            actual_state="UNTOUCHED",
        ),
    )
    sample_approved_plan.planned_steps = [gmail_step]
    ExecutionPlanRepository().save(sample_approved_plan)

    audit = ExecutionAuditRecord(
        execution_id="exec-ext-test",
        workflow_id=sample_approved_plan.source_workflow_id,
        workflow_version="1.0.0",
        execution_plan_id=sample_approved_plan.execution_plan_id,
        approval_state="approved",
        execution_mode=ExecutionMode.LIVE,
        status=ExecutionOverallStatus.COMPLETED,
        sandbox_root=str(Path(tempfile.gettempdir()) / "workflowos_sandbox" / "exec-ext-test"),
        step_results=[
            ExecutionStepResult(
                execution_step_id="estep-ext",
                planned_step_id="pstep-gmail",
                action_name="send_email",
                target_application="Gmail",
                strategy=ExecutionStrategy.APPLICATION_INTEGRATION,
                executor_name="ControlledLocalExecutor",
                status=ExecutionStepStatus.SUCCESS,
                parameters_used={},
                output={},
                affected_resources=["gmail_api"],
            )
        ],
    )
    Path(audit.sandbox_root).mkdir(parents=True, exist_ok=True)
    ExecutionRepository().save(audit)

    verif_engine = VerificationEngine()
    verif_result = verif_engine.verify_execution("exec-ext-test", force_recheck=True)

    assert verif_result.overall_status == VerificationStatus.NOT_APPLICABLE
    assert verif_result.checks[0].status == VerificationStatus.NOT_APPLICABLE
    assert "External service verification" in verif_result.checks[0].reason


def test_verification_persistence_across_repository_reload(sample_approved_plan):
    """16. Test SQLite persistence of verification results and checks across repository reload."""
    exec_engine = ExecutionEngine()
    audit = exec_engine.execute_plan(sample_approved_plan.execution_plan_id)

    verif_engine = VerificationEngine()
    verif_result = verif_engine.verify_execution(audit.execution_id)

    # Re-instantiate repository (simulating server reboot)
    new_repo = VerificationRepository()
    loaded_result = new_repo.get_by_id(verif_result.verification_run_id)

    assert loaded_result is not None
    assert loaded_result.verification_run_id == verif_result.verification_run_id
    assert loaded_result.execution_id == audit.execution_id
    assert loaded_result.overall_status == VerificationStatus.VERIFIED
    assert len(loaded_result.checks) == len(verif_result.checks)
    assert loaded_result.checks[0].check_type == verif_result.checks[0].check_type
    assert loaded_result.checks[0].evidence["sha256"] == verif_result.checks[0].evidence["sha256"]


def test_repeated_verification_behavior(sample_approved_plan):
    """17. Test idempotency: Calling verify multiple times reuses existing result unless force_recheck=True."""
    exec_engine = ExecutionEngine()
    audit = exec_engine.execute_plan(sample_approved_plan.execution_plan_id)

    verif_engine = VerificationEngine()
    res1 = verif_engine.verify_execution(audit.execution_id, force_recheck=False)

    # Calling again without force_recheck should return exact same verification run ID
    res2 = verif_engine.verify_execution(audit.execution_id, force_recheck=False)
    assert res1.verification_run_id == res2.verification_run_id

    # Calling with force_recheck=True creates a fresh verification run
    res3 = verif_engine.verify_execution(audit.execution_id, force_recheck=True)
    assert res3.verification_run_id != res1.verification_run_id
    assert res3.overall_status == VerificationStatus.VERIFIED

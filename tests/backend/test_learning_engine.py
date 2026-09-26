"""Deterministic Unit & Integration Tests for Phase 11: Workflow Learning & Reliability Intelligence.

Tests:
1. Empty history produces a valid learning profile
2. Single verified success is counted correctly
3. Repeated verified successes produce the correct reliability metrics
4. Execution failure is classified correctly
5. Verification failure is not counted as success
6. Blocked execution is distinguished from execution failure
7. Unsupported strategy produces the correct learning event
8. Repeated unsupported strategy generates an improvement suggestion
9. Repeated verification failures generate an improvement suggestion
10. Repeated unresolved parameter problems generate a suggestion
11. Step-level statistics are correct
12. Workflow-level statistics are correct
13. Learning is deterministic
14. Learning refresh is idempotent
15. Learning survives persistence/reload
16. Learning does not modify CanonicalWorkflowSpec
17. Learning does not modify approval state
18. Learning does not execute workflows
19. Learning does not make external requests
20. Existing Phase 0–10 tests remain passing
"""

from datetime import datetime, timezone
import json
import os
import tempfile
import uuid
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
    ExecutionMode,
    ExecutionOverallStatus,
    ExecutionStepResult,
    ExecutionStepStatus,
)
from app.models.execution_plan import ExecutionStrategy
from app.models.learning import (
    FailureCategory,
    LearningEventType,
    LearningThresholds,
    WorkflowReliabilityProfile,
)
from app.models.verification import (
    VerificationCheck,
    VerificationResult,
    VerificationStatus,
    VerificationStrategyType,
)
from app.repositories.canonical_repository import CanonicalWorkflowRepository
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.learning_repository import LearningRepository
from app.repositories.verification_repository import VerificationRepository
from app.services.learning_engine import LearningEngine


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    try:
        os.remove(path)
    except OSError:
        pass


@pytest.fixture
def repos(temp_db):
    exec_repo = ExecutionRepository(db_path=temp_db)
    verif_repo = VerificationRepository(db_path=temp_db)
    learn_repo = LearningRepository(db_path=temp_db)
    spec_repo = CanonicalWorkflowRepository(db_path=temp_db)
    return {
        "exec": exec_repo,
        "verif": verif_repo,
        "learn": learn_repo,
        "spec": spec_repo,
        "db": temp_db,
    }


@pytest.fixture
def engine(repos):
    return LearningEngine(
        execution_repo=repos["exec"],
        verification_repo=repos["verif"],
        learning_repo=repos["learn"],
        canonical_repo=repos["spec"],
        thresholds=LearningThresholds(
            min_executions_for_reliability_insight=1,
            repeated_failure_threshold=2,
            repeated_block_threshold=2,
            repeated_parameter_problem_threshold=2,
            high_reliability_threshold=2,
        ),
    )


def create_sample_spec(workflow_id: str = "wf-test-1") -> CanonicalWorkflowSpec:
    return CanonicalWorkflowSpec(
        workflow_id=workflow_id,
        source_dna_id="dna-1",
        source_semantic_workflow_id="sem-1",
        title="Test Workflow",
        intent="Save customer summary",
        description="Local customer summary writer",
        version="1.0.0",
        status="approved",
        approval_state=ApprovalMetadata(
            state=ApprovalState.APPROVED,
            reviewed_by="admin",
            reviewed_at=datetime.now(timezone.utc).isoformat(),
        ),
        steps=[
            CanonicalStep(
                canonical_step_id="step-1",
                source_semantic_step_id="ssem-1",
                source_dna_step_key="sdna-1",
                application="File System",
                event_type="file:create",
                action="save_file",
                description="Write local file",
                input_variables=["file_name", "content"],
                output_variables=["status"],
                risk=StepRisk(
                    step_id="step-1",
                    application="File System",
                    action="save_file",
                    risk_level=RiskLevel.LOW,
                    risk_category=RiskCategory.READ_ONLY,
                    reason="Safe sandbox save",
                    requires_confirmation=False,
                ),
                evidence_reference="ev-1",
            )
        ],
        variables=[],
        boundaries=WorkflowBoundaries(
            first_step="save_file",
            last_step="save_file",
            min_duration_seconds=1.0,
            max_duration_seconds=5.0,
            average_duration_seconds=2.0,
            total_supporting_sessions=2,
        ),
        evidence=DNAEvidence(
            supporting_session_count=2,
            invariant_evidence="Consistent file saving",
            variable_evidence="filename, content",
            optional_step_evidence="None",
            ordering_evidence="Single step",
            boundary_evidence="Local sandbox folder",
        ),
        risk_assessment=RiskAssessment(
            overall_risk_level=RiskLevel.LOW,
            primary_risk_category=RiskCategory.READ_ONLY,
            summary="Low risk local workflow",
        ),
    )


def record_verified_execution(repos, workflow_id="wf-test-1", step_id="step-1", action="save_file"):
    exec_id = f"exec-{uuid.uuid4().hex[:8]}"
    step_res = ExecutionStepResult(
        planned_step_id=step_id,
        action_name=action,
        target_application="File System",
        strategy=ExecutionStrategy.CONTROLLED_LOCAL,
        executor_name="ControlledLocalExecutor",
        status=ExecutionStepStatus.SUCCESS,
        selected_strategy="CONTROLLED_LOCAL",
        fallback_used=False,
        policy_decision="ALLOWED",
    )
    exec_rec = ExecutionAuditRecord(
        execution_id=exec_id,
        workflow_id=workflow_id,
        execution_plan_id="plan-1",
        approval_state="approved",
        status=ExecutionOverallStatus.COMPLETED,
        sandbox_root="/tmp/sandbox",
        step_results=[step_res],
        verification_status="VERIFIED",
    )
    repos["exec"].save(exec_rec)

    v_run = VerificationResult(
        verification_run_id=f"vrun-{uuid.uuid4().hex[:8]}",
        execution_id=exec_id,
        workflow_id=workflow_id,
        execution_plan_id="plan-1",
        overall_status=VerificationStatus.VERIFIED,
        verified_count=1,
        checks=[
            VerificationCheck(
                execution_id=exec_id,
                execution_step_id=step_res.execution_step_id,
                planned_step_id=step_id,
                check_type="file_exists",
                strategy_type=VerificationStrategyType.FILE_SYSTEM,
                target="output.txt",
                expected_state=True,
                actual_state=True,
                status=VerificationStatus.VERIFIED,
                reason="File exists inside sandbox",
            )
        ],
    )
    repos["verif"].save(v_run)
    return exec_rec, v_run


def record_verification_failure_execution(repos, workflow_id="wf-test-1", step_id="step-1", action="save_file"):
    exec_id = f"exec-{uuid.uuid4().hex[:8]}"
    step_res = ExecutionStepResult(
        planned_step_id=step_id,
        action_name=action,
        target_application="File System",
        strategy=ExecutionStrategy.CONTROLLED_LOCAL,
        executor_name="ControlledLocalExecutor",
        status=ExecutionStepStatus.SUCCESS,
        selected_strategy="CONTROLLED_LOCAL",
        fallback_used=False,
        policy_decision="ALLOWED",
    )
    exec_rec = ExecutionAuditRecord(
        execution_id=exec_id,
        workflow_id=workflow_id,
        execution_plan_id="plan-1",
        approval_state="approved",
        status=ExecutionOverallStatus.COMPLETED,
        sandbox_root="/tmp/sandbox",
        step_results=[step_res],
        verification_status="FAILED",
    )
    repos["exec"].save(exec_rec)

    v_run = VerificationResult(
        verification_run_id=f"vrun-{uuid.uuid4().hex[:8]}",
        execution_id=exec_id,
        workflow_id=workflow_id,
        execution_plan_id="plan-1",
        overall_status=VerificationStatus.FAILED,
        failed_count=1,
        checks=[
            VerificationCheck(
                execution_id=exec_id,
                execution_step_id=step_res.execution_step_id,
                planned_step_id=step_id,
                check_type="file_exists",
                strategy_type=VerificationStrategyType.FILE_SYSTEM,
                target="output.txt",
                expected_state=True,
                actual_state=False,
                status=VerificationStatus.FAILED,
                reason="File was missing in sandbox",
            )
        ],
    )
    repos["verif"].save(v_run)
    return exec_rec, v_run


def record_blocked_execution(repos, workflow_id="wf-test-1", step_id="step-ext", action="send_slack_notification", reason="UNSUPPORTED_EXECUTION_STRATEGY"):
    exec_id = f"exec-{uuid.uuid4().hex[:8]}"
    step_res = ExecutionStepResult(
        planned_step_id=step_id,
        action_name=action,
        target_application="Slack",
        strategy=ExecutionStrategy.APPLICATION_INTEGRATION,
        executor_name="None",
        status=ExecutionStepStatus.BLOCKED,
        selected_strategy=None,
        blocked_reason=reason,
        policy_decision="BLOCKED",
        error=f"Blocked: {reason}",
    )
    exec_rec = ExecutionAuditRecord(
        execution_id=exec_id,
        workflow_id=workflow_id,
        execution_plan_id="plan-1",
        approval_state="approved",
        status=ExecutionOverallStatus.BLOCKED,
        sandbox_root="/tmp/sandbox",
        step_results=[step_res],
        verification_status="NOT_APPLICABLE",
    )
    repos["exec"].save(exec_rec)
    return exec_rec


# ==============================================================================
# 1. Empty history produces a valid learning profile
# ==============================================================================
def test_empty_history_produces_valid_profile(engine):
    profile = engine.analyze_workflow("wf-nonexistent")
    assert isinstance(profile, WorkflowReliabilityProfile)
    assert profile.workflow_id == "wf-nonexistent"
    assert profile.total_executions == 0
    assert profile.reliability_rate == 0.0
    assert profile.step_reliabilities == []
    assert profile.detected_patterns == []
    assert profile.suggestions == []


# ==============================================================================
# 2. Single verified success is counted correctly
# ==============================================================================
def test_single_verified_success_counted_correctly(engine, repos):
    record_verified_execution(repos, workflow_id="wf-1")
    profile = engine.analyze_workflow("wf-1")

    assert profile.total_executions == 1
    assert profile.successful_executions == 1
    assert profile.verified_executions == 1
    assert profile.failed_executions == 0
    assert profile.verification_failures == 0
    assert profile.reliability_rate == 1.0
    assert profile.verification_rate == 1.0
    assert len(profile.latest_events) == 1
    assert profile.latest_events[0].event_type == LearningEventType.EXECUTION_SUCCESS_OBSERVED


# ==============================================================================
# 3. Repeated verified successes produce correct metrics and trigger milestone
# ==============================================================================
def test_repeated_verified_successes(engine, repos):
    record_verified_execution(repos, workflow_id="wf-rep")
    record_verified_execution(repos, workflow_id="wf-rep")

    profile = engine.analyze_workflow("wf-rep")
    assert profile.total_executions == 2
    assert profile.verified_executions == 2
    assert profile.reliability_rate == 1.0

    # Milestone pattern
    pat_types = [p.pattern_type for p in profile.detected_patterns]
    assert "REPEATED_VERIFIED_SUCCESS" in pat_types

    sug_categories = [s.category for s in profile.suggestions]
    assert "HIGH_RELIABILITY" in sug_categories


# ==============================================================================
# 4. Execution failure is classified correctly
# ==============================================================================
def test_execution_failure_classified_correctly(engine, repos):
    exec_id = "exec-fail-1"
    step_res = ExecutionStepResult(
        planned_step_id="step-1",
        action_name="save_file",
        target_application="File System",
        strategy=ExecutionStrategy.CONTROLLED_LOCAL,
        executor_name="ControlledLocalExecutor",
        status=ExecutionStepStatus.FAILED,
        error="Permission denied inside sandbox",
    )
    exec_rec = ExecutionAuditRecord(
        execution_id=exec_id,
        workflow_id="wf-fail",
        execution_plan_id="plan-1",
        approval_state="approved",
        status=ExecutionOverallStatus.FAILED,
        sandbox_root="/tmp/sandbox",
        step_results=[step_res],
        error_summary="Permission denied inside sandbox",
    )
    repos["exec"].save(exec_rec)

    profile = engine.analyze_workflow("wf-fail")
    assert profile.total_executions == 1
    assert profile.failed_executions == 1
    assert profile.verified_executions == 0
    assert profile.reliability_rate == 0.0

    cat = engine.classify_failure(step_res, exec_rec.status, None)
    assert cat == FailureCategory.EXECUTION_FAILURE


# ==============================================================================
# 5. Verification failure is not counted as success
# ==============================================================================
def test_verification_failure_not_counted_as_success(engine, repos):
    record_verification_failure_execution(repos, workflow_id="wf-vfail")
    profile = engine.analyze_workflow("wf-vfail")

    assert profile.total_executions == 1
    assert profile.successful_executions == 1  # executor phase succeeded
    assert profile.verification_failures == 1  # but verification failed
    assert profile.verified_executions == 0    # so verified count is strictly ZERO
    assert profile.reliability_rate == 0.0     # reliability is 0.0!

    cat = engine.classify_failure(
        profile.step_reliabilities[0] if profile.step_reliabilities else None,
        ExecutionOverallStatus.COMPLETED,
        VerificationStatus.FAILED,
    )
    assert cat == FailureCategory.VERIFICATION_FAILURE


# ==============================================================================
# 6. Blocked execution is distinguished from execution failure
# ==============================================================================
def test_blocked_execution_distinguished_from_failure(engine, repos):
    record_blocked_execution(repos, workflow_id="wf-block", reason="UNSUPPORTED_EXECUTION_STRATEGY")
    profile = engine.analyze_workflow("wf-block")

    assert profile.total_executions == 1
    assert profile.blocked_executions == 1
    assert profile.failed_executions == 0  # NOT an execution failure!
    assert profile.blocked_rate == 1.0


# ==============================================================================
# 7. Unsupported strategy produces the correct learning event
# ==============================================================================
def test_unsupported_strategy_produces_learning_event(engine, repos):
    record_blocked_execution(repos, workflow_id="wf-unsupp", reason="UNSUPPORTED_EXECUTION_STRATEGY")
    profile = engine.analyze_workflow("wf-unsupp")

    events = [e for e in profile.latest_events if e.event_type == LearningEventType.STRATEGY_BLOCK_OBSERVED]
    assert len(events) >= 1
    assert "unsupported execution strategy" in events[0].insight.lower()


# ==============================================================================
# 8. Repeated unsupported strategy generates improvement suggestion
# ==============================================================================
def test_repeated_unsupported_strategy_generates_suggestion(engine, repos):
    record_blocked_execution(repos, workflow_id="wf-unsupp-rep", step_id="step-slack", action="send_slack")
    record_blocked_execution(repos, workflow_id="wf-unsupp-rep", step_id="step-slack", action="send_slack")

    profile = engine.analyze_workflow("wf-unsupp-rep")
    patterns = [p.pattern_type for p in profile.detected_patterns]
    assert "REPEATED_UNSUPPORTED_STRATEGY" in patterns

    sugs = [s for s in profile.suggestions if s.category == "STRATEGY_REQUIREMENT"]
    assert len(sugs) == 1
    assert sugs[0].is_advisory is True
    assert "execution strategy" in sugs[0].suggestion.lower()


# ==============================================================================
# 9. Repeated verification failures generate an improvement suggestion
# ==============================================================================
def test_repeated_verification_failures_generate_suggestion(engine, repos):
    record_verification_failure_execution(repos, workflow_id="wf-vfail-rep", step_id="step-file")
    record_verification_failure_execution(repos, workflow_id="wf-vfail-rep", step_id="step-file")

    profile = engine.analyze_workflow("wf-vfail-rep")
    patterns = [p.pattern_type for p in profile.detected_patterns]
    assert "REPEATED_VERIFICATION_FAILURE" in patterns

    sugs = [s for s in profile.suggestions if s.category == "VERIFICATION_DEFINITION"]
    assert len(sugs) == 1
    assert sugs[0].is_advisory is True
    assert "expected-state" in sugs[0].suggestion.lower()


# ==============================================================================
# 10. Repeated unresolved parameter problems generate a suggestion
# ==============================================================================
def test_repeated_parameter_problems_generate_suggestion(engine, repos):
    record_blocked_execution(repos, workflow_id="wf-param", step_id="step-p", reason="UNRESOLVED_PARAMETER")
    record_blocked_execution(repos, workflow_id="wf-param", step_id="step-p", reason="UNRESOLVED_PARAMETER")

    profile = engine.analyze_workflow("wf-param")
    patterns = [p.pattern_type for p in profile.detected_patterns]
    assert "REPEATED_PARAMETER_PROBLEM" in patterns

    sugs = [s for s in profile.suggestions if s.category == "PARAMETER_CONFIG"]
    assert len(sugs) == 1
    assert sugs[0].is_advisory is True
    assert "parameters" in sugs[0].suggestion.lower()


# ==============================================================================
# 11. Step-level statistics are correct
# ==============================================================================
def test_step_level_statistics_are_correct(engine, repos):
    record_verified_execution(repos, workflow_id="wf-steps", step_id="step-a", action="action_a")
    record_verification_failure_execution(repos, workflow_id="wf-steps", step_id="step-a", action="action_a")

    profile = engine.analyze_workflow("wf-steps")
    assert len(profile.step_reliabilities) == 1
    st = profile.step_reliabilities[0]
    assert st.planned_step_id == "step-a"
    assert st.total_executions == 2
    assert st.successful_executions == 2
    assert st.verified_success_count == 1
    assert st.verification_failure_count == 1
    assert st.last_outcome == "VERIFICATION_FAILED"


# ==============================================================================
# 12. Workflow-level statistics are correct
# ==============================================================================
def test_workflow_level_statistics_are_correct(engine, repos):
    record_verified_execution(repos, workflow_id="wf-mix")
    record_verification_failure_execution(repos, workflow_id="wf-mix")
    record_blocked_execution(repos, workflow_id="wf-mix")

    profile = engine.analyze_workflow("wf-mix")
    assert profile.total_executions == 3
    assert profile.successful_executions == 2
    assert profile.verified_executions == 1
    assert profile.verification_failures == 1
    assert profile.blocked_executions == 1
    assert profile.blocked_rate == round(1 / 3, 4)
    # completed_executable = 1 (verified) + 1 (vfail) = 2
    assert profile.reliability_rate == 0.5


# ==============================================================================
# 13. Learning is deterministic
# ==============================================================================
def test_learning_is_deterministic(engine, repos):
    record_verified_execution(repos, workflow_id="wf-det")
    record_verification_failure_execution(repos, workflow_id="wf-det")

    profile1 = engine.analyze_workflow("wf-det", persist=False)
    profile2 = engine.analyze_workflow("wf-det", persist=False)

    assert profile1.total_executions == profile2.total_executions
    assert profile1.reliability_rate == profile2.reliability_rate
    assert profile1.verification_failures == profile2.verification_failures
    assert len(profile1.detected_patterns) == len(profile2.detected_patterns)
    assert len(profile1.suggestions) == len(profile2.suggestions)


# ==============================================================================
# 14. Learning refresh is idempotent
# ==============================================================================
def test_learning_refresh_is_idempotent(engine, repos):
    record_verified_execution(repos, workflow_id="wf-idem")

    profile_run1 = engine.analyze_workflow("wf-idem", persist=True)
    profile_run2 = engine.analyze_workflow("wf-idem", persist=True)

    assert profile_run1.total_executions == profile_run2.total_executions
    assert profile_run1.reliability_rate == profile_run2.reliability_rate
    # SQLite has only one row per workflow_id
    stored = repos["learn"].get_profile("wf-idem")
    assert stored is not None
    assert stored.total_executions == 1


# ==============================================================================
# 15. Learning survives persistence/reload
# ==============================================================================
def test_learning_survives_persistence_and_reload(repos, temp_db):
    engine1 = LearningEngine(
        execution_repo=repos["exec"],
        verification_repo=repos["verif"],
        learning_repo=repos["learn"],
    )
    record_verified_execution(repos, workflow_id="wf-persist")
    engine1.analyze_workflow("wf-persist", persist=True)

    # Reinitialize repos with same sqlite file
    learn_repo2 = LearningRepository(db_path=temp_db)
    reloaded_profile = learn_repo2.get_profile("wf-persist")
    assert reloaded_profile is not None
    assert reloaded_profile.workflow_id == "wf-persist"
    assert reloaded_profile.verified_executions == 1
    assert reloaded_profile.reliability_rate == 1.0


# ==============================================================================
# 16. Learning does not modify CanonicalWorkflowSpec
# ==============================================================================
def test_learning_does_not_modify_canonical_spec(engine, repos):
    spec = create_sample_spec("wf-spec-guard")
    repos["spec"].save(spec)
    spec_before_json = spec.model_dump_json()

    record_verified_execution(repos, workflow_id="wf-spec-guard")
    engine.analyze_workflow("wf-spec-guard", persist=True)

    spec_after = repos["spec"].get_by_id("wf-spec-guard")
    assert spec_after is not None
    assert spec_after.model_dump_json() == spec_before_json


# ==============================================================================
# 17. Learning does not modify approval state
# ==============================================================================
def test_learning_does_not_modify_approval_state(engine, repos):
    spec = create_sample_spec("wf-approval-guard")
    repos["spec"].save(spec)

    record_verification_failure_execution(repos, workflow_id="wf-approval-guard")
    record_verification_failure_execution(repos, workflow_id="wf-approval-guard")
    engine.analyze_workflow("wf-approval-guard", persist=True)

    spec_after = repos["spec"].get_by_id("wf-approval-guard")
    assert spec_after.approval_state.state == ApprovalState.APPROVED


# ==============================================================================
# 18. Learning does not execute workflows
# ==============================================================================
def test_learning_does_not_execute_workflows(engine, repos):
    record_verified_execution(repos, workflow_id="wf-noexec")
    exec_count_before = len(repos["exec"].list_all(workflow_id="wf-noexec"))

    engine.analyze_workflow("wf-noexec", persist=True)
    exec_count_after = len(repos["exec"].list_all(workflow_id="wf-noexec"))

    assert exec_count_before == exec_count_after == 1


# ==============================================================================
# 19. Learning does not make external requests
# ==============================================================================
def test_learning_does_not_make_external_requests(engine, repos, monkeypatch):
    import urllib.request
    def fail_network(*args, **kwargs):
        raise RuntimeError("External network request forbidden in Phase 11 learning")

    monkeypatch.setattr(urllib.request, "urlopen", fail_network)

    record_blocked_execution(repos, workflow_id="wf-netguard")
    profile = engine.analyze_workflow("wf-netguard", persist=True)
    assert profile.total_executions == 1


# ==============================================================================
# 20. Learning suggestions are strictly advisory
# ==============================================================================
def test_all_suggestions_are_strictly_advisory(engine, repos):
    record_verification_failure_execution(repos, workflow_id="wf-advisory")
    record_verification_failure_execution(repos, workflow_id="wf-advisory")

    profile = engine.analyze_workflow("wf-advisory", persist=True)
    assert len(profile.suggestions) > 0
    for sug in profile.suggestions:
        assert sug.is_advisory is True

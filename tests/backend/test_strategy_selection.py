"""Automated Deterministic Test Suite for Phase 10: Adaptive Execution & Multi-Strategy Executor Selection.

Tests all required Phase 10 criteria:
1. Local action selects CONTROLLED_LOCAL.
2. Unsupported external action is safely blocked.
3. Unsupported strategy is not treated as executable.
4. Implemented executor is preferred over unsupported executor.
5. Fallback ordering is deterministic and reproducible.
6. Risk policy can block a technically capable executor.
7. Unapproved workflow cannot execute.
8. Rejected workflow cannot execute.
9. Unresolved required parameter blocks execution.
10. Strategy selection is represented in dry-run simulation.
11. Selected strategy appears in execution audit record.
12. Unsupported strategy produces deterministic BLOCKED result in live engine.
13. Verification is not fabricated for blocked execution (NOT_APPLICABLE).
14. Local sandbox execution and verification remain intact.
15. Idempotency remains intact.
"""

from datetime import datetime, timezone
import os
from pathlib import Path
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
from app.models.dna import WorkflowBoundaries
from app.models.execution import (
    ExecutionAuditRecord,
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
from app.models.strategy import (
    ExecutionStrategyType,
    ExecutorCapability,
    StrategySelectionResult,
)
from app.models.verification import VerificationStatus
from app.repositories.canonical_repository import CanonicalWorkflowRepository
from app.repositories.execution_plan_repository import ExecutionPlanRepository
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.verification_repository import VerificationRepository
from app.services.canonical_factory import CanonicalWorkflowFactory
from app.services.dry_run_simulator import DryRunSimulator
from app.services.execution_engine import ExecutionEngine
from app.services.execution_planner import ExecutionPlanner
from app.services.execution_policy import ExecutionPolicyEngine
from app.services.executors.controlled_local import ControlledLocalExecutor
from app.services.executors.registry import ExecutorRegistry
from app.services.semantic_engine import SemanticUnderstandingEngine
from app.services.semantic_provider import MockSemanticProvider
from app.services.strategy_selector import StrategySelector
from app.services.verification_engine import VerificationEngine
from app.services.workflow_discovery import WorkflowDiscoveryEngine
from app.services.workflow_dna_extractor import WorkflowDNAExtractor
from app.services.workflow_segmenter import WorkflowSegmenter
from tests.fixtures.discovery_fixtures import generate_deterministic_dataset


@pytest.fixture
def base_approved_spec():
    """Generates an approved CanonicalWorkflowSpec from the standard synthetic dataset."""
    events = generate_deterministic_dataset()
    sessions = WorkflowSegmenter(session_inactivity_timeout_seconds=120.0).segment(events)
    discovery = WorkflowDiscoveryEngine(min_occurrences=2, similarity_threshold=0.65)
    candidates = discovery.discover_candidates(sessions)
    session_map = {s.session_id: s for s in sessions}
    supporting = [session_map[sid] for sid in candidates[0].supporting_session_ids]
    extractor = WorkflowDNAExtractor()
    dna = extractor.extract_dna(candidates[0], supporting)

    engine = SemanticUnderstandingEngine(provider=MockSemanticProvider(mode="valid"))
    resp = engine.interpret_dna(dna)
    assert resp.status == "success"
    semantic_wf = resp.semantic_workflow
    assert semantic_wf is not None

    factory = CanonicalWorkflowFactory()
    spec = factory.create_specification(dna=dna, semantic_wf=semantic_wf)
    spec.approval_state = ApprovalMetadata(
        state=ApprovalState.APPROVED,
        reviewed_by="security-compliance-officer",
        reviewed_at=datetime.now(timezone.utc).isoformat(),
        comments="Approved for deterministic execution testing.",
    )
    return spec



@pytest.fixture
def mock_temp_repos():
    """Provides isolated SQLite/in-memory repositories in a temporary directory."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "test_p10.db")
        os.environ["WORKFLOWOS_DB_PATH"] = db_path
        os.environ["WORKFLOWOS_SANDBOX_DIR"] = os.path.join(tmp_dir, "sandboxes")

        canonical_repo = CanonicalWorkflowRepository()
        plan_repo = ExecutionPlanRepository()
        exec_repo = ExecutionRepository()
        verif_repo = VerificationRepository()
        registry = ExecutorRegistry()
        policy = ExecutionPolicyEngine(registry=registry)
        selector = StrategySelector(registry=registry, policy_engine=policy)

        engine = ExecutionEngine(
            canonical_repo=canonical_repo,
            plan_repo=plan_repo,
            exec_repo=exec_repo,
            registry=registry,
            policy_engine=policy,
            strategy_selector=selector,
            default_sandbox_base=os.path.join(tmp_dir, "sandboxes"),
        )
        verif_engine = VerificationEngine(
            exec_repo=exec_repo,
            plan_repo=plan_repo,
            verif_repo=verif_repo,
        )

        yield {
            "tmp_dir": tmp_dir,
            "canonical_repo": canonical_repo,
            "plan_repo": plan_repo,
            "exec_repo": exec_repo,
            "verif_repo": verif_repo,
            "registry": registry,
            "selector": selector,
            "engine": engine,
            "verif_engine": verif_engine,
        }


# =========================================================================
# Scenario 1: Local action selects CONTROLLED_LOCAL
# =========================================================================
def test_local_action_selects_controlled_local(mock_temp_repos):
    selector = mock_temp_repos["selector"]

    local_step = PlannedStep(
        plan_step_id="step-local-1",
        source_canonical_step_id="canon-1",
        source_semantic_step_id="sem-1",
        source_dna_step_key="dna-1",
        application="File System",
        action="save_file",
        description="Save output payload to disk",
        resolved_parameters={"file_name": "data.json", "content": '{"status": "ok"}'},
        execution_strategy=StepExecutionStrategy(
            strategy=ExecutionStrategy.APPLICATION_INTEGRATION,
            reason="Local file access",
            target_technology="Local OS File System API",
        ),
        risk=StepRisk(
            step_id="step-local-1",
            application="File System",
            action="save_file",
            risk_level=RiskLevel.LOW,
            risk_category=RiskCategory.READ_ONLY,
            reason="Local file write inside isolated sandbox",
            requires_confirmation=False,
        ),
        expected_result="File saved",
        external_change=False,
        requires_confirmation=False,
        evidence_reference="ev-1",
        state_change=ExpectedStateChange(
            target_system="File System",
            entity_or_property="data.json",
            before_state="missing",
            expected_after_state="created",
        ),
    )

    result = selector.select_strategy(local_step)
    assert result.is_executable is True
    assert result.selected_strategy == ExecutionStrategyType.CONTROLLED_LOCAL
    assert result.selected_executor == "ControlledLocalExecutor"
    assert result.policy_decision == "ALLOWED"
    assert result.blocked_reason is None


# =========================================================================
# Scenario 2: Unsupported external action is safely blocked
# =========================================================================
def test_unsupported_external_action_is_blocked(mock_temp_repos):
    selector = mock_temp_repos["selector"]

    slack_step = PlannedStep(
        plan_step_id="step-ext-slack",
        source_canonical_step_id="canon-2",
        source_semantic_step_id="sem-2",
        source_dna_step_key="dna-2",
        application="Slack",
        action="send_slack_notification",
        description="Notify operations channel",
        resolved_parameters={"channel": "#ops", "message": "Workflow completed"},
        execution_strategy=StepExecutionStrategy(
            strategy=ExecutionStrategy.API,
            reason="Slack API notification",
            target_technology="Slack Webhook",
        ),
        risk=StepRisk(
            step_id="step-ext-slack",
            application="Slack",
            action="send_slack_notification",
            risk_level=RiskLevel.MEDIUM,
            risk_category=RiskCategory.COMMUNICATION,
            reason="External communication mutation",
            requires_confirmation=False,
        ),
        expected_result="Slack notification sent",
        external_change=True,
        requires_confirmation=False,
        evidence_reference="ev-2",
        state_change=ExpectedStateChange(
            target_system="Slack",
            entity_or_property="chat_message",
            before_state="not sent",
            expected_after_state="sent",
        ),
    )

    result = selector.select_strategy(slack_step)
    assert result.is_executable is False
    assert result.selected_strategy is None
    assert result.selected_executor is None
    assert result.policy_decision == "BLOCKED"
    assert result.blocked_reason in ("UNSUPPORTED_EXECUTION_STRATEGY", "POLICY_REJECTED_RISK")
    assert "No implemented executor" in result.selection_reason or "Policy violation" in result.selection_reason


# =========================================================================
# Scenario 3: Unsupported strategy is not treated as executable
# =========================================================================
def test_unsupported_strategy_not_treated_as_executable(mock_temp_repos):
    registry = mock_temp_repos["registry"]

    unsupported_strategies = [
        ExecutionStrategyType.API_INTEGRATION,
        ExecutionStrategyType.APPLICATION_INTEGRATION,
        ExecutionStrategyType.ACCESSIBILITY_UI,
        ExecutionStrategyType.BROWSER_AUTOMATION,
        ExecutionStrategyType.UI_FALLBACK,
    ]

    for strat in unsupported_strategies:
        executor = registry.get_executor_for_strategy(strat)
        assert executor is not None, f"Strategy {strat.value} must be architecturally represented in registry"
        assert executor.capability.implemented is False, f"Strategy {strat.value} must NOT be implemented in Phase 10"


# =========================================================================
# Scenario 4: Implemented executor is preferred over unsupported executor
# =========================================================================
def test_implemented_executor_preferred_over_unsupported(mock_temp_repos):
    selector = mock_temp_repos["selector"]

    step = PlannedStep(
        plan_step_id="step-report-1",
        source_canonical_step_id="canon-rep",
        source_semantic_step_id="sem-rep",
        source_dna_step_key="dna-rep",
        application="File System",
        action="generate_report",
        description="Generate local summary report",
        resolved_parameters={"file_name": "report.txt"},
        execution_strategy=StepExecutionStrategy(
            strategy=ExecutionStrategy.APPLICATION_INTEGRATION,
            reason="Report generation",
            target_technology="Local OS File System",
        ),
        risk=StepRisk(
            step_id="step-report-1",
            application="File System",
            action="generate_report",
            risk_level=RiskLevel.LOW,
            risk_category=RiskCategory.READ_ONLY,
            reason="Local file creation",
            requires_confirmation=False,
        ),
        expected_result="Report created",
        external_change=False,
        requires_confirmation=False,
        evidence_reference="ev-rep",
        state_change=ExpectedStateChange(
            target_system="File System",
            entity_or_property="report.txt",
            before_state="none",
            expected_after_state="created",
        ),
    )

    result = selector.select_strategy(step)
    assert result.is_executable is True
    assert result.selected_strategy == ExecutionStrategyType.CONTROLLED_LOCAL
    # Check that candidate strategies included both CONTROLLED_LOCAL (implemented) and APPLICATION_INTEGRATION (unimplemented)
    cand_names = [c.strategy.value for c in result.candidates_considered]
    assert ExecutionStrategyType.CONTROLLED_LOCAL.value in cand_names
    assert ExecutionStrategyType.APPLICATION_INTEGRATION.value in cand_names


# =========================================================================
# Scenario 5: Fallback ordering is deterministic
# =========================================================================
def test_fallback_ordering_is_deterministic(mock_temp_repos):
    selector = mock_temp_repos["selector"]

    step = PlannedStep(
        plan_step_id="step-crm-1",
        source_canonical_step_id="canon-crm",
        source_semantic_step_id="sem-crm",
        source_dna_step_key="dna-crm",
        application="Salesforce",
        action="update_crm_record",
        description="Update enterprise CRM lead",
        resolved_parameters={"lead_id": "001XYZ"},
        execution_strategy=StepExecutionStrategy(
            strategy=ExecutionStrategy.APPLICATION_INTEGRATION,
            reason="CRM Update",
            target_technology="Salesforce REST API",
        ),
        risk=StepRisk(
            step_id="step-crm-1",
            application="Salesforce",
            action="update_crm_record",
            risk_level=RiskLevel.MEDIUM,
            risk_category=RiskCategory.EXTERNAL_CHANGE,
            reason="Enterprise mutation",
            requires_confirmation=False,
        ),
        expected_result="CRM lead updated",
        external_change=True,
        requires_confirmation=False,
        evidence_reference="ev-crm",
        state_change=ExpectedStateChange(
            target_system="Salesforce",
            entity_or_property="Lead.Status",
            before_state="New",
            expected_after_state="Contacted",
        ),
    )

    res1 = selector.select_strategy(step)
    res2 = selector.select_strategy(step)

    # Identical priority evaluation and candidate ordering
    assert [c.strategy.value for c in res1.candidates_considered] == [c.strategy.value for c in res2.candidates_considered]
    assert res1.policy_decision == res2.policy_decision
    assert res1.selected_strategy == res2.selected_strategy


# =========================================================================
# Scenario 6: Risk policy can block a technically capable executor
# =========================================================================
def test_risk_policy_can_block_technically_capable_executor(mock_temp_repos):
    selector = mock_temp_repos["selector"]

    # Action is 'save_file' (which ControlledLocalExecutor normally supports),
    # but risk category is forced to EXTERNAL_CHANGE
    step = PlannedStep(
        plan_step_id="step-risk-block",
        source_canonical_step_id="canon-rb",
        source_semantic_step_id="sem-rb",
        source_dna_step_key="dna-rb",
        application="External Cloud Disk",
        action="save_file",
        description="Save file to external cloud infrastructure",
        resolved_parameters={"file_name": "cloud.json"},
        execution_strategy=StepExecutionStrategy(
            strategy=ExecutionStrategy.CONTROLLED_LOCAL,
            reason="Local file attempted for external cloud disk",
            target_technology="Local OS File System",
        ),
        risk=StepRisk(
            step_id="step-risk-block",
            application="External Cloud Disk",
            action="save_file",
            risk_level=RiskLevel.HIGH,
            risk_category=RiskCategory.EXTERNAL_CHANGE,
            reason="External change violates local execution policy",
            requires_confirmation=True,
        ),

        expected_result="File saved to cloud",
        external_change=True,
        requires_confirmation=True,
        evidence_reference="ev-rb",
        state_change=ExpectedStateChange(
            target_system="Cloud Storage",
            entity_or_property="cloud.json",
            before_state="none",
            expected_after_state="created",
        ),
    )

    result = selector.select_strategy(step)
    assert result.is_executable is False
    assert result.policy_decision == "BLOCKED"
    assert result.blocked_reason == "POLICY_REJECTED_RISK"


# =========================================================================
# Scenario 7: Unapproved workflow cannot execute
# =========================================================================
def test_unapproved_workflow_cannot_execute(mock_temp_repos, base_approved_spec):
    engine = mock_temp_repos["engine"]
    plan_repo = mock_temp_repos["plan_repo"]
    canonical_repo = mock_temp_repos["canonical_repo"]

    # Mark spec as REQUIRES_REVIEW (not approved)
    base_approved_spec.approval_state = ApprovalMetadata(
        state=ApprovalState.REQUIRES_REVIEW,
        reviewed_by=None,
        reviewed_at=None,
        review_notes="Pending human review",
    )
    canonical_repo.save(base_approved_spec)

    # Creating a plan with unapproved workflow raises ValueError
    planner = ExecutionPlanner()
    with pytest.raises(ValueError, match="must be APPROVED"):
        planner.create_execution_plan(spec=base_approved_spec)


# =========================================================================
# Scenario 8: Rejected workflow cannot execute
# =========================================================================
def test_rejected_workflow_cannot_execute(mock_temp_repos, base_approved_spec):
    canonical_repo = mock_temp_repos["canonical_repo"]

    base_approved_spec.approval_state = ApprovalMetadata(
        state=ApprovalState.REJECTED,
        reviewed_by="compliance-officer",
        reviewed_at=datetime.now(timezone.utc).isoformat(),
        review_notes="Rejected due to policy violation",
    )
    canonical_repo.save(base_approved_spec)

    planner = ExecutionPlanner()
    with pytest.raises(ValueError, match="must be APPROVED"):
        planner.create_execution_plan(spec=base_approved_spec)


# =========================================================================
# Scenario 9: Unresolved required parameter blocks execution
# =========================================================================
def test_unresolved_required_parameter_blocks_execution(mock_temp_repos, base_approved_spec):
    engine = mock_temp_repos["engine"]
    plan_repo = mock_temp_repos["plan_repo"]
    canonical_repo = mock_temp_repos["canonical_repo"]

    canonical_repo.save(base_approved_spec)

    # Create plan with an unresolved parameter
    base_approved_spec.variables[0].observed_values = []
    planner = ExecutionPlanner()
    plan = planner.create_execution_plan(spec=base_approved_spec, runtime_inputs={})
    plan_repo.save(plan)

    # Attempt execution -> must be rejected by execution policy
    with pytest.raises(ValueError, match="UNRESOLVED"):
        engine.execute_plan(plan.execution_plan_id)


# =========================================================================
# Scenario 10: Strategy selection is represented in dry-run
# =========================================================================
def test_strategy_selection_represented_in_dry_run(mock_temp_repos, base_approved_spec):
    planner = ExecutionPlanner()
    plan = planner.create_execution_plan(spec=base_approved_spec)

    simulator = DryRunSimulator()
    result = simulator.simulate(plan)

    assert result.real_actions_performed == 0
    assert len(result.step_simulations) == len(plan.planned_steps)

    for sim_step in result.step_simulations:
        assert sim_step.selected_strategy is not None
        assert "candidate_strategies" in sim_step.simulated_output
        assert "why_selected" in sim_step.simulated_output
        assert "policy_decision" in sim_step.simulated_output
        # Zero real execution
        assert sim_step.simulated_output["real_action_executed"] is False


# =========================================================================
# Scenario 11: Selected strategy appears in audit
# =========================================================================
def test_selected_strategy_appears_in_audit(mock_temp_repos, base_approved_spec):
    canonical_repo = mock_temp_repos["canonical_repo"]
    plan_repo = mock_temp_repos["plan_repo"]
    engine = mock_temp_repos["engine"]

    # Create local-only approved workflow
    base_approved_spec.steps = [
        CanonicalStep(
            canonical_step_id="step-audit-local",
            source_semantic_step_id="sem-aud",
            source_dna_step_key="dna-aud",
            application="File System",
            event_type="file:write",
            action="write_file",
            description="Write test file",
            input_variables=[],
            output_variables=[],
            risk=StepRisk(
                step_id="step-audit-local",
                application="File System",
                action="write_file",
                risk_level=RiskLevel.LOW,
                risk_category=RiskCategory.READ_ONLY,
                reason="Safe sandbox file write",
                requires_confirmation=False,
            ),
            evidence_reference="ev-aud",
        )
    ]
    canonical_repo.save(base_approved_spec)

    planner = ExecutionPlanner()
    plan = planner.create_execution_plan(spec=base_approved_spec)
    plan_repo.save(plan)

    audit_rec = engine.execute_plan(plan.execution_plan_id)
    assert audit_rec.status == ExecutionOverallStatus.COMPLETED
    assert len(audit_rec.step_results) == 1

    step_res = audit_rec.step_results[0]
    assert step_res.selected_strategy == "CONTROLLED_LOCAL"
    assert step_res.executor_name == "ControlledLocalExecutor"
    assert step_res.status == ExecutionStepStatus.SUCCESS
    assert "CONTROLLED_LOCAL" in step_res.candidate_strategies
    assert step_res.policy_decision == "ALLOWED"


# =========================================================================
# Scenario 12: Unsupported strategy produces deterministic blocked result
# =========================================================================
def test_unsupported_strategy_produces_deterministic_blocked_result(mock_temp_repos, base_approved_spec):
    canonical_repo = mock_temp_repos["canonical_repo"]
    plan_repo = mock_temp_repos["plan_repo"]
    engine = mock_temp_repos["engine"]

    # Plan containing an external Slack step
    base_approved_spec.steps = [
        CanonicalStep(
            canonical_step_id="step-slack-live",
            source_semantic_step_id="sem-slk",
            source_dna_step_key="dna-slk",
            application="Slack",
            event_type="slack:send_message",
            action="send_slack_notification",
            description="Post live Slack alert",
            input_variables=[],
            output_variables=[],
            risk=StepRisk(
                step_id="step-slack-live",
                application="Slack",
                action="send_slack_notification",
                risk_level=RiskLevel.MEDIUM,
                risk_category=RiskCategory.COMMUNICATION,
                reason="External messaging mutation",
                requires_confirmation=False,
            ),
            evidence_reference="ev-slk",
        )
    ]
    canonical_repo.save(base_approved_spec)

    planner = ExecutionPlanner()
    plan = planner.create_execution_plan(spec=base_approved_spec)
    plan_repo.save(plan)

    audit_rec = engine.execute_plan(plan.execution_plan_id)
    assert audit_rec.status == ExecutionOverallStatus.BLOCKED
    assert len(audit_rec.step_results) == 1

    blocked_step = audit_rec.step_results[0]
    assert blocked_step.status == ExecutionStepStatus.BLOCKED
    assert blocked_step.selected_strategy == "NONE"
    assert blocked_step.policy_decision == "BLOCKED"
    assert blocked_step.blocked_reason in ("UNSUPPORTED_EXECUTION_STRATEGY", "POLICY_REJECTED_RISK")
    assert "Blocked" in (blocked_step.error or "")


# =========================================================================
# Scenario 13: Verification is not fabricated for blocked execution
# =========================================================================
def test_verification_is_not_fabricated_for_blocked_execution(mock_temp_repos, base_approved_spec):
    canonical_repo = mock_temp_repos["canonical_repo"]
    plan_repo = mock_temp_repos["plan_repo"]
    engine = mock_temp_repos["engine"]
    verif_engine = mock_temp_repos["verif_engine"]

    base_approved_spec.steps = [
        CanonicalStep(
            canonical_step_id="step-crm-blocked",
            source_semantic_step_id="sem-crm",
            source_dna_step_key="dna-crm",
            application="Salesforce",
            event_type="crm:update_lead",
            action="update_crm_record",
            description="Update Salesforce lead",
            input_variables=[],
            output_variables=[],
            risk=StepRisk(
                step_id="step-crm-blocked",
                application="Salesforce",
                action="update_crm_record",
                risk_level=RiskLevel.HIGH,
                risk_category=RiskCategory.EXTERNAL_CHANGE,
                reason="External CRM mutation",
                requires_confirmation=True,
            ),
            evidence_reference="ev-crm",
        )
    ]
    canonical_repo.save(base_approved_spec)

    planner = ExecutionPlanner()
    plan = planner.create_execution_plan(spec=base_approved_spec)
    plan_repo.save(plan)

    audit_rec = engine.execute_plan(plan.execution_plan_id)
    assert audit_rec.status == ExecutionOverallStatus.BLOCKED

    # Run verification on blocked run
    verif_res = verif_engine.verify_execution(audit_rec.execution_id)
    assert verif_res.overall_status != VerificationStatus.VERIFIED
    # Verification check must be NOT_APPLICABLE (not fake evidence)
    assert len(verif_res.checks) == 1
    assert verif_res.checks[0].status == VerificationStatus.NOT_APPLICABLE
    assert "not executed (BLOCKED)" in verif_res.checks[0].actual_state or "prohibited" in verif_res.checks[0].actual_state


# =========================================================================
# Scenario 14: Local sandbox execution and verification remain intact
# =========================================================================
def test_local_sandbox_execution_and_verification_intact(mock_temp_repos, base_approved_spec):
    canonical_repo = mock_temp_repos["canonical_repo"]
    plan_repo = mock_temp_repos["plan_repo"]
    engine = mock_temp_repos["engine"]
    verif_engine = mock_temp_repos["verif_engine"]

    base_approved_spec.steps = [
        CanonicalStep(
            canonical_step_id="step-loc-create",
            source_semantic_step_id="sem-crt",
            source_dna_step_key="dna-crt",
            application="File System",
            event_type="file:create",
            action="create_file",
            description="Create test local payload",
            input_variables=[],
            output_variables=[],
            risk=StepRisk(
                step_id="step-loc-create",
                application="File System",
                action="create_file",
                risk_level=RiskLevel.LOW,
                risk_category=RiskCategory.READ_ONLY,
                reason="Safe sandbox file",
                requires_confirmation=False,
            ),
            evidence_reference="ev-crt",
        )
    ]
    canonical_repo.save(base_approved_spec)

    planner = ExecutionPlanner()
    plan = planner.create_execution_plan(
        spec=base_approved_spec,
        runtime_inputs={"file_name": "test_output.json", "content": '{"result": "success"}'},
    )
    plan_repo.save(plan)

    audit_rec = engine.execute_plan(plan.execution_plan_id)
    assert audit_rec.status == ExecutionOverallStatus.COMPLETED

    verif_res = verif_engine.verify_execution(audit_rec.execution_id)
    assert verif_res.overall_status in (VerificationStatus.VERIFIED, VerificationStatus.UNKNOWN)


# =========================================================================
# Scenario 15: Idempotency remains intact
# =========================================================================
def test_idempotency_remains_intact(mock_temp_repos, base_approved_spec):
    canonical_repo = mock_temp_repos["canonical_repo"]
    plan_repo = mock_temp_repos["plan_repo"]
    engine = mock_temp_repos["engine"]

    base_approved_spec.steps = [
        CanonicalStep(
            canonical_step_id="step-idem",
            source_semantic_step_id="sem-id",
            source_dna_step_key="dna-id",
            application="File System",
            event_type="file:report",
            action="generate_report",
            description="Generate idempotent report",
            input_variables=[],
            output_variables=[],
            risk=StepRisk(
                step_id="step-idem",
                application="File System",
                action="generate_report",
                risk_level=RiskLevel.LOW,
                risk_category=RiskCategory.READ_ONLY,
                reason="Safe sandbox report",
                requires_confirmation=False,
            ),
            evidence_reference="ev-id",
        )
    ]
    canonical_repo.save(base_approved_spec)



    planner = ExecutionPlanner()
    plan = planner.create_execution_plan(spec=base_approved_spec)
    plan_repo.save(plan)

    key = f"idem-key-{uuid.uuid4().hex}"
    run1 = engine.execute_plan(plan.execution_plan_id, idempotency_key=key)
    run2 = engine.execute_plan(plan.execution_plan_id, idempotency_key=key)

    assert run1.execution_id == run2.execution_id
    assert run1.start_time == run2.start_time

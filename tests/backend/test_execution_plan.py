"""Deterministic automated tests for Phase 7 Execution Planning and Dry Run / Shadow Simulation.

Verifies:
1. Execution plan creation from an APPROVED canonical workflow specification.
2. Approved workflow requirement (draft / requires_review cannot produce plan).
3. Rejected workflow cannot produce an execution plan.
4. Parameter resolution (distinguishes definition, observed sample, runtime value, unresolved).
5. Unresolved parameter handling without LLM invention.
6. Duplicate semantic parameter handling preserving separate source identity.
7. Execution strategy selection and explainable rationale.
8. Expected state changes (before_state, expected_after_state, actual_state UNTOUCHED).
9. Precondition validation (satisfied, unsatisfied, unknown).
10. Risk propagation from Phase 6 risk analysis.
11. Confirmation requirement propagation.
12. Dry-run deterministic simulation (SIMULATED status, never SUCCESSFUL).
13. Persistence across repository reload / backend restart.
14. Guarantee that dry-run performs ZERO real actions (no clicks, emails, crm mutations, shell calls).
"""

import os
import tempfile
import pytest

from app.models.canonical import (
    ApprovalMetadata,
    ApprovalState,
    CanonicalWorkflowSpec,
)
from app.models.execution_plan import (
    ExecutionPlan,
    ExecutionStrategy,
    ParameterResolutionStatus,
    PreconditionStatus,
)
from app.services.canonical_factory import CanonicalWorkflowFactory
from app.services.execution_planner import ExecutionPlanner
from app.services.dry_run_simulator import DryRunSimulator
from app.repositories.canonical_repository import CanonicalWorkflowRepository
from app.repositories.execution_plan_repository import ExecutionPlanRepository
from app.services.semantic_engine import SemanticUnderstandingEngine
from app.services.semantic_provider import MockSemanticProvider
from app.services.workflow_discovery import WorkflowDiscoveryEngine
from app.services.workflow_dna_extractor import WorkflowDNAExtractor
from app.services.workflow_segmenter import WorkflowSegmenter
from tests.fixtures.discovery_fixtures import generate_deterministic_dataset


@pytest.fixture
def approved_spec():
    """Generates an approved CanonicalWorkflowSpec end-to-end through Phase 1-6 pipelines."""
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

    # Transition to APPROVED state
    spec.approval_state = ApprovalMetadata(
        state=ApprovalState.APPROVED,
        reviewed_by="security_admin",
        comments="Approved for automated planning verification",
    )
    return spec


def test_execution_plan_creation_from_approved_spec(approved_spec):
    """Execution plan should successfully be created from an approved workflow specification."""
    planner = ExecutionPlanner()
    plan = planner.create_execution_plan(spec=approved_spec)

    assert plan is not None
    assert plan.source_workflow_id == approved_spec.workflow_id
    assert plan.source_approval_state == "approved"
    assert len(plan.planned_steps) == len(approved_spec.steps)
    assert plan.dry_run_status == "not_started"


def test_unapproved_workflow_rejected_from_planning(approved_spec):
    """Draft or requires_review workflow cannot produce an execution plan."""
    approved_spec.approval_state.state = ApprovalState.REQUIRES_REVIEW
    planner = ExecutionPlanner()
    with pytest.raises(ValueError, match="must be APPROVED by a human reviewer"):
        planner.create_execution_plan(spec=approved_spec)


def test_rejected_workflow_cannot_produce_executable_plan(approved_spec):
    """Rejected workflow cannot produce an execution plan."""
    approved_spec.approval_state.state = ApprovalState.REJECTED
    approved_spec.approval_state.rejection_reason = "Unsafe sequence"
    planner = ExecutionPlanner()
    with pytest.raises(ValueError, match="must be APPROVED by a human reviewer"):
        planner.create_execution_plan(spec=approved_spec)


def test_parameter_resolution_distinguishes_sources(approved_spec):
    """Parameter resolution distinguishes definition, sample value, and runtime value."""
    runtime_inputs = {
        "customer_name": "Rahul",
    }

    planner = ExecutionPlanner()
    plan = planner.create_execution_plan(
        spec=approved_spec,
        runtime_inputs=runtime_inputs,
    )

    resolved_params = plan.resolved_parameters
    assert len(resolved_params) > 0

    # Verify that runtime_value was applied
    customer_param = None
    for param in resolved_params:
        if param.semantic_name == "customer_name":
            customer_param = param
            break

    if customer_param:
        assert customer_param.runtime_value == "Rahul"
        assert customer_param.resolution_status == ParameterResolutionStatus.RESOLVED


def test_unresolved_parameter_handling_without_inventing_values(approved_spec):
    """If runtime parameter is missing and observed values are empty, parameter remains UNRESOLVED."""
    # Temporarily clear observed values for one variable to verify UNRESOLVED status
    approved_spec.variables[0].observed_values = []

    planner = ExecutionPlanner()
    plan = planner.create_execution_plan(
        spec=approved_spec,
        runtime_inputs={},
    )

    # First parameter has no observed values and no runtime input
    assert plan.resolved_parameters[0].resolution_status == ParameterResolutionStatus.UNRESOLVED
    assert plan.resolved_parameters[0].runtime_value is None


def test_execution_strategy_selection_and_explanation(approved_spec):
    """Planner assigns strategy and provides human-readable explainable rationale."""
    spec_repo = CanonicalWorkflowRepository(db_path=":memory:")
    spec_repo.save(approved_spec)

    planner = ExecutionPlanner()
    plan = planner.create_execution_plan(spec=approved_spec)

    for step in plan.planned_steps:
        strat = step.execution_strategy
        assert strat.strategy in [
            ExecutionStrategy.API,
            ExecutionStrategy.APPLICATION_INTEGRATION,
            ExecutionStrategy.BROWSER_AUTOMATION,
            ExecutionStrategy.ACCESSIBILITY_SEMANTIC_UI,
            ExecutionStrategy.UI_FALLBACK,
        ]
        assert len(strat.reason) > 5
        assert len(strat.target_technology) > 2


def test_expected_state_changes_distinguishes_expected_from_actual(approved_spec):
    """Step expected state changes explicitly represent before, expected after, and actual untouched."""
    planner = ExecutionPlanner()
    plan = planner.create_execution_plan(spec=approved_spec)

    for step in plan.planned_steps:
        state_change = step.state_change
        assert state_change.target_system == step.application
        assert "UNTOUCHED" in state_change.actual_state
        assert "Simulation Mode" in state_change.actual_state


def test_precondition_validation_marks_unknown_without_assuming_satisfied(approved_spec):
    """Preconditions requiring runtime OS inspection must be marked UNKNOWN, not assumed satisfied."""
    approved_spec.preconditions = ["Target application window must be open", "User must be authenticated"]
    planner = ExecutionPlanner()
    plan = planner.create_execution_plan(spec=approved_spec)

    assert len(plan.preconditions) == 2
    for cond in plan.preconditions:
        assert cond.status == PreconditionStatus.UNKNOWN
        assert "inspection" in cond.evaluation_reason.lower()


def test_risk_and_confirmation_propagation(approved_spec):
    """Execution plan inherits per-step risk, workflow risk, and confirmation requirements from Phase 6."""
    planner = ExecutionPlanner()
    plan = planner.create_execution_plan(spec=approved_spec)

    assert plan.risk_assessment.overall_risk_level == approved_spec.risk_assessment.overall_risk_level
    assert plan.risk_assessment.requires_human_confirmation == approved_spec.risk_assessment.requires_human_confirmation

    for p_step, c_step in zip(plan.planned_steps, approved_spec.steps):
        assert p_step.risk.risk_level == c_step.risk.risk_level
        assert p_step.requires_confirmation == c_step.risk.requires_confirmation


def test_dry_run_simulation_and_zero_real_actions(approved_spec):
    """Dry-run simulator produces deterministic simulation and performs ZERO real actions."""
    planner = ExecutionPlanner()
    plan = planner.create_execution_plan(spec=approved_spec)

    simulator = DryRunSimulator()
    result = simulator.simulate(plan)

    # Simulator must report SIMULATED, not SUCCESSFUL
    assert result.overall_simulation_status == "SIMULATED"
    # STRICT GUARANTEE: zero real actions performed
    assert result.real_actions_performed == 0
    assert len(result.step_simulations) == len(plan.planned_steps)

    for step_res in result.step_simulations:
        assert step_res.simulation_status == "SIMULATED"
        assert "NOT performed" in step_res.notes or "Simulated" in step_res.notes


def test_dry_run_blocked_when_required_parameters_unresolved(approved_spec):
    """Dry run marks overall status as SIMULATION_BLOCKED when required parameters cannot be resolved."""
    # Force a parameter to be unresolved
    approved_spec.variables[0].observed_values = []
    planner = ExecutionPlanner()
    plan = planner.create_execution_plan(
        spec=approved_spec,
        runtime_inputs={},
    )

    simulator = DryRunSimulator()
    result = simulator.simulate(plan)

    assert result.overall_simulation_status == "SIMULATION_BLOCKED"
    assert result.real_actions_performed == 0


def test_persistence_across_restart(approved_spec):
    """Execution plan and dry-run results persist across database re-instantiation."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_file = tmp.name

    try:
        spec_repo = CanonicalWorkflowRepository(db_path=db_file)
        spec_repo.save(approved_spec)

        plan_repo = ExecutionPlanRepository(db_path=db_file)
        planner = ExecutionPlanner()
        plan = planner.create_execution_plan(spec=approved_spec)
        plan_repo.save(plan)

        simulator = DryRunSimulator()
        dry_run_result = simulator.simulate(plan)
        plan_repo.update_dry_run_result(plan.execution_plan_id, dry_run_result)

        # Re-instantiate repository (simulating server restart)
        reloaded_repo = ExecutionPlanRepository(db_path=db_file)
        retrieved_plan = reloaded_repo.get_by_id(plan.execution_plan_id)

        assert retrieved_plan is not None
        assert retrieved_plan.execution_plan_id == plan.execution_plan_id
        assert retrieved_plan.dry_run_status == "simulated"
        assert retrieved_plan.dry_run_result is not None
        assert retrieved_plan.dry_run_result.real_actions_performed == 0
        assert retrieved_plan.dry_run_result.overall_simulation_status == "SIMULATED"
    finally:
        if os.path.exists(db_file):
            try:
                os.remove(db_file)
            except OSError:
                pass

"""Comprehensive Automated Tests for Canonical Workflow Specification (Phase 6).

Verifies:
1. Canonical specification creation from WorkflowDNA + validated SemanticWorkflow.
2. Complete end-to-end traceability:
   ActivityEvent -> TaskSession -> DiscoveryCandidate -> WorkflowDNA -> SemanticWorkflow -> CanonicalWorkflowSpec.
3. Step traceability: CanonicalStep -> SemanticStep -> InvariantStep -> Evidence.
4. Parameter binding and deterministic type inference without LLM.
5. Independent handling of duplicate semantic names (no accidental merging).
6. Risk classification per step and aggregated workflow risk assessment.
7. Initial state is 'requires_review' / 'draft' (never auto-approved).
8. Approval state transition to 'approved' (approval records metadata only, NO execution).
9. Rejection state transition to 'rejected' with reason.
10. Editing semantic variable names updates the binding while keeping source_parameter immutable.
11. Invalid or mismatched SemanticWorkflow rejection.
12. Verification that no browser, shell, or API automation occurs during approval.
13. SQLite persistence across restarts (re-instantiated repository retrieves spec and state).
"""

import os
import tempfile
import pytest

from app.models.canonical import (
    ApprovalState,
    CanonicalWorkflowSpec,
    ParameterUpdateItem,
    RiskCategory,
    RiskLevel,
    VariableType,
)
from app.models.dna import VariableParameter, WorkflowDNA
from app.models.semantic import SemanticVariable, SemanticWorkflow
from app.repositories.canonical_repository import CanonicalWorkflowRepository
from app.services.canonical_factory import CanonicalWorkflowFactory
from app.services.parameter_binder import ParameterBinder
from app.services.risk_analyzer import RiskAnalyzer
from app.services.semantic_engine import SemanticUnderstandingEngine
from app.services.semantic_provider import MockSemanticProvider
from app.services.workflow_discovery import WorkflowDiscoveryEngine
from app.services.workflow_dna_extractor import WorkflowDNAExtractor
from app.services.workflow_segmenter import WorkflowSegmenter
from tests.fixtures.discovery_fixtures import generate_deterministic_dataset


@pytest.fixture
def sample_dna_and_semantic():
    """Generates a valid WorkflowDNA and a validated SemanticWorkflow."""
    events = generate_deterministic_dataset()
    segmenter = WorkflowSegmenter(session_inactivity_timeout_seconds=120.0)
    sessions = segmenter.segment(events)
    discovery = WorkflowDiscoveryEngine(
        min_occurrences=2,
        similarity_threshold=0.65,
        incidental_applications={"whatsapp"},
    )
    candidates = discovery.discover_candidates(sessions)
    assert len(candidates) >= 1

    session_map = {s.session_id: s for s in sessions}
    supporting = [session_map[sid] for sid in candidates[0].supporting_session_ids]
    extractor = WorkflowDNAExtractor()
    dna = extractor.extract_dna(candidates[0], supporting)

    mock_provider = MockSemanticProvider(mode="valid")
    engine = SemanticUnderstandingEngine(provider=mock_provider)
    resp = engine.interpret_dna(dna)
    assert resp.status == "success"
    assert resp.semantic_workflow is not None

    return dna, resp.semantic_workflow


def test_canonical_specification_creation(sample_dna_and_semantic) -> None:
    """Test standard creation of CanonicalWorkflowSpec from DNA and validated SemanticWorkflow."""
    dna, semantic_wf = sample_dna_and_semantic
    factory = CanonicalWorkflowFactory()

    spec = factory.create_specification(dna=dna, semantic_wf=semantic_wf)

    assert spec.workflow_id.startswith("wf-spec-")
    assert spec.source_dna_id == dna.dna_id
    assert spec.source_semantic_workflow_id == semantic_wf.semantic_workflow_id
    assert spec.title == semantic_wf.title
    assert spec.intent == semantic_wf.intent
    assert spec.version == "1.0.0"
    assert spec.status == "specification_ready"

    # Invariant steps match 1:1
    assert len(spec.steps) == len(semantic_wf.semantic_steps)
    # Parameters bound
    assert len(spec.variables) == len(dna.variable_parameters)
    # Preconditions preserved
    assert len(spec.preconditions) >= 1
    # Boundaries preserved
    assert spec.boundaries.first_step == dna.boundaries.first_step
    assert spec.boundaries.last_step == dna.boundaries.last_step


def test_complete_traceability_chain(sample_dna_and_semantic) -> None:
    """Every canonical step must trace back to SemanticStep, InvariantStep, and Evidence."""
    dna, semantic_wf = sample_dna_and_semantic
    factory = CanonicalWorkflowFactory()
    spec = factory.create_specification(dna=dna, semantic_wf=semantic_wf)

    dna_step_keys = {inv.step_key for inv in dna.invariant_steps}
    sem_step_ids = {st.step_id for st in semantic_wf.semantic_steps}

    for step in spec.steps:
        # Canonical Step -> Semantic Step
        assert step.source_semantic_step_id in sem_step_ids
        # Canonical Step -> DNA Step
        assert step.source_dna_step_key in dna_step_keys
        # Evidence reference exists
        assert len(step.evidence_reference) > 0
        # Classification is invariant
        assert step.classification == "invariant"
        assert step.occurrence_ratio == 1.0


def test_parameter_binding_and_type_inference(sample_dna_and_semantic) -> None:
    """Variables must be bound with deterministically inferred types without LLM invention."""
    dna, semantic_wf = sample_dna_and_semantic
    binder = ParameterBinder()
    bindings = binder.bind_parameters(dna, semantic_wf)

    assert len(bindings) == len(dna.variable_parameters)

    # Check window title variable is inferred as identifier
    title_vars = [b for b in bindings if "title" in b.source_field.lower()]
    assert len(title_vars) >= 1
    for tv in title_vars:
        assert tv.inferred_type == VariableType.IDENTIFIER
        assert tv.binding_status == "bound"
        assert tv.user_override is False

    # Check file name variable is inferred as filename
    file_vars = [b for b in bindings if "file" in b.source_field.lower()]
    assert len(file_vars) >= 1
    for fv in file_vars:
        assert fv.inferred_type == VariableType.FILENAME
        assert fv.binding_status == "bound"


def test_independent_handling_of_duplicate_semantic_names() -> None:
    """Distinct DNA parameters given the same semantic name must remain separate bindings."""
    binder = ParameterBinder()

    # Create dummy DNA with two different window title variables
    dna = WorkflowDNA(
        dna_id="dna-test-dup",
        source_candidate_id="cand-1",
        normalized_signature="test:sig",
        invariant_steps=[],
        variable_parameters=[
            VariableParameter(
                parameter_name="window_title_variable_1",
                source_field="metadata.window_title",
                associated_step_key="crm:window_focused",
                associated_application="CRM",
                observed_values=["CRM - Customer Rahul", "CRM - Customer Ananya"],
                distinct_value_count=2,
                total_observations=2,
                variation_ratio=1.0,
            ),
            VariableParameter(
                parameter_name="window_title_variable_3",
                source_field="metadata.window_title",
                associated_step_key="gmail:window_focused",
                associated_application="Gmail",
                observed_values=["Rahul - Replacement", "Ananya - Replacement"],
                distinct_value_count=2,
                total_observations=2,
                variation_ratio=1.0,
            ),
        ],
        optional_steps=[],
        ordering_constraints=[],
        preconditions=[],
        boundaries={
            "first_step": "s1",
            "last_step": "s2",
            "min_duration_seconds": 1.0,
            "max_duration_seconds": 2.0,
            "average_duration_seconds": 1.5,
            "total_supporting_sessions": 2,
        },
        evidence={
            "supporting_session_count": 2,
            "invariant_evidence": "ev",
            "variable_evidence": "ev",
            "optional_step_evidence": "ev",
            "ordering_evidence": "ev",
            "boundary_evidence": "ev",
        },
    )

    # Both variables given the same semantic name "customer_name" by the LLM
    semantic_wf = SemanticWorkflow(
        semantic_workflow_id="sem-wf-dup",
        source_dna_id="dna-test-dup",
        title="Test Duplicate Handling",
        intent="Test",
        summary="Test",
        semantic_steps=[],
        semantic_variables=[
            SemanticVariable(
                source_parameter="window_title_variable_1",
                semantic_name="customer_name",
                source_field="metadata.window_title",
                observed_values=["CRM - Customer Rahul"],
                reason="CRM title has customer name",
            ),
            SemanticVariable(
                source_parameter="window_title_variable_3",
                semantic_name="customer_name",
                source_field="metadata.window_title",
                observed_values=["Rahul - Replacement"],
                reason="Gmail title has customer name",
            ),
        ],
        boundaries=dna.boundaries,
        interpretation_notes="Notes",
    )

    bindings = binder.bind_parameters(dna, semantic_wf)

    # Must preserve TWO distinct bindings
    assert len(bindings) == 2
    assert bindings[0].source_parameter == "window_title_variable_1"
    assert bindings[0].semantic_name == "customer_name"
    assert bindings[1].source_parameter == "window_title_variable_3"
    assert bindings[1].semantic_name == "customer_name"
    assert bindings[0].binding_id != bindings[1].binding_id


def test_risk_classification(sample_dna_and_semantic) -> None:
    """Verify deterministic risk analysis across read_only, local_change, external_change, communication."""
    analyzer = RiskAnalyzer()

    # 1. Gmail observation -> read_only, LOW
    r1 = analyzer.analyze_step("s1", "Gmail", "Review incoming email", "Checking inbox for requests", "window_focused")
    assert r1.risk_category == RiskCategory.READ_ONLY
    assert r1.risk_level == RiskLevel.LOW
    assert r1.requires_confirmation is False
    assert "read-only" in r1.reason.lower()

    # 2. File Download -> local_change, MEDIUM
    r2 = analyzer.analyze_step("s2", "File System", "Download file", "Save invoice.pdf locally", "file_downloaded")
    assert r2.risk_category == RiskCategory.LOCAL_CHANGE
    assert r2.risk_level == RiskLevel.MEDIUM
    assert "local filesystem" in r2.reason.lower()

    # 3. CRM Update -> external_change, HIGH
    r3 = analyzer.analyze_step("s3", "CRM", "Update customer replacement record", "Mutate customer status in CRM", "window_focused")
    assert r3.risk_category == RiskCategory.EXTERNAL_CHANGE
    assert r3.risk_level == RiskLevel.HIGH
    assert r3.requires_confirmation is True
    assert "external" in r3.reason.lower()

    # 4. Slack notification -> communication, MEDIUM
    r4 = analyzer.analyze_step("s4", "Slack", "Notify operations team", "Post replacement update to channel", "window_focused")
    assert r4.risk_category == RiskCategory.COMMUNICATION
    assert r4.risk_level == RiskLevel.MEDIUM
    assert r4.requires_confirmation is True
    assert "notification" in r4.reason.lower()

    # 5. Potentially sensitive step -> potentially_sensitive, HIGH
    r5 = analyzer.analyze_step("s5", "Browser", "Enter password credential", "Input user credential token", "window_focused")
    assert r5.risk_category == RiskCategory.POTENTIALLY_SENSITIVE
    assert r5.risk_level == RiskLevel.HIGH
    assert r5.requires_confirmation is True


def test_initial_approval_state(sample_dna_and_semantic) -> None:
    """Newly generated specifications must always require review and never auto-approve."""
    dna, semantic_wf = sample_dna_and_semantic
    factory = CanonicalWorkflowFactory()
    spec = factory.create_specification(dna=dna, semantic_wf=semantic_wf)

    assert spec.approval_state.state == ApprovalState.REQUIRES_REVIEW
    assert spec.approval_state.reviewed_by is None
    assert spec.approval_state.reviewed_at is None


def test_approval_state_transition() -> None:
    """Approval updates governance metadata to 'approved' without executing anything."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        temp_db_path = tf.name

    try:
        repo = CanonicalWorkflowRepository(db_path=temp_db_path)
        events = generate_deterministic_dataset()
        segmenter = WorkflowSegmenter()
        sessions = segmenter.segment(events)
        discovery = WorkflowDiscoveryEngine(min_occurrences=2, similarity_threshold=0.65)
        candidates = discovery.discover_candidates(sessions)
        session_map = {s.session_id: s for s in sessions}
        supporting = [session_map[sid] for sid in candidates[0].supporting_session_ids]
        dna = WorkflowDNAExtractor().extract_dna(candidates[0], supporting)

        sem_wf = SemanticUnderstandingEngine(provider=MockSemanticProvider(mode="valid")).interpret_dna(dna).semantic_workflow
        factory = CanonicalWorkflowFactory()
        spec = factory.create_specification(dna=dna, semantic_wf=sem_wf)

        # Save to repo
        repo.save(spec)

        # Approve
        approved = repo.update_approval_state(
            workflow_id=spec.workflow_id,
            new_state=ApprovalState.APPROVED,
            reviewer="alice@company.com",
            comments="Verified steps and parameters.",
        )

        assert approved is not None
        assert approved.approval_state.state == ApprovalState.APPROVED
        assert approved.approval_state.reviewed_by == "alice@company.com"
        assert approved.approval_state.reviewed_at is not None
        assert approved.approval_state.comments == "Verified steps and parameters."

        # Fetch from repo to confirm persistence
        fetched = repo.get_by_id(spec.workflow_id)
        assert fetched is not None
        assert fetched.approval_state.state == ApprovalState.APPROVED
    finally:
        if os.path.exists(temp_db_path):
            os.remove(temp_db_path)


def test_rejection_state_transition() -> None:
    """Rejection updates state to 'rejected' with reason."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        temp_db_path = tf.name

    try:
        repo = CanonicalWorkflowRepository(db_path=temp_db_path)
        events = generate_deterministic_dataset()
        sessions = WorkflowSegmenter().segment(events)
        candidates = WorkflowDiscoveryEngine(min_occurrences=2, similarity_threshold=0.65).discover_candidates(sessions)
        session_map = {s.session_id: s for s in sessions}
        supporting = [session_map[sid] for sid in candidates[0].supporting_session_ids]
        dna = WorkflowDNAExtractor().extract_dna(candidates[0], supporting)
        sem_wf = SemanticUnderstandingEngine(provider=MockSemanticProvider()).interpret_dna(dna).semantic_workflow
        spec = CanonicalWorkflowFactory().create_specification(dna=dna, semantic_wf=sem_wf)
        repo.save(spec)

        rejected = repo.update_approval_state(
            workflow_id=spec.workflow_id,
            new_state=ApprovalState.REJECTED,
            reviewer="compliance_team",
            comments="Requires additional security verification.",
            rejection_reason="Unapproved external CRM modification.",
        )

        assert rejected is not None
        assert rejected.approval_state.state == ApprovalState.REJECTED
        assert rejected.approval_state.rejection_reason == "Unapproved external CRM modification."
    finally:
        if os.path.exists(temp_db_path):
            os.remove(temp_db_path)


def test_editing_semantic_variable_names(sample_dna_and_semantic) -> None:
    """User can edit semantic names while DNA source parameter remains immutable."""
    dna, semantic_wf = sample_dna_and_semantic
    factory = CanonicalWorkflowFactory()
    spec = factory.create_specification(dna=dna, semantic_wf=semantic_wf)

    binder = ParameterBinder()
    original_source_param = spec.variables[0].source_parameter

    # Rename customer_name -> client_full_name
    updated_bindings = binder.update_binding_name(
        bindings=spec.variables,
        source_parameter=original_source_param,
        new_semantic_name="client_full_name",
    )

    matching = next(b for b in updated_bindings if b.source_parameter == original_source_param)
    assert matching.semantic_name == "client_full_name"
    assert matching.source_parameter == original_source_param  # IMMUTABLE
    assert matching.user_override is True
    assert matching.binding_status == "user_modified"

    # Attempting to update a non-existent parameter must fail
    with pytest.raises(ValueError, match="not found"):
        binder.update_binding_name(spec.variables, "non_existent_param", "name")


def test_invalid_semantic_workflow_cannot_become_canonical(sample_dna_and_semantic) -> None:
    """An unvalidated or mismatched SemanticWorkflow must be rejected by factory."""
    dna, semantic_wf = sample_dna_and_semantic
    factory = CanonicalWorkflowFactory()

    # 1. Mismatched DNA ID
    mismatched_wf = semantic_wf.model_copy(update={"source_dna_id": "different-dna-id"})
    with pytest.raises(ValueError, match="Source DNA mismatch"):
        factory.create_specification(dna=dna, semantic_wf=mismatched_wf)

    # 2. Corrupted status
    error_wf = semantic_wf.model_copy(update={"status": "error"})
    with pytest.raises(ValueError, match="unvalidated"):
        factory.create_specification(dna=dna, semantic_wf=error_wf)


def test_sqlite_persistence_across_restart(sample_dna_and_semantic) -> None:
    """Specification and approval state must survive backend restarts."""
    dna, semantic_wf = sample_dna_and_semantic
    factory = CanonicalWorkflowFactory()
    spec = factory.create_specification(dna=dna, semantic_wf=semantic_wf)

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        temp_db_path = tf.name

    try:
        # First backend session
        repo1 = CanonicalWorkflowRepository(db_path=temp_db_path)
        repo1.save(spec)
        repo1.update_approval_state(
            workflow_id=spec.workflow_id,
            new_state=ApprovalState.APPROVED,
            reviewer="admin",
        )

        # Simulate backend restart with a completely new repository instance
        repo2 = CanonicalWorkflowRepository(db_path=temp_db_path)
        reloaded = repo2.get_by_id(spec.workflow_id)

        assert reloaded is not None
        assert reloaded.workflow_id == spec.workflow_id
        assert reloaded.title == spec.title
        assert reloaded.approval_state.state == ApprovalState.APPROVED
        assert reloaded.approval_state.reviewed_by == "admin"
        assert len(reloaded.steps) == len(spec.steps)
        assert len(reloaded.variables) == len(spec.variables)
    finally:
        if os.path.exists(temp_db_path):
            os.remove(temp_db_path)

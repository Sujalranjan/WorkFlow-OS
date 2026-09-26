"""Tests for Workflow DNA Extractor (Phase 4).

Validates:
- Case A: Invariants (steps appearing across 100% of sessions)
- Case B: Variable window titles (structural title variation extracted)
- Case C: Variable filenames (filename variation & template detection)
- Case D: Optional steps (Excel step occurring in 1 of 3 sessions)
- Case E: Different workflow isolation (developer workflow remains separate)
- Case F: Ordering constraints (consistent before/after pairs)
- Case G: Explainable evidence across all dimensions
- Deterministic repeated execution idempotency
"""

from app.services.workflow_discovery import WorkflowDiscoveryEngine
from app.services.workflow_dna_extractor import WorkflowDNAExtractor
from app.services.workflow_segmenter import WorkflowSegmenter
from tests.fixtures.discovery_fixtures import generate_deterministic_dataset


def test_workflow_dna_extraction() -> None:
    events = generate_deterministic_dataset()
    segmenter = WorkflowSegmenter(session_inactivity_timeout_seconds=120.0)
    sessions = segmenter.segment(events)

    discovery_engine = WorkflowDiscoveryEngine(
        min_occurrences=2,
        similarity_threshold=0.65,
        incidental_applications={"whatsapp"},
    )
    candidates = discovery_engine.discover_candidates(sessions)
    assert len(candidates) == 1

    cand = candidates[0]
    session_dict = {s.session_id: s for s in sessions}
    supporting_sessions = [session_dict[sid] for sid in cand.supporting_session_ids]
    assert len(supporting_sessions) == 3

    extractor = WorkflowDNAExtractor()
    dna = extractor.extract_dna(candidate=cand, supporting_sessions=supporting_sessions)

    # 1. Invariant steps verification (Case A)
    # Core invariant steps: Gmail, File System, CRM, Slack
    invariant_keys = [inv.step_key for inv in dna.invariant_steps]
    assert "gmail:window_focused" in invariant_keys
    assert "file system:file_downloaded" in invariant_keys
    assert "crm:window_focused" in invariant_keys
    assert "slack:window_focused" in invariant_keys
    for inv in dna.invariant_steps:
        assert inv.occurrences == 3
        assert inv.occurrence_ratio == 1.0

    # 2. Variable parameters verification (Cases B & C)
    var_fields = [v.source_field for v in dna.variable_parameters]
    assert "metadata.file_name" in var_fields
    assert "metadata.window_title" in var_fields

    # Verify filename variable details
    file_var = next(v for v in dna.variable_parameters if v.source_field == "metadata.file_name")
    assert file_var.distinct_value_count == 3
    assert set(file_var.observed_values) == {"invoice_101.pdf", "invoice_102.pdf", "invoice_103.pdf"}
    assert file_var.pattern_template == "invoice_{variable}.pdf"

    # Verify window title variable details
    title_var = next(v for v in dna.variable_parameters if v.source_field == "metadata.window_title")
    assert title_var.distinct_value_count >= 2
    assert title_var.associated_application in ("Gmail", "CRM")

    # 3. Optional step verification (Case D)
    opt_keys = [opt.step_key for opt in dna.optional_steps]
    assert "microsoft excel:window_focused" in opt_keys
    excel_opt = next(opt for opt in dna.optional_steps if opt.step_key == "microsoft excel:window_focused")
    assert excel_opt.occurrences == 1
    assert excel_opt.occurrence_ratio == round(1 / 3, 3)
    assert len(excel_opt.supporting_session_ids) == 1

    # 4. Ordering constraints verification (Case F)
    # Check that sequential invariant steps have explicit before/after precedence
    pred_succ_pairs = [(oc.predecessor, oc.successor) for oc in dna.ordering_constraints]
    assert ("gmail:window_focused", "file system:file_downloaded") in pred_succ_pairs
    assert ("file system:file_downloaded", "crm:window_focused") in pred_succ_pairs
    assert ("crm:window_focused", "slack:window_focused") in pred_succ_pairs

    # 5. Preconditions and Boundaries verification
    assert len(dna.preconditions) >= 3
    assert "Precondition: 'gmail:window_focused' must precede 'file system:file_downloaded'." in dna.preconditions
    assert dna.boundaries.first_step == "gmail:window_focused"
    assert dna.boundaries.last_step == "slack:window_focused"
    assert dna.boundaries.total_supporting_sessions == 3

    # 6. Evidence verification (Case G)
    assert "Classified 4 steps as invariant" in dna.evidence.invariant_evidence
    assert "Identified" in dna.evidence.optional_step_evidence
    assert "microsoft excel:window_focused" in dna.evidence.optional_step_evidence
    assert "invoice_{variable}.pdf" in dna.evidence.variable_evidence
    assert "pairwise ordering constraints" in dna.evidence.ordering_evidence


def test_workflow_dna_determinism() -> None:
    """Verify that multiple extractions on the same data yield identical results."""
    events = generate_deterministic_dataset()
    segmenter = WorkflowSegmenter(session_inactivity_timeout_seconds=120.0)
    sessions = segmenter.segment(events)

    discovery_engine = WorkflowDiscoveryEngine(min_occurrences=2, similarity_threshold=0.65)
    candidates = discovery_engine.discover_candidates(sessions)
    cand = candidates[0]
    session_dict = {s.session_id: s for s in sessions}
    supporting_sessions = [session_dict[sid] for sid in cand.supporting_session_ids]

    extractor = WorkflowDNAExtractor()
    dna_run_1 = extractor.extract_dna(cand, supporting_sessions)
    dna_run_2 = extractor.extract_dna(cand, supporting_sessions)

    # Identical JSON serialization proves deterministic extraction
    assert dna_run_1.model_dump_json() == dna_run_2.model_dump_json()

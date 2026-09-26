"""Comprehensive tests for Semantic Understanding & Intent Translation (Phase 5).

Verifies:
1. Canonical SemanticWorkflow Pydantic validation.
2. Valid MockSemanticProvider generation.
3. Unknown DNA step rejection in validation layer.
4. Unknown variable rejection in validation layer.
5. Application mismatch rejection in validation layer.
6. Ordering contradiction rejection in validation layer.
7. Provider unavailable graceful fallback handling.
8. Missing Gemini API key fallback handling.
9. Deterministic WorkflowDNA remaining completely unchanged after semantic interpretation.
10. Optional live Gemini integration test if GEMINI_API_KEY is configured.
"""

import os
import pytest
from app.models.semantic import SemanticWorkflow
from app.services.semantic_engine import SemanticUnderstandingEngine
from app.services.semantic_provider import (
    GeminiSemanticProvider,
    MockSemanticProvider,
    ProviderUnavailableError,
)
from app.services.semantic_validator import SemanticWorkflowValidator
from app.services.workflow_discovery import WorkflowDiscoveryEngine
from app.services.workflow_dna_extractor import WorkflowDNAExtractor
from app.services.workflow_segmenter import WorkflowSegmenter
from tests.fixtures.discovery_fixtures import generate_deterministic_dataset


@pytest.fixture
def sample_workflow_dna():
    """Generates a sample deterministic WorkflowDNA for tests."""
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
    return extractor.extract_dna(candidates[0], supporting)


def test_valid_semantic_interpretation(sample_workflow_dna) -> None:
    """Test standard valid interpretation generation and validation."""
    mock_provider = MockSemanticProvider(mode="valid")
    engine = SemanticUnderstandingEngine(provider=mock_provider)

    resp = engine.interpret_dna(sample_workflow_dna)

    assert resp.status == "success"
    assert resp.validation_passed is True
    assert resp.semantic_workflow is not None
    assert resp.semantic_workflow.title == "Customer Replacement Request Processing"
    assert "replacement" in resp.semantic_workflow.intent.lower()

    # Step validation
    assert len(resp.semantic_workflow.semantic_steps) == len(sample_workflow_dna.invariant_steps)
    step_keys = [s.source_dna_step_key for s in resp.semantic_workflow.semantic_steps]
    assert "gmail:window_focused" in step_keys
    assert "file system:file_downloaded" in step_keys
    assert "crm:window_focused" in step_keys
    assert "slack:window_focused" in step_keys

    # Variable validation
    assert len(resp.semantic_workflow.semantic_variables) >= 2
    var_names = [v.semantic_name for v in resp.semantic_workflow.semantic_variables]
    assert "customer_name" in var_names
    assert "invoice_document" in var_names

    # Explicit confidence label (LLM estimate)
    cust_var = next(v for v in resp.semantic_workflow.semantic_variables if v.semantic_name == "customer_name")
    assert cust_var.model_interpretation_confidence == 0.92
    assert "window_title_variable" in cust_var.source_parameter


def test_unknown_dna_step_rejection(sample_workflow_dna) -> None:
    """Validator must reject hallucinated or invented DNA step keys."""
    mock_provider = MockSemanticProvider(mode="invalid_step")
    validator = SemanticWorkflowValidator()

    raw_payload = mock_provider.interpret_workflow_dna(sample_workflow_dna)
    is_valid, errors = validator.validate(raw_payload, sample_workflow_dna)

    assert is_valid is False
    assert any("does not exist in WorkflowDNA" in err for err in errors)


def test_unknown_variable_rejection(sample_workflow_dna) -> None:
    """Validator must reject hallucinated or unobserved variable parameters."""
    mock_provider = MockSemanticProvider(mode="invalid_variable")
    validator = SemanticWorkflowValidator()

    raw_payload = mock_provider.interpret_workflow_dna(sample_workflow_dna)
    is_valid, errors = validator.validate(raw_payload, sample_workflow_dna)

    assert is_valid is False
    assert any("does not exist in WorkflowDNA variable parameters" in err for err in errors)


def test_application_mismatch_rejection(sample_workflow_dna) -> None:
    """Validator must reject application mismatches against underlying DNA step."""
    mock_provider = MockSemanticProvider(mode="app_mismatch")
    validator = SemanticWorkflowValidator()

    raw_payload = mock_provider.interpret_workflow_dna(sample_workflow_dna)
    is_valid, errors = validator.validate(raw_payload, sample_workflow_dna)

    assert is_valid is False
    assert any("Application mismatch" in err or "does not exist in source DNA" in err for err in errors)


def test_ordering_contradiction_rejection(sample_workflow_dna) -> None:
    """Validator must reject semantic step sequences that contradict DNA ordering constraints."""
    mock_provider = MockSemanticProvider(mode="ordering_contradiction")
    validator = SemanticWorkflowValidator()

    raw_payload = mock_provider.interpret_workflow_dna(sample_workflow_dna)
    is_valid, errors = validator.validate(raw_payload, sample_workflow_dna)

    assert is_valid is False
    assert any("Ordering contradiction" in err for err in errors)


def test_provider_unavailable_fallback(sample_workflow_dna) -> None:
    """Engine must gracefully fall back without crashing if the LLM provider fails."""
    mock_provider = MockSemanticProvider(mode="unavailable")
    engine = SemanticUnderstandingEngine(provider=mock_provider)

    resp = engine.interpret_dna(sample_workflow_dna)

    assert resp.status == "fallback"
    assert resp.semantic_workflow is None
    assert resp.validation_passed is False
    assert "unavailable" in resp.message.lower()
    # Deterministic DNA must still be intact in the response
    assert resp.source_dna.dna_id == sample_workflow_dna.dna_id


def test_missing_gemini_api_key_fallback(sample_workflow_dna) -> None:
    """GeminiSemanticProvider must raise ProviderUnavailableError and fall back if API key is missing."""
    gemini_provider = GeminiSemanticProvider(api_key="")
    engine = SemanticUnderstandingEngine(provider=gemini_provider)

    resp = engine.interpret_dna(sample_workflow_dna)

    assert resp.status == "fallback"
    assert resp.semantic_workflow is None
    assert "api key" in resp.message.lower()


def test_dna_immutability_after_interpretation(sample_workflow_dna) -> None:
    """Deterministic WorkflowDNA must remain completely unchanged after semantic interpretation."""
    dna_json_before = sample_workflow_dna.model_dump_json()

    mock_provider = MockSemanticProvider(mode="valid")
    engine = SemanticUnderstandingEngine(provider=mock_provider)
    resp = engine.interpret_dna(sample_workflow_dna)

    assert resp.status == "success"
    dna_json_after = sample_workflow_dna.model_dump_json()

    assert dna_json_before == dna_json_after


@pytest.mark.skipif(not os.getenv("GEMINI_API_KEY"), reason="Requires live GEMINI_API_KEY in environment")
def test_live_gemini_provider_integration(sample_workflow_dna) -> None:
    """Optional live integration test with real Google Gemini API."""
    gemini_provider = GeminiSemanticProvider()
    engine = SemanticUnderstandingEngine(provider=gemini_provider)

    resp = engine.interpret_dna(sample_workflow_dna)

    assert resp.status == "success"
    assert resp.validation_passed is True
    assert resp.semantic_workflow is not None
    assert len(resp.semantic_workflow.title) > 5
    assert len(resp.semantic_workflow.semantic_steps) >= 3

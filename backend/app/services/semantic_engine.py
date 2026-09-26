"""Semantic Understanding Engine (Phase 5).

Coordinates LLM semantic interpretation, deterministic ground truth validation,
caching, and safe fallback handling when the LLM provider is unavailable.
"""

import logging
from typing import Dict, List, Optional
from app.models.dna import WorkflowDNA
from app.models.semantic import InterpretationResponse, SemanticWorkflow
from app.services.semantic_provider import (
    GeminiSemanticProvider,
    MockSemanticProvider,
    ProviderUnavailableError,
    SemanticModelProvider,
)
from app.services.semantic_validator import SemanticWorkflowValidator

logger = logging.getLogger(__name__)


class SemanticUnderstandingEngine:
    """Orchestrates deterministic WorkflowDNA interpretation into validated SemanticWorkflow."""

    def __init__(
        self,
        provider: Optional[SemanticModelProvider] = None,
        validator: Optional[SemanticWorkflowValidator] = None,
    ) -> None:
        self.provider = provider or GeminiSemanticProvider()
        self.validator = validator or SemanticWorkflowValidator()
        # In-memory storage for generated semantic workflows
        self._semantic_store: Dict[str, SemanticWorkflow] = {}
        # Mapping from dna_id to semantic_workflow_id
        self._dna_to_semantic_map: Dict[str, str] = {}

    def set_provider(self, provider: SemanticModelProvider) -> None:
        """Allow runtime switching of providers (e.g. for testing)."""
        self.provider = provider

    def get_interpretation_by_id(self, semantic_workflow_id: str) -> Optional[SemanticWorkflow]:
        """Retrieve a previously validated SemanticWorkflow by its ID."""
        return self._semantic_store.get(semantic_workflow_id)

    def get_interpretation_by_dna_id(self, dna_id: str) -> Optional[SemanticWorkflow]:
        """Retrieve a cached SemanticWorkflow by source DNA ID."""
        sem_id = self._dna_to_semantic_map.get(dna_id)
        if sem_id:
            return self._semantic_store.get(sem_id)
        return None

    def interpret_dna(
        self,
        dna: WorkflowDNA,
        force_refresh: bool = False,
    ) -> InterpretationResponse:
        """Translate a WorkflowDNA into a validated SemanticWorkflow.

        Implements safe fallback: if the LLM provider is unavailable or validation
        fails, the system continues functioning safely without crashing.
        """
        # Check cache if not forcing refresh
        if not force_refresh:
            cached = self.get_interpretation_by_dna_id(dna.dna_id)
            if cached:
                return InterpretationResponse(
                    status="success",
                    semantic_workflow=cached,
                    source_dna=dna,
                    message="Retrieved cached validated semantic workflow interpretation.",
                    validation_passed=True,
                    validation_errors=[],
                )

        # 1. Call LLM Provider
        try:
            raw_payload = self.provider.interpret_workflow_dna(dna)
        except ProviderUnavailableError as p_err:
            logger.warning(f"Semantic interpretation provider unavailable for DNA '{dna.dna_id}': {p_err}")
            return InterpretationResponse(
                status="fallback",
                semantic_workflow=None,
                source_dna=dna,
                message=f"Semantic understanding unavailable: {p_err}. Deterministic WorkflowDNA is preserved.",
                validation_passed=False,
                validation_errors=[str(p_err)],
            )
        except Exception as unk_err:
            logger.error(f"Unexpected provider error during interpretation: {unk_err}")
            return InterpretationResponse(
                status="error",
                semantic_workflow=None,
                source_dna=dna,
                message=f"An unexpected error occurred during semantic generation: {unk_err}",
                validation_passed=False,
                validation_errors=[str(unk_err)],
            )

        # 2. Deterministic Semantic Validation Layer
        is_valid, validation_errors = self.validator.validate(raw_payload, dna)
        if not is_valid:
            logger.warning(
                f"LLM semantic interpretation failed deterministic validation for DNA '{dna.dna_id}': "
                f"{validation_errors}"
            )
            return InterpretationResponse(
                status="error",
                semantic_workflow=None,
                source_dna=dna,
                message="Semantic interpretation was rejected because it contradicted deterministic WorkflowDNA facts.",
                validation_passed=False,
                validation_errors=validation_errors,
            )

        # 3. Canonical Pydantic Schema Validation
        try:
            semantic_wf = SemanticWorkflow(**raw_payload)
        except Exception as pydantic_err:
            logger.error(f"SemanticWorkflow Pydantic validation failed: {pydantic_err}")
            return InterpretationResponse(
                status="error",
                semantic_workflow=None,
                source_dna=dna,
                message=f"Model output schema validation failed: {pydantic_err}",
                validation_passed=False,
                validation_errors=[str(pydantic_err)],
            )

        # 4. Store in cache
        self._semantic_store[semantic_wf.semantic_workflow_id] = semantic_wf
        self._dna_to_semantic_map[dna.dna_id] = semantic_wf.semantic_workflow_id

        return InterpretationResponse(
            status="success",
            semantic_workflow=semantic_wf,
            source_dna=dna,
            message="Successfully extracted, interpreted, and validated semantic workflow.",
            validation_passed=True,
            validation_errors=[],
        )

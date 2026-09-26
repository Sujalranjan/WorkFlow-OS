"""Semantic Understanding API endpoints (Phase 5)."""

import os
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from app.api.dna import _generate_dna_from_events
from app.api.events import get_event_service
from app.config import GEMINI_API_KEY
from app.models.semantic import InterpretationResponse, SemanticWorkflow
from app.services.event_service import EventService
from app.services.semantic_engine import SemanticUnderstandingEngine
from app.services.semantic_provider import GeminiSemanticProvider, MockSemanticProvider

router = APIRouter(prefix="/api/workflows", tags=["Semantic Understanding"])

# Global engine instance for in-memory interpretation caching
_semantic_engine: Optional[SemanticUnderstandingEngine] = None


def get_semantic_engine() -> SemanticUnderstandingEngine:
    global _semantic_engine
    if _semantic_engine is None:
        # Default to Gemini if API key is present, otherwise Mock provider
        api_key = GEMINI_API_KEY or os.getenv("GEMINI_API_KEY")
        if api_key:
            provider = GeminiSemanticProvider(api_key=api_key)
        else:
            # If no API key is configured, default to MockSemanticProvider so the system works out-of-the-box
            provider = MockSemanticProvider()
        _semantic_engine = SemanticUnderstandingEngine(provider=provider)
    return _semantic_engine


@router.post("/{dna_id}/interpret", response_model=InterpretationResponse)
def interpret_workflow_dna_endpoint(
    dna_id: str,
    limit: int = Query(default=500, ge=1, le=2000),
    inactivity_timeout: float = Query(default=120.0, ge=5.0, le=3600.0),
    min_occurrences: int = Query(default=2, ge=2, le=50),
    similarity_threshold: float = Query(default=0.65, ge=0.4, le=1.0),
    provider_type: Optional[str] = Query(
        default=None,
        description="Optional provider override: 'gemini' or 'mock'",
    ),
    force_refresh: bool = Query(default=False),
    service: EventService = Depends(get_event_service),
    engine: SemanticUnderstandingEngine = Depends(get_semantic_engine),
) -> InterpretationResponse:
    """Translate deterministic WorkflowDNA into a validated SemanticWorkflow using an LLM."""
    dna_items = _generate_dna_from_events(
        service=service,
        limit=limit,
        inactivity_timeout=inactivity_timeout,
        min_occurrences=min_occurrences,
        similarity_threshold=similarity_threshold,
    )

    matching_dna = next((d for d in dna_items if d.dna_id == dna_id), None)
    if not matching_dna:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow DNA '{dna_id}' not found among discovered workflows.",
        )

    # Allow dynamic provider selection if requested
    if provider_type == "mock":
        engine.set_provider(MockSemanticProvider())
    elif provider_type == "gemini":
        engine.set_provider(GeminiSemanticProvider())

    return engine.interpret_dna(matching_dna, force_refresh=force_refresh)


@router.get("/semantic/{semantic_workflow_id}", response_model=SemanticWorkflow)
def get_semantic_workflow_by_id(
    semantic_workflow_id: str,
    engine: SemanticUnderstandingEngine = Depends(get_semantic_engine),
) -> SemanticWorkflow:
    """Retrieve a previously generated and validated SemanticWorkflow by its ID."""
    workflow = engine.get_interpretation_by_id(semantic_workflow_id)
    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Semantic Workflow '{semantic_workflow_id}' not found.",
        )
    return workflow

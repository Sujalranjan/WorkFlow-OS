"""Workflow DNA API endpoints (Phase 4)."""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from app.api.events import get_event_service
from app.models.dna import WorkflowDNA
from app.services.event_service import EventService
from app.services.workflow_discovery import WorkflowDiscoveryEngine
from app.services.workflow_dna_extractor import WorkflowDNAExtractor
from app.services.workflow_segmenter import WorkflowSegmenter

router = APIRouter(prefix="/api/workflows/dna", tags=["Workflow DNA"])


class WorkflowDNAListResponse(BaseModel):
    """Response containing extracted Workflow DNA items."""
    total_candidates_analyzed: int
    dna_count: int
    dna_items: List[WorkflowDNA]


def _generate_dna_from_events(
    service: EventService,
    limit: int = 500,
    inactivity_timeout: float = 120.0,
    min_occurrences: int = 2,
    similarity_threshold: float = 0.65,
) -> List[WorkflowDNA]:
    """Internal helper to segment, discover, and extract WorkflowDNA from stored events."""
    events = service.get_recent_events(limit=limit)
    if not events:
        return []

    # 1. Segment
    segmenter = WorkflowSegmenter(session_inactivity_timeout_seconds=inactivity_timeout)
    sessions = segmenter.segment(events)

    # 2. Discover candidates
    discovery_engine = WorkflowDiscoveryEngine(
        min_occurrences=min_occurrences,
        similarity_threshold=similarity_threshold,
    )
    candidates = discovery_engine.discover_candidates(sessions)

    # 3. Extract DNA for each candidate
    extractor = WorkflowDNAExtractor()
    session_dict = {s.session_id: s for s in sessions}

    dna_items: List[WorkflowDNA] = []
    for cand in candidates:
        supporting_sessions = [
            session_dict[sid] for sid in cand.supporting_session_ids if sid in session_dict
        ]
        if supporting_sessions:
            dna = extractor.extract_dna(candidate=cand, supporting_sessions=supporting_sessions)
            dna_items.append(dna)

    return dna_items


@router.get("", response_model=WorkflowDNAListResponse)
def list_workflow_dna(
    limit: int = Query(default=500, ge=1, le=2000),
    inactivity_timeout: float = Query(default=120.0, ge=5.0, le=3600.0),
    min_occurrences: int = Query(default=2, ge=2, le=50),
    similarity_threshold: float = Query(default=0.65, ge=0.4, le=1.0),
    service: EventService = Depends(get_event_service),
) -> WorkflowDNAListResponse:
    """Extract and retrieve Workflow DNA for all discovered workflow candidates."""
    dna_items = _generate_dna_from_events(
        service=service,
        limit=limit,
        inactivity_timeout=inactivity_timeout,
        min_occurrences=min_occurrences,
        similarity_threshold=similarity_threshold,
    )
    return WorkflowDNAListResponse(
        total_candidates_analyzed=len(dna_items),
        dna_count=len(dna_items),
        dna_items=dna_items,
    )


@router.get("/{dna_id}", response_model=WorkflowDNA)
def get_workflow_dna_by_id(
    dna_id: str,
    limit: int = Query(default=500, ge=1, le=2000),
    inactivity_timeout: float = Query(default=120.0, ge=5.0, le=3600.0),
    min_occurrences: int = Query(default=2, ge=2, le=50),
    similarity_threshold: float = Query(default=0.65, ge=0.4, le=1.0),
    service: EventService = Depends(get_event_service),
) -> WorkflowDNA:
    """Retrieve specific Workflow DNA by its identifier."""
    dna_items = _generate_dna_from_events(
        service=service,
        limit=limit,
        inactivity_timeout=inactivity_timeout,
        min_occurrences=min_occurrences,
        similarity_threshold=similarity_threshold,
    )
    for dna in dna_items:
        if dna.dna_id == dna_id:
            return dna
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workflow DNA '{dna_id}' not found.")

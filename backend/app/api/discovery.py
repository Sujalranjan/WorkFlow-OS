"""Workflow Discovery API endpoints."""

from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from app.api.events import get_event_service
from app.models.discovery import DiscoveryCandidate, TaskSession
from app.services.event_service import EventService
from app.services.workflow_discovery import WorkflowDiscoveryEngine
from app.services.workflow_segmenter import WorkflowSegmenter

router = APIRouter(prefix="/api/discovery", tags=["Discovery"])


class DiscoveryAnalysisResponse(BaseModel):
    """Result of running segmentation and workflow discovery over activity events."""
    total_events_analyzed: int
    total_sessions_found: int
    candidate_count: int
    sessions: List[TaskSession]
    candidates: List[DiscoveryCandidate]


@router.get("/candidates", response_model=DiscoveryAnalysisResponse)
def get_discovery_candidates(
    limit: int = Query(default=500, ge=1, le=2000),
    inactivity_timeout: float = Query(default=120.0, ge=5.0, le=3600.0),
    min_occurrences: int = Query(default=2, ge=2, le=50),
    similarity_threshold: float = Query(default=0.70, ge=0.4, le=1.0),
    service: EventService = Depends(get_event_service),
) -> DiscoveryAnalysisResponse:
    """Analyze stored activity events, segment them into task sessions, and discover recurring workflow candidates."""
    # 1. Fetch recent events from SQLite
    events = service.get_recent_events(limit=limit)

    # 2. Segment into task sessions
    segmenter = WorkflowSegmenter(session_inactivity_timeout_seconds=inactivity_timeout)
    sessions = segmenter.segment(events)

    # 3. Discover candidates
    discovery_engine = WorkflowDiscoveryEngine(
        min_occurrences=min_occurrences,
        similarity_threshold=similarity_threshold,
    )
    candidates = discovery_engine.discover_candidates(sessions)

    return DiscoveryAnalysisResponse(
        total_events_analyzed=len(events),
        total_sessions_found=len(sessions),
        candidate_count=len(candidates),
        sessions=sessions,
        candidates=candidates,
    )

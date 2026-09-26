"""Models for Workflow Segmentation and Discovery Engine (Phase 3)."""

from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field
from app.models.event import ActivityEvent


class TaskSession(BaseModel):
    """Represents a segmented block of contiguous, related user activity."""
    session_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for the segmented session",
    )
    start_time: datetime = Field(
        ...,
        description="Timestamp of the first event in the session",
    )
    end_time: datetime = Field(
        ...,
        description="Timestamp of the last event in the session",
    )
    events: List[ActivityEvent] = Field(
        default_factory=list,
        description="Chronological list of activity events belonging to this session",
    )
    applications_involved: List[str] = Field(
        default_factory=list,
        description="Deduplicated list of application names observed in this session",
    )
    event_count: int = Field(
        default=0,
        description="Total number of events in this session",
    )
    duration_seconds: float = Field(
        default=0.0,
        description="Duration of the session in seconds",
    )
    segmentation_reason: str = Field(
        ...,
        description="Explainable deterministic rule that established or demarcated this session",
    )


class NormalizedStep(BaseModel):
    """An abstract, normalized step in a discovered sequence."""
    step_index: int
    application: str
    event_type: str
    action_key: str
    is_optional: bool = False


class DiscoveryCandidate(BaseModel):
    """Structured representation of a recurring workflow candidate pattern."""
    candidate_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for the discovered candidate",
    )
    normalized_signature: str = Field(
        ...,
        description="Deterministic canonical signature (e.g. 'google chrome:window_focused -> ...')",
    )
    occurrences: int = Field(
        default=0,
        description="Number of task sessions supporting this candidate pattern",
    )
    first_seen: datetime = Field(
        ...,
        description="Earliest timestamp among supporting sessions",
    )
    last_seen: datetime = Field(
        ...,
        description="Latest timestamp among supporting sessions",
    )
    applications: List[str] = Field(
        default_factory=list,
        description="Distinct applications participating in the workflow",
    )
    event_types: List[str] = Field(
        default_factory=list,
        description="Distinct event types participating in the workflow",
    )
    representative_sequence: List[NormalizedStep] = Field(
        default_factory=list,
        description="Ordered canonical steps representing this discovered workflow candidate",
    )
    average_similarity_score: float = Field(
        default=1.0,
        description="Calculated deterministic sequence similarity score (0.0 to 1.0)",
    )
    supporting_session_ids: List[str] = Field(
        default_factory=list,
        description="IDs of all sessions matching this workflow candidate",
    )
    evidence: str = Field(
        ...,
        description="Explainable explanation detailing why this pattern was discovered",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional structured metrics for future Workflow DNA transformation",
    )

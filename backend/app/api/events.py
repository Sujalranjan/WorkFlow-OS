"""Activity Events API endpoints."""

from typing import List
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from app.config import DATABASE_PATH
from app.models.event import ActivityEvent
from app.repositories.event_repository import EventRepository
from app.services.event_service import EventService

router = APIRouter(prefix="/api/events", tags=["Events"])


def get_event_service() -> EventService:
    """Dependency injector providing an EventService configured with the database path."""
    repository = EventRepository(db_path=DATABASE_PATH)
    return EventService(repository=repository)


class EventCreateResponse(BaseModel):
    """Response returned upon successful event ingestion."""
    status: str
    message: str
    event: ActivityEvent


@router.post("", status_code=status.HTTP_201_CREATED, response_model=EventCreateResponse)
def create_event(
    event: ActivityEvent,
    service: EventService = Depends(get_event_service),
) -> EventCreateResponse:
    """Ingest a validated ActivityEvent into storage."""
    persisted_event = service.record_event(event)
    return EventCreateResponse(
        status="success",
        message="Event recorded successfully",
        event=persisted_event,
    )


@router.get("", response_model=List[ActivityEvent])
def get_recent_events(
    limit: int = Query(default=50, ge=1, le=500),
    service: EventService = Depends(get_event_service),
) -> List[ActivityEvent]:
    """Retrieve recently ingested activity events."""
    return service.get_recent_events(limit=limit)

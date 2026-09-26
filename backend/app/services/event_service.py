"""Event service handling activity event domain operations."""

from typing import List
from app.models.event import ActivityEvent
from app.repositories.event_repository import EventRepository


class EventService:
    """Business logic and orchestrator for activity events."""

    def __init__(self, repository: EventRepository | None = None) -> None:
        self.repository = repository or EventRepository()

    def record_event(self, event: ActivityEvent) -> ActivityEvent:
        """Process and persist an incoming activity event."""
        return self.repository.create(event)

    def get_recent_events(self, limit: int = 50) -> List[ActivityEvent]:
        """Retrieve recent events from the repository."""
        return self.repository.list_recent(limit=limit)

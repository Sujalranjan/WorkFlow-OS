"""Event repository: persistence for ActivityEvent entities."""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import delete, select

from app.db import Repository, activity_events
from app.models.event import ActivityEvent, ActivityEventType

_COLUMNS = (
    activity_events.c.event_id,
    activity_events.c.event_type,
    activity_events.c.timestamp,
    activity_events.c.application,
    activity_events.c.source,
    activity_events.c.metadata,
)


def _to_event(row) -> ActivityEvent:
    return ActivityEvent(
        event_id=row.event_id,
        event_type=ActivityEventType(row.event_type),
        timestamp=datetime.fromisoformat(row.timestamp),
        application=row.application,
        source=row.source,
        metadata=row.metadata,
    )


class EventRepository(Repository):
    """Manages persistence for ActivityEvent entities."""

    def create(self, event: ActivityEvent) -> ActivityEvent:
        with self.begin() as conn:
            conn.execute(
                activity_events.insert().values(
                    event_id=event.event_id,
                    event_type=event.event_type.value,
                    timestamp=event.timestamp.isoformat(),
                    application=event.application,
                    source=event.source,
                    metadata=event.metadata,
                )
            )
        return event

    def list_recent(self, limit: int = 50) -> List[ActivityEvent]:
        """Most recent events first (by timestamp, then insertion order)."""
        stmt = (
            select(*_COLUMNS)
            .order_by(activity_events.c.timestamp.desc(), activity_events.c.id.desc())
            .limit(limit)
        )
        with self.connect() as conn:
            return [_to_event(row) for row in conn.execute(stmt)]

    def get_by_id(self, event_id: str) -> Optional[ActivityEvent]:
        with self.connect() as conn:
            row = conn.execute(select(*_COLUMNS).where(activity_events.c.event_id == event_id)).first()
        return _to_event(row) if row else None

    def delete_all(self) -> int:
        with self.begin() as conn:
            return conn.execute(delete(activity_events)).rowcount

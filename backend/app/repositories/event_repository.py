"""Event repository layer with SQLite persistence."""

from contextlib import contextmanager
import json
import sqlite3
from datetime import datetime
from typing import Generator, List, Optional
from app.models.event import ActivityEvent, ActivityEventType


class EventRepository:
    """Manages SQLite persistence for ActivityEvent entities."""

    def __init__(self, db_path: str = "workflowos.db") -> None:
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Create and yield a connection with row factory support, ensuring clean closure."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Initialize database schema if it doesn't exist."""
        with self._get_connection() as conn:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS activity_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_id TEXT UNIQUE NOT NULL,
                        event_type TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        application TEXT,
                        source TEXT NOT NULL,
                        metadata TEXT NOT NULL
                    )
                    """
                )

    def create(self, event: ActivityEvent) -> ActivityEvent:
        """Insert a new ActivityEvent into SQLite."""
        with self._get_connection() as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO activity_events (event_id, event_type, timestamp, application, source, metadata)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.event_type.value,
                        event.timestamp.isoformat(),
                        event.application,
                        event.source,
                        json.dumps(event.metadata),
                    ),
                )
        return event

    def list_recent(self, limit: int = 50) -> List[ActivityEvent]:
        """Fetch recently stored activity events ordered by timestamp and insertion ID descending."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT event_id, event_type, timestamp, application, source, metadata
                FROM activity_events
                ORDER BY timestamp DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()

        events: List[ActivityEvent] = []
        for row in rows:
            events.append(
                ActivityEvent(
                    event_id=row["event_id"],
                    event_type=ActivityEventType(row["event_type"]),
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    application=row["application"],
                    source=row["source"],
                    metadata=json.loads(row["metadata"]),
                )
            )
        return events

    def get_by_id(self, event_id: str) -> Optional[ActivityEvent]:
        """Fetch an activity event by its ID."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT event_id, event_type, timestamp, application, source, metadata
                WHERE event_id = ?
                """,
                (event_id,),
            )
            row = cursor.fetchone()

        if not row:
            return None

        return ActivityEvent(
            event_id=row["event_id"],
            event_type=ActivityEventType(row["event_type"]),
            timestamp=datetime.fromisoformat(row["timestamp"]),
            application=row["application"],
            source=row["source"],
            metadata=json.loads(row["metadata"]),
        )

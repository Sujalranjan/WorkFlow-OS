"""Learning & Reliability Repository (Phase 11).

Provides SQLite persistence for WorkflowReliabilityProfile and WorkflowLearningEvent entities.
Guarantees that reliability profiles, step statistics, failure pattern intelligence,
and learning audit histories survive backend restarts.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import sqlite3
from typing import Generator, List, Optional

from app.config import DATABASE_PATH
from app.models.learning import (
    WorkflowLearningEvent,
    WorkflowReliabilityProfile,
)


class LearningRepository:
    """Manages SQLite persistence for workflow learning intelligence and reliability profiles."""

    def __init__(self, db_path: str = DATABASE_PATH) -> None:
        self.db_path = db_path
        self._memory_conn: Optional[sqlite3.Connection] = None
        if self.db_path == ":memory:":
            self._memory_conn = sqlite3.connect(":memory:")
            self._memory_conn.row_factory = sqlite3.Row
        self._init_db()

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        if self._memory_conn is not None:
            yield self._memory_conn
        else:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
            finally:
                conn.close()

    def _init_db(self) -> None:
        """Create tables for workflow reliability profiles and learning events."""
        with self._get_connection() as conn:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workflow_reliability_profiles (
                        workflow_id TEXT PRIMARY KEY,
                        profile_id TEXT NOT NULL,
                        total_executions INTEGER NOT NULL,
                        reliability_rate REAL NOT NULL,
                        computed_at TEXT NOT NULL,
                        profile_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workflow_learning_events (
                        event_id TEXT PRIMARY KEY,
                        workflow_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        event_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_levent_workflow_id
                    ON workflow_learning_events(workflow_id)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_levent_timestamp
                    ON workflow_learning_events(timestamp)
                    """
                )

    def save_profile(self, profile: WorkflowReliabilityProfile) -> WorkflowReliabilityProfile:
        """Insert or replace a WorkflowReliabilityProfile in SQLite."""
        prof_dict = profile.model_dump(mode="json")
        prof_json = json.dumps(prof_dict)

        with self._get_connection() as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO workflow_reliability_profiles (
                        workflow_id,
                        profile_id,
                        total_executions,
                        reliability_rate,
                        computed_at,
                        profile_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(workflow_id) DO UPDATE SET
                        profile_id = excluded.profile_id,
                        total_executions = excluded.total_executions,
                        reliability_rate = excluded.reliability_rate,
                        computed_at = excluded.computed_at,
                        profile_json = excluded.profile_json
                    """,
                    (
                        profile.workflow_id,
                        profile.profile_id,
                        profile.total_executions,
                        profile.reliability_rate,
                        profile.computed_at,
                        prof_json,
                    ),
                )
        return profile

    def get_profile(self, workflow_id: str) -> Optional[WorkflowReliabilityProfile]:
        """Fetch a reliability profile by workflow_id."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT profile_json FROM workflow_reliability_profiles
                WHERE workflow_id = ?
                """,
                (workflow_id,),
            )
            row = cursor.fetchone()

        if not row:
            return None

        data = json.loads(row["profile_json"])
        return WorkflowReliabilityProfile.model_validate(data)

    def save_event(self, event: WorkflowLearningEvent) -> WorkflowLearningEvent:
        """Insert a single WorkflowLearningEvent in SQLite."""
        evt_dict = event.model_dump(mode="json")
        evt_json = json.dumps(evt_dict)

        with self._get_connection() as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO workflow_learning_events (
                        event_id,
                        workflow_id,
                        event_type,
                        timestamp,
                        event_json
                    )
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(event_id) DO UPDATE SET
                        event_json = excluded.event_json
                    """,
                    (
                        event.event_id,
                        event.workflow_id,
                        event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type),
                        event.timestamp,
                        evt_json,
                    ),
                )
        return event

    def save_events(self, events: List[WorkflowLearningEvent]) -> List[WorkflowLearningEvent]:
        """Batch insert workflow learning events."""
        with self._get_connection() as conn:
            with conn:
                for event in events:
                    evt_dict = event.model_dump(mode="json")
                    evt_json = json.dumps(evt_dict)
                    conn.execute(
                        """
                        INSERT INTO workflow_learning_events (
                            event_id,
                            workflow_id,
                            event_type,
                            timestamp,
                            event_json
                        )
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(event_id) DO UPDATE SET
                            event_json = excluded.event_json
                        """,
                        (
                            event.event_id,
                            event.workflow_id,
                            event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type),
                            event.timestamp,
                            evt_json,
                        ),
                    )
        return events

    def list_events(self, workflow_id: str, limit: int = 100) -> List[WorkflowLearningEvent]:
        """Fetch all learning events for a workflow ordered by timestamp DESC."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT event_json FROM workflow_learning_events
                WHERE workflow_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (workflow_id, limit),
            )
            rows = cursor.fetchall()

        events: List[WorkflowLearningEvent] = []
        for row in rows:
            data = json.loads(row["event_json"])
            events.append(WorkflowLearningEvent.model_validate(data))
        return events

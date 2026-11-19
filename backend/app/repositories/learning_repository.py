"""Learning & Reliability Repository.

Persistence for WorkflowReliabilityProfile and WorkflowLearningEvent entities: reliability
profiles, step statistics, failure patterns and learning history.
"""

from typing import List, Optional

from sqlalchemy import delete, select

from app.db import Repository, upsert, workflow_learning_events, workflow_reliability_profiles
from app.models.learning import WorkflowLearningEvent, WorkflowReliabilityProfile


def _event_values(event: WorkflowLearningEvent) -> dict:
    return {
        "event_id": event.event_id,
        "workflow_id": event.workflow_id,
        "event_type": event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type),
        "timestamp": event.timestamp,
        "event_json": event.model_dump(mode="json"),
    }


class LearningRepository(Repository):
    """Manages persistence for workflow learning intelligence and reliability profiles."""

    def save_profile(self, profile: WorkflowReliabilityProfile) -> WorkflowReliabilityProfile:
        with self.begin() as conn:
            upsert(
                conn,
                workflow_reliability_profiles,
                {
                    "workflow_id": profile.workflow_id,
                    "profile_id": profile.profile_id,
                    "total_executions": profile.total_executions,
                    "reliability_rate": profile.reliability_rate,
                    "computed_at": profile.computed_at,
                    "profile_json": profile.model_dump(mode="json"),
                },
                key=["workflow_id"],
            )
        return profile

    def get_profile(self, workflow_id: str) -> Optional[WorkflowReliabilityProfile]:
        stmt = select(workflow_reliability_profiles.c.profile_json).where(
            workflow_reliability_profiles.c.workflow_id == workflow_id
        )
        with self.connect() as conn:
            data = conn.execute(stmt).scalar()
        return WorkflowReliabilityProfile.model_validate(data) if data else None

    def save_event(self, event: WorkflowLearningEvent) -> WorkflowLearningEvent:
        self.save_events([event])
        return event

    def save_events(self, events: List[WorkflowLearningEvent]) -> List[WorkflowLearningEvent]:
        """Insert learning events (an existing event_id only has its document replaced)."""
        with self.begin() as conn:
            for event in events:
                upsert(conn, workflow_learning_events, _event_values(event), key=["event_id"], update=["event_json"])
        return events

    def list_events(self, workflow_id: str, limit: int = 100) -> List[WorkflowLearningEvent]:
        """Learning events for a workflow, newest first."""
        stmt = (
            select(workflow_learning_events.c.event_json)
            .where(workflow_learning_events.c.workflow_id == workflow_id)
            .order_by(workflow_learning_events.c.timestamp.desc())
            .limit(limit)
        )
        with self.connect() as conn:
            return [WorkflowLearningEvent.model_validate(data) for data in conn.execute(stmt).scalars()]

    def delete_all(self) -> int:
        """Delete all profiles and events; returns the number of profiles removed."""
        with self.begin() as conn:
            conn.execute(delete(workflow_learning_events))
            return conn.execute(delete(workflow_reliability_profiles)).rowcount

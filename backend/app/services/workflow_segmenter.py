"""Deterministic Workflow Segmenter dividing ActivityEvents into TaskSessions."""

import hashlib
from datetime import datetime, timezone
from typing import List, Optional
from app.models.discovery import TaskSession
from app.models.event import ActivityEvent


class WorkflowSegmenter:
    """Segments a chronological sequence of ActivityEvents into coherent task sessions.

    Uses deterministic, explainable rules:
    1. Inactivity Timeout: If the gap between two consecutive events exceeds `session_inactivity_timeout_seconds`,
       a new session is started.
    2. Maximum Session Duration: If a session exceeds `max_session_duration_seconds`, a boundary is enforced.
    3. Minimum Session Events: Sessions with fewer than `min_session_events` can be filtered as isolated noise.
    """

    def __init__(
        self,
        session_inactivity_timeout_seconds: float = 120.0,
        max_session_duration_seconds: float = 1800.0,
        min_session_events: int = 2,
    ) -> None:
        self.session_inactivity_timeout_seconds = session_inactivity_timeout_seconds
        self.max_session_duration_seconds = max_session_duration_seconds
        self.min_session_events = min_session_events

    def segment(self, events: List[ActivityEvent]) -> List[TaskSession]:
        """Segment a list of ActivityEvents into TaskSession instances.

        Events are automatically sorted chronologically by timestamp before segmentation.
        """
        if not events:
            return []

        sorted_events = sorted(events, key=lambda e: e.timestamp)
        sessions: List[TaskSession] = []

        current_events: List[ActivityEvent] = [sorted_events[0]]
        current_reason = "Initial activity window started."

        for i in range(1, len(sorted_events)):
            prev_event = sorted_events[i - 1]
            curr_event = sorted_events[i]

            gap_seconds = (curr_event.timestamp - prev_event.timestamp).total_seconds()
            session_duration = (curr_event.timestamp - current_events[0].timestamp).total_seconds()

            # Rule 1: Inactivity timeout boundary
            if gap_seconds > self.session_inactivity_timeout_seconds:
                sessions.append(
                    self._create_session(
                        current_events,
                        segmentation_reason=f"Session closed due to inactivity gap of {gap_seconds:.1f}s (threshold: {self.session_inactivity_timeout_seconds:.1f}s).",
                    )
                )
                current_events = [curr_event]
                current_reason = f"New session started following {gap_seconds:.1f}s inactivity."
                continue

            # Rule 2: Maximum duration threshold
            if session_duration > self.max_session_duration_seconds:
                sessions.append(
                    self._create_session(
                        current_events,
                        segmentation_reason=f"Session closed after reaching maximum duration threshold of {self.max_session_duration_seconds:.1f}s.",
                    )
                )
                current_events = [curr_event]
                current_reason = "New session started following max duration boundary."
                continue

            # Normal continuation
            current_events.append(curr_event)

        # Flush final session
        if current_events:
            sessions.append(
                self._create_session(
                    current_events,
                    segmentation_reason="Session bounded by end of observed activity stream.",
                )
            )

        # Filter out sessions that do not meet the minimum event requirement
        return [s for s in sessions if s.event_count >= self.min_session_events]

    def _create_session(self, events: List[ActivityEvent], segmentation_reason: str) -> TaskSession:
        start_time = events[0].timestamp
        end_time = events[-1].timestamp
        duration = max(0.0, (end_time - start_time).total_seconds())

        apps = []
        for e in events:
            if e.application and e.application not in apps:
                apps.append(e.application)

        sess_hash = hashlib.sha256(
            f"{start_time.isoformat()}_{end_time.isoformat()}_{len(events)}".encode()
        ).hexdigest()[:12]
        sess_id = f"sess-{sess_hash}"

        return TaskSession(
            session_id=sess_id,
            start_time=start_time,
            end_time=end_time,
            events=events,
            applications_involved=apps,
            event_count=len(events),
            duration_seconds=duration,
            segmentation_reason=segmentation_reason,
        )

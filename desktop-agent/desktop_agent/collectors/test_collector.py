"""TestActivityCollector for deterministic event generation during unit tests."""

from typing import Any, Dict, Optional
from desktop_agent.collectors.base import BaseCollector, EventCallback
from desktop_agent.models.event import ActivityEvent, ActivityEventType


class TestActivityCollector(BaseCollector):
    """Produces structured ActivityEvents deterministically for tests (maintains Phase 1 collector API)."""

    __test__ = False

    def __init__(self, callback: Optional[EventCallback] = None, source_name: str = "desktop_agent") -> None:
        super().__init__(callback=callback, source_name=source_name)

    def start(self) -> None:
        self._is_running = True

    def stop(self) -> None:
        self._is_running = False

    def create_event(
        self,
        event_type: ActivityEventType | str,
        application: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        source: Optional[str] = None,
    ) -> ActivityEvent:
        """Create a validated ActivityEvent and optionally emit to callback."""
        if isinstance(event_type, str):
            event_type = ActivityEventType(event_type)

        event = ActivityEvent(
            event_type=event_type,
            application=application,
            source=source or self.source_name,
            metadata=metadata or {},
        )
        if self._is_running and self.callback:
            self.emit(event)
        return event

    def generate_application_opened(
        self, application: str, metadata: Optional[Dict[str, Any]] = None
    ) -> ActivityEvent:
        """Convenience generator for application_opened event."""
        return self.create_event(
            event_type=ActivityEventType.APPLICATION_OPENED,
            application=application,
            metadata=metadata or {},
        )

    def generate_file_downloaded(
        self, file_name: str, application: str = "Chrome", metadata: Optional[Dict[str, Any]] = None
    ) -> ActivityEvent:
        """Convenience generator for file_downloaded event."""
        meta = {"file_name": file_name}
        if metadata:
            meta.update(metadata)
        return self.create_event(
            event_type=ActivityEventType.FILE_DOWNLOADED,
            application=application,
            metadata=meta,
        )


# Backward compatibility alias
ActivityCollector = TestActivityCollector

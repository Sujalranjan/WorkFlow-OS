"""Base collector interface for WorkFlowOS desktop activity collection."""

from abc import ABC, abstractmethod
from typing import Callable, Optional
from desktop_agent.models.event import ActivityEvent

# Callback type for emitting events directly into an agent or queue
EventCallback = Callable[[ActivityEvent], None]


class BaseCollector(ABC):
    """Abstract base class for all activity collectors."""

    def __init__(self, callback: Optional[EventCallback] = None, source_name: str = "desktop_agent") -> None:
        self.callback = callback
        self.source_name = source_name
        self._is_running = False

    @property
    def is_running(self) -> bool:
        """Return whether collector is actively running."""
        return self._is_running

    def set_callback(self, callback: EventCallback) -> None:
        """Set or update the callback for emitted events."""
        self.callback = callback

    def emit(self, event: ActivityEvent) -> None:
        """Emit an activity event to the configured callback if present."""
        if self.callback:
            self.callback(event)

    @abstractmethod
    def start(self) -> None:
        """Start the collector."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Stop the collector and release all system resources."""
        pass

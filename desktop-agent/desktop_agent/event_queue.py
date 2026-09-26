"""Local in-memory FIFO event queue for Desktop Activity Agent."""

from collections import deque
from threading import Lock
from typing import List, Optional
from desktop_agent.models.event import ActivityEvent


class EventQueue:
    """Thread-safe FIFO queue storing ActivityEvents before dispatching."""

    def __init__(self, maxsize: Optional[int] = None) -> None:
        self._queue: deque[ActivityEvent] = deque(maxlen=maxsize)
        self._lock = Lock()

    def enqueue(self, event: ActivityEvent) -> None:
        """Add an activity event to the queue."""
        with self._lock:
            self._queue.append(event)

    def dequeue(self) -> Optional[ActivityEvent]:
        """Retrieve and remove the oldest event from the queue. Returns None if empty."""
        with self._lock:
            if self._queue:
                return self._queue.popleft()
            return None

    def peek(self) -> Optional[ActivityEvent]:
        """View the next event without removing it."""
        with self._lock:
            if self._queue:
                return self._queue[0]
            return None

    def size(self) -> int:
        """Return current count of items in the queue."""
        with self._lock:
            return len(self._queue)

    def is_empty(self) -> bool:
        """Check if queue is empty."""
        with self._lock:
            return len(self._queue) == 0

    def drain(self, limit: Optional[int] = None) -> List[ActivityEvent]:
        """Drain up to `limit` events in FIFO order."""
        with self._lock:
            drained: List[ActivityEvent] = []
            count = 0
            while self._queue and (limit is None or count < limit):
                drained.append(self._queue.popleft())
                count += 1
            return drained

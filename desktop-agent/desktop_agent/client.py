"""HTTP client for dispatching activity events to WorkFlowOS backend."""

import os
import time
from typing import Any, Dict, Optional
import requests
from desktop_agent.models.event import ActivityEvent


class BackendClient:
    """Client for sending activity events to the WorkFlowOS backend."""

    def __init__(self, backend_url: Optional[str] = None, timeout: float = 5.0) -> None:
        raw_url = backend_url or os.getenv("BACKEND_API_URL") or os.getenv("BACKEND_URL") or "http://127.0.0.1:8000"
        self.backend_url = raw_url.rstrip("/")
        self.events_endpoint = f"{self.backend_url}/api/events"
        self.timeout = timeout

    def send_event(self, event: ActivityEvent, retries: int = 2, backoff_factor: float = 0.5) -> Dict[str, Any]:
        """Send an ActivityEvent to POST /api/events with basic retry logic."""
        payload = event.model_dump(mode="json")
        last_error: Optional[Exception] = None

        for attempt in range(retries + 1):
            try:
                response = requests.post(
                    self.events_endpoint,
                    json=payload,
                    timeout=self.timeout,
                    headers={"Content-Type": "application/json"},
                )
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, Exception) as exc:
                last_error = exc
                if attempt < retries:
                    time.sleep(backoff_factor * (2**attempt))
                else:
                    raise RuntimeError(
                        f"Failed to deliver event {event.event_id} to {self.events_endpoint} after {retries + 1} attempts: {exc}"
                    ) from last_error
        raise RuntimeError("Unexpected failure in send_event")

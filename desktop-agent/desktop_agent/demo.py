"""Demonstration script: Run DesktopAgent event generation, queuing, backend ingestion, and verification."""

import os
import sys
import time
from desktop_agent.agent import DesktopAgent
from desktop_agent.client import BackendClient


def run_demo() -> None:
    """Execute end-to-end event flow."""
    backend_url = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000")
    print(f"=== WorkFlowOS Phase 1 Event Pipeline Demo ===")
    print(f"Target Backend: {backend_url}")

    agent = DesktopAgent(backend_url=backend_url)
    status = agent.start()
    print(f"[{agent.name}] Status: {status['status']}")

    # 1. Create simulated workflow events (e.g. Gmail -> Download Attachment -> CRM)
    print("\n1. Generating structured activity events...")
    e1 = agent.collector.generate_application_opened(
        application="Google Chrome",
        metadata={"url": "https://mail.google.com", "tab_title": "Inbox (1 unread) - Operations"},
    )
    e2 = agent.collector.generate_file_downloaded(
        file_name="customer_quote_request_482.pdf",
        application="Google Chrome",
        metadata={"size_bytes": 1048576, "download_path": "C:\\Users\\User\\Downloads"},
    )
    e3 = agent.collector.generate_application_opened(
        application="CRM Client",
        metadata={"view": "CustomerSearch", "query": "Acme Corp"},
    )

    # 2. Enqueue events
    print("2. Enqueueing events to local FIFO queue...")
    agent.record_activity(e1)
    agent.record_activity(e2)
    agent.record_activity(e3)
    print(f"Local queue populated. Current queue depth: {agent.queue.size()}")

    # 3. Dispatch events to backend
    print("3. Dispatching events to backend POST /api/events...")
    dispatched = agent.dispatch_all()
    print(f"Dispatched {len(dispatched)} events successfully!")
    print(f"Queue depth after dispatch: {agent.queue.size()}")

    for item in dispatched:
        evt = item.get("event", {})
        print(f" -> Recorded {evt.get('event_type')} (ID: {evt.get('event_id')})")

    print("\nDemo completed successfully. View the frontend to inspect real-time events.")


if __name__ == "__main__":
    run_demo()

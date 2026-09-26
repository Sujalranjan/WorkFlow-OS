"""End-to-End integration test: Desktop Agent -> Event Queue -> Backend Ingestion -> Storage -> Retrieval."""

import os
import tempfile
from fastapi.testclient import TestClient
from app.api.events import get_event_service
from app.main import app
from app.repositories.event_repository import EventRepository
from app.services.event_service import EventService
from desktop_agent.agent import DesktopAgent


def test_end_to_end_pipeline() -> None:
    """Verify end-to-end ingestion from DesktopAgent through SQLite storage to GET /api/events."""
    temp_dir = tempfile.mkdtemp()
    test_db_path = os.path.join(temp_dir, "test_e2e.db")

    try:
        # 1. Setup backend test instance with isolated database
        repo = EventRepository(db_path=test_db_path)
        service = EventService(repository=repo)
        app.dependency_overrides[get_event_service] = lambda: service
        test_client = TestClient(app)

        # 2. Desktop agent creates ActivityEvents
        agent = DesktopAgent()
        event1 = agent.collector.generate_application_opened(
            application="Chrome",
            metadata={"title": "Gmail - Inbox", "tab_url": "https://mail.google.com"},
        )
        event2 = agent.collector.generate_file_downloaded(
            file_name="customer_request.pdf",
            application="Chrome",
            metadata={"size_bytes": 1048576},
        )

        # 3. Events placed in the local queue
        agent.record_activity(event1)
        agent.record_activity(event2)
        assert agent.queue.size() == 2

        # 4. Events dispatched to backend via API in FIFO order
        while not agent.queue.is_empty():
            evt = agent.queue.dequeue()
            assert evt is not None
            resp = test_client.post("/api/events", json=evt.model_dump(mode="json"))
            assert resp.status_code == 201
            assert resp.json()["status"] == "success"

        # 5. Verify backend storage contains both events and GET /api/events returns them in order
        get_resp = test_client.get("/api/events")
        assert get_resp.status_code == 200
        events_retrieved = get_resp.json()

        assert len(events_retrieved) == 2
        # Most recent first
        assert events_retrieved[0]["event_type"] == "file_downloaded"
        assert events_retrieved[0]["metadata"]["file_name"] == "customer_request.pdf"
        assert events_retrieved[1]["event_type"] == "application_opened"
        assert events_retrieved[1]["application"] == "Chrome"

    finally:
        app.dependency_overrides.clear()
        if os.path.exists(test_db_path):
            try:
                os.remove(test_db_path)
                os.rmdir(temp_dir)
            except OSError:
                pass

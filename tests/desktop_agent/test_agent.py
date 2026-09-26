"""Tests for the desktop-agent collector, queue, and client."""

from unittest.mock import MagicMock, patch
from desktop_agent.agent import DesktopAgent, main
from desktop_agent.collector import ActivityCollector
from desktop_agent.models.event import ActivityEvent, ActivityEventType
from desktop_agent.event_queue import EventQueue


def test_desktop_agent_initialization() -> None:
    """Verify that DesktopAgent initializes with expected defaults."""
    agent = DesktopAgent()
    assert agent.name == "WorkFlowOS-Desktop-Agent"
    assert agent.is_running is False
    assert agent.queue.is_empty() is True


def test_desktop_agent_start() -> None:
    """Verify that DesktopAgent start returns expected status dictionary."""
    agent = DesktopAgent()
    result = agent.start()
    assert agent.is_running is True
    assert result["status"] == "started"
    assert result["name"] == "WorkFlowOS-Desktop-Agent"


def test_desktop_agent_stop() -> None:
    """Verify that DesktopAgent stop cleanly halts the agent."""
    agent = DesktopAgent()
    agent.start()
    result = agent.stop()
    assert agent.is_running is False
    assert result["status"] == "stopped"


def test_desktop_agent_main_entrypoint() -> None:
    """Verify that the CLI main entrypoint initializes and stops cleanly."""
    with patch("time.sleep", side_effect=KeyboardInterrupt):
        exit_code = main()
        assert exit_code == 0


def test_activity_collector_creation() -> None:
    """Verify that ActivityCollector produces valid structured events."""
    collector = ActivityCollector(source_name="test_source")
    event1 = collector.generate_application_opened("Chrome", metadata={"url": "https://mail.google.com"})
    assert event1.event_type == ActivityEventType.APPLICATION_OPENED
    assert event1.application == "Chrome"
    assert event1.source == "test_source"
    assert event1.metadata["url"] == "https://mail.google.com"

    event2 = collector.generate_file_downloaded("customer_request.pdf")
    assert event2.event_type == ActivityEventType.FILE_DOWNLOADED
    assert event2.metadata["file_name"] == "customer_request.pdf"


def test_event_queue_ordering_and_drain() -> None:
    """Verify FIFO ordering and drain behavior in EventQueue."""
    queue = EventQueue()
    assert queue.is_empty() is True

    collector = ActivityCollector()
    evt1 = collector.generate_application_opened("Chrome")
    evt2 = collector.generate_file_downloaded("invoice.pdf")

    queue.enqueue(evt1)
    queue.enqueue(evt2)
    assert queue.size() == 2

    assert queue.peek() == evt1
    popped1 = queue.dequeue()
    assert popped1 == evt1
    assert queue.size() == 1

    popped2 = queue.dequeue()
    assert popped2 == evt2
    assert queue.is_empty() is True


def test_agent_dispatch() -> None:
    """Verify DesktopAgent dispatching queued events using mock client."""
    agent = DesktopAgent()
    evt = agent.collector.generate_application_opened("CRM")
    agent.record_activity(evt)

    mock_response = {"status": "success", "event": evt.model_dump(mode="json")}
    with patch.object(agent.client, "send_event", return_value=mock_response) as mock_send:
        result = agent.dispatch_next()
        assert result == mock_response
        mock_send.assert_called_once_with(evt)
        assert agent.queue.is_empty() is True

"""Tests for Phase 2 collectors: BaseCollector, WindowsWindowCollector, and FileSystemCollector."""

import os
import shutil
import tempfile
import time
from unittest.mock import MagicMock, patch
from desktop_agent.collectors.base import BaseCollector
from desktop_agent.collectors.file_collector import FileActivityHandler, FileSystemCollector
from desktop_agent.collectors.test_collector import TestActivityCollector
from desktop_agent.collectors.window_collector import WindowsWindowCollector
from desktop_agent.models.event import ActivityEvent, ActivityEventType


def test_base_collector_interface() -> None:
    """Verify BaseCollector start, stop, emit, and callback setting."""
    events = []
    collector = TestActivityCollector(callback=lambda e: events.append(e))
    assert collector.is_running is False

    collector.start()
    assert collector.is_running is True

    evt = collector.generate_application_opened("Chrome")
    assert len(events) == 1
    assert events[0].event_type == ActivityEventType.APPLICATION_OPENED

    collector.stop()
    assert collector.is_running is False


def test_window_name_normalization() -> None:
    """Verify application executable name normalization."""
    assert WindowsWindowCollector.normalize_app_name("chrome.exe") == "Google Chrome"
    assert WindowsWindowCollector.normalize_app_name("msedge.exe") == "Microsoft Edge"
    assert WindowsWindowCollector.normalize_app_name("code.exe") == "Visual Studio Code"
    assert WindowsWindowCollector.normalize_app_name("explorer.exe") == "File Explorer"
    assert WindowsWindowCollector.normalize_app_name("notepad.exe") == "Notepad"
    assert WindowsWindowCollector.normalize_app_name("custom_app.exe") == "custom_app.exe"


def test_window_deduplication_and_debounce() -> None:
    """Verify that identical consecutive window states are deduplicated and debounced."""
    collector = WindowsWindowCollector(poll_interval=0.1, debounce_seconds=0.2)

    # 1. First event should be allowed
    t0 = 1000.0
    assert collector.should_emit_event("Google Chrome", "Inbox", t0) is True
    collector._last_state = ("Google Chrome", "Inbox")
    collector._last_event_time = t0

    # 2. Identical state at t0 + 0.1s should be deduplicated
    assert collector.should_emit_event("Google Chrome", "Inbox", t0 + 0.1) is False

    # 3. Changed state before debounce window (e.g. t0 + 0.1s < 0.2s) should be debounced
    assert collector.should_emit_event("Slack", "General", t0 + 0.1) is False

    # 4. Changed state after debounce window (t0 + 0.25s) should be allowed
    assert collector.should_emit_event("Slack", "General", t0 + 0.25) is True


def test_window_collector_startup_and_clean_shutdown() -> None:
    """Verify WindowsWindowCollector starts thread and stops cleanly."""
    collector = WindowsWindowCollector(poll_interval=0.05)
    assert collector.is_running is False

    # Mock get_foreground_window_info to avoid OS dependency in unit test
    with patch.object(collector, "get_foreground_window_info", return_value=("Google Chrome", "Inbox")):
        events = []
        collector.set_callback(lambda e: events.append(e))
        collector.start()
        assert collector.is_running is True
        time.sleep(0.15)
        collector.stop()
        assert collector.is_running is False
        assert collector._thread is None
        assert len(events) >= 1
        assert events[0].application == "Google Chrome"


def test_file_activity_handler_event_translation() -> None:
    """Verify file creation and move translation to ActivityEvents."""
    events = []
    temp_dir = tempfile.mkdtemp()
    try:
        collector = FileSystemCollector(watch_directory=temp_dir, callback=lambda e: events.append(e))
        handler = FileActivityHandler(collector)

        # Mock FileSystemEvent for created file
        mock_create = MagicMock()
        mock_create.is_directory = False
        mock_create.src_path = os.path.join(temp_dir, "customer_request.pdf")
        handler.on_created(mock_create)

        assert len(events) == 1
        assert events[0].event_type == ActivityEventType.FILE_CREATED
        assert events[0].metadata["file_name"] == "customer_request.pdf"

        # Mock FileSystemEvent for temporary file (should be ignored)
        mock_tmp = MagicMock()
        mock_tmp.is_directory = False
        mock_tmp.src_path = os.path.join(temp_dir, "tempfile.tmp")
        handler.on_created(mock_tmp)
        assert len(events) == 1  # Still 1

        # Mock FileSystemEvent for download completion (.crdownload -> final file)
        mock_move = MagicMock()
        mock_move.is_directory = False
        mock_move.src_path = os.path.join(temp_dir, "contract.docx.crdownload")
        mock_move.dest_path = os.path.join(temp_dir, "contract.docx")
        handler.on_moved(mock_move)

        assert len(events) == 2
        assert events[1].event_type == ActivityEventType.FILE_DOWNLOADED
        assert events[1].metadata["file_name"] == "contract.docx"
        assert events[1].metadata["is_download_completed"] is True
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_file_system_collector_lifecycle() -> None:
    """Verify FileSystemCollector start and stop."""
    temp_dir = tempfile.mkdtemp()
    try:
        collector = FileSystemCollector(watch_directory=temp_dir)
        collector.start()
        assert collector.is_running is True
        assert os.path.exists(temp_dir)
        collector.stop()
        assert collector.is_running is False
        assert collector._observer is None
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

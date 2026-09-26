"""Deterministic test datasets for Workflow Segmentation, Discovery, and Workflow DNA (Phase 4)."""

from datetime import datetime, timedelta, timezone
from typing import List
from app.models.event import ActivityEvent, ActivityEventType


def create_test_event(
    event_type: ActivityEventType,
    application: str,
    timestamp: datetime,
    metadata: dict = None,
) -> ActivityEvent:
    return ActivityEvent(
        event_type=event_type,
        application=application,
        timestamp=timestamp,
        source="test_fixture",
        metadata=metadata or {},
    )


def generate_deterministic_dataset() -> List[ActivityEvent]:
    """Generates a rich, deterministic set of multi-session ActivityEvents.

    Phase 4 Enhancements:
    - Session 1:
      * Gmail (title: "Rahul - Replacement Request")
      * file_downloaded (file_name: "invoice_101.pdf")
      * CRM (title: "CRM - Customer Rahul")
      * Slack (title: "#ops-notifications")
    - Session 2:
      * Gmail (title: "Ananya - Replacement Request")
      * file_downloaded (file_name: "invoice_102.pdf")
      * CRM (title: "CRM - Customer Ananya")
      * Slack (title: "#ops-notifications")
    - Session 3:
      * Gmail (title: "Vikram - Replacement Request")
      * WhatsApp (title: "Chat with Mom") -> Incidental interruption
      * Google Chrome (title: "Chrome Tab")
      * file_downloaded (file_name: "invoice_103.pdf")
      * CRM (title: "CRM - Customer Vikram")
      * Microsoft Excel (title: "Log.xlsx") -> Optional step!
      * Slack (title: "#ops-notifications")
    - Session 4: Developer Workflow
      * VS Code -> Terminal -> Browser
    - Session 5: Isolated Noise
      * Spotify -> Calculator
    """
    base_time = datetime(2026, 9, 26, 9, 0, 0, tzinfo=timezone.utc)
    events: List[ActivityEvent] = []

    # --- Session 1: Execution A ---
    t = base_time
    events.append(
        create_test_event(
            ActivityEventType.WINDOW_FOCUSED,
            "Gmail",
            t,
            {"window_title": "Rahul - Replacement Request"},
        )
    )
    t += timedelta(seconds=10)
    events.append(
        create_test_event(
            ActivityEventType.FILE_DOWNLOADED,
            "File System",
            t,
            {"file_name": "invoice_101.pdf", "file_path": "C:\\Downloads\\invoice_101.pdf"},
        )
    )
    t += timedelta(seconds=15)
    events.append(
        create_test_event(
            ActivityEventType.WINDOW_FOCUSED,
            "CRM",
            t,
            {"window_title": "CRM - Customer Rahul"},
        )
    )
    t += timedelta(seconds=20)
    events.append(
        create_test_event(
            ActivityEventType.WINDOW_FOCUSED,
            "Slack",
            t,
            {"window_title": "#ops-notifications"},
        )
    )

    # --- 300s Inactivity Gap ---
    t += timedelta(seconds=300)

    # --- Session 2: Execution B ---
    events.append(
        create_test_event(
            ActivityEventType.WINDOW_FOCUSED,
            "Gmail",
            t,
            {"window_title": "Ananya - Replacement Request"},
        )
    )
    t += timedelta(seconds=12)
    events.append(
        create_test_event(
            ActivityEventType.FILE_DOWNLOADED,
            "File System",
            t,
            {"file_name": "invoice_102.pdf", "file_path": "C:\\Downloads\\invoice_102.pdf"},
        )
    )
    t += timedelta(seconds=18)
    events.append(
        create_test_event(
            ActivityEventType.WINDOW_FOCUSED,
            "CRM",
            t,
            {"window_title": "CRM - Customer Ananya"},
        )
    )
    t += timedelta(seconds=25)
    events.append(
        create_test_event(
            ActivityEventType.WINDOW_FOCUSED,
            "Slack",
            t,
            {"window_title": "#ops-notifications"},
        )
    )

    # --- 300s Inactivity Gap ---
    t += timedelta(seconds=300)

    # --- Session 3: Execution C (With noise + Optional Excel step) ---
    events.append(
        create_test_event(
            ActivityEventType.WINDOW_FOCUSED,
            "Gmail",
            t,
            {"window_title": "Vikram - Replacement Request"},
        )
    )
    t += timedelta(seconds=5)
    events.append(
        create_test_event(
            ActivityEventType.WINDOW_FOCUSED,
            "WhatsApp",
            t,
            {"window_title": "Chat with Mom"},
        )
    )
    t += timedelta(seconds=10)
    events.append(
        create_test_event(
            ActivityEventType.WINDOW_FOCUSED,
            "Google Chrome",
            t,
            {"window_title": "Search"},
        )
    )
    t += timedelta(seconds=15)
    events.append(
        create_test_event(
            ActivityEventType.FILE_DOWNLOADED,
            "File System",
            t,
            {"file_name": "invoice_103.pdf", "file_path": "C:\\Downloads\\invoice_103.pdf"},
        )
    )
    t += timedelta(seconds=20)
    events.append(
        create_test_event(
            ActivityEventType.WINDOW_FOCUSED,
            "CRM",
            t,
            {"window_title": "CRM - Customer Vikram"},
        )
    )
    t += timedelta(seconds=22)
    events.append(
        create_test_event(
            ActivityEventType.WINDOW_FOCUSED,
            "Microsoft Excel",
            t,
            {"window_title": "Log.xlsx"},
        )
    )
    t += timedelta(seconds=25)
    events.append(
        create_test_event(
            ActivityEventType.WINDOW_FOCUSED,
            "Slack",
            t,
            {"window_title": "#ops-notifications"},
        )
    )

    # --- 300s Inactivity Gap ---
    t += timedelta(seconds=300)

    # --- Session 4: Developer Workflow (Different Pattern) ---
    events.append(
        create_test_event(
            ActivityEventType.WINDOW_FOCUSED,
            "Visual Studio Code",
            t,
            {"window_title": "main.py - project"},
        )
    )
    t += timedelta(seconds=15)
    events.append(
        create_test_event(
            ActivityEventType.WINDOW_FOCUSED,
            "Terminal",
            t,
            {"window_title": "PowerShell"},
        )
    )
    t += timedelta(seconds=30)
    events.append(
        create_test_event(
            ActivityEventType.WINDOW_FOCUSED,
            "Browser",
            t,
            {"window_title": "Documentation"},
        )
    )

    # --- 300s Inactivity Gap ---
    t += timedelta(seconds=300)

    # --- Session 5: Unrelated Isolated Activity ---
    events.append(
        create_test_event(
            ActivityEventType.WINDOW_FOCUSED,
            "Spotify",
            t,
            {"window_title": "Chill Mix"},
        )
    )
    t += timedelta(seconds=10)
    events.append(
        create_test_event(
            ActivityEventType.WINDOW_FOCUSED,
            "Calculator",
            t,
            {"window_title": "Calculator"},
        )
    )

    return events

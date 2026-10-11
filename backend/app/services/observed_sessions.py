"""Recorded browser sessions of a person doing the customer-replacement routine by hand.

Used by the `observed_browser_routine` demo scenario and by the observation->execution tests.

The events are shaped exactly like the ones the WorkFlowOS browser extension
(desktop-agent/browser_extension) and the Windows window collector send to POST /api/events.
Each session: search Gmail -> open the email -> download the attachment -> look the customer up
in the CRM -> set the status -> post in Slack. Customers, attachments and timings differ
between sessions; the search query, the target status and the Slack channel stay the same.
"""

from datetime import datetime, timedelta, timezone
from typing import List

from app.models.event import ActivityEvent, ActivityEventType

GMAIL_SEARCH = "has:attachment subject:replacement"
GMAIL_SEARCH_URL = "https://mail.google.com/mail/u/0/#search/has%3Aattachment+subject%3Areplacement"
SLACK_CHANNEL = "C0123456789"

SESSIONS = [
    {"customer_id": "cust-001", "email": "rahul.sharma@example.com", "invoice": "invoice_101.pdf", "msg": "FMfcgzQXJWDsKmPqRtZvLhNbYcWx"},
    {"customer_id": "cust-002", "email": "priya.patel@example.com", "invoice": "invoice_102.pdf", "msg": "FMfcgzQXKbTrLmNpQsVwXyZaBcDe"},
    {"customer_id": "cust-003", "email": "amit.kumar@example.com", "invoice": "invoice_103.pdf", "msg": "FMfcgzQXLcUsMnOqRtWxYzAbCdEf"},
]


def _event(ts: datetime, event_type: ActivityEventType, application: str, **metadata) -> ActivityEvent:
    return ActivityEvent(
        event_type=event_type,
        timestamp=ts,
        application=application,
        source="browser_extension" if event_type != ActivityEventType.WINDOW_FOCUSED else "desktop_agent",
        metadata=metadata,
    )


def build_session_events(start: datetime, customer_id: str, email: str, invoice: str, msg: str) -> List[ActivityEvent]:
    t = start
    step = timedelta(seconds=7)
    crm = "http://127.0.0.1:8001/ui/customers"
    events = [
        _event(t, ActivityEventType.WINDOW_FOCUSED, "Gmail", window_title="Inbox - Gmail - Google Chrome"),
        _event(t + step, ActivityEventType.BROWSER_NAVIGATION, "Google Chrome", url=GMAIL_SEARCH_URL),
        _event(t + 2 * step, ActivityEventType.BROWSER_NAVIGATION, "Google Chrome", url=f"{GMAIL_SEARCH_URL}/{msg}"),
        _event(
            t + 3 * step,
            ActivityEventType.FILE_DOWNLOADED,
            "Google Chrome",
            url="https://mail.google.com/mail/u/0?ui=2&ik=4f1c2&attid=0.1&disp=safe",
            file_name=invoice,
        ),
        _event(t + 4 * step, ActivityEventType.BROWSER_NAVIGATION, "Google Chrome", url=f"{crm}?q={email.replace('@', '%40')}"),
        _event(t + 5 * step, ActivityEventType.BROWSER_NAVIGATION, "Google Chrome", url=f"{crm}/{customer_id}"),
        _event(
            t + 6 * step,
            ActivityEventType.FORM_SUBMITTED,
            "Google Chrome",
            url=f"{crm}/{customer_id}",
            form_fields={"status": "replacement_processed"},
        ),
        _event(t + 7 * step, ActivityEventType.WINDOW_FOCUSED, "Slack", window_title="ops-replacements (Channel) - Slack"),
        _event(
            t + 8 * step,
            ActivityEventType.FORM_SUBMITTED,
            "Google Chrome",
            url=f"https://app.slack.com/client/T0WORKFLOW/{SLACK_CHANNEL}",
        ),
    ]
    return events


def build_observed_events(start: datetime = datetime(2026, 9, 28, 9, 0, tzinfo=timezone.utc)) -> List[ActivityEvent]:
    """Three sessions, each separated by an idle gap well beyond the segmenter's 120s timeout."""
    events: List[ActivityEvent] = []
    for i, s in enumerate(SESSIONS):
        events.extend(build_session_events(start + timedelta(hours=i), s["customer_id"], s["email"], s["invoice"], s["msg"]))
    return events

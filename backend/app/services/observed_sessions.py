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


# --------------------------------------------------------- the same routine, done in HubSpot

HUBSPOT_PORTAL = "4812345"
HUBSPOT_CONTACT_IDS = ["90001", "90002", "90003"]  # one per entry in SESSIONS


def build_hubspot_session_events(start: datetime, contact_id: str, email: str, invoice: str, msg: str) -> List[ActivityEvent]:
    """Gmail search + attachment -> HubSpot contact: set a property, add a note -> Slack."""
    t = start
    step = timedelta(seconds=7)
    base = f"https://app.hubspot.com/contacts/{HUBSPOT_PORTAL}"
    record = f"{base}/record/0-1/{contact_id}"
    return [
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
        _event(
            t + 4 * step,
            ActivityEventType.BROWSER_NAVIGATION,
            "Google Chrome",
            url=f"{base}/objects/0-1/views/all/list?query={email.replace('@', '%40')}",
        ),
        _event(t + 5 * step, ActivityEventType.BROWSER_NAVIGATION, "Google Chrome", url=record),
        _event(
            t + 6 * step,
            ActivityEventType.FORM_SUBMITTED,
            "Google Chrome",
            url=record,
            form_fields={"kind": "property", "property": "replacement_status", "value": "processed"},
        ),
        _event(t + 7 * step, ActivityEventType.FORM_SUBMITTED, "Google Chrome", url=record, form_fields={"kind": "note"}),
        _event(t + 8 * step, ActivityEventType.WINDOW_FOCUSED, "Slack", window_title="ops-replacements (Channel) - Slack"),
        _event(
            t + 9 * step,
            ActivityEventType.FORM_SUBMITTED,
            "Google Chrome",
            url=f"https://app.slack.com/client/T0WORKFLOW/{SLACK_CHANNEL}",
        ),
    ]


def build_observed_hubspot_events(start: datetime = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)) -> List[ActivityEvent]:
    events: List[ActivityEvent] = []
    for i, (s, contact_id) in enumerate(zip(SESSIONS, HUBSPOT_CONTACT_IDS)):
        events.extend(build_hubspot_session_events(start + timedelta(hours=i), contact_id, s["email"], s["invoice"], s["msg"]))
    return events


SHARED_FOLDER_DIR = r"S:\Team\Invoices"  # what the desktop agent watches with SHARED_FOLDER_DIRECTORY


def build_folder_session_events(start: datetime, invoice: str, msg: str) -> List[ActivityEvent]:
    """Gmail search + attachment -> the file is put into the team's shared folder -> Slack."""
    t = start
    step = timedelta(seconds=7)
    return [
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
        ActivityEvent(
            event_type=ActivityEventType.FILE_CREATED,
            timestamp=t + 4 * step,
            application="File System",
            source="desktop_agent",
            metadata={
                "file_name": invoice,
                "file_path": SHARED_FOLDER_DIR + "\\" + invoice,
                "directory": SHARED_FOLDER_DIR,
                "collector": "FileSystemCollector",
                "folder_role": "shared",
            },
        ),
        _event(t + 5 * step, ActivityEventType.WINDOW_FOCUSED, "Slack", window_title="ops-replacements (Channel) - Slack"),
        _event(t + 6 * step, ActivityEventType.FORM_SUBMITTED, "Google Chrome", url=f"https://app.slack.com/client/T0WORKFLOW/{SLACK_CHANNEL}"),
    ]


def build_observed_folder_events(start: datetime = datetime(2026, 11, 9, 9, 0, tzinfo=timezone.utc)) -> List[ActivityEvent]:
    events: List[ActivityEvent] = []
    for i, s in enumerate(SESSIONS):
        events.extend(build_folder_session_events(start + timedelta(hours=i), s["invoice"], s["msg"]))
    return events


def build_thread_session_events(start: datetime, invoice: str, msg: str) -> List[ActivityEvent]:
    """Gmail attachment -> 'received' in Slack -> filed in the shared folder -> 'done' as a thread reply."""
    session = build_folder_session_events(start, invoice, msg)
    download, saved, slack_focus, slack_send = session[3], session[4], session[5], session[6]
    step = timedelta(seconds=7)
    t = download.timestamp
    slack_url = slack_send.metadata["url"]
    return session[:4] + [
        _event(t + step, ActivityEventType.WINDOW_FOCUSED, "Slack", window_title=slack_focus.metadata["window_title"]),
        _event(t + 2 * step, ActivityEventType.FORM_SUBMITTED, "Google Chrome", url=slack_url),
        saved.model_copy(update={"timestamp": t + 3 * step, "event_id": f"{saved.event_id}-t"}),
        _event(t + 4 * step, ActivityEventType.FORM_SUBMITTED, "Google Chrome", url=slack_url, form_fields={"kind": "thread_reply"}),
    ]


def build_observed_thread_events(start: datetime = datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc)) -> List[ActivityEvent]:
    events: List[ActivityEvent] = []
    for i, s in enumerate(SESSIONS):
        events.extend(build_thread_session_events(start + timedelta(hours=i), s["invoice"], s["msg"]))
    return events


PROCESSED_LABEL = "Processed"


def build_label_session_events(start: datetime, invoice: str, msg: str) -> List[ActivityEvent]:
    """Gmail attachment -> label the email 'Processed' -> Slack."""
    session = build_folder_session_events(start, invoice, msg)
    labeled = _event(
        session[3].timestamp + timedelta(seconds=3),
        ActivityEventType.FORM_SUBMITTED,
        "Google Chrome",
        url=f"{GMAIL_SEARCH_URL}/{msg}",
        form_fields={"kind": "label_added", "label": PROCESSED_LABEL},
    )
    return session[:4] + [labeled] + session[5:]


def build_observed_label_events(start: datetime = datetime(2026, 11, 18, 9, 0, tzinfo=timezone.utc)) -> List[ActivityEvent]:
    events: List[ActivityEvent] = []
    for i, s in enumerate(SESSIONS):
        events.extend(build_label_session_events(start + timedelta(hours=i), s["invoice"], s["msg"]))
    return events


LOG_SPREADSHEET_ID = "1WfOsLogSheet0000000000000000000000000000ab"


def build_sheet_session_events(start: datetime, invoice: str, msg: str) -> List[ActivityEvent]:
    """Gmail attachment -> open the team's log sheet (a row is typed there) -> Slack."""
    session = build_folder_session_events(start, invoice, msg)
    opened = _event(
        session[3].timestamp + timedelta(seconds=3),
        ActivityEventType.BROWSER_NAVIGATION,
        "Google Chrome",
        url=f"https://docs.google.com/spreadsheets/d/{LOG_SPREADSHEET_ID}",
    )
    return session[:4] + [opened] + session[5:]


def build_observed_sheet_events(start: datetime = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)) -> List[ActivityEvent]:
    events: List[ActivityEvent] = []
    for i, s in enumerate(SESSIONS):
        events.extend(build_sheet_session_events(start + timedelta(hours=i), s["invoice"], s["msg"]))
    return events

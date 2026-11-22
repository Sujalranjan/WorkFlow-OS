"""Gmail: search the mailbox and download an attachment into the sandbox (read-only), and, only
when an admin opts in, label the processed email (gmail.add_label, see services/gmail_labels.py)."""

import re
from typing import Optional, Tuple
from urllib.parse import unquote_plus, urlparse

from app.integrations.base import CatalogAction, CatalogParameter, ClassifiedAction, Integration, host_matches
from app.models.canonical import RiskCategory, RiskLevel
from app.models.event import ActivityEvent, ActivityEventType
from app.models.strategy import ExecutionStrategyType

_GMAIL_HOSTS = ("mail.google.com",)
_ATTACHMENT_HOSTS = ("mail.google.com", "mail-attachment.googleusercontent.com")
# Gmail web message ids appended to a search route (e.g. '#search/<query>/FMfcgz...')
_MESSAGE_ID_RE = re.compile(r"^[A-Za-z0-9]{16,}$")

SEARCH_EMAIL = CatalogAction(
    action_id="gmail.search_email",
    application="Gmail",
    action="search_email",
    description="Search the mailbox (read-only) and select the matching email",
    executor_name="GmailApiExecutor",
    strategy=ExecutionStrategyType.API_INTEGRATION,
    risk_level=RiskLevel.LOW,
    risk_category=RiskCategory.READ_ONLY,
    risk_reason="Read-only Gmail search; no mailbox state is modified.",
    parameters=(
        CatalogParameter("search_query", "Gmail search query, e.g. 'has:attachment subject:invoice'"),
        CatalogParameter(
            "trigger_message_id",
            "Gmail message id supplied by an email trigger; pins the run to that exact email",
            required=False,
        ),
    ),
    produces=("message_id", "email_subject", "customer_email", "attachment_id", "filename"),
)

DOWNLOAD_ATTACHMENT = CatalogAction(
    action_id="gmail.download_attachment",
    application="Gmail",
    action="download_attachment",
    description="Download the selected email's attachment into the execution sandbox",
    executor_name="GmailApiExecutor",
    strategy=ExecutionStrategyType.API_INTEGRATION,
    risk_level=RiskLevel.MEDIUM,
    risk_category=RiskCategory.LOCAL_CHANGE,
    risk_reason="Writes the attachment into the isolated per-execution sandbox only.",
    produces=("downloaded_file", "attachment_sha256"),
    requires=("message_id",),
)


ADD_LABEL = CatalogAction(
    action_id="gmail.add_label",
    application="Gmail",
    action="add_label",
    description="Add a label to the processed email (opt-in; adds only, never removes or moves)",
    executor_name="GmailLabelExecutor",
    strategy=ExecutionStrategyType.API_INTEGRATION,
    risk_level=RiskLevel.MEDIUM,
    risk_category=RiskCategory.EXTERNAL_CHANGE,
    risk_reason="Adds a label to an email in Gmail (the only Gmail change WorkFlowOS can make).",
    parameters=(
        CatalogParameter("message_id", "The email this run processed", upstream_template="{message_id}"),
        CatalogParameter("label", "Name of an existing Gmail label (created by you, not a system label)"),
    ),
    produces=("gmail_label",),
    requires=("message_id",),
)


def _search_query(url: str) -> Optional[str]:
    fragment = urlparse(url).fragment
    if not fragment.startswith("search/"):
        return None
    parts = fragment[len("search/"):].split("/")
    if len(parts) > 1 and _MESSAGE_ID_RE.match(parts[-1]):
        parts = parts[:-1]
    query = unquote_plus("/".join(parts)).strip()
    return query or None


def classify_search(evt: ActivityEvent) -> Optional[ClassifiedAction]:
    """A Gmail search route (#search/<query>) is a search; the inbox or a label is not."""
    if evt.event_type != ActivityEventType.BROWSER_NAVIGATION:
        return None
    url = evt.metadata.get("url") or evt.metadata.get("tab_url")
    if not isinstance(url, str) or not host_matches(url, _GMAIL_HOSTS):
        return None
    query = _search_query(url)
    return ClassifiedAction(SEARCH_EMAIL, {"search_query": query}) if query else None


def classify_download(evt: ActivityEvent) -> Optional[ClassifiedAction]:
    """A finished download whose source is Gmail is an attachment download."""
    if evt.event_type != ActivityEventType.FILE_DOWNLOADED:
        return None
    for key in ("url", "source_url", "referrer", "final_url"):
        val = evt.metadata.get(key)
        if isinstance(val, str) and host_matches(val, _ATTACHMENT_HOSTS):
            return ClassifiedAction(DOWNLOAD_ATTACHMENT, {})
    return None


def classify_label(evt: ActivityEvent) -> Optional[ClassifiedAction]:
    """Applying a label in the Gmail web app, as reported by the extension (best effort)."""
    if evt.event_type != ActivityEventType.FORM_SUBMITTED:
        return None
    url = evt.metadata.get("url") or ""
    if not isinstance(url, str) or not host_matches(url, _GMAIL_HOSTS):
        return None
    fields = evt.metadata.get("form_fields") if isinstance(evt.metadata.get("form_fields"), dict) else {}
    if fields.get("kind") != "label_added":
        return None
    label = str(fields.get("label") or "").strip()
    return ClassifiedAction(ADD_LABEL, {"label": label} if label else {})


def _executor():
    from app.services.executors.gmail_executor import GmailApiExecutor

    return GmailApiExecutor()


def _label_executor():
    from app.services.executors.gmail_label_executor import GmailLabelExecutor

    return GmailLabelExecutor()


def _verifier():
    from app.services.verifiers.gmail_verifier import GmailVerificationStrategy

    return GmailVerificationStrategy()


def _label_verifier():
    from app.services.verifiers.gmail_label_verifier import GmailLabelVerificationStrategy

    return GmailLabelVerificationStrategy()


def status() -> Tuple[bool, str]:
    from app.services.gmail_client import GmailApiClient

    gmail = GmailApiClient()
    if not gmail.is_configured():
        return False, "Not set up: use Connect Gmail in Settings."
    if not gmail.is_authenticated():
        return False, "Sign-in needed: use Connect Gmail in Settings."
    return gmail.check_access()


GMAIL = Integration(
    key="gmail",
    name="Gmail",
    role="Reads request emails and attachments",
    actions=(SEARCH_EMAIL, DOWNLOAD_ATTACHMENT, ADD_LABEL),
    classifiers=(classify_search, classify_download, classify_label),
    executors=(_executor, _label_executor),
    verifiers=(_verifier, _label_verifier),
    status=status,
)

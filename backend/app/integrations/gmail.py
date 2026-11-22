"""Gmail (read-only): search the mailbox, download an attachment into the sandbox."""

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


def _executor():
    from app.services.executors.gmail_executor import GmailApiExecutor

    return GmailApiExecutor()


def _verifier():
    from app.services.verifiers.gmail_verifier import GmailVerificationStrategy

    return GmailVerificationStrategy()


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
    actions=(SEARCH_EMAIL, DOWNLOAD_ATTACHMENT),
    classifiers=(classify_search, classify_download),
    executors=(_executor,),
    verifiers=(_verifier,),
    status=status,
)

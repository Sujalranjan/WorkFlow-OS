"""Action Catalog: the fixed vocabulary that bridges observation and execution.

Observed desktop/browser activity is only executable if it can be named exactly. The
catalog lists every action WorkFlowOS can actually perform, together with:

- the executor that performs it (routing is by exact name, never by keyword guessing),
- its deterministic risk classification,
- the parameters it consumes and where each parameter comes from at runtime.

`classify_event()` maps a single observed ActivityEvent to a catalog action using
deterministic rules (explicit `workflow_action` metadata, Gmail/CRM/Slack URL patterns,
attachment downloads, CRM form submissions). Events that do not match remain ordinary
observational context (e.g. window focus) and are never executed.

STRICT GUARANTEES:
- No LLM involvement: classification is pure pattern matching on event metadata.
- No message bodies, form contents (other than the CRM status field) or keystrokes are read.
"""

from dataclasses import dataclass, field
import os
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote_plus, urlparse

from app.models.canonical import RiskCategory, RiskLevel
from app.models.event import ActivityEvent, ActivityEventType
from app.models.strategy import ExecutionStrategyType

CRM_WEB_BASE_URL = os.getenv("CRM_WEB_BASE_URL", "http://127.0.0.1:8001")


@dataclass(frozen=True)
class CatalogParameter:
    """An input consumed by a catalog action."""

    name: str
    description: str
    required: bool = True
    # Template resolved by the ExecutionEngine from upstream step outputs when the
    # parameter varies between observed sessions and no runtime value is supplied.
    upstream_template: Optional[str] = None


@dataclass(frozen=True)
class CatalogAction:
    """A single executable action with exact executor routing."""

    action_id: str
    application: str
    action: str
    description: str
    executor_name: str
    strategy: ExecutionStrategyType
    risk_level: RiskLevel
    risk_category: RiskCategory
    risk_reason: str
    requires_confirmation: bool = False
    parameters: Tuple[CatalogParameter, ...] = field(default_factory=tuple)
    produces: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def step_key(self) -> str:
        """DNA step key for this action (e.g. 'gmail:search_email')."""
        return f"{self.application.lower()}:{self.action}"

    def parameter(self, name: str) -> Optional[CatalogParameter]:
        return next((p for p in self.parameters if p.name == name), None)


ACTION_CATALOG: Dict[str, CatalogAction] = {
    a.action_id: a
    for a in (
        CatalogAction(
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
        ),
        CatalogAction(
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
        ),
        CatalogAction(
            action_id="crm.find_customer",
            application="CRM",
            action="find_customer",
            description="Look up the customer record in the CRM",
            executor_name="CrmApiExecutor",
            strategy=ExecutionStrategyType.API_INTEGRATION,
            risk_level=RiskLevel.LOW,
            risk_category=RiskCategory.READ_ONLY,
            risk_reason="Read-only CRM lookup.",
            parameters=(
                CatalogParameter(
                    "customer_query",
                    "Customer id, email or name to look up",
                    upstream_template="{customer_email}",
                ),
            ),
            produces=("customer_id", "customer_name", "customer_email"),
        ),
        CatalogAction(
            action_id="crm.update_customer_record",
            application="CRM",
            action="update_customer_record",
            description="Update the customer's status in the CRM",
            executor_name="CrmApiExecutor",
            strategy=ExecutionStrategyType.API_INTEGRATION,
            risk_level=RiskLevel.HIGH,
            risk_category=RiskCategory.EXTERNAL_CHANGE,
            risk_reason="Mutates an external CRM record.",
            requires_confirmation=True,
            parameters=(CatalogParameter("customer_status", "New status value written to the CRM record"),),
            produces=("crm_updated",),
        ),
        CatalogAction(
            action_id="slack.send_notification",
            application="Slack",
            action="send_notification",
            description="Post a status notification to the team Slack channel",
            executor_name="SlackApiExecutor",
            strategy=ExecutionStrategyType.API_INTEGRATION,
            risk_level=RiskLevel.MEDIUM,
            risk_category=RiskCategory.COMMUNICATION,
            risk_reason="Sends a message to a team channel.",
            parameters=(CatalogParameter("channel", "Slack channel id (defaults to SLACK_CHANNEL_ID)", required=False),),
            produces=("slack_ts",),
        ),
    )
}

_BY_STEP_KEY: Dict[str, CatalogAction] = {a.step_key: a for a in ACTION_CATALOG.values()}


def get_action(action_id: Optional[str]) -> Optional[CatalogAction]:
    return ACTION_CATALOG.get(action_id) if action_id else None


def get_action_by_step_key(step_key: Optional[str]) -> Optional[CatalogAction]:
    return _BY_STEP_KEY.get(step_key) if step_key else None


def list_actions() -> List[CatalogAction]:
    return list(ACTION_CATALOG.values())


# ---------------------------------------------------------------------------
# Event classification
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ClassifiedAction:
    action: CatalogAction
    parameters: Dict[str, str]


_GMAIL_HOSTS = ("mail.google.com",)
_GMAIL_ATTACHMENT_HOSTS = ("mail.google.com", "mail-attachment.googleusercontent.com")
_SLACK_HOSTS = ("app.slack.com",)
# Gmail web message ids appended to a search route (e.g. '#search/<query>/FMfcgz...')
_GMAIL_MESSAGE_ID_RE = re.compile(r"^[A-Za-z0-9]{16,}$")
_CRM_CUSTOMER_PATH_RE = re.compile(r"^/ui/customers/([^/]+)/?$")
_SLACK_CHANNEL_PATH_RE = re.compile(r"^/client/[^/]+/([CDG][A-Z0-9]+)")


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _host_matches(url: str, hosts: Tuple[str, ...]) -> bool:
    h = _host(url)
    return any(h == x or h.endswith("." + x) for x in hosts)


_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _is_crm_url(url: str) -> bool:
    try:
        target = urlparse(url)
        base = urlparse(CRM_WEB_BASE_URL)
        same_port = target.port == base.port
    except ValueError:
        return False
    same_host = target.hostname == base.hostname or (
        target.hostname in _LOOPBACK_HOSTS and base.hostname in _LOOPBACK_HOSTS
    )
    return same_host and same_port and target.path.startswith("/ui/")


def _gmail_search_query(url: str) -> Optional[str]:
    fragment = urlparse(url).fragment
    if not fragment.startswith("search/"):
        return None
    parts = fragment[len("search/"):].split("/")
    if len(parts) > 1 and _GMAIL_MESSAGE_ID_RE.match(parts[-1]):
        parts = parts[:-1]
    query = unquote_plus("/".join(parts)).strip()
    return query or None


def _classify_navigation(url: str) -> Optional[ClassifiedAction]:
    if _host_matches(url, _GMAIL_HOSTS):
        query = _gmail_search_query(url)
        if query:
            return ClassifiedAction(ACTION_CATALOG["gmail.search_email"], {"search_query": query})
        return None

    if _is_crm_url(url):
        parsed = urlparse(url)
        m = _CRM_CUSTOMER_PATH_RE.match(parsed.path)
        if m:
            return ClassifiedAction(ACTION_CATALOG["crm.find_customer"], {"customer_query": unquote_plus(m.group(1))})
        if parsed.path.rstrip("/") == "/ui/customers":
            q = (parse_qs(parsed.query).get("q") or [""])[0].strip()
            if q:
                return ClassifiedAction(ACTION_CATALOG["crm.find_customer"], {"customer_query": q})
    return None


def _classify_download(evt: ActivityEvent) -> Optional[ClassifiedAction]:
    md = evt.metadata
    for key in ("url", "source_url", "referrer", "final_url"):
        val = md.get(key)
        if isinstance(val, str) and _host_matches(val, _GMAIL_ATTACHMENT_HOSTS):
            return ClassifiedAction(ACTION_CATALOG["gmail.download_attachment"], {})
    return None


def _classify_form_submission(evt: ActivityEvent) -> Optional[ClassifiedAction]:
    md = evt.metadata
    url = md.get("url") or ""
    if not isinstance(url, str):
        return None

    if _is_crm_url(url) and _CRM_CUSTOMER_PATH_RE.match(urlparse(url).path):
        fields = md.get("form_fields") or {}
        status = fields.get("status") if isinstance(fields, dict) else None
        params = {"customer_status": str(status).strip()} if status else {}
        return ClassifiedAction(ACTION_CATALOG["crm.update_customer_record"], params)

    if _host_matches(url, _SLACK_HOSTS):
        m = _SLACK_CHANNEL_PATH_RE.match(urlparse(url).path)
        params = {"channel": m.group(1)} if m else {}
        return ClassifiedAction(ACTION_CATALOG["slack.send_notification"], params)
    return None


def classify_event(evt: ActivityEvent) -> Optional[ClassifiedAction]:
    """Deterministically map an observed event to a catalog action, or None."""
    md = evt.metadata or {}

    explicit = md.get("workflow_action")
    if isinstance(explicit, str) and explicit in ACTION_CATALOG:
        params = md.get("action_parameters") or {}
        clean = {str(k): str(v) for k, v in params.items() if v is not None} if isinstance(params, dict) else {}
        return ClassifiedAction(ACTION_CATALOG[explicit], clean)

    if evt.event_type == ActivityEventType.BROWSER_NAVIGATION:
        url = md.get("url") or md.get("tab_url")
        return _classify_navigation(url) if isinstance(url, str) else None
    if evt.event_type == ActivityEventType.FILE_DOWNLOADED:
        return _classify_download(evt)
    if evt.event_type == ActivityEventType.FORM_SUBMITTED:
        return _classify_form_submission(evt)
    return None


def step_key_for_event(evt: ActivityEvent) -> str:
    """The normalized step key used by discovery and DNA extraction."""
    classified = classify_event(evt)
    if classified:
        return classified.action.step_key
    app = (evt.application or "").strip().lower() or "unknown_app"
    return f"{app}:{evt.event_type.value}"


def application_for_event(evt: ActivityEvent) -> str:
    classified = classify_event(evt)
    if classified:
        return classified.action.application
    return evt.application or "Unknown"


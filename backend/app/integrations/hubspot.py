"""HubSpot CRM: find a contact, update one contact property, add a note to the contact.

Execution uses the documented HubSpot API (see services/hubspot_client.py). Observation is best
effort: HubSpot does not document its web-app URLs, so the rules below recognise the URL shapes the
app uses today (contact record pages and the contacts list search) and the events the browser
extension's HubSpot script reports. If HubSpot changes its UI, these rules (not execution) need
updating.
"""

import re
from typing import Optional, Tuple
from urllib.parse import parse_qs, unquote_plus, urlparse

from app.integrations.base import CatalogAction, CatalogParameter, ClassifiedAction, Integration, host
from app.models.canonical import RiskCategory, RiskLevel
from app.models.event import ActivityEvent, ActivityEventType
from app.models.strategy import ExecutionStrategyType

# /contacts/<portal>/record/0-1/<id> (current) and /contacts/<portal>/contact/<id> (older)
_RECORD_PATH_RE = re.compile(r"^/contacts/\d+/(?:record/0-1|contact)/(\d+)/?")
_LIST_PATH_RE = re.compile(r"^/contacts/\d+/(?:objects/0-1|contacts)(?:/|$)")

FIND_CONTACT = CatalogAction(
    action_id="hubspot.find_contact",
    application="HubSpot",
    action="find_contact",
    description="Look up the contact in HubSpot (exact email match, or a search)",
    executor_name="HubSpotApiExecutor",
    strategy=ExecutionStrategyType.API_INTEGRATION,
    risk_level=RiskLevel.LOW,
    risk_category=RiskCategory.READ_ONLY,
    risk_reason="Read-only HubSpot lookup.",
    parameters=(
        CatalogParameter("contact_query", "Contact email or search text", upstream_template="{customer_email}"),
    ),
    produces=("contact_id", "contact_name", "contact_email"),
)

UPDATE_CONTACT = CatalogAction(
    action_id="hubspot.update_contact",
    application="HubSpot",
    action="update_contact",
    description="Set one property on the HubSpot contact (the property chosen in Settings)",
    executor_name="HubSpotApiExecutor",
    strategy=ExecutionStrategyType.API_INTEGRATION,
    risk_level=RiskLevel.HIGH,
    risk_category=RiskCategory.EXTERNAL_CHANGE,
    risk_reason="Changes a record in HubSpot.",
    requires_confirmation=True,
    parameters=(
        CatalogParameter("contact_property", "Internal name of the property (default: from Settings)", required=False),
        CatalogParameter("property_value", "Value to write (default: from Settings)", required=False),
    ),
    produces=("hubspot_updated",),
)

ADD_NOTE = CatalogAction(
    action_id="hubspot.add_note",
    application="HubSpot",
    action="add_note",
    description="Add a note to the HubSpot contact's timeline",
    executor_name="HubSpotApiExecutor",
    strategy=ExecutionStrategyType.API_INTEGRATION,
    risk_level=RiskLevel.MEDIUM,
    risk_category=RiskCategory.EXTERNAL_CHANGE,
    risk_reason="Adds a note to a HubSpot record (does not change existing data).",
    parameters=(CatalogParameter("note_body", "Note text (default: names the processed email)", required=False),),
    produces=("note_id",),
)


def _is_hubspot_app(url: str) -> bool:
    h = host(url)
    # app.hubspot.com, app-eu1.hubspot.com, ...; never a look-alike such as hubspot.com.evil.example
    return h.endswith(".hubspot.com") and h.split(".", 1)[0].startswith("app")


def classify_lookup(evt: ActivityEvent) -> Optional[ClassifiedAction]:
    """Opening a contact record, or searching the contacts list, is a lookup."""
    if evt.event_type != ActivityEventType.BROWSER_NAVIGATION:
        return None
    url = evt.metadata.get("url") or evt.metadata.get("tab_url")
    if not isinstance(url, str) or not _is_hubspot_app(url):
        return None
    parsed = urlparse(url)
    m = _RECORD_PATH_RE.match(parsed.path)
    if m:
        return ClassifiedAction(FIND_CONTACT, {"contact_query": m.group(1)})
    if _LIST_PATH_RE.match(parsed.path):
        q = unquote_plus((parse_qs(parsed.query).get("query") or [""])[0]).strip()
        if q:
            return ClassifiedAction(FIND_CONTACT, {"contact_query": q})
    return None


def classify_change(evt: ActivityEvent) -> Optional[ClassifiedAction]:
    """Saving on a contact record, as reported by the extension: a note, or a property edit."""
    if evt.event_type != ActivityEventType.FORM_SUBMITTED:
        return None
    url = evt.metadata.get("url") or ""
    if not isinstance(url, str) or not _is_hubspot_app(url) or not _RECORD_PATH_RE.match(urlparse(url).path):
        return None
    fields = evt.metadata.get("form_fields") if isinstance(evt.metadata.get("form_fields"), dict) else {}
    if fields.get("kind") == "note":
        return ClassifiedAction(ADD_NOTE, {})
    params = {}
    if fields.get("property"):
        params["contact_property"] = str(fields["property"])
    if fields.get("value") not in (None, ""):
        params["property_value"] = str(fields["value"])
    return ClassifiedAction(UPDATE_CONTACT, params)


def _executor():
    from app.services.executors.hubspot_executor import HubSpotApiExecutor

    return HubSpotApiExecutor()


def _verifier():
    from app.services.verifiers.hubspot_verifier import HubSpotVerificationStrategy

    return HubSpotVerificationStrategy()


def status() -> Tuple[bool, str]:
    from app.services.hubspot_client import HubSpotClient

    return HubSpotClient(timeout=5.0).check_access()


HUBSPOT = Integration(
    key="hubspot",
    name="HubSpot",
    role="Looks up contacts, updates them and adds notes",
    actions=(FIND_CONTACT, UPDATE_CONTACT, ADD_NOTE),
    classifiers=(classify_lookup, classify_change),
    executors=(_executor,),
    verifiers=(_verifier,),
    status=status,
)

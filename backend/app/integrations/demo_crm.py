"""The bundled Demo CRM: find a customer, update their status.

Observed through its browser UI (`/ui/customers...` on CRM_WEB_BASE_URL), executed through its REST
API (CRM_API_BASE_URL).
"""

import os
import re
from typing import Optional, Tuple
from urllib.parse import parse_qs, unquote_plus, urlparse

from app.integrations.base import CatalogAction, CatalogParameter, ClassifiedAction, Integration
from app.models.canonical import RiskCategory, RiskLevel
from app.models.event import ActivityEvent, ActivityEventType
from app.models.strategy import ExecutionStrategyType

CRM_WEB_BASE_URL = os.getenv("CRM_WEB_BASE_URL", "http://127.0.0.1:8001")
_CUSTOMER_PATH_RE = re.compile(r"^/ui/customers/([^/]+)/?$")
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

FIND_CUSTOMER = CatalogAction(
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
        CatalogParameter("customer_query", "Customer id, email or name to look up", upstream_template="{customer_email}"),
    ),
    produces=("customer_id", "customer_name", "customer_email", "customer_status"),
)

UPDATE_CUSTOMER = CatalogAction(
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
    produces=("crm_updated", "customer_status"),
    requires=("customer_id",),
)


def is_crm_url(url: str) -> bool:
    """A page of the Demo CRM's browser UI (localhost and 127.0.0.1 count as the same host)."""
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


def classify_lookup(evt: ActivityEvent) -> Optional[ClassifiedAction]:
    """Opening a customer page, or searching the customer list, is a lookup."""
    if evt.event_type != ActivityEventType.BROWSER_NAVIGATION:
        return None
    url = evt.metadata.get("url") or evt.metadata.get("tab_url")
    if not isinstance(url, str) or not is_crm_url(url):
        return None
    parsed = urlparse(url)
    m = _CUSTOMER_PATH_RE.match(parsed.path)
    if m:
        return ClassifiedAction(FIND_CUSTOMER, {"customer_query": unquote_plus(m.group(1))})
    if parsed.path.rstrip("/") == "/ui/customers":
        q = (parse_qs(parsed.query).get("q") or [""])[0].strip()
        if q:
            return ClassifiedAction(FIND_CUSTOMER, {"customer_query": q})
    return None


def classify_update(evt: ActivityEvent) -> Optional[ClassifiedAction]:
    """Saving the status form on a customer page is an update (only the status field is read)."""
    if evt.event_type != ActivityEventType.FORM_SUBMITTED:
        return None
    url = evt.metadata.get("url") or ""
    if not isinstance(url, str) or not (is_crm_url(url) and _CUSTOMER_PATH_RE.match(urlparse(url).path)):
        return None
    fields = evt.metadata.get("form_fields") or {}
    status = fields.get("status") if isinstance(fields, dict) else None
    return ClassifiedAction(UPDATE_CUSTOMER, {"customer_status": str(status).strip()} if status else {})


def _executor():
    from app.services.executors.crm_executor import CrmApiExecutor

    return CrmApiExecutor()


def _verifier():
    from app.services.verifiers.crm_verifier import CrmVerificationStrategy

    return CrmVerificationStrategy()


def status() -> Tuple[bool, str]:
    from app.services.crm_client import CrmApiClient

    crm = CrmApiClient(timeout=3.0)
    if crm.is_healthy():
        return True, crm.base_url
    return False, f"Not reachable at {crm.base_url}. Start it with: python backend/app/crm_server.py"


DEMO_CRM = Integration(
    key="crm",
    name="CRM",
    role="Looks up and updates customers",
    actions=(FIND_CUSTOMER, UPDATE_CUSTOMER),
    classifiers=(classify_lookup, classify_update),
    executors=(_executor,),
    verifiers=(_verifier,),
    status=status,
)

"""HubSpot CRM API client (contacts and notes).

Authentication: a HubSpot access token sent as `Authorization: Bearer <token>`. For one team this
is a **service key** (HubSpot > Development > Keys > Service keys, with the contact scopes) or an
existing legacy private-app token. HubSpot stopped allowing new legacy private apps on
2026-10-26, so new installs use service keys.

Token precedence, resolved on every call (Settings changes apply without a restart): explicit
argument, then Settings (encrypted store), then HUBSPOT_ACCESS_TOKEN.

Endpoints (developers.hubspot.com):
    POST  /crm/v3/objects/contacts/search        find by email or free text
    GET   /crm/v3/objects/contacts/{id}          read one contact
    PATCH /crm/v3/objects/contacts/{id}          update properties
    POST  /crm/v3/objects/notes                  create a note, associated to the contact (type 202)
    GET   /crm/v3/objects/notes/{id}             read it back (verification)
    GET   /crm/v3/properties/contacts            property list for Settings
    GET   /account-info/v3/details               portal id and UI domain (best effort)

Never logs or returns the token. Errors carry the HTTP status so callers can tell a missing scope
(403) from a bad token (401) from a rate limit (429).
"""

from datetime import datetime, timezone
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

HUBSPOT_API_BASE_URL = os.getenv("HUBSPOT_API_BASE_URL", "https://api.hubapi.com").rstrip("/")
CONTACT_PROPERTIES = ["email", "firstname", "lastname", "company"]
NOTE_TO_CONTACT_ASSOCIATION = 202  # HUBSPOT_DEFINED "Note to contact"


class HubSpotError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class HubSpotNotConfigured(HubSpotError):
    pass


class HubSpotRateLimited(HubSpotError, ConnectionError):
    """429: HubSpot asked us to slow down. The step fails (the run stops); run it again later."""


class HubSpotContact(BaseModel):
    contact_id: str
    email: Optional[str] = None
    firstname: Optional[str] = None
    lastname: Optional[str] = None
    company: Optional[str] = None
    properties: Dict[str, Any] = {}

    @property
    def name(self) -> str:
        return " ".join(p for p in (self.firstname, self.lastname) if p) or (self.email or self.contact_id)

    def as_candidate(self) -> Dict[str, Any]:
        """Shape used by the Inbox 'which customer?' picker (shared with the Demo CRM)."""
        return {"customer_id": self.contact_id, "name": self.name, "email": self.email, "company": self.company}


def _contact(raw: Dict[str, Any]) -> HubSpotContact:
    props = raw.get("properties") or {}
    return HubSpotContact(
        contact_id=str(raw.get("id")),
        email=props.get("email"),
        firstname=props.get("firstname"),
        lastname=props.get("lastname"),
        company=props.get("company"),
        properties=props,
    )


def _stored_token() -> Optional[str]:
    try:
        from app.services.credential_store import HUBSPOT, get_credential_store

        record = get_credential_store().get(HUBSPOT)
    except Exception:
        logger.exception("Could not read the HubSpot token from the credential store")
        return None
    return record.secret.get("access_token") if record else None


class HubSpotClient:
    def __init__(
        self,
        access_token: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 15.0,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        self._explicit_token = access_token
        self.base_url = (base_url or HUBSPOT_API_BASE_URL).rstrip("/")
        self.timeout = timeout
        self._http = http_client

    @property
    def _token(self) -> Optional[str]:
        return self._explicit_token or _stored_token() or os.getenv("HUBSPOT_ACCESS_TOKEN")

    def is_configured(self) -> bool:
        return bool(self._token)

    # ------------------------------------------------------------------- http

    def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        token = self._token
        if not token:
            raise HubSpotNotConfigured("HubSpot is not connected. Add an access token in Settings.")
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        client = self._http or httpx.Client(timeout=self.timeout)
        try:
            res = client.request(method, f"{self.base_url}{path}", headers=headers, **kwargs)
        finally:
            if self._http is None:
                client.close()
        if res.status_code == 429:
            raise HubSpotRateLimited("HubSpot rate limit reached; try again shortly.", 429)
        if res.status_code == 401:
            raise HubSpotError("HubSpot rejected the access token.", 401)
        if res.status_code == 403:
            raise HubSpotError("The HubSpot token is missing a permission (scope) this action needs.", 403)
        if res.status_code == 404:
            raise HubSpotError("Not found in HubSpot.", 404)
        if res.status_code >= 400:
            raise HubSpotError(f"HubSpot returned HTTP {res.status_code}: {res.text[:200]}", res.status_code)
        return res.json() if res.content else {}

    # --------------------------------------------------------------- account

    def account_details(self) -> Optional[Dict[str, Any]]:
        """{'portalId', 'uiDomain', ...} or None if the token cannot read account info."""
        try:
            return self._request("GET", "/account-info/v3/details")
        except HubSpotError:
            return None

    def check_access(self) -> Tuple[bool, str]:
        """Confirms the token can read contacts (the minimum every HubSpot action needs)."""
        if not self.is_configured():
            return False, "Not set up: add a HubSpot access token in Settings."
        try:
            self._request("GET", "/crm/v3/objects/contacts", params={"limit": 1, "properties": "email"})
        except HubSpotError as e:
            if e.status_code == 403:
                return False, "The token cannot read contacts: add the crm.objects.contacts.read scope."
            return False, str(e)
        except httpx.HTTPError as e:
            return False, f"HubSpot unreachable: {type(e).__name__}."
        return True, "Can read contacts."

    # -------------------------------------------------------------- contacts

    def find_contacts(self, query: str, limit: int = 10) -> List[HubSpotContact]:
        """Exact email match when `query` is an email address, otherwise HubSpot's text search."""
        query = query.strip()
        body: Dict[str, Any] = {"properties": CONTACT_PROPERTIES, "limit": max(1, min(limit, 100))}
        if "@" in query:
            body["filterGroups"] = [{"filters": [{"propertyName": "email", "operator": "EQ", "value": query}]}]
        else:
            body["query"] = query
        res = self._request("POST", "/crm/v3/objects/contacts/search", json=body)
        return [_contact(r) for r in res.get("results", [])]

    def get_contact(self, contact_id: str, properties: Optional[List[str]] = None) -> HubSpotContact:
        props = ",".join(sorted(set(CONTACT_PROPERTIES + (properties or []))))
        return _contact(self._request("GET", f"/crm/v3/objects/contacts/{contact_id}", params={"properties": props}))

    def update_contact(self, contact_id: str, properties: Dict[str, Any]) -> HubSpotContact:
        res = self._request("PATCH", f"/crm/v3/objects/contacts/{contact_id}", json={"properties": properties})
        return _contact(res)

    def list_contact_properties(self) -> List[Dict[str, Any]]:
        """Writable contact properties for the Settings picker: name, label, type, and options if any."""
        res = self._request("GET", "/crm/v3/properties/contacts")
        out = []
        for p in res.get("results", []):
            if (p.get("modificationMetadata") or {}).get("readOnlyValue") or p.get("calculated"):
                continue
            out.append(
                {
                    "name": p.get("name"),
                    "label": p.get("label") or p.get("name"),
                    "type": p.get("type"),
                    "options": [o.get("value") for o in p.get("options") or [] if o.get("value") is not None],
                }
            )
        return sorted(out, key=lambda p: (p["label"] or "").lower())

    # ----------------------------------------------------------------- notes

    def create_note(self, contact_id: str, body: str) -> Dict[str, Any]:
        payload = {
            "properties": {
                "hs_note_body": body[:65536],
                "hs_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            "associations": [
                {
                    "to": {"id": str(contact_id)},
                    "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": NOTE_TO_CONTACT_ASSOCIATION}],
                }
            ],
        }
        return self._request("POST", "/crm/v3/objects/notes", json=payload)

    def get_note(self, note_id: str) -> Dict[str, Any]:
        return self._request(
            "GET", f"/crm/v3/objects/notes/{note_id}", params={"properties": "hs_note_body,hs_timestamp", "associations": "contacts"}
        )

"""CRM API Client Abstraction (Phase 15B).

Provides a dedicated HTTP client interface for interacting with the WorkFlowOS Demo CRM REST API.
Enforces the architectural separation:
    WorkFlowOS Executor -> CrmApiClient -> CRM REST API -> CRM Database

SECURITY & GOVERNANCE:
- Never executes direct SQL against the CRM database.
- Uses normalized REST API payloads and responses.
- Supports both live HTTP connections and ASGI in-process transport for deterministic tests.
"""

from datetime import datetime, timezone
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

from app.models.crm import CrmCustomer, CrmSearchResult

logger = logging.getLogger(__name__)

DEFAULT_CRM_API_BASE_URL = os.getenv("CRM_API_BASE_URL", "http://127.0.0.1:8001/api/crm")


class CrmClientError(Exception):
    """Base exception for CRM API Client errors."""
    pass


class CrmConnectionError(CrmClientError):
    """Raised when the CRM API server is unreachable or connection fails."""
    pass


class CrmCustomerNotFoundError(CrmClientError):
    """Raised when the requested customer is not found in CRM."""
    pass


class CrmApiError(CrmClientError):
    """Raised when the CRM API returns an HTTP error status."""
    pass


class CrmApiClient:
    """Dedicated HTTP client communicating with the CRM REST API.

    In REAL/production mode (default):
        Strictly executes live HTTP requests against the CRM API service via httpx.
        Does NOT silently fall back to local in-process execution.
        If the server is unavailable, raises CrmConnectionError.

    In TEST mode (when app is passed or use_in_process=True):
        Uses FastAPI TestClient for in-process ASGI execution during test suites.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = 10.0,
        app: Optional[Any] = None,
        use_in_process: bool = False,
    ) -> None:
        self.base_url = (base_url or DEFAULT_CRM_API_BASE_URL).rstrip("/")
        self.timeout = timeout
        self._app = app
        self._use_in_process = use_in_process or (app is not None)

    def _get_client(self) -> Any:
        """Constructs an HTTP client.

        Strictly respects mode:
        - If use_in_process: uses FastAPI TestClient.
        - Otherwise (real live mode): uses httpx.Client. NEVER silently falls back!
        """
        if self._use_in_process:
            from fastapi.testclient import TestClient
            if self._app is not None:
                return TestClient(self._app)
            from app.main import app as main_app
            return TestClient(main_app)

        # Real HTTP client
        return httpx.Client(timeout=self.timeout)

    def is_healthy(self) -> bool:
        """Checks if the CRM API is reachable and healthy."""
        try:
            with self._get_client() as client:
                res = client.get(f"{self.base_url}/health")
                return res.status_code == 200
        except Exception:
            return False

    def find_customer(
        self,
        query: Optional[str] = None,
        email: Optional[str] = None,
        limit: int = 50,
    ) -> CrmSearchResult:
        """Searches customer records via the CRM API /customers/search endpoint."""
        payload: Dict[str, Any] = {"limit": limit}
        if query:
            payload["query"] = query.strip()
        if email:
            payload["email"] = email.strip()

        try:
            with self._get_client() as client:
                res = client.post(f"{self.base_url}/customers/search", json=payload)
                if res.status_code != 200:
                    raise CrmApiError(f"CRM API search failed ({res.status_code}): {res.text}")
                data = res.json()
                return CrmSearchResult(**data)
        except CrmClientError:
            raise
        except Exception as e:
            logger.error("Failed to connect to CRM API for customer search: %s", str(e))
            raise CrmConnectionError(f"CRM API connection failed: {str(e)}") from e

    def get_customer(self, customer_id: str) -> Optional[CrmCustomer]:
        """Retrieves a customer by customer_id from the CRM API."""
        if not customer_id or not str(customer_id).strip():
            raise ValueError("customer_id cannot be empty")

        cid = str(customer_id).strip()
        try:
            with self._get_client() as client:
                res = client.get(f"{self.base_url}/customers/{cid}")
                if res.status_code == 404:
                    return None
                if res.status_code != 200:
                    raise CrmApiError(f"CRM API get customer failed ({res.status_code}): {res.text}")
                return CrmCustomer(**res.json())
        except CrmClientError:
            raise
        except Exception as e:
            logger.error("Failed to connect to CRM API for get_customer: %s", str(e))
            raise CrmConnectionError(f"CRM API connection failed: {str(e)}") from e

    def update_customer(self, customer_id: str, updates: Dict[str, Any]) -> CrmCustomer:
        """Updates an existing customer record via the CRM API PATCH endpoint."""
        if not customer_id or not str(customer_id).strip():
            raise ValueError("customer_id cannot be empty for update")

        cid = str(customer_id).strip()
        try:
            with self._get_client() as client:
                res = client.patch(f"{self.base_url}/customers/{cid}", json=updates)
                if res.status_code == 404:
                    raise CrmCustomerNotFoundError(f"Customer '{cid}' not found in CRM.")
                if res.status_code != 200:
                    raise CrmApiError(f"CRM API update failed ({res.status_code}): {res.text}")
                return CrmCustomer(**res.json())
        except CrmClientError:
            raise
        except Exception as e:
            logger.error("Failed to connect to CRM API for update_customer: %s", str(e))
            raise CrmConnectionError(f"CRM API connection failed: {str(e)}") from e

    def create_customer(self, customer_data: Dict[str, Any]) -> CrmCustomer:
        """Creates a new customer record via the CRM API POST endpoint."""
        try:
            with self._get_client() as client:
                res = client.post(f"{self.base_url}/customers", json=customer_data)
                if res.status_code != 201:
                    raise CrmApiError(f"CRM API create customer failed ({res.status_code}): {res.text}")
                return CrmCustomer(**res.json())
        except CrmClientError:
            raise
        except Exception as e:
            logger.error("Failed to connect to CRM API for create_customer: %s", str(e))
            raise CrmConnectionError(f"CRM API connection failed: {str(e)}") from e

    def seed_demo_data(self) -> List[CrmCustomer]:
        """Seeds the demo baseline data into the CRM database via the CRM API."""
        try:
            with self._get_client() as client:
                res = client.post(f"{self.base_url}/seed")
                if res.status_code != 200:
                    raise CrmApiError(f"CRM API seed failed ({res.status_code}): {res.text}")
                return [CrmCustomer(**c) for c in res.json()]
        except CrmClientError:
            raise
        except Exception as e:
            logger.error("Failed to seed demo data via CRM API: %s", str(e))
            raise CrmConnectionError(f"CRM API connection failed: {str(e)}") from e

    def reset_database(self) -> Dict[str, Any]:
        """Resets the CRM database with clean demo baseline records via the CRM API."""
        try:
            with self._get_client() as client:
                res = client.post(f"{self.base_url}/reset")
                if res.status_code != 200:
                    raise CrmApiError(f"CRM API reset failed ({res.status_code}): {res.text}")
                return res.json()
        except CrmClientError:
            raise
        except Exception as e:
            logger.error("Failed to reset CRM database via CRM API: %s", str(e))
            raise CrmConnectionError(f"CRM API connection failed: {str(e)}") from e


"""Gmail API Client Abstraction for Phase 12.

Provides a dedicated, secure client interface for read-only Gmail API operations.
Uses official Google OAuth 2.0 with the narrowest read-only scope:
    https://www.googleapis.com/auth/gmail.readonly

SECURITY & PRIVACY GUARANTEES:
- Strictly read-only operations (search_messages / get_metadata).
- ZERO modification endpoints (no send, delete, move, mark-as-read, or label change).
- ZERO logging or exposure of access/refresh tokens or client secrets.
- Fails closed when credentials or configuration are unavailable.
"""

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import (
    GMAIL_CREDENTIALS_PATH,
    GMAIL_ENABLED,
    GMAIL_SCOPES,
    GMAIL_TOKEN_PATH,
)
from app.models.gmail import GmailMessageSummary, GmailSearchResult

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    InstalledAppFlow = None  # type: ignore

logger = logging.getLogger(__name__)


class GmailClientError(Exception):
    """Base exception for Gmail API client errors."""
    pass


class GmailConfigurationError(GmailClientError):
    """Raised when Gmail integration is disabled or required config files are missing."""
    pass


class GmailAuthenticationError(GmailClientError):
    """Raised when OAuth credentials/token are missing, expired, or invalid."""
    pass


class GmailApiError(GmailClientError):
    """Raised when a Gmail API network or execution call fails."""
    pass


class GmailApiClient:
    """Dedicated client managing authentication and read-only searches via the Gmail API."""

    def __init__(
        self,
        credentials_path: Optional[str] = None,
        token_path: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        service: Optional[Any] = None,
    ) -> None:
        self.credentials_path = credentials_path or GMAIL_CREDENTIALS_PATH
        self.token_path = token_path or GMAIL_TOKEN_PATH
        self.scopes = scopes or GMAIL_SCOPES
        self._service = service  # allows injecting a mock service for deterministic testing

    def is_configured(self) -> bool:
        """Checks whether Gmail integration is enabled and configured."""
        if self._service is not None:
            return True
        if not GMAIL_ENABLED and not os.path.exists(self.credentials_path) and not os.path.exists(self.token_path):
            return False
        return os.path.exists(self.credentials_path) or os.path.exists(self.token_path)

    def is_authenticated(self) -> bool:
        """Checks if a valid or refreshable OAuth token is available."""
        if self._service is not None:
            return True
        if not os.path.exists(self.token_path):
            return False

        try:
            from google.oauth2.credentials import Credentials
            creds = Credentials.from_authorized_user_file(self.token_path, self.scopes)
            if creds and creds.valid:
                return True
            # Expired with refresh token can be refreshed automatically
            if creds and creds.expired and creds.refresh_token:
                return True
            return False
        except Exception as e:
            logger.debug("Failed validating Gmail token file: %s", str(e))
            return False

    def authenticate_interactive(self, open_browser: bool = True) -> Any:
        """Starts an interactive OAuth 2.0 authorization flow in the local browser.

        Uses client credentials at credentials_path, requests ONLY the narrow read-only
        scope (https://www.googleapis.com/auth/gmail.readonly), runs a local callback
        server on an ephemeral port, and saves the authorized user token to token_path.

        Returns:
            The authenticated Google API Resource service object.
        """
        if not os.path.exists(self.credentials_path):
            raise GmailConfigurationError(
                f"OAuth client secrets file not found at '{self.credentials_path}'. "
                "Download OAuth 2.0 Client ID (Desktop Application) from Google Cloud Console "
                f"and save it to '{self.credentials_path}'."
            )

        if InstalledAppFlow is None:
            raise GmailConfigurationError(
                "google-auth-oauthlib package is required for interactive OAuth authentication."
            )

        try:
            from googleapiclient.discovery import build

            logger.info("Initiating local Google OAuth 2.0 flow for read-only Gmail access...")
            flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, self.scopes)
            creds = flow.run_local_server(port=0, open_browser=open_browser)

            # Persist authorized user token securely
            token_dir = os.path.dirname(os.path.abspath(self.token_path))
            if token_dir and not os.path.exists(token_dir):
                os.makedirs(token_dir, exist_ok=True)

            with open(self.token_path, "w", encoding="utf-8") as token_file:
                token_file.write(creds.to_json())

            logger.info("OAuth token successfully saved to '%s'", self.token_path)
            self._service = build("gmail", "v1", credentials=creds)
            return self._service
        except (GmailConfigurationError, GmailAuthenticationError):
            raise
        except Exception as e:
            logger.error("OAuth interactive authorization failed: %s", str(e))
            raise GmailAuthenticationError(f"OAuth authorization flow failed: {str(e)}") from e

    def get_service(self, interactive: bool = False, open_browser: bool = True) -> Any:
        """Returns the authenticated Google API Resource service object."""
        if self._service is not None:
            return self._service

        if not self.is_configured():
            raise GmailConfigurationError(
                "Gmail integration is not configured. Set GMAIL_ENABLED=true and provide GMAIL_CREDENTIALS_PATH."
            )

        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build

            creds = None
            if os.path.exists(self.token_path):
                try:
                    creds = Credentials.from_authorized_user_file(self.token_path, self.scopes)
                except Exception as load_err:
                    logger.debug("Failed loading token file '%s': %s", self.token_path, str(load_err))

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    try:
                        creds.refresh(Request())
                        with open(self.token_path, "w", encoding="utf-8") as token_file:
                            token_file.write(creds.to_json())
                    except Exception as refresh_err:
                        if interactive and os.path.exists(self.credentials_path):
                            return self.authenticate_interactive(open_browser=open_browser)
                        raise GmailAuthenticationError(
                            f"OAuth token expired and refresh failed: {str(refresh_err)}"
                        ) from refresh_err
                elif interactive and os.path.exists(self.credentials_path):
                    return self.authenticate_interactive(open_browser=open_browser)
                else:
                    raise GmailAuthenticationError(
                        f"OAuth token is missing or invalid at '{self.token_path}'. "
                        "Authorization is required via OAuth flow."
                    )

            self._service = build("gmail", "v1", credentials=creds)
            return self._service

        except (GmailConfigurationError, GmailAuthenticationError):
            raise
        except Exception as e:
            raise GmailApiError(f"Failed to initialize Gmail API service: {str(e)}") from e

    def search_messages(self, query: str, max_results: int = 10) -> GmailSearchResult:
        """Executes a read-only search on Gmail messages matching query.

        Args:
            query: The search filter string (e.g., 'from:user@example.com').
            max_results: Maximum messages to retrieve metadata for (default 10, max 50).

        Returns:
            GmailSearchResult containing normalized message summaries.
        """
        if not query or not query.strip():
            raise ValueError("Query string cannot be empty for search_email operation.")

        service = self.get_service()
        clamped_max = min(max(1, max_results), 50)

        try:
            # 1. Execute list query
            list_res = (
                service.users()
                .messages()
                .list(userId="me", q=query.strip(), maxResults=clamped_max)
                .execute()
            )

            raw_messages = list_res.get("messages", [])
            normalized_list: List[GmailMessageSummary] = []

            # 2. Retrieve metadata for each message
            for msg_item in raw_messages:
                msg_id = msg_item.get("id")
                thread_id = msg_item.get("threadId", "")

                msg_data = (
                    service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=msg_id,
                        format="metadata",
                        metadataHeaders=["Subject", "From", "Date"],
                    )
                    .execute()
                )

                # Extract headers safely
                headers = msg_data.get("payload", {}).get("headers", [])
                header_map = {h.get("name", "").lower(): h.get("value", "") for h in headers}

                normalized_list.append(
                    GmailMessageSummary(
                        message_id=msg_id,
                        thread_id=thread_id,
                        subject=header_map.get("subject", "(No Subject)"),
                        sender=header_map.get("from", "(Unknown Sender)"),
                        timestamp=header_map.get("date") or msg_data.get("internalDate"),
                        snippet=msg_data.get("snippet", ""),
                    )
                )

            return GmailSearchResult(
                query=query.strip(),
                total_found=len(normalized_list),
                messages=normalized_list,
                searched_at=datetime.now(timezone.utc).isoformat(),
            )

        except (GmailConfigurationError, GmailAuthenticationError):
            raise
        except Exception as e:
            logger.error("Gmail search API call failed: %s", str(e))
            raise GmailApiError(f"Gmail search API error: {str(e)}") from e

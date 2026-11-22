"""Gmail API Client Abstraction.

Provides a dedicated, secure client interface for read-only Gmail API operations.
Uses official Google OAuth 2.0 with the narrowest read-only scope:
    https://www.googleapis.com/auth/gmail.readonly

SECURITY & PRIVACY GUARANTEES:
- Strictly read-only operations (search_messages / get_metadata).
- ZERO modification endpoints (no send, delete, move, mark-as-read, or label change).
- ZERO logging or exposure of access/refresh tokens or client secrets.
- Fails closed when credentials or configuration are unavailable.
"""

import base64
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.config import (
    GMAIL_CREDENTIALS_PATH,
    GMAIL_ENABLED,
    GMAIL_SCOPES,
    GMAIL_TOKEN_PATH,
)
from app.models.gmail import GmailAttachmentInfo, GmailMessageSummary, GmailSearchResult

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    InstalledAppFlow = None  # type: ignore

logger = logging.getLogger(__name__)

SIGN_IN_NEEDED = "Sign-in needed: use Connect Gmail in Settings (or run scripts/gmail_login.py)."
SIGN_IN_EXPIRED = "Sign-in expired: connect Gmail again in Settings (or run scripts/gmail_login.py --force)."

_PART_FIELDS = "filename,mimeType,body(attachmentId,size)"
_SUMMARY_FIELDS = (
    "id,threadId,snippet,internalDate,"
    f"payload(headers,{_PART_FIELDS},parts({_PART_FIELDS},parts({_PART_FIELDS},parts({_PART_FIELDS}))))"
)


def _list_attachments(payload: Dict[str, Any]) -> List[GmailAttachmentInfo]:
    """Walk a (field-masked) message payload and list named file parts."""
    found: List[GmailAttachmentInfo] = []

    def walk(part: Dict[str, Any]) -> None:
        body = part.get("body", {}) or {}
        if part.get("filename") and (body.get("attachmentId") or body.get("size")):
            found.append(
                GmailAttachmentInfo(
                    attachment_id=body.get("attachmentId"),
                    filename=part["filename"],
                    mime_type=part.get("mimeType"),
                    size_bytes=int(body.get("size") or 0),
                )
            )
        for sub in part.get("parts", []) or []:
            walk(sub)

    walk(payload)
    return found


class GmailClientError(Exception):
    """Base exception for Gmail API client errors."""
    pass


class GmailConfigurationError(GmailClientError):
    """Raised when Gmail integration is disabled or required config files are missing."""
    pass


class GmailAuthenticationError(GmailClientError):
    """Raised when OAuth credentials/token are missing, expired, or invalid."""
    pass


class GmailHistoryExpired(GmailClientError):
    """The stored history id is too old for Gmail (kept roughly a week); a full resync is needed."""
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
        credential_store: Optional[Any] = None,
        use_credential_store: Optional[bool] = None,
    ) -> None:
        self.credentials_path = credentials_path or GMAIL_CREDENTIALS_PATH
        self.token_path = token_path or GMAIL_TOKEN_PATH
        self.scopes = scopes or GMAIL_SCOPES
        self._injected_service = service  # allows injecting a mock service for deterministic testing
        # Built service, reused only while the same sign-in (source + refresh token) is in effect,
        # so Disconnect or connecting another account takes effect without a restart.
        self._service: Optional[Any] = None
        self._service_identity: Optional[Tuple[Optional[str], Optional[str]]] = None
        # Token sources, in order: "Connect Gmail" in Settings (encrypted store), then token.json.
        # An explicit token_path (CLI sign-in script, tests) means file only.
        self._store = credential_store
        self._use_store = use_credential_store if use_credential_store is not None else token_path is None

    def _stored_token(self) -> Optional[Dict[str, Any]]:
        if not self._use_store:
            return None
        try:
            from app.services.credential_store import GMAIL_TOKEN, get_credential_store

            record = (self._store or get_credential_store()).get(GMAIL_TOKEN)
        except Exception:
            logger.exception("Could not read the Gmail token from the credential store")
            return None
        return record.secret if record else None

    def _load_credentials(self) -> Tuple[Any, Optional[str]]:
        """(google Credentials, 'store' | 'file') or (None, None)."""
        from google.oauth2.credentials import Credentials

        info = self._stored_token()
        if info:
            return Credentials.from_authorized_user_info(info, self.scopes), "store"
        if os.path.exists(self.token_path):
            return Credentials.from_authorized_user_file(self.token_path, self.scopes), "file"
        return None, None

    def _save_credentials(self, creds: Any, source: Optional[str]) -> None:
        """Persist a refreshed token back where it came from."""
        if source == "store":
            from app.services.credential_store import GMAIL_TOKEN, get_credential_store

            (self._store or get_credential_store()).update_secret(GMAIL_TOKEN, json.loads(creds.to_json()))
            return
        with open(self.token_path, "w", encoding="utf-8") as token_file:
            token_file.write(creds.to_json())

    def is_configured(self) -> bool:
        """Checks whether Gmail integration is enabled and configured."""
        if self._injected_service is not None:
            return True
        if self._stored_token():
            return True
        if not GMAIL_ENABLED and not os.path.exists(self.credentials_path) and not os.path.exists(self.token_path):
            return False
        return os.path.exists(self.credentials_path) or os.path.exists(self.token_path)

    def is_authenticated(self) -> bool:
        """Checks if a valid or refreshable OAuth token is available."""
        if self._injected_service is not None:
            return True

        try:
            creds, _ = self._load_credentials()
            if creds and creds.valid:
                return True
            # Expired with refresh token can be refreshed automatically
            if creds and creds.expired and creds.refresh_token:
                return True
            return False
        except Exception as e:
            logger.debug("Failed validating Gmail token file: %s", str(e))
            return False

    def check_access(self) -> Tuple[bool, str]:
        """Confirm with Google that the saved sign-in still works (refreshing it if expired).

        Unlike is_authenticated(), this makes a network call, so it notices a revoked or
        expired refresh token instead of trusting the token file.
        """
        if self._injected_service is not None:
            return True, "Read-only access."
        try:
            from google.auth.transport.requests import Request

            creds, source = self._load_credentials()
            if creds is None:
                return False, SIGN_IN_NEEDED
            if creds.valid:
                return True, "Read-only access."
            if not creds.refresh_token:
                return False, SIGN_IN_EXPIRED
            creds.refresh(Request())
            self._save_credentials(creds, source)
            return True, "Read-only access."
        except Exception as e:
            logger.info("Gmail sign-in check failed: %s", e)
            if "invalid_grant" in str(e):
                return False, SIGN_IN_EXPIRED
            return False, f"Could not confirm Gmail access: {type(e).__name__}."

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
        if self._injected_service is not None:
            return self._injected_service

        if not self.is_configured():
            raise GmailConfigurationError(
                "Gmail is not set up. Connect Gmail in Settings (or provide credentials.json and token.json)."
            )

        try:
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build

            creds, source = None, None
            try:
                creds, source = self._load_credentials()
            except Exception as load_err:
                logger.debug("Failed loading Gmail token: %s", str(load_err))

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    try:
                        creds.refresh(Request())
                        self._save_credentials(creds, source)
                    except Exception as refresh_err:
                        if interactive and os.path.exists(self.credentials_path):
                            return self.authenticate_interactive(open_browser=open_browser)
                        raise GmailAuthenticationError(
                            f"OAuth token expired and refresh failed: {str(refresh_err)}"
                        ) from refresh_err
                elif interactive and os.path.exists(self.credentials_path):
                    return self.authenticate_interactive(open_browser=open_browser)
                else:
                    raise GmailAuthenticationError(f"Gmail token is missing or invalid. {SIGN_IN_NEEDED}")

            identity = (source, creds.refresh_token)
            if self._service is None or self._service_identity != identity:
                self._service = build("gmail", "v1", credentials=creds)
                self._service_identity = identity
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

            # 2. Retrieve metadata for each message
            normalized_list: List[GmailMessageSummary] = [
                self._summarize(service, msg_item.get("id"), msg_item.get("threadId", ""))
                for msg_item in raw_messages
            ]

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

    # ------------------------------------------------------------ incremental sync (read-only)

    def current_history_id(self) -> str:
        """The mailbox's latest history id: a bookmark for messages_added_since()."""
        service = self.get_service()
        try:
            return str(service.users().getProfile(userId="me").execute()["historyId"])
        except (GmailConfigurationError, GmailAuthenticationError):
            raise
        except Exception as e:
            raise GmailApiError(f"Gmail profile API error: {e}") from e

    def messages_added_since(self, start_history_id: str) -> Tuple[bool, str]:
        """Whether any message was added after `start_history_id`, and the newest history id.

        Reads only the change log (ids), never message content. Raises GmailHistoryExpired when Gmail
        no longer has history that old.
        """
        service = self.get_service()
        added = False
        latest = str(start_history_id)
        page_token: Optional[str] = None
        try:
            while True:
                res = (
                    service.users()
                    .history()
                    .list(
                        userId="me",
                        startHistoryId=str(start_history_id),
                        historyTypes=["messageAdded"],
                        maxResults=500,
                        pageToken=page_token,
                    )
                    .execute()
                )
                latest = str(res.get("historyId", latest))
                if any(h.get("messagesAdded") for h in res.get("history", [])):
                    added = True
                page_token = res.get("nextPageToken")
                if added or not page_token:
                    return added, latest
        except (GmailConfigurationError, GmailAuthenticationError):
            raise
        except Exception as e:
            if getattr(getattr(e, "resp", None), "status", None) == 404:
                raise GmailHistoryExpired(f"History id {start_history_id} is no longer available.") from e
            raise GmailApiError(f"Gmail history API error: {e}") from e

    def list_message_ids(self, query: str, limit: int = 5000) -> List[str]:
        """Ids of every message matching `query` (newest first), across all result pages, up to `limit`."""
        if not query or not query.strip():
            raise ValueError("Query string cannot be empty.")
        service = self.get_service()
        ids: List[str] = []
        page_token: Optional[str] = None
        try:
            while len(ids) < limit:
                res = (
                    service.users()
                    .messages()
                    .list(userId="me", q=query.strip(), maxResults=min(500, limit - len(ids)), pageToken=page_token)
                    .execute()
                )
                ids.extend(m["id"] for m in res.get("messages", []))
                page_token = res.get("nextPageToken")
                if not page_token:
                    break
            return ids
        except (GmailConfigurationError, GmailAuthenticationError):
            raise
        except Exception as e:
            raise GmailApiError(f"Gmail search API error: {e}") from e

    @staticmethod
    def _summarize(service: Any, msg_id: str, thread_id: str = "") -> GmailMessageSummary:
        """Fetch one message's headers and attachment listing (never body or attachment data)."""
        # format=full with a field mask: returns headers and the attachment
        # listing (filename/id/size) but never body or attachment data.
        msg_data = (
            service.users()
            .messages()
            .get(userId="me", id=msg_id, format="full", fields=_SUMMARY_FIELDS)
            .execute()
        )
        payload = msg_data.get("payload", {})
        headers = payload.get("headers", [])
        header_map = {
            h.get("name", "").lower(): h.get("value", "")
            for h in headers
            if h.get("name", "").lower() in ("subject", "from", "date")
        }
        attachments = _list_attachments(payload)
        return GmailMessageSummary(
            message_id=msg_id,
            thread_id=thread_id or msg_data.get("threadId", ""),
            subject=header_map.get("subject", "(No Subject)"),
            sender=header_map.get("from", "(Unknown Sender)"),
            timestamp=header_map.get("date") or msg_data.get("internalDate"),
            snippet=msg_data.get("snippet", ""),
            has_attachments=bool(attachments),
            attachments=attachments,
        )

    def get_message_summary(self, message_id: str) -> GmailMessageSummary:
        """Read-only metadata for one message by Gmail id (used to pin a triggered run to its email)."""
        if not message_id or not str(message_id).strip():
            raise ValueError("message_id cannot be empty")
        service = self.get_service()
        try:
            return self._summarize(service, str(message_id).strip())
        except (GmailConfigurationError, GmailAuthenticationError):
            raise
        except Exception as e:
            logger.error("Gmail get message API call failed: %s", str(e))
            raise GmailApiError(f"Gmail get message API error: {str(e)}") from e

    def get_message_attachments(self, message_id: str) -> List[Dict[str, Any]]:
        """Retrieves metadata of attachments associated with a message.

        Returns a list of dicts:
            [{"attachment_id": ..., "filename": ..., "mime_type": ..., "size_bytes": ...}]
        """
        if not message_id or not str(message_id).strip():
            raise ValueError("message_id cannot be empty for attachment retrieval.")

        service = self.get_service()
        try:
            msg_data = (
                service.users()
                .messages()
                .get(userId="me", id=str(message_id).strip(), format="full")
                .execute()
            )
            attachments: List[Dict[str, Any]] = []

            def _traverse_parts(parts: List[Dict[str, Any]]) -> None:
                for part in parts:
                    filename = part.get("filename", "")
                    body = part.get("body", {})
                    att_id = body.get("attachmentId")
                    inline_data = body.get("data")
                    if filename and (att_id or inline_data):
                        attachments.append({
                            "attachment_id": att_id or f"inline-{len(attachments)}",
                            "filename": filename,
                            "mime_type": part.get("mimeType"),
                            "size_bytes": body.get("size", 0),
                            "inline_data": inline_data,
                        })
                    sub_parts = part.get("parts", [])
                    if sub_parts:
                        _traverse_parts(sub_parts)

            payload = msg_data.get("payload", {})
            if payload.get("parts"):
                _traverse_parts(payload.get("parts", []))
            elif payload.get("filename") and (payload.get("body", {}).get("attachmentId") or payload.get("body", {}).get("data")):
                body = payload.get("body", {})
                attachments.append({
                    "attachment_id": body.get("attachmentId") or "inline-0",
                    "filename": payload.get("filename"),
                    "mime_type": payload.get("mimeType"),
                    "size_bytes": body.get("size", 0),
                    "inline_data": body.get("data"),
                })

            return attachments

        except (GmailConfigurationError, GmailAuthenticationError):
            raise
        except Exception as e:
            logger.error("Failed to retrieve attachments for message '%s': %s", message_id, str(e))
            raise GmailApiError(f"Failed to retrieve message attachments: {str(e)}") from e

    def get_attachment_data(self, message_id: str, attachment_id: str) -> bytes:
        """Retrieves raw attachment bytes via the Gmail API attachments.get endpoint."""
        if not message_id or not attachment_id:
            raise ValueError("Both message_id and attachment_id are required.")

        service = self.get_service()
        try:
            res = (
                service.users()
                .messages()
                .attachments()
                .get(userId="me", messageId=str(message_id).strip(), id=str(attachment_id).strip())
                .execute()
            )
            raw_data = res.get("data", "")
            if not raw_data:
                raise GmailApiError("Attachment payload contains empty data")
            try:
                # Add URL-safe base64 padding
                padded = raw_data + "=" * ((4 - len(raw_data) % 4) % 4)
                return base64.urlsafe_b64decode(padded.encode("utf-8"))
            except Exception as dec_err:
                raise GmailApiError(f"Failed to decode base64 attachment data: {str(dec_err)}") from dec_err

        except (GmailConfigurationError, GmailAuthenticationError, GmailApiError):
            raise
        except Exception as e:
            logger.error("Gmail attachment download failed: %s", str(e))
            raise GmailApiError(f"Gmail attachment API error: {str(e)}") from e

    def download_attachment(
        self,
        message_id: str,
        attachment_id: Optional[str] = None,
        filename: Optional[str] = None,
    ) -> Tuple[bytes, Dict[str, Any]]:
        """Downloads an attachment, discovering it from message metadata if attachment_id is omitted.

        Returns:
            Tuple[bytes, metadata_dict]
        """
        if not message_id or not str(message_id).strip():
            raise ValueError("message_id is required for download_attachment.")

        msg_id_clean = str(message_id).strip()

        # 1. Inspect message parts to discover attachment if needed
        att_meta = None
        if not attachment_id or not filename:
            attachments = self.get_message_attachments(msg_id_clean)
            if not attachments:
                raise GmailApiError(f"No attachments found in message '{msg_id_clean}'.")

            if attachment_id:
                for att in attachments:
                    if att["attachment_id"] == attachment_id:
                        att_meta = att
                        break
            elif filename:
                for att in attachments:
                    if att["filename"].lower() == filename.lower():
                        att_meta = att
                        break
            elif len(attachments) == 1:
                att_meta = attachments[0]
            else:
                filenames = [a["filename"] for a in attachments]
                raise GmailApiError(
                    f"Multiple attachments found in message '{msg_id_clean}': {filenames}. "
                    "Specify 'attachment_id' or 'filename' parameter."
                )

            if not att_meta:
                crit = f"filename='{filename}'" if filename else f"attachment_id='{attachment_id}'"
                raise GmailApiError(f"No attachment matching {crit} found in message '{msg_id_clean}'.")

            target_att_id = att_meta["attachment_id"]
            final_filename = att_meta["filename"]
            mime_type = att_meta.get("mime_type")
            inline_data = att_meta.get("inline_data")
        else:
            target_att_id = str(attachment_id).strip()
            final_filename = str(filename).strip()
            mime_type = None
            inline_data = None

        # 2. Retrieve bytes
        if inline_data:
            try:
                padded = inline_data + "=" * ((4 - len(inline_data) % 4) % 4)
                file_bytes = base64.urlsafe_b64decode(padded.encode("utf-8"))
            except Exception as dec_err:
                raise GmailApiError(f"Failed to decode inline attachment data: {str(dec_err)}") from dec_err
        else:
            file_bytes = self.get_attachment_data(message_id=msg_id_clean, attachment_id=target_att_id)

        metadata = {
            "message_id": msg_id_clean,
            "attachment_id": target_att_id,
            "filename": final_filename,
            "mime_type": mime_type,
            "size_bytes": len(file_bytes),
        }
        return file_bytes, metadata


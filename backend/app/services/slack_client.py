"""Slack Web API Client Abstraction (Phase 15D).

Provides a dedicated HTTPS client interface for interacting with the official Slack Web API.
Enforces the architectural separation:
    WorkFlowOS Executor -> SlackApiClient -> HTTPS -> Slack Web API (chat.postMessage)

SECURITY & GOVERNANCE:
- Never hardcodes, prints, logs, or audits bot tokens.
- Excludes Authorization headers from all error messages and diagnostics.
- Uses HTTPS with timeouts.
- Channel IDs must come from validated parameters or explicit environment configuration.
"""

from datetime import datetime, timezone
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx

import app.config  # Ensures .env is loaded via centralized config
from app.models.slack import SlackNotificationPayload, SlackNotificationResult

logger = logging.getLogger(__name__)

SLACK_API_BASE_URL = os.getenv("SLACK_API_BASE_URL", "https://slack.com/api").rstrip("/")
CHANNEL_REGEX = re.compile(r"^[A-Z0-9#\-_]{2,80}$", re.IGNORECASE)


class SlackClientError(Exception):
    """Base exception for Slack API Client errors."""
    pass


class SlackConfigurationError(SlackClientError):
    """Raised when required Slack configuration (e.g. token) is missing."""
    pass


class SlackValidationError(SlackClientError):
    """Raised when request parameters (channel, message) are invalid."""
    pass


class SlackApiError(SlackClientError):
    """Raised when Slack API returns an error response (e.g. channel_not_found)."""
    def __init__(self, error_code: str, message: Optional[str] = None) -> None:
        self.error_code = error_code
        super().__init__(message or f"Slack API error: {error_code}")


class SlackConnectionError(SlackClientError):
    """Raised when network connection to Slack Web API fails."""
    pass


class SlackApiClient:
    """Official Slack Web API client wrapper.

    Scopes Required:
    - Sending notifications: chat:write
    - Independent verification: channels:history (public) or groups:history (private)
    """

    def __init__(
        self,
        bot_token: Optional[str] = None,
        default_channel_id: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 10.0,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        self._bot_token = bot_token or os.getenv("SLACK_BOT_TOKEN")
        self.default_channel_id = default_channel_id or os.getenv("SLACK_CHANNEL_ID")
        self.base_url = (base_url or SLACK_API_BASE_URL).rstrip("/")
        self.timeout = timeout
        self._custom_client = http_client

    def _get_client(self) -> httpx.Client:
        """Returns the configured HTTP client."""
        if self._custom_client is not None:
            return self._custom_client
        return httpx.Client(timeout=self.timeout)

    def _get_auth_headers(self) -> Dict[str, str]:
        """Builds sanitized authorization headers. Never exposed in logs or errors."""
        if not self._bot_token or not self._bot_token.strip():
            raise SlackConfigurationError(
                "SLACK_BOT_TOKEN is not configured. Set SLACK_BOT_TOKEN environment variable."
            )
        return {
            "Authorization": f"Bearer {self._bot_token.strip()}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def validate_channel(self, channel: Optional[str]) -> str:
        """Validates and resolves the target channel."""
        target = self.default_channel_id if channel is None else channel
        target_clean = (target or "").strip()
        if not target_clean:
            raise SlackValidationError(
                "Slack channel is required but not provided or configured in SLACK_CHANNEL_ID."
            )
        if not CHANNEL_REGEX.match(target_clean):
            raise SlackValidationError(
                f"Invalid Slack channel format '{target_clean}'. Must be alphanumeric channel ID or valid channel name."
            )
        return target_clean

    def is_healthy(self) -> bool:
        """Checks Slack API connectivity via auth.test."""
        if not self._bot_token:
            return False
        try:
            headers = self._get_auth_headers()
            with self._get_client() as client:
                res = client.post(f"{self.base_url}/auth.test", headers=headers)
                data = res.json()
                return data.get("ok", False) is True
        except Exception:
            return False

    def send_notification(
        self,
        channel: Optional[str] = None,
        text: str = "",
        blocks: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SlackNotificationResult:
        """Sends a notification to a Slack channel via chat.postMessage.

        Args:
            channel: Target Slack channel ID or name.
            text: Notification message content.
            blocks: Optional Block Kit components.
            metadata: Optional structured metadata.

        Returns:
            SlackNotificationResult: Structured response with success status and message ts.
        """
        # 1. Validation
        resolved_channel = self.validate_channel(channel)
        text_clean = (text or "").strip()
        if not text_clean and not blocks:
            raise SlackValidationError("Slack notification text or blocks cannot be empty.")

        headers = self._get_auth_headers()
        payload: Dict[str, Any] = {
            "channel": resolved_channel,
            "text": text_clean,
        }
        if blocks:
            payload["blocks"] = blocks
        if metadata:
            payload["metadata"] = metadata

        # 2. HTTP POST
        try:
            with self._get_client() as client:
                resp = client.post(
                    f"{self.base_url}/chat.postMessage",
                    headers=headers,
                    json=payload,
                )
        except httpx.TimeoutException as e:
            logger.error("Slack API chat.postMessage timed out")
            raise SlackConnectionError("Slack API request timed out.") from e
        except httpx.RequestError as e:
            logger.error("Slack API connection error: %s", type(e).__name__)
            raise SlackConnectionError(f"Failed to connect to Slack API: {type(e).__name__}") from e

        # 3. Handle response
        try:
            data = resp.json()
        except Exception as e:
            raise SlackApiError("malformed_response", f"Malformed response from Slack API: {resp.text[:100]}") from e

        if not data.get("ok"):
            err_code = data.get("error", "unknown_error")
            if err_code == "not_in_channel":
                # Attempt to join public channel if bot has permission
                try:
                    with self._get_client() as client:
                        join_res = client.post(
                            f"{self.base_url}/conversations.join",
                            headers=headers,
                            json={"channel": resolved_channel},
                        )
                        if join_res.json().get("ok"):
                            logger.info("Successfully joined channel '%s', retrying chat.postMessage", resolved_channel)
                            retry_res = client.post(
                                f"{self.base_url}/chat.postMessage",
                                headers=headers,
                                json=payload,
                            )
                            retry_data = retry_res.json()
                            if retry_data.get("ok"):
                                return SlackNotificationResult(
                                    success=True,
                                    channel=retry_data.get("channel", resolved_channel),
                                    ts=retry_data.get("ts"),
                                    message=retry_data.get("message"),
                                    status_code=retry_res.status_code,
                                )
                except Exception as ex:
                    logger.debug("Auto-join attempt failed: %s", str(ex))

            logger.warning("Slack API chat.postMessage returned error: %s", err_code)
            raise SlackApiError(err_code, f"Slack API error: {err_code}")

        return SlackNotificationResult(
            success=True,
            channel=data.get("channel", resolved_channel),
            ts=data.get("ts"),
            message=data.get("message"),
            status_code=resp.status_code,
        )

    def verify_message(
        self,
        channel: str,
        ts: str,
        expected_text_contains: Optional[str] = None,
    ) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        """Independently verifies that a message exists in Slack via conversations.history.

        Requires scope: channels:history (or groups:history).

        Args:
            channel: Target channel ID.
            ts: Message timestamp identifier.
            expected_text_contains: Optional text substring to verify against message body.

        Returns:
            Tuple[bool, Optional[Dict[str, Any]], str]: (is_verified, message_data, reason)
        """
        if not channel or not ts:
            return False, None, "Invalid channel or timestamp for verification."

        headers = self._get_auth_headers()
        params = {
            "channel": channel,
            "latest": ts,
            "oldest": ts,
            "inclusive": "true",
            "limit": 1,
        }

        try:
            with self._get_client() as client:
                resp = client.get(
                    f"{self.base_url}/conversations.history",
                    headers=headers,
                    params=params,
                )
        except Exception as e:
            return False, None, f"Failed to query Slack API for verification: {str(e)}"

        try:
            data = resp.json()
        except Exception:
            return False, None, "Malformed verification response from Slack API."

        if not data.get("ok"):
            err = data.get("error", "unknown_error")
            return False, None, f"Slack verification query failed: {err}"

        messages = data.get("messages", [])
        if not messages:
            return False, None, f"Message with ts '{ts}' not found in channel '{channel}'."

        msg = messages[0]
        if expected_text_contains:
            msg_text = msg.get("text", "")
            if expected_text_contains not in msg_text:
                return False, msg, f"Message content mismatch: expected to contain '{expected_text_contains}'."

        return True, msg, f"Message '{ts}' confirmed present in channel '{channel}'."

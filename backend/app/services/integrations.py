"""Connecting Gmail and Slack from the dashboard.

Gmail ("Connect Gmail"): OAuth 2.0 authorization-code flow with PKCE and a single-use, 10 minute
`state`. The OAuth client (ID + secret) is entered once in Settings (stored encrypted) or read from
credentials.json. Only the gmail.readonly scope is requested. The resulting token is stored
encrypted and refreshed in place by GmailApiClient.

Slack: an admin saves a bot token and default channel; the token is checked with auth.test before
it is stored.

Nothing in this module returns a secret to callers outside the backend.
"""

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import os
import secrets
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import urlencode

import httpx

from app import config
from app.services.credential_store import (
    GMAIL_OAUTH_CLIENT,
    GMAIL_TOKEN,
    HUBSPOT,
    SLACK,
    CredentialStore,
    get_credential_store,
)

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GMAIL_PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"


class IntegrationError(Exception):
    """A problem the admin can fix; the message is safe to show."""

    def __init__(self, message: str, code: str = "error") -> None:
        super().__init__(message)
        self.code = code
        self.return_to: Optional[str] = None  # dashboard origin to send the browser back to


def _pkce_pair() -> Tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


class IntegrationService:
    def __init__(
        self,
        store: Optional[CredentialStore] = None,
        http_factory: Optional[Callable[[], httpx.Client]] = None,
        redirect_uri: Optional[str] = None,
    ) -> None:
        self._store = store
        self._http_factory = http_factory or (lambda: httpx.Client(timeout=10.0))
        self.redirect_uri = redirect_uri or config.GMAIL_OAUTH_REDIRECT_URI

    @property
    def store(self) -> CredentialStore:
        return self._store or get_credential_store()

    # ----------------------------------------------------------- gmail client

    def gmail_client_config(self) -> Optional[Tuple[str, str, str]]:
        """(client_id, client_secret, source) from Settings, else from credentials.json."""
        stored = self.store.get(GMAIL_OAUTH_CLIENT)
        if stored and stored.secret.get("client_id") and stored.secret.get("client_secret"):
            return stored.secret["client_id"], stored.secret["client_secret"], "settings"
        path = config.GMAIL_CREDENTIALS_PATH
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                section = data.get("web") or data.get("installed") or {}
                if section.get("client_id") and section.get("client_secret"):
                    return section["client_id"], section["client_secret"], "file"
            except (OSError, ValueError):
                logger.warning("Could not read the Gmail OAuth client file", extra={"path": path})
        return None

    def save_gmail_client(self, client_id: str, client_secret: str, actor: str) -> None:
        client_id, client_secret = client_id.strip(), client_secret.strip()
        if not client_id.endswith(".apps.googleusercontent.com"):
            raise IntegrationError("That does not look like a Google OAuth client ID (it ends in .apps.googleusercontent.com).")
        if not client_secret:
            raise IntegrationError("Client secret is required.")
        self.store.put(
            GMAIL_OAUTH_CLIENT,
            {"client_id": client_id, "client_secret": client_secret},
            {"client_id": client_id},
            actor,
        )

    def remove_gmail_client(self) -> None:
        self.store.delete(GMAIL_OAUTH_CLIENT)

    # ---------------------------------------------------------- gmail connect

    def start_gmail_connect(self, actor: str, return_to: Optional[str] = None) -> str:
        """Authorization URL to send the admin's browser to."""
        client = self.gmail_client_config()
        if not client:
            raise IntegrationError("Add the Google OAuth client ID and secret first.")
        if return_to and return_to.rstrip("/") not in config.FRONTEND_ORIGINS:
            raise IntegrationError("Unknown dashboard address.")
        state = secrets.token_urlsafe(32)
        verifier, challenge = _pkce_pair()
        self.store.save_oauth_state(
            state,
            {"verifier": verifier, "actor": actor, "return_to": (return_to or "").rstrip("/"), "client_id": client[0]},
        )
        params = {
            "client_id": client[0],
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(config.GMAIL_SCOPES),
            "access_type": "offline",
            "prompt": "consent",  # always return a refresh token, also on reconnect
            "include_granted_scopes": "false",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

    def finish_gmail_connect(self, state: str, code: Optional[str], error: Optional[str]) -> Tuple[str, Dict[str, Any]]:
        """Complete the sign-in. Returns (dashboard origin to return to, connected account info)."""
        pending = self.store.pop_oauth_state(state)
        if not pending:
            raise IntegrationError("This sign-in link expired or was already used. Start again from Settings.", "expired")
        return_to = pending.get("return_to") or ""
        try:
            if error:
                raise IntegrationError("Google sign-in was cancelled or denied.", "denied")
            if not code:
                raise IntegrationError("Google did not return an authorization code.", "denied")
            client = self.gmail_client_config()
            if not client or client[0] != pending["client_id"]:
                raise IntegrationError("The OAuth client changed during sign-in. Start again.", "client_changed")
            client_id, client_secret, _ = client

            with self._http_factory() as http:
                res = http.post(
                    GOOGLE_TOKEN_URL,
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": self.redirect_uri,
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "code_verifier": pending["verifier"],
                    },
                )
                if res.status_code != 200:
                    logger.warning("Google token exchange failed", extra={"status": res.status_code})
                    raise IntegrationError("Google rejected the sign-in. Check the client ID, secret and redirect URI.", "exchange_failed")
                tokens = res.json()
                granted = set((tokens.get("scope") or "").split())
                if not set(config.GMAIL_SCOPES) <= granted:
                    raise IntegrationError("Read-only Gmail access was not granted.", "scope")
                if not tokens.get("refresh_token"):
                    raise IntegrationError("Google did not return a refresh token. Remove WorkFlowOS from your Google account's third-party access and connect again.", "no_refresh_token")
                profile = http.get(GMAIL_PROFILE_URL, headers={"Authorization": f"Bearer {tokens['access_token']}"})
                account = profile.json().get("emailAddress") if profile.status_code == 200 else None
        except httpx.HTTPError:
            logger.warning("Could not reach Google to finish the Gmail sign-in")
            err = IntegrationError("Could not reach Google. Check the server's internet connection and try again.", "network")
            err.return_to = return_to
            raise err
        except IntegrationError as e:
            e.return_to = return_to
            raise

        expiry = datetime.now(timezone.utc) + timedelta(seconds=int(tokens.get("expires_in", 3600)))
        secret = {
            "token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
            "token_uri": GOOGLE_TOKEN_URL,
            "client_id": client_id,
            "client_secret": client_secret,
            "scopes": list(config.GMAIL_SCOPES),
            # google-auth expects a naive UTC timestamp here
            "expiry": expiry.replace(tzinfo=None).isoformat(),
        }
        metadata = {"account": account}
        self.store.put(GMAIL_TOKEN, secret, metadata, pending.get("actor"))
        logger.info("Gmail connected", extra={"account": account, "actor": pending.get("actor")})
        return return_to, metadata

    def disconnect_gmail(self) -> None:
        stored = self.store.get(GMAIL_TOKEN)
        if stored and stored.secret.get("refresh_token"):
            try:
                with self._http_factory() as http:
                    http.post(GOOGLE_REVOKE_URL, data={"token": stored.secret["refresh_token"]})
            except httpx.HTTPError:
                logger.warning("Could not revoke the Gmail token at Google; removing it locally anyway")
        self.store.delete(GMAIL_TOKEN)

    # ------------------------------------------------------------------ slack

    def save_slack(self, bot_token: str, channel_id: str, actor: str) -> Dict[str, Any]:
        from app.services.slack_client import CHANNEL_REGEX, SlackApiClient

        bot_token, channel_id = bot_token.strip(), channel_id.strip()
        if not bot_token.startswith("xoxb-"):
            raise IntegrationError("Use a bot token (it starts with xoxb-).")
        if not CHANNEL_REGEX.match(channel_id):
            raise IntegrationError("Enter a channel ID such as C0123456789.")
        identity = SlackApiClient(bot_token=bot_token, default_channel_id=channel_id, http_client=self._http_factory()).identify()
        if not identity:
            raise IntegrationError("Slack rejected this token.")
        metadata = {"channel_id": channel_id, "team": identity.get("team"), "bot": identity.get("user")}
        self.store.put(SLACK, {"bot_token": bot_token}, metadata, actor)
        return metadata

    def remove_slack(self) -> None:
        self.store.delete(SLACK)

    # ---------------------------------------------------------------- hubspot

    def _hubspot_client(self, token: Optional[str] = None):
        from app.services.hubspot_client import HubSpotClient

        return HubSpotClient(access_token=token, http_client=self._http_factory())

    def save_hubspot(self, access_token: str, actor: str) -> Dict[str, Any]:
        """Store a HubSpot service key (or legacy private-app token) after checking it can read contacts."""
        token = access_token.strip()
        if len(token) < 20:
            raise IntegrationError("That does not look like a HubSpot access token.")
        ok, detail = self._hubspot_client(token).check_access()
        if not ok:
            raise IntegrationError(f"HubSpot did not accept this token: {detail}")
        account = self._hubspot_client(token).account_details() or {}
        previous = self.store.info(HUBSPOT)
        metadata = {
            **(previous.metadata if previous else {}),  # keep the chosen status property on reconnect
            "portal_id": account.get("portalId"),
            "ui_domain": account.get("uiDomain"),
        }
        self.store.put(HUBSPOT, {"access_token": token}, metadata, actor)
        return metadata

    def hubspot_properties(self):
        """Writable contact properties of the connected account (for the Settings picker)."""
        from app.services.hubspot_client import HubSpotError

        if not self.store.info(HUBSPOT):
            raise IntegrationError("Connect HubSpot first.")
        try:
            return self._hubspot_client().list_contact_properties()
        except HubSpotError as e:
            raise IntegrationError(f"Could not list HubSpot properties: {e}")

    def save_hubspot_settings(self, status_property: str, status_value: Optional[str], actor: str) -> Dict[str, Any]:
        """Which contact property hubspot.update_contact writes, and the value used when a run has none."""
        props = {p["name"]: p for p in self.hubspot_properties()}
        chosen = props.get(status_property.strip())
        if chosen is None:
            raise IntegrationError(f"'{status_property}' is not a writable HubSpot contact property.")
        value = (status_value or "").strip() or None
        if value and chosen["options"] and value not in chosen["options"]:
            raise IntegrationError(f"'{value}' is not one of the options of {chosen['label']}: {', '.join(chosen['options'])}.")
        self.store.update_metadata(
            HUBSPOT,
            {"status_property": chosen["name"], "status_property_label": chosen["label"], "status_value": value},
            actor,
        )
        return self.describe()["hubspot"]

    def remove_hubspot(self) -> None:
        self.store.delete(HUBSPOT)

    # ----------------------------------------------------------------- status

    def _describe_hubspot(self) -> Dict[str, Any]:
        info = self.store.info(HUBSPOT)
        meta = info.metadata if info else {}
        env = bool(os.getenv("HUBSPOT_ACCESS_TOKEN"))
        return {
            "configured": bool(info) or env,
            "source": "settings" if info else ("environment" if env else None),
            "portal_id": meta.get("portal_id"),
            "ui_domain": meta.get("ui_domain"),
            "status_property": meta.get("status_property"),
            "status_property_label": meta.get("status_property_label"),
            "status_value": meta.get("status_value"),
            "updated_at": info.updated_at if info else None,
            "updated_by": info.updated_by if info else None,
        }

    def describe(self) -> Dict[str, Any]:
        """Configuration summary for Settings. No secrets, no network calls."""
        gmail_token = self.store.info(GMAIL_TOKEN)
        client = self.gmail_client_config()
        slack = self.store.info(SLACK)
        env_slack = bool(os.getenv("SLACK_BOT_TOKEN"))
        token_file = os.path.exists(config.GMAIL_TOKEN_PATH)
        return {
            "gmail": {
                "connected": bool(gmail_token) or token_file,
                "source": "settings" if gmail_token else ("file" if token_file else None),
                "account": gmail_token.metadata.get("account") if gmail_token else None,
                "connected_at": gmail_token.updated_at if gmail_token else None,
                "connected_by": gmail_token.updated_by if gmail_token else None,
                "client_configured": client is not None,
                "client_source": client[2] if client else None,
                "client_id": client[0] if client else None,
                "redirect_uri": self.redirect_uri,
            },
            "hubspot": self._describe_hubspot(),
            "slack": {
                "configured": bool(slack) or env_slack,
                "source": "settings" if slack else ("environment" if env_slack else None),
                "channel_id": slack.metadata.get("channel_id") if slack else os.getenv("SLACK_CHANNEL_ID"),
                "team": slack.metadata.get("team") if slack else None,
                "updated_at": slack.updated_at if slack else None,
                "updated_by": slack.updated_by if slack else None,
            },
        }


def stored_slack_settings() -> Tuple[Optional[str], Optional[str]]:
    """(bot_token, channel_id) saved in Settings, or (None, None)."""
    try:
        stored = get_credential_store().get(SLACK)
    except Exception:
        logger.exception("Could not read Slack settings from the credential store")
        return None, None
    if not stored:
        return None, None
    return stored.secret.get("bot_token"), stored.metadata.get("channel_id")


_service: Optional[IntegrationService] = None


def get_integration_service() -> IntegrationService:
    global _service
    if _service is None:
        _service = IntegrationService()
    return _service

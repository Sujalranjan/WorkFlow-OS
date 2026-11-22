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
    GMAIL_OPTIONS,
    GMAIL_TOKEN,
    HUBSPOT,
    SHARED_FOLDER,
    SHEETS,
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

    # ---------------------------------------------------------- gmail options

    def gmail_labels_allowed(self) -> bool:
        info = self.store.info(GMAIL_OPTIONS)
        return bool(info and info.metadata.get("allow_labels"))

    def gmail_sheets_allowed(self) -> bool:
        info = self.store.info(GMAIL_OPTIONS)
        return bool(info and info.metadata.get("allow_sheets"))

    def set_gmail_options(self, allow_labels: Optional[bool], actor: str, allow_sheets: Optional[bool] = None) -> None:
        """Opt in to (or out of) labeling and Google Sheets. Turning one on takes effect at the next
        Connect Gmail, which then also asks Google for that permission (gmail.modify, spreadsheets).
        Turning it off stops it at once; reconnecting afterwards removes the permission at Google.
        An option left as None keeps its current value."""
        info = self.store.info(GMAIL_OPTIONS)
        current = dict(info.metadata) if info else {}
        if allow_labels is not None:
            current["allow_labels"] = bool(allow_labels)
        if allow_sheets is not None:
            current["allow_sheets"] = bool(allow_sheets)
        self.store.put(GMAIL_OPTIONS, {}, current, actor)

    def _gmail_requested_scopes(self) -> list:
        scopes = list(config.GMAIL_SCOPES)
        if self.gmail_labels_allowed():
            scopes.append(config.GMAIL_MODIFY_SCOPE)
        if self.gmail_sheets_allowed():
            scopes.append(config.SHEETS_SCOPE)
        return scopes

    # ------------------------------------------------------------ google sheets

    def save_sheet(self, spreadsheet: str, sheet: str, columns: list, actor: str, sheets_client=None) -> Dict[str, Any]:
        """Choose the spreadsheet and tab sheets.append_row writes to, and its columns.
        Checked with Google (needs the Sheets permission), so a typo or a sheet without access fails here."""
        from app.services.google_sheets import COLUMNS, GoogleSheetsClient, SheetsError, parse_spreadsheet_id

        spreadsheet_id = parse_spreadsheet_id(spreadsheet)
        if not spreadsheet_id:
            raise IntegrationError("Paste the spreadsheet's link or id (docs.google.com/spreadsheets/d/<id>/...).")
        unknown = [c for c in columns if c not in COLUMNS]
        if unknown or not columns:
            raise IntegrationError(f"Choose columns from: {', '.join(COLUMNS)}.")
        if len(set(columns)) != len(columns):
            raise IntegrationError("Each column can be used once.")
        client = sheets_client or GoogleSheetsClient()
        try:
            meta = client.spreadsheet(spreadsheet_id)
        except SheetsError as e:
            raise IntegrationError(str(e))
        tabs = meta["sheets"]
        tab = (sheet or "").strip() or tabs[0]
        if tab not in tabs:
            raise IntegrationError(f"The spreadsheet has no tab named '{tab}'. Tabs: {', '.join(tabs)}.")
        metadata = {"spreadsheet_id": spreadsheet_id, "title": meta["title"], "sheet": tab, "columns": list(columns)}
        self.store.put(SHEETS, {}, metadata, actor)
        return metadata

    def remove_sheet(self) -> None:
        self.store.delete(SHEETS)

    def _describe_sheets(self) -> Dict[str, Any]:
        from app.services.google_sheets import COLUMNS, DEFAULT_COLUMNS

        info = self.store.info(SHEETS)
        meta = info.metadata if info else {}
        return {
            "configured": bool(info),
            "spreadsheet_id": meta.get("spreadsheet_id"),
            "title": meta.get("title"),
            "sheet": meta.get("sheet"),
            "columns": meta.get("columns") or list(DEFAULT_COLUMNS),
            "available_columns": list(COLUMNS),
            "updated_at": info.updated_at if info else None,
            "updated_by": info.updated_by if info else None,
        }

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
            "scope": " ".join(self._gmail_requested_scopes()),
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

        # Google lets people untick a permission on the consent screen: keep what was really granted.
        # Stored as metadata, because the reading client rewrites the secret when it refreshes.
        granted_scopes = sorted(set(self._gmail_requested_scopes()) & granted)
        expiry = datetime.now(timezone.utc) + timedelta(seconds=int(tokens.get("expires_in", 3600)))
        secret = {
            "token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
            "token_uri": GOOGLE_TOKEN_URL,
            "client_id": client_id,
            "client_secret": client_secret,
            "scopes": granted_scopes,
            # google-auth expects a naive UTC timestamp here
            "expiry": expiry.replace(tzinfo=None).isoformat(),
        }
        metadata = {"account": account, "scopes": granted_scopes}
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

    def _slack_token(self, bot_token: Optional[str]) -> str:
        """The token being set up, or (when none is given) the one already saved in Settings."""
        token = (bot_token or "").strip()
        if not token:
            stored = self.store.get(SLACK)
            token = (stored.secret.get("bot_token") or "") if stored else ""
            if not token:
                raise IntegrationError("Paste the Slack bot token first.")
        if not token.startswith("xoxb-"):
            raise IntegrationError("Use a bot token (it starts with xoxb-).")
        return token

    def slack_channels(self, bot_token: Optional[str] = None) -> Dict[str, Any]:
        """Channels for the Settings picker. Without the channels:read scope the list is empty and
        `can_list` is False, and Settings asks for the channel id instead."""
        from app.services.slack_client import SlackApiClient, SlackApiError, SlackClientError

        client = SlackApiClient(bot_token=self._slack_token(bot_token), http_client=self._http_factory())
        try:
            channels, notes = client.list_channels()
        except SlackApiError as e:
            if e.error_code == "missing_scope":
                return {
                    "can_list": False,
                    "channels": [],
                    "notes": ["This token cannot list channels (add the channels:read scope). You can type the channel id instead."],
                }
            if e.error_code in ("invalid_auth", "not_authed", "account_inactive", "token_revoked"):
                raise IntegrationError("Slack rejected this token.")
            raise IntegrationError(f"Slack could not list channels ({e.error_code}).")
        except SlackClientError as e:
            raise IntegrationError(str(e))
        return {"can_list": True, "channels": channels, "notes": notes}

    def save_slack(self, bot_token: Optional[str], channel_id: str, actor: str) -> Dict[str, Any]:
        """Save the bot token (or keep the saved one) and the default channel.

        Also records whether the bot is a member of the channel (bots can only post to channels they
        were invited to), so Settings can warn without calling Slack on every page load. When the
        token cannot read channel info (no channels:read), membership is unknown (None).
        """
        from app.services.slack_client import CHANNEL_REGEX, SlackApiClient, SlackApiError, SlackClientError

        token, channel_id = self._slack_token(bot_token), channel_id.strip()
        if not CHANNEL_REGEX.match(channel_id):
            raise IntegrationError("Enter a channel ID such as C0123456789.")
        client = SlackApiClient(bot_token=token, default_channel_id=channel_id, http_client=self._http_factory())
        identity = client.identify()
        if not identity:
            raise IntegrationError("Slack rejected this token.")
        channel_name, member = None, None
        try:
            info = client.channel_info(channel_id)
            channel_name, member = info.get("name"), info.get("is_member")
        except SlackApiError as e:
            if e.error_code == "channel_not_found":
                raise IntegrationError(
                    "Slack cannot find that channel. Check the id; for a private channel, invite the bot first."
                )
            if e.error_code != "missing_scope":
                logger.warning("Could not check Slack channel membership: %s", e.error_code)
        except SlackClientError:
            logger.warning("Could not check Slack channel membership (Slack unreachable)")
        metadata = {
            "channel_id": channel_id,
            "channel_name": channel_name,
            "bot_in_channel": member,
            "team": identity.get("team"),
            "bot": identity.get("user"),
        }
        self.store.put(SLACK, {"bot_token": token}, metadata, actor)
        return metadata

    def remove_slack(self) -> None:
        self.store.delete(SLACK)

    # ---------------------------------------------------------- shared folder

    def save_shared_folder(self, folder: str, actor: str) -> Dict[str, Any]:
        """Choose the folder files.save_to_folder copies into (a path on the WorkFlowOS server)."""
        from app.services.shared_folder import SharedFolderError, check_folder

        try:
            resolved = check_folder(folder)
        except SharedFolderError as e:
            raise IntegrationError(str(e))
        metadata = {"folder": str(resolved)}
        self.store.put(SHARED_FOLDER, {}, metadata, actor)
        return metadata

    def remove_shared_folder(self) -> None:
        self.store.delete(SHARED_FOLDER)

    def _describe_shared_folder(self) -> Dict[str, Any]:
        from app.services.shared_folder import configured_folder, folder_status

        folder, source = configured_folder()
        info = self.store.info(SHARED_FOLDER)
        ready, detail = folder_status()
        return {
            "configured": bool(folder),
            "source": source,
            "folder": folder,
            "ready": ready,
            "detail": detail,
            "updated_at": info.updated_at if info else None,
            "updated_by": info.updated_by if info else None,
        }

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
                # labeling: opted in (Settings) and granted by Google at the last Connect Gmail
                "labels_allowed": self.gmail_labels_allowed(),
                "can_label": bool(gmail_token)
                and config.GMAIL_MODIFY_SCOPE in (gmail_token.metadata.get("scopes") or []),
                "sheets_allowed": self.gmail_sheets_allowed(),
                "can_use_sheets": bool(gmail_token)
                and config.SHEETS_SCOPE in (gmail_token.metadata.get("scopes") or []),
            },
            "sheets": self._describe_sheets(),
            "hubspot": self._describe_hubspot(),
            "files": self._describe_shared_folder(),
            "slack": {
                "configured": bool(slack) or env_slack,
                "source": "settings" if slack else ("environment" if env_slack else None),
                "channel_id": slack.metadata.get("channel_id") if slack else os.getenv("SLACK_CHANNEL_ID"),
                "channel_name": slack.metadata.get("channel_name") if slack else None,
                # True/False as checked when saved; None when unknown (token without channels:read)
                "bot_in_channel": slack.metadata.get("bot_in_channel") if slack else None,
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

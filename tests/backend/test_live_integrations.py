"""Phase 3 integrations against real test accounts. Never part of an ordinary run.

Run with WORKFLOWOS_LIVE_TESTS=1 (see README "Live tests"). Each test is skipped unless its own
variables are set. Everything here only reads, except the Slack test, which posts one message and
one thread reply to SLACK_CHANNEL_ID (use a test channel).
"""

import json
import os
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.live


def _need(*names):
    missing = [n for n in names if not os.getenv(n)]
    if missing:
        pytest.skip(f"set {', '.join(missing)} to run this live test")
    return [os.environ[n] for n in names]


def test_live_slack_post_reply_and_channels():
    from app.services.slack_client import SlackApiClient

    token, channel = _need("SLACK_BOT_TOKEN", "SLACK_CHANNEL_ID")
    client = SlackApiClient(bot_token=token, default_channel_id=channel)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    parent = client.send_notification(text=f"WorkFlowOS live test {stamp}")
    reply = client.send_notification(channel=parent.channel, text="WorkFlowOS live test: thread reply", thread_ts=parent.ts)
    assert client.verify_message(parent.channel, parent.ts)[0]
    assert client.verify_reply(parent.channel, parent.ts, reply.ts)[0]
    try:
        channels, _ = client.list_channels()
    except Exception as e:  # token without channels:read: the picker falls back to typing the id
        pytest.skip(f"channel listing not available for this token: {e}")
    assert any(c["id"] == parent.channel for c in channels)


def test_live_hubspot_access_search_and_properties():
    from app.services.hubspot_client import HubSpotClient

    (token,) = _need("HUBSPOT_ACCESS_TOKEN")
    client = HubSpotClient(access_token=token)
    ok, detail = client.check_access()
    assert ok, detail
    assert client.list_contact_properties(), "the account should have writable contact properties"
    email = os.getenv("WORKFLOWOS_LIVE_HUBSPOT_EMAIL")
    if email:
        assert [c.email.lower() for c in client.find_contacts(email)] == [email.lower()]


def _google_service(api: str, version: str, scope: str):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    (path,) = _need("WORKFLOWOS_LIVE_GOOGLE_TOKEN")
    with open(path, encoding="utf-8") as f:
        info = json.load(f)
    granted = info.get("scopes") or []
    if scope not in granted:
        pytest.skip(f"the token in WORKFLOWOS_LIVE_GOOGLE_TOKEN was not granted {scope}")
    return build(api, version, credentials=Credentials.from_authorized_user_info(info, granted), cache_discovery=False)


def test_live_gmail_user_labels():
    from app import config
    from app.services.gmail_labels import GmailLabeler

    labeler = GmailLabeler(service=_google_service("gmail", "v1", config.GMAIL_MODIFY_SCOPE), check_permission=False)
    labels = labeler.user_labels()
    assert all(not label["id"] in ("INBOX", "TRASH", "SPAM") for label in labels)  # system labels never offered


def test_live_sheets_metadata():
    from app import config
    from app.services.google_sheets import GoogleSheetsClient

    (sheet_id,) = _need("WORKFLOWOS_LIVE_SHEET_ID")
    client = GoogleSheetsClient(service=_google_service("sheets", "v4", config.SHEETS_SCOPE), check_permission=False)
    meta = client.spreadsheet(sheet_id)
    assert meta["title"] and meta["sheets"]

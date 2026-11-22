"""'Add to Slack': app credentials, HTTPS-only start, single-use state per provider, code exchange,
and keeping the chosen channel and alerts when the bot token is replaced."""

from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import httpx
import pytest

from app import config
import app.main as main
from app.services import integrations as integrations_module
from app.services.credential_store import SLACK, SLACK_OAUTH_CLIENT, CredentialStore

DASHBOARD = "https://wfos.example.com"
CLIENT_ID = "1234567890.987654321"
CLIENT_SECRET = "0123456789abcdef0123456789abcdef"


class FakeSlackOAuth:
    def __init__(self):
        self.exchanges = []
        self.response = {
            "ok": True, "token_type": "bot", "access_token": "xoxb-installed-token-1",
            "scope": "chat:write,channels:history,channels:read", "team": {"id": "T1", "name": "Acme"}, "bot_user_id": "U0BOT",
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert str(request.url) == integrations_module.SLACK_TOKEN_URL
        form = parse_qs(request.content.decode())
        self.exchanges.append((request.headers.get("authorization"), form))
        return httpx.Response(200, json=self.response)

    def factory(self):
        return httpx.Client(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_API_URL", DASHBOARD)
    monkeypatch.setattr(config, "FRONTEND_ORIGINS", [DASHBOARD])
    monkeypatch.delenv("SLACK_CLIENT_ID", raising=False)
    store = CredentialStore(str(tmp_path / "c.db"), Fernet.generate_key())
    fake = FakeSlackOAuth()
    svc = integrations_module.IntegrationService(store=store, http_factory=fake.factory)
    monkeypatch.setattr(integrations_module, "_service", svc)
    return TestClient(main.create_app()), store, fake, svc


def _start(client):
    res = client.post("/api/integrations/slack/connect", json={"return_to": DASHBOARD})
    assert res.status_code == 200, res.text
    url = urlparse(res.json()["authorization_url"])
    assert f"{url.scheme}://{url.netloc}{url.path}" == integrations_module.SLACK_AUTHORIZE_URL
    return {k: v[0] for k, v in parse_qs(url.query).items()}


def test_add_to_slack_end_to_end(setup):
    client, store, fake, _ = setup
    assert client.post("/api/integrations/slack/connect", json={}).status_code == 400  # no app yet
    assert client.put("/api/integrations/slack/app", json={"client_id": "nope-nope", "client_secret": CLIENT_SECRET}).status_code == 400
    saved = client.put("/api/integrations/slack/app", json={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET})
    assert saved.status_code == 200 and CLIENT_SECRET not in saved.text
    assert saved.json()["slack"]["redirect_uri"] == f"{DASHBOARD}/api/integrations/slack/callback"

    # an earlier pasted token with a chosen channel and alerts
    store.put(SLACK, {"bot_token": "xoxb-old"}, {"channel_id": "C0OPS00001", "alert_channel_id": "C0ALERT001", "team": "Old"})
    params = _start(client)
    assert params["client_id"] == CLIENT_ID and "chat:write" in params["scope"].split(",")
    res = client.get("/api/integrations/slack/callback", params={"state": params["state"], "code": "c0de"}, follow_redirects=False)
    assert res.status_code == 303 and res.headers["location"] == f"{DASHBOARD}/#/settings/slack-connected"

    (auth, form), = fake.exchanges
    assert auth.startswith("Basic ") and form["code"] == ["c0de"]  # the secret goes in the header, not the URL
    rec = store.get(SLACK)
    assert rec.secret["bot_token"] == "xoxb-installed-token-1"
    assert rec.metadata["channel_id"] == "C0OPS00001" and rec.metadata["alert_channel_id"] == "C0ALERT001"  # kept
    assert rec.metadata["team"] == "Acme" and rec.metadata["installed_with"] == "add_to_slack"

    again = client.get("/api/integrations/slack/callback", params={"state": params["state"], "code": "c0de"}, follow_redirects=False)
    assert again.headers["location"].endswith("/#/settings/slack-error/expired")  # single use


def test_states_cannot_cross_providers(setup):
    client, store, fake, svc = setup
    store.put(SLACK_OAUTH_CLIENT, {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}, {})
    slack_state = _start(client)["state"]
    gmail = client.get("/api/integrations/gmail/callback", params={"state": slack_state, "code": "x"}, follow_redirects=False)
    assert gmail.headers["location"].endswith("/#/settings/gmail-error/expired")

    store.save_oauth_state("gmail-state", {"provider": "gmail", "client_id": "x", "verifier": "v"})
    slack = client.get("/api/integrations/slack/callback", params={"state": "gmail-state", "code": "x"}, follow_redirects=False)
    assert slack.headers["location"].endswith("/#/settings/slack-error/expired")
    assert fake.exchanges == []


def test_refusals(setup, monkeypatch):
    client, store, fake, _ = setup
    store.put(SLACK_OAUTH_CLIENT, {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}, {})
    denied = client.get("/api/integrations/slack/callback", params={"state": _start(client)["state"], "error": "access_denied"},
                        follow_redirects=False)
    assert denied.headers["location"].endswith("/#/settings/slack-error/denied")

    fake.response = {"ok": True, "token_type": "user", "access_token": "xoxp-user"}  # never store a user token
    bad = client.get("/api/integrations/slack/callback", params={"state": _start(client)["state"], "code": "c"}, follow_redirects=False)
    assert bad.headers["location"].endswith("/#/settings/slack-error/exchange_failed") and store.get(SLACK) is None

    assert client.post("/api/integrations/slack/connect", json={"return_to": "https://evil.example"}).status_code == 400
    monkeypatch.setattr(config, "PUBLIC_API_URL", "http://localhost:8000")
    plain = client.post("/api/integrations/slack/connect", json={})
    assert plain.status_code == 400 and "HTTPS" in plain.json()["detail"]

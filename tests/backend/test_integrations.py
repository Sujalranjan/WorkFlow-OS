"""Encrypted credential store, "Connect Gmail" web OAuth and Slack settings."""

from datetime import datetime, timedelta, timezone
import json
import sqlite3
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import httpx
import pytest

from app import config, security
from app.main import create_app
from app.services import integrations as integrations_module
from app.services.credential_store import (
    GMAIL_TOKEN,
    SLACK,
    CredentialStore,
    CredentialStoreError,
    load_or_create_key,
    set_credential_store,
)
from app.services.gmail_client import GmailApiClient
from app.services.integrations import IntegrationError, IntegrationService
from app.services.slack_client import SlackApiClient

CLIENT_ID = "1234-abc.apps.googleusercontent.com"
CLIENT_SECRET = "GOCSPX-test-client-secret"
REFRESH = "1//refresh-token-value"
DASHBOARD = config.FRONTEND_ORIGINS[0]


@pytest.fixture
def store(tmp_path):
    s = CredentialStore(str(tmp_path / "creds.db"), Fernet.generate_key())
    set_credential_store(s)
    yield s
    set_credential_store(None)


class FakeGoogle:
    """Mock transport for Google's token, profile and revoke endpoints and Slack's auth.test."""

    def __init__(self) -> None:
        self.calls = []
        self.token_response = {
            "access_token": "ya29.access",
            "refresh_token": REFRESH,
            "expires_in": 3599,
            "scope": "https://www.googleapis.com/auth/gmail.readonly",
            "token_type": "Bearer",
        }
        self.slack_ok = True

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        url = str(request.url)
        if url.startswith(integrations_module.GOOGLE_TOKEN_URL):
            return httpx.Response(200, json=self.token_response)
        if url.startswith(integrations_module.GMAIL_PROFILE_URL):
            assert request.headers["authorization"] == "Bearer ya29.access"
            return httpx.Response(200, json={"emailAddress": "ops@example.com"})
        if url.startswith(integrations_module.GOOGLE_REVOKE_URL):
            return httpx.Response(200)
        if url.endswith("/auth.test"):
            if self.slack_ok:
                return httpx.Response(200, json={"ok": True, "team": "Acme", "user": "workflowos"})
            return httpx.Response(200, json={"ok": False, "error": "invalid_auth"})
        return httpx.Response(404)

    def factory(self):
        return httpx.Client(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def google():
    return FakeGoogle()


@pytest.fixture
def service(store, google, monkeypatch):
    svc = IntegrationService(store=store, http_factory=google.factory, redirect_uri="http://localhost:8000/api/integrations/gmail/callback")
    monkeypatch.setattr(integrations_module, "_service", svc)
    monkeypatch.setattr(config, "GMAIL_CREDENTIALS_PATH", "does-not-exist.json")
    monkeypatch.setattr(config, "GMAIL_TOKEN_PATH", "does-not-exist-token.json")
    return svc


# ----------------------------------------------------------------- store


def test_secrets_are_encrypted_at_rest(store):
    store.put(SLACK, {"bot_token": "xoxb-super-secret"}, {"channel_id": "C123"}, "admin@example.com")
    with sqlite3.connect(store.db_path) as conn:
        raw = conn.execute("SELECT ciphertext, metadata_json FROM integration_credentials").fetchone()
    assert b"xoxb-super-secret" not in raw[0]
    assert "xoxb" not in raw[1]

    got = store.get(SLACK)
    assert got.secret == {"bot_token": "xoxb-super-secret"}
    assert got.metadata == {"channel_id": "C123"} and got.updated_by == "admin@example.com"
    assert store.info(SLACK).secret == {}


def test_wrong_key_reads_as_missing(store):
    store.put(GMAIL_TOKEN, {"token": "x"})
    other = CredentialStore(store.db_path, Fernet.generate_key())
    assert other.get(GMAIL_TOKEN) is None
    assert other.info(GMAIL_TOKEN) is not None  # metadata is still visible, so Settings can say "reconnect"


def test_key_file_is_created_once_and_env_key_is_validated(tmp_path, monkeypatch):
    monkeypatch.delenv("WORKFLOWOS_SECRET_KEY", raising=False)
    path = str(tmp_path / "keys" / "secret.key")
    first = load_or_create_key(path)
    assert load_or_create_key(path) == first
    Fernet(first)

    monkeypatch.setenv("WORKFLOWOS_SECRET_KEY", "not-a-key")
    with pytest.raises(CredentialStoreError):
        load_or_create_key(path)
    good = Fernet.generate_key().decode()
    monkeypatch.setenv("WORKFLOWOS_SECRET_KEY", good)
    assert load_or_create_key(path) == good.encode()


def test_oauth_state_is_single_use_and_expires(store):
    store.save_oauth_state("s1", {"verifier": "v"})
    assert store.pop_oauth_state("s1") == {"verifier": "v"}
    assert store.pop_oauth_state("s1") is None
    assert store.pop_oauth_state("") is None

    store.save_oauth_state("s2", {"verifier": "v"})
    with sqlite3.connect(store.db_path) as conn:
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        conn.execute("UPDATE oauth_states SET expires_at = ?", (past,))
    assert store.pop_oauth_state("s2") is None


# ------------------------------------------------------------ gmail oauth


def _start(client: TestClient) -> dict:
    client.put("/api/integrations/gmail/client", json={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET})
    res = client.post("/api/integrations/gmail/connect", json={"return_to": DASHBOARD})
    assert res.status_code == 200, res.text
    return {k: v[0] for k, v in parse_qs(urlparse(res.json()["authorization_url"]).query).items()}


def test_connect_gmail_end_to_end(service, store, google):
    client = TestClient(create_app())
    params = _start(client)
    assert params["client_id"] == CLIENT_ID
    assert params["scope"] == "https://www.googleapis.com/auth/gmail.readonly"
    assert params["access_type"] == "offline" and params["code_challenge_method"] == "S256"
    assert params["redirect_uri"] == service.redirect_uri

    res = client.get("/api/integrations/gmail/callback", params={"state": params["state"], "code": "auth-code"}, follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == f"{DASHBOARD}/#/settings/gmail-connected"

    exchange = next(c for c in google.calls if str(c.url).startswith(integrations_module.GOOGLE_TOKEN_URL))
    form = parse_qs(exchange.content.decode())
    assert form["code"] == ["auth-code"] and form["client_secret"] == [CLIENT_SECRET]
    assert len(form["code_verifier"][0]) >= 43  # PKCE verifier sent with the exchange

    token = store.get(GMAIL_TOKEN)
    assert token.secret["refresh_token"] == REFRESH and token.metadata == {"account": "ops@example.com"}
    assert token.updated_by == "test-admin@example.com"

    described = client.get("/api/integrations").json()
    assert described["gmail"]["connected"] and described["gmail"]["account"] == "ops@example.com"
    body = json.dumps(described)
    assert CLIENT_SECRET not in body and REFRESH not in body and "ya29" not in body

    # The state cannot be replayed
    again = client.get("/api/integrations/gmail/callback", params={"state": params["state"], "code": "auth-code"}, follow_redirects=False)
    assert again.headers["location"].endswith("/#/settings/gmail-error/expired")


def test_denied_and_missing_refresh_token_store_nothing(service, store, google):
    client = TestClient(create_app())
    denied = client.get(
        "/api/integrations/gmail/callback", params={"state": _start(client)["state"], "error": "access_denied"}, follow_redirects=False
    )
    assert denied.headers["location"] == f"{DASHBOARD}/#/settings/gmail-error/denied"

    del google.token_response["refresh_token"]
    no_refresh = client.get(
        "/api/integrations/gmail/callback", params={"state": _start(client)["state"], "code": "c"}, follow_redirects=False
    )
    assert no_refresh.headers["location"].endswith("/gmail-error/no_refresh_token")
    assert store.get(GMAIL_TOKEN) is None


def test_connect_requires_client_and_known_dashboard(service):
    with pytest.raises(IntegrationError, match="client ID"):
        service.start_gmail_connect("admin")
    service.save_gmail_client(CLIENT_ID, CLIENT_SECRET, "admin")
    with pytest.raises(IntegrationError, match="Unknown dashboard"):
        service.start_gmail_connect("admin", return_to="https://evil.example")
    with pytest.raises(IntegrationError, match="googleusercontent"):
        service.save_gmail_client("not-a-client-id", "x", "admin")


def test_disconnect_revokes_at_google(service, store, google):
    store.put(GMAIL_TOKEN, {"refresh_token": REFRESH}, {"account": "ops@example.com"})
    service.disconnect_gmail()
    assert store.get(GMAIL_TOKEN) is None
    revoke = next(c for c in google.calls if str(c.url).startswith(integrations_module.GOOGLE_REVOKE_URL))
    assert parse_qs(revoke.content.decode())["token"] == [REFRESH]


def test_gmail_client_uses_and_refreshes_the_stored_token(store, monkeypatch):
    expired = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(tzinfo=None).isoformat()
    store.put(
        GMAIL_TOKEN,
        {
            "token": "old-access",
            "refresh_token": REFRESH,
            "token_uri": integrations_module.GOOGLE_TOKEN_URL,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "scopes": config.GMAIL_SCOPES,
            "expiry": expired,
        },
        {"account": "ops@example.com"},
    )
    from google.oauth2.credentials import Credentials

    def fake_refresh(self, request):
        self.token = "new-access"
        self.expiry = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)

    monkeypatch.setattr(Credentials, "refresh", fake_refresh)

    client = GmailApiClient(credential_store=store)
    assert client.is_configured() and client.is_authenticated()
    assert client.check_access() == (True, "Read-only access.")
    refreshed = store.get(GMAIL_TOKEN)
    assert refreshed.secret["token"] == "new-access"
    assert refreshed.metadata == {"account": "ops@example.com"}  # metadata survives a refresh

    # An explicit token file means file mode only (CLI sign-in script, tests)
    assert GmailApiClient(token_path="missing.json", credentials_path="missing.json", credential_store=store).is_configured() is False


# ------------------------------------------------------------------ slack


def test_slack_settings_are_validated_and_used_by_the_client(service, store, google, monkeypatch):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    client = TestClient(create_app())

    google.slack_ok = False
    bad = client.put("/api/integrations/slack", json={"bot_token": "xoxb-rejected-token", "channel_id": "C0123456789"})
    assert bad.status_code == 400 and store.get(SLACK) is None
    assert client.put("/api/integrations/slack", json={"bot_token": "xoxp-user-token", "channel_id": "C0123456789"}).status_code == 400

    google.slack_ok = True
    ok = client.put("/api/integrations/slack", json={"bot_token": "xoxb-good-token-123", "channel_id": "C0123456789"})
    assert ok.status_code == 200
    assert ok.json()["slack"] == {
        "configured": True,
        "source": "settings",
        "channel_id": "C0123456789",
        "team": "Acme",
        "updated_at": ok.json()["slack"]["updated_at"],
        "updated_by": "test-admin@example.com",
    }
    assert "xoxb-good" not in ok.text

    slack = SlackApiClient()
    assert slack._bot_token == "xoxb-good-token-123" and slack.default_channel_id == "C0123456789"
    # explicit arguments still win
    assert SlackApiClient(bot_token="xoxb-explicit", default_channel_id="C999").default_channel_id == "C999"

    assert client.delete("/api/integrations/slack").json()["slack"]["configured"] is False
    assert SlackApiClient()._bot_token is None


# ------------------------------------------------------------------- access


@pytest.mark.real_auth
def test_only_admins_manage_integrations(tmp_path, monkeypatch, store):
    from app.models.auth import CreateUserRequest, Role
    from app.repositories.auth_repository import AuthRepository
    from app.services.auth_service import AuthService

    auth = AuthService(AuthRepository(str(tmp_path / "auth.db")))
    monkeypatch.setattr(security, "_auth_service", auth)
    for role in Role:
        auth.create_user(CreateUserRequest(email=f"{role.value}@example.com", name=role.value, role=role, password="correct-horse-battery"))
    app = create_app()
    csrf = {"X-WorkflowOS-CSRF": "1"}

    def signed_in(role: Role) -> TestClient:
        c = TestClient(app)
        assert c.post("/api/auth/login", json={"email": f"{role.value}@example.com", "password": "correct-horse-battery"}).status_code == 200
        return c

    approver = signed_in(Role.APPROVER)
    assert approver.get("/api/integrations").status_code == 403
    assert approver.put("/api/integrations/slack", json={"bot_token": "xoxb-1234567890", "channel_id": "C1"}, headers=csrf).status_code == 403
    assert signed_in(Role.ADMIN).get("/api/integrations").status_code == 200
    # The callback is reachable without a session, but only a valid state does anything
    anon = TestClient(app).get("/api/integrations/gmail/callback", params={"state": "forged", "code": "x"}, follow_redirects=False)
    assert anon.status_code == 303 and anon.headers["location"].endswith("/gmail-error/expired")


# ------------------------------------------------- changes apply without a restart


def test_long_lived_clients_see_settings_changes(store, monkeypatch):
    """The executor registry and trigger poller keep one client for the life of the server."""
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_CHANNEL_ID", raising=False)
    slack = SlackApiClient()  # created before anything is configured, like at server start
    assert slack._bot_token is None
    store.put(SLACK, {"bot_token": "xoxb-saved-later"}, {"channel_id": "C0LATER"})
    assert slack._bot_token == "xoxb-saved-later" and slack.default_channel_id == "C0LATER"
    store.delete(SLACK)
    assert slack._bot_token is None and slack.default_channel_id is None

    from google.oauth2.credentials import Credentials
    import googleapiclient.discovery

    built = []
    monkeypatch.setattr(googleapiclient.discovery, "build", lambda *a, **k: built.append(k["credentials"].refresh_token) or object())
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(tzinfo=None).isoformat()

    def connect(refresh: str) -> None:
        store.put(GMAIL_TOKEN, {
            "token": "access", "refresh_token": refresh, "token_uri": integrations_module.GOOGLE_TOKEN_URL,
            "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "scopes": config.GMAIL_SCOPES, "expiry": future,
        })

    monkeypatch.setattr(config, "GMAIL_CREDENTIALS_PATH", "does-not-exist.json")
    gmail = GmailApiClient(credential_store=store)
    connect("refresh-account-a")
    first = gmail.get_service()
    assert gmail.get_service() is first  # same sign-in: reused
    connect("refresh-account-b")
    assert gmail.get_service() is not first and built == ["refresh-account-a", "refresh-account-b"]

    store.delete(GMAIL_TOKEN)
    assert gmail.is_configured() is False  # Disconnect stops it immediately


def test_google_unreachable_during_callback_shows_a_message(service, store):
    def offline():
        def handler(request):
            raise httpx.ConnectError("offline", request=request)
        return httpx.Client(transport=httpx.MockTransport(handler))

    service._http_factory = offline
    client = TestClient(create_app())
    res = client.get("/api/integrations/gmail/callback", params={"state": _start(client)["state"], "code": "c"}, follow_redirects=False)
    assert res.status_code == 303 and res.headers["location"] == f"{DASHBOARD}/#/settings/gmail-error/network"
    assert store.get(GMAIL_TOKEN) is None


def test_key_file_created_concurrently_is_shared(tmp_path, monkeypatch):
    monkeypatch.delenv("WORKFLOWOS_SECRET_KEY", raising=False)
    path = tmp_path / "secret.key"
    existing = Fernet.generate_key()
    real_open = __import__("os").open

    def racing_open(p, flags, mode=0o777):
        # Another process writes the key between our exists() check and our create.
        path.write_bytes(existing)
        return real_open(p, flags, mode)

    monkeypatch.setattr("app.services.credential_store.os.open", racing_open)
    assert load_or_create_key(str(path)) == existing

"""Shared pytest configuration.

Isolation guarantees:
- Every test session writes to a throwaway directory: the WorkFlowOS database, the
  Demo CRM database and the execution sandbox never touch the developer's real files.
- Live external integrations (Gemini, Slack, Gmail) are OFF by default. Secrets from the
  root .env are scrubbed so an ordinary `pytest` run can never post to Slack or call an
  LLM. Opt in with `WORKFLOWOS_LIVE_TESTS=1`, which keeps the .env values and runs tests
  marked `@pytest.mark.live`.
"""

import os
import sys
import tempfile

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
backend_dir = os.path.join(root_dir, "backend")
agent_dir = os.path.join(root_dir, "desktop-agent")

for _p in (root_dir, backend_dir, agent_dir):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from dotenv import load_dotenv  # noqa: E402

LIVE_TESTS = os.getenv("WORKFLOWOS_LIVE_TESTS", "").lower() in ("1", "true", "yes")

env_path = os.path.join(root_dir, ".env")
if LIVE_TESTS and os.path.exists(env_path):
    load_dotenv(dotenv_path=env_path, override=False)

# Session-wide isolated storage. Must be set BEFORE any `app.*` import because
# repositories capture their default database path at import time.
_TEST_DATA_DIR = tempfile.mkdtemp(prefix="workflowos-tests-")
os.environ["DATABASE_PATH"] = os.path.join(_TEST_DATA_DIR, "workflowos_test.db")
os.environ["CRM_DATABASE_PATH"] = os.path.join(_TEST_DATA_DIR, "crm_test.db")
os.environ["WORKFLOWOS_SANDBOX_DIR"] = os.path.join(_TEST_DATA_DIR, "sandbox")
# Prevent app.config from re-reading the developer's .env and overriding the above.
os.environ["WORKFLOWOS_SKIP_DOTENV"] = "1"
# Tests drive trigger polling explicitly; never start the background poller.
os.environ["TRIGGER_POLLER_ENABLED"] = "false"

if not LIVE_TESTS:
    for _secret in ("GEMINI_API_KEY", "SLACK_BOT_TOKEN", "SLACK_CHANNEL_ID"):
        os.environ.pop(_secret, None)
    os.environ["GMAIL_ENABLED"] = "false"

import pytest  # noqa: E402

import app.config  # noqa: E402,F401


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live: talks to real external services (Gemini/Slack/Gmail); run with WORKFLOWOS_LIVE_TESTS=1",
    )
    config.addinivalue_line(
        "markers",
        "real_auth: exercise real sign-in, sessions, roles and API keys instead of the test admin",
    )


TEST_ADMIN_EMAIL = "test-admin@example.com"


@pytest.fixture(autouse=True)
def _signed_in_as_test_admin(request, monkeypatch):
    """API tests about workflows run as a signed-in admin; `real_auth` tests use real credentials."""
    if request.node.get_closest_marker("real_auth"):
        return
    from app import security
    from app.models.auth import Principal, Role, User

    admin = Principal(kind="user", user=User(email=TEST_ADMIN_EMAIL, name="Test Admin", role=Role.ADMIN))
    monkeypatch.setattr(security, "resolve_principal", lambda _request: admin)


def pytest_collection_modifyitems(config, items):
    if LIVE_TESTS:
        return
    skip_live = pytest.mark.skip(reason="live integration test; set WORKFLOWOS_LIVE_TESTS=1 to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)

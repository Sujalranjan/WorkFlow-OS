"""Backend configuration settings."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Locate and load the root .env file if present
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"
# Real environment variables take precedence over .env (12-factor convention).
# WORKFLOWOS_SKIP_DOTENV=1 disables .env loading entirely (used by the test suite).
if os.getenv("WORKFLOWOS_SKIP_DOTENV", "").lower() not in ("1", "true", "yes"):
    if _ENV_PATH.exists():
        load_dotenv(dotenv_path=_ENV_PATH, override=False)
    else:
        load_dotenv(override=False)

PROJECT_NAME = "WorkFlowOS Backend"
VERSION = "0.1.0"
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
HOST = os.getenv("BACKEND_HOST", "127.0.0.1")
PORT = int(os.getenv("BACKEND_PORT", "8000"))
DATABASE_PATH = os.getenv("DATABASE_PATH", "workflowos.db")
CRM_DATABASE_PATH = os.getenv("CRM_DATABASE_PATH", "crm.db")
SANDBOX_DIR = os.getenv("WORKFLOWOS_SANDBOX_DIR", "workflowos_sandbox")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

# Gmail API Integration Configuration (Read-Only)
GMAIL_ENABLED = os.getenv("GMAIL_ENABLED", "false").lower() in ("true", "1", "yes")
GMAIL_CREDENTIALS_PATH = os.getenv("GMAIL_CREDENTIALS_PATH", "credentials.json")
GMAIL_TOKEN_PATH = os.getenv("GMAIL_TOKEN_PATH", "token.json")
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
GMAIL_SEARCH_QUERY = os.getenv("GMAIL_SEARCH_QUERY", "from:me")
GMAIL_MAX_RESULTS = int(os.getenv("GMAIL_MAX_RESULTS", "5"))

# Email triggers: background polling of enabled triggers (each trigger has its own interval)
TRIGGER_POLLER_ENABLED = os.getenv("TRIGGER_POLLER_ENABLED", "true").lower() in ("true", "1", "yes")
TRIGGER_POLLER_TICK_SECONDS = float(os.getenv("TRIGGER_POLLER_TICK_SECONDS", "15"))

# Authentication
SESSION_COOKIE_NAME = "wfos_session"
SESSION_TTL_HOURS = int(os.getenv("SESSION_TTL_HOURS", "12"))
# Send the session cookie only over HTTPS. Set to true whenever the app is served over HTTPS.
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() in ("true", "1", "yes")
LOGIN_MAX_ATTEMPTS = int(os.getenv("LOGIN_MAX_ATTEMPTS", "5"))
LOGIN_WINDOW_SECONDS = int(os.getenv("LOGIN_WINDOW_SECONDS", "900"))
# Browser origins allowed to call the API with credentials (the dashboard's address).
FRONTEND_ORIGINS = [
    o.strip()
    for o in os.getenv("FRONTEND_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if o.strip()
]

# Integration credentials (Gmail OAuth token, Slack bot token) are encrypted in the database with
# WORKFLOWOS_SECRET_KEY, or with a key file created next to the database on first use.
SECRET_KEY_PATH = os.getenv("SECRET_KEY_PATH")


def secret_key_path() -> str:
    return SECRET_KEY_PATH or os.path.join(os.path.dirname(os.path.abspath(DATABASE_PATH)), "workflowos.secret.key")


# The API's address as seen from the user's browser; Google redirects here after "Connect Gmail".
# Register PUBLIC_API_URL + /api/integrations/gmail/callback as a redirect URI on the OAuth client.
PUBLIC_API_URL = os.getenv("PUBLIC_API_URL", f"http://localhost:{PORT}").rstrip("/")
GMAIL_OAUTH_REDIRECT_URI = f"{PUBLIC_API_URL}/api/integrations/gmail/callback"

# Slack API Integration Configuration
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID")
SLACK_API_BASE_URL = os.getenv("SLACK_API_BASE_URL", "https://slack.com/api")
SLACK_SCOPES = ["chat:write", "channels:history"]



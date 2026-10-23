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

# Slack API Integration Configuration
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID")
SLACK_API_BASE_URL = os.getenv("SLACK_API_BASE_URL", "https://slack.com/api")
SLACK_SCOPES = ["chat:write", "channels:history"]



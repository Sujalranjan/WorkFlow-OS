"""Backend configuration settings."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Locate and load the root .env file if present
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"
if _ENV_PATH.exists():
    load_dotenv(dotenv_path=_ENV_PATH)
else:
    load_dotenv()

PROJECT_NAME = "WorkFlowOS Backend"
VERSION = "0.1.0"
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
HOST = os.getenv("BACKEND_HOST", "127.0.0.1")
PORT = int(os.getenv("BACKEND_PORT", "8000"))
DATABASE_PATH = os.getenv("DATABASE_PATH", "workflowos.db")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

# Phase 12 / 12.1: Gmail API Integration Configuration (Read-Only)
GMAIL_ENABLED = os.getenv("GMAIL_ENABLED", "false").lower() in ("true", "1", "yes")
GMAIL_CREDENTIALS_PATH = os.getenv("GMAIL_CREDENTIALS_PATH", "credentials.json")
GMAIL_TOKEN_PATH = os.getenv("GMAIL_TOKEN_PATH", "token.json")
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
GMAIL_SEARCH_QUERY = os.getenv("GMAIL_SEARCH_QUERY", "from:me")
GMAIL_MAX_RESULTS = int(os.getenv("GMAIL_MAX_RESULTS", "5"))


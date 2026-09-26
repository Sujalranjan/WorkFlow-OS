"""Backend configuration settings."""

import os

PROJECT_NAME = "WorkFlowOS Backend"
VERSION = "0.1.0"
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
HOST = os.getenv("BACKEND_HOST", "127.0.0.1")
PORT = int(os.getenv("BACKEND_PORT", "8000"))
DATABASE_PATH = os.getenv("DATABASE_PATH", "workflowos.db")

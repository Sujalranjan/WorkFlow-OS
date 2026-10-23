"""Structured logging for the WorkFlowOS services.

LOG_FORMAT=json (default in Docker) writes one JSON object per line, ready for any log
collector; LOG_FORMAT=text keeps human-readable lines for local development. Every API request
gets an id (taken from an incoming X-Request-ID header or generated) that is attached to all log
records written while handling it and echoed back in the response header.
"""

from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
import os
import time
import uuid
from typing import Any, Dict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

# Attributes every LogRecord has; anything else was passed via `extra=` and is emitted as a field.
_STANDARD_ATTRS = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: Dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                entry[key] = value if isinstance(value, (str, int, float, bool, type(None))) else str(value)
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def setup_logging(service: str) -> None:
    """Configure root logging once per process (idempotent)."""
    root = logging.getLogger()
    if getattr(root, "_workflowos_configured", False):
        return
    handler = logging.StreamHandler()
    handler.addFilter(_RequestIdFilter())
    if os.getenv("LOG_FORMAT", "text").lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(f"%(asctime)s %(levelname)s [{service}] [%(request_id)s] %(name)s: %(message)s")
        )
    root.handlers = [handler]
    root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    # Route uvicorn's server logs through the same handler; its access log duplicates the request log below.
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True
    logging.getLogger("uvicorn.access").disabled = True
    root._workflowos_configured = True  # type: ignore[attr-defined]


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Assign a request id and log one structured line per request."""

    def __init__(self, app, service: str) -> None:
        super().__init__(app)
        self.logger = logging.getLogger(f"workflowos.{service}.http")

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            self.logger.info(
                "%s %s %s",
                request.method,
                request.url.path,
                status,
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": status,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                },
            )
            request_id_var.reset(token)

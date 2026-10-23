"""Structured logging: JSON records carry the request id, and every response echoes it."""

import json
import logging

from fastapi.testclient import TestClient

from app.logging_config import JsonFormatter, request_id_var
from app.main import create_app


def test_json_formatter_includes_request_id_and_extra_fields():
    token = request_id_var.set("req-123")
    try:
        record = logging.LogRecord("workflowos.test", logging.INFO, __file__, 1, "ran %s", ("step",), None)
        record.status = 200
        line = json.loads(JsonFormatter().format(record))
    finally:
        request_id_var.reset(token)
    assert line["message"] == "ran step"
    assert line["level"] == "INFO"
    assert line["request_id"] == "req-123"
    assert line["status"] == 200


def test_requests_get_an_id_and_a_log_line(caplog):
    client = TestClient(create_app())
    with caplog.at_level(logging.INFO, logger="workflowos.api.http"):
        generated = client.get("/health")
        forwarded = client.get("/health", headers={"X-Request-ID": "from-proxy"})

    assert generated.headers["X-Request-ID"]
    assert forwarded.headers["X-Request-ID"] == "from-proxy"
    entries = [r for r in caplog.records if r.name == "workflowos.api.http"]
    assert any(r.path == "/health" and r.status == 200 and r.duration_ms >= 0 for r in entries)

"""Security headers on every response, the request size limit, HSTS on HTTPS, and switching off docs."""

from fastapi.testclient import TestClient

from app import config
import app.main as main


def test_security_headers_on_api_and_health():
    client = TestClient(main.create_app())
    for path in ("/health", "/api/status"):
        res = client.get(path)
        h = res.headers
        assert h["x-content-type-options"] == "nosniff"
        assert h["x-frame-options"] == "DENY"
        assert h["referrer-policy"] == "no-referrer"
        assert "default-src 'none'" in h["content-security-policy"]
        assert "strict-transport-security" not in h  # plain HTTP in development
    assert client.get("/api/status").headers["cache-control"] == "no-store"  # personal data is never cached


def test_hsts_only_when_https(monkeypatch):
    monkeypatch.setattr(config, "COOKIE_SECURE", True)
    res = TestClient(main.create_app()).get("/health")
    assert res.headers["strict-transport-security"].startswith("max-age=31536000")


def test_large_requests_are_refused_before_reading(monkeypatch):
    monkeypatch.setattr(config, "MAX_REQUEST_BYTES", 1000)
    client = TestClient(main.create_app())
    res = client.post("/api/events", content=b"x" * 2000, headers={"Content-Type": "application/json"})
    assert res.status_code == 413
    bad = client.post("/api/events", content=b"{}", headers={"Content-Type": "application/json", "Content-Length": "abc"})
    assert bad.status_code == 400


def test_docs_can_be_switched_off(monkeypatch):
    assert TestClient(main.create_app()).get("/docs").status_code == 200
    monkeypatch.setattr(main, "API_DOCS_ENABLED", False)
    client = TestClient(main.create_app())
    assert client.get("/docs").status_code == 404 and client.get("/openapi.json").status_code == 404

"""Integration test: Backend startup and GET /health."""

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_check_status_code() -> None:
    """Verify that the health check endpoint returns 200 OK."""
    response = client.get("/health")
    assert response.status_code == 200


def test_health_check_payload() -> None:
    """Verify the payload structure of the health check endpoint."""
    response = client.get("/health")
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "workflowos-backend"
    assert "version" in data

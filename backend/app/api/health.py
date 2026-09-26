"""Health check endpoints."""

from fastapi import APIRouter

router = APIRouter(tags=["Health"])


@router.get("/health")
def get_health() -> dict[str, str]:
    """Return basic health status of the backend."""
    return {
        "status": "healthy",
        "service": "workflowos-backend",
        "version": "0.1.0",
    }

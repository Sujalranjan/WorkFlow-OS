"""Readiness, Prometheus metrics and the admin System overview."""

import hmac
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse, PlainTextResponse

from app import config
from app.services import monitoring

router = APIRouter(tags=["Monitoring"])


@router.get("/health/ready")
def ready() -> JSONResponse:
    """For load balancers and orchestrators: 200 when the install can do work, else 503.
    Reports only which checks pass, nothing about the data."""
    ok, checks = monitoring.readiness()
    return JSONResponse({"status": "ready" if ok else "not_ready", "checks": checks}, status_code=200 if ok else 503)


@router.get("/metrics", response_class=PlainTextResponse)
def metrics(request: Request) -> PlainTextResponse:
    """Prometheus metrics. Off unless METRICS_TOKEN is set; then only with `Authorization: Bearer <token>`."""
    if not config.METRICS_TOKEN:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    given = request.headers.get("authorization", "")
    if not hmac.compare_digest(given.encode(), f"Bearer {config.METRICS_TOKEN}".encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Metrics token required.")
    return PlainTextResponse(monitoring.metrics_text(), media_type="text/plain; version=0.0.4")


@router.get("/api/system")
def system() -> Dict[str, Any]:
    """Admin overview: readiness, workers, job queue, problems, triggers, alerting."""
    return monitoring.system_overview()

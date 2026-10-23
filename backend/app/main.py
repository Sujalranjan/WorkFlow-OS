"""FastAPI application factory and instance."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.auth import router as auth_router
from app.api.automation import get_trigger_service, router as automation_router
from app.api.canonical import router as canonical_router
from app.api.crm import router as crm_router
from app.api.demo import router as demo_router
from app.api.discovery import router as discovery_router
from app.api.dna import router as dna_router
from app.api.events import router as events_router
from app.api.execution import router as execution_router
from app.api.health import router as health_router
from app.api.learning import router as learning_router
from app.api.semantic import router as semantic_router
from app.logging_config import RequestLoggingMiddleware, setup_logging
from app.config import FRONTEND_ORIGINS, PROJECT_NAME, TRIGGER_POLLER_ENABLED, TRIGGER_POLLER_TICK_SECONDS, VERSION
from app.security import CSRF_HEADER, authorize
from app.services.trigger_scheduler import TriggerScheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = None
    if TRIGGER_POLLER_ENABLED:
        scheduler = TriggerScheduler(get_trigger_service(), tick_seconds=TRIGGER_POLLER_TICK_SECONDS)
        scheduler.start()
    try:
        yield
    finally:
        if scheduler is not None:
            await scheduler.stop()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    setup_logging("api")
    app = FastAPI(
        title=PROJECT_NAME,
        version=VERSION,
        description="WorkFlowOS Backend Service",
        lifespan=lifespan,
        # Every route is checked against security.ROUTE_POLICY (unlisted routes are admin-only).
        dependencies=[Depends(authorize)],
    )

    # Only the dashboard's own origin may call the API with the session cookie.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=FRONTEND_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Authorization", CSRF_HEADER],
        expose_headers=["X-Request-ID"],
    )

    app.add_middleware(RequestLoggingMiddleware, service="api")

    # Register routers
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(demo_router)
    app.include_router(events_router)
    app.include_router(discovery_router)
    app.include_router(dna_router)
    app.include_router(semantic_router)
    app.include_router(canonical_router)
    app.include_router(crm_router)
    app.include_router(execution_router)
    app.include_router(learning_router)
    app.include_router(automation_router)

    return app


app = create_app()

"""FastAPI application factory and instance."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.auth import router as auth_router
from app.api.automation import router as automation_router
from app.api.canonical import router as canonical_router
from app.api.catalog import router as catalog_router
from app.api.crm import router as crm_router
from app.api.demo import router as demo_router
from app.api.discovery import router as discovery_router
from app.api.dna import router as dna_router
from app.api.events import router as events_router
from app.api.execution import router as execution_router
from app.api.health import router as health_router
from app.api.integrations import router as integrations_router
from app.api.jobs import router as jobs_router
from app.api.learning import router as learning_router
from app.api.monitoring import router as monitoring_router
from app.api.semantic import router as semantic_router
from app.http_security import SecurityHeadersMiddleware
from app.logging_config import RequestLoggingMiddleware, setup_logging
from app.config import (
    API_DOCS_ENABLED,
    FRONTEND_ORIGINS,
    EMBEDDED_WORKER,
    MIGRATE_ON_START,
    PROJECT_NAME,
    VERSION,
)
from app.security import CSRF_HEADER, authorize


@asynccontextmanager
async def lifespan(app: FastAPI):
    if MIGRATE_ON_START:
        from app.migrate import upgrade

        upgrade()
    worker = None
    if EMBEDDED_WORKER:
        # Local development: run queued jobs and email polling in this process.
        from app.worker import EmbeddedWorker

        worker = EmbeddedWorker()
        worker.start()
    try:
        yield
    finally:
        if worker is not None:
            worker.stop()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    setup_logging("api")
    app = FastAPI(
        title=PROJECT_NAME,
        version=VERSION,
        description="WorkFlowOS Backend Service",
        lifespan=lifespan,
        docs_url="/docs" if API_DOCS_ENABLED else None,
        redoc_url="/redoc" if API_DOCS_ENABLED else None,
        openapi_url="/openapi.json" if API_DOCS_ENABLED else None,
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

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestLoggingMiddleware, service="api")

    # Register routers
    app.include_router(health_router)
    app.include_router(monitoring_router)
    app.include_router(auth_router)
    app.include_router(integrations_router)
    app.include_router(demo_router)
    app.include_router(events_router)
    app.include_router(discovery_router)
    app.include_router(dna_router)
    app.include_router(semantic_router)
    app.include_router(canonical_router)
    app.include_router(catalog_router)
    app.include_router(crm_router)
    app.include_router(execution_router)
    app.include_router(learning_router)
    app.include_router(automation_router)
    app.include_router(jobs_router)

    return app


app = create_app()

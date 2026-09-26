"""FastAPI application factory and instance."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.discovery import router as discovery_router
from app.api.dna import router as dna_router
from app.api.events import router as events_router
from app.api.health import router as health_router
from app.config import PROJECT_NAME, VERSION


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    app = FastAPI(
        title=PROJECT_NAME,
        version=VERSION,
        description="WorkFlowOS Backend Service",
    )

    # Enable CORS for local frontend communication
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    app.include_router(health_router)
    app.include_router(events_router)
    app.include_router(discovery_router)
    app.include_router(dna_router)

    return app


app = create_app()

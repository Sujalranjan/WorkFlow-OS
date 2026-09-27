"""Independent WorkFlowOS Demo CRM Server (Phase 15C).

Provides a dedicated, independent process entry point for the WorkFlowOS Demo CRM API.
Enforces the architectural separation:
    WorkFlowOS Backend (Port 8000)
         |
         | HTTP REST
         v
    Demo CRM Service   (Port 8001)
         |
         v
    crm.db (Independent SQLite database)

Usage:
    python -m app.crm_server
    or
    python backend/app/crm_server.py
"""

from contextlib import asynccontextmanager
import logging
import os
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Ensure the backend directory is in sys.path if run directly
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from app.api.crm import router as crm_router
from app.repositories.crm_repository import CrmRepository

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("workflowos.crm_server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler to ensure clean startup and seeding."""
    logger.info("Initializing WorkFlowOS Demo CRM server...")
    repo = CrmRepository()
    existing = repo.list_all(limit=1)
    if not existing:
        logger.info("CRM database is empty. Seeding default hackathon demo customers...")
        repo.seed_default_customers()
    logger.info("WorkFlowOS Demo CRM server is ready.")
    yield
    logger.info("Shutting down WorkFlowOS Demo CRM server cleanly.")


crm_app = FastAPI(
    title="WorkFlowOS Demo CRM API",
    description="Independent purpose-built CRM application service for WorkFlowOS demo scenarios.",
    version="1.0.0",
    lifespan=lifespan,
)

# Enable CORS for local testing/dashboard access
crm_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount CRM REST API
crm_app.include_router(crm_router)


@crm_app.get("/")
def root():
    """Root status summary."""
    return {
        "service": "WorkFlowOS Demo CRM",
        "status": "online",
        "endpoints": {
            "health": "/api/crm/health",
            "customers": "/api/crm/customers",
            "search": "/api/crm/customers/search",
        },
    }


def main():
    """Main entrypoint for independent CRM server."""
    host = os.getenv("CRM_HOST", "127.0.0.1")
    port = int(os.getenv("CRM_PORT", "8001"))
    logger.info("Starting WorkFlowOS Demo CRM server on http://%s:%d/api/crm", host, port)
    uvicorn.run(
        "app.crm_server:crm_app",
        host=host,
        port=port,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    main()

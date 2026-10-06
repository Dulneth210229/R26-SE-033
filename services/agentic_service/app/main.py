"""
FastAPI application entry point.

Run this backend using:

    uvicorn app.main:app --reload

This file:
- creates the FastAPI app
- registers routes
- enables basic startup checks
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.services.preview_service import preview_service
from app.utils.logger import get_logger

logger = get_logger(__name__)


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Backend for Human-in-the-Loop Multi-Agent SDLC Automation System"
)

# CORS is enabled for local frontend development.
# Later, restrict origins in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _sweep_orphaned_preview_containers() -> None:
    """
    A `--reload` restart drops preview_service's in-memory registry while a
    previously-started preview container may still be running -- sweep for
    and stop any container still carrying the preview label so a restart
    never leaves one running forever. Best-effort: logs and continues if
    Docker itself isn't reachable at startup (sandbox_service already
    degrades to an empty list in that case, never raises).
    """
    stopped = preview_service.sweep_orphaned_containers()
    if stopped:
        logger.info("Stopped %d orphaned preview container(s) on startup.", stopped)


@app.get("/")
def root():
    """
    Root endpoint.
    """
    return {
        "message": "AutoForge Agentic SDLC Backend is running",
        "version": settings.APP_VERSION,
        "docs": "/docs"
    }


# Register all API routes with version prefix.
app.include_router(api_router, prefix=settings.API_PREFIX)
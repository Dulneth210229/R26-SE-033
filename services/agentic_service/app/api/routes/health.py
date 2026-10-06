"""
Health check route.

This is used to check whether the backend is running.
"""

from fastapi import APIRouter
from app.core.config import settings

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("")
def health_check():
    """
    Simple backend health check endpoint.
    """
    return {
        "status": "ok",
        "app_name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.APP_ENV,
    }
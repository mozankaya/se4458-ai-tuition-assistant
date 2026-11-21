"""FastAPI application entry point for the Tuition REST API."""

from fastapi import FastAPI

from app.config import get_settings
from app.routers import health


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Tuition query, payment and administration API for the AI Tuition Assistant.",
    )
    app.include_router(health.router, prefix=settings.api_v1_prefix)
    return app


app = create_app()

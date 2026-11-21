"""FastAPI application entry point for the Tuition REST API."""

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from app.config import get_settings
from app.errors import register_error_handlers
from app.routers import admin, auth, banking, health, mobile

DESCRIPTION = """
Tuition query, payment and administration API for the **AI Tuition Assistant** (SE 4458 Midterm 1).

All routes are versioned under `/api/v1`. In deployment every request goes through the API Gateway.

### Authentication
1. Call `POST /api/v1/auth/login` with a demo user (see README) to receive a JWT.
2. Click **Authorize** and paste the `access_token`.

Roles: `student` (own records only), `bank` (banking operations for any student), `admin` (admin routes).

### Error format
Every error uses the same body:

```json
{"error": {"code": "STUDENT_NOT_FOUND", "message": "Student 99999999 was not found"}}
```

`details` is added when useful (validation errors list each invalid field).

| HTTP | Codes |
|---|---|
| 401 | `UNAUTHORIZED`, `INVALID_CREDENTIALS` |
| 403 | `FORBIDDEN` |
| 404 | `NOT_FOUND`, `STUDENT_NOT_FOUND`, `TUITION_NOT_FOUND` |
| 409 | `DUPLICATE_TRANSACTION`, `AMOUNT_BELOW_PAID`, `CURRENCY_MISMATCH`, `CURRENCY_CHANGE_NOT_ALLOWED` |
| 422 | `VALIDATION_ERROR`, `AMOUNT_EXCEEDS_BALANCE`, `INVALID_CSV` |
| 429 | `RATE_LIMIT_EXCEEDED` |
| 500 | `INTERNAL_ERROR` |
"""

TAGS = [
    {"name": "Health", "description": "Service status."},
    {"name": "Auth", "description": "Login for demo users and token introspection."},
    {"name": "Mobile App", "description": "University mobile app. No authentication; 3 queries per student per day."},
    {"name": "Banking App", "description": "Banking app. Requires role `bank` or `student` (own records)."},
    {"name": "Admin", "description": "University web site admin. Requires role `admin`."},
]


def _custom_openapi(app: FastAPI) -> dict[str, Any]:
    """Generate the schema and document 422 responses with our error format instead of FastAPI's default."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=app.openapi_tags,
    )
    error_ref = {"$ref": "#/components/schemas/ErrorResponse"}
    for operation in (op for path in schema["paths"].values() for op in path.values()):
        response = operation.get("responses", {}).get("422")
        if response is not None:
            content = response.get("content", {}).get("application/json", {})
            if content.get("schema", {}).get("$ref", "").endswith("/HTTPValidationError"):
                response["description"] = "Validation error"
                content["schema"] = error_ref
    for unused in ("HTTPValidationError", "ValidationError"):
        schema["components"]["schemas"].pop(unused, None)
    app.openapi_schema = schema
    return schema


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=DESCRIPTION,
        openapi_tags=TAGS,
    )
    register_error_handlers(app)
    app.include_router(health.router, prefix=settings.api_v1_prefix)
    app.include_router(auth.router, prefix=settings.api_v1_prefix)
    app.include_router(mobile.router, prefix=settings.api_v1_prefix)
    app.include_router(banking.router, prefix=settings.api_v1_prefix)
    app.include_router(admin.router, prefix=settings.api_v1_prefix)
    app.openapi = lambda: _custom_openapi(app)  # type: ignore[method-assign]
    return app


app = create_app()

from fastapi.testclient import TestClient

from app.export_openapi import OPENAPI_PATH, render_openapi
from app.main import create_app


def test_exported_openapi_file_is_up_to_date():
    assert OPENAPI_PATH.exists(), "Run: python -m app.export_openapi"
    assert OPENAPI_PATH.read_text(encoding="utf-8") == render_openapi(), "Run: python -m app.export_openapi"


def test_all_routes_are_versioned_and_errors_use_error_format():
    schema = create_app().openapi()

    assert all(path.startswith("/api/v1/") for path in schema["paths"])
    assert "HTTPValidationError" not in schema["components"]["schemas"]
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            for code, response in operation["responses"].items():
                if code.startswith(("4", "5")):
                    ref = response["content"]["application/json"]["schema"]["$ref"]
                    assert ref.endswith("/ErrorResponse"), f"{method.upper()} {path} {code}"


def test_protected_routes_declare_bearer_security():
    schema = create_app().openapi()
    public = {("post", "/api/v1/auth/login"), ("get", "/api/v1/health"), ("get", "/api/v1/mobile/tuition/{studentNo}")}

    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            has_security = "security" in operation
            assert has_security != ((method, path) in public), f"{method.upper()} {path}"


def test_unexpected_exception_returns_500_in_error_format():
    app = create_app()

    @app.get("/test/boom")
    def boom():
        raise RuntimeError("secret internal detail")

    response = TestClient(app, raise_server_exceptions=False).get("/test/boom")

    assert response.status_code == 500
    assert response.json() == {"error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred"}}


def test_method_not_allowed_uses_error_format():
    response = TestClient(create_app()).delete("/api/v1/health")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"

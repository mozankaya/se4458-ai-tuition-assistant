from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "Tuition API"
    assert body["version"] == "1.0.0"


def test_unversioned_health_route_is_not_found():
    response = client.get("/health")

    assert response.status_code == 404

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import TOKEN_ISSUER, CurrentUser, ensure_student_access, require_roles
from app.config import get_settings
from app.db import get_db
from app.errors import ApiError
from app.main import create_app
from app.models import ROLE_ADMIN, ROLE_BANK, ROLE_STUDENT, User
from tests.conftest import TEST_DEMO_PASSWORD

LOGIN_URL = "/api/v1/auth/login"
ME_URL = "/api/v1/auth/me"


def _token(**claims) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {"sub": "student1", "role": "student", "iss": TOKEN_ISSUER, "iat": now,
               "exp": now + timedelta(minutes=5)}
    payload.update(claims)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


# --- Login ---------------------------------------------------------------------------------------

def test_login_student_returns_token_with_student_claims(client: TestClient, seeded: Session):
    response = client.post(LOGIN_URL, json={"username": "student1", "password": TEST_DEMO_PASSWORD})

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["role"] == "student"
    assert body["student_no"] == "20230001"
    assert body["expires_in"] == get_settings().jwt_expire_minutes * 60
    claims = jwt.decode(body["access_token"], get_settings().jwt_secret, algorithms=["HS256"],
                        issuer=TOKEN_ISSUER)
    assert claims["sub"] == "student1"
    assert claims["student_no"] == "20230001"


@pytest.mark.parametrize("username", ["bank1", "admin1"])
def test_login_non_student_has_no_student_no(client: TestClient, seeded: Session, username: str):
    response = client.post(LOGIN_URL, json={"username": username, "password": TEST_DEMO_PASSWORD})

    assert response.status_code == 200
    assert response.json()["student_no"] is None


@pytest.mark.parametrize(
    ("username", "password"),
    [("student1", "wrong-password"), ("nobody", TEST_DEMO_PASSWORD)],
)
def test_login_with_bad_credentials_returns_401(client: TestClient, seeded: Session, username, password):
    response = client.post(LOGIN_URL, json={"username": username, "password": password})

    assert response.status_code == 401
    assert response.json() == {
        "error": {"code": "INVALID_CREDENTIALS", "message": "Invalid username or password"}
    }


def test_login_inactive_user_returns_401(client: TestClient, seeded: Session):
    seeded.scalar(select(User).where(User.username == "student1")).is_active = False
    seeded.flush()

    response = client.post(LOGIN_URL, json={"username": "student1", "password": TEST_DEMO_PASSWORD})

    assert response.status_code == 401


def test_login_with_missing_fields_returns_validation_error(client: TestClient, seeded: Session):
    response = client.post(LOGIN_URL, json={"username": "student1"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"][0]["field"] == "body.password"


# --- Token validation ----------------------------------------------------------------------------

def test_me_returns_identity_from_token(client: TestClient, seeded: Session, login: Callable):
    response = client.get(ME_URL, headers=login("student2"))

    assert response.status_code == 200
    assert response.json() == {"username": "student2", "role": "student", "student_no": "20230002"}


@pytest.mark.parametrize(
    ("headers", "message"),
    [
        ({}, "Missing bearer token"),
        ({"Authorization": "Bearer not-a-jwt"}, "Invalid token"),
        ({"Authorization": f"Bearer {_token(exp=datetime.now(UTC) - timedelta(seconds=1))}"}, "Token has expired"),
        ({"Authorization": "Bearer " + jwt.encode({"sub": "student1", "role": "student", "iss": TOKEN_ISSUER,
                                                   "exp": datetime.now(UTC) + timedelta(minutes=5)},
                                                  "some-other-secret-that-is-long-enough", algorithm="HS256")},
         "Invalid token"),
        ({"Authorization": f"Bearer {_token(iss='someone-else')}"}, "Invalid token"),
        ({"Authorization": f"Bearer {_token(sub='ghost')}"}, "User is not active"),
    ],
    ids=["missing", "malformed", "expired", "wrong-signature", "wrong-issuer", "unknown-user"],
)
def test_me_rejects_bad_tokens(client: TestClient, seeded: Session, headers, message):
    response = client.get(ME_URL, headers=headers)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"] == {"code": "UNAUTHORIZED", "message": message}


def test_unknown_route_uses_error_format(client: TestClient):
    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "NOT_FOUND", "message": "Not Found"}}


# --- Role and ownership dependencies -------------------------------------------------------------

@pytest.fixture
def guarded_client(db_session: Session) -> TestClient:
    """App with an extra admin-only route to exercise require_roles."""
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session

    @app.get("/test/admin-only")
    def admin_only(user: Annotated[CurrentUser, Depends(require_roles(ROLE_ADMIN))]):
        return {"user": user.username}

    return TestClient(app)


def test_require_roles_allows_matching_role(guarded_client: TestClient, seeded: Session, login: Callable):
    response = guarded_client.get("/test/admin-only", headers=login("admin1"))

    assert response.status_code == 200
    assert response.json() == {"user": "admin1"}


@pytest.mark.parametrize("username", ["student1", "bank1"])
def test_require_roles_rejects_other_roles(guarded_client: TestClient, seeded: Session, login: Callable,
                                           username: str):
    response = guarded_client.get("/test/admin-only", headers=login(username))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_ensure_student_access_allows_own_number():
    ensure_student_access(CurrentUser(1, "student1", ROLE_STUDENT, "20230001"), "20230001")


def test_ensure_student_access_rejects_other_students_number():
    with pytest.raises(ApiError) as exc:
        ensure_student_access(CurrentUser(1, "student1", ROLE_STUDENT, "20230001"), "20230002")

    assert exc.value.status_code == 403


@pytest.mark.parametrize("role", [ROLE_BANK, ROLE_ADMIN])
def test_ensure_student_access_allows_bank_and_admin_any_number(role: str):
    ensure_student_access(CurrentUser(5, "staff", role, None), "20230002")

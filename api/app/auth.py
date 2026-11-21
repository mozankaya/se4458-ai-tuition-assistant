"""JWT issuing/validation and authorization dependencies."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import ApiError
from app.models import ROLE_STUDENT, User

TOKEN_ISSUER = "tuition-api"

bearer_scheme = HTTPBearer(auto_error=False, description="JWT from POST /api/v1/auth/login")


@dataclass(frozen=True)
class CurrentUser:
    id: int
    username: str
    role: str
    student_no: str | None


def _secret() -> str:
    secret = get_settings().jwt_secret
    if not secret:
        raise RuntimeError("JWT_SECRET is not configured")
    return secret


def create_access_token(user: User) -> tuple[str, int]:
    """Return (token, expires_in_seconds) for the given user."""
    settings = get_settings()
    expires_in = settings.jwt_expire_minutes * 60
    now = datetime.now(UTC)
    claims = {
        "sub": user.username,
        "role": user.role,
        "student_no": user.student.student_no if user.student else None,
        "iss": TOKEN_ISSUER,
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
    }
    return jwt.encode(claims, _secret(), algorithm=settings.jwt_algorithm), expires_in


def _unauthorized(message: str) -> ApiError:
    return ApiError(401, "UNAUTHORIZED", message, headers={"WWW-Authenticate": "Bearer"})


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> CurrentUser:
    if credentials is None:
        raise _unauthorized("Missing bearer token")
    try:
        claims = jwt.decode(
            credentials.credentials,
            _secret(),
            algorithms=[get_settings().jwt_algorithm],
            issuer=TOKEN_ISSUER,
            options={"require": ["sub", "role", "exp", "iss"]},
        )
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Token has expired") from None
    except jwt.InvalidTokenError:
        raise _unauthorized("Invalid token") from None

    # Re-check the user in the database so deactivated accounts lose access immediately.
    user = db.scalar(select(User).where(User.username == claims["sub"]))
    if user is None or not user.is_active:
        raise _unauthorized("User is not active")
    return CurrentUser(
        id=user.id,
        username=user.username,
        role=user.role,
        student_no=user.student.student_no if user.student else None,
    )


def require_roles(*roles: str) -> Callable[..., CurrentUser]:
    """Dependency factory that allows only the given roles."""

    def dependency(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        if user.role not in roles:
            raise ApiError(403, "FORBIDDEN", f"Role '{user.role}' is not allowed to perform this operation")
        return user

    return dependency


def ensure_student_access(user: CurrentUser, student_no: str) -> None:
    """Students may only access their own student number; other allowed roles are unrestricted."""
    if user.role == ROLE_STUDENT and user.student_no != student_no:
        raise ApiError(403, "FORBIDDEN", "Students can only access their own tuition records")

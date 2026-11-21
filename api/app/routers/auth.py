"""Authentication endpoints for the seeded demo users."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import CurrentUser, create_access_token, get_current_user
from app.db import get_db
from app.errors import ApiError, ErrorResponse
from app.models import User
from app.security import hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["Auth"])

# Compared against when the username is unknown, so response time does not reveal valid usernames.
_DUMMY_HASH = hash_password("dummy-password-for-timing")


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50, examples=["student1"])
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Token lifetime in seconds")
    role: str
    student_no: str | None


class MeResponse(BaseModel):
    username: str
    role: str
    student_no: str | None


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Log in and receive a JWT",
    responses={401: {"model": ErrorResponse, "description": "Invalid credentials"}},
)
def login(body: LoginRequest, db: Annotated[Session, Depends(get_db)]) -> TokenResponse:
    user = db.scalar(select(User).where(User.username == body.username))
    password_ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if user is None or not password_ok or not user.is_active:
        raise ApiError(401, "INVALID_CREDENTIALS", "Invalid username or password")

    token, expires_in = create_access_token(user)
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        role=user.role,
        student_no=user.student.student_no if user.student else None,
    )


@router.get(
    "/me",
    response_model=MeResponse,
    summary="Return the identity encoded in the current token",
    responses={401: {"model": ErrorResponse, "description": "Missing or invalid token"}},
)
def me(user: Annotated[CurrentUser, Depends(get_current_user)]) -> MeResponse:
    return MeResponse(username=user.username, role=user.role, student_no=user.student_no)

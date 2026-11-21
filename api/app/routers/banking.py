"""Banking App endpoints (authentication required)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from app.auth import CurrentUser, ensure_student_access, require_roles
from app.db import get_db
from app.errors import ErrorResponse
from app.models import ROLE_BANK, ROLE_STUDENT
from app.schemas import STUDENT_NO_PATTERN, TuitionSummary
from app.services.tuition import get_tuition_summary

router = APIRouter(prefix="/banking", tags=["Banking App"])

BankingUser = Annotated[CurrentUser, Depends(require_roles(ROLE_BANK, ROLE_STUDENT))]

AUTH_ERRORS = {
    401: {"model": ErrorResponse, "description": "Missing or invalid token"},
    403: {"model": ErrorResponse, "description": "Role not allowed, or a student accessing another student"},
}


@router.get(
    "/tuition/{studentNo}",
    response_model=TuitionSummary,
    response_model_by_alias=True,
    summary="Query tuition (banking app)",
    description=(
        "Returns the overall tuition total and outstanding balance for a student, with a per-term "
        "breakdown. Requires a bearer token with role `bank` (any student) or `student` (own student "
        "number only)."
    ),
    responses={**AUTH_ERRORS, 404: {"model": ErrorResponse, "description": "Student not found"}},
)
def query_tuition_banking(
    student_no: Annotated[str, Path(alias="studentNo", pattern=STUDENT_NO_PATTERN, examples=["20230001"])],
    user: BankingUser,
    db: Annotated[Session, Depends(get_db)],
) -> TuitionSummary:
    ensure_student_access(user, student_no)
    return get_tuition_summary(db, student_no)

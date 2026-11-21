"""University Mobile App endpoints (no authentication, rate limited per student)."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import ApiError, ErrorResponse
from app.rate_limit import consume, local_now
from app.schemas import STUDENT_NO_PATTERN, TuitionSummary
from app.services.tuition import get_tuition_summary

router = APIRouter(prefix="/mobile", tags=["Mobile App"])

MOBILE_QUERY_ENDPOINT = "mobile_tuition_query"


@router.get(
    "/tuition/{studentNo}",
    response_model=TuitionSummary,
    response_model_by_alias=True,
    summary="Query tuition (mobile app)",
    description=(
        "Returns the overall tuition total and outstanding balance for a student, with a per-term "
        "breakdown. No authentication. Limited to **3 calls per student number per day** "
        "(Europe/Istanbul calendar day), keyed by student number, not client IP. Calls for unknown "
        "student numbers also count."
    ),
    responses={
        404: {"model": ErrorResponse, "description": "Student not found"},
        429: {"model": ErrorResponse, "description": "Daily limit for this student number reached"},
    },
)
def query_tuition_mobile(
    response: Response,
    student_no: Annotated[str, Path(alias="studentNo", pattern=STUDENT_NO_PATTERN, examples=["20230001"])],
    db: Annotated[Session, Depends(get_db)],
    now: Annotated[datetime, Depends(local_now)],
) -> TuitionSummary:
    limit = get_settings().mobile_daily_query_limit
    result = consume(db, student_no, MOBILE_QUERY_ENDPOINT, limit, now)
    headers = {"X-RateLimit-Limit": str(result.limit), "X-RateLimit-Remaining": str(result.remaining)}
    if not result.allowed:
        raise ApiError(
            429,
            "RATE_LIMIT_EXCEEDED",
            f"Daily query limit of {limit} reached for student {student_no}. Try again tomorrow.",
            headers={**headers, "Retry-After": str(result.retry_after_seconds)},
        )
    response.headers.update(headers)
    return get_tuition_summary(db, student_no)

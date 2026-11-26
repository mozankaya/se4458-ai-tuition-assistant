"""University Web Site - Admin endpoints (role `admin` required)."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from sqlalchemy.orm import Session

from app.auth import CurrentUser, require_roles
from app.db import get_db
from app.errors import ErrorResponse
from app.models import ROLE_ADMIN
from app.schemas import (
    TERM_PATTERN,
    BatchResult,
    TuitionUpsertRequest,
    TuitionUpsertResponse,
    UnpaidTuitionPage,
)
from app.services.admin import list_unpaid, process_batch_csv, upsert_tuition

router = APIRouter(prefix="/admin", tags=["Admin"])

AdminUser = Annotated[CurrentUser, Depends(require_roles(ROLE_ADMIN))]

AUTH_ERRORS = {
    401: {"model": ErrorResponse, "description": "Missing or invalid token"},
    403: {"model": ErrorResponse, "description": "Role is not admin"},
}


@router.post(
    "/tuitions",
    response_model=TuitionUpsertResponse,
    response_model_by_alias=True,
    summary="Add or update tuition",
    description=(
        "Create-or-update keyed by `(studentNo, term)`. Returns `201` with status `CREATED` for a new "
        "record, `200` with status `UPDATED` when an existing record is replaced. Unknown student numbers "
        "are created automatically. Rejected with `409` if the new amount is below the amount already "
        "paid, or if the currency conflicts with the student's other records or existing payments. "
        "Concurrent calls for the same student are serialized (row lock), so two simultaneous creates "
        "result in one `CREATED` and one `UPDATED` instead of a conflict error."
    ),
    responses={
        **AUTH_ERRORS,
        201: {"model": TuitionUpsertResponse, "description": "Tuition created"},
        409: {"model": ErrorResponse, "description": "Amount below paid amount or currency conflict"},
        422: {"model": ErrorResponse, "description": "Invalid input"},
    },
)
def add_tuition(
    body: TuitionUpsertRequest,
    response: Response,
    _: AdminUser,
    db: Annotated[Session, Depends(get_db)],
) -> TuitionUpsertResponse:
    result = upsert_tuition(db, body)
    db.commit()
    response.status_code = 201 if result.status == "CREATED" else 200
    return result


@router.get(
    "/tuitions/unpaid",
    response_model=UnpaidTuitionPage,
    response_model_by_alias=True,
    summary="Unpaid tuition status (paged)",
    description=(
        "Lists tuition records with an outstanding balance (`balance > 0`), ordered by student number "
        "and term. Filter by `term` or omit it for all terms. `page` starts at 1; `pageSize` is 1-100 "
        "(default 20). A page past the end returns an empty `items` list."
    ),
    responses={**AUTH_ERRORS, 422: {"model": ErrorResponse, "description": "Invalid query parameters"}},
)
def unpaid_tuition_status(
    _: AdminUser,
    db: Annotated[Session, Depends(get_db)],
    term: Annotated[str | None, Query(pattern=TERM_PATTERN, examples=["2026-FALL"])] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
) -> UnpaidTuitionPage:
    return list_unpaid(db, term, page, page_size)


@router.post(
    "/tuitions/batch",
    response_model=BatchResult,
    response_model_by_alias=True,
    summary="Add or update tuition in batch (CSV)",
    description=(
        "Upload a UTF-8 CSV file with header `studentNo,term,amount,currency`. Each row follows the same "
        "rules as *Add or update tuition* and is applied independently: valid rows are saved even when "
        "other rows fail. The response reports success/failure counts and per-row errors with the CSV "
        "line number. Duplicate `(studentNo, term)` rows are applied in file order (last one wins). "
        "Quoted cells, CRLF line endings, a UTF-8 BOM, blank lines and empty trailing columns are "
        "accepted. A file that is not UTF-8, is malformed, has a wrong header, has no data rows or more "
        "than 10,000 rows is rejected as a whole (`422`) before any row is saved; a file over 5 MB "
        "returns `413`."
    ),
    responses={
        **AUTH_ERRORS,
        413: {"model": ErrorResponse, "description": "File larger than 5 MB"},
        422: {"model": ErrorResponse, "description": "Invalid, malformed or empty CSV file"},
    },
)
async def add_tuition_batch(
    file: Annotated[UploadFile, File(description="CSV file: studentNo,term,amount,currency")],
    _: AdminUser,
    db: Annotated[Session, Depends(get_db)],
) -> BatchResult:
    content = await file.read()
    return process_batch_csv(db, content)

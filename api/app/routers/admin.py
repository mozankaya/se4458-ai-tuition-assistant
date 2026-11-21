"""University Web Site - Admin endpoints (role `admin` required)."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Response, UploadFile
from sqlalchemy.orm import Session

from app.auth import CurrentUser, require_roles
from app.db import get_db
from app.errors import ErrorResponse
from app.models import ROLE_ADMIN
from app.schemas import BatchResult, TuitionUpsertRequest, TuitionUpsertResponse
from app.services.admin import process_batch_csv, upsert_tuition

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
        "paid, or if the currency conflicts with the student's other records or existing payments."
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


@router.post(
    "/tuitions/batch",
    response_model=BatchResult,
    response_model_by_alias=True,
    summary="Add or update tuition in batch (CSV)",
    description=(
        "Upload a UTF-8 CSV file with header `studentNo,term,amount,currency`. Each row follows the same "
        "rules as *Add or update tuition* and is applied independently: valid rows are saved even when "
        "other rows fail. The response reports success/failure counts and per-row errors. Duplicate "
        "`(studentNo, term)` rows are applied in file order (last one wins)."
    ),
    responses={**AUTH_ERRORS, 422: {"model": ErrorResponse, "description": "Invalid or empty CSV file"}},
)
async def add_tuition_batch(
    file: Annotated[UploadFile, File(description="CSV file: studentNo,term,amount,currency")],
    _: AdminUser,
    db: Annotated[Session, Depends(get_db)],
) -> BatchResult:
    content = await file.read()
    return process_batch_csv(db, content)

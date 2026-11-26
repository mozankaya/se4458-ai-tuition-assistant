"""Admin tuition management: create-or-update and CSV batch import."""

import csv
import io
import math

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import Student, Tuition
from app.schemas import (
    BatchResult,
    BatchRowError,
    TuitionUpsertRequest,
    TuitionUpsertResponse,
    UnpaidTuitionItem,
    UnpaidTuitionPage,
)

CSV_COLUMNS = ["studentNo", "term", "amount", "currency"]
MAX_BATCH_ROWS = 10_000
MAX_BATCH_BYTES = 5 * 1024 * 1024


def upsert_tuition(db: Session, request: TuitionUpsertRequest) -> TuitionUpsertResponse:
    """Create or update the tuition for (studentNo, term). Does not commit.

    Rules (see docs/ASSUMPTIONS.md):
    - unknown student numbers are created automatically;
    - the new amount may not be below the amount already paid;
    - all of a student's tuition records must use the same currency, and the currency of a record
      with payments cannot change.
    """
    # Concurrency: the student is created with INSERT ... ON CONFLICT DO NOTHING, so two concurrent
    # requests for a new student number cannot both insert it (no unique-violation 500). The student row
    # is then locked until commit, which serializes all upserts of one student: the currency check and
    # the tuition create/update below cannot interleave with another upsert of the same student.
    db.execute(
        pg_insert(Student)
        .values(student_no=request.student_no)
        .on_conflict_do_nothing(index_elements=[Student.student_no])
    )
    student = db.scalar(
        select(Student)
        .where(Student.student_no == request.student_no)
        .with_for_update()
        .execution_options(populate_existing=True)
    )

    other_currencies = set(
        db.scalars(
            select(Tuition.currency).where(Tuition.student_id == student.id, Tuition.term != request.term)
        )
    )
    if other_currencies and other_currencies != {request.currency}:
        raise ApiError(
            409,
            "CURRENCY_MISMATCH",
            f"Student {request.student_no} already has tuition in {', '.join(sorted(other_currencies))}",
        )

    tuition = db.scalar(
        select(Tuition)
        .where(Tuition.student_id == student.id, Tuition.term == request.term)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if tuition is None:
        tuition = Tuition(
            student_id=student.id,
            term=request.term,
            amount=request.amount,
            paid_amount=0,
            currency=request.currency,
        )
        db.add(tuition)
        status = "CREATED"
    else:
        if request.amount < tuition.paid_amount:
            raise ApiError(
                409,
                "AMOUNT_BELOW_PAID",
                f"New amount {request.amount:.2f} is below the already paid amount {tuition.paid_amount:.2f}",
            )
        if request.currency != tuition.currency and tuition.paid_amount > 0:
            raise ApiError(
                409, "CURRENCY_CHANGE_NOT_ALLOWED", "Currency cannot change after payments were recorded"
            )
        tuition.amount = request.amount
        tuition.currency = request.currency
        status = "UPDATED"
    db.flush()

    return TuitionUpsertResponse(
        status=status,
        student_no=student.student_no,
        term=tuition.term,
        amount=tuition.amount,
        paid_amount=tuition.paid_amount,
        balance=tuition.balance,
        currency=tuition.currency,
    )


def list_unpaid(db: Session, term: str | None, page: int, page_size: int) -> UnpaidTuitionPage:
    """Paged list of tuition records with an outstanding balance, ordered by student number and term."""
    conditions = [Tuition.amount > Tuition.paid_amount]
    if term is not None:
        conditions.append(Tuition.term == term)

    total = db.scalar(select(func.count()).select_from(Tuition).where(*conditions))
    rows = db.execute(
        select(Tuition, Student)
        .join(Student)
        .where(*conditions)
        .order_by(Student.student_no, Tuition.term)
        .limit(page_size)
        .offset((page - 1) * page_size)
    ).all()

    return UnpaidTuitionPage(
        term=term,
        page=page,
        page_size=page_size,
        total_items=total,
        total_pages=math.ceil(total / page_size),
        items=[
            UnpaidTuitionItem(
                student_no=student.student_no,
                full_name=student.full_name,
                term=tuition.term,
                tuition_total=tuition.amount,
                paid_amount=tuition.paid_amount,
                balance=tuition.balance,
                currency=tuition.currency,
            )
            for tuition, student in rows
        ],
    )


def _validation_message(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())


def _trim_trailing_empty(cells: list[str]) -> list[str]:
    """Drop empty cells at the end of a row (spreadsheet exports often add trailing commas)."""
    cells = [cell.strip() for cell in cells]
    while cells and not cells[-1]:
        cells.pop()
    return cells


def _parse_csv(content: bytes) -> list[tuple[int, list[str]]]:
    """Validate the file as a whole and return its data rows as (line number, cells).

    Whole-file problems are rejected before any row is written, so a rejected upload changes nothing.
    """
    if len(content) > MAX_BATCH_BYTES:
        raise ApiError(413, "FILE_TOO_LARGE", f"File must not be larger than {MAX_BATCH_BYTES} bytes")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ApiError(422, "INVALID_CSV", "File must be UTF-8 encoded") from None
    if "\x00" in text:
        raise ApiError(422, "INVALID_CSV", "File contains NUL bytes; it is not a text CSV file")

    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader, None)
        if header is None or _trim_trailing_empty(header) != CSV_COLUMNS:
            raise ApiError(
                422, "INVALID_CSV", f"CSV header must be exactly: {','.join(CSV_COLUMNS)} (comma-separated)"
            )
        rows = []
        for row in reader:
            if not any(cell.strip() for cell in row):
                continue  # ignore blank lines
            rows.append((reader.line_num, row))
            if len(rows) > MAX_BATCH_ROWS:
                raise ApiError(422, "INVALID_CSV", f"A batch may contain at most {MAX_BATCH_ROWS} rows")
    except csv.Error as exc:
        raise ApiError(422, "INVALID_CSV", f"Malformed CSV near line {reader.line_num}: {exc}") from None
    if not rows:
        raise ApiError(422, "INVALID_CSV", "CSV file contains no data rows")
    return rows


def process_batch_csv(db: Session, content: bytes) -> BatchResult:
    """Apply every CSV row independently; a failing row does not undo the others.

    Each row is committed on its own. Row locks are therefore held only briefly, so concurrent batch
    uploads and single Add Tuition calls on the same students wait for each other instead of
    deadlocking, and an error in one row cannot roll back rows that were already reported as saved.
    """
    rows = _parse_csv(content)
    errors: list[BatchRowError] = []
    created = updated = 0

    for line_no, raw in rows:
        row = _trim_trailing_empty(raw)
        student_no = row[0] if row else None
        term = row[1] if len(row) > 1 else None
        if len(row) != len(CSV_COLUMNS):
            errors.append(BatchRowError(line=line_no, student_no=student_no, term=term, code="INVALID_ROW",
                                        message=f"Expected {len(CSV_COLUMNS)} columns, got {len(row)}"))
            continue

        try:
            request = TuitionUpsertRequest.model_validate(dict(zip(CSV_COLUMNS, row)))
        except ValidationError as exc:
            errors.append(BatchRowError(line=line_no, student_no=student_no, term=term,
                                        code="VALIDATION_ERROR", message=_validation_message(exc)))
            continue

        try:
            result = upsert_tuition(db, request)
            db.commit()
        except ApiError as exc:
            db.rollback()
            errors.append(BatchRowError(line=line_no, student_no=student_no, term=term,
                                        code=exc.code, message=exc.message))
            continue
        except IntegrityError:
            db.rollback()
            errors.append(BatchRowError(line=line_no, student_no=student_no, term=term,
                                        code="CONFLICT", message="Row conflicts with existing data"))
            continue
        if result.status == "CREATED":
            created += 1
        else:
            updated += 1

    success = created + updated
    status = "COMPLETED" if not errors else ("FAILED" if success == 0 else "PARTIAL")
    return BatchResult(
        status=status,
        total_rows=len(rows),
        success_count=success,
        failure_count=len(errors),
        created_count=created,
        updated_count=updated,
        errors=errors,
    )

"""Admin tuition management: create-or-update and CSV batch import."""

import csv
import io

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import Student, Tuition
from app.schemas import BatchResult, BatchRowError, TuitionUpsertRequest, TuitionUpsertResponse

CSV_COLUMNS = ["studentNo", "term", "amount", "currency"]
MAX_BATCH_ROWS = 10_000


def upsert_tuition(db: Session, request: TuitionUpsertRequest) -> TuitionUpsertResponse:
    """Create or update the tuition for (studentNo, term). Does not commit.

    Rules (see docs/ASSUMPTIONS.md):
    - unknown student numbers are created automatically;
    - the new amount may not be below the amount already paid;
    - all of a student's tuition records must use the same currency, and the currency of a record
      with payments cannot change.
    """
    student = db.scalar(select(Student).where(Student.student_no == request.student_no))
    if student is None:
        student = Student(student_no=request.student_no)
        db.add(student)
        db.flush()

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


def _validation_message(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())


def process_batch_csv(db: Session, content: bytes) -> BatchResult:
    """Apply every CSV row independently; a failing row does not undo the others."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ApiError(422, "INVALID_CSV", "File must be UTF-8 encoded") from None

    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if header is None or [h.strip() for h in header] != CSV_COLUMNS:
        raise ApiError(422, "INVALID_CSV", f"CSV header must be exactly: {','.join(CSV_COLUMNS)}")

    errors: list[BatchRowError] = []
    created = updated = total = 0

    for line_no, row in enumerate(reader, start=2):
        if not any(cell.strip() for cell in row):
            continue  # ignore blank lines
        total += 1
        if total > MAX_BATCH_ROWS:
            raise ApiError(422, "INVALID_CSV", f"A batch may contain at most {MAX_BATCH_ROWS} rows")

        student_no = row[0].strip() if row else None
        term = row[1].strip() if len(row) > 1 else None
        if len(row) != len(CSV_COLUMNS):
            errors.append(BatchRowError(line=line_no, student_no=student_no, term=term, code="INVALID_ROW",
                                        message=f"Expected {len(CSV_COLUMNS)} columns, got {len(row)}"))
            continue

        try:
            request = TuitionUpsertRequest.model_validate(dict(zip(CSV_COLUMNS, (c.strip() for c in row))))
        except ValidationError as exc:
            errors.append(BatchRowError(line=line_no, student_no=student_no, term=term,
                                        code="VALIDATION_ERROR", message=_validation_message(exc)))
            continue

        savepoint = db.begin_nested()
        try:
            result = upsert_tuition(db, request)
            savepoint.commit()
        except ApiError as exc:
            savepoint.rollback()
            errors.append(BatchRowError(line=line_no, student_no=student_no, term=term,
                                        code=exc.code, message=exc.message))
            continue
        except IntegrityError:
            savepoint.rollback()
            errors.append(BatchRowError(line=line_no, student_no=student_no, term=term,
                                        code="CONFLICT", message="Row conflicts with existing data"))
            continue
        if result.status == "CREATED":
            created += 1
        else:
            updated += 1

    if total == 0:
        raise ApiError(422, "INVALID_CSV", "CSV file contains no data rows")
    db.commit()
    success = created + updated
    status = "COMPLETED" if not errors else ("FAILED" if success == 0 else "PARTIAL")
    return BatchResult(
        status=status,
        total_rows=total,
        success_count=success,
        failure_count=len(errors),
        created_count=created,
        updated_count=updated,
        errors=errors,
    )

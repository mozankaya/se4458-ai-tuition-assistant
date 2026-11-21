"""Pay Tuition business logic."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import Payment, Student, Tuition
from app.schemas import PaymentRequest, PaymentResponse


def _duplicate(transaction_id: str) -> ApiError:
    return ApiError(409, "DUPLICATE_TRANSACTION", f"Transaction {transaction_id} has already been processed")


def pay_tuition(db: Session, request: PaymentRequest, user_id: int | None) -> PaymentResponse:
    """Record a simulated partial or full payment for one student and term.

    The tuition row is locked with SELECT ... FOR UPDATE so concurrent payments cannot together
    exceed the balance. The UNIQUE constraint on transaction_id is the final guard against duplicates.
    """
    if db.scalar(select(Payment.id).where(Payment.transaction_id == request.transaction_id)) is not None:
        raise _duplicate(request.transaction_id)

    student = db.scalar(select(Student).where(Student.student_no == request.student_no))
    if student is None:
        raise ApiError(404, "STUDENT_NOT_FOUND", f"Student {request.student_no} was not found")

    tuition = db.scalar(
        select(Tuition)
        .where(Tuition.student_id == student.id, Tuition.term == request.term)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if tuition is None:
        raise ApiError(
            404, "TUITION_NOT_FOUND", f"No tuition found for student {request.student_no} in {request.term}"
        )

    if request.amount > tuition.balance:
        db.rollback()  # release the row lock
        raise ApiError(
            422,
            "AMOUNT_EXCEEDS_BALANCE",
            f"Payment amount {request.amount:.2f} exceeds the outstanding balance {tuition.balance:.2f}",
            details={"balance": tuition.balance},
        )

    tuition.paid_amount = tuition.paid_amount + request.amount
    db.add(
        Payment(
            transaction_id=request.transaction_id,
            tuition_id=tuition.id,
            user_id=user_id,
            amount=request.amount,
            status="SUCCESS",
            channel="banking",
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _duplicate(request.transaction_id) from None

    return PaymentResponse(
        status="SUCCESS",
        transaction_id=request.transaction_id,
        student_no=request.student_no,
        term=request.term,
        paid_amount=request.amount,
        remaining_balance=tuition.balance,
        currency=tuition.currency,
    )

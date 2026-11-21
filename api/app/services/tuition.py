"""Read-side tuition logic shared by the mobile and banking query endpoints."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.errors import ApiError
from app.models import Student
from app.schemas import TermBalance, TuitionSummary

DEFAULT_CURRENCY = "USD"
ZERO = Decimal("0.00")


def get_student_or_404(db: Session, student_no: str) -> Student:
    student = db.scalar(
        select(Student).where(Student.student_no == student_no).options(selectinload(Student.tuitions))
    )
    if student is None:
        raise ApiError(404, "STUDENT_NOT_FOUND", f"Student {student_no} was not found")
    return student


def get_tuition_summary(db: Session, student_no: str) -> TuitionSummary:
    """Overall tuition total and balance for a student, with a per-term breakdown."""
    student = get_student_or_404(db, student_no)
    terms = [
        TermBalance(
            term=t.term,
            tuition_total=t.amount,
            paid_amount=t.paid_amount,
            balance=t.balance,
        )
        for t in student.tuitions
    ]
    return TuitionSummary(
        student_no=student.student_no,
        currency=student.tuitions[0].currency if student.tuitions else DEFAULT_CURRENCY,
        tuition_total=sum((t.tuition_total for t in terms), ZERO),
        balance=sum((t.balance for t in terms), ZERO),
        terms=terms,
    )

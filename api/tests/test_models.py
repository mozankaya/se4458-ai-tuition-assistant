from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Payment, Student, Tuition, User
from app.security import hash_password, verify_password
from app.seed import seed
from tests.conftest import TEST_DEMO_PASSWORD


def _student(session: Session, student_no: str = "99990001") -> Student:
    student = Student(student_no=student_no)
    session.add(student)
    session.flush()
    return student


def _tuition(session: Session, student: Student, **overrides) -> Tuition:
    values = {"term": "2026-FALL", "amount": Decimal("1000.00"), "paid_amount": Decimal("0.00")}
    values.update(overrides)
    tuition = Tuition(student_id=student.id, **values)
    session.add(tuition)
    session.flush()
    return tuition


def test_seed_creates_demo_data_and_is_idempotent(db_session: Session):
    first = seed(db_session, TEST_DEMO_PASSWORD)
    second = seed(db_session, TEST_DEMO_PASSWORD)

    assert first == {"students": 5, "tuitions": 6, "payments": 3, "users": 6}
    assert second == {"students": 0, "tuitions": 0, "payments": 0, "users": 0}
    tuition = db_session.scalar(
        select(Tuition).join(Student).where(Student.student_no == "20230004", Tuition.term == "2026-FALL")
    )
    assert tuition.balance == Decimal("1500.00")
    assert db_session.scalar(select(func.count()).select_from(User)) == 6


def test_seeded_payments_match_paid_amounts(db_session: Session):
    seed(db_session, TEST_DEMO_PASSWORD)

    for tuition in db_session.scalars(select(Tuition)):
        assert sum((p.amount for p in tuition.payments), Decimal("0.00")) == tuition.paid_amount


def test_duplicate_term_for_same_student_is_rejected(db_session: Session):
    student = _student(db_session)
    _tuition(db_session, student)

    with pytest.raises(IntegrityError):
        _tuition(db_session, student)


def test_paid_amount_cannot_exceed_amount(db_session: Session):
    student = _student(db_session)

    with pytest.raises(IntegrityError):
        _tuition(db_session, student, paid_amount=Decimal("1000.01"))


@pytest.mark.parametrize("term", ["2026-fall", "FALL-2026", "2026-WINTER"])
def test_invalid_term_format_is_rejected(db_session: Session, term: str):
    student = _student(db_session)

    with pytest.raises(IntegrityError):
        _tuition(db_session, student, term=term)


def test_duplicate_transaction_id_is_rejected(db_session: Session):
    tuition = _tuition(db_session, _student(db_session))
    db_session.add(Payment(transaction_id="txn-1", tuition_id=tuition.id, amount=Decimal("10.00")))
    db_session.flush()

    db_session.add(Payment(transaction_id="txn-1", tuition_id=tuition.id, amount=Decimal("20.00")))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_non_positive_payment_amount_is_rejected(db_session: Session):
    tuition = _tuition(db_session, _student(db_session))

    db_session.add(Payment(transaction_id="txn-zero", tuition_id=tuition.id, amount=Decimal("0.00")))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(
    ("role", "needs_student", "valid"),
    [("student", True, True), ("student", False, False), ("bank", True, False), ("auditor", False, False)],
)
def test_user_role_and_student_link_rules(db_session: Session, role: str, needs_student: bool, valid: bool):
    student = _student(db_session)
    db_session.add(
        User(
            username="u1",
            password_hash="x",
            role=role,
            student_id=student.id if needs_student else None,
        )
    )

    if valid:
        db_session.flush()
    else:
        with pytest.raises(IntegrityError):
            db_session.flush()


def test_password_hash_roundtrip():
    stored = hash_password("s3cret")

    assert stored != "s3cret"
    assert verify_password("s3cret", stored)
    assert not verify_password("wrong", stored)
    assert not verify_password("s3cret", "malformed-hash")

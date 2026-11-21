import threading
import uuid
from collections.abc import Callable
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import Payment, Student, Tuition
from app.schemas import PaymentRequest
from app.services.payments import pay_tuition

URL = "/api/v1/banking/payments"


def _body(**overrides) -> dict:
    body = {"studentNo": "20230001", "term": "2026-FALL", "amount": 500, "transactionId": str(uuid.uuid4())}
    body.update(overrides)
    return body


def _tuition(session: Session, student_no: str, term: str) -> Tuition:
    return session.scalar(
        select(Tuition).join(Student).where(Student.student_no == student_no, Tuition.term == term)
    )


# --- Success paths -------------------------------------------------------------------------------

def test_partial_payment_updates_balance_and_ledger(client: TestClient, seeded: Session, login: Callable):
    body = _body(amount=500)

    response = client.post(URL, json=body, headers=login("student1"))

    assert response.status_code == 201
    assert response.json() == {
        "status": "SUCCESS",
        "transactionId": body["transactionId"],
        "studentNo": "20230001",
        "term": "2026-FALL",
        "paidAmount": 500.0,
        "remainingBalance": 2500.0,
        "currency": "USD",
    }
    tuition = _tuition(seeded, "20230001", "2026-FALL")
    seeded.refresh(tuition)
    assert tuition.paid_amount == Decimal("500.00")
    payment = seeded.scalar(select(Payment).where(Payment.transaction_id == body["transactionId"]))
    assert payment.amount == Decimal("500.00")
    assert payment.user_id is not None


def test_full_payment_leaves_zero_balance(client: TestClient, seeded: Session, login: Callable):
    response = client.post(URL, json=_body(studentNo="20230004", amount=1500), headers=login("bank1"))

    assert response.status_code == 201
    assert response.json()["remainingBalance"] == 0.0


def test_successive_partial_payments_accumulate(client: TestClient, seeded: Session, login: Callable):
    headers = login("student1")

    first = client.post(URL, json=_body(amount="1000.50"), headers=headers)
    second = client.post(URL, json=_body(amount="999.50"), headers=headers)

    assert first.json()["remainingBalance"] == 1999.5
    assert second.json()["remainingBalance"] == 1000.0


# --- Business rule failures ----------------------------------------------------------------------

def test_duplicate_transaction_id_is_rejected(client: TestClient, seeded: Session, login: Callable):
    headers = login("student1")
    body = _body(amount=100)
    assert client.post(URL, json=body, headers=headers).status_code == 201

    retry = client.post(URL, json=body, headers=headers)

    assert retry.status_code == 409
    assert retry.json()["error"]["code"] == "DUPLICATE_TRANSACTION"
    tuition = _tuition(seeded, "20230001", "2026-FALL")
    seeded.refresh(tuition)
    assert tuition.paid_amount == Decimal("100.00")  # charged only once


def test_amount_exceeding_balance_is_rejected(client: TestClient, seeded: Session, login: Callable):
    response = client.post(URL, json=_body(studentNo="20230004", amount="1500.01"), headers=login("bank1"))

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "AMOUNT_EXCEEDS_BALANCE"
    assert error["details"] == {"balance": 1500.0}
    tuition = _tuition(seeded, "20230004", "2026-FALL")
    seeded.refresh(tuition)
    assert tuition.paid_amount == Decimal("1500.00")


def test_payment_on_fully_paid_term_is_rejected(client: TestClient, seeded: Session, login: Callable):
    response = client.post(URL, json=_body(studentNo="20230002", amount=1), headers=login("bank1"))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "AMOUNT_EXCEEDS_BALANCE"


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"studentNo": "99999999"}, "STUDENT_NOT_FOUND"),
        ({"term": "2030-FALL"}, "TUITION_NOT_FOUND"),
    ],
)
def test_unknown_student_or_term_returns_404(client: TestClient, seeded: Session, login: Callable,
                                             overrides, code):
    response = client.post(URL, json=_body(**overrides), headers=login("bank1"))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == code


# --- Input validation ----------------------------------------------------------------------------

@pytest.mark.parametrize(
    "overrides",
    [
        {"amount": 0},
        {"amount": -10},
        {"amount": "10.001"},
        {"amount": "abc"},
        {"term": "fall-2026"},
        {"transactionId": ""},
        {"transactionId": "has spaces"},
        {"studentNo": "abc"},
    ],
    ids=["zero", "negative", "three-decimals", "not-a-number", "bad-term", "empty-txn", "bad-txn", "bad-no"],
)
def test_invalid_payment_input_returns_422(client: TestClient, seeded: Session, login: Callable, overrides):
    response = client.post(URL, json=_body(**overrides), headers=login("bank1"))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_missing_fields_return_422(client: TestClient, seeded: Session, login: Callable):
    response = client.post(URL, json={"studentNo": "20230001"}, headers=login("bank1"))

    assert response.status_code == 422
    fields = {d["field"] for d in response.json()["error"]["details"]}
    assert fields == {"body.term", "body.amount", "body.transactionId"}


# --- Authorization -------------------------------------------------------------------------------

def test_student_cannot_pay_for_another_student(client: TestClient, seeded: Session, login: Callable):
    response = client.post(URL, json=_body(studentNo="20230002", term="2027-SPRING", amount=10),
                           headers=login("student1"))

    assert response.status_code == 403
    tuition = _tuition(seeded, "20230002", "2027-SPRING")
    seeded.refresh(tuition)
    assert tuition.paid_amount == Decimal("1000.00")


def test_admin_cannot_pay(client: TestClient, seeded: Session, login: Callable):
    response = client.post(URL, json=_body(), headers=login("admin1"))

    assert response.status_code == 403


def test_payment_requires_token(client: TestClient, seeded: Session):
    response = client.post(URL, json=_body())

    assert response.status_code == 401


# --- Concurrency (uses committed data and real separate connections) ------------------------------

def test_concurrent_payments_cannot_exceed_balance(engine: Engine):
    student_no = "88880001"
    with Session(engine) as setup:
        student = Student(student_no=student_no)
        setup.add(student)
        setup.flush()
        setup.add(Tuition(student_id=student.id, term="2026-FALL", amount=Decimal("100.00")))
        setup.commit()

    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def worker() -> None:
        request = PaymentRequest(student_no=student_no, term="2026-FALL", amount=Decimal("70.00"),
                                 transaction_id=str(uuid.uuid4()))
        with Session(engine) as session:
            barrier.wait()
            try:
                pay_tuition(session, request, None)
                outcomes.append("SUCCESS")
            except ApiError as exc:
                outcomes.append(exc.code)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert sorted(outcomes) == ["AMOUNT_EXCEEDS_BALANCE", "SUCCESS"]
        with Session(engine) as check:
            tuition = _tuition(check, student_no, "2026-FALL")
            assert tuition.paid_amount == Decimal("70.00")
            assert check.scalar(select(func.count()).select_from(Payment).where(
                Payment.tuition_id == tuition.id)) == 1
    finally:
        with Session(engine) as cleanup:
            student_id = cleanup.scalar(select(Student.id).where(Student.student_no == student_no))
            tuition_ids = select(Tuition.id).where(Tuition.student_id == student_id)
            cleanup.execute(delete(Payment).where(Payment.tuition_id.in_(tuition_ids)))
            cleanup.execute(delete(Tuition).where(Tuition.student_id == student_id))
            cleanup.execute(delete(Student).where(Student.id == student_id))
            cleanup.commit()

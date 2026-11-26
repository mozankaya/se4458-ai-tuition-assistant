from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Student, Tuition

URL = "/api/v1/admin/tuitions"
BATCH_URL = "/api/v1/admin/tuitions/batch"
SAMPLE_CSV = Path(__file__).resolve().parents[2] / "docs" / "samples" / "tuitions_batch_sample.csv"


def _tuition(session: Session, student_no: str, term: str) -> Tuition | None:
    return session.scalar(
        select(Tuition).join(Student).where(Student.student_no == student_no, Tuition.term == term)
    )


def _upload(client: TestClient, headers: dict, content: str | bytes):
    data = content.encode() if isinstance(content, str) else content
    return client.post(BATCH_URL, files={"file": ("tuitions.csv", data, "text/csv")}, headers=headers)


# --- Add Tuition ---------------------------------------------------------------------------------

def test_add_tuition_creates_record_and_student(client: TestClient, seeded: Session, login: Callable):
    body = {"studentNo": "20239999", "term": "2026-FALL", "amount": 3000, "currency": "USD"}

    response = client.post(URL, json=body, headers=login("admin1"))

    assert response.status_code == 201
    assert response.json() == {
        "status": "CREATED", "studentNo": "20239999", "term": "2026-FALL",
        "amount": 3000.0, "paidAmount": 0.0, "balance": 3000.0, "currency": "USD",
    }
    assert _tuition(seeded, "20239999", "2026-FALL").amount == Decimal("3000.00")


def test_add_tuition_updates_existing_record(client: TestClient, seeded: Session, login: Callable):
    body = {"studentNo": "20230004", "term": "2026-FALL", "amount": "3500.00", "currency": "USD"}

    response = client.post(URL, json=body, headers=login("admin1"))

    assert response.status_code == 200
    assert response.json()["status"] == "UPDATED"
    assert response.json()["balance"] == 2000.0  # 3500 - 1500 already paid


def test_currency_defaults_to_usd(client: TestClient, seeded: Session, login: Callable):
    response = client.post(URL, json={"studentNo": "20230005", "term": "2026-FALL", "amount": 100},
                           headers=login("admin1"))

    assert response.status_code == 201
    assert response.json()["currency"] == "USD"


def test_amount_below_paid_is_rejected(client: TestClient, seeded: Session, login: Callable):
    body = {"studentNo": "20230004", "term": "2026-FALL", "amount": "1499.99", "currency": "USD"}

    response = client.post(URL, json=body, headers=login("admin1"))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "AMOUNT_BELOW_PAID"
    assert _tuition(seeded, "20230004", "2026-FALL").amount == Decimal("3000.00")


def test_currency_mismatch_with_other_terms_is_rejected(client: TestClient, seeded: Session, login: Callable):
    body = {"studentNo": "20230001", "term": "2027-SUMMER", "amount": 500, "currency": "EUR"}

    response = client.post(URL, json=body, headers=login("admin1"))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CURRENCY_MISMATCH"


def test_currency_change_after_payment_is_rejected(client: TestClient, seeded: Session, login: Callable):
    body = {"studentNo": "20230004", "term": "2026-FALL", "amount": 3000, "currency": "EUR"}

    response = client.post(URL, json=body, headers=login("admin1"))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CURRENCY_CHANGE_NOT_ALLOWED"


@pytest.mark.parametrize(
    "overrides",
    [{"amount": -1}, {"amount": "1.234"}, {"term": "2026-WINTER"}, {"currency": "usd"}, {"studentNo": "x1"}],
    ids=["negative", "three-decimals", "bad-term", "lowercase-currency", "bad-student-no"],
)
def test_add_tuition_invalid_input_returns_422(client: TestClient, seeded: Session, login: Callable, overrides):
    body = {"studentNo": "20230005", "term": "2026-FALL", "amount": 100, "currency": "USD", **overrides}

    response = client.post(URL, json=body, headers=login("admin1"))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("username", ["student1", "bank1"])
def test_add_tuition_requires_admin(client: TestClient, seeded: Session, login: Callable, username):
    body = {"studentNo": "20230005", "term": "2026-FALL", "amount": 100, "currency": "USD"}

    assert client.post(URL, json=body, headers=login(username)).status_code == 403
    assert client.post(URL, json=body).status_code == 401


# --- Batch ---------------------------------------------------------------------------------------

def test_batch_sample_file_reports_counts_and_row_errors(client: TestClient, seeded: Session, login: Callable):
    response = _upload(client, login("admin1"), SAMPLE_CSV.read_bytes())

    assert response.status_code == 200
    body = response.json()
    assert {k: body[k] for k in ("status", "totalRows", "successCount", "failureCount",
                                 "createdCount", "updatedCount")} == {
        "status": "PARTIAL", "totalRows": 7, "successCount": 4, "failureCount": 3,
        "createdCount": 3, "updatedCount": 1,
    }
    assert [(e["line"], e["code"]) for e in body["errors"]] == [
        (6, "AMOUNT_BELOW_PAID"), (7, "VALIDATION_ERROR"), (8, "VALIDATION_ERROR"),
    ]
    # Valid rows were saved despite the failing ones.
    assert _tuition(seeded, "20230005", "2027-SPRING").amount == Decimal("3000.00")
    assert _tuition(seeded, "20230003", "2026-FALL").amount == Decimal("300.00")
    assert _tuition(seeded, "20230002", "2026-FALL").amount == Decimal("2250.00")
    assert _tuition(seeded, "20230007", "2026-AUTUMN") is None


def test_batch_all_valid_rows_completes(client: TestClient, seeded: Session, login: Callable):
    csv_text = "studentNo,term,amount,currency\n20230010,2026-FALL,100.00,USD\n\n20230011,2026-FALL,200,USD\n"

    body = _upload(client, login("admin1"), csv_text).json()

    assert body["status"] == "COMPLETED"
    assert body["successCount"] == 2
    assert body["errors"] == []


def test_batch_duplicate_rows_last_one_wins(client: TestClient, seeded: Session, login: Callable):
    csv_text = "studentNo,term,amount,currency\n20230010,2026-FALL,100,USD\n20230010,2026-FALL,150,USD\n"

    body = _upload(client, login("admin1"), csv_text).json()

    assert (body["createdCount"], body["updatedCount"]) == (1, 1)
    assert _tuition(seeded, "20230010", "2026-FALL").amount == Decimal("150.00")


def test_batch_all_rows_failing_reports_failed(client: TestClient, seeded: Session, login: Callable):
    csv_text = "studentNo,term,amount,currency\n20230010,2026-FALL,abc,USD\n20230010,2026-FALL\n"

    body = _upload(client, login("admin1"), csv_text).json()

    assert body["status"] == "FAILED"
    assert [e["code"] for e in body["errors"]] == ["VALIDATION_ERROR", "INVALID_ROW"]


def test_batch_accepts_utf8_bom(client: TestClient, seeded: Session, login: Callable):
    content = "﻿studentNo,term,amount,currency\n20230010,2026-FALL,100,USD\n".encode()

    assert _upload(client, login("admin1"), content).json()["status"] == "COMPLETED"


@pytest.mark.parametrize(
    "content",
    ["student,term,amount\n1,2026-FALL,1\n", "", "studentNo,term,amount,currency\n", b"\xff\xfe\x00bad"],
    ids=["wrong-header", "empty", "header-only", "not-utf8"],
)
def test_batch_invalid_file_returns_422(client: TestClient, seeded: Session, login: Callable, content):
    response = _upload(client, login("admin1"), content)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_CSV"


def test_batch_requires_admin(client: TestClient, seeded: Session, login: Callable):
    response = _upload(client, login("bank1"), "studentNo,term,amount,currency\n")

    assert response.status_code == 403


# --- Batch edge cases ----------------------------------------------------------------------------

def test_batch_accepts_crlf_quotes_and_trailing_commas(client: TestClient, seeded: Session, login: Callable):
    # Spreadsheet exports: Windows line endings, quoted cells, an empty trailing column.
    content = 'studentNo,term,amount,currency,\r\n"20230010","2026-FALL"," 100.50 ",USD,\r\n'

    body = _upload(client, login("admin1"), content).json()

    assert body["status"] == "COMPLETED", body
    assert _tuition(seeded, "20230010", "2026-FALL").amount == Decimal("100.50")


def test_batch_row_with_extra_column_is_reported(client: TestClient, seeded: Session, login: Callable):
    content = "studentNo,term,amount,currency\n20230010,2026-FALL,100,USD,extra\n20230011,2026-FALL,100,USD\n"

    body = _upload(client, login("admin1"), content).json()

    assert body["status"] == "PARTIAL"
    assert [(e["line"], e["code"]) for e in body["errors"]] == [(2, "INVALID_ROW")]


def test_batch_line_numbers_count_blank_lines_and_multiline_cells(
    client: TestClient, seeded: Session, login: Callable
):
    content = 'studentNo,term,amount,currency\n\n"20230010\nx",2026-FALL,100,USD\n20230011,2026-FALL,-5,USD\n'

    body = _upload(client, login("admin1"), content).json()

    # The quoted cell spans lines 3-4, so the next row is line 5.
    assert [(e["line"], e["code"]) for e in body["errors"]] == [(4, "VALIDATION_ERROR"), (5, "VALIDATION_ERROR")]


def test_batch_rows_conflicting_inside_one_file(client: TestClient, seeded: Session, login: Callable):
    content = "studentNo,term,amount,currency\n20230010,2026-FALL,100,USD\n20230010,2027-SPRING,100,EUR\n"

    body = _upload(client, login("admin1"), content).json()

    assert body["status"] == "PARTIAL"
    assert [(e["line"], e["code"]) for e in body["errors"]] == [(3, "CURRENCY_MISMATCH")]
    assert _tuition(seeded, "20230010", "2026-FALL") is not None
    assert _tuition(seeded, "20230010", "2027-SPRING") is None


def test_batch_semicolon_file_explains_expected_header(client: TestClient, seeded: Session, login: Callable):
    response = _upload(client, login("admin1"), "studentNo;term;amount;currency\n20230010;2026-FALL;100;USD\n")

    assert response.status_code == 422
    assert "comma-separated" in response.json()["error"]["message"]


@pytest.mark.parametrize(
    "content",
    [b"studentNo,term,amount,currency\n20230010,2026-FALL,1\x0000,USD\n",
     ("studentNo,term,amount,currency\n" + '"' + "x" * 200_000 + '",2026-FALL,1,USD\n').encode()],
    ids=["nul-byte", "huge-cell"],
)
def test_batch_malformed_file_is_rejected_without_changes(
    client: TestClient, seeded: Session, login: Callable, content
):
    before = seeded.scalar(select(func.count()).select_from(Tuition))

    response = _upload(client, login("admin1"), content)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_CSV"
    assert seeded.scalar(select(func.count()).select_from(Tuition)) == before


def test_batch_too_many_rows_is_rejected_before_any_write(
    client: TestClient, seeded: Session, login: Callable, monkeypatch
):
    monkeypatch.setattr("app.services.admin.MAX_BATCH_ROWS", 2)
    content = "studentNo,term,amount,currency\n" + "".join(f"2023002{i},2026-FALL,100,USD\n" for i in range(3))

    response = _upload(client, login("admin1"), content)

    assert response.status_code == 422
    assert _tuition(seeded, "20230020", "2026-FALL") is None


def test_batch_file_too_large_returns_413(client: TestClient, seeded: Session, login: Callable, monkeypatch):
    monkeypatch.setattr("app.services.admin.MAX_BATCH_BYTES", 50)
    content = "studentNo,term,amount,currency\n20230010,2026-FALL,100,USD\n"

    response = _upload(client, login("admin1"), content)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"

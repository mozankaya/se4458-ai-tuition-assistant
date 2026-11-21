from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

URL = "/api/v1/banking/tuition/{}"


def test_bank_can_query_any_student(client: TestClient, seeded: Session, login: Callable):
    response = client.get(URL.format("20230004"), headers=login("bank1"))

    assert response.status_code == 200
    body = response.json()
    assert body["studentNo"] == "20230004"
    assert body["tuitionTotal"] == 3000.0
    assert body["balance"] == 1500.0
    assert body["terms"] == [
        {"term": "2026-FALL", "tuitionTotal": 3000.0, "paidAmount": 1500.0, "balance": 1500.0}
    ]


def test_student_can_query_own_tuition(client: TestClient, seeded: Session, login: Callable):
    response = client.get(URL.format("20230001"), headers=login("student1"))

    assert response.status_code == 200
    assert response.json()["balance"] == 6000.0


def test_student_cannot_query_another_student(client: TestClient, seeded: Session, login: Callable):
    response = client.get(URL.format("20230002"), headers=login("student1"))

    assert response.status_code == 403
    assert response.json()["error"] == {
        "code": "FORBIDDEN",
        "message": "Students can only access their own tuition records",
    }


def test_admin_role_is_not_allowed(client: TestClient, seeded: Session, login: Callable):
    response = client.get(URL.format("20230001"), headers=login("admin1"))

    assert response.status_code == 403


def test_missing_token_returns_401(client: TestClient, seeded: Session):
    response = client.get(URL.format("20230001"))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_unknown_student_returns_404_for_bank(client: TestClient, seeded: Session, login: Callable):
    response = client.get(URL.format("99999999"), headers=login("bank1"))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "STUDENT_NOT_FOUND"


def test_banking_query_is_not_rate_limited(client: TestClient, seeded: Session, login: Callable):
    headers = login("bank1")

    statuses = {client.get(URL.format("20230001"), headers=headers).status_code for _ in range(5)}

    assert statuses == {200}


@pytest.mark.parametrize("student_no", ["abc", "2023-0001"])
def test_invalid_student_no_returns_422(client: TestClient, seeded: Session, login: Callable, student_no):
    response = client.get(URL.format(student_no), headers=login("bank1"))

    assert response.status_code == 422

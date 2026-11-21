from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RateLimitCounter
from app.rate_limit import local_now

URL = "/api/v1/mobile/tuition/{}"
IST = ZoneInfo("Europe/Istanbul")


@pytest.fixture
def clock(client: TestClient):
    """Controllable 'now' for the rate limiter. Set clock['now'] to move time."""
    state = {"now": datetime(2026, 11, 21, 10, 0, tzinfo=IST)}
    client.app.dependency_overrides[local_now] = lambda: state["now"]
    return state


def test_query_returns_overall_and_per_term_balance(client: TestClient, seeded: Session, clock):
    response = client.get(URL.format("20230002"))

    assert response.status_code == 200
    assert response.json() == {
        "studentNo": "20230002",
        "currency": "USD",
        "tuitionTotal": 4500.0,
        "balance": 1250.0,
        "terms": [
            {"term": "2026-FALL", "tuitionTotal": 2250.0, "paidAmount": 2250.0, "balance": 0.0},
            {"term": "2027-SPRING", "tuitionTotal": 2250.0, "paidAmount": 1000.0, "balance": 1250.0},
        ],
    }
    assert response.headers["X-RateLimit-Limit"] == "3"
    assert response.headers["X-RateLimit-Remaining"] == "2"


def test_query_requires_no_authentication(client: TestClient, seeded: Session, clock):
    response = client.get(URL.format("20230001"), headers={"Authorization": "Bearer garbage"})

    assert response.status_code == 200


def test_student_without_tuition_returns_zero_balance(client: TestClient, seeded: Session, clock):
    response = client.get(URL.format("20230005"))

    assert response.status_code == 200
    body = response.json()
    assert body["tuitionTotal"] == 0.0
    assert body["balance"] == 0.0
    assert body["terms"] == []


def test_unknown_student_returns_404(client: TestClient, seeded: Session, clock):
    response = client.get(URL.format("99999999"))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "STUDENT_NOT_FOUND"


@pytest.mark.parametrize("student_no", ["abc", "2023-0001", "1" * 21])
def test_invalid_student_no_format_returns_422(client: TestClient, seeded: Session, clock, student_no):
    response = client.get(URL.format(student_no))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_fourth_call_same_day_returns_429(client: TestClient, seeded: Session, clock):
    statuses = [client.get(URL.format("20230001")).status_code for _ in range(3)]
    fourth = client.get(URL.format("20230001"))

    assert statuses == [200, 200, 200]
    assert fourth.status_code == 429
    assert fourth.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert fourth.headers["X-RateLimit-Remaining"] == "0"
    # 10:00 local time -> 14 hours until midnight Istanbul time
    assert fourth.headers["Retry-After"] == str(14 * 3600)


def test_limit_is_keyed_by_student_not_client(client: TestClient, seeded: Session, clock):
    for _ in range(3):
        client.get(URL.format("20230001"))

    assert client.get(URL.format("20230001")).status_code == 429
    assert client.get(URL.format("20230002")).status_code == 200


def test_limit_resets_on_next_istanbul_day(client: TestClient, seeded: Session, clock):
    clock["now"] = datetime(2026, 11, 21, 23, 59, tzinfo=IST)
    for _ in range(3):
        client.get(URL.format("20230001"))
    assert client.get(URL.format("20230001")).status_code == 429

    clock["now"] = datetime(2026, 11, 22, 0, 1, tzinfo=IST)

    assert client.get(URL.format("20230001")).status_code == 200


def test_unknown_student_numbers_are_counted_too(client: TestClient, seeded: Session, clock):
    statuses = [client.get(URL.format("99999999")).status_code for _ in range(4)]

    assert statuses == [404, 404, 404, 429]


def test_counter_is_stored_per_student_and_day(client: TestClient, seeded: Session, clock):
    client.get(URL.format("20230003"))
    client.get(URL.format("20230003"))

    counter = seeded.scalar(select(RateLimitCounter).where(RateLimitCounter.student_no == "20230003"))
    assert counter.request_count == 2
    assert counter.window_date.isoformat() == "2026-11-21"
    assert counter.endpoint == "mobile_tuition_query"

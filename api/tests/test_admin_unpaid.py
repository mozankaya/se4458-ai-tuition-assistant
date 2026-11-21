from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

URL = "/api/v1/admin/tuitions/unpaid"


def _keys(body: dict) -> list[tuple[str, str]]:
    return [(item["studentNo"], item["term"]) for item in body["items"]]


def test_unpaid_for_term_lists_only_outstanding_records(client: TestClient, seeded: Session, login: Callable):
    response = client.get(URL, params={"term": "2026-FALL"}, headers=login("admin1"))

    assert response.status_code == 200
    body = response.json()
    assert {k: body[k] for k in ("term", "page", "pageSize", "totalItems", "totalPages")} == {
        "term": "2026-FALL", "page": 1, "pageSize": 20, "totalItems": 3, "totalPages": 1,
    }
    # 20230002 paid Fall in full, so it is excluded.
    assert _keys(body) == [("20230001", "2026-FALL"), ("20230003", "2026-FALL"), ("20230004", "2026-FALL")]
    assert body["items"][2] == {
        "studentNo": "20230004", "fullName": "Jordan Smith", "term": "2026-FALL",
        "tuitionTotal": 3000.0, "paidAmount": 1500.0, "balance": 1500.0, "currency": "USD",
    }


def test_unpaid_without_term_covers_all_terms(client: TestClient, seeded: Session, login: Callable):
    body = client.get(URL, headers=login("admin1")).json()

    assert body["term"] is None
    assert body["totalItems"] == 5
    assert ("20230002", "2027-SPRING") in _keys(body)


def test_paging_splits_results_in_stable_order(client: TestClient, seeded: Session, login: Callable):
    headers = login("admin1")

    pages = [client.get(URL, params={"page": p, "pageSize": 2}, headers=headers).json() for p in (1, 2, 3)]

    assert [len(p["items"]) for p in pages] == [2, 2, 1]
    assert all(p["totalPages"] == 3 and p["totalItems"] == 5 for p in pages)
    assert [k for p in pages for k in _keys(p)] == [
        ("20230001", "2026-FALL"), ("20230001", "2027-SPRING"), ("20230002", "2027-SPRING"),
        ("20230003", "2026-FALL"), ("20230004", "2026-FALL"),
    ]


def test_page_past_end_returns_empty_items(client: TestClient, seeded: Session, login: Callable):
    body = client.get(URL, params={"page": 99}, headers=login("admin1")).json()

    assert body["items"] == []
    assert body["totalItems"] == 5


def test_term_with_no_unpaid_records_returns_empty_page(client: TestClient, seeded: Session, login: Callable):
    body = client.get(URL, params={"term": "2030-FALL"}, headers=login("admin1")).json()

    assert body["totalItems"] == 0
    assert body["totalPages"] == 0
    assert body["items"] == []


@pytest.mark.parametrize(
    "params",
    [{"page": 0}, {"pageSize": 0}, {"pageSize": 101}, {"page": "x"}, {"term": "fall"}],
    ids=["page-zero", "size-zero", "size-too-big", "page-not-int", "bad-term"],
)
def test_invalid_query_params_return_422(client: TestClient, seeded: Session, login: Callable, params):
    response = client.get(URL, params=params, headers=login("admin1"))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("username", ["student1", "bank1"])
def test_unpaid_requires_admin(client: TestClient, seeded: Session, login: Callable, username):
    assert client.get(URL, headers=login(username)).status_code == 403


def test_unpaid_requires_token(client: TestClient, seeded: Session):
    assert client.get(URL).status_code == 401

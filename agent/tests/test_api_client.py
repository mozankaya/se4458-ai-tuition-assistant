import json
from decimal import Decimal

import httpx
import pytest

from tuition_agent.api_client import ApiCallError, TuitionApiClient

GATEWAY = "http://gateway.test"
SUMMARY = {"studentNo": "20230001", "currency": "USD", "tuitionTotal": 6000.0, "balance": 6000.0, "terms": []}


class FakeGateway:
    """Records requests and answers like the Tuition API behind the gateway."""

    def __init__(self, role: str = "student", student_no: str | None = "20230001") -> None:
        self.requests: list[httpx.Request] = []
        self.role, self.student_no = role, student_no

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/api/v1/auth/login":
            if json.loads(request.content)["password"] != "right":
                return httpx.Response(401, json={"error": {"code": "INVALID_CREDENTIALS", "message": "bad"}})
            return httpx.Response(200, json={"access_token": "jwt-1", "token_type": "bearer", "expires_in": 3600,
                                             "role": self.role, "student_no": self.student_no})
        if path.startswith("/api/v1/banking/tuition/"):
            return httpx.Response(200, json=SUMMARY)
        if path == "/api/v1/banking/payments":
            body = json.loads(request.content)
            if body["amount"] == "99999":
                return httpx.Response(422, json={"error": {"code": "AMOUNT_EXCEEDS_BALANCE", "message": "too much",
                                                           "details": {"balance": 3000.0}}})
            return httpx.Response(201, json={"status": "SUCCESS", "transactionId": body["transactionId"]})
        if path == "/api/v1/gateway-error":
            return httpx.Response(502, text="<html>Bad Gateway</html>")
        return httpx.Response(404, json={"message": "no Route matched with those values"})


def _client(gateway: FakeGateway) -> TuitionApiClient:
    http = httpx.Client(base_url=GATEWAY, transport=httpx.MockTransport(gateway.handler))
    return TuitionApiClient(GATEWAY, http_client=http)


def test_login_stores_token_and_student_no_from_response():
    gateway = FakeGateway()
    client = _client(gateway)

    client.login("student1", "right")

    assert client.is_logged_in
    assert client.student_no == "20230001"
    assert "authorization" not in gateway.requests[0].headers


def test_get_my_tuition_uses_token_student_and_bearer_header():
    gateway = FakeGateway()
    client = _client(gateway)
    client.login("student1", "right")

    assert client.get_my_tuition() == SUMMARY

    request = gateway.requests[-1]
    assert str(request.url) == f"{GATEWAY}/api/v1/banking/tuition/20230001"
    assert request.headers["authorization"] == "Bearer jwt-1"


def test_pay_tuition_sends_exact_amount_and_transaction_id():
    gateway = FakeGateway()
    client = _client(gateway)
    client.login("student1", "right")

    result = client.pay_tuition("2026-FALL", Decimal("500.50"), "txn-123")

    assert result == {"status": "SUCCESS", "transactionId": "txn-123"}
    assert json.loads(gateway.requests[-1].content) == {
        "studentNo": "20230001", "term": "2026-FALL", "amount": "500.50", "transactionId": "txn-123",
    }


def test_wrong_password_raises_api_error():
    client = _client(FakeGateway())

    with pytest.raises(ApiCallError) as exc:
        client.login("student1", "wrong")

    assert (exc.value.status_code, exc.value.code) == (401, "INVALID_CREDENTIALS")
    assert not client.is_logged_in


@pytest.mark.parametrize(("role", "student_no"), [("bank", None), ("admin", None)])
def test_non_student_accounts_are_rejected(role, student_no):
    client = _client(FakeGateway(role=role, student_no=student_no))

    with pytest.raises(ApiCallError) as exc:
        client.login("staff", "right")

    assert exc.value.code == "STUDENT_ACCOUNT_REQUIRED"
    assert not client.is_logged_in


def test_calls_before_login_are_rejected_without_network():
    gateway = FakeGateway()

    with pytest.raises(ApiCallError) as exc:
        _client(gateway).get_my_tuition()

    assert exc.value.code == "NOT_LOGGED_IN"
    assert gateway.requests == []


def test_api_error_keeps_code_and_details_for_the_llm():
    client = _client(FakeGateway())
    client.login("student1", "right")

    with pytest.raises(ApiCallError) as exc:
        client.pay_tuition("2026-FALL", Decimal("99999"), "txn-1")

    assert exc.value.to_dict() == {"error": {"status": 422, "code": "AMOUNT_EXCEEDS_BALANCE",
                                             "message": "too much", "details": {"balance": 3000.0}}}


@pytest.mark.parametrize(
    ("path", "status", "message"),
    [("/gateway-error", 502, "<html>Bad Gateway</html>"), ("/unknown", 404, "no Route matched with those values")],
)
def test_non_api_error_bodies_are_handled(path, status, message):
    client = _client(FakeGateway())

    with pytest.raises(ApiCallError) as exc:
        client._request("GET", path, auth=False)

    assert (exc.value.status_code, exc.value.code, exc.value.message) == (status, "HTTP_ERROR", message)


def test_network_failure_becomes_api_error():
    def fail(request):
        raise httpx.ConnectError("refused")

    client = TuitionApiClient(GATEWAY, http_client=httpx.Client(base_url=GATEWAY, transport=httpx.MockTransport(fail)))

    with pytest.raises(ApiCallError) as exc:
        client.login("student1", "right")

    assert (exc.value.status_code, exc.value.code) == (503, "NETWORK_ERROR")


def test_logout_clears_identity():
    client = _client(FakeGateway())
    client.login("student1", "right")

    client.logout()

    assert not client.is_logged_in
    assert client.student_no is None

"""REST client for the Tuition API. All calls go to the API Gateway base URL."""

from decimal import Decimal
from typing import Any

import httpx

API_PREFIX = "/api/v1"


class ApiCallError(Exception):
    """A failed REST call, in the API's error format so it can be passed back to the LLM."""

    def __init__(self, status_code: int, code: str, message: str, details: Any = None) -> None:
        super().__init__(f"{status_code} {code}: {message}")
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        error: dict[str, Any] = {"status": self.status_code, "code": self.code, "message": self.message}
        if self.details is not None:
            error["details"] = self.details
        return {"error": error}


class TuitionApiClient:
    """Holds the logged-in student's JWT. The student number always comes from the login response."""

    def __init__(self, base_url: str, http_client: httpx.Client | None = None, timeout: float = 15.0) -> None:
        self._http = http_client or httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)
        self._token: str | None = None
        self.username: str | None = None
        self.student_no: str | None = None

    @property
    def is_logged_in(self) -> bool:
        return self._token is not None

    def login(self, username: str, password: str) -> None:
        body = self._request("POST", "/auth/login", json={"username": username, "password": password}, auth=False)
        if body.get("role") != "student" or not body.get("student_no"):
            raise ApiCallError(403, "STUDENT_ACCOUNT_REQUIRED", "The assistant is available to student accounts only")
        self._token = body["access_token"]
        self.username = username
        self.student_no = body["student_no"]

    def logout(self) -> None:
        self._token = self.username = self.student_no = None

    def get_my_tuition(self) -> dict[str, Any]:
        return self._request("GET", f"/banking/tuition/{self._require_student()}")

    def pay_tuition(self, term: str, amount: Decimal, transaction_id: str) -> dict[str, Any]:
        payload = {
            "studentNo": self._require_student(),
            "term": term,
            "amount": str(amount),  # string keeps the exact decimal value
            "transactionId": transaction_id,
        }
        return self._request("POST", "/banking/payments", json=payload)

    def _require_student(self) -> str:
        if self._token is None or self.student_no is None:
            raise ApiCallError(401, "NOT_LOGGED_IN", "Log in before calling the Tuition API")
        return self.student_no

    def _request(self, method: str, path: str, *, json: Any = None, auth: bool = True) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._token}"} if auth and self._token else {}
        try:
            response = self._http.request(method, API_PREFIX + path, json=json, headers=headers)
        except httpx.HTTPError as exc:
            raise ApiCallError(503, "NETWORK_ERROR", f"Tuition API is unreachable: {exc.__class__.__name__}") from exc

        try:
            body = response.json()
        except ValueError:
            body = None
        if response.is_success and isinstance(body, dict):
            return body

        error = body.get("error") if isinstance(body, dict) else None
        if isinstance(error, dict):
            raise ApiCallError(response.status_code, error.get("code", "ERROR"), error.get("message", ""),
                               error.get("details"))
        # Errors produced by the gateway itself may not use the API's error format.
        message = body.get("message") if isinstance(body, dict) else response.text[:200]
        raise ApiCallError(response.status_code, "HTTP_ERROR", message or response.reason_phrase)

"""Web chat API with a scripted LLM and fake backends (no network, no live LLM)."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from tests.fakes import FakeApi, FakePolicies, ScriptedLLM, calls, says, tool_call
from tuition_agent.agent import AgentError, TuitionAgent
from tuition_agent.api_client import ApiCallError
from tuition_agent.web import create_app


class FakeLoginApi(FakeApi):
    def __init__(self) -> None:
        super().__init__()
        self.username = self.student_no = None

    def login(self, username: str, password: str) -> None:
        if password != "right":
            raise ApiCallError(401, "INVALID_CREDENTIALS", "Invalid username or password")
        self.username, self.student_no = username, "20230001"


@pytest.fixture
def web(tmp_path):
    state = {"llm": ScriptedLLM(), "api": None}

    def make_api():
        state["api"] = FakeLoginApi()
        return state["api"]

    def make_agent(api):
        return TuitionAgent(llm=state["llm"], api=api, policies=FakePolicies(),
                            confirm_payment=lambda summary: None, llm_label="mock")

    client = TestClient(create_app(make_api, make_agent, trace_dir=tmp_path))
    return client, state, tmp_path


def _login(client: TestClient) -> None:
    assert client.post("/api/login", json={"username": "student1", "password": "right"}).status_code == 200


def test_index_page_is_served(web):
    client, *_ = web

    response = client.get("/")

    assert response.status_code == 200
    assert "AI Tuition Assistant" in response.text


def test_wrong_password_returns_401(web):
    client, *_ = web

    response = client.post("/api/login", json={"username": "student1", "password": "wrong"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid username or password"


@pytest.mark.parametrize(("method", "url", "body"), [
    ("get", "/api/me", None), ("post", "/api/chat", {"message": "hi"}), ("post", "/api/confirm", {"approved": True}),
])
def test_endpoints_require_login(web, method, url, body):
    client, *_ = web

    response = client.request(method.upper(), url, json=body)

    assert response.status_code == 401


def test_chat_returns_answer_trace_and_saves_trace_file(web):
    client, state, trace_dir = web
    state["llm"].responses += [calls(tool_call("get_my_tuition")), says("Your balance is 6,000.00 USD.")]
    _login(client)

    data = client.post("/api/chat", json={"message": "What is my balance?"}).json()

    assert data["answer"] == "Your balance is 6,000.00 USD."
    assert data["error"] is None
    assert [t["tool"] for t in data["trace"]] == ["get_my_tuition"]
    assert data["pendingPayment"] is None
    assert (trace_dir / data["traceFile"]).exists()
    assert client.get("/api/me").json()["studentNo"] == "20230001"


def test_payment_waits_for_confirm_button_then_pays(web):
    client, state, _ = web
    state["llm"].responses += [
        calls(tool_call("pay_tuition", {"term": "2026-FALL", "amount": 500})),
        says("Please confirm the payment of 500.00 USD."),
        says("Payment of 500.00 USD recorded. Remaining balance: 2,500.00 USD."),
    ]
    _login(client)

    asked = client.post("/api/chat", json={"message": "Pay 500 for 2026-FALL"}).json()

    assert asked["pendingPayment"] == {"studentNo": "20230001", "term": "2026-FALL", "amount": 500.0,
                                       "currentBalance": 3000.0, "balanceAfter": 2500.0, "currency": "USD"}
    assert asked["trace"][0]["result"]["status"] == "CONFIRMATION_REQUIRED"
    assert asked["trace"][0]["confirmation"] == "pending"
    assert state["api"].payments == []  # nothing is paid before the click

    confirmed = client.post("/api/confirm", json={"approved": True}).json()

    assert [(t, a) for t, a, _ in state["api"].payments] == [("2026-FALL", Decimal("500.00"))]
    assert confirmed["trace"][0]["confirmation"] == "yes"
    assert confirmed["trace"][0]["result"]["status"] == "SUCCESS"
    assert confirmed["pendingPayment"] is None
    assert "recorded" in confirmed["answer"]


def test_cancel_button_does_not_pay(web):
    client, state, _ = web
    state["llm"].responses += [
        calls(tool_call("pay_tuition", {"term": "2026-FALL", "amount": 500})),
        says("Please confirm."),
        says("The payment was cancelled."),
    ]
    _login(client)
    client.post("/api/chat", json={"message": "Pay 500"})

    cancelled = client.post("/api/confirm", json={"approved": False}).json()

    assert state["api"].payments == []
    assert cancelled["trace"][0]["confirmation"] == "no"
    assert cancelled["trace"][0]["result"]["status"] == "CANCELLED"


def test_confirm_without_pending_payment_returns_409(web):
    client, *_ = web
    _login(client)

    assert client.post("/api/confirm", json={"approved": True}).status_code == 409


def test_llm_failure_after_payment_still_reports_the_payment(web):
    client, state, _ = web

    class FailAfterFirstCall(ScriptedLLM):
        def complete(self, messages, tools):
            if self.calls and len(self.calls) >= 2:
                raise RuntimeError("provider error")
            return super().complete(messages, tools)

    state["llm"] = FailAfterFirstCall(calls(tool_call("pay_tuition", {"term": "2026-FALL", "amount": 100})),
                                      says("Please confirm."))
    _login(client)
    client.post("/api/chat", json={"message": "Pay 100"})

    data = client.post("/api/confirm", json={"approved": True}).json()

    assert "WAS recorded" in data["error"]
    assert len(state["api"].payments) == 1


def test_empty_message_is_rejected(web):
    client, *_ = web
    _login(client)

    assert client.post("/api/chat", json={"message": ""}).status_code == 422


def test_resolve_without_pending_payment_raises():
    agent = TuitionAgent(llm=ScriptedLLM(), api=FakeApi(), policies=FakePolicies(), confirm_payment=lambda s: None)

    with pytest.raises(ValueError):
        agent.resolve_pending_payment(True)


def test_cli_style_immediate_confirmation_still_works():
    agent = TuitionAgent(llm=ScriptedLLM(calls(tool_call("pay_tuition", {"term": "2026-FALL", "amount": 10})),
                                         says("Paid.")),
                         api=FakeApi(), policies=FakePolicies(), confirm_payment=lambda s: True)

    trace = agent.ask("Pay 10")

    assert trace.tool_calls[0].confirmation == "yes"
    assert agent.pending_payment is None
    assert not isinstance(trace, AgentError)

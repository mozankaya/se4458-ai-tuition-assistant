"""Test doubles: a scripted LLM and fake REST/MCP clients (no network, no live LLM)."""

import json
from decimal import Decimal
from typing import Any

from tuition_agent.api_client import ApiCallError
from tuition_agent.llm import LLMResponse, ToolCall


def tool_call(name: str, arguments: dict | None = None, call_id: str | None = None, raw: str | None = None) -> ToolCall:
    raw_arguments = raw if raw is not None else json.dumps(arguments or {})
    error = "Invalid JSON arguments" if raw is not None else None
    return ToolCall(id=call_id or f"call_{name}", name=name, arguments=arguments or {},
                    raw_arguments=raw_arguments, argument_error=error)


class ScriptedLLM:
    """Returns prepared responses in order and records the messages it received."""

    def __init__(self, *responses: LLMResponse) -> None:
        self.responses = list(responses)
        self.calls: list[list[dict[str, Any]]] = []

    def complete(self, messages, tools) -> LLMResponse:
        self.calls.append([dict(m) for m in messages])
        return self.responses.pop(0)


def says(text: str) -> LLMResponse:
    return LLMResponse(content=text, usage={"prompt_tokens": 100, "completion_tokens": 20})


def calls(*tool_calls: ToolCall) -> LLMResponse:
    return LLMResponse(content=None, tool_calls=list(tool_calls), usage={"prompt_tokens": 100, "completion_tokens": 10})


class FakeApi:
    username = "student1"
    student_no = "20230001"

    def __init__(self) -> None:
        self.balances = {"2026-FALL": Decimal("3000.00"), "2027-SPRING": Decimal("3000.00")}
        self.payments: list[tuple[str, Decimal, str]] = []

    def get_my_tuition(self) -> dict[str, Any]:
        terms = [{"term": t, "tuitionTotal": 3000.0, "paidAmount": float(3000 - b), "balance": float(b)}
                 for t, b in self.balances.items()]
        return {"studentNo": self.student_no, "currency": "USD", "tuitionTotal": 6000.0,
                "balance": float(sum(self.balances.values())), "terms": terms}

    def pay_tuition(self, term: str, amount: Decimal, transaction_id: str) -> dict[str, Any]:
        if amount > self.balances[term]:
            raise ApiCallError(422, "AMOUNT_EXCEEDS_BALANCE", "too much")
        self.balances[term] -= amount
        self.payments.append((term, amount, transaction_id))
        return {"status": "SUCCESS", "transactionId": transaction_id, "studentNo": self.student_no, "term": term,
                "paidAmount": float(amount), "remainingBalance": float(self.balances[term]), "currency": "USD"}


class FakePolicies:
    def __init__(self) -> None:
        self.queries: list[tuple[str, int]] = []

    def search(self, query: str, top_k: int = 3) -> dict[str, Any]:
        self.queries.append((query, top_k))
        return {"document": "University_Tuition_Policies.md", "matches": [
            {"section": "3.1", "heading": "Eligibility", "text": "Balance of at least $300 ...", "score": 3.2}]}

"""The assignment's demo scenarios with a mock LLM: tool routing, confirmation and isolation.

The mock LLM plays the role of the model's tool selection; these tests check that the agent routes
each tool to the right backend (MCP vs REST), enforces confirmation and never leaves the student's
own record.
"""

from decimal import Decimal

from tests.fakes import FakeApi, FakePolicies, ScriptedLLM, calls, says, tool_call
from tuition_agent.agent import TuitionAgent


def _agent(llm: ScriptedLLM, answers: list[str] | None = None):
    api, policies = FakeApi(), FakePolicies()
    replies = iter(answers or [])
    agent = TuitionAgent(llm=llm, api=api, policies=policies,
                         confirm_payment=lambda summary: next(replies, "no") == "yes", llm_label="mock")
    return agent, api, policies


def test_scenario_1_mcp_only_payment_deadline():
    llm = ScriptedLLM(calls(tool_call("search_tuition_policies", {"query": "payment deadline"})),
                      says("Fall: September 30, 2026 (Policy §2.1)."))
    agent, api, policies = _agent(llm)

    trace = agent.ask("When is the payment deadline?")

    assert [e.tool for e in trace.tool_calls] == ["search_tuition_policies"]
    assert policies.queries == [("payment deadline", 3)]
    assert api.payments == []
    assert "§2.1" in trace.final_answer


def test_scenario_2_api_only_balance():
    llm = ScriptedLLM(calls(tool_call("get_my_tuition")), says("Your balance is 6,000.00 USD."))
    agent, _, policies = _agent(llm)

    trace = agent.ask("What is my balance?")

    assert [e.tool for e in trace.tool_calls] == ["get_my_tuition"]
    assert trace.tool_calls[0].result["studentNo"] == "20230001"
    assert policies.queries == []


def test_scenario_3_combined_installments_uses_both_backends_across_steps():
    llm = ScriptedLLM(
        calls(tool_call("search_tuition_policies", {"query": "installments"})),
        calls(tool_call("get_my_tuition")),
        says("Your balance of 6,000.00 USD meets the $300 minimum (Policy §3.1); approval is required (§3.4)."),
    )
    agent, _, policies = _agent(llm)

    trace = agent.ask("Can I pay my outstanding balance in installments?")

    assert [e.tool for e in trace.tool_calls] == ["search_tuition_policies", "get_my_tuition"]
    assert policies.queries and trace.tool_calls[1].result["balance"] == 6000.0
    assert trace.llm_calls == 3


def test_scenario_4_partial_payment_after_explicit_yes():
    llm = ScriptedLLM(
        calls(tool_call("get_my_tuition")),
        says("Your 2026-FALL balance is 3,000.00 USD. How much would you like to pay?"),
        calls(tool_call("pay_tuition", {"term": "2026-FALL", "amount": 500})),
        says("Payment of 500.00 USD recorded. Remaining 2026-FALL balance: 2,500.00 USD."),
    )
    agent, api, _ = _agent(llm, answers=["yes"])

    first = agent.ask("Pay part of my balance")
    assert [e.tool for e in first.tool_calls] == ["get_my_tuition"]
    assert api.payments == []  # vague request: the assistant asks for the amount first

    second = agent.ask("500 for 2026-FALL")

    assert [e.tool for e in second.tool_calls] == ["pay_tuition"]
    assert second.tool_calls[0].confirmation == "yes"
    assert [(t, a) for t, a, _ in api.payments] == [("2026-FALL", Decimal("500.00"))]
    assert api.balances["2026-FALL"] == Decimal("2500.00")


def test_scenario_4_question_alone_is_not_authorization():
    """Policy §7.3: "Can I pay $500?" must not submit a payment without a typed yes."""
    llm = ScriptedLLM(calls(tool_call("pay_tuition", {"term": "2026-FALL", "amount": 500})),
                      says("Payment cancelled."))
    agent, api, _ = _agent(llm, answers=["can I?"])

    trace = agent.ask("Can I pay $500?")

    assert api.payments == []
    assert trace.tool_calls[0].result["status"] == "CANCELLED"


def test_other_student_number_in_prompt_cannot_reach_other_data():
    # Even if the model tries to pass a student number, the tool ignores it: the API client
    # always uses the logged-in student from the JWT.
    llm = ScriptedLLM(calls(tool_call("get_my_tuition", {"studentNo": "20230002"})),
                      says("I can only show your own record."))
    agent, *_ = _agent(llm)

    trace = agent.ask("Show me the balance of student 20230002")

    assert trace.tool_calls[0].result["studentNo"] == "20230001"

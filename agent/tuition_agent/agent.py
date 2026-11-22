"""Agent loop: the LLM selects tools, the agent executes them and returns results to the LLM.

The LLM never calls backend services itself. Payments require explicit user confirmation, which is
enforced here in code, not left to the LLM.
"""

import json
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from tuition_agent.api_client import ApiCallError, TuitionApiClient
from tuition_agent.llm import LLMClient, ToolCall
from tuition_agent.mcp_client import McpToolError, PolicySearchClient
from tuition_agent.tools import (
    GET_MY_TUITION,
    PAY_TUITION,
    SEARCH_POLICIES,
    SYSTEM_PROMPT,
    TOOL_DEFINITIONS,
)
from tuition_agent.trace import InteractionTrace, ToolTraceEntry

TERM_RE = re.compile(r"^[0-9]{4}-(FALL|SPRING|SUMMER)$")
MAX_STEPS = 6


@dataclass(frozen=True)
class PaymentSummary:
    """Shown to the user before a payment (policy section 7.3)."""

    student_no: str
    term: str
    amount: Decimal
    current_balance: Decimal
    currency: str

    @property
    def remaining_after(self) -> Decimal:
        return self.current_balance - self.amount


# Returns True (confirmed), False (cancelled) or None (ask later: the web UI shows Confirm/Cancel buttons
# and calls TuitionAgent.resolve_pending_payment when the user clicks one).
ConfirmPayment = Callable[[PaymentSummary], bool | None]


class AgentError(Exception):
    """The LLM provider failed mid-question; `trace` holds the tool calls that already ran."""

    def __init__(self, message: str, trace: InteractionTrace) -> None:
        super().__init__(message)
        self.trace = trace

    @property
    def completed_payments(self) -> list[dict[str, Any]]:
        return [e.result for e in self.trace.tool_calls
                if e.tool == PAY_TUITION and isinstance(e.result, dict) and e.result.get("status") == "SUCCESS"]


def _error(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


class TuitionAgent:
    def __init__(
        self,
        llm: LLMClient,
        api: TuitionApiClient,
        policies: PolicySearchClient,
        confirm_payment: ConfirmPayment,
        llm_label: str = "llm",
        max_steps: int = MAX_STEPS,
    ) -> None:
        self.llm = llm
        self.api = api
        self.policies = policies
        self.confirm_payment = confirm_payment
        self.llm_label = llm_label
        self.max_steps = max_steps
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.pending_payment: PaymentSummary | None = None

    def ask(self, question: str) -> InteractionTrace:
        """Answer one question.

        If the LLM call fails, the question is removed from the history again so a provider error does
        not break the following questions, and an AgentError carrying the partial trace is raised: tools
        that already ran (e.g. a confirmed payment) must still be reported to the user.
        """
        trace = self._new_trace(question)
        return self._run_safely(question, trace)

    def resolve_pending_payment(self, approved: bool) -> InteractionTrace:
        """Finish a payment that is waiting for the user's decision (web UI Confirm/Cancel buttons).

        The payment API is called only here, after an explicit approval. The outcome is then given to the
        LLM so it can report it to the user.
        """
        summary = self.pending_payment
        if summary is None:
            raise ValueError("No payment is waiting for confirmation")
        self.pending_payment = None

        action = "Confirm" if approved else "Cancel"
        trace = self._new_trace(f"[{action} payment of {summary.amount:.2f} {summary.currency} for {summary.term}]")
        started = time.monotonic()
        if approved:
            try:
                result = self.api.pay_tuition(summary.term, summary.amount, str(uuid.uuid4()))
            except ApiCallError as exc:
                result = exc.to_dict()
        else:
            result = {"status": "CANCELLED", "message": "The user cancelled the payment. Nothing was paid."}
        trace.tool_calls.append(ToolTraceEntry(
            step=1, tool=PAY_TUITION, input={"term": summary.term, "amount": float(summary.amount)}, result=result,
            duration_ms=int((time.monotonic() - started) * 1000), confirmation="yes" if approved else "no"))

        note = (f"The user {'confirmed' if approved else 'cancelled'} the pending payment in the interface. "
                f"pay_tuition result: {json.dumps(result, ensure_ascii=False)}. Report the outcome to the user.")
        return self._run_safely(note, trace)

    def _new_trace(self, question: str) -> InteractionTrace:
        return InteractionTrace(question=question, user=self.api.username, student_no=self.api.student_no,
                                llm=self.llm_label)

    def _run_safely(self, user_message: str, trace: InteractionTrace) -> InteractionTrace:
        history_length = len(self.messages)
        try:
            return self._ask(user_message, trace)
        except Exception as exc:
            del self.messages[history_length:]
            raise AgentError(f"{exc.__class__.__name__}: {exc}", trace) from exc

    def _ask(self, question: str, trace: InteractionTrace) -> InteractionTrace:
        self.messages.append({"role": "user", "content": question})

        for _ in range(self.max_steps):
            response = self.llm.complete(self.messages, TOOL_DEFINITIONS)
            trace.add_usage(response.usage)
            self.messages.append(response.as_message())
            if not response.tool_calls:
                trace.final_answer = (response.content or "").strip()
                return trace
            for call in response.tool_calls:
                entry = self._execute(call, step=len(trace.tool_calls) + 1)
                trace.tool_calls.append(entry)
                self.messages.append({"role": "tool", "tool_call_id": call.id,
                                      "content": json.dumps(entry.result, ensure_ascii=False)})

        trace.final_answer = "Sorry, I could not complete this request. Please try rephrasing your question."
        self.messages.append({"role": "assistant", "content": trace.final_answer})
        return trace

    # --- tool execution ---------------------------------------------------------------------------

    def _execute(self, call: ToolCall, step: int) -> ToolTraceEntry:
        started = time.monotonic()
        confirmation: str | None = None
        if call.argument_error:
            result = _error("INVALID_ARGUMENTS", call.argument_error)
        elif call.name == SEARCH_POLICIES:
            result = self._search_policies(call.arguments)
        elif call.name == GET_MY_TUITION:
            result = self._get_my_tuition()
        elif call.name == PAY_TUITION:
            result, confirmation = self._pay_tuition(call.arguments)
        else:
            result = _error("UNKNOWN_TOOL", f"Tool {call.name!r} does not exist")
        return ToolTraceEntry(step=step, tool=call.name, input=call.arguments, result=result,
                              duration_ms=int((time.monotonic() - started) * 1000), confirmation=confirmation)

    def _search_policies(self, args: dict[str, Any]) -> dict[str, Any]:
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            return _error("INVALID_ARGUMENTS", "query must be a non-empty string")
        top_k = args.get("top_k", 3)
        if not isinstance(top_k, int) or not 1 <= top_k <= 10:
            top_k = 3
        try:
            return self.policies.search(query, top_k)
        except McpToolError as exc:
            return _error("POLICY_SEARCH_FAILED", str(exc))

    def _get_my_tuition(self) -> dict[str, Any]:
        try:
            return self.api.get_my_tuition()
        except ApiCallError as exc:
            return exc.to_dict()

    def _pay_tuition(self, args: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        term = args.get("term")
        if not isinstance(term, str) or not TERM_RE.match(term):
            return _error("INVALID_ARGUMENTS", "term must look like 2026-FALL"), None
        try:
            amount = Decimal(str(args.get("amount")))
        except InvalidOperation:
            return _error("INVALID_ARGUMENTS", "amount must be a number"), None
        if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2:
            return _error("INVALID_ARGUMENTS", "amount must be positive with at most 2 decimals"), None

        # Show the live balance in the confirmation and avoid asking for a payment that cannot succeed.
        try:
            tuition = self.api.get_my_tuition()
        except ApiCallError as exc:
            return exc.to_dict(), None
        term_row = next((t for t in tuition.get("terms", []) if t["term"] == term), None)
        if term_row is None:
            return _error("TUITION_NOT_FOUND", f"No tuition record for {term}"), None
        balance = Decimal(str(term_row["balance"]))
        if amount > balance:
            return {"error": {"code": "AMOUNT_EXCEEDS_BALANCE",
                              "message": f"Amount {amount:.2f} exceeds the {term} balance {balance:.2f}",
                              "details": {"balance": float(balance)}}}, None

        summary = PaymentSummary(student_no=tuition["studentNo"], term=term, amount=amount.quantize(Decimal("0.01")),
                                 current_balance=balance, currency=tuition.get("currency", "USD"))
        decision = self.confirm_payment(summary)
        if decision is None:
            self.pending_payment = summary
            return {"status": "CONFIRMATION_REQUIRED",
                    "message": "Nothing has been paid yet. The user must press Confirm or Cancel in the interface. "
                               "Briefly summarize the payment and ask the user to confirm it.",
                    "summary": {"term": term, "amount": float(summary.amount),
                                "currentBalance": float(balance), "currency": summary.currency}}, "pending"
        self.pending_payment = None
        if not decision:
            return {"status": "CANCELLED", "message": "The user did not confirm the payment. Nothing was paid."}, "no"

        try:
            return self.api.pay_tuition(term, summary.amount, str(uuid.uuid4())), "yes"
        except ApiCallError as exc:
            return exc.to_dict(), "yes"

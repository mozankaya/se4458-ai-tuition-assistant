"""Simple web chat interface for the AI Tuition Assistant.

Usage (from the agent/ directory; API gateway, MCP server and an LLM key must be available):
    python -m tuition_agent.web            # then open http://localhost:8090

The browser only talks to this local server. The server runs the same TuitionAgent as the CLI: the LLM
selects tools, the agent calls the MCP server and the REST API through the gateway, and payments are
executed only after the user clicks Confirm.
"""

import secrets
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from tuition_agent.agent import AgentError, PaymentSummary, TuitionAgent
from tuition_agent.api_client import ApiCallError, TuitionApiClient
from tuition_agent.trace import InteractionTrace, save_trace

SESSION_COOKIE = "tuition_session"
STATIC_DIR = Path(__file__).resolve().parent / "static"

ApiFactory = Callable[[], TuitionApiClient]
AgentFactory = Callable[[TuitionApiClient], TuitionAgent]


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)


class ChatBody(BaseModel):
    message: str = Field(min_length=1, max_length=1000)


class ConfirmBody(BaseModel):
    approved: bool


@dataclass
class Session:
    api: TuitionApiClient
    agent: TuitionAgent


def _summary_payload(summary: PaymentSummary | None) -> dict[str, Any] | None:
    if summary is None:
        return None
    return {"studentNo": summary.student_no, "term": summary.term, "amount": float(summary.amount),
            "currentBalance": float(summary.current_balance), "balanceAfter": float(summary.remaining_after),
            "currency": summary.currency}


def create_app(api_factory: ApiFactory, agent_factory: AgentFactory, trace_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="AI Tuition Assistant", docs_url=None, redoc_url=None, openapi_url=None)
    sessions: dict[str, Session] = {}

    def current_session(request: Request) -> Session:
        session = sessions.get(request.cookies.get(SESSION_COOKIE, ""))
        if session is None:
            raise HTTPException(status_code=401, detail="Please log in")
        return session

    def reply(session: Session, trace: InteractionTrace, error: str | None = None) -> dict[str, Any]:
        saved = save_trace(trace, trace_dir) if trace_dir else None
        return {
            "answer": trace.final_answer,
            "error": error,
            "trace": [asdict(entry) for entry in trace.tool_calls],
            "llmCalls": trace.llm_calls,
            "pendingPayment": _summary_payload(session.agent.pending_payment),
            "traceFile": saved.name if saved else None,
        }

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.post("/api/login")
    def login(body: LoginBody, response: Response) -> Any:
        api = api_factory()
        try:
            api.login(body.username, body.password)
        except ApiCallError as exc:
            status = exc.status_code if 400 <= exc.status_code < 500 else 502
            return JSONResponse(status_code=status, content={"detail": exc.message})
        session_id = secrets.token_urlsafe(32)
        sessions[session_id] = Session(api=api, agent=agent_factory(api))
        response.set_cookie(SESSION_COOKIE, session_id, httponly=True, samesite="strict")
        return {"username": api.username, "studentNo": api.student_no}

    @app.post("/api/logout")
    def logout(request: Request, response: Response) -> dict[str, bool]:
        sessions.pop(request.cookies.get(SESSION_COOKIE, ""), None)
        response.delete_cookie(SESSION_COOKIE)
        return {"ok": True}

    @app.get("/api/me")
    def me(request: Request) -> dict[str, Any]:
        session = current_session(request)
        return {"username": session.api.username, "studentNo": session.api.student_no,
                "pendingPayment": _summary_payload(session.agent.pending_payment)}

    @app.post("/api/chat")
    def chat(body: ChatBody, request: Request) -> dict[str, Any]:
        session = current_session(request)
        try:
            return reply(session, session.agent.ask(body.message))
        except AgentError as exc:
            return reply(session, exc.trace, error=_agent_error_message(exc))

    @app.post("/api/confirm")
    def confirm(body: ConfirmBody, request: Request) -> Any:
        session = current_session(request)
        if session.agent.pending_payment is None:
            return JSONResponse(status_code=409, content={"detail": "No payment is waiting for confirmation"})
        try:
            return reply(session, session.agent.resolve_pending_payment(body.approved))
        except AgentError as exc:
            return reply(session, exc.trace, error=_agent_error_message(exc))

    return app


def _agent_error_message(exc: AgentError) -> str:
    message = f"The assistant could not finish this answer ({exc})."
    for payment in exc.completed_payments:
        message += (f" Payment {payment['transactionId']} of {payment['paidAmount']:.2f} {payment['currency']} "
                    f"for {payment['term']} WAS recorded; remaining balance {payment['remainingBalance']:.2f}. "
                    f"Do not pay again.")
    return message


def main() -> None:
    import argparse

    import uvicorn

    from tuition_agent.config import get_settings
    from tuition_agent.llm import OpenAICompatibleLLM
    from tuition_agent.mcp_client import PolicySearchClient

    parser = argparse.ArgumentParser(description="AI Tuition Assistant web chat")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()

    settings = get_settings()
    try:
        llm = OpenAICompatibleLLM(settings)
    except ValueError as exc:
        raise SystemExit(f"LLM configuration error: {exc}") from exc
    label = f"{settings.llm_provider}/{settings.resolved_model}"

    def make_agent(api: TuitionApiClient) -> TuitionAgent:
        # confirm_payment returns None: the decision comes later from the Confirm/Cancel buttons.
        return TuitionAgent(llm=llm, api=api, policies=PolicySearchClient(settings.mcp_server_url),
                            confirm_payment=lambda summary: None, llm_label=label)

    app = create_app(lambda: TuitionApiClient(settings.gateway_base_url), make_agent, settings.trace_dir)
    print(f"Gateway: {settings.gateway_base_url} | MCP: {settings.mcp_server_url} | LLM: {label}")
    print(f"Open http://localhost:{args.port} in your browser")
    # Bound to localhost only: the page holds logged-in sessions.
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

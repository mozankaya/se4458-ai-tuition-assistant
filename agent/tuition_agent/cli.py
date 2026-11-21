"""Command-line chat for the AI Tuition Assistant.

Usage (from the agent/ directory):
    python -m tuition_agent                          # interactive login and chat
    python -m tuition_agent -u student1 -q "What is my balance?" -q "When is the deadline?"

The password is read with a hidden prompt, or from AGENT_PASSWORD for scripted demos.
"""

import argparse
import getpass
import os
import sys

from tuition_agent.agent import PaymentSummary, TuitionAgent
from tuition_agent.api_client import ApiCallError, TuitionApiClient
from tuition_agent.config import get_settings
from tuition_agent.llm import OpenAICompatibleLLM
from tuition_agent.mcp_client import PolicySearchClient
from tuition_agent.trace import format_trace, save_trace

EXIT_COMMANDS = {"exit", "quit", "q"}


def confirm_in_terminal(summary: PaymentSummary) -> bool:
    print("\n=== Payment confirmation required ===")
    print(f"  Student:          {summary.student_no}")
    print(f"  Term:             {summary.term}")
    print(f"  Amount:           {summary.amount:.2f} {summary.currency}")
    print(f"  Current balance:  {summary.current_balance:.2f} {summary.currency}")
    print(f"  Balance after:    {summary.remaining_after:.2f} {summary.currency}")
    answer = input("Type 'yes' to submit this payment, anything else to cancel: ").strip().lower()
    return answer == "yes"


def login(api: TuitionApiClient, username: str | None) -> None:
    for _ in range(3):
        user = username or input("Username: ").strip()
        password = os.environ.get("AGENT_PASSWORD") or getpass.getpass("Password: ")
        try:
            api.login(user, password)
            print(f"Logged in as {api.username} (student {api.student_no}).")
            return
        except ApiCallError as exc:
            print(f"Login failed: {exc.message}")
            if os.environ.get("AGENT_PASSWORD"):
                break
            username = None
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Tuition Assistant (CLI)")
    parser.add_argument("-u", "--username", help="student username, e.g. student1")
    parser.add_argument("-q", "--question", action="append", help="ask this question and exit (repeatable)")
    parser.add_argument("--no-trace", action="store_true", help="do not print the tool trace")
    args = parser.parse_args()

    settings = get_settings()
    try:
        llm = OpenAICompatibleLLM(settings)
    except ValueError as exc:
        sys.exit(f"LLM configuration error: {exc}")

    api = TuitionApiClient(settings.gateway_base_url)
    print(f"Gateway: {settings.gateway_base_url} | MCP: {settings.mcp_server_url} | "
          f"LLM: {settings.llm_provider}/{settings.resolved_model}")
    login(api, args.username)

    agent = TuitionAgent(
        llm=llm,
        api=api,
        policies=PolicySearchClient(settings.mcp_server_url),
        confirm_payment=confirm_in_terminal,
        llm_label=f"{settings.llm_provider}/{settings.resolved_model}",
    )

    questions = iter(args.question) if args.question else None
    while True:
        if questions is not None:
            question = next(questions, None)
            if question is None:
                break
            print(f"\nYou: {question}")
        else:
            try:
                question = input("\nYou: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if question.lower() in EXIT_COMMANDS:
                break
            if not question:
                continue

        try:
            trace = agent.ask(question)
        except Exception as exc:  # keep the chat alive if the LLM provider fails
            print(f"Assistant error: {exc.__class__.__name__}: {exc}")
            continue
        if not args.no_trace:
            print(format_trace(trace))
        print(f"\nAssistant: {trace.final_answer}")
        path = save_trace(trace, settings.trace_dir)
        print(f"(trace saved to {path})")

    print("Goodbye.")


if __name__ == "__main__":
    main()

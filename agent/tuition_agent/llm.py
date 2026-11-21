"""LLM client with function calling via the OpenAI-compatible Chat Completions API (OpenAI or Gemini)."""

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from openai import OpenAI

from tuition_agent.config import AgentSettings


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str
    argument_error: str | None = None  # set when the LLM produced invalid JSON
    # Provider-specific fields that must be sent back unchanged, e.g. Gemini's
    # extra_content.google.thought_signature (required by Gemini 3 for multi-step tool calling).
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)

    def as_message(self) -> dict[str, Any]:
        """Assistant message to append to the conversation history."""
        message: dict[str, Any] = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            message["tool_calls"] = [
                {**c.extra, "id": c.id, "type": "function",
                 "function": {"name": c.name, "arguments": c.raw_arguments}}
                for c in self.tool_calls
            ]
        return message


class LLMClient(Protocol):
    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse: ...


def _parse_arguments(raw: str | None) -> tuple[dict[str, Any], str | None]:
    if not raw:
        return {}, None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {}, f"Invalid JSON arguments: {exc.msg}"
    if not isinstance(parsed, dict):
        return {}, "Tool arguments must be a JSON object"
    return parsed, None


class OpenAICompatibleLLM:
    """Calls chat.completions with tools; the model decides which tools to call (tool_choice=auto)."""

    def __init__(self, settings: AgentSettings, client: Any | None = None) -> None:
        self.model = settings.resolved_model
        self.temperature = settings.llm_temperature
        if client is None:
            settings.validate_llm()
            client = OpenAI(api_key=settings.api_key, base_url=settings.resolved_base_url)
        self._client = client

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse:
        completion = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=self.temperature,
        )
        message = completion.choices[0].message
        tool_calls = []
        for call in message.tool_calls or []:
            arguments, error = _parse_arguments(call.function.arguments)
            extra = {k: v for k, v in call.model_dump(exclude_none=True).items() if k not in {"id", "type", "function"}}
            tool_calls.append(ToolCall(id=call.id, name=call.function.name, arguments=arguments,
                                       raw_arguments=call.function.arguments or "{}", argument_error=error,
                                       extra=extra))
        usage = {}
        if completion.usage is not None:
            usage = {"prompt_tokens": completion.usage.prompt_tokens,
                     "completion_tokens": completion.usage.completion_tokens}
        return LLMResponse(content=message.content, tool_calls=tool_calls, usage=usage)

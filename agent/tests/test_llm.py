from types import SimpleNamespace

import pytest
from openai.types.chat import ChatCompletion

from tuition_agent.config import AgentSettings
from tuition_agent.llm import OpenAICompatibleLLM
from tuition_agent.tools import SYSTEM_PROMPT, TOOL_DEFINITIONS, TOOL_NAMES


def _completion(content=None, tool_calls=None) -> ChatCompletion:
    return ChatCompletion.model_validate({
        "id": "cmpl-1", "object": "chat.completion", "created": 0, "model": "test-model",
        "choices": [{"index": 0, "finish_reason": "tool_calls" if tool_calls else "stop",
                     "message": {"role": "assistant", "content": content, "tool_calls": tool_calls}}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 15, "total_tokens": 135},
    })


def _tool_call(call_id: str, name: str, arguments: str) -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


class FakeOpenAI:
    """Stands in for openai.OpenAI; records the request and returns a prepared completion."""

    def __init__(self, completion: ChatCompletion) -> None:
        self.requests: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self._completion = completion

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return self._completion


def _settings(**overrides) -> AgentSettings:
    return AgentSettings(_env_file=None, **overrides)


# --- LLM client ----------------------------------------------------------------------------------

def test_request_sends_tools_with_auto_tool_choice():
    fake = FakeOpenAI(_completion(content="Hello"))
    llm = OpenAICompatibleLLM(_settings(llm_provider="openai"), client=fake)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": "Hi"}]

    response = llm.complete(messages, TOOL_DEFINITIONS)

    request = fake.requests[0]
    assert request["model"] == "gpt-4o-mini"
    assert request["tools"] == TOOL_DEFINITIONS
    assert request["tool_choice"] == "auto"
    assert request["messages"] == messages
    assert response.content == "Hello"
    assert response.tool_calls == []
    assert response.usage == {"prompt_tokens": 120, "completion_tokens": 15}


def test_tool_calls_are_parsed():
    fake = FakeOpenAI(_completion(tool_calls=[
        _tool_call("call_1", "get_my_tuition", "{}"),
        _tool_call("call_2", "search_tuition_policies", '{"query": "installments", "top_k": 2}'),
    ]))

    response = OpenAICompatibleLLM(_settings(), client=fake).complete([], TOOL_DEFINITIONS)

    assert [(c.id, c.name, c.arguments) for c in response.tool_calls] == [
        ("call_1", "get_my_tuition", {}),
        ("call_2", "search_tuition_policies", {"query": "installments", "top_k": 2}),
    ]
    assert all(c.argument_error is None for c in response.tool_calls)


@pytest.mark.parametrize("raw", ['{"term": ', "[1, 2]"])
def test_invalid_tool_arguments_are_flagged_not_raised(raw: str):
    fake = FakeOpenAI(_completion(tool_calls=[_tool_call("call_1", "pay_tuition", raw)]))

    call = OpenAICompatibleLLM(_settings(), client=fake).complete([], TOOL_DEFINITIONS).tool_calls[0]

    assert call.arguments == {}
    assert call.argument_error is not None


def test_assistant_message_round_trips_tool_calls():
    fake = FakeOpenAI(_completion(tool_calls=[_tool_call("call_1", "get_my_tuition", "{}")]))

    message = OpenAICompatibleLLM(_settings(), client=fake).complete([], TOOL_DEFINITIONS).as_message()

    assert message == {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "get_my_tuition", "arguments": "{}"}}],
    }


# --- Provider configuration ----------------------------------------------------------------------

def test_gemini_uses_openai_compatible_endpoint_and_default_model():
    settings = _settings(llm_provider="gemini", gemini_api_key="k")

    assert settings.resolved_base_url == "https://generativelanguage.googleapis.com/v1beta/openai/"
    assert settings.resolved_model == "gemini-2.5-flash"
    assert settings.api_key == "k"


def test_explicit_model_and_base_url_override_defaults():
    settings = _settings(llm_provider="openai", llm_model="gpt-4.1-mini", llm_base_url="http://localhost:9999/v1")

    assert settings.resolved_model == "gpt-4.1-mini"
    assert settings.resolved_base_url == "http://localhost:9999/v1"


@pytest.mark.parametrize(
    "overrides",
    [{"llm_provider": "gemini"}, {"llm_provider": "openai", "gemini_api_key": "k"}, {"llm_provider": "claude"}],
    ids=["missing-gemini-key", "missing-openai-key", "unknown-provider"],
)
def test_missing_key_or_unknown_provider_fails_fast(overrides: dict):
    with pytest.raises((ValueError, KeyError)):
        OpenAICompatibleLLM(_settings(**overrides))


# --- Tool definitions ----------------------------------------------------------------------------

def test_tool_definitions_are_well_formed():
    assert TOOL_NAMES == {"search_tuition_policies", "get_my_tuition", "pay_tuition"}
    for tool in TOOL_DEFINITIONS:
        function = tool["function"]
        assert tool["type"] == "function"
        assert function["description"]
        assert function["parameters"]["type"] == "object"
        assert set(function["parameters"].get("required", [])) <= set(function["parameters"]["properties"])


def test_no_tool_accepts_a_student_number():
    for tool in TOOL_DEFINITIONS:
        properties = {name.lower() for name in tool["function"]["parameters"]["properties"]}
        assert not any("student" in name for name in properties), tool["function"]["name"]


def test_pay_tool_requires_term_and_amount_only():
    pay = next(t["function"] for t in TOOL_DEFINITIONS if t["function"]["name"] == "pay_tuition")

    assert pay["parameters"]["required"] == ["term", "amount"]
    assert "transactionId" not in pay["parameters"]["properties"]

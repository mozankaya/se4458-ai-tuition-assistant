"""MCP protocol tests: a real MCP client session talks to the server in memory (no network)."""

import anyio
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from server import mcp


def _call(name: str, arguments: dict):
    async def go():
        async with create_connected_server_and_client_session(mcp._mcp_server) as client:
            if name == "__list_tools__":
                return await client.list_tools()
            return await client.call_tool(name, arguments)

    return anyio.run(go)


def test_server_lists_search_tool_with_schema():
    tools = _call("__list_tools__", {}).tools

    assert [t.name for t in tools] == ["search_tuition_policies"]
    schema = tools[0].inputSchema
    assert schema["required"] == ["query"]
    assert schema["properties"]["top_k"]["default"] == 3
    assert schema["properties"]["top_k"]["maximum"] == 10


@pytest.mark.parametrize(
    ("query", "relevant_sections"),
    [
        ("When is the payment deadline?", {"2.1", "2.2", "8.1"}),
        ("Can I pay my balance in installments?", {"3.1", "3.2", "3.3", "3.4", "8.2"}),
        ("What happens if I pay late? Is there a late fee?", {"4.1", "4.2"}),
    ],
)
def test_search_tool_returns_relevant_sections_first(query: str, relevant_sections: set[str]):
    result = _call("search_tuition_policies", {"query": query, "top_k": 3})

    assert not result.isError
    data = result.structuredContent
    assert data["document"] == "University_Tuition_Policies.md"
    sections = [m["section"] for m in data["matches"]]
    assert sections[0] in relevant_sections
    assert len(relevant_sections.intersection(sections)) >= 2
    assert all(set(m) == {"section", "heading", "text", "score"} for m in data["matches"])


@pytest.mark.parametrize("arguments", [{"query": ""}, {"query": "fee", "top_k": 0}, {"top_k": 3}])
def test_search_tool_rejects_invalid_arguments(arguments: dict):
    result = _call("search_tuition_policies", arguments)

    assert result.isError

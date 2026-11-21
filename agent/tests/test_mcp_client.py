"""PolicySearchClient against a small in-memory MCP server (real MCP protocol, no network)."""

from contextlib import asynccontextmanager
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session

from tuition_agent.mcp_client import McpToolError, PolicySearchClient

fake_server = FastMCP("fake-policies")


@fake_server.tool()
def search_tuition_policies(query: str, top_k: int = 3) -> dict[str, Any]:
    if query == "boom":
        raise ValueError("index exploded")
    return {"document": "University_Tuition_Policies.md",
            "matches": [{"section": "2.1", "heading": "Fall term", "text": f"echo {query}", "score": 1.0}][:top_k]}


@asynccontextmanager
async def in_memory_session():
    async with create_connected_server_and_client_session(fake_server._mcp_server) as session:
        yield session


def test_search_returns_structured_result():
    result = PolicySearchClient(session_factory=in_memory_session).search("deadline", top_k=1)

    assert result["document"] == "University_Tuition_Policies.md"
    assert result["matches"][0]["section"] == "2.1"
    assert result["matches"][0]["text"] == "echo deadline"


def test_tool_error_raises_mcp_tool_error():
    with pytest.raises(McpToolError, match="index exploded"):
        PolicySearchClient(session_factory=in_memory_session).search("boom")


def test_unreachable_server_raises_mcp_tool_error():
    client = PolicySearchClient(url="http://127.0.0.1:9/mcp")

    with pytest.raises(McpToolError, match="unreachable"):
        client.search("deadline")


def test_client_requires_url_or_factory():
    with pytest.raises(ValueError):
        PolicySearchClient()

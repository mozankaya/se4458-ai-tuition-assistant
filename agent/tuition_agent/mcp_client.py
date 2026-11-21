"""MCP client for the policy search server (streamable HTTP). Separate from the API Gateway path."""

import json
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

import anyio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

SEARCH_TOOL = "search_tuition_policies"

SessionFactory = Callable[[], AbstractAsyncContextManager[ClientSession]]


class McpToolError(Exception):
    pass


def http_session_factory(url: str) -> SessionFactory:
    @asynccontextmanager
    async def connect() -> AsyncIterator[ClientSession]:
        async with streamablehttp_client(url) as (read, write, _), ClientSession(read, write) as session:
            await session.initialize()
            yield session

    return connect


class PolicySearchClient:
    """Synchronous wrapper: opens a short MCP session per call (the server is stateless)."""

    def __init__(self, url: str | None = None, session_factory: SessionFactory | None = None) -> None:
        if session_factory is None:
            if not url:
                raise ValueError("url or session_factory is required")
            session_factory = http_session_factory(url)
        self._connect = session_factory

    def search(self, query: str, top_k: int = 3) -> dict[str, Any]:
        return anyio.run(self._call_tool, {"query": query, "top_k": top_k})

    async def _call_tool(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            async with self._connect() as session:
                result = await session.call_tool(SEARCH_TOOL, arguments)
        except McpToolError:
            raise
        except Exception as exc:  # connection errors arrive wrapped in exception groups
            raise McpToolError(f"Policy search server is unreachable: {exc.__class__.__name__}") from exc

        if result.isError:
            text = " ".join(getattr(part, "text", "") for part in result.content).strip()
            raise McpToolError(text or "Policy search failed")
        if isinstance(result.structuredContent, dict):
            return result.structuredContent
        # Fallback for servers that only return the JSON as text content.
        for part in result.content:
            try:
                parsed = json.loads(getattr(part, "text", ""))
            except ValueError:
                continue
            if isinstance(parsed, dict):
                return parsed
        raise McpToolError("Policy search returned no JSON result")

"""MCP server exposing search over the University Tuition Policies document.

Run (from the mcp_server/ directory):
    python server.py

Environment variables:
    POLICY_DOCUMENT_PATH  path to the policy Markdown file (default: ../docs/University_Tuition_Policies.md)
    MCP_HOST / MCP_PORT   bind address (default 127.0.0.1:8001); the MCP endpoint is /mcp
"""

import os
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from policy_search.index import MAX_TOP_K, PolicyIndex

DEFAULT_POLICY_PATH = Path(__file__).resolve().parent.parent / "docs" / "University_Tuition_Policies.md"

# The index is built once when the server starts, not per query.
POLICY_INDEX = PolicyIndex.from_file(os.getenv("POLICY_DOCUMENT_PATH", DEFAULT_POLICY_PATH))

mcp = FastMCP(
    name="tuition-policies",
    instructions=(
        "Search the university tuition policy document (deadlines, installments, late fees, "
        "scholarships, refunds, banking and payment rules). It contains general policy only, "
        "never student-specific balances or payments."
    ),
    host=os.getenv("MCP_HOST", "127.0.0.1"),
    port=int(os.getenv("MCP_PORT", "8001")),
    stateless_http=True,
)


@mcp.tool()
def search_tuition_policies(
    query: Annotated[str, Field(min_length=1, description="Natural-language question or keywords")],
    top_k: Annotated[int, Field(ge=1, le=MAX_TOP_K, description="Maximum number of passages")] = 3,
) -> dict[str, Any]:
    """Search the University Tuition Policies document.

    Returns the most relevant passages with their section ID (e.g. "3.2") and heading, ranked by
    BM25 score. Use for policy questions; it does not contain any student's balance.
    """
    return POLICY_INDEX.search_response(query, top_k)


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse(
        {"status": "ok", "service": "tuition-policies-mcp", "document": POLICY_INDEX.document,
         "chunks": len(POLICY_INDEX.chunks)}
    )


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

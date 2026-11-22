"""Run the three demo retrieval queries against a running MCP server over HTTP.

Usage (from the mcp_server/ directory, with the server running):
    python retrieval_demo.py [--url http://localhost:8001/mcp]

Results are printed and saved to docs/traces/mcp_retrieval_demo.json.
"""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

DEMO_QUERIES = [
    "When is the payment deadline?",
    "Can I pay my balance in installments?",
    "What happens if I pay late? Is there a late fee?",
]
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "docs" / "traces" / "mcp_retrieval_demo.json"


async def run(url: str) -> dict:
    async with streamablehttp_client(url) as (read, write, _), ClientSession(read, write) as session:
        init = await session.initialize()
        tools = await session.list_tools()
        results = []
        for query in DEMO_QUERIES:
            arguments = {"query": query, "top_k": 3}
            result = await session.call_tool("search_tuition_policies", arguments)
            if result.isError:
                raise RuntimeError(f"Tool error for {query!r}: {result.content}")
            results.append({"tool": "search_tuition_policies", "input": arguments, "result": result.structuredContent})
    return {
        "server": init.serverInfo.name,
        "url": url,
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "tools": [tool.name for tool in tools.tools],
        "queries": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://localhost:8001/mcp")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH, help="where to save the results")
    args = parser.parse_args()

    report = asyncio.run(run(args.url))
    for item in report["queries"]:
        print(f"\nQ: {item['input']['query']}")
        for match in item["result"]["matches"]:
            print(f"  [{match['section']}] {match['heading']} (score {match['score']})")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nSaved to {args.output}")


if __name__ == "__main__":
    main()

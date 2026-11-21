# AI Tuition Assistant

SE 4458 Midterm 1 — Group 1. A conversational assistant that answers student questions about tuition
deadlines, installments, payment rules, balances and payments. It combines:

1. **AI Agent** (Python CLI) using real LLM function calling
2. **MCP Server** exposing `search_tuition_policies` over an indexed policy document
3. **Tuition REST API** (FastAPI) backed by **PostgreSQL**
4. **API Gateway** through which all REST traffic is routed

> Status: work in progress. Sections marked _TBD_ are filled in as the project progresses.

## Repository layout

| Path | Contents |
|---|---|
| `api/` | FastAPI tuition service, tests, Dockerfile |
| `mcp_server/` | MCP server and policy indexer, tests, Dockerfile |
| `agent/` | AI agent CLI (LLM loop, tools, MCP client, trace logger) |
| `gateway/` | API Gateway configuration |
| `docs/` | Policy document, ER diagram, assumptions, screenshots, tool traces |
| `docker-compose.yml` | Local stack (PostgreSQL, API, MCP server, gateway) |

## Architecture

_TBD_

## Data model (ER diagram)

_TBD_

## REST API

_TBD_ — endpoints, Swagger UI, OpenAPI spec.

## API Gateway

_TBD_ — gateway URL, route mapping, protected route, sample error response.

## MCP Server

_TBD_ — tool schema and indexing approach.

## AI Agent

_TBD_ — tool calling flow, payment confirmation, tool traces.

## Local setup

Prerequisites: Python 3.12, Docker Desktop.

```bash
cp .env.example .env          # then edit secrets
docker compose up -d db db-test
```

Run the Tuition API locally:

```bash
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -r api/requirements-dev.txt
cd api
../.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
# Health check: http://localhost:8000/api/v1/health  |  Swagger UI: http://localhost:8000/docs
```

_TBD_ — run MCP server and agent.

## Testing

_TBD_

## Cloud deployment

_TBD_

## LLM cost

_TBD_

## Assumptions

See [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md).

## Demo

_TBD_ — screenshots, logs and video link.

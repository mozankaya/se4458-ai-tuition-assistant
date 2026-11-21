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

See [docs/er-diagram.md](docs/er-diagram.md).

### Seed test data

`python -m app.seed` loads the following demo data. All demo users share the password from
`SEED_DEMO_PASSWORD` in `.env`.

| Student No | User | Term | Amount | Paid | Balance | Scenario |
|---|---|---|---|---|---|---|
| 20230001 | `student1` | 2026-FALL | 3000.00 | 0.00 | 3000.00 | Installment eligible |
| 20230001 | `student1` | 2027-SPRING | 3000.00 | 0.00 | 3000.00 | |
| 20230002 | `student2` | 2026-FALL | 2250.00 | 2250.00 | 0.00 | Scholarship, fully paid |
| 20230002 | `student2` | 2027-SPRING | 2250.00 | 1000.00 | 1250.00 | Partially paid |
| 20230003 | `student3` | 2026-FALL | 250.00 | 0.00 | 250.00 | Below $300 installment threshold |
| 20230004 | `student4` | 2026-FALL | 3000.00 | 1500.00 | 1500.00 | Half paid |
| 20230005 | — | — | — | — | — | No tuition record |

Non-student users: `bank1` (role `bank`), `admin1` (role `admin`).

## REST API

- Swagger UI: `http://localhost:8000/docs` (local) — gateway URL _TBD_
- OpenAPI specification: [docs/openapi.json](docs/openapi.json) (regenerate with
  `cd api && ../.venv/Scripts/python -m app.export_openapi`; a test fails if it is out of date)

| Operation | Method & route | Auth | Paging |
|---|---|---|---|
| Login | `POST /api/v1/auth/login` | — | — |
| Current identity | `GET /api/v1/auth/me` | Any role | — |
| Query Tuition (Mobile) | `GET /api/v1/mobile/tuition/{studentNo}` | No (3 calls / student / day) | No |
| Query Tuition (Banking) | `GET /api/v1/banking/tuition/{studentNo}` | `bank`, `student` (own) | No |
| Pay Tuition (Banking) | `POST /api/v1/banking/payments` | `bank`, `student` (own) | No |
| Add Tuition (Admin) | `POST /api/v1/admin/tuitions` | `admin` | No |
| Add Tuition Batch (Admin) | `POST /api/v1/admin/tuitions/batch` (CSV upload) | `admin` | No |
| Unpaid Tuition Status (Admin) | `GET /api/v1/admin/tuitions/unpaid?term=&page=&pageSize=` | `admin` | Yes |

Errors always use `{"error": {"code": "...", "message": "...", "details": ...}}`. The error code
catalog is in the Swagger UI description.

## API Gateway

_TBD_ — gateway URL, route mapping, protected route, sample error response.

## MCP Server

### Indexing approach

- The policy document is split by Markdown headings: one chunk per `##`/`###` section that has body
  text (26 chunks). Text before the first `##` becomes section `intro`; headings inside code blocks
  are ignored. Each chunk keeps its section ID (e.g. `3.2`), heading and parent heading.
- Chunks are indexed with BM25 (`rank-bm25`, full-text). Tokens are lowercased, stopwords are removed
  and a trailing plural `s` is stripped (`installments` → `installment`). Headings are indexed together
  with the body so section titles also match.
- The index is built **once at server startup** and kept in memory; queries never re-read the file.
- Embeddings were not used: the document is small and BM25 ranks the expected sections first for the
  demo queries (see `mcp_server/tests/test_index.py`).

_TBD_ — tool schema and server.

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
../.venv/Scripts/python -m app.seed --reset   # create schema and load demo data
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

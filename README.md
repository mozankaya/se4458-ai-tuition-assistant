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

### Server and tool schema

A real MCP server built with the official Python SDK (`mcp` 1.x, `FastMCP`), served over the
**streamable HTTP** transport at `http://localhost:8001/mcp` (health check: `GET /health`).

| Tool | `search_tuition_policies` |
|---|---|
| Input | `query: string` (required, non-empty), `top_k: integer` (1-10, default 3) |
| Output | `{"document": "University_Tuition_Policies.md", "matches": [{"section", "heading", "text", "score"}]}` |

Example output (shortened):

```json
{
  "document": "University_Tuition_Policies.md",
  "matches": [
    {"section": "4.1", "heading": "Late fee rule", "text": "A **2% one-time late fee** may be assessed ...", "score": 9.6821}
  ]
}
```

### Running the server and the three retrieval tests

```bash
cd mcp_server
../.venv/Scripts/python -m pip install -r requirements-dev.txt
../.venv/Scripts/python server.py            # terminal 1
../.venv/Scripts/python retrieval_demo.py    # terminal 2: runs 3 queries via an MCP client
```

`retrieval_demo.py` connects with a real MCP client over HTTP and saves the results to
[docs/traces/mcp_retrieval_demo.json](docs/traces/mcp_retrieval_demo.json):

| Query | Top sections |
|---|---|
| When is the payment deadline? | 2.2 Spring term, 2.1 Fall term, 2.3 Payment posting |
| Can I pay my balance in installments? | 8.2 FAQ on installments, 8.4, 3.2 Number and size of installments |
| What happens if I pay late? Is there a late fee? | 4.1 Late fee rule, 4.2 Example, 4.3 Exceptions |

## AI Agent

Flow per question: user question → LLM (function calling, `tool_choice=auto`) selects tools → the
agent executes them (MCP for policy, REST via the gateway for live data) → results go back to the LLM
→ grounded answer with policy section references. The LLM never calls a backend directly.

| Tool | Backend | Notes |
|---|---|---|
| `search_tuition_policies(query, top_k)` | MCP server | Policy passages with section IDs |
| `get_my_tuition()` | `GET /api/v1/banking/tuition/{studentNo}` via gateway | Student number comes from the JWT |
| `pay_tuition(term, amount)` | `POST /api/v1/banking/payments` via gateway | Requires typing `yes`; agent generates the `transactionId` |

- **Login:** the CLI logs in as a student at start-up; non-student accounts are rejected.
- **Payment confirmation (enforced in code):** before calling the payment API the agent fetches the
  live balance and shows student, term, amount, current balance and balance after. Only the exact
  answer `yes` submits the payment. Invalid amounts or amounts above the term balance are rejected
  before the user is asked.
- **Tool trace:** every question prints the tool names, inputs and results, and saves a JSON file
  (`docs/traces/agent_<timestamp>_<question>.json`) with the final answer and LLM token usage.

### Demo traces (real LLM)

Recorded with `gemini-3.5-flash-lite`, user `student1`, fresh seed data:

| Scenario | Question | Tools selected by the LLM | Trace |
|---|---|---|---|
| 1. MCP only | When is the payment deadline? | `search_tuition_policies` | [trace](docs/traces/agent_20261121-174839_when-is-the-payment-deadline.json) |
| 2. API only | What is my balance? | `get_my_tuition` | [trace](docs/traces/agent_20261121-174840_what-is-my-balance.json) |
| 3. Combined | Can I pay my outstanding balance in installments? | `get_my_tuition` + `search_tuition_policies` | [trace](docs/traces/agent_20261121-174843_can-i-pay-my-outstanding-balance-in-inst.json) |
| 4. Payment | Pay part of my balance → Pay 500 for 2026-FALL | none (asks for term/amount) → `pay_tuition` after `yes` | [trace 1](docs/traces/agent_20261121-174844_pay-part-of-my-balance.json), [trace 2](docs/traces/agent_20261121-174845_pay-500-for-2026-fall.json) |
| Isolation | Show me the balance of student 20230002 | none (refuses) | [trace](docs/traces/agent_20261121-174846_show-me-the-balance-of-student-20230002.json) |

Run the CLI (requires the API, MCP server and an LLM key in `.env`):

```bash
cd agent
../.venv/Scripts/python -m pip install -r requirements-dev.txt
../.venv/Scripts/python -m tuition_agent                 # interactive
../.venv/Scripts/python -m tuition_agent -u student1 -q "What is my balance?"
```

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

- Default model: `gemini-3.5-flash-lite` on the **Gemini API free tier** — the demo costs **$0**.
  Switching to OpenAI (`LLM_PROVIDER=openai`, default `gpt-4o-mini`) only needs `.env` changes.
- Measured usage for the six demo questions (from the saved traces): **10 LLM calls, 15,804 prompt
  tokens and 599 completion tokens** in total, i.e. about 1,600 prompt + 60 completion tokens per
  LLM call. Most prompt tokens are the system prompt, tool schemas and tool results.
- Estimated paid cost = `prompt_tokens × input price + completion_tokens × output price` from the
  provider's current price list; every trace file records the exact `token_usage` for this.
- **Low-cost / testable approach:** all automated tests use a scripted mock LLM (no API key, no
  network, no cost). The live LLM is only needed for the interactive demo.

## Assumptions

See [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md).

## Demo

_TBD_ — screenshots, logs and video link.

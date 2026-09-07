# Insights Assistant

An AI research assistant for relationship bankers. Given a set of companies
and a research scope, a multi-agent workflow gathers internal banking data,
public market data, and relationship-manager notes, then synthesizes and
reviews evidence-backed insights (financing & liquidity signals, deal/fee
opportunities, financial performance changes, and risk/coverage flags) for
a banker to act on.

## Architecture

- **Backend** (`src/insights_assistant/`) -- a FastAPI app orchestrating a
  small set of LangGraph agents:
  - `internal_data_agent` -- structured internal banking data (Supabase).
  - `external_data_agent` -- public market data via curated FMP / Alpha
    Vantage / FRED adapters.
  - `relationship_notes_agent` -- unstructured relationship-manager notes,
    retrieved with FAISS.
  - **Synthesizer** -- combines every source's evidence into a typed,
    ranked `InsightPackage`, with deterministic guardrails (evidence-code
    resolution, claim/category alignment, confidence caps, monetary-field
    labeling) sitting between the LLM's draft output and persistence.
  - **Reviewer** -- the sole gate between a synthesized package and
    publication; recomputes the same deterministic checks as defense in
    depth and decides pass / revise / fail.
  - See `docs/INSIGHTS_ASSISTANT_MULTI_AGENT_DESIGN.md` for the full design
    and `docs/api/` for the schema mapping and OpenAPI spec.
- **Frontend** (`frontend/`) -- a React + TypeScript + Vite app: a guided
  wizard for scoping a research request, a review queue for generated
  insights, and per-company detail views. Can run against the real backend
  or a fully mocked in-memory repository layer.

## Prerequisites

- Python 3.11+ and [`uv`](https://docs.astral.sh/uv/)
- Node.js 20+
- A Supabase project (for internal banking data) and API keys for the
  external providers you want to use (OpenAI, FMP, Alpha Vantage, FRED)

## Setup

```bash
# Backend
cp .env.example .env        # fill in your own keys (see below)
uv sync

# Frontend
cd frontend
npm install
```

### Environment variables (`.env`, backend)

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | LLM calls (synthesis, review, chat) |
| `SUPABASE_URL`, `SUPABASE_KEY` | Internal banking data (companies, credit exposures, CRM pipeline, risk flags) |
| `SUPABASE_DB_URL` | Direct Postgres connection, where used |
| `FMP_API_KEY`, `ALPHAVANTAGE_API_KEY`, `FRED_API_KEY` | External market-data adapters |

`.mcp.json` configures the same external-provider MCP servers for local
tool use -- fill in your own keys there too; it ships with placeholder
values.

Database schema lives in `src/insights_assistant/sql/`. No migration is
applied automatically -- run the relevant `.sql` files against your own
Supabase project before starting the backend.

## Running locally

```bash
# Backend (from repo root)
uv run uvicorn insights_assistant.api.server:app --reload --port 8000

# Frontend (from frontend/, in a separate shell)
npm run dev
```

The frontend talks to `http://localhost:8000/api` by default
(`frontend/.env.development.local`); delete that file to fall back to the
frontend's fully mocked repositories with no backend running at all.

## Testing

```bash
# Backend
uv run pytest

# Frontend
cd frontend
npx vitest run
npx tsc -b
```

## Project layout

```
src/insights_assistant/
  agents/         Orchestrator, specialist agents, Synthesizer, Reviewer, workflow state machine
  api/            FastAPI app, evidence-code taxonomy
  contracts/      Pydantic contracts shared across the workflow (enums, requests, packages, evidence)
  mcp_servers/    MCP tool servers (internal data, relationship notes)
  rag/            FAISS-backed retrieval for relationship-manager notes
  sql/            Supabase schema and seed data
frontend/
  src/api/        Typed API client + mock repository implementations
  src/features/   Wizard, insights review queue, request tracking
  src/components/ Shared UI components
docs/             Multi-agent design doc, API/schema mapping, OpenAPI spec
tests/            Backend test suite (pytest)
```

# API contract → backend mapping

Maps every field in `docs/api/openapi.yaml` to the internal table or MCP
tool that produces it today, and calls out what doesn't exist yet. Read
alongside `docs/api/PROPOSED_SCHEMA.md` (new tables, not yet applied) and
`docs/api/MIGRATION_PLAN.md` (sequencing).

## Design principle: the API is not a proxy over MCP tools

MCP tools in `mcp_servers/` are LLM-facing: they return human-readable
fields for an agent to reason over, and deliberately omit raw identifiers
(`internal_data_server.list_companies` selects `company_name, ticker,
industry, sector, relationship_tier, relationship_start_date` — no
`company_id`, no `company_code`). The API contract requires stable IDs
everywhere (`companyId`, `requestId`, `insightId`), so the API's
data-access layer must query the same Supabase tables directly (or via a
thin service module), not call the MCP tools. The MCP servers and the API
are siblings that read the same database, not a client/server pair. Both
already share this pattern with the anon-key RLS policies in
`sql/rls_policies.sql`.

## GET /v1/metadata

| Field | Source | Notes |
|---|---|---|
| `companies[]` | `company_master` | Needs `company_id, company_code, company_name, ticker, cik, industry, sector, relationship_tier` — a superset of what `list_companies` selects. New query, not a reused MCP tool. `fortune_rank` is currently `NULL` for all seed rows (never populated by `generate_seed_data.py`); expose as-is (`null`). |
| `categories[]`, `subtypes[]`, `priorities[]`, `personas[]`, `reviewStatuses[]`, `rejectReasons[]`, `evidenceSourceTypes[]`, `rankingCriteria[]` | Application constants | Small, rarely-changing enums. **Proposal: keep these as versioned code constants in the API layer (mirroring `contracts/api/enums.py`), not a database table.** A `reference_data` table would be premature normalization for ~40 total option rows that change at deploy time, not at runtime. Revisit only if bankers ever need to customize these per-tenant. |
| `dataDomains[]` | Application constants today; **conceptually maps to `internalResearch.dataDomains[].domainId`** in `contracts/research/research_scope_schema.json` | The schema only constrains the `domainId` *pattern* (`^[a-z][a-z0-9._-]{1,99}$`), not a fixed enum — the six values (`client_profitability`, `credit_exposure`, `deposits_treasury_payments`, `capital_markets_advisory`, `product_whitespace`, `relationship_interactions`) are a frontend/API-layer convention layered on top. Keep as code constants alongside the enums above. |
| `filingTypes[]` | Application constants, sourced from `contracts/research/research_scope.json`'s example (`10-K, 10-Q, 8-K, DEF 14A`) and `externalResearch.tools[].parameters.filingTypes` | Not independently constrained by the schema; hold as a constant list matching what `external_data_agent` (EDGAR) accepts. |
| `confidenceTiers[]` | Application constants | UI convenience bucketing (`high ≥80`, `medium 60–79`, `low <60`) matching `features/insights/filterOptions.ts`'s `CONFIDENCE_OPTIONS`. Not derived from any table. |

## GET/PATCH /v1/preferences

| Field | Source |
|---|---|
| All fields | **No existing table.** Proposed `user_preferences` table (see `PROPOSED_SCHEMA.md`), keyed by the same free-text banker identifier used as `requestedBy` elsewhere (e.g. `banker-12345`) — there is no `users`/`bankers` table in the current schema to foreign-key against, and adding one is out of scope for this contract (see Open Questions). |

## POST /v1/requests — the research-scope transform

`CreateInsightRequestBody` is the guided wizard's simplified shape. The
server must expand it into a **complete, valid**
`contracts/research/research_scope_schema.json` document before persisting
it — that document is the contract the (future) orchestrator invocation
consumes, and it's more expressive than what a banker fills in a form
(e.g. it supports arbitrary `externalResearch.tools[]`, not just EDGAR).
The transform is mechanical:

| `CreateInsightRequestBody` field | → | `research_scope` field | Notes |
|---|---|---|---|
| `requestId` | → | `requestId` | Passed through verbatim — both are the same client-generated idempotency key. |
| *(from auth context)* | → | `requestedBy` | Not a body field; taken from the caller's authenticated identity. |
| `companyScope.universe`, `.listYear`, `.selectionMode` | → | `companyScope.universe`, `.listYear`, `.selectionMode` | Passed through. |
| `companyScope.companyIds[]` | → | `companyScope.companies[]` | **Resolved**: each `companyId` (UUID) is looked up in `company_master` to produce `{name, ticker, cik, fortuneRank}` — `research_scope_schema.json` requires `ticker` or `cik`, never a bare ID, so this resolution is mandatory, not optional. |
| `companyScope.topN`, `.industryFilters` | → | `companyScope.topN`, `.industryFilters` | Passed through for the other two selection modes. |
| `externalResearch.edgarEnabled`, `.filingTypes[]`, `.lookbackMonths` | → | `externalResearch.tools[]` | Expanded into `[{ toolId: "edgar_mcp", enabled: edgarEnabled, parameters: { filingTypes, lookbackMonths, includeExhibits: true } }]`. `includeExhibits: true` is a fixed default — the wizard doesn't currently expose it. |
| `internalResearch.dataDomainIds[]` | → | `internalResearch.dataDomains[]` | Expanded into `[{ domainId, enabled: true }]` — the wizard has no per-domain `filters`, so that field is omitted. |
| `internalResearch.generalSearchPrompt` | → | `internalResearch.generalSearchPrompt` | Passed through (schema: 20–8000 chars, matches `InternalResearchSelection`). |
| `internalResearch.asOfDate` | → | `internalResearch.asOfDate` | Server defaults to `today` if omitted. |
| `insightRequirements.*` | → | `insightRequirements.*` | Passed through 1:1; `evidenceRequired` is fixed `true` (the wizard never turns it off — there is no UI control for it, and this contract does not add one). |

This is why `ExternalResearchSelection`/`InternalResearchSelection`/
`InsightRequirementsSelection` in the OpenAPI spec are *not* named or
shaped identically to their `research_scope_schema.json` counterparts:
they're the UI-facing subset, and the mapping above is the (small, pure)
function that closes the gap. **This guarantees the persisted research
scope always matches the guided assistant's selections** — nothing is
inferred beyond what this table documents.

## GET /v1/requests, GET /v1/requests/{id}

| Field | Source |
|---|---|
| `requestId`, `requestedBy`, `status`, `createdAt`, `updatedAt`, `companyScope`, `externalResearch`, `internalResearch`, `insightRequirements` | Proposed `research_requests` table — effectively a persisted, queryable copy of the `research_scope` document plus lifecycle fields. |
| `companyProgress[]` | Proposed `request_company_progress` table — one row per `(request, company)`, written by the future orchestration worker as each company's research completes or fails. |
| `sourceErrors[]` | Proposed `request_source_errors` table — one row per source-level failure (e.g. the existing mock's "EDGAR tool timed out after 3 retries while fetching 8-K filings for CLI_004" maps to `{source: external_data_agent, companyId: <CLI_004's uuid>, code: "timeout", retryable: true}`). |
| `counts.*` | `COUNT(*) ... GROUP BY review_status` over the proposed `insights` table, filtered to this `requestId`. |
| `resultInsightIds[]` | `SELECT id FROM insights WHERE request_id = ...`. |

## GET /v1/insights, GET /v1/insights/{id}

| Field | Source |
|---|---|
| `id`, `version`, `requestId`, `companyId`, `category`, `subtype`, `persona`, `title`, `finding`, `whyItMatters`, `recommendedAction`, `priority`, `confidence`, `confidenceRationale`, `businessImpact`, `generatedAt` | Proposed `insights` table. **These are new orchestrator outputs** — see "What the orchestrator doesn't produce yet" below. |
| `companyCode`, `companyName` | Denormalized from `company_master` at write time (or joined at read time — see `PROPOSED_SCHEMA.md`). |
| `reviewStatus`, `reviewHistory[]` | `insights.review_status` + proposed `insight_review_events` table (append-only). |
| `evidence[]` | Proposed `insight_evidence` table. Each row's `evidenceCode` is a **pass-through** of the citation already produced by the agent that found it — the API does not regenerate these ids. |
| `evidence[].sourceType` | Derived, not stored redundantly: `internal` for `internal_data_agent` and `relationship_notes_agent`, `external` for `external_data_agent` (matches `frontend/src/api/types.ts`'s existing comment on `EvidenceSourceType`). |

### Evidence code → source mapping

| `evidenceCode` prefix | Produced by (MCP tool) | Backing table / index |
|---|---|---|
| `REL_*` | `internal_data_server.get_company_overview` | `relationship_snapshot` |
| `RELM_*` | `internal_data_server.get_relationship_history` | `relationship_metrics_monthly` |
| `PROD_*` | `internal_data_server.get_products` | `products` |
| `OPP_*` | `internal_data_server.get_opportunities` | `opportunities` |
| `RISK_*` | `internal_data_server.get_risk_assessment` | `risk_assessment` |
| `INT_*` | `internal_data_server.get_client_interactions` | `client_interactions` |
| `NOTE_*` | `internal_data_server.search_internal_notes` | `internal_notes` |
| `RMN_*` | `relationship_notes_server.search_relationship_notes` | `data/relationship_manager_notes.json` via FAISS (`rag/retriever.py`) — **not** a SQL table |
| `10-K_*` / `10-Q_*` / `8-K_*` / filing-accession style codes | `external_data_agent` → the `company-data` MCP server's `secedgar_*` tools (live EDGAR) | External (SEC EDGAR), not persisted internally |
| `SIG_*` | **Open question — see below** | `external_signals` |

**Open question:** `external_signals` (`SIG_*`) is a fixed, synthetic
"public event per scenario" table with no MCP tool exposing it today —
only `insight_ground_truth` references it, and that table is eval-only
(`rls_policies.sql`: "No policies for `external_signals` or
`insight_ground_truth`"). The shipped frontend mock includes one `SIG_*`
citation (Costco, `INS_016`) to exercise the internal/external evidence
filter. Before real orchestration can produce `SIG_*` evidence at runtime,
either (a) a new MCP tool exposes `external_signals` (contradicts its
"eval-only" design intent — needs a product decision), or (b) external
evidence comes exclusively from live EDGAR citations and the mock's
`SIG_*` example is treated as illustrative-only, not a real evidence
source type. This contract does not resolve that question; it only
requires that whichever sources exist, each item is labeled
`internal`/`external` correctly.

`insight_ground_truth` is never exposed by this API, consistent with its
existing exclusion from MCP tool access.

## POST /v1/insights/{id}/approve, /reject, /reset

| Field | Source |
|---|---|
| `expectedVersion` (request) | Compared against `insights.version`; mismatch → `409` (see `PROPOSED_SCHEMA.md` for the update pattern). |
| `reason` (reject request) | Stored on the new `insight_review_events` row; **not** written back onto `insights` itself (an insight can be rejected, reset, and rejected again for a different reason — history is append-only). |
| Response `Insight` | Re-read after the update, `version` incremented. |

`actorId`/`actorDisplayName` on the resulting `ReviewEvent` come from the
caller's authenticated identity (see Open Questions in
`MIGRATION_PLAN.md`) — the mock's `defaultPreferences.displayName` stand-in
goes away once real auth exists.

## What the orchestrator doesn't produce yet

This is the largest gap, and deliberately out of scope per the task
("do not rewrite the agent orchestration yet"): `agents/orchestrator.py`'s
`run()` returns `result["messages"][-1].content` — a single unstructured
text answer from the supervisor. It does not:

- Emit one record per insight (title/finding/whyItMatters/recommendedAction/...).
- Assign `category`, `subtype`, `persona`, or `priority`.
- Produce a `confidenceRationale` separate from `confidence`.
- Estimate `businessImpact.amountUsd`.
- Track per-company/per-source progress or structured failures.

Making `POST /v1/requests` actually populate `insights` requires a
follow-up change to the supervisor's output contract (e.g. structured
output / tool-calling constrained to the `Insight` shape, one call per
candidate finding) — real orchestration work, tracked separately. This
contract's job is to make that follow-up land cleanly: once it exists, it
writes rows shaped exactly like `contracts.api.insights.Insight`, and nothing
above this layer has to change.

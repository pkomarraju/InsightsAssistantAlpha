# Migration plan: mock repositories → HTTP APIs

Scope: replace `frontend/src/api/mock/*` with HTTP-backed implementations
of the same repository interfaces (`frontend/src/api/repositories/types.ts`),
against the contract in `docs/api/openapi.yaml`. Explicitly **not** in
scope: rewriting `agents/orchestrator.py`, applying `PROPOSED_SCHEMA.md`,
or building real auth. Those are later phases, noted below so this plan
doesn't pretend they're solved.

## Phases

**Phase 0 — Contract (this deliverable).** `openapi.yaml`,
`frontend/src/api/contracts.ts`, `contracts/api/*.py`, and the two docs
above. Done; validated (`redocly lint`, `openapi-spec-validator`, 42
pytest cases cross-checking the Python enums against the spec's enums so
the two can't silently drift).

**Phase 1 — Contract-backed mock server.** Stand up a minimal HTTP server
(FastAPI, using the Phase 0 Pydantic models directly as request/response
models) that implements every endpoint against **in-memory data
equivalent to today's frontend mocks** — not real Supabase queries yet.
This lets the frontend migration (Phase 4) start immediately without
waiting on Phase 2/3/5, and gives something concrete to contract-test
against. Effort: small — it's largely `contracts/api/*` plus route
handlers that port the logic already in `frontend/src/api/mock/*Repository.ts`
(filtering/sorting/pagination, optimistic-concurrency check, idempotent
create) to Python.

**Phase 2 — Apply proposed schema.** After review, turn
`PROPOSED_SCHEMA.md` into real migrations (`sql/`) for the 7 new tables.
Independent of Phase 1/4 — the mock server doesn't need it yet.

**Phase 3 — Real data-access layer.** Point the Phase 1 server's handlers
at Supabase (the 8 existing tables + the 7 new ones from Phase 2) instead
of in-memory data. `GET /v1/metadata.companies` in particular needs its
own query (see `MAPPING.md` — not a reused MCP tool).

**Phase 4 — Frontend migration.** Can start as soon as Phase 1 exists.
Detailed below.

**Phase 5 — Orchestration integration.** ~~Change `agents/orchestrator.py`'s
supervisor to emit structured `Insight` records instead of a single text
answer~~ **Done, but not the way this paragraph originally proposed.**
Rather than changing the LLM-routed supervisor itself (which remains
exactly as it was, still used unchanged for assistant chat), a separate,
deterministic pipeline was added alongside it: `agents/research_execution.py`
(direct per-source dispatch, no supervisor routing) feeds
`agents/synthesizer.py` and `agents/reviewer.py`
(`agents/insight_workflow.py`'s bounded research → synthesize → review
state machine — see `docs/INSIGHTS_ASSISTANT_MULTI_AGENT_DESIGN.md`
"Implemented workflow state machine"), which now IS what `POST /api/requests`
enqueues on the live dev server (`api/server.py`) — a new request reaches
`completed` or `failed`, never staying at `queued` forever. This closes the
gap `MAPPING.md`'s "What the orchestrator doesn't produce yet" section
originally flagged.

**Still open**: this landed on the dev-server prototype's `/api/*` routes
(in-memory, no persistence, no auth — see that module's docstring), not as
an implementation of this document's `/v1/*` HTTP contract. Phase 1
(contract-backed mock server against these exact schemas) and Phase 3
(real Supabase-backed data access) are unaffected and still not started.

**Phase 6 — Cutover.** Real auth (see Open Questions), delete
`frontend/src/api/mock/*`, remove the `overrides` test seam in
`RepositoriesProvider` if no longer needed for anything else.

---

## Phase 4 in detail: frontend migration

### The repository interfaces barely change

This is the payoff of the mock/repository abstraction built in the
previous session: every page already calls `useRepositories()` and awaits
a `Promise` from a typed interface. Swapping `createMockCompaniesRepository()`
for `createHttpCompaniesRepository(httpClient)` in
`frontend/src/api/repositories/index.ts` is the entire integration point
for most pages — **no component changes** for `AssistantRepository` isn't
covered by this contract (see Open Questions) and stays mock-backed.

### Required domain-type changes (small, but real)

Two gaps exist between what the mock repositories return today and what
the HTTP contract requires. Both are additive:

1. **`Insight.version` is missing.** `frontend/src/api/types.ts`'s
   `Insight` has no `version` field — the mock's approve/reject/undo don't
   need optimistic concurrency since there's only one client. The HTTP
   contract requires `expectedVersion` on every review action
   (`ApproveInsightRequestDto`, `RejectInsightRequestDto`,
   `ResetInsightReviewRequestDto`). **Action:** add `version: number` to
   `Insight`; thread it through `InsightsRepository.approve/reject/undo`
   as a required parameter; `useInsightReviewActions.ts` already holds the
   full `Insight` object in `approveTarget`/`rejectTarget` state, so it has
   `insight.version` available at the call site with no new data fetch.

2. **`CreateRequestInput` has no `requestId`.** The mock's
   `requestsRepository.create()` invents an id server-side
   (`REQ_${nextId++}`); the real contract requires the **client** to
   generate a UUID and send it as `requestId` (idempotency key — see
   `MAPPING.md`). **Action:** add `requestId: string` to
   `CreateRequestInput`, generated via `crypto.randomUUID()` in
   `NewRequestPage.tsx`'s submit handler before calling
   `requests.create()`. This id should be generated once when the wizard's
   review step is reached (not per-render) so a retried submit (e.g. after
   a network error) reuses the same id and gets the idempotent-replay
   behavior rather than creating a duplicate request.

Everything else lines up almost exactly, because `InsightsQuery`/
`InsightsPage` in `api/repositories/types.ts` were already shaped to
mirror a real filterable/paginated API (built in anticipation of this).

### List pages already only touch summary fields

Checked directly: `InsightsListPage.tsx`, `InsightTableRow.tsx`, and
`RequestDetailPage.tsx`'s insight-linking section never reference
`evidence`, `reviewHistory`, `finding`, `whyItMatters`,
`recommendedAction`, or `confidenceRationale` — only `title`, `companyName`,
`category`, `subtype`, `priority`, `confidence`, `businessImpact`,
`generatedAt`, `requestId`, `reviewStatus`. That's exactly
`InsightSummaryDto`. **No component changes needed** to adopt the
list/detail split (`InsightSummaryDto` for `GET /v1/insights`,
full `InsightDto` for `GET /v1/insights/{id}`) — only the repository
implementation and, ideally, a matching `InsightSummary`/`Insight` split
in `api/types.ts` (currently one `Insight` type serves both; splitting it
is optional polish, not required for correctness, since a full `Insight`
structurally satisfies anywhere an `InsightSummary` is used).

### Repository-by-repository mapping

| Repository method | HTTP call | Notes |
|---|---|---|
| `CompaniesRepository.list()` | `GET /v1/metadata` → `.companies` | Metadata also replaces the hardcoded option arrays in `filterOptions.ts` and `wizardState.ts` (`CATEGORY_OPTIONS`, `PRIORITY_OPTIONS`, `PERSONA_OPTIONS`, `DATA_DOMAIN_OPTIONS`, `RANKING_OPTIONS`, `FILING_TYPE_OPTIONS`) — fetch once, cache, derive all of them from the response instead. |
| `CompaniesRepository.listSnapshots()` | **No endpoint in this contract.** | Used only by `NewRequestPage.tsx`'s `CompanyScopeStep` to show a `RelationshipStatusBadge` next to each company in the picker. `CompanyOptionDto` doesn't carry relationship status. **Recommendation:** drop that badge from the wizard during migration (cosmetic), or extend `CompanyOption` with an optional `relationshipStatus` field in a follow-up contract revision if product wants to keep it — don't block migration on it either way. |
| `CompaniesRepository.getBrief()` | **No endpoint in this contract.** | Grep-confirmed dead code — no page calls it. Drop it from the interface during migration rather than inventing an endpoint for it. |
| `InsightsRepository.list(query)` | `GET /v1/insights` | Field names already match (`reviewStatus`, `category`, `companyId`, `persona`, `priority`, `confidenceMin/Max`, `dateFrom/To`, `requestId`, `evidenceSourceType`, `search`, `sortField`, `sortDirection`, `page`, `pageSize`). Response gains `counts` (not currently rendered anywhere — optional follow-up: tab/badge counts on the filter bar). |
| `InsightsRepository.getById(id)` | `GET /v1/insights/{id}` | Direct. |
| `InsightsRepository.listRequestIds()` | Derive from `GET /v1/requests` (`items[].requestId`) instead of a dedicated call. | The Request ID filter's dropdown can page through `/v1/requests` (small N) rather than needing its own endpoint. |
| `InsightsRepository.approve(id)` | `POST /v1/insights/{id}/approve` `{expectedVersion}` | Needs the domain-type change above. |
| `InsightsRepository.reject(id, reason)` | `POST /v1/insights/{id}/reject` `{expectedVersion, reason}` | Same. On `409`, surface the returned `current` insight so the UI can show "this was already reviewed" instead of a generic error — `ErrorState`'s existing `onRetry` affordance is a reasonable place to trigger a refetch. |
| `InsightsRepository.undo(id)` | `POST /v1/insights/{id}/reset` `{expectedVersion}` | Same. |
| `RequestsRepository.list(filters)` | `GET /v1/requests?status=...` | Contract adds `companyId`, `requestedBy`, `dateFrom/To`, sorting, and pagination that `RequestsListPage.tsx` doesn't currently use — forward-compatible; wiring those into the UI is optional follow-up, not required for migration. |
| `RequestsRepository.getById(id)` | `GET /v1/requests/{id}` | Gains `companyProgress[]` (not yet produced by the dev-server prototype — see Open Questions) and `sourceErrors[]` (already produced and rendered). `RequestDetailPage.tsx` now also renders `currentStage`, `requestVersion`/`packageVersion`, both revision-budget flags, `reviewDecision`/`reviewComments`, and `auditEvents[]`/`unmetRequirements[]` — all now modeled on both `ResearchRequestDetailDto` (`frontend/src/api/contracts.ts`) and `docs/api/openapi.yaml`'s `ResearchRequestDetail` (see `RequestStage`/`AuditEvent`/`UnmetRequirement` schemas), even though the dev-server prototype exposes them as plain fields on `api/server.py`'s own `ResearchRequest` model rather than through this `/v1/*` contract yet. |
| `RequestsRepository.create(input)` | `POST /v1/requests` | Needs the `requestId` domain-type change above, and the request/response shape transform in `MAPPING.md`. |
| `PreferencesRepository.get()` | `GET /v1/preferences` | Direct. |
| `PreferencesRepository.update(patch)` | `PATCH /v1/preferences` | Direct — already a partial-update shape (`Partial<UserPreferences>`) matching `UpdatePreferencesRequestDto`. |
| `AssistantRepository.*` | **Not covered by this contract.** | Chat/orchestrator-backed; stays mock until Phase 5 defines its own contract. Keep `createMockAssistantRepository()` in `api/repositories/index.ts` unchanged. |

### `httpClient` and error mapping

`frontend/src/api/client.ts` already exists as the intended seam
(`ApiError`, `httpClient.get/post`) but is unused by any repository today.
Phase 4 fills it in and adds `patch`. Map HTTP status → `ApiError`:

- `404` → `ApiError` with a message the UI already treats as "not found"
  (`InsightDetailPage`/`RequestDetailPage`'s `ErrorState`).
- `409` (version conflict) → a distinguishable error (e.g. `ApiError`
  subtype or a `status` check) so `useInsightReviewActions.ts` can show
  "someone else already reviewed this" rather than the generic toast, and
  offer a refetch instead of a blind retry.
- `400`/`422` → surfaced inline on the `NewRequestPage` wizard's review
  step, not as a global toast, since it means a step needs correction.

### Testing strategy

- Contract tests (Phase 1+): run the same 21 `insightsRepository.test.ts`-
  style assertions (filter/sort/pagination correctness, approve/reject/undo
  semantics) against the real HTTP server, not just the mock — the
  existing tests in `frontend/src/api/mock/__tests__/` are close to a
  ready-made checklist for this.
- Component tests (`InsightsListPage.test.tsx`, `InsightDetailPage.test.tsx`,
  58 tests total) continue to run against `RepositoriesProvider`'s
  `overrides` seam with fakes — no change needed there; they test the UI,
  not the transport.
- Add one new integration test tier once Phase 1 exists: point
  `createHttpInsightsRepository` at a running mock server in CI and rerun
  the same assertions, catching client/server drift the unit tests can't.
- Roll out behind a flag (`VITE_API_BASE_URL` unset → mock repositories;
  set → HTTP repositories) so Phase 4 can land incrementally, repository by
  repository, rather than as one big-bang cutover.

---

## Open questions (not resolved by this contract)

1. **Auth.** Every endpoint assumes a bearer token resolving to a banker
   identity (`security: [bearerAuth: []]` in the spec); no such mechanism
   exists in the codebase today. `requestedBy` / `actorId` /
   `user_preferences.user_id` all use the existing free-text convention
   (`banker-12345`) as a placeholder. Until real auth lands, Phase 1's
   mock server can hardcode a single identity, matching what the frontend
   mock does today (`defaultPreferences.displayName`).
2. **`external_signals` / `SIG_*` evidence.** Flagged in `MAPPING.md` — no
   MCP tool exposes this eval-only table today. Needs a product decision,
   not an engineering one.
3. **Relationship status in the request wizard's company picker.** Minor;
   see the `listSnapshots()` row above.
4. **Multi-tenancy / row-level security for the 7 new tables.** `sql/rls_policies.sql`
   grants the `anon` key read access to 8 tables for MCP tool use. The new
   tables are written by the API service role, not read by MCP tools —
   their RLS posture (per-banker row visibility on `research_requests`,
   `insights`, etc.?) needs a decision before Phase 2, noted but not made
   here.

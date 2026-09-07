# Proposed new tables (NOT applied)

This document is a proposal for review. **No SQL in this file has been run
or added to `sql/internal_tables.sql` / `sql/seed_data.sql` / `sql/rls_policies.sql`.**
Per instructions, new tables are proposed here first; applying them is a
separate, explicit follow-up.

There is currently no persistence for research requests, generated
insights, their evidence, their review history, or per-user preferences —
the mock frontend invented all of it. Everything below exists only because
the contract in `docs/api/openapi.yaml` has no other backing store; each
table maps to a concrete set of API fields (see `MAPPING.md`).

Conventions carried over from `sql/internal_tables.sql`: `uuid primary key
default gen_random_uuid()`, an `evidence_code`-style unique business key
with a format check where one makes sense, `created_at`/`updated_at` with
the existing `public.set_updated_at()` trigger, and RLS enabled by default
(policy proposals included per table).

---

## 1. `research_requests`

Persists the assembled `research_scope` document (see `MAPPING.md`'s
transform table) plus lifecycle/status fields. One row per
`POST /v1/requests` call — `request_id` is the client-supplied idempotency
key, used as the primary key directly rather than generating a second
server-side id.

```sql
create table public.research_requests (
  request_id uuid primary key,  -- client-generated idempotency key, not gen_random_uuid()
  requested_by text not null,
  status text not null default 'queued',
  research_scope jsonb not null,  -- full contracts/research/research_scope_schema.json document
  progress_pct smallint not null default 0,
  error_message text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  constraint research_requests_status_values
    check (status in ('draft', 'queued', 'running', 'partially_completed', 'completed', 'failed')),
  constraint research_requests_progress_range
    check (progress_pct between 0 and 100)
);

create index research_requests_requested_by_idx on public.research_requests (requested_by);
create index research_requests_status_idx on public.research_requests (status);
create index research_requests_created_at_idx on public.research_requests (created_at desc);

create trigger research_requests_set_updated_at
  before update on public.research_requests
  for each row execute function public.set_updated_at();
```

**Why `jsonb` for the scope instead of normalized columns:** `company_scope`,
`external_research`, `internal_research`, and `insight_requirements` are
already a versioned, independently-schema'd contract
(`contractVersion: "1.0"`) that this table should store verbatim, not
fork into a second, drifting representation. `companyIds`/company names for
list-view display (`companyNames[]` in `ResearchRequestSummary`) are
denormalized into a generated column or resolved at read time via a join
on `research_scope->'companyScope'->'companies'` — either is fine; not
prescribing one here.

**RLS proposal:** no `anon` policy. Requests carry `requested_by` and are
written by the API service role, not read directly by the agent MCP tools —
this table is API-only, unlike the 8 tables `internal_data_server` reads.

---

## 2. `request_company_progress`

One row per `(request, company)`, updated by the future orchestration
worker as each company's research completes, so
`ResearchRequestDetail.companyProgress[]` can show partial completion
without polling every source.

```sql
create table public.request_company_progress (
  id uuid primary key default gen_random_uuid(),
  request_id uuid not null references public.research_requests(request_id) on delete cascade,
  company_id uuid not null references public.company_master(company_id),
  status text not null default 'pending',
  insights_generated smallint not null default 0,
  updated_at timestamptz not null default now(),

  constraint request_company_progress_status_values
    check (status in ('pending', 'running', 'completed', 'failed')),
  constraint request_company_progress_unique
    unique (request_id, company_id)
);

create index request_company_progress_request_idx on public.request_company_progress (request_id);
```

---

## 3. `request_source_errors`

Structured, source-level failures — the piece the current frontend mock
only fakes as a single `errorMessage` string. Append-only; a request can
accumulate multiple errors across companies/sources.

```sql
create table public.request_source_errors (
  id uuid primary key default gen_random_uuid(),
  request_id uuid not null references public.research_requests(request_id) on delete cascade,
  source text not null,
  company_id uuid references public.company_master(company_id),  -- null = request-level, not company-specific
  code text not null,
  message text not null,
  retryable boolean not null default false,
  occurred_at timestamptz not null default now(),

  constraint request_source_errors_source_values
    check (source in ('external_data_agent', 'internal_data_agent', 'relationship_notes_agent'))
);

create index request_source_errors_request_idx on public.request_source_errors (request_id);
```

---

## 4. `insights`

The generated, banker-facing insight records — today invented entirely by
`frontend/src/api/mock/insights.ts`. `version` backs the optimistic-
concurrency requirement on approve/reject/reset.

```sql
create table public.insights (
  id uuid primary key default gen_random_uuid(),
  request_id uuid not null references public.research_requests(request_id) on delete cascade,
  company_id uuid not null references public.company_master(company_id),
  category text not null,
  subtype text not null,
  persona text not null,
  title text not null,
  finding text not null,
  why_it_matters text not null,
  recommended_action text not null,
  priority text not null,
  confidence smallint not null,
  confidence_rationale text not null,
  business_impact_amount_usd bigint not null default 0,
  business_impact_description text not null,
  generated_at timestamptz not null default now(),
  review_status text not null default 'pending',
  version integer not null default 1,

  constraint insights_category_values
    check (category in ('revenue_cross_sell', 'credit_risk', 'capital_markets_advisory', 'treasury_payments_liquidity')),
  constraint insights_subtype_values
    check (subtype in ('relationship_risk', 'opportunity_risk', 'project_risk', 'credit_risk', 'operational_risk')),
  constraint insights_persona_values
    check (persona in ('relationship_manager', 'credit_officer', 'capital_markets_banker', 'treasury_sales_officer', 'risk_officer', 'executive_sponsor')),
  constraint insights_priority_values
    check (priority in ('critical', 'high', 'medium', 'low')),
  constraint insights_confidence_range
    check (confidence between 0 and 100),
  constraint insights_review_status_values
    check (review_status in ('pending', 'approved', 'rejected')),
  constraint insights_version_positive
    check (version >= 1)
);

create index insights_request_idx on public.insights (request_id);
create index insights_company_idx on public.insights (company_id);
create index insights_review_status_idx on public.insights (review_status);
create index insights_generated_at_idx on public.insights (generated_at desc);
```

**Optimistic concurrency pattern:** the API layer's approve/reject/reset
handler does

```sql
update public.insights
   set review_status = :new_status, version = version + 1
 where id = :insight_id
   and version = :expected_version
returning *;
```

Zero rows returned means either the id doesn't exist (404) or the version
didn't match (409) — the handler distinguishes the two with a preceding
existence check. This needs no extra column beyond `version`; a
`SELECT ... FOR UPDATE` is unnecessary since the `WHERE version = ...`
clause already makes the update atomic under Postgres's MVCC.

`company_code`/`company_name` are **not** duplicated onto this table —
`MAPPING.md` calls for joining `company_master` (or a Supabase view) at
read time, since inserting them here would let them drift if a company is
ever renamed. This is a place the earlier frontend mock's `Insight` type
does duplicate them (`companyCode`, `companyName` alongside `companyId`);
the API layer should keep those fields in the response DTO for backward
compatibility with the shipped UI (`MAPPING.md`, `MIGRATION_PLAN.md`) while
resolving them via a join rather than storage.

---

## 5. `insight_evidence`

Evidence items are heterogeneous by design — a `RISK_*` code points at
`risk_assessment`, an `RMN_*` code points at a FAISS-indexed JSON file, not
a table. A strict foreign key per source type would require a different
column per evidence kind. This table stores the citation the agent already
produced (`evidence_code`, `label`, `detail`, `date`) without attempting to
re-normalize it into a polymorphic FK — the code remains the traceable,
stable pointer back to its origin (see `MAPPING.md`'s evidence-code table).

```sql
create table public.insight_evidence (
  id uuid primary key default gen_random_uuid(),
  insight_id uuid not null references public.insights(id) on delete cascade,
  source_agent text not null,
  evidence_code text not null,
  label text not null,
  detail text not null,
  evidence_date date not null,

  constraint insight_evidence_source_agent_values
    check (source_agent in ('external_data_agent', 'internal_data_agent', 'relationship_notes_agent'))
);

create index insight_evidence_insight_idx on public.insight_evidence (insight_id);
```

`source_type` (`internal`/`external`) is not a stored column — it's
derived from `source_agent` at read time (`MAPPING.md`), same as the
frontend mock's `ev()` helper does today (`sourceType: sourceAgent ===
'external_data_agent' ? 'external' : 'internal'`), so the two can never
drift out of sync.

---

## 6. `insight_review_events`

Append-only audit log backing `Insight.reviewHistory[]`. Never updated or
deleted; a "generated" row is inserted alongside the `insights` row at
creation time.

```sql
create table public.insight_review_events (
  id uuid primary key default gen_random_uuid(),
  insight_id uuid not null references public.insights(id) on delete cascade,
  action text not null,
  actor_id text not null,          -- 'system' for the generated event
  actor_display_name text not null,
  reason text,                      -- only present when action = 'rejected'
  occurred_at timestamptz not null default now(),

  constraint insight_review_events_action_values
    check (action in ('generated', 'approved', 'rejected', 'reset')),
  constraint insight_review_events_reason_values
    check (reason is null or reason in ('incorrect', 'insufficient_evidence', 'duplicate', 'not_material', 'outdated', 'wrong_audience', 'action_not_useful')),
  constraint insight_review_events_reason_only_on_reject
    check (reason is null or action = 'rejected')
);

create index insight_review_events_insight_idx on public.insight_review_events (insight_id, occurred_at);
```

---

## 7. `user_preferences`

No `users`/`bankers` table exists in the current schema — `requested_by`
and RM/exec-sponsor names elsewhere are plain strings, not FKs. This table
follows that same convention rather than introducing user modeling this
contract doesn't otherwise need (see Open Questions in
`MIGRATION_PLAN.md`).

```sql
create table public.user_preferences (
  user_id text primary key,   -- same free-text identifier convention as research_requests.requested_by
  display_name text not null,
  role text not null,
  default_data_domains text[] not null default '{}',
  default_ranking_criteria text[] not null default '{}',
  email_digest_enabled boolean not null default true,
  at_risk_alerts_enabled boolean not null default true,
  display_density text not null default 'comfortable',
  default_lookback_months smallint not null default 24,
  updated_at timestamptz not null default now(),

  constraint user_preferences_display_density_values
    check (display_density in ('comfortable', 'compact')),
  constraint user_preferences_lookback_range
    check (default_lookback_months between 1 and 60)
);

create trigger user_preferences_set_updated_at
  before update on public.user_preferences
  for each row execute function public.set_updated_at();
```

---

## Summary

| Table | Rows today | Backs |
|---|---|---|
| `research_requests` | 0 (none exists) | `POST/GET /v1/requests` |
| `request_company_progress` | 0 | `ResearchRequestDetail.companyProgress[]` |
| `request_source_errors` | 0 | `ResearchRequestDetail.sourceErrors[]` |
| `insights` | 0 | `GET /v1/insights*`, approve/reject/reset |
| `insight_evidence` | 0 | `Insight.evidence[]` |
| `insight_review_events` | 0 | `Insight.reviewHistory[]` |
| `user_preferences` | 0 | `GET/PATCH /v1/preferences` |

Explicitly **not** proposed: a `users`/`bankers` table (see Open Questions,
`MIGRATION_PLAN.md`), a `reference_data`/taxonomy table for the small enum
lists in `Metadata` (kept as code constants — see `MAPPING.md`), and any
change to the 10 existing tables in `sql/internal_tables.sql`.

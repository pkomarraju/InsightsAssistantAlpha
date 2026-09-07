-- Persistence for api/server.py's own dev-bridge state: generated research
-- requests and insights, so a process restart (or a UI reload after one)
-- doesn't lose request/insight history including failed runs. This is
-- deliberately NOT docs/api/PROPOSED_SCHEMA.md's normalized
-- research_requests/insights/insight_evidence/... design -- that proposal
-- targets the full contracts/api (`/v1/*`) DTOs a real service-role-backed
-- API would serve, which nothing in this repo implements yet (see
-- docs/api/MIGRATION_PLAN.md). These two tables instead store api/server.py's
-- actual current flat ResearchRequest/InsightDto Pydantic models verbatim as
-- jsonb, one row per id -- exactly what that module already builds and
-- serves from its in-memory STORE/INSIGHTS_STORE dicts today. Reapplying the
-- normalized schema later is a separate, independent migration; it does not
-- need to read from these tables.
--
-- Uses the existing public.set_updated_at() trigger function from
-- internal_tables.sql -- run that file first.

begin;

create table public.app_requests (
  request_id text primary key,
  requested_by text not null,
  status text not null,
  current_stage text not null,
  state jsonb not null,  -- full ResearchRequest.model_dump(mode="json"), by_alias -- the source of truth for GET responses
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index app_requests_status_idx on public.app_requests (status);
create index app_requests_created_at_idx on public.app_requests (created_at desc);

create trigger app_requests_set_updated_at
  before update on public.app_requests
  for each row execute function public.set_updated_at();

create table public.app_insights (
  id text primary key,
  request_id text not null references public.app_requests(request_id) on delete cascade,
  review_status text not null,
  state jsonb not null,  -- full InsightDto.model_dump(mode="json"), by_alias
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index app_insights_request_idx on public.app_insights (request_id);
create index app_insights_review_status_idx on public.app_insights (review_status);

create trigger app_insights_set_updated_at
  before update on public.app_insights
  for each row execute function public.set_updated_at();

commit;

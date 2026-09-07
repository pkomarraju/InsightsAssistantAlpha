-- Supabase/PostgreSQL schema for a fully synthetic internal enterprise dataset:
-- fictional relationships between a bank and ten real Fortune 500 companies,
-- used to validate that the Insights Assistant correctly combines internal
-- relationship data with external (EDGAR) signals into the right insight.
--
-- insight_ground_truth is evaluation-only: no MCP tool exposes it to the agent.

begin;

create extension if not exists pgcrypto;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- 1. Company master
create table public.company_master (
  company_id uuid primary key default gen_random_uuid(),
  company_code text not null unique,
  company_name text not null,
  ticker text,
  cik text,
  industry text not null,
  sector text not null,
  fortune500_flag boolean not null default true,
  fortune_rank smallint,
  relationship_tier text not null,
  relationship_start_date date not null,
  synthetic_flag boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  constraint company_master_code_format
    check (company_code ~ '^CLI_[0-9]{3,}$'),
  constraint company_master_ticker_format
    check (ticker is null or ticker ~ '^[A-Z0-9.-]{1,10}$'),
  constraint company_master_cik_format
    check (cik is null or cik ~ '^[0-9]{10}$'),
  constraint company_master_tier_values
    check (relationship_tier in ('tier_1', 'tier_2')),
  constraint company_master_fortune_rank_range
    check (fortune_rank is null or fortune_rank between 1 and 500)
);

create unique index company_master_ticker_uq
  on public.company_master (ticker)
  where ticker is not null;

create trigger company_master_set_updated_at
  before update on public.company_master
  for each row execute function public.set_updated_at();

-- 2. Relationship snapshot (current state)
create table public.relationship_snapshot (
  relationship_id uuid primary key default gen_random_uuid(),
  evidence_code text not null unique,
  company_id uuid not null references public.company_master(company_id) on delete cascade,
  relationship_strength text not null,
  current_annual_revenue numeric(14,2) not null,
  prior_year_revenue numeric(14,2) not null,
  yoy_growth_pct numeric(6,2) not null,
  transaction_volume_ytd numeric(16,2) not null,
  relationship_status text not null,
  relationship_manager text not null,
  executive_sponsor text not null,
  as_of_date date not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  constraint relationship_snapshot_evidence_code_format
    check (evidence_code ~ '^REL_[0-9]{3,}$'),
  constraint relationship_snapshot_strength_values
    check (relationship_strength in ('strong', 'moderate', 'developing', 'at_risk')),
  constraint relationship_snapshot_status_values
    check (relationship_status in ('strong', 'stable', 'developing_opportunity', 'at_risk', 'critical')),
  constraint relationship_snapshot_company_uq
    unique (company_id)
);

create trigger relationship_snapshot_set_updated_at
  before update on public.relationship_snapshot
  for each row execute function public.set_updated_at();

-- 3. Relationship metrics, monthly time series (24 months per company)
create table public.relationship_metrics_monthly (
  metric_id uuid primary key default gen_random_uuid(),
  evidence_code text not null unique,
  company_id uuid not null references public.company_master(company_id) on delete cascade,
  observation_month date not null,
  transaction_volume numeric(16,2) not null,
  relationship_revenue numeric(14,2) not null,
  pipeline_value numeric(14,2) not null,
  risk_score numeric(5,2) not null,
  sentiment_label text not null,
  trend_label text not null,
  created_at timestamptz not null default now(),

  constraint relationship_metrics_evidence_code_format
    check (evidence_code ~ '^RELM_[0-9]{3,}$'),
  constraint relationship_metrics_month_start
    check (observation_month = date_trunc('month', observation_month)::date),
  constraint relationship_metrics_risk_range
    check (risk_score between 0 and 100),
  constraint relationship_metrics_sentiment_values
    check (sentiment_label in ('positive', 'neutral', 'negative', 'mixed')),
  constraint relationship_metrics_trend_values
    check (trend_label in (
      'rapid_growth', 'slow_growth', 'stable', 'declining',
      'sudden_deterioration', 'recovering'
    )),
  constraint relationship_metrics_company_month_uq
    unique (company_id, observation_month)
);

create index relationship_metrics_company_idx
  on public.relationship_metrics_monthly (company_id, observation_month);

-- 4. Products
create table public.products (
  product_id uuid primary key default gen_random_uuid(),
  evidence_code text not null unique,
  company_id uuid not null references public.company_master(company_id) on delete cascade,
  product_name text not null,
  annual_revenue numeric(14,2) not null,
  product_status text not null,
  growth_trend text not null,
  renewal_date date,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  constraint products_evidence_code_format
    check (evidence_code ~ '^PROD_[0-9]{3,}$'),
  constraint products_name_values
    check (product_name in (
      'payments', 'treasury_services', 'lending', 'investment_banking',
      'capital_markets', 'fx', 'trade_finance', 'liquidity_management', 'custody'
    )),
  constraint products_status_values
    check (product_status in ('active', 'inactive', 'pilot', 'churned')),
  constraint products_growth_trend_values
    check (growth_trend in ('rapid_growth', 'growing', 'stable', 'declining', 'at_risk'))
);

create index products_company_idx
  on public.products (company_id);

create trigger products_set_updated_at
  before update on public.products
  for each row execute function public.set_updated_at();

-- 5. Opportunities
create table public.opportunities (
  opportunity_id uuid primary key default gen_random_uuid(),
  evidence_code text not null unique,
  company_id uuid not null references public.company_master(company_id) on delete cascade,
  opportunity_name text not null,
  opportunity_value numeric(14,2) not null,
  stage text not null,
  probability_pct numeric(5,2) not null,
  expected_close_date date,
  strategic_importance text not null,
  status text not null,
  competitive_pressure text not null default 'none',
  competitor_name text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  constraint opportunities_evidence_code_format
    check (evidence_code ~ '^OPP_[0-9]{3,}$'),
  constraint opportunities_stage_values
    check (stage in ('prospecting', 'qualification', 'proposal', 'negotiation', 'closed_won', 'closed_lost', 'stalled')),
  constraint opportunities_probability_range
    check (probability_pct between 0 and 100),
  constraint opportunities_strategic_importance_values
    check (strategic_importance in ('low', 'medium', 'high', 'critical')),
  constraint opportunities_status_values
    check (status in ('active', 'won', 'lost', 'stalled')),
  constraint opportunities_competitive_pressure_values
    check (competitive_pressure in ('none', 'low', 'moderate', 'high'))
);

create index opportunities_company_idx
  on public.opportunities (company_id);

create trigger opportunities_set_updated_at
  before update on public.opportunities
  for each row execute function public.set_updated_at();

-- 6. Risk assessment (quarterly)
create table public.risk_assessment (
  risk_id uuid primary key default gen_random_uuid(),
  evidence_code text not null unique,
  company_id uuid not null references public.company_master(company_id) on delete cascade,
  as_of_date date not null,
  credit_exposure numeric(14,2) not null,
  relationship_risk_score numeric(5,2) not null,
  concentration_risk_score numeric(5,2) not null,
  operational_risk_score numeric(5,2) not null,
  risk_trend text not null,
  explanatory_comment text not null,
  created_at timestamptz not null default now(),

  constraint risk_assessment_evidence_code_format
    check (evidence_code ~ '^RISK_[0-9]{3,}$'),
  constraint risk_assessment_scores_range
    check (
      relationship_risk_score between 0 and 100
      and concentration_risk_score between 0 and 100
      and operational_risk_score between 0 and 100
    ),
  constraint risk_assessment_trend_values
    check (risk_trend in ('improving', 'stable', 'worsening')),
  constraint risk_assessment_company_date_uq
    unique (company_id, as_of_date)
);

create index risk_assessment_company_idx
  on public.risk_assessment (company_id, as_of_date);

-- 7. Client interactions
create table public.client_interactions (
  interaction_id uuid primary key default gen_random_uuid(),
  evidence_code text not null unique,
  company_id uuid not null references public.company_master(company_id) on delete cascade,
  interaction_date date not null,
  interaction_type text not null,
  topic text not null,
  attendees text[] not null default '{}',
  summary text not null,
  sentiment text not null,
  created_at timestamptz not null default now(),

  constraint client_interactions_evidence_code_format
    check (evidence_code ~ '^INT_[0-9]{3,}$'),
  constraint client_interactions_type_values
    check (interaction_type in ('meeting', 'call', 'email', 'conference')),
  constraint client_interactions_topic_values
    check (topic in (
      'expansion_plans', 'investment_priorities', 'relationship_concerns',
      'product_discussion', 'competitor_activity', 'renewal_discussion',
      'strategic_opportunity'
    )),
  constraint client_interactions_sentiment_values
    check (sentiment in ('positive', 'neutral', 'negative', 'mixed'))
);

create index client_interactions_company_idx
  on public.client_interactions (company_id, interaction_date);

-- 8. Internal notes (unstructured, semantic-retrieval surface)
create table public.internal_notes (
  note_id uuid primary key default gen_random_uuid(),
  evidence_code text not null unique,
  company_id uuid not null references public.company_master(company_id) on delete cascade,
  related_interaction_id uuid references public.client_interactions(interaction_id) on delete set null,
  note_date date not null,
  author text not null,
  note_text text not null,
  tags text[] not null default '{}',
  created_at timestamptz not null default now(),

  constraint internal_notes_evidence_code_format
    check (evidence_code ~ '^NOTE_[0-9]{3,}$')
);

create index internal_notes_company_idx
  on public.internal_notes (company_id, note_date);

-- 9. External signals (fixed, synthetic "public event" per scenario -- not live EDGAR data)
create table public.external_signals (
  signal_id uuid primary key default gen_random_uuid(),
  evidence_code text not null unique,
  company_id uuid not null references public.company_master(company_id) on delete cascade,
  signal_date date not null,
  headline text not null,
  description text not null,
  signal_character text not null,
  synthetic_flag boolean not null default true,
  created_at timestamptz not null default now(),

  constraint external_signals_evidence_code_format
    check (evidence_code ~ '^SIG_[0-9]{3,}$'),
  constraint external_signals_character_values
    check (signal_character in ('positive', 'negative', 'significant_neutral'))
);

create index external_signals_company_idx
  on public.external_signals (company_id);

-- 10. Insight ground truth (evaluation-only -- never exposed via an MCP tool)
create table public.insight_ground_truth (
  ground_truth_id uuid primary key default gen_random_uuid(),
  evidence_code text not null unique,
  company_id uuid not null references public.company_master(company_id) on delete cascade,
  external_signal_id uuid not null references public.external_signals(signal_id) on delete cascade,
  expected_internal_signal text not null,
  expected_signal_alignment text not null,
  expected_insight_category text not null,
  expected_relevance_level text not null,
  expected_relationship_interpretation text not null,
  key_internal_evidence_ids text[] not null,
  expected_action text not null,
  explanation text not null,
  created_at timestamptz not null default now(),

  constraint insight_ground_truth_evidence_code_format
    check (evidence_code ~ '^GT_[0-9]{3,}$'),
  constraint insight_ground_truth_alignment_values
    check (expected_signal_alignment in ('CONFIRMING', 'CONTRADICTORY', 'NEUTRAL', 'INSUFFICIENT')),
  constraint insight_ground_truth_category_values
    check (expected_insight_category in ('OPPORTUNITY', 'RELATIONSHIP_RISK', 'NO_MATERIAL_IMPACT', 'INSUFFICIENT_EVIDENCE')),
  constraint insight_ground_truth_relevance_values
    check (expected_relevance_level in ('LOW', 'MEDIUM', 'HIGH')),
  constraint insight_ground_truth_action_values
    check (expected_action in ('SURFACE', 'SUPPRESS', 'REVIEW'))
);

create index insight_ground_truth_company_idx
  on public.insight_ground_truth (company_id);

commit;

-- Migration for the new internal-data schema referenced by
-- mcp_servers/internal_data_server.py's get_company_research_context tool:
-- target_companies / bank_credit_exposures / crm_deal_pipeline /
-- internal_risk_flags.
--
-- NOT APPLIED to the live Supabase project. This file is the reviewable
-- migration only -- run it deliberately (e.g. via the same psycopg/
-- SUPABASE_DB_URL one-off script used for sql/app_state_tables.sql) once
-- reviewed. Never use a service-role key at runtime; this migration itself
-- is schema/seeding work, same convention as internal_tables.sql.
--
-- Starting point was the reference DDL the requester supplied (four tables,
-- no company_code/evidence_code/benchmark_index/as_of_date columns, no
-- NOT NULL FKs, no check constraints beyond the enums). Everything below
-- that isn't in that reference DDL is a hardening addition, called out
-- inline. Existing enterprise-data conventions from internal_tables.sql are
-- reused: pgcrypto's gen_random_uuid() (this migration also enables
-- uuid-ossp for compatibility with the reference DDL's uuid_generate_v4(),
-- since the seed data's literal UUIDs don't depend on either), and the
-- existing public.set_updated_at() trigger function.

begin;

create extension if not exists "uuid-ossp";
create extension if not exists pgcrypto;

create type public.company_status as enum ('At risk', 'Developing opportunity', 'Stable', 'Strong');
create type public.exposure_type as enum ('Revolving Credit', 'Term Loan B', 'Vendor Payable', 'Bond Underwriting');
create type public.deal_stage as enum ('Origination', 'Pitching', 'Due Diligence', 'Term Sheet Signed');

-- 1. Core corporate entities ---------------------------------------------

create table public.target_companies (
    id uuid primary key default uuid_generate_v4(),
    ticker varchar(10) unique not null,
    name text not null,
    industry text not null,
    current_status public.company_status not null,
    internal_coverage_lead text not null,

    -- Hardening addition: a stable compatibility identifier, not derived
    -- from row order. Backfilled below from the existing company_master
    -- table by ticker where one already exists (7 of the 8 seeded tickers
    -- do); for a ticker with no legacy match, a deterministic fallback
    -- derived from the ticker itself (never from insertion order) is used
    -- instead. mcp_servers/internal_data_server.py's compatibility layer
    -- reads this column to resolve a company the same way regardless of
    -- which schema actually backs it.
    company_code text unique,

    created_at timestamptz default now()
);

create index idx_target_companies_ticker on public.target_companies (ticker);
create index idx_target_companies_company_code on public.target_companies (company_code);

-- 2. Credit exposure & facilities -----------------------------------------

create table public.bank_credit_exposures (
    id uuid primary key default uuid_generate_v4(),
    -- Hardening addition: NOT NULL (the reference DDL allowed a facility
    -- with no owning company, which get_company_research_context could
    -- never resolve back to anything).
    company_id uuid not null references public.target_companies(id) on delete cascade,
    facility_type public.exposure_type not null,
    committed_amount_usd numeric(15, 2) not null,
    drawn_amount_usd numeric(15, 2) not null,
    interest_spread_bps int not null,           -- e.g. SOFR + 275 bps
    -- Hardening addition: the reference DDL's "SOFR + N bps" comment named
    -- a benchmark but never stored it as data.
    benchmark_index text not null default 'SOFR',
    covenant_max_leverage numeric(4, 2),        -- e.g. Max 3.5x Debt/EBITDA

    -- Hardening addition: stable, application-generated evidence code --
    -- deterministic from this row's own immutable id (never from row
    -- order), populated by the trigger below. Format:
    -- EXP_<TICKER>_<first 8 hex chars of id>.
    evidence_code text unique,

    -- Hardening addition: this schema has no historical versioning (a row
    -- is the current snapshot of one facility), so as_of_date/updated_at
    -- mark when that snapshot was last known accurate -- see
    -- mcp_servers/internal_data_server.py's as_of_date handling, which
    -- treats a snapshot as-of any date >= this column's value and stale
    -- otherwise, rather than pretending it has point-in-time history.
    as_of_date date not null default current_date,
    updated_at timestamptz not null default now(),

    maturity_date date not null,

    -- Hardening addition, from the migration checklist.
    constraint bank_credit_exposures_drawn_le_committed
        check (drawn_amount_usd <= committed_amount_usd)
);

create index idx_credit_exposures_company on public.bank_credit_exposures (company_id);
create index idx_credit_exposures_company_as_of on public.bank_credit_exposures (company_id, as_of_date desc);
create index idx_credit_exposures_maturity on public.bank_credit_exposures (maturity_date);

create trigger bank_credit_exposures_set_updated_at
    before update on public.bank_credit_exposures
    for each row execute function public.set_updated_at();

-- 3. CRM deals & banker pipeline -------------------------------------------

create table public.crm_deal_pipeline (
    id uuid primary key default uuid_generate_v4(),
    company_id uuid not null references public.target_companies(id) on delete cascade,
    deal_title text not null,
    potential_fee_usd numeric(12, 2) not null,
    stage public.deal_stage not null,
    -- Hardening addition: explicit range check (the reference DDL's own
    -- comment already implied 0-1 -- "0.40 for 40%" -- but never enforced it).
    probability numeric(3, 2) not null check (probability between 0 and 1),
    target_close_date date not null,

    evidence_code text unique,
    as_of_date date not null default current_date,
    updated_at timestamptz not null default now()
);

create index idx_crm_pipeline_company on public.crm_deal_pipeline (company_id);
create index idx_crm_pipeline_target_close on public.crm_deal_pipeline (target_close_date);

create trigger crm_deal_pipeline_set_updated_at
    before update on public.crm_deal_pipeline
    for each row execute function public.set_updated_at();

-- 4. Internal risk registry -------------------------------------------------

create table public.internal_risk_flags (
    id uuid primary key default uuid_generate_v4(),
    company_id uuid not null references public.target_companies(id) on delete cascade,
    flag_type text not null,                    -- e.g., 'Covenant Squeeze', 'Contract Dispute', 'Renewal'
    severity text not null check (severity in ('Low', 'Medium', 'High', 'Critical')),
    description text not null,
    reported_date date not null default current_date,

    evidence_code text unique,
    updated_at timestamptz not null default now()
);

create index idx_risk_flags_company on public.internal_risk_flags (company_id);
create index idx_risk_flags_company_reported on public.internal_risk_flags (company_id, reported_date desc);

create trigger internal_risk_flags_set_updated_at
    before update on public.internal_risk_flags
    for each row execute function public.set_updated_at();

-- Deterministic evidence_code / company_code generation ---------------------
--
-- A single trigger function, parameterized by TG_ARGV[0] (the code prefix),
-- keeps the "derive from the row's own immutable id, never from row order"
-- rule in exactly one place for all three child tables.

create or replace function public.set_evidence_code()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
    v_ticker text;
    v_prefix text := TG_ARGV[0];
begin
    if new.evidence_code is not null then
        return new;
    end if;
    select ticker into v_ticker from public.target_companies where id = new.company_id;
    new.evidence_code := v_prefix || '_' || coalesce(upper(v_ticker), 'UNKNOWN') || '_'
        || left(replace(new.id::text, '-', ''), 8);
    return new;
end;
$$;

create trigger bank_credit_exposures_set_evidence_code
    before insert on public.bank_credit_exposures
    for each row execute function public.set_evidence_code('EXP');

create trigger crm_deal_pipeline_set_evidence_code
    before insert on public.crm_deal_pipeline
    for each row execute function public.set_evidence_code('DEAL');

create trigger internal_risk_flags_set_evidence_code
    before insert on public.internal_risk_flags
    for each row execute function public.set_evidence_code('RISKFLAG');

-- company_code backfill: reuse the existing company_master.company_code
-- (CLI_xxx) wherever the ticker already matches a row there, so the two
-- schemas share one stable identifier space instead of forking a second
-- one. A ticker with no legacy match gets a deterministic fallback derived
-- from the ticker itself (NEWCLI_<TICKER>) -- never from insertion order,
-- and stable across reruns of this backfill.
update public.target_companies tc
set company_code = cm.company_code
from public.company_master cm
where tc.company_code is null and cm.ticker = tc.ticker;

update public.target_companies
set company_code = 'NEWCLI_' || upper(ticker)
where company_code is null;

alter table public.target_companies alter column company_code set not null;

-- Row-level security ----------------------------------------------------
--
-- Same posture as sql/rls_policies.sql's 8 existing enterprise-data tables:
-- read-only to the anon/publishable key, no service-role key at runtime.

alter table public.target_companies enable row level security;
alter table public.bank_credit_exposures enable row level security;
alter table public.crm_deal_pipeline enable row level security;
alter table public.internal_risk_flags enable row level security;

create policy "anon_read_target_companies" on public.target_companies
    for select to anon using (true);

create policy "anon_read_bank_credit_exposures" on public.bank_credit_exposures
    for select to anon using (true);

create policy "anon_read_crm_deal_pipeline" on public.crm_deal_pipeline
    for select to anon using (true);

create policy "anon_read_internal_risk_flags" on public.internal_risk_flags
    for select to anon using (true);

commit;

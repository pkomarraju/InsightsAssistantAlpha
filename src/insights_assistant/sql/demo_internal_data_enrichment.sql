-- Demo-only compatibility and enrichment for the four new internal-data tables.
-- Safe to rerun: schema changes use IF NOT EXISTS and added rows use stable
-- evidence codes with ON CONFLICT updates.
--
-- Run after new_internal_data.ddl.txt / new_internal_data_tables.sql.

begin;

-- -------------------------------------------------------------------------
-- 1. Bring a database created from the original lightweight DDL up to the
--    contract expected by mcp_servers/internal_data_server.py.
-- -------------------------------------------------------------------------

alter table public.target_companies
    add column if not exists company_code text,
    add column if not exists evidence_code text,
    add column if not exists as_of_date date default current_date,
    add column if not exists updated_at timestamptz default now();

alter table public.bank_credit_exposures
    add column if not exists benchmark_index text default 'SOFR',
    add column if not exists evidence_code text,
    add column if not exists as_of_date date default current_date,
    add column if not exists updated_at timestamptz default now();

alter table public.crm_deal_pipeline
    add column if not exists evidence_code text,
    add column if not exists as_of_date date default current_date,
    add column if not exists updated_at timestamptz default now();

alter table public.internal_risk_flags
    add column if not exists evidence_code text,
    add column if not exists updated_at timestamptz default now();

-- Reuse the application's existing CLI_xxx identifier when company_master
-- exists. Fall back to a stable ticker-based code for standalone demo DBs.
do $$
begin
    if to_regclass('public.company_master') is not null then
        execute $sql$
            update public.target_companies tc
               set company_code = cm.company_code
              from public.company_master cm
             where tc.company_code is null
               and upper(tc.ticker) = upper(cm.ticker)
        $sql$;
    end if;
end;
$$;

update public.target_companies
   set company_code = 'NEWCLI_' || upper(ticker)
 where company_code is null;

update public.target_companies
   set evidence_code = 'PROFILE_' || upper(ticker) || '_' ||
                       upper(left(replace(id::text, '-', ''), 8))
 where evidence_code is null;

update public.target_companies
   set as_of_date = date '2026-08-31'
 where as_of_date is null;

-- Backfill stable, traceable evidence codes for any rows inserted from the
-- original seed file before evidence_code existed.
update public.bank_credit_exposures e
   set evidence_code = 'EXP_' || upper(c.ticker) || '_' ||
                       upper(left(replace(e.id::text, '-', ''), 8))
  from public.target_companies c
 where e.company_id = c.id
   and e.evidence_code is null;

update public.crm_deal_pipeline d
   set evidence_code = 'DEAL_' || upper(c.ticker) || '_' ||
                       upper(left(replace(d.id::text, '-', ''), 8))
  from public.target_companies c
 where d.company_id = c.id
   and d.evidence_code is null;

update public.internal_risk_flags r
   set evidence_code = 'RISKFLAG_' || upper(c.ticker) || '_' ||
                       upper(left(replace(r.id::text, '-', ''), 8))
  from public.target_companies c
 where r.company_id = c.id
   and r.evidence_code is null;

update public.bank_credit_exposures
   set benchmark_index = 'SOFR'
 where benchmark_index is null;

update public.bank_credit_exposures
   set as_of_date = date '2026-08-31'
 where as_of_date is null;

update public.crm_deal_pipeline
   set as_of_date = date '2026-08-31'
 where as_of_date is null;

create unique index if not exists uq_target_companies_company_code
    on public.target_companies (company_code);
create unique index if not exists uq_target_companies_evidence_code
    on public.target_companies (evidence_code);
create unique index if not exists uq_bank_credit_exposures_evidence_code
    on public.bank_credit_exposures (evidence_code);
create unique index if not exists uq_crm_deal_pipeline_evidence_code
    on public.crm_deal_pipeline (evidence_code);
create unique index if not exists uq_internal_risk_flags_evidence_code
    on public.internal_risk_flags (evidence_code);

alter table public.target_companies
    alter column company_code set not null,
    alter column evidence_code set not null,
    alter column as_of_date set default current_date,
    alter column as_of_date set not null;
alter table public.bank_credit_exposures
    alter column benchmark_index set default 'SOFR',
    alter column benchmark_index set not null,
    alter column evidence_code set not null,
    alter column as_of_date set default current_date,
    alter column as_of_date set not null;
alter table public.crm_deal_pipeline
    alter column evidence_code set not null,
    alter column as_of_date set default current_date,
    alter column as_of_date set not null;
alter table public.internal_risk_flags
    alter column evidence_code set not null;

-- Preserve evidence-code generation for future inserts that omit a code.
create or replace function public.set_company_profile_evidence_code()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    if new.evidence_code is null then
        new.evidence_code := 'PROFILE_' || upper(new.ticker) || '_' ||
                             upper(left(replace(new.id::text, '-', ''), 8));
    end if;
    return new;
end;
$$;

drop trigger if exists target_companies_set_evidence_code
    on public.target_companies;
create trigger target_companies_set_evidence_code
    before insert on public.target_companies
    for each row execute function public.set_company_profile_evidence_code();

create or replace function public.set_evidence_code()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
    v_ticker text;
    v_prefix text := tg_argv[0];
begin
    if new.evidence_code is not null then
        return new;
    end if;

    select ticker
      into v_ticker
      from public.target_companies
     where id = new.company_id;

    new.evidence_code := v_prefix || '_' || upper(coalesce(v_ticker, 'UNKNOWN')) || '_' ||
                         upper(left(replace(new.id::text, '-', ''), 8));
    return new;
end;
$$;

drop trigger if exists bank_credit_exposures_set_evidence_code
    on public.bank_credit_exposures;
create trigger bank_credit_exposures_set_evidence_code
    before insert on public.bank_credit_exposures
    for each row execute function public.set_evidence_code('EXP');

drop trigger if exists crm_deal_pipeline_set_evidence_code
    on public.crm_deal_pipeline;
create trigger crm_deal_pipeline_set_evidence_code
    before insert on public.crm_deal_pipeline
    for each row execute function public.set_evidence_code('DEAL');

drop trigger if exists internal_risk_flags_set_evidence_code
    on public.internal_risk_flags;
create trigger internal_risk_flags_set_evidence_code
    before insert on public.internal_risk_flags
    for each row execute function public.set_evidence_code('RISKFLAG');

-- -------------------------------------------------------------------------
-- 2. Add missing facility snapshots. Existing seed data already gives
--    GOOGL, XOM, AAPL, and COST facilities.
-- -------------------------------------------------------------------------

insert into public.bank_credit_exposures (
    id, company_id, facility_type, committed_amount_usd, drawn_amount_usd,
    interest_spread_bps, benchmark_index, covenant_max_leverage,
    maturity_date, evidence_code, as_of_date
)
select
    v.id::uuid, c.id, v.facility_type::public.exposure_type,
    v.committed_amount_usd, v.drawn_amount_usd, v.interest_spread_bps,
    v.benchmark_index, v.covenant_max_leverage, v.maturity_date,
    v.evidence_code, v.as_of_date
from (
    values
        ('90000000-0000-0000-0000-000000000001', 'WMT', 'Revolving Credit',
         1200000000.00, 360000000.00, 95, 'SOFR', 3.00,
         date '2028-12-15', 'EXP_WMT_DEMO_001', date '2026-08-31'),
        ('90000000-0000-0000-0000-000000000002', 'UNH', 'Revolving Credit',
         1000000000.00, 600000000.00, 160, 'SOFR', 3.50,
         date '2027-05-31', 'EXP_UNH_DEMO_001', date '2026-08-31'),
        ('90000000-0000-0000-0000-000000000003', 'COR', 'Revolving Credit',
         650000000.00, 455000000.00, 150, 'SOFR', 3.25,
         date '2027-09-30', 'EXP_COR_DEMO_001', date '2026-08-31'),
        ('90000000-0000-0000-0000-000000000004', 'CVS', 'Term Loan B',
         1500000000.00, 1500000000.00, 210, 'SOFR', 4.50,
         date '2027-12-15', 'EXP_CVS_DEMO_001', date '2026-08-31')
) as v(
    id, ticker, facility_type, committed_amount_usd, drawn_amount_usd,
    interest_spread_bps, benchmark_index, covenant_max_leverage,
    maturity_date, evidence_code, as_of_date
)
join public.target_companies c on upper(c.ticker) = v.ticker
on conflict (evidence_code) do update set
    committed_amount_usd = excluded.committed_amount_usd,
    drawn_amount_usd = excluded.drawn_amount_usd,
    interest_spread_bps = excluded.interest_spread_bps,
    benchmark_index = excluded.benchmark_index,
    covenant_max_leverage = excluded.covenant_max_leverage,
    maturity_date = excluded.maturity_date,
    as_of_date = excluded.as_of_date,
    updated_at = now();

-- -------------------------------------------------------------------------
-- 3. Add missing active CRM opportunities. Existing seed data already gives
--    XOM, COST, and UNH active deals.
-- -------------------------------------------------------------------------

insert into public.crm_deal_pipeline (
    id, company_id, deal_title, potential_fee_usd, stage, probability,
    target_close_date, evidence_code, as_of_date
)
select
    v.id::uuid, c.id, v.deal_title, v.potential_fee_usd,
    v.stage::public.deal_stage, v.probability, v.target_close_date,
    v.evidence_code, v.as_of_date
from (
    values
        ('91000000-0000-0000-0000-000000000001', 'GOOGL',
         'AI Data Center Financing Advisory', 6200000.00, 'Origination', 0.30,
         date '2027-04-30', 'DEAL_GOOGL_DEMO_001', date '2026-08-31'),
        ('91000000-0000-0000-0000-000000000002', 'AAPL',
         'Commercial Paper and Liquidity Backstop Advisory', 2400000.00, 'Origination', 0.35,
         date '2027-06-30', 'DEAL_AAPL_DEMO_001', date '2026-08-31'),
        ('91000000-0000-0000-0000-000000000003', 'WMT',
         'Supply Chain Automation Financing', 5000000.00, 'Pitching', 0.45,
         date '2027-02-28', 'DEAL_WMT_DEMO_001', date '2026-08-31'),
        ('91000000-0000-0000-0000-000000000004', 'COR',
         'Receivables Securitization Program', 3600000.00, 'Due Diligence', 0.60,
         date '2027-01-31', 'DEAL_COR_DEMO_001', date '2026-08-31'),
        ('91000000-0000-0000-0000-000000000005', 'CVS',
         'Debt Refinancing and Liability Management', 7500000.00, 'Pitching', 0.45,
         date '2027-06-30', 'DEAL_CVS_DEMO_001', date '2026-08-31')
) as v(
    id, ticker, deal_title, potential_fee_usd, stage, probability,
    target_close_date, evidence_code, as_of_date
)
join public.target_companies c on upper(c.ticker) = v.ticker
on conflict (evidence_code) do update set
    deal_title = excluded.deal_title,
    potential_fee_usd = excluded.potential_fee_usd,
    stage = excluded.stage,
    probability = excluded.probability,
    target_close_date = excluded.target_close_date,
    as_of_date = excluded.as_of_date,
    updated_at = now();

-- -------------------------------------------------------------------------
-- 4. Add missing internal flags. These are coverage signals, not assertions
--    of default or borrower distress unless explicitly stated.
-- -------------------------------------------------------------------------

insert into public.internal_risk_flags (
    id, company_id, flag_type, severity, description,
    reported_date, evidence_code
)
select
    v.id::uuid, c.id, v.flag_type, v.severity, v.description,
    v.reported_date, v.evidence_code
from (
    values
        ('92000000-0000-0000-0000-000000000001', 'AAPL',
         'Low Facility Utilization', 'Low',
         'Only $50M of the $750M revolving facility is drawn (6.7% utilization), with maturity in March 2029. Treat negative working capital as a monitoring signal rather than evidence of immediate liquidity stress.',
         date '2026-08-22', 'RISKFLAG_AAPL_DEMO_001'),
        ('92000000-0000-0000-0000-000000000002', 'WMT',
         'Funding Calendar Review', 'Medium',
         'The coverage team should align the supply-chain investment calendar with available revolver capacity before the financing pitch advances.',
         date '2026-08-24', 'RISKFLAG_WMT_DEMO_001'),
        ('92000000-0000-0000-0000-000000000003', 'COST',
         'Expansion Execution Monitoring', 'Medium',
         'Distribution-center expansion is increasing funding needs while the syndicated-facility opportunity remains in due diligence; confirm draw timing and committed capacity.',
         date '2026-08-25', 'RISKFLAG_COST_DEMO_001'),
        ('92000000-0000-0000-0000-000000000004', 'COR',
         'Seasonal Working Capital Concentration', 'Medium',
         'Internal treasury review identified higher seasonal working-capital usage and customer concentration; validate liquidity capacity before peak funding demand.',
         date '2026-08-26', 'RISKFLAG_COR_DEMO_001'),
        ('92000000-0000-0000-0000-000000000005', 'CVS',
         'Covenant Headroom Watch', 'High',
         'Internal credit monitoring estimates leverage at 3.9x against a 4.5x maximum covenant. Confirm covenant definitions and headroom before advancing the refinancing proposal.',
         date '2026-08-28', 'RISKFLAG_CVS_DEMO_001')
) as v(
    id, ticker, flag_type, severity, description, reported_date, evidence_code
)
join public.target_companies c on upper(c.ticker) = v.ticker
on conflict (evidence_code) do update set
    flag_type = excluded.flag_type,
    severity = excluded.severity,
    description = excluded.description,
    reported_date = excluded.reported_date,
    updated_at = now();

commit;

-- Quick verification: every UI company should now have a company profile,
-- at least one facility, at least one active deal, and at least one flag.
select
    c.ticker,
    c.name,
    c.company_code,
    count(distinct e.id) as facility_count,
    count(distinct d.id) as active_deal_count,
    count(distinct r.id) as risk_flag_count
from public.target_companies c
left join public.bank_credit_exposures e on e.company_id = c.id
left join public.crm_deal_pipeline d on d.company_id = c.id
left join public.internal_risk_flags r on r.company_id = c.id
group by c.id, c.ticker, c.name, c.company_code
order by c.ticker;

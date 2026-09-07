-- Seed data for sql/new_internal_data_tables.sql, transcribed from the
-- reference seed data supplied for this migration (treated as reference
-- data only, not modified in place -- copied here so it lives in the repo
-- and can be reviewed/applied alongside the schema migration it depends
-- on). NOT APPLIED to the live Supabase project; run after
-- new_internal_data_tables.sql, deliberately, same as that file.
--
-- No changes needed to the original INSERT statements themselves: every
-- hardening column the schema migration added (company_code, evidence_code,
-- benchmark_index, as_of_date, updated_at) either has a default or is
-- populated by a trigger, so this is the reference data byte-for-byte.

begin;

insert into public.target_companies (id, ticker, name, industry, current_status, internal_coverage_lead) values
('11111111-1111-1111-1111-111111111111', 'GOOGL', 'Alphabet', 'Internet Services', 'At risk', 'Sarah Jenkins (TMT Group)'),
('22222222-2222-2222-2222-222222222222', 'XOM', 'Exxon Mobil', 'Oil & Gas', 'At risk', 'Mark Ramirez (Energy Group)'),
('33333333-3333-3333-3333-333333333333', 'AAPL', 'Apple', 'Consumer Electronics', 'Strong', 'Sarah Jenkins (TMT Group)'),
('44444444-4444-4444-4444-444444444444', 'WMT', 'Walmart', 'Retail', 'Strong', 'David Chen (Consumer/Retail)'),
('55555555-5555-5555-5555-555555555555', 'COST', 'Costco', 'Wholesale Retail', 'Developing opportunity', 'David Chen (Consumer/Retail)'),
('66666666-6666-6666-6666-666666666666', 'UNH', 'UnitedHealth Group', 'Managed Health Care', 'Developing opportunity', 'Elena Rostova (Healthcare)'),
('77777777-7777-7777-7777-777777777777', 'COR', 'Cencora', 'Health Care Distribution', 'Stable', 'Elena Rostova (Healthcare)'),
('88888888-8888-8888-8888-888888888888', 'CVS', 'CVS Health', 'Health Care & Pharmacy', 'Stable', 'Elena Rostova (Healthcare)');

insert into public.bank_credit_exposures (company_id, facility_type, committed_amount_usd, drawn_amount_usd, interest_spread_bps, covenant_max_leverage, maturity_date) values
-- GOOGL: Large credit line, low draw, but heavy compliance exposure
('11111111-1111-1111-1111-111111111111', 'Revolving Credit', 500000000.00, 200000000.00, 110, 2.50, '2027-06-30'),
-- XOM: Syndicated term loan nearing repayment window (golden scenario -- see tests/agents/test_external_research_plan.py)
('22222222-2222-2222-2222-222222222222', 'Term Loan B', 850000000.00, 850000000.00, 240, 3.25, '2026-11-15'),
-- AAPL: Backstop facility, barely utilized
('33333333-3333-3333-3333-333333333333', 'Revolving Credit', 750000000.00, 50000000.00, 75, 2.00, '2029-03-31'),
-- COST: Expansion credit line for new distribution centers
('55555555-5555-5555-5555-555555555555', 'Revolving Credit', 300000000.00, 120000000.00, 125, 2.75, '2028-09-30');

insert into public.crm_deal_pipeline (company_id, deal_title, potential_fee_usd, stage, probability, target_close_date) values
('22222222-2222-2222-2222-222222222222', 'Carbon-Capture Project Refinancing Bond', 4200000.00, 'Pitching', 0.40, '2026-10-31'),
('55555555-5555-5555-5555-555555555555', 'Logistics Automation Syndicated Facility', 2800000.00, 'Due Diligence', 0.65, '2027-01-15'),
('66666666-6666-6666-6666-666666666666', 'Digital Health Acquisition M&A Advisory', 9500000.00, 'Origination', 0.25, '2027-04-30');

insert into public.internal_risk_flags (company_id, flag_type, severity, description) values
('11111111-1111-1111-1111-111111111111', 'Regulatory Fine Exposure', 'High', 'DOJ Antitrust scrutiny threatening ad-tech cash flow margins; internal stress-test indicates possible EBITDA contraction.'),
('22222222-2222-2222-2222-222222222222', 'Maturity Wall Imminence', 'Critical', '$850M Term Loan B matures in Nov 2026; sustained oil volatility creates underwriting spread risk.'),
('66666666-6666-6666-6666-666666666666', 'Margin Recovery Indicator', 'Medium', 'Internal models show medical loss ratio stabilizing; poised for aggressive hospital M&A.');

commit;

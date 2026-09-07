-- Row-level security for app_requests/app_insights (see app_state_tables.sql).
--
-- Unlike rls_policies.sql's 8 enterprise-data tables -- read-only to anon,
-- since only MCP tools query them and nothing should ever write through
-- that path -- these two tables ARE api/server.py's own read/write state,
-- and api/server.py only ever holds the anon/publishable key (SUPABASE_KEY;
-- there is no service-role key configured for this prototype). So anon gets
-- full CRUD here, scoped to exactly these two tables, deliberately not
-- extended to any of the 8 enterprise-data tables or the two
-- MCP-unreachable eval tables. This is a single-user dev prototype with no
-- auth (see api/server.py's module docstring); revisit this policy
-- (per-banker row ownership) before any real multi-tenant deployment --
-- see docs/api/MIGRATION_PLAN.md's Open Question 4.

begin;

create policy "anon_all_app_requests" on public.app_requests
  for all to anon using (true) with check (true);

create policy "anon_all_app_insights" on public.app_insights
  for all to anon using (true) with check (true);

commit;

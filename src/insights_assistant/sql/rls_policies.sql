-- Row-level security policies for the internal enterprise dataset.
--
-- RLS is enabled by default on all tables in this project. This grants
-- read-only access, to the anon/publishable key only, on the 8 tables the
-- internal_data MCP server is allowed to query. external_signals and
-- insight_ground_truth intentionally get no policy at all: with RLS on and
-- no policy, they stay unreadable via the publishable key even if a future
-- tool or query mistakenly tries to reach them. The direct Postgres
-- connection (SUPABASE_DB_URL) bypasses RLS entirely and is for
-- schema/seeding scripts only -- it must never be used at agent runtime.

begin;

create policy "anon_read_company_master" on public.company_master
  for select to anon using (true);

create policy "anon_read_relationship_snapshot" on public.relationship_snapshot
  for select to anon using (true);

create policy "anon_read_relationship_metrics_monthly" on public.relationship_metrics_monthly
  for select to anon using (true);

create policy "anon_read_products" on public.products
  for select to anon using (true);

create policy "anon_read_opportunities" on public.opportunities
  for select to anon using (true);

create policy "anon_read_risk_assessment" on public.risk_assessment
  for select to anon using (true);

create policy "anon_read_client_interactions" on public.client_interactions
  for select to anon using (true);

create policy "anon_read_internal_notes" on public.internal_notes
  for select to anon using (true);

-- No policies for external_signals or insight_ground_truth: RLS stays on,
-- default-deny, by design.

commit;

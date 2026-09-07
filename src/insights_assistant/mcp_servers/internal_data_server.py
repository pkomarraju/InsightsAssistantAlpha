import json
import os
from datetime import date, datetime

from dotenv import load_dotenv
from mcp.server import MCPServer
from supabase import create_client

from insights_assistant.contracts.workflow.external_research import (
    CompanyResearchContext,
    CreditFacilityContext,
    CrmDealContext,
    RiskFlagContext,
)

load_dotenv()

server = MCPServer("internal-data")

# Uses the anon/publishable key deliberately: RLS grants it read access to
# the 8 original tables plus the 4 new ones below (target_companies/
# bank_credit_exposures/crm_deal_pipeline/internal_risk_flags -- see
# sql/new_internal_data_tables.sql) and nothing else. external_signals and
# insight_ground_truth have no policy, so they stay unreachable through this
# client even if a future tool tries to query them -- see
# sql/rls_policies.sql. Never swap this for SUPABASE_DB_URL here.


def _client():
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])


def _dump(rows) -> str:
    return json.dumps(rows, indent=2, default=str)


def _resolve_company(identifier: str) -> dict:
    client = _client()
    result = (
        client.table("company_master")
        .select("company_id,company_name,ticker,relationship_tier")
        .or_(f"ticker.eq.{identifier.upper()},company_name.ilike.%{identifier}%")
        .execute()
    )
    if not result.data:
        raise ValueError(f"No company found matching {identifier!r}")
    if len(result.data) > 1:
        names = ", ".join(f"{c['company_name']} ({c['ticker']})" for c in result.data)
        raise ValueError(f"{identifier!r} matches multiple companies: {names}. Use the ticker to disambiguate.")
    return result.data[0]


def resolve_ticker_for_company_code(company_code: str) -> str | None:
    """Looks up company_master.ticker for an existing CLI_xxx application
    code -- used by agents/research_execution.py to translate the
    company_code its ResearchTasks are keyed by into the ticker
    build_company_research_context/build_external_research_plan actually
    need (get_company_research_context resolves by ticker or the newer
    target_companies.company_code, never by this legacy company_code
    directly). Returns None rather than raising when not found or the
    lookup itself fails, since the caller already falls back to a generic
    external research plan in that case."""

    try:
        result = (
            _client().table("company_master").select("ticker").eq("company_code", company_code).execute()
        )
    except Exception:
        return None
    if not result.data:
        return None
    return result.data[0].get("ticker")


@server.tool()
def list_companies() -> str:
    """List all companies in the internal relationship dataset, with their relationship tier."""
    result = (
        _client().table("company_master")
        .select("company_name,ticker,industry,sector,relationship_tier,relationship_start_date")
        .order("company_name")
        .execute()
    )
    return _dump(result.data)


@server.tool()
def get_company_overview(company: str) -> str:
    """Get a company's current relationship snapshot: tier, revenue, YoY growth, status,
    relationship manager, and executive sponsor. `company` may be a ticker or a name/partial name.
    """
    c = _resolve_company(company)
    result = (
        _client().table("relationship_snapshot")
        .select("*")
        .eq("company_id", c["company_id"])
        .execute()
    )
    return _dump({"company": c, "relationship": result.data[0] if result.data else None})


@server.tool()
def get_relationship_history(company: str, months: int = 24) -> str:
    """Get the monthly relationship time series (transaction volume, revenue, pipeline value,
    risk score, sentiment, trend label) for a company, most recent `months` first.
    """
    c = _resolve_company(company)
    result = (
        _client().table("relationship_metrics_monthly")
        .select("evidence_code,observation_month,transaction_volume,relationship_revenue,pipeline_value,risk_score,sentiment_label,trend_label")
        .eq("company_id", c["company_id"])
        .order("observation_month", desc=True)
        .limit(months)
        .execute()
    )
    return _dump(result.data)


@server.tool()
def get_products(company: str) -> str:
    """Get the banking products a company uses: revenue, status, and growth trend per product."""
    c = _resolve_company(company)
    result = (
        _client().table("products")
        .select("evidence_code,product_name,annual_revenue,product_status,growth_trend,renewal_date")
        .eq("company_id", c["company_id"])
        .execute()
    )
    return _dump(result.data)


@server.tool()
def get_opportunities(company: str, status: str | None = None) -> str:
    """Get a company's opportunity pipeline. Optionally filter by status
    (active, won, lost, stalled)."""
    c = _resolve_company(company)
    query = (
        _client().table("opportunities")
        .select("evidence_code,opportunity_name,opportunity_value,stage,probability_pct,expected_close_date,strategic_importance,status,competitive_pressure,competitor_name")
        .eq("company_id", c["company_id"])
    )
    if status:
        query = query.eq("status", status)
    result = query.execute()
    return _dump(result.data)


@server.tool()
def get_risk_assessment(company: str) -> str:
    """Get a company's quarterly risk history: credit exposure, relationship/concentration/
    operational risk scores, risk trend, and explanatory comments, most recent first."""
    c = _resolve_company(company)
    result = (
        _client().table("risk_assessment")
        .select("evidence_code,as_of_date,credit_exposure,relationship_risk_score,concentration_risk_score,operational_risk_score,risk_trend,explanatory_comment")
        .eq("company_id", c["company_id"])
        .order("as_of_date", desc=True)
        .execute()
    )
    return _dump(result.data)


@server.tool()
def get_client_interactions(company: str, limit: int = 10) -> str:
    """Get a company's recent client meetings/calls: date, type, topic, attendees, summary,
    and sentiment, most recent first."""
    c = _resolve_company(company)
    result = (
        _client().table("client_interactions")
        .select("evidence_code,interaction_date,interaction_type,topic,attendees,summary,sentiment")
        .eq("company_id", c["company_id"])
        .order("interaction_date", desc=True)
        .limit(limit)
        .execute()
    )
    return _dump(result.data)


@server.tool()
def search_internal_notes(company: str, query: str | None = None, limit: int = 5) -> str:
    """Search a relationship manager's unstructured notes for a company. If `query` is given,
    matches notes whose text contains it (case-insensitive); otherwise returns the most recent
    notes. This is the semantic-retrieval surface -- notes are free text, not structured fields.
    """
    c = _resolve_company(company)
    q = (
        _client().table("internal_notes")
        .select("evidence_code,note_date,author,note_text,tags")
        .eq("company_id", c["company_id"])
    )
    if query:
        q = q.ilike("note_text", f"%{query}%")
    result = q.order("note_date", desc=True).limit(limit).execute()
    return _dump(result.data)


# --- Company research context (sql/new_internal_data_tables.sql) -----------
#
# get_company_research_context is the ONLY thing agents/external_research_plan.py
# and agents/external_adapters.py ever see of the bank's internal data --
# external_data_agent itself never receives Supabase credentials or queries
# any internal table (see agents/orchestrator.py's SPECIALIST_PROMPTS and
# agents/external_adapters.py's module docstring). build_company_research_context
# is a plain function (not just the @server.tool() wrapper below) precisely so
# research_execution.py can call it in-process -- the same direct-Supabase-read
# pattern api/server.py already uses for company resolution -- rather than
# round-tripping through this module's own stdio MCP server for something the
# app itself needs structurally before it can even build a plan.
#
# Two backing schemas, one typed shape: a company present in the new
# target_companies table (7 of the 10 existing demo companies, plus their
# credit facilities/CRM deals/risk flags) gets a context built from that
# schema (source="new_schema"); everything else falls back to the original
# company_master/relationship_snapshot/opportunities/risk_assessment tables,
# approximated into the same CompanyResearchContext shape (source=
# "legacy_schema") -- callers never need to know or care which backed a
# given company. An empty facilities/deals/risk_flags list is valid data
# (e.g. Apple's revolving-credit-only, no-flags profile), never an error.


def _new_schema_company(identifier: str) -> dict | None:
    result = (
        _client().table("target_companies")
        .select("id,ticker,name,industry,current_status,internal_coverage_lead,company_code")
        .or_(f"ticker.eq.{identifier.upper()},company_code.eq.{identifier}")
        .execute()
    )
    if not result.data:
        return None
    if len(result.data) > 1:
        raise ValueError(f"{identifier!r} matches multiple companies in target_companies")
    return result.data[0]


def _facility_from_new_schema(row: dict) -> CreditFacilityContext:
    committed = float(row["committed_amount_usd"])
    drawn = float(row["drawn_amount_usd"])
    return CreditFacilityContext(
        evidence_code=row["evidence_code"],
        as_of_date=date.fromisoformat(row["as_of_date"]),
        facility_type=row["facility_type"],
        committed_amount_usd=committed,
        drawn_amount_usd=drawn,
        utilization_pct=round(100 * drawn / committed, 1) if committed else None,
        interest_spread_bps=row["interest_spread_bps"],
        benchmark_index=row.get("benchmark_index"),
        covenant_max_leverage=float(row["covenant_max_leverage"]) if row.get("covenant_max_leverage") is not None else None,
        maturity_date=date.fromisoformat(row["maturity_date"]),
    )


def _deal_from_new_schema(row: dict) -> CrmDealContext:
    return CrmDealContext(
        evidence_code=row["evidence_code"],
        deal_title=row["deal_title"],
        stage=row["stage"],
        probability=float(row["probability"]),
        potential_fee_usd=float(row["potential_fee_usd"]),
        target_close_date=date.fromisoformat(row["target_close_date"]),
    )


def _risk_flag_from_new_schema(row: dict) -> RiskFlagContext:
    return RiskFlagContext(
        evidence_code=row["evidence_code"],
        flag_type=row["flag_type"],
        severity=row["severity"],
        description=row["description"],
        reported_date=date.fromisoformat(row["reported_date"]),
    )


def _build_from_new_schema(company: dict, as_of: date) -> CompanyResearchContext:
    client = _client()
    company_id = company["id"]

    exposures = (
        client.table("bank_credit_exposures").select("*").eq("company_id", company_id)
        .lte("as_of_date", as_of.isoformat()).order("as_of_date", desc=True).execute()
    )
    deals = client.table("crm_deal_pipeline").select("*").eq("company_id", company_id).execute()
    flags = (
        client.table("internal_risk_flags").select("*").eq("company_id", company_id)
        .lte("reported_date", as_of.isoformat()).order("reported_date", desc=True).execute()
    )

    return CompanyResearchContext(
        company_code=company["company_code"],
        ticker=company["ticker"],
        company_name=company["name"],
        industry=company["industry"],
        status=company["current_status"],
        coverage_lead=company["internal_coverage_lead"],
        as_of_date=as_of,
        facilities=[_facility_from_new_schema(r) for r in exposures.data],
        deals=[_deal_from_new_schema(r) for r in deals.data],
        risk_flags=[_risk_flag_from_new_schema(r) for r in flags.data],
        source="new_schema",
    )


def _build_from_legacy_schema(identifier: str, as_of: date) -> CompanyResearchContext:
    """Approximates the same CompanyResearchContext shape from the original
    company_master/relationship_snapshot/opportunities/risk_assessment
    tables, for a company not (yet) present in target_companies. The legacy
    schema has no committed-vs-drawn facility breakdown, no benchmark
    index/spread, and no covenant field -- those stay None rather than
    guessed; only what the legacy data genuinely supports is populated.
    """
    client = _client()
    c = _resolve_company(identifier)
    company_id = c["company_id"]

    snapshot = (
        client.table("relationship_snapshot").select("*").eq("company_id", company_id).execute()
    ).data
    snapshot_row = snapshot[0] if snapshot else None

    risk_rows = (
        client.table("risk_assessment")
        .select("evidence_code,as_of_date,credit_exposure,risk_trend,explanatory_comment")
        .eq("company_id", company_id).lte("as_of_date", as_of.isoformat())
        .order("as_of_date", desc=True).execute()
    ).data

    facilities = [
        CreditFacilityContext(
            evidence_code=row["evidence_code"],
            as_of_date=date.fromisoformat(row["as_of_date"]),
            committed_amount_usd=None,
            drawn_amount_usd=None,
            utilization_pct=None,
            interest_spread_bps=None,
            benchmark_index=None,
            covenant_max_leverage=None,
            maturity_date=None,
        )
        for row in risk_rows
        if row.get("credit_exposure") is not None
    ]

    opp_rows = (
        client.table("opportunities")
        .select("evidence_code,opportunity_name,opportunity_value,stage,probability_pct,expected_close_date")
        .eq("company_id", company_id).execute()
    ).data
    deals = [
        CrmDealContext(
            evidence_code=row["evidence_code"],
            deal_title=row["opportunity_name"],
            stage=row["stage"],
            probability=round((row.get("probability_pct") or 0) / 100, 2),
            potential_fee_usd=float(row["opportunity_value"]),
            target_close_date=date.fromisoformat(row["expected_close_date"]),
        )
        for row in opp_rows
        if row.get("expected_close_date")
    ]

    risk_flags = [
        RiskFlagContext(
            evidence_code=row["evidence_code"],
            flag_type=f"Risk trend: {row['risk_trend']}" if row.get("risk_trend") else "Risk assessment",
            severity="High" if row.get("risk_trend") == "worsening" else "Medium",
            description=row.get("explanatory_comment") or "",
            reported_date=date.fromisoformat(row["as_of_date"]),
        )
        for row in risk_rows
        if row.get("explanatory_comment")
    ]

    return CompanyResearchContext(
        company_code=c.get("company_code") or c["company_id"],
        ticker=c["ticker"],
        company_name=c["company_name"],
        industry="",
        status=snapshot_row["relationship_status"] if snapshot_row else "unknown",
        coverage_lead=snapshot_row["relationship_manager"] if snapshot_row else "unassigned",
        as_of_date=as_of,
        facilities=facilities,
        deals=deals,
        risk_flags=risk_flags,
        source="legacy_schema",
    )


def build_company_research_context(company: str, as_of_date: str | None = None) -> CompanyResearchContext:
    """Resolves `company` by exact ticker or stable application identifier
    (a target_companies.company_code / legacy company_master.company_code),
    trying the new schema first and falling back to the legacy one -- see
    module docstring. Raises ValueError if the identifier resolves to no
    company in either schema (a real failure, distinct from a found company
    that simply has zero facilities/deals/risk flags, which is valid data).
    """
    as_of = date.fromisoformat(as_of_date) if as_of_date else datetime.now().date()

    new_schema_row = _new_schema_company(company)
    if new_schema_row is not None:
        return _build_from_new_schema(new_schema_row, as_of)
    return _build_from_legacy_schema(company, as_of)


@server.tool()
def get_company_research_context(company: str, as_of_date: str | None = None) -> str:
    """Get a company's full internal research context as of a date: identity/
    status/coverage lead, credit facilities (with computed utilization,
    spread, benchmark index, covenant threshold, maturity), active CRM deals
    (stage/probability/fee/target close date), and applicable internal risk
    flags -- each with a stable evidence_code and date. `company` may be a
    ticker (e.g. XOM) or an application company_code (e.g. CLI_006 or
    NEWCLI_XOM). `as_of_date` defaults to today (ISO YYYY-MM-DD). An empty
    facilities/deals/risk_flags list is valid: it means none exist for this
    company as of this date, not that the lookup failed.
    """
    context = build_company_research_context(company, as_of_date)
    return context.model_dump_json(indent=2, by_alias=True)


if __name__ == "__main__":
    server.run(transport="stdio")

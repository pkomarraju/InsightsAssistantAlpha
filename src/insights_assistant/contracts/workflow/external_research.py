"""Typed shapes for the internal-context -> external-plan -> curated-adapter
pipeline that replaces external_data_agent's old raw-EDGAR/raw-vendor-tool
design. See:
  - mcp_servers/internal_data_server.py (builds CompanyResearchContext, from
    either the new target_companies/bank_credit_exposures/crm_deal_pipeline/
    internal_risk_flags tables or the legacy company_master/relationship_
    snapshot/opportunities/risk_assessment ones -- CompanyResearchContext
    itself never says which; see its own `source` field).
  - agents/external_research_plan.py (CompanyResearchContext -> ExternalResearchPlan).
  - agents/external_adapters.py (ExternalResearchPlan -> ExternalEvidenceRecord
    list per provider, each wrapped in a ProviderCallResult).

Every one of these is a plain, fully-typed Pydantic model precisely so nothing
in the pipeline passes a loosely-structured dict between steps -- the
orchestrator, research_execution, and the Synthesizer all see the same typed
shape a test can construct and assert against directly.
"""

from datetime import date, datetime

from pydantic import Field

from insights_assistant.contracts.api.common import ApiModel
from insights_assistant.contracts.api.enums import ExternalProvider, ExternalResearchTrigger, ProviderStatus


# --- Internal research context (mcp_servers/internal_data_server.py) --------


class CreditFacilityContext(ApiModel):
    """One row of bank_credit_exposures (or, for a company not yet migrated
    to that table, a best-effort equivalent derived from the legacy
    risk_assessment.credit_exposure figure -- see internal_data_server.py's
    compatibility layer, which sets facility_type=None and leaves the
    facility-specific fields unset in that fallback case)."""

    evidence_code: str
    as_of_date: date
    facility_type: str | None = None
    committed_amount_usd: float | None = None
    drawn_amount_usd: float | None = None
    utilization_pct: float | None = Field(
        default=None, description="drawn_amount_usd / committed_amount_usd, computed here, never by the model."
    )
    interest_spread_bps: int | None = None
    benchmark_index: str | None = None
    covenant_max_leverage: float | None = None
    maturity_date: date | None = None


class CrmDealContext(ApiModel):
    """One row of crm_deal_pipeline (or a legacy `opportunities` row, for a
    company not yet migrated -- see internal_data_server.py)."""

    evidence_code: str
    deal_title: str
    stage: str
    probability: float = Field(ge=0, le=1)
    potential_fee_usd: float
    target_close_date: date


class RiskFlagContext(ApiModel):
    """One row of internal_risk_flags (or a legacy risk_assessment-derived
    flag). `description` is bank-internal free text: agents/external_research_plan.py
    reads it only to *detect* a trigger category (e.g. does it mention
    "margin") -- it is never forwarded into an external prompt or adapter
    call verbatim; only the matched ExternalResearchTrigger is."""

    evidence_code: str
    flag_type: str
    severity: str
    description: str
    reported_date: date


class CompanyResearchContext(ApiModel):
    """Bounded, structured internal context for one company, as of one date
    -- what agents/external_research_plan.py's build_external_research_plan
    consumes to decide which external adapters are worth calling, and all
    that's ever passed toward external_data_agent (see its own module
    docstring: never raw Supabase rows, never a live DB connection).
    """

    company_code: str = Field(description="Stable existing CLI_xxx identifier where one exists; see company_code_map.")
    ticker: str
    company_name: str
    industry: str
    status: str
    coverage_lead: str
    as_of_date: date
    facilities: list[CreditFacilityContext] = Field(default_factory=list)
    deals: list[CrmDealContext] = Field(default_factory=list)
    risk_flags: list[RiskFlagContext] = Field(default_factory=list)
    source: str = Field(
        description="Which backing schema this context was built from: 'new_schema' "
        "(target_companies/bank_credit_exposures/crm_deal_pipeline/internal_risk_flags), "
        "'legacy_schema' (company_master/relationship_snapshot/opportunities/risk_assessment, "
        "for a company not yet present in the new tables), or 'not_found'."
    )


# --- External research plan (agents/external_research_plan.py) -------------


class PlannedAdapterCall(ApiModel):
    """One curated adapter (agents/external_adapters.py's ADAPTER_NAMES) the
    plan calls for, and the public-safe reason -- `focus` is a short,
    already-genericized description (e.g. "liquidity and leverage metrics
    ahead of a near-term maturity"), never the raw internal record text that
    triggered it."""

    adapter: str
    reason: ExternalResearchTrigger
    focus: str


class ExternalResearchPlan(ApiModel):
    """What agents/external_research_plan.py hands back to research_execution.py
    for one company: which curated adapters are worth calling and why. This
    -- not the CompanyResearchContext itself -- is what gets rendered into
    external_data_agent's task prompt (see research_execution.py), so the
    agent sees categories/reasons, never raw internal fields."""

    ticker: str
    as_of_date: date
    triggers: list[ExternalResearchTrigger] = Field(default_factory=list)
    adapter_calls: list[PlannedAdapterCall] = Field(default_factory=list)
    generic: bool = Field(
        description="True when built without internal context (internal research disabled for this "
        "request, or the company resolved to no internal context at all) -- a bounded default plan "
        "was used instead of a trigger-driven one."
    )

    def render_for_prompt(self) -> str:
        """Bounded, structured-but-textual summary for the external agent's
        prompt -- categories and reasons only, never raw internal record
        content (see PlannedAdapterCall.focus)."""

        if not self.adapter_calls:
            return (
                f"No internal research context is available for {self.ticker}. Use the curated "
                "adapters at your discretion, preferring financial-health and valuation signals."
            )
        lines = [f"Research plan for {self.ticker} (as of {self.as_of_date.isoformat()}):"]
        for call in self.adapter_calls:
            lines.append(f"- {call.adapter}: {call.focus} (trigger: {call.reason.value})")
        return "\n".join(lines)


# --- External evidence / provider status (agents/external_adapters.py) -----


class ExternalEvidenceRecord(ApiModel):
    """One normalized fact from a curated adapter call. evidence_code is
    always generated deterministically in Python (see
    agents/external_adapters.py::_evidence_code) from normalized, immutable
    fields -- provider/ticker/metric/period -- never by the LLM; the
    external specialist only ever copies one of these verbatim."""

    evidence_code: str
    provider: ExternalProvider
    ticker: str
    metric: str
    value: float | str | None
    unit: str | None
    period_end: date | None
    published_at: date | None = Field(
        default=None, description="When the source published this figure, if known and distinct from period_end."
    )
    source_tool: str = Field(description="The real underlying MCP tool name this was fetched from, e.g. get_financial_ratios.")
    source_locator: str = Field(description="Enough to trace this back to the exact call, e.g. 'fmp:get_financial_ratios:XOM:annual'.")
    retrieved_at: datetime
    stale: bool = Field(
        default=False, description="True when this is the most recent data available but is older than a "
        "freshness threshold for its metric class -- never fabricated as current."
    )


class ProviderCallResult(ApiModel):
    """One provider's outcome for one company's external research pass.
    completed with an empty `evidence` list is NO_DATA, a genuinely
    different, positive fact from UNAVAILABLE/AUTH_ERROR/RATE_LIMITED/
    TIMED_OUT -- see ProviderStatus and agents/external_adapters.py's
    module docstring. `message` is set for every non-COMPLETED status."""

    provider: ExternalProvider
    status: ProviderStatus
    evidence: list[ExternalEvidenceRecord] = Field(default_factory=list)
    message: str | None = None


class ProviderStatusReport(ApiModel):
    """Leaner than ProviderCallResult (no `evidence` -- that already flows
    to research_execution.py via SpecialistEvidenceItem/EvidenceItem
    separately): what agents/orchestrator.py's SpecialistFindings.
    provider_statuses actually carries, and what
    contracts.workflow.research.SourcePayload.provider_statuses persists.
    The specialist self-reports one of these per adapter it called, from
    the ProviderCallResult JSON each adapter tool call returned -- the same
    trust model the rest of SpecialistFindings already uses for evidence
    codes/dates the model read out of real tool output, not a new one.
    """

    provider: ExternalProvider
    status: ProviderStatus
    message: str | None = None

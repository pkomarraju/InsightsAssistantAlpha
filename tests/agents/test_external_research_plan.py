"""Covers agents/external_research_plan.py's deterministic
internal-trigger -> external-adapter routing. No LLM/network involved --
build_external_research_plan is a pure function over a typed
CompanyResearchContext.
"""

from datetime import date

from insights_assistant.agents.external_research_plan import build_external_research_plan
from insights_assistant.contracts.api.enums import ExternalResearchTrigger
from insights_assistant.contracts.workflow.external_research import (
    CompanyResearchContext,
    CreditFacilityContext,
    CrmDealContext,
    RiskFlagContext,
)

AS_OF = date(2026, 9, 5)


def _context(**overrides) -> CompanyResearchContext:
    defaults = dict(
        company_code="CLI_006", ticker="XOM", company_name="Exxon Mobil", industry="Oil & Gas",
        status="At risk", coverage_lead="Mark Ramirez", as_of_date=AS_OF,
        facilities=[], deals=[], risk_flags=[], source="new_schema",
    )
    defaults.update(overrides)
    return CompanyResearchContext(**defaults)


def _facility(**overrides) -> CreditFacilityContext:
    defaults = dict(
        evidence_code="EXP_XOM_1", as_of_date=AS_OF, facility_type="Term Loan B",
        committed_amount_usd=850_000_000.0, drawn_amount_usd=850_000_000.0, utilization_pct=100.0,
        interest_spread_bps=240, benchmark_index="SOFR", covenant_max_leverage=3.25,
        maturity_date=date(2026, 11, 15),
    )
    defaults.update(overrides)
    return CreditFacilityContext(**defaults)


def _deal(**overrides) -> CrmDealContext:
    defaults = dict(
        evidence_code="DEAL_XOM_1", deal_title="Carbon-Capture Project Refinancing Bond",
        stage="Pitching", probability=0.40, potential_fee_usd=4_200_000.0,
        target_close_date=date(2026, 10, 31),
    )
    defaults.update(overrides)
    return CrmDealContext(**defaults)


def _risk_flag(**overrides) -> RiskFlagContext:
    defaults = dict(
        evidence_code="RISKFLAG_XOM_1", flag_type="Maturity Wall Imminence", severity="Critical",
        description="$850M Term Loan B matures in Nov 2026.", reported_date=date(2026, 8, 1),
    )
    defaults.update(overrides)
    return RiskFlagContext(**defaults)


class TestGenericPlan:
    def test_no_context_returns_generic_bounded_plan(self):
        """Internal research disabled for the request -- external research
        must still work, via a bounded default plan, not be skipped."""
        plan = build_external_research_plan(None, ticker="XOM", as_of_date=AS_OF)

        assert plan.generic is True
        assert plan.triggers == []
        assert len(plan.adapter_calls) == 1
        assert plan.adapter_calls[0].adapter == "fmp_get_financial_health"
        assert plan.adapter_calls[0].reason == ExternalResearchTrigger.GENERIC

    def test_context_with_no_triggers_falls_back_to_generic_calls(self):
        context = _context()  # no facilities/deals/risk_flags at all
        plan = build_external_research_plan(context, ticker="XOM", as_of_date=AS_OF)

        assert plan.generic is False
        assert plan.triggers == [ExternalResearchTrigger.NONE]
        assert [c.adapter for c in plan.adapter_calls] == ["fmp_get_financial_health"]

    def test_render_for_prompt_never_leaks_raw_risk_flag_description(self):
        context = _context(risk_flags=[_risk_flag(description="Highly sensitive internal commentary about XOM.")])
        plan = build_external_research_plan(context, ticker="XOM", as_of_date=AS_OF)

        rendered = plan.render_for_prompt()
        assert "Highly sensitive internal commentary" not in rendered
        assert "XOM" in rendered


class TestTriggerDetection:
    def test_near_maturity_fires_financial_health_and_rate_signal(self):
        context = _context(facilities=[_facility(maturity_date=date(2027, 1, 1))])
        plan = build_external_research_plan(context, ticker="XOM", as_of_date=AS_OF)

        assert ExternalResearchTrigger.NEAR_MATURITY in plan.triggers
        adapters = {c.adapter for c in plan.adapter_calls}
        assert "fmp_get_financial_health" in adapters
        assert "fred_get_rate_signal" in adapters

    def test_maturity_far_in_the_future_does_not_trigger(self):
        context = _context(facilities=[_facility(maturity_date=date(2030, 1, 1), utilization_pct=10.0, covenant_max_leverage=None)])
        plan = build_external_research_plan(context, ticker="XOM", as_of_date=AS_OF)

        assert ExternalResearchTrigger.NEAR_MATURITY not in plan.triggers

    def test_high_utilization_triggers_independent_of_maturity(self):
        context = _context(facilities=[_facility(maturity_date=date(2030, 1, 1), utilization_pct=92.0, covenant_max_leverage=None)])
        plan = build_external_research_plan(context, ticker="XOM", as_of_date=AS_OF)

        assert ExternalResearchTrigger.HIGH_UTILIZATION in plan.triggers
        assert ExternalResearchTrigger.NEAR_MATURITY not in plan.triggers

    def test_low_utilization_does_not_trigger(self):
        context = _context(facilities=[_facility(maturity_date=date(2030, 1, 1), utilization_pct=6.7, covenant_max_leverage=None)])
        plan = build_external_research_plan(context, ticker="AAPL", as_of_date=AS_OF)

        assert ExternalResearchTrigger.HIGH_UTILIZATION not in plan.triggers

    def test_covenant_present_triggers_covenant_threshold(self):
        context = _context(facilities=[_facility(maturity_date=date(2030, 1, 1), utilization_pct=10.0, covenant_max_leverage=2.5)])
        plan = build_external_research_plan(context, ticker="XOM", as_of_date=AS_OF)

        assert ExternalResearchTrigger.COVENANT_THRESHOLD in plan.triggers

    def test_refinancing_keyword_in_deal_title_triggers_refinancing_opportunity(self):
        context = _context(deals=[_deal(deal_title="Carbon-Capture Project Refinancing Bond")])
        plan = build_external_research_plan(context, ticker="XOM", as_of_date=AS_OF)

        assert ExternalResearchTrigger.REFINANCING_OPPORTUNITY in plan.triggers
        adapters = {c.adapter for c in plan.adapter_calls}
        assert {"fmp_get_valuation", "av_get_earnings_signal", "av_get_market_signal", "fred_get_rate_signal"} <= adapters

    def test_ma_keyword_in_deal_title_triggers_ma_opportunity(self):
        context = _context(deals=[_deal(deal_title="Digital Health Acquisition M&A Advisory")])
        plan = build_external_research_plan(context, ticker="UNH", as_of_date=AS_OF)

        assert ExternalResearchTrigger.MA_OPPORTUNITY in plan.triggers
        adapters = {c.adapter for c in plan.adapter_calls}
        assert {"fmp_get_valuation", "av_get_earnings_signal"} <= adapters

    def test_margin_keyword_in_risk_flag_triggers_margin_risk(self):
        context = _context(risk_flags=[_risk_flag(
            flag_type="Margin Recovery Indicator", description="Medical loss ratio stabilizing.",
        )])
        plan = build_external_research_plan(context, ticker="UNH", as_of_date=AS_OF)

        assert ExternalResearchTrigger.MARGIN_RISK in plan.triggers

    def test_unrelated_deal_title_and_risk_flag_do_not_trigger_anything(self):
        context = _context(
            deals=[_deal(deal_title="Logistics Automation Syndicated Facility")],
            risk_flags=[_risk_flag(flag_type="Contract Dispute", description="Vendor dispute ongoing.")],
        )
        plan = build_external_research_plan(context, ticker="COST", as_of_date=AS_OF)

        assert plan.triggers == [ExternalResearchTrigger.NONE]

    def test_same_adapter_named_by_two_triggers_appears_once(self):
        """fmp_get_financial_health is reachable from NEAR_MATURITY,
        HIGH_UTILIZATION, COVENANT_THRESHOLD, and MARGIN_RISK -- it must
        never appear more than once in adapter_calls."""
        context = _context(
            facilities=[_facility()],  # near maturity + high utilization + covenant, all at once
            risk_flags=[_risk_flag(flag_type="Margin squeeze", description="margin pressure building")],
        )
        plan = build_external_research_plan(context, ticker="XOM", as_of_date=AS_OF)

        adapter_names = [c.adapter for c in plan.adapter_calls]
        assert adapter_names.count("fmp_get_financial_health") == 1

    def test_plan_is_deterministic_across_repeated_calls(self):
        context = _context(facilities=[_facility()], deals=[_deal()], risk_flags=[_risk_flag()])
        plan_a = build_external_research_plan(context, ticker="XOM", as_of_date=AS_OF)
        plan_b = build_external_research_plan(context, ticker="XOM", as_of_date=AS_OF)

        assert [c.adapter for c in plan_a.adapter_calls] == [c.adapter for c in plan_b.adapter_calls]
        assert plan_a.triggers == plan_b.triggers


class TestGoldenExxonScenario:
    """The exact synthetic scenario from the requester's reference seed
    data: $850M Term Loan B, fully drawn, 3.25x covenant, Nov 15 2026
    maturity, a Critical "Maturity Wall Imminence" flag, and a pitching
    refinancing bond deal."""

    def _xom_context(self) -> CompanyResearchContext:
        return _context(
            facilities=[_facility(
                committed_amount_usd=850_000_000.0, drawn_amount_usd=850_000_000.0, utilization_pct=100.0,
                covenant_max_leverage=3.25, maturity_date=date(2026, 11, 15),
            )],
            deals=[_deal(deal_title="Carbon-Capture Project Refinancing Bond")],
            risk_flags=[_risk_flag(flag_type="Maturity Wall Imminence", severity="Critical")],
        )

    def test_fires_maturity_utilization_covenant_and_refinancing_triggers(self):
        plan = build_external_research_plan(self._xom_context(), ticker="XOM", as_of_date=AS_OF)

        assert set(plan.triggers) >= {
            ExternalResearchTrigger.NEAR_MATURITY,
            ExternalResearchTrigger.HIGH_UTILIZATION,
            ExternalResearchTrigger.COVENANT_THRESHOLD,
            ExternalResearchTrigger.REFINANCING_OPPORTUNITY,
        }

    def test_calls_fmp_valuation_and_fred_rate_signal_for_refinancing_urgency(self):
        plan = build_external_research_plan(self._xom_context(), ticker="XOM", as_of_date=AS_OF)

        adapters = {c.adapter for c in plan.adapter_calls}
        assert "fmp_get_financial_health" in adapters
        assert "fmp_get_valuation" in adapters
        assert "fred_get_rate_signal" in adapters

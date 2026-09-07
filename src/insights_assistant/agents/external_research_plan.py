"""Deterministic internal-trigger -> external-adapter routing.

build_external_research_plan(context, ...) is a pure function: given one
company's CompanyResearchContext (or None, when internal research is
disabled for the request), it returns an ExternalResearchPlan naming which
of agents/external_adapters.py's curated adapters are worth calling and why.
No LLM call happens here -- which adapters get called is a deterministic
function of internal facts (near a maturity, over-utilized, a covenant on
file, a refinancing/M&A deal in the pipeline, a margin-flagged risk), not a
model's judgment. research_execution.py renders the resulting plan's
render_for_prompt() into external_data_agent's task prompt; the model then
still decides *how* to use each named adapter (which ticker/period/interval
to ask for), but not *whether* one is relevant.

Thresholds below are the demo's own documented judgment calls, not values
from any spec: NEAR_MATURITY_MONTHS=12, HIGH_UTILIZATION_PCT=85. Adjust
here if the product wants different sensitivity -- nothing else in the
pipeline hardcodes them.
"""

from datetime import date

from insights_assistant.contracts.api.enums import ExternalResearchTrigger
from insights_assistant.contracts.workflow.external_research import (
    CompanyResearchContext,
    ExternalResearchPlan,
    PlannedAdapterCall,
)

NEAR_MATURITY_MONTHS = 12
HIGH_UTILIZATION_PCT = 85.0

_REFINANCING_KEYWORDS = ("refinanc", "bond")
_MA_KEYWORDS = ("m&a", "acquisition", "merger")
_MARGIN_KEYWORDS = ("margin",)

# trigger -> (adapter, focus) pairs, applied in this order; a later trigger
# naming an adapter already added by an earlier one is skipped (see
# _add_call) rather than duplicated -- one company can fire several
# triggers that all want, say, fmp_get_financial_health.
_ADAPTER_FOCUS_BY_TRIGGER: dict[ExternalResearchTrigger, list[tuple[str, str]]] = {
    ExternalResearchTrigger.NEAR_MATURITY: [
        ("fmp_get_financial_health", "liquidity, leverage, and cash flow ahead of a near-term debt maturity"),
        ("fred_get_rate_signal", "current benchmark lending rates relevant to refinancing this maturity"),
    ],
    ExternalResearchTrigger.HIGH_UTILIZATION: [
        ("fmp_get_financial_health", "liquidity and debt metrics given a highly utilized credit facility"),
        ("fred_get_rate_signal", "current benchmark lending rates relevant to this facility's cost of capital"),
    ],
    ExternalResearchTrigger.COVENANT_THRESHOLD: [
        ("fmp_get_financial_health", "leverage and coverage ratios relative to an on-file covenant threshold"),
    ],
    ExternalResearchTrigger.REFINANCING_OPPORTUNITY: [
        ("fmp_get_valuation", "enterprise value and debt capacity for a refinancing/bond opportunity"),
        ("av_get_earnings_signal", "recent earnings trend relevant to a refinancing/bond opportunity"),
        ("av_get_market_signal", "recent price trend relevant to a refinancing/bond opportunity"),
        ("fred_get_rate_signal", "benchmark rates/spreads relevant to a refinancing/bond opportunity"),
    ],
    ExternalResearchTrigger.MA_OPPORTUNITY: [
        ("fmp_get_valuation", "cash, debt, cash flow, and enterprise value for an M&A opportunity"),
        ("av_get_earnings_signal", "recent earnings trend relevant to an M&A opportunity"),
    ],
    ExternalResearchTrigger.MARGIN_RISK: [
        ("fmp_get_financial_health", "margin trends relevant to a flagged margin risk"),
        ("av_get_earnings_signal", "earnings history relevant to a flagged margin risk"),
    ],
}

_GENERIC_PLAN_CALLS: list[tuple[str, str]] = [
    ("fmp_get_financial_health", "baseline financial health -- no specific internal trigger fired"),
]


def _months_between(earlier: date, later: date) -> float:
    return (later.year - earlier.year) * 12 + (later.month - earlier.month) + (later.day - earlier.day) / 30.4375


def _detect_triggers(context: CompanyResearchContext) -> set[ExternalResearchTrigger]:
    triggers: set[ExternalResearchTrigger] = set()

    for facility in context.facilities:
        if facility.maturity_date is not None:
            months_to_maturity = _months_between(context.as_of_date, facility.maturity_date)
            if 0 <= months_to_maturity <= NEAR_MATURITY_MONTHS:
                triggers.add(ExternalResearchTrigger.NEAR_MATURITY)
        if facility.utilization_pct is not None and facility.utilization_pct >= HIGH_UTILIZATION_PCT:
            triggers.add(ExternalResearchTrigger.HIGH_UTILIZATION)
        if facility.covenant_max_leverage is not None:
            triggers.add(ExternalResearchTrigger.COVENANT_THRESHOLD)

    for deal in context.deals:
        title = deal.deal_title.lower()
        if any(keyword in title for keyword in _REFINANCING_KEYWORDS):
            triggers.add(ExternalResearchTrigger.REFINANCING_OPPORTUNITY)
        if any(keyword in title for keyword in _MA_KEYWORDS):
            triggers.add(ExternalResearchTrigger.MA_OPPORTUNITY)

    for flag in context.risk_flags:
        haystack = f"{flag.flag_type} {flag.description}".lower()
        if any(keyword in haystack for keyword in _MARGIN_KEYWORDS):
            triggers.add(ExternalResearchTrigger.MARGIN_RISK)

    return triggers


def _add_call(calls: list[PlannedAdapterCall], seen: set[str], adapter: str, focus: str, reason: ExternalResearchTrigger) -> None:
    if adapter in seen:
        return
    seen.add(adapter)
    calls.append(PlannedAdapterCall(adapter=adapter, reason=reason, focus=focus))


def build_external_research_plan(
    context: CompanyResearchContext | None,
    *,
    ticker: str,
    as_of_date: date,
) -> ExternalResearchPlan:
    """Builds the plan for one company. `context` is None when internal
    research is disabled for this request (or the company had no internal
    context at all) -- in that case a bounded generic plan is returned
    rather than skipping external research entirely (per the requirement
    that external research must still work with internal research off).
    """

    if context is None:
        calls = [PlannedAdapterCall(adapter=adapter, reason=ExternalResearchTrigger.GENERIC, focus=focus)
                 for adapter, focus in _GENERIC_PLAN_CALLS]
        return ExternalResearchPlan(ticker=ticker, as_of_date=as_of_date, triggers=[], adapter_calls=calls, generic=True)

    triggers = _detect_triggers(context)
    calls: list[PlannedAdapterCall] = []
    seen: set[str] = set()
    # Deterministic order: iterate triggers in the enum's declared order,
    # not set iteration order, so the same context always produces the same
    # plan (sets are unordered in general, and dict/enum declaration order
    # is stable across runs -- this loop relies on the latter, not the former).
    for trigger in ExternalResearchTrigger:
        if trigger not in triggers:
            continue
        for adapter, focus in _ADAPTER_FOCUS_BY_TRIGGER.get(trigger, []):
            _add_call(calls, seen, adapter, focus, trigger)

    if not calls:
        for adapter, focus in _GENERIC_PLAN_CALLS:
            _add_call(calls, seen, adapter, focus, ExternalResearchTrigger.NONE)

    return ExternalResearchPlan(
        ticker=ticker,
        as_of_date=as_of_date,
        triggers=sorted(triggers, key=lambda t: t.value) or [ExternalResearchTrigger.NONE],
        adapter_calls=calls,
        generic=False,
    )

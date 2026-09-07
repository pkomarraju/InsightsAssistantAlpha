"""Curated, namespaced external-data adapters -- what external_data_agent
actually sees, instead of the raw union of every FMP/Alpha Vantage/FRED MCP
tool (agents/orchestrator.py used to build this way; see its own comments).

Five adapters, one per row of the requester's own target tool surface:
  - fmp_get_financial_health: liquidity/leverage/margin ratios and key
    metrics (FMP get_financial_ratios + get_key_metrics).
  - fmp_get_valuation: enterprise value and valuation multiples (FMP
    get_key_metrics's EV-side fields -- the same underlying tool as
    financial_health, different fields extracted, so both adapters are
    cheap to call together without double-fetching raw statements).
  - av_get_market_signal: company profile and recent price action (Alpha
    Vantage company_overview + time_series_daily).
  - av_get_earnings_signal: recent earnings history (Alpha Vantage
    company_earnings).
  - fred_get_rate_signal: a named benchmark/macro series (FRED fred_search
    to resolve a series id, then fred_get_series for its latest observation).

Every adapter, not the model, is responsible for:
  - calling the real underlying MCP tool (see _REAL_TOOL_BY_ADAPTER --
    these names come from actually running each installed package's
    list_tools(), never assumed from a conceptual spec -- see
    mcp_servers/registry.py's module docstring for how each was verified),
  - normalizing units/dates and computing any derived figures (deltas,
    ratios) deterministically here, in Python,
  - excluding anything dated after as_of_date (point-in-time discipline --
    see _within_as_of_date),
  - generating this fact's evidence_code deterministically from normalized,
    immutable fields (_evidence_code) -- the LLM only ever copies one of
    these verbatim; it can never construct its own,
  - reporting a typed ProviderStatus, never silently returning an empty
    list for what was actually an auth/rate-limit/timeout failure -- see
    ProviderStatus's own docstring on why that distinction matters to the
    Synthesizer (a checked-and-clean NO_DATA is a fact; an UNAVAILABLE
    provider is a gap that must become a `limitations` note, not a
    unstated absence).

Each adapter is exposed to the LLM as one LangChain StructuredTool with a
typed (Pydantic) argument schema accepting only public identifiers --
ticker, series id, interval, period, as_of_date -- never a free-text
internal description (see agents/external_research_plan.py's
PlannedAdapterCall.focus, which is the only internal-derived text that ever
reaches this agent, and only as prose in its own prompt, never as a tool
argument).
"""

import asyncio
import json
import logging
from datetime import date, datetime, timezone

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from insights_assistant import mcp_client
from insights_assistant.contracts.api.enums import ExternalProvider, ProviderStatus
from insights_assistant.contracts.workflow.external_research import ExternalEvidenceRecord, ProviderCallResult

logger = logging.getLogger(__name__)

# Real underlying MCP tool name(s) each adapter calls, per provider -- see
# module docstring. Kept as one lookup table so a future registry/package
# change (e.g. swapping which FMP package backs "fmp") only means editing
# this table, never the adapter bodies below.
_REAL_TOOL_BY_ADAPTER = {
    "fmp_get_financial_health": [("fmp", "get_financial_ratios"), ("fmp", "get_key_metrics")],
    "fmp_get_valuation": [("fmp", "get_key_metrics")],
    "av_get_market_signal": [("alpha_vantage", "company_overview"), ("alpha_vantage", "time_series_daily")],
    "av_get_earnings_signal": [("alpha_vantage", "company_earnings")],
    # fred_search exists (and is a real, verified tool name -- see
    # mcp_servers/registry.py's module docstring) but isn't called below:
    # fred_get_rate_signal resolves the common benchmark/macro series it's
    # asked for via a small curated alias map (_KNOWN_SERIES) instead, so a
    # request for "sofr"/"10y_treasury"/"fed_funds" never depends on an
    # LLM-driven search step. A raw FRED series id not in that map is
    # passed straight to fred_get_series (uppercased) rather than searched.
    "fred_get_rate_signal": [("fred", "fred_get_series")],
}

ADAPTER_NAMES = tuple(_REAL_TOOL_BY_ADAPTER)

# Alpha Vantage's free tier returns HTTP 200 with a JSON body carrying one of
# these keys instead of a real payload when it's rate-limited -- verified
# live (see mcp_servers/registry.py's module docstring) -- so this can't be
# detected as an HTTP error the way a real 429 would be; the adapter must
# inspect the body itself.
_AV_RATE_LIMIT_KEYS = ("Information", "Note")


# Must match api/evidence_mapping.py's PREFIX_MAP keys exactly (FMP_/AV_/
# FRED_) -- that module is what classifies an evidence_code's source_agent/
# source_type for every downstream consumer (research_execution.py's
# _build_evidence drops anything it can't classify). Deliberately NOT
# provider.value.upper() (that would produce "ALPHA_VANTAGE_..." for
# ExternalProvider.ALPHA_VANTAGE, which evidence_mapping.py would not
# recognize at all -- silently dropping every Alpha Vantage fact).
_EVIDENCE_CODE_PREFIX = {
    ExternalProvider.FMP: "FMP",
    ExternalProvider.ALPHA_VANTAGE: "AV",
    ExternalProvider.FRED: "FRED",
}


def _evidence_code(provider: ExternalProvider, ticker: str, metric: str, period_end: date | None) -> str:
    """Deterministic, application-generated -- never the LLM's. Unique and
    stable for the same (provider, ticker, metric, period_end): calling
    this adapter again for the same fact reproduces the same code."""

    period_token = period_end.strftime("%Y%m%d") if period_end else "NA"
    metric_token = "".join(ch if ch.isalnum() else "_" for ch in metric.upper())
    return f"{_EVIDENCE_CODE_PREFIX[provider]}_{ticker.upper()}_{metric_token}_{period_token}"


def _within_as_of_date(observed: date | None, as_of_date: date) -> bool:
    """Excludes anything dated after as_of_date -- see module docstring's
    point-in-time discipline. A missing date is NOT treated as "unknown, so
    allow it": the caller must have a real date to cite this fact at all
    (see the module docstring on never promoting a dateless item into
    cited evidence), so this only ever gates on a date that exists."""

    return observed is None or observed <= as_of_date


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _record(
    *, provider: ExternalProvider, ticker: str, metric: str, value: float | str | None, unit: str | None,
    period_end: date | None, source_tool: str, published_at: date | None = None,
    stale: bool = False,
) -> ExternalEvidenceRecord:
    return ExternalEvidenceRecord(
        evidence_code=_evidence_code(provider, ticker, metric, period_end),
        provider=provider, ticker=ticker, metric=metric, value=value, unit=unit,
        period_end=period_end, published_at=published_at, source_tool=source_tool,
        source_locator=f"{provider.value}:{source_tool}:{ticker}", retrieved_at=datetime.now(timezone.utc),
        stale=stale,
    )


async def _call_real_tool(
    provider: str, tool_name: str, arguments: dict, *, as_of_date: str
) -> tuple[ProviderStatus, dict | list | None, str | None]:
    """Calls the real vendor tool (cached, TTL-bound -- see mcp_client.call_tool_cached)
    and classifies the outcome into a ProviderStatus. Never raises -- every
    failure mode (auth, rate limit, timeout, an unparseable/empty response)
    becomes a typed status the caller records, rather than an exception
    that would otherwise look identical to "the tool call itself is broken"
    further up the stack.

    as_of_date is folded into the cache key (never sent to the vendor tool
    itself, which mostly doesn't accept it) so a request for the same
    provider/tool/arguments at a different point in time never reuses a
    response cached for a different as_of_date.
    """

    try:
        raw = await asyncio.wait_for(
            mcp_client.call_tool_cached(provider, tool_name, arguments, cache_key_extra={"as_of_date": as_of_date}),
            timeout=45,
        )
    except asyncio.TimeoutError:
        return ProviderStatus.TIMED_OUT, None, f"{provider}:{tool_name} timed out after 45s"
    except Exception as exc:  # noqa: BLE001 -- classify below, never let a raw vendor exception escape
        message = str(exc)
        lowered = message.lower()
        if "auth" in lowered or "token" in lowered or "unauthorized" in lowered or "api key" in lowered:
            return ProviderStatus.AUTH_ERROR, None, message[:300]
        if "rate limit" in lowered or "429" in lowered or "too many requests" in lowered:
            return ProviderStatus.RATE_LIMITED, None, message[:300]
        return ProviderStatus.UNAVAILABLE, None, message[:300]

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return ProviderStatus.UNAVAILABLE, None, "Non-JSON response from provider"

    if isinstance(parsed, dict) and any(key in parsed for key in _AV_RATE_LIMIT_KEYS):
        note = parsed.get("Information") or parsed.get("Note") or ""
        status = ProviderStatus.RATE_LIMITED if "rate" in note.lower() or "per day" in note.lower() else ProviderStatus.UNAVAILABLE
        return status, None, note[:300]

    if not parsed:
        return ProviderStatus.NO_DATA, parsed, None

    return ProviderStatus.COMPLETED, parsed, None


def _finalize_status(raw_statuses: list[ProviderStatus], evidence: list) -> ProviderStatus:
    """The one place an adapter decides its own final ProviderStatus, from
    the raw status(es) its underlying tool call(s) returned AND whether any
    evidence actually survived normalization/as_of_date filtering.

    Evidence present always means COMPLETED. Otherwise: a genuine failure
    (anything but COMPLETED/NO_DATA) in any raw call wins and is reported,
    since that's a real gap the Synthesizer must see as such -- never
    reported as NO_DATA (which the Synthesizer would treat as objectively
    normal "checked and clean", the wrong story for a call that actually
    timed out or hit an auth error). Otherwise every raw call completed but
    nothing survived to be reported -- which is NO_DATA even when a raw
    call's own JSON payload was technically non-empty (e.g. a FRED
    observation whose date is after as_of_date, or a metric field simply
    absent from an otherwise real response) -- the fact reported to the
    Synthesizer is about what's usable, not about the raw wire payload's
    own emptiness.
    """

    if evidence:
        return ProviderStatus.COMPLETED
    non_trivial = [s for s in raw_statuses if s not in (ProviderStatus.COMPLETED, ProviderStatus.NO_DATA)]
    if non_trivial:
        return non_trivial[0]
    return ProviderStatus.NO_DATA


# --- FMP ---------------------------------------------------------------


class _FmpArgs(BaseModel):
    ticker: str = Field(description="Public ticker symbol, e.g. XOM.")
    as_of_date: str = Field(description="ISO YYYY-MM-DD. Facts dated after this are excluded.")
    period: str = Field(default="annual", description="'annual' or 'quarter'.")


async def fmp_get_financial_health(ticker: str, as_of_date: str, period: str = "annual") -> str:
    as_of = date.fromisoformat(as_of_date)
    ratios_status, ratios, ratios_err = await _call_real_tool("fmp", "get_financial_ratios", {"symbol": ticker, "period": period}, as_of_date=as_of_date)
    metrics_status, metrics, metrics_err = await _call_real_tool("fmp", "get_key_metrics", {"symbol": ticker, "period": period}, as_of_date=as_of_date)

    evidence: list[ExternalEvidenceRecord] = []
    fields = [
        ("currentRatio", "current_ratio", "ratio"), ("quickRatio", "quick_ratio", "ratio"),
        ("debtToEquityRatio", "debt_to_equity", "ratio"), ("grossProfitMargin", "gross_profit_margin", "pct"),
        ("operatingProfitMargin", "operating_profit_margin", "pct"), ("netProfitMargin", "net_profit_margin", "pct"),
    ]
    if ratios_status == ProviderStatus.COMPLETED and isinstance(ratios, list) and ratios:
        row = ratios[0]
        period_end = _parse_date(row.get("date"))
        if _within_as_of_date(period_end, as_of):
            for raw_key, metric, unit in fields:
                if row.get(raw_key) is not None:
                    evidence.append(_record(
                        provider=ExternalProvider.FMP, ticker=ticker, metric=metric, value=row[raw_key],
                        unit=unit, period_end=period_end, source_tool="get_financial_ratios",
                    ))

    if metrics_status == ProviderStatus.COMPLETED and isinstance(metrics, list) and metrics:
        row = metrics[0]
        period_end = _parse_date(row.get("date"))
        if _within_as_of_date(period_end, as_of):
            for raw_key, metric, unit in [
                ("netDebtToEBITDA", "net_debt_to_ebitda", "ratio"),
                ("workingCapital", "working_capital", "usd"),
                ("freeCashFlowYield", "free_cash_flow_yield", "pct"),
            ]:
                if row.get(raw_key) is not None:
                    evidence.append(_record(
                        provider=ExternalProvider.FMP, ticker=ticker, metric=metric, value=row[raw_key],
                        unit=unit, period_end=period_end, source_tool="get_key_metrics",
                    ))

    status = _finalize_status([ratios_status, metrics_status], evidence)
    message = ratios_err or metrics_err if status not in (ProviderStatus.COMPLETED, ProviderStatus.NO_DATA) else None
    result = ProviderCallResult(provider=ExternalProvider.FMP, status=status, evidence=evidence[:10], message=message)
    return result.model_dump_json(by_alias=True)


async def fmp_get_valuation(ticker: str, as_of_date: str, period: str = "annual") -> str:
    as_of = date.fromisoformat(as_of_date)
    metrics_status, metrics, err = await _call_real_tool("fmp", "get_key_metrics", {"symbol": ticker, "period": period}, as_of_date=as_of_date)

    evidence: list[ExternalEvidenceRecord] = []
    if metrics_status == ProviderStatus.COMPLETED and isinstance(metrics, list) and metrics:
        row = metrics[0]
        period_end = _parse_date(row.get("date"))
        if _within_as_of_date(period_end, as_of):
            for raw_key, metric, unit in [
                ("enterpriseValue", "enterprise_value", "usd"), ("evToEBITDA", "ev_to_ebitda", "ratio"),
                ("evToSales", "ev_to_sales", "ratio"), ("marketCap", "market_cap", "usd"),
            ]:
                if row.get(raw_key) is not None:
                    evidence.append(_record(
                        provider=ExternalProvider.FMP, ticker=ticker, metric=metric, value=row[raw_key],
                        unit=unit, period_end=period_end, source_tool="get_key_metrics",
                    ))

    status = _finalize_status([metrics_status], evidence)
    result = ProviderCallResult(provider=ExternalProvider.FMP, status=status, evidence=evidence[:10],
                                 message=err if status not in (ProviderStatus.COMPLETED, ProviderStatus.NO_DATA) else None)
    return result.model_dump_json(by_alias=True)


# --- Alpha Vantage -------------------------------------------------------


async def av_get_market_signal(ticker: str, as_of_date: str) -> str:
    as_of = date.fromisoformat(as_of_date)
    overview_status, overview, overview_err = await _call_real_tool("alpha_vantage", "company_overview", {"symbol": ticker}, as_of_date=as_of_date)
    price_status, price, price_err = await _call_real_tool("alpha_vantage", "time_series_daily", {"symbol": ticker, "outputsize": "compact"}, as_of_date=as_of_date)

    evidence: list[ExternalEvidenceRecord] = []
    if overview_status == ProviderStatus.COMPLETED and isinstance(overview, dict):
        latest_quarter = _parse_date(overview.get("LatestQuarter"))
        for raw_key, metric, unit in [
            ("PERatio", "pe_ratio", "ratio"), ("ProfitMargin", "profit_margin", "pct"),
            ("MarketCapitalization", "market_cap", "usd"),
        ]:
            value = overview.get(raw_key)
            if value not in (None, "None", "-"):
                evidence.append(_record(
                    provider=ExternalProvider.ALPHA_VANTAGE, ticker=ticker, metric=metric, value=value,
                    unit=unit, period_end=latest_quarter, source_tool="company_overview",
                ))

    if price_status == ProviderStatus.COMPLETED and isinstance(price, dict):
        series = price.get("Time Series (Daily)") or {}
        # Most recent trading day not after as_of_date -- never today's date
        # as a substitute, and never a future observation (see module docstring).
        eligible_dates = sorted((d for d in series if _parse_date(d) and _parse_date(d) <= as_of), reverse=True)
        if eligible_dates:
            latest_date_str = eligible_dates[0]
            latest = series[latest_date_str]
            close = latest.get("4. close")
            if close is not None:
                evidence.append(_record(
                    provider=ExternalProvider.ALPHA_VANTAGE, ticker=ticker, metric="close_price",
                    value=float(close), unit="usd_per_share", period_end=_parse_date(latest_date_str),
                    source_tool="time_series_daily",
                    stale=(as_of - _parse_date(latest_date_str)).days > 7,
                ))

    status = _finalize_status([overview_status, price_status], evidence)
    message = overview_err or price_err if status not in (ProviderStatus.COMPLETED, ProviderStatus.NO_DATA) else None
    result = ProviderCallResult(provider=ExternalProvider.ALPHA_VANTAGE, status=status, evidence=evidence[:10], message=message)
    return result.model_dump_json(by_alias=True)


async def av_get_earnings_signal(ticker: str, as_of_date: str) -> str:
    as_of = date.fromisoformat(as_of_date)
    status, payload, err = await _call_real_tool("alpha_vantage", "company_earnings", {"symbol": ticker}, as_of_date=as_of_date)

    evidence: list[ExternalEvidenceRecord] = []
    if status == ProviderStatus.COMPLETED and isinstance(payload, dict):
        quarterly = payload.get("quarterlyEarnings") or []
        eligible = [
            q for q in quarterly
            if _parse_date(q.get("reportedDate")) and _parse_date(q.get("reportedDate")) <= as_of
        ]
        # Only enough history to establish a trend, not the whole series.
        for row in eligible[:4]:
            reported = _parse_date(row.get("reportedDate"))
            fiscal_end = _parse_date(row.get("fiscalDateEnding"))
            if row.get("reportedEPS") not in (None, "None"):
                evidence.append(_record(
                    provider=ExternalProvider.ALPHA_VANTAGE, ticker=ticker, metric="reported_eps",
                    value=row["reportedEPS"], unit="usd_per_share", period_end=fiscal_end,
                    published_at=reported, source_tool="company_earnings",
                ))
            if row.get("surprisePercentage") not in (None, "None"):
                evidence.append(_record(
                    provider=ExternalProvider.ALPHA_VANTAGE, ticker=ticker, metric="eps_surprise_pct",
                    value=row["surprisePercentage"], unit="pct", period_end=fiscal_end,
                    published_at=reported, source_tool="company_earnings",
                ))

    final_status = _finalize_status([status], evidence)
    result = ProviderCallResult(provider=ExternalProvider.ALPHA_VANTAGE, status=final_status, evidence=evidence[:10],
                                 message=err if final_status not in (ProviderStatus.COMPLETED, ProviderStatus.NO_DATA) else None)
    return result.model_dump_json(by_alias=True)


# --- FRED ----------------------------------------------------------------

# A small, curated ticker/context -> FRED series id map for the benchmark
# rates this demo actually needs, rather than trusting the model to invent a
# series id: SOFR (overnight financing) and the 10-year Treasury are the two
# most broadly relevant lending/benchmark references for a corporate credit
# conversation. fred_search (called first) is still used to resolve
# anything not in this map, so a genuinely different series a banker asks
# about isn't blocked -- this map only shortcuts the common case.
_KNOWN_SERIES = {"sofr": "SOFR", "10y_treasury": "DGS10", "fed_funds": "DFF"}


async def fred_get_rate_signal(series: str, as_of_date: str) -> str:
    as_of = date.fromisoformat(as_of_date)
    series_id = _KNOWN_SERIES.get(series.lower(), series.upper())

    obs_status, obs, obs_err = await _call_real_tool(
        "fred", "fred_get_series",
        {"series_id": series_id, "observation_end": as_of.isoformat(), "limit": 5, "sort_order": "desc"},
        as_of_date=as_of_date,
    )

    evidence: list[ExternalEvidenceRecord] = []
    if obs_status == ProviderStatus.COMPLETED and isinstance(obs, dict):
        observations = obs.get("observations") or obs.get("data") or []
        eligible = [o for o in observations if _parse_date(o.get("date")) and _parse_date(o.get("date")) <= as_of]
        if eligible:
            latest = eligible[0]
            value = latest.get("value")
            if value not in (None, "."):
                obs_date = _parse_date(latest["date"])
                evidence.append(_record(
                    provider=ExternalProvider.FRED, ticker=series_id, metric=f"rate_{series_id.lower()}",
                    value=value, unit="pct", period_end=obs_date, source_tool="fred_get_series",
                    stale=(as_of - obs_date).days > 45,
                ))

    status = _finalize_status([obs_status], evidence)
    result = ProviderCallResult(provider=ExternalProvider.FRED, status=status, evidence=evidence[:5],
                                 message=obs_err if status not in (ProviderStatus.COMPLETED, ProviderStatus.NO_DATA) else None)
    return result.model_dump_json(by_alias=True)


def build_external_adapter_tools() -> list[StructuredTool]:
    """The exact, fixed tool surface external_data_agent gets -- five
    hand-named, collision-free tools, never the raw per-provider union
    (agents/orchestrator.py used to merge+dedupe that union; this replaces
    it for external_data_agent specifically)."""

    return [
        StructuredTool.from_function(
            coroutine=fmp_get_financial_health, name="fmp_get_financial_health",
            description="Liquidity, leverage, and margin ratios for a public company (FMP). "
            "Args: ticker, as_of_date (YYYY-MM-DD), period ('annual'|'quarter').",
            args_schema=_FmpArgs,
        ),
        StructuredTool.from_function(
            coroutine=fmp_get_valuation, name="fmp_get_valuation",
            description="Enterprise value and valuation multiples for a public company (FMP). "
            "Args: ticker, as_of_date (YYYY-MM-DD), period ('annual'|'quarter').",
            args_schema=_FmpArgs,
        ),
        StructuredTool.from_function(
            coroutine=av_get_market_signal, name="av_get_market_signal",
            description="Company profile and most recent equity price for a public company (Alpha Vantage). "
            "Args: ticker, as_of_date (YYYY-MM-DD).",
        ),
        StructuredTool.from_function(
            coroutine=av_get_earnings_signal, name="av_get_earnings_signal",
            description="Recent quarterly earnings (EPS, surprise vs. estimate) for a public company "
            "(Alpha Vantage). Args: ticker, as_of_date (YYYY-MM-DD).",
        ),
        StructuredTool.from_function(
            coroutine=fred_get_rate_signal, name="fred_get_rate_signal",
            description="A named benchmark/macro rate's most recent observation (FRED). "
            "Args: series (one of 'sofr', '10y_treasury', 'fed_funds', or a raw FRED series id), "
            "as_of_date (YYYY-MM-DD).",
        ),
    ]

"""Covers agents/external_adapters.py's curated external-data adapters:
deterministic evidence-code generation (never the LLM's), as_of_date /
future-data filtering, provider-status classification (completed/no_data/
unavailable/auth_error/rate_limited/timed_out), the fixed five-tool
namespaced surface, and graceful degradation when one provider fails.
mcp_client.call_tool_cached is always monkeypatched -- these tests never
hit a real network/provider.
"""

import asyncio
import json

import pytest

from insights_assistant.agents import external_adapters
from insights_assistant.contracts.api.enums import ExternalProvider, ProviderStatus


def _fake_call_tool_cached(responses: dict[tuple[str, str], object]):
    """responses maps (server_name, tool_name) -> either a dict/list (JSON
    response) or an Exception instance to raise."""

    async def fake(server_name, tool_name, arguments, *, cache_key_extra=None, ttl_seconds=None):
        key = (server_name, tool_name)
        if key not in responses:
            raise AssertionError(f"unexpected call: {key} {arguments}")
        value = responses[key]
        if isinstance(value, Exception):
            raise value
        return json.dumps(value)

    return fake


class TestEvidenceCodeGeneration:
    def test_matches_evidence_mapping_prefixes_for_all_three_providers(self):
        from insights_assistant.api import evidence_mapping

        for provider in ExternalProvider:
            code = external_adapters._evidence_code(provider, "XOM", "net_debt_to_ebitda", None)
            classified = evidence_mapping.classify(code)
            assert classified == ("external_data_agent", "external"), (
                f"{provider.value} evidence code {code!r} did not classify -- would be silently dropped"
            )

    def test_deterministic_and_stable_for_the_same_inputs(self):
        import datetime

        period = datetime.date(2026, 6, 30)
        code_a = external_adapters._evidence_code(ExternalProvider.FMP, "XOM", "net_debt_to_ebitda", period)
        code_b = external_adapters._evidence_code(ExternalProvider.FMP, "XOM", "net_debt_to_ebitda", period)
        assert code_a == code_b == "FMP_XOM_NET_DEBT_TO_EBITDA_20260630"

    def test_different_metric_or_period_produces_a_different_code(self):
        import datetime

        base = external_adapters._evidence_code(ExternalProvider.FMP, "XOM", "current_ratio", datetime.date(2026, 6, 30))
        other_metric = external_adapters._evidence_code(ExternalProvider.FMP, "XOM", "quick_ratio", datetime.date(2026, 6, 30))
        other_period = external_adapters._evidence_code(ExternalProvider.FMP, "XOM", "current_ratio", datetime.date(2026, 3, 31))
        assert len({base, other_metric, other_period}) == 3


class TestCuratedToolSurface:
    def test_exactly_five_namespaced_collision_free_tools(self):
        tools = external_adapters.build_external_adapter_tools()
        names = [t.name for t in tools]

        assert names == [
            "fmp_get_financial_health", "fmp_get_valuation",
            "av_get_market_signal", "av_get_earnings_signal", "fred_get_rate_signal",
        ]
        assert len(set(names)) == len(names)

    def test_no_tool_accepts_a_free_text_internal_description_argument(self):
        """Every adapter's real parameter surface is public identifiers
        only (ticker/series/as_of_date/period) -- never anything shaped
        like an internal description/note."""
        tools = external_adapters.build_external_adapter_tools()
        for tool in tools:
            schema = tool.args_schema
            fields = getattr(schema, "model_fields", None) or {}
            for name in fields:
                assert "description" not in name.lower() and "note" not in name.lower()


@pytest.mark.asyncio
class TestFmpGetFinancialHealth:
    async def test_extracts_ratios_and_key_metrics_with_matching_evidence_codes(self, monkeypatch):
        monkeypatch.setattr(external_adapters.mcp_client, "call_tool_cached", _fake_call_tool_cached({
            ("fmp", "get_financial_ratios"): [{
                "date": "2025-12-31", "currentRatio": 1.15, "quickRatio": 0.79,
                "debtToEquityRatio": 0.17, "grossProfitMargin": 0.22,
                "operatingProfitMargin": 0.10, "netProfitMargin": 0.09,
            }],
            ("fmp", "get_key_metrics"): [{
                "date": "2025-12-31", "netDebtToEBITDA": 0.48, "workingCapital": 11052000000,
                "freeCashFlowYield": 0.045,
            }],
        }))

        raw = await external_adapters.fmp_get_financial_health("XOM", "2026-09-05")
        result = json.loads(raw)

        assert result["status"] == "completed"
        metrics = {e["metric"] for e in result["evidence"]}
        assert "current_ratio" in metrics
        assert "net_debt_to_ebitda" in metrics
        for item in result["evidence"]:
            assert item["evidenceCode"].startswith("FMP_XOM_")

    async def test_future_dated_period_is_excluded(self, monkeypatch):
        monkeypatch.setattr(external_adapters.mcp_client, "call_tool_cached", _fake_call_tool_cached({
            ("fmp", "get_financial_ratios"): [{"date": "2027-01-01", "currentRatio": 1.15}],
            ("fmp", "get_key_metrics"): [{"date": "2027-01-01", "netDebtToEBITDA": 0.48}],
        }))

        raw = await external_adapters.fmp_get_financial_health("XOM", "2026-09-05")
        result = json.loads(raw)

        assert result["evidence"] == []

    async def test_empty_response_is_no_data_not_an_error(self, monkeypatch):
        monkeypatch.setattr(external_adapters.mcp_client, "call_tool_cached", _fake_call_tool_cached({
            ("fmp", "get_financial_ratios"): [],
            ("fmp", "get_key_metrics"): [],
        }))

        raw = await external_adapters.fmp_get_financial_health("XOM", "2026-09-05")
        result = json.loads(raw)

        assert result["status"] == "no_data"
        assert result["evidence"] == []

    async def test_timeout_is_reported_as_timed_out_not_swallowed(self, monkeypatch):
        async def fake(*_args, **_kwargs):
            raise asyncio.TimeoutError()

        monkeypatch.setattr(external_adapters.mcp_client, "call_tool_cached", fake)

        raw = await external_adapters.fmp_get_financial_health("XOM", "2026-09-05")
        result = json.loads(raw)

        assert result["status"] == "timed_out"
        assert result["evidence"] == []
        assert result["message"]

    async def test_auth_error_is_classified_distinctly_from_generic_unavailable(self, monkeypatch):
        monkeypatch.setattr(external_adapters.mcp_client, "call_tool_cached", _fake_call_tool_cached({
            ("fmp", "get_financial_ratios"): RuntimeError("Invalid API key / unauthorized"),
            ("fmp", "get_key_metrics"): RuntimeError("Invalid API key / unauthorized"),
        }))

        raw = await external_adapters.fmp_get_financial_health("XOM", "2026-09-05")
        result = json.loads(raw)

        assert result["status"] == "auth_error"

    async def test_one_of_two_underlying_calls_failing_still_returns_the_other(self, monkeypatch):
        """fmp_get_financial_health calls two real tools; one failing must
        not discard evidence the other one successfully returned."""
        monkeypatch.setattr(external_adapters.mcp_client, "call_tool_cached", _fake_call_tool_cached({
            ("fmp", "get_financial_ratios"): RuntimeError("connection reset"),
            ("fmp", "get_key_metrics"): [{"date": "2025-12-31", "netDebtToEBITDA": 0.48}],
        }))

        raw = await external_adapters.fmp_get_financial_health("XOM", "2026-09-05")
        result = json.loads(raw)

        assert result["status"] == "completed"
        assert any(e["metric"] == "net_debt_to_ebitda" for e in result["evidence"])


@pytest.mark.asyncio
class TestAlphaVantageAdapters:
    async def test_rate_limit_body_is_detected_and_classified(self, monkeypatch):
        """Alpha Vantage's free tier returns HTTP 200 with an 'Information'
        key instead of a real payload when rate-limited -- verified live
        (see mcp_servers/registry.py) -- so this must be detected from the
        body, not from a transport-level error."""
        monkeypatch.setattr(external_adapters.mcp_client, "call_tool_cached", _fake_call_tool_cached({
            ("alpha_vantage", "company_overview"): {
                "Information": "Thank you for using Alpha Vantage! ... 25 requests per day"
            },
            ("alpha_vantage", "time_series_daily"): {
                "Information": "Thank you for using Alpha Vantage! ... 25 requests per day"
            },
        }))

        raw = await external_adapters.av_get_market_signal("XOM", "2026-09-05")
        result = json.loads(raw)

        assert result["status"] == "rate_limited"
        assert result["evidence"] == []

    async def test_market_signal_picks_the_most_recent_price_not_after_as_of_date(self, monkeypatch):
        monkeypatch.setattr(external_adapters.mcp_client, "call_tool_cached", _fake_call_tool_cached({
            ("alpha_vantage", "company_overview"): {"PERatio": "17.9", "LatestQuarter": "2025-12-31"},
            ("alpha_vantage", "time_series_daily"): {
                "Time Series (Daily)": {
                    "2026-09-10": {"4. close": "999.99"},  # after as_of_date -- must be excluded
                    "2026-09-04": {"4. close": "111.50"},
                    "2026-09-03": {"4. close": "110.00"},
                }
            },
        }))

        raw = await external_adapters.av_get_market_signal("XOM", "2026-09-05")
        result = json.loads(raw)

        price_items = [e for e in result["evidence"] if e["metric"] == "close_price"]
        assert len(price_items) == 1
        assert price_items[0]["value"] == 111.50
        assert price_items[0]["periodEnd"] == "2026-09-04"

    async def test_earnings_signal_excludes_reports_published_after_as_of_date(self, monkeypatch):
        monkeypatch.setattr(external_adapters.mcp_client, "call_tool_cached", _fake_call_tool_cached({
            ("alpha_vantage", "company_earnings"): {
                "quarterlyEarnings": [
                    {"fiscalDateEnding": "2026-09-30", "reportedDate": "2026-10-15", "reportedEPS": "2.10", "surprisePercentage": "3.1"},
                    {"fiscalDateEnding": "2026-06-30", "reportedDate": "2026-07-30", "reportedEPS": "1.95", "surprisePercentage": "1.2"},
                ]
            },
        }))

        raw = await external_adapters.av_get_earnings_signal("XOM", "2026-09-05")
        result = json.loads(raw)

        reported_dates = {e["publishedAt"] for e in result["evidence"]}
        assert "2026-10-15" not in reported_dates
        assert "2026-07-30" in reported_dates


@pytest.mark.asyncio
class TestFredRateSignal:
    async def test_known_series_alias_resolves_to_real_series_id(self, monkeypatch):
        monkeypatch.setattr(external_adapters.mcp_client, "call_tool_cached", _fake_call_tool_cached({
            ("fred", "fred_get_series"): {
                "observations": [{"date": "2026-09-01", "value": "5.33"}],
            },
        }))

        raw = await external_adapters.fred_get_rate_signal("sofr", "2026-09-05")
        result = json.loads(raw)

        assert result["status"] == "completed"
        assert result["evidence"][0]["ticker"] == "SOFR"
        assert result["evidence"][0]["value"] == "5.33"

    async def test_missing_value_marker_is_not_reported_as_evidence(self, monkeypatch):
        monkeypatch.setattr(external_adapters.mcp_client, "call_tool_cached", _fake_call_tool_cached({
            ("fred", "fred_get_series"): {"observations": [{"date": "2026-09-01", "value": "."}]},
        }))

        raw = await external_adapters.fred_get_rate_signal("sofr", "2026-09-05")
        result = json.loads(raw)

        assert result["evidence"] == []
        assert result["status"] == "no_data"

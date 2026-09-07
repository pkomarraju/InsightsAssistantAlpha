"""Covers mcp_servers/internal_data_server.py's get_company_research_context /
build_company_research_context: new-schema (target_companies/
bank_credit_exposures/crm_deal_pipeline/internal_risk_flags) resolution, the
legacy-schema fallback, an empty facilities/deals/risk_flags result being
valid (not an error), and resolve_ticker_for_company_code. A small fake
Supabase query builder stands in for the real client -- these tests never
hit the network.
"""

import json

import pytest

import insights_assistant.mcp_servers.internal_data_server as server_module


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, rows):
        self._rows = list(rows)

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, column, value):
        self._rows = [r for r in self._rows if r.get(column) == value]
        return self

    def lte(self, column, value):
        self._rows = [r for r in self._rows if r.get(column) is not None and r[column] <= value]
        return self

    def order(self, column, desc=False):
        self._rows = sorted(self._rows, key=lambda r: r.get(column) or "", reverse=desc)
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def ilike(self, column, pattern):
        needle = pattern.strip("%").lower()
        self._rows = [r for r in self._rows if needle in str(r.get(column, "")).lower()]
        return self

    def or_(self, expression):
        conditions = [c.split(".", 2) for c in expression.split(",")]
        matched = []
        for row in self._rows:
            for column, op, value in conditions:
                cell = row.get(column)
                if cell is None:
                    continue
                if op == "eq" and str(cell).upper() == str(value).upper():
                    matched.append(row)
                    break
                if op == "ilike" and value.strip("%").lower() in str(cell).lower():
                    matched.append(row)
                    break
        self._rows = matched
        return self

    def execute(self):
        return _FakeResult(self._rows)


class _FakeClient:
    def __init__(self, tables: dict[str, list[dict]]):
        self._tables = tables

    def table(self, name):
        return _FakeQuery(self._tables.get(name, []))


XOM_TARGET_COMPANY = {
    "id": "22222222-2222-2222-2222-222222222222",
    "ticker": "XOM",
    "name": "Exxon Mobil",
    "industry": "Oil & Gas",
    "current_status": "At risk",
    "internal_coverage_lead": "Mark Ramirez (Energy Group)",
    "company_code": "CLI_006",
}

XOM_EXPOSURE = {
    "id": "aaaaaaaa-0000-0000-0000-000000000001",
    "company_id": "22222222-2222-2222-2222-222222222222",
    "facility_type": "Term Loan B",
    "committed_amount_usd": 850000000.00,
    "drawn_amount_usd": 850000000.00,
    "interest_spread_bps": 240,
    "benchmark_index": "SOFR",
    "covenant_max_leverage": 3.25,
    "evidence_code": "EXP_XOM_AAAAAAAA",
    "as_of_date": "2026-07-01",
    "maturity_date": "2026-11-15",
}

XOM_DEAL = {
    "id": "bbbbbbbb-0000-0000-0000-000000000001",
    "company_id": "22222222-2222-2222-2222-222222222222",
    "deal_title": "Carbon-Capture Project Refinancing Bond",
    "potential_fee_usd": 4200000.00,
    "stage": "Pitching",
    "probability": 0.40,
    "target_close_date": "2026-10-31",
    "evidence_code": "DEAL_XOM_BBBBBBBB",
}

XOM_RISK_FLAG = {
    "id": "cccccccc-0000-0000-0000-000000000001",
    "company_id": "22222222-2222-2222-2222-222222222222",
    "flag_type": "Maturity Wall Imminence",
    "severity": "Critical",
    "description": "$850M Term Loan B matures in Nov 2026; sustained oil volatility creates underwriting spread risk.",
    "reported_date": "2026-08-01",
    "evidence_code": "RISKFLAG_XOM_CCCCCCCC",
}

AAPL_TARGET_COMPANY = {
    "id": "33333333-3333-3333-3333-333333333333",
    "ticker": "AAPL",
    "name": "Apple",
    "industry": "Consumer Electronics",
    "current_status": "Strong",
    "internal_coverage_lead": "Sarah Jenkins (TMT Group)",
    "company_code": "CLI_003",
}

AAPL_EXPOSURE = {
    "id": "aaaaaaaa-0000-0000-0000-000000000002",
    "company_id": "33333333-3333-3333-3333-333333333333",
    "facility_type": "Revolving Credit",
    "committed_amount_usd": 750000000.00,
    "drawn_amount_usd": 50000000.00,
    "interest_spread_bps": 75,
    "benchmark_index": "SOFR",
    "covenant_max_leverage": 2.00,
    "evidence_code": "EXP_AAPL_AAAAAAAB",
    "as_of_date": "2026-07-01",
    "maturity_date": "2029-03-31",
}


def _fake_client_with(tables: dict[str, list[dict]]):
    return lambda: _FakeClient(tables)


class TestNewSchemaResolution:
    def test_resolves_by_ticker_and_returns_facilities_deals_risk_flags(self, monkeypatch):
        monkeypatch.setattr(server_module, "_client", _fake_client_with({
            "target_companies": [XOM_TARGET_COMPANY],
            "bank_credit_exposures": [XOM_EXPOSURE],
            "crm_deal_pipeline": [XOM_DEAL],
            "internal_risk_flags": [XOM_RISK_FLAG],
        }))

        context = server_module.build_company_research_context("XOM", "2026-09-05")

        assert context.source == "new_schema"
        assert context.company_code == "CLI_006"
        assert context.ticker == "XOM"
        assert len(context.facilities) == 1
        assert len(context.deals) == 1
        assert len(context.risk_flags) == 1

    def test_resolves_by_company_code_too(self, monkeypatch):
        monkeypatch.setattr(server_module, "_client", _fake_client_with({
            "target_companies": [XOM_TARGET_COMPANY],
            "bank_credit_exposures": [],
            "crm_deal_pipeline": [],
            "internal_risk_flags": [],
        }))

        context = server_module.build_company_research_context("CLI_006", "2026-09-05")
        assert context.ticker == "XOM"

    def test_computes_utilization_pct(self, monkeypatch):
        monkeypatch.setattr(server_module, "_client", _fake_client_with({
            "target_companies": [XOM_TARGET_COMPANY],
            "bank_credit_exposures": [XOM_EXPOSURE],
            "crm_deal_pipeline": [],
            "internal_risk_flags": [],
        }))

        context = server_module.build_company_research_context("XOM", "2026-09-05")
        assert context.facilities[0].utilization_pct == 100.0
        assert context.facilities[0].benchmark_index == "SOFR"
        assert context.facilities[0].evidence_code == "EXP_XOM_AAAAAAAA"

    def test_low_utilization_facility_computed_correctly(self, monkeypatch):
        monkeypatch.setattr(server_module, "_client", _fake_client_with({
            "target_companies": [AAPL_TARGET_COMPANY],
            "bank_credit_exposures": [AAPL_EXPOSURE],
            "crm_deal_pipeline": [],
            "internal_risk_flags": [],
        }))

        context = server_module.build_company_research_context("AAPL", "2026-09-05")
        assert context.facilities[0].utilization_pct == pytest.approx(6.7, abs=0.1)

    def test_empty_facilities_deals_risk_flags_is_valid_not_an_error(self, monkeypatch):
        """A found company with genuinely nothing in any of the three child
        tables must return empty lists, never raise."""
        monkeypatch.setattr(server_module, "_client", _fake_client_with({
            "target_companies": [AAPL_TARGET_COMPANY],
            "bank_credit_exposures": [],
            "crm_deal_pipeline": [],
            "internal_risk_flags": [],
        }))

        context = server_module.build_company_research_context("AAPL", "2026-09-05")
        assert context.facilities == []
        assert context.deals == []
        assert context.risk_flags == []
        assert context.source == "new_schema"

    def test_unknown_identifier_in_new_schema_falls_back_and_eventually_raises(self, monkeypatch):
        """No match in target_companies AND no match in the legacy
        company_master either -- a genuine not-found, distinct from "found
        but empty"."""
        monkeypatch.setattr(server_module, "_client", _fake_client_with({
            "target_companies": [],
            "company_master": [],
        }))

        with pytest.raises(ValueError, match="No company found"):
            server_module.build_company_research_context("NOPE", "2026-09-05")

    def test_as_of_date_excludes_risk_flags_reported_after_it(self, monkeypatch):
        monkeypatch.setattr(server_module, "_client", _fake_client_with({
            "target_companies": [XOM_TARGET_COMPANY],
            "bank_credit_exposures": [],
            "crm_deal_pipeline": [],
            "internal_risk_flags": [XOM_RISK_FLAG],  # reported_date 2026-08-01
        }))

        context = server_module.build_company_research_context("XOM", "2026-07-01")
        assert context.risk_flags == []


class TestLegacySchemaFallback:
    def test_falls_back_to_legacy_tables_when_not_in_new_schema(self, monkeypatch):
        legacy_company = {
            "company_id": "legacy-uuid-1", "company_name": "Amazon", "ticker": "AMZN",
            "relationship_tier": "tier_1", "company_code": "CLI_002",
        }
        monkeypatch.setattr(server_module, "_client", _fake_client_with({
            "target_companies": [],
            "company_master": [legacy_company],
            "relationship_snapshot": [{
                "company_id": "legacy-uuid-1", "relationship_status": "at_risk", "relationship_manager": "Marcus Ibe",
            }],
            "risk_assessment": [],
            "opportunities": [],
        }))

        context = server_module.build_company_research_context("AMZN", "2026-09-05")

        assert context.source == "legacy_schema"
        assert context.ticker == "AMZN"
        assert context.coverage_lead == "Marcus Ibe"
        assert context.status == "at_risk"
        assert context.facilities == []


class TestResolveTickerForCompanyCode:
    def test_returns_ticker_when_found(self, monkeypatch):
        monkeypatch.setattr(server_module, "_client", _fake_client_with({
            "company_master": [{"company_code": "CLI_006", "ticker": "XOM"}],
        }))
        assert server_module.resolve_ticker_for_company_code("CLI_006") == "XOM"

    def test_returns_none_when_not_found(self, monkeypatch):
        monkeypatch.setattr(server_module, "_client", _fake_client_with({"company_master": []}))
        assert server_module.resolve_ticker_for_company_code("CLI_999") is None

    def test_returns_none_on_lookup_failure_rather_than_raising(self, monkeypatch):
        def _raise():
            raise RuntimeError("network down")
        monkeypatch.setattr(server_module, "_client", _raise)
        assert server_module.resolve_ticker_for_company_code("CLI_006") is None


def test_mcp_tool_returns_valid_json_matching_the_typed_context(monkeypatch):
    monkeypatch.setattr(server_module, "_client", _fake_client_with({
        "target_companies": [XOM_TARGET_COMPANY],
        "bank_credit_exposures": [XOM_EXPOSURE],
        "crm_deal_pipeline": [XOM_DEAL],
        "internal_risk_flags": [XOM_RISK_FLAG],
    }))

    raw = server_module.get_company_research_context("XOM", "2026-09-05")
    payload = json.loads(raw)

    assert payload["companyCode"] == "CLI_006"
    assert payload["ticker"] == "XOM"
    assert len(payload["facilities"]) == 1
    assert payload["facilities"][0]["evidenceCode"] == "EXP_XOM_AAAAAAAA"
    assert len(payload["deals"]) == 1
    assert len(payload["riskFlags"]) == 1

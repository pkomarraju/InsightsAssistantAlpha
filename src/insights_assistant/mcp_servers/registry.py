"""Which MCP servers exist and how to reach them. Read by mcp_client.py
(call_tool/list_tools) and, indirectly, by agents/orchestrator.py's
SPECIALIST_SERVERS, which says which of these back each specialist.

fmp/alpha_vantage/fred together replace the single "edgar" entry this used
to have (SEC EDGAR filings) -- external_data_agent now answers from
pre-calculated ratios/financial statements (FMP), company overviews/price
history/earnings (Alpha Vantage), and macro/benchmark rates (FRED) instead
of raw filings. All three are npx/uvx-launched local subprocesses (stdio
transport), unlike the old edgar entry, which was a remote streamable_http
endpoint.

API keys are read from the environment (see .env) at import time, never
hardcoded here -- this module is safe to have open in an editor or paste
into a bug report.

Every package/version choice below was verified live against the real
registry (`npx <pkg> --help` / an actual MCP list_tools() handshake), not
assumed from the requester's own config, because two of the three
originally-requested packages turned out not to work as given:

- fmp: the originally-requested "financial-modeling-prep-mcp-server" package
  has NO stdio mode at all -- `npx ... --fmp-token=...` always starts a
  local HTTP server (default port 8080) and writes plain console logs to
  stdout, which corrupts the stdio JSON-RPC stream mcp.Client expects.
  "@houtini/fmp-mcp" is a genuinely stdio-native alternative -- verified
  live (26 real tools: get_income_statement, get_balance_sheet,
  get_financial_ratios, get_key_metrics [FMP's ratios/enterprise-value-style
  data], get_cash_flow, ...) -- and reads its key via FMP_API_KEY in `env`
  rather than a CLI arg, so (unlike the old package) the key never appears
  in this process's argv/`ps` output either.
- alpha_vantage: the originally-requested "alpha-vantage-mcp" package name
  doesn't exist on PyPI; the real one is "alphavantage-mcp" (verified via
  its own README/PyPI page). It also has two live upstream bugs as
  currently published: it's missing a declared `python-dotenv` dependency
  (crashes on import without `--with python-dotenv`), and it calls a
  `Server.list_prompts()` method the `mcp` Python SDK removed at some point
  after this package was last published against it (needs an older `mcp`
  pinned into its ephemeral uv environment via `--with "mcp<2.0"`). Both
  workarounds are verified live (112 real tools: company_overview,
  time_series_daily, company_earnings, treasury_yield, federal_funds_rate,
  ...) -- note these are the real tool names; the requester's
  COMPANY_OVERVIEW/TIME_SERIES_DAILY/EARNINGS were the right *datasets*,
  just not this package's actual (lowercase) tool names.
- fred: "fred-mcp-server" and FRED_API_KEY are both correct as given
  (verified via the package's own README and npm metadata) and start
  correctly when run directly -- but every live handshake attempt during
  verification failed ("Connection closed"), and the placeholder key value
  this repo currently has in .env (a-through-z + 1-6, not a real FRED key
  shape) is the most likely reason: get a real key at
  https://fred.stlouisfed.org/docs/api/api_key.html and re-verify before
  relying on this one.
"""

import os

MCP_SERVERS = {
    "fmp": {
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@houtini/fmp-mcp"],
        "env": {"FMP_API_KEY": os.environ.get("FMP_API_KEY", "")},
    },
    "alpha_vantage": {
        "transport": "stdio",
        "command": "uvx",
        # --with python-dotenv: alphavantage-mcp imports dotenv but doesn't
        # declare it as a dependency (upstream bug, verified live).
        # --with "mcp<2.0": alphavantage-mcp calls Server.list_prompts(),
        # which mcp>=2.0 (this project's own pin) removed (upstream bug,
        # verified live) -- pinning an older mcp only inside this package's
        # own ephemeral uvx environment, never affecting this project's venv.
        "args": ["--with", "python-dotenv", "--with", "mcp<2.0", "alphavantage-mcp"],
        "env": {"ALPHAVANTAGE_API_KEY": os.environ.get("ALPHAVANTAGE_API_KEY", "")},
    },
    "fred": {
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "fred-mcp-server"],
        "env": {"FRED_API_KEY": os.environ.get("FRED_API_KEY", "")},
    },
    "internal_data": {
        "transport": "stdio",
        "command": "python",
        "args": ["-m", "insights_assistant.mcp_servers.internal_data_server"],
    },
    "relationship_notes": {
        "transport": "stdio",
        "command": "python",
        "args": ["-m", "insights_assistant.mcp_servers.relationship_notes_server"],
    },
}

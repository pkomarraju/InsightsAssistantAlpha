import asyncio
import json
import os
import time
from typing import Any

import mcp
from langchain_core.tools import StructuredTool
from mcp.client.stdio import stdio_client

from insights_assistant.mcp_servers.registry import MCP_SERVERS

# Prototype session cache.  The API currently has no authenticated user/session
# concept, so a "session" is the lifetime of this Python server process.  Keep
# external MCP results here while leaving internal and relationship-note tools
# uncached so changes to bank data are visible on the next request.
#
# TTL-based, not unlimited-process-lifetime: a provider's own data changes
# (a new filing, a new price, a revised rate) on its own schedule, so a cache
# entry that outlives the whole process risks silently serving stale figures
# for the rest of a long-running server's life. Each entry now carries its
# own expiry; _cache_get evicts it (rather than returning it) once expired.
_RESULT_CACHE: dict[str, tuple[str, float]] = {}
_IN_FLIGHT: dict[str, asyncio.Task[str]] = {}
_TOOL_DEFINITION_CACHE: dict[str, list[mcp.Tool]] = {}
_TOOL_DEFINITION_IN_FLIGHT: dict[str, asyncio.Task[list[mcp.Tool]]] = {}

# INSIGHTS_EXTERNAL_MAX_RESULT_CHARS is the current name -- renamed from
# INSIGHTS_EDGAR_MAX_RESULT_CHARS now that this bounds any external-data
# server's response, not only the old EDGAR one. The old name is still read
# as a fallback so an existing deployment's env config keeps working
# unchanged; a value set under the new name always wins.
EXTERNAL_MAX_RESULT_CHARS = int(
    os.environ.get("INSIGHTS_EXTERNAL_MAX_RESULT_CHARS")
    or os.environ.get("INSIGHTS_EDGAR_MAX_RESULT_CHARS")
    or 12_000
)
# Backward-compatible alias -- some callers/tests may still reference the old
# name directly.
EDGAR_MAX_RESULT_CHARS = EXTERNAL_MAX_RESULT_CHARS

RESULT_CACHE_TTL_SECONDS = float(os.environ.get("INSIGHTS_EXTERNAL_CACHE_TTL_SECONDS") or 900)

# Bounded retry/backoff for transient provider errors (agents/external_adapters.py
# separately classifies AUTH_ERROR/RATE_LIMITED as non-retryable there; this
# layer only retries a raw connection/transport failure, which is where a
# genuinely transient blip -- a cold npx/uvx start racing the client's first
# request, a dropped pipe -- actually shows up).
_TRANSIENT_RETRY_ATTEMPTS = int(os.environ.get("INSIGHTS_EXTERNAL_RETRY_ATTEMPTS") or 2)
_TRANSIENT_RETRY_BACKOFF_SECONDS = float(os.environ.get("INSIGHTS_EXTERNAL_RETRY_BACKOFF_SECONDS") or 1.5)

# The external_data_agent's servers (agents/orchestrator.py's
# SPECIALIST_SERVERS) -- the only ones whose raw responses are large/public
# enough to have ever needed bounding. As of agents/external_adapters.py,
# nothing calls call_tool for these three without immediately extracting a
# small, structural subset of fields (see that module's own docstring) --
# so character-slicing a possibly-still-oversized raw response is no longer
# the active safety net it once was; it's kept only as a last-resort
# guard against something calling call_tool directly and getting an
# unexpectedly huge response, and it slices on the *cached* value, never
# altering what a caller that skips the cache receives.
_BOUNDED_RESULT_SERVERS = frozenset({"fmp", "alpha_vantage", "fred"})


def _bound_external_result(server_name: str, result: str) -> str:
    """Last-resort size guard before caching -- see _BOUNDED_RESULT_SERVERS.
    Structural limiting (top-N periods/fields, top-N evidence items) in
    agents/external_adapters.py is what actually keeps a normal response
    small; this only protects against an abnormally large one slipping
    through raw. Never applied to what a direct call_tool() caller receives
    live -- only to the copy this module caches for reuse.
    """

    if server_name not in _BOUNDED_RESULT_SERVERS or len(result) <= EXTERNAL_MAX_RESULT_CHARS:
        return result
    omitted = len(result) - EXTERNAL_MAX_RESULT_CHARS
    return (
        result[:EXTERNAL_MAX_RESULT_CHARS]
        + f"\n\n[{server_name} response bounded for prototype: {omitted:,} additional characters omitted.]"
    )


def _cache_key(server_name: str, tool_name: str, arguments: dict[str, Any], extra: dict[str, Any] | None = None) -> str:
    payload: dict[str, Any] = dict(arguments)
    if extra:
        # Namespaced so it can never collide with a real argument name.
        payload["__cache_key_extra__"] = extra
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return f"{server_name}:{tool_name}:{normalized}"


def _cache_get(key: str) -> str | None:
    entry = _RESULT_CACHE.get(key)
    if entry is None:
        return None
    value, expires_at = entry
    if time.monotonic() >= expires_at:
        _RESULT_CACHE.pop(key, None)
        return None
    return value


def _cache_set(key: str, value: str, ttl_seconds: float) -> None:
    _RESULT_CACHE[key] = (value, time.monotonic() + ttl_seconds)


def clear_result_cache() -> None:
    """Clear cached external results (primarily useful for tests and local demos)."""

    _RESULT_CACHE.clear()
    _TOOL_DEFINITION_CACHE.clear()
    for task in _IN_FLIGHT.values():
        task.cancel()
    for task in _TOOL_DEFINITION_IN_FLIGHT.values():
        task.cancel()
    _IN_FLIGHT.clear()
    _TOOL_DEFINITION_IN_FLIGHT.clear()


def _transport(config: dict[str, Any]):
    if config["transport"] == "streamable_http":
        return config["url"]
    if config["transport"] == "stdio":
        # env, when given, is merged with (not a replacement for) a safe
        # default environment stdio_client already provides (PATH/HOME/etc,
        # via mcp.client.stdio.get_default_environment()) -- so passing just
        # the one or two secret env vars a server needs (fmp/alpha_vantage/
        # fred in mcp_servers/registry.py) never breaks the child process's
        # ability to find npx/uvx on PATH.
        params = mcp.StdioServerParameters(
            command=config["command"], args=config["args"], env=config.get("env")
        )
        return stdio_client(params)
    raise ValueError(f"Unsupported transport: {config['transport']}")


# --- Connection lifecycle: one subprocess per call, deliberately ----------
#
# call_tool below opens a fresh `async with mcp.Client(...)` for every
# invocation rather than holding one long-lived connection per server and
# reusing it across calls/requests. Considered and declined for this pass:
# the mcp SDK's Client/ClientSession are async context managers with no
# documented contract for safe concurrent use by multiple unrelated callers
# sharing one instance (this app dispatches many companies/sources
# concurrently -- see agents/research_execution.py's RESEARCH_CONCURRENCY),
# and a stdio-backed connection's other half is a live subprocess whose
# failure/restart semantics under concurrent access aren't documented
# either. Building a per-server connection pool with its own health-check/
# reconnect logic is a real, separable piece of work, not a one-line change
# -- doing it un-reviewed here risked exactly the kind of silent
# cross-request interference or leaked-subprocess bug this prototype can't
# easily catch in tests. Deferred; the actual per-call cost this avoids
# (a cold npx/uvx subprocess start) is mitigated instead by the result cache
# above, which already makes a repeated call within its TTL free regardless
# of connection reuse.


async def call_tool(server_name: str, tool_name: str, arguments: dict[str, Any]) -> str:
    last_exc: Exception | None = None
    for attempt in range(_TRANSIENT_RETRY_ATTEMPTS + 1):
        try:
            async with mcp.Client(_transport(MCP_SERVERS[server_name])) as client:
                result = await client.call_tool(tool_name, arguments)
                text = "\n".join(block.text for block in result.content if hasattr(block, "text"))
                return _bound_external_result(server_name, text)
        except Exception as exc:  # noqa: BLE001 -- retried transport/connection failures only
            last_exc = exc
            if attempt < _TRANSIENT_RETRY_ATTEMPTS:
                await asyncio.sleep(_TRANSIENT_RETRY_BACKOFF_SECONDS * (attempt + 1))
                continue
            raise
    raise last_exc  # pragma: no cover -- loop always returns or raises above


async def call_tool_cached(
    server_name: str,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    cache_key_extra: dict[str, Any] | None = None,
    ttl_seconds: float | None = None,
) -> str:
    """Like call_tool, but result-cached with a TTL (default
    RESULT_CACHE_TTL_SECONDS) and in-flight-request coalescing. Used by
    agents/external_adapters.py, whose curated adapters call this directly
    rather than going through the LLM-facing _make_tool wrapper below (which
    still exists for internal_data_agent/relationship_notes_agent's raw,
    single-server tool loading).

    cache_key_extra folds additional values (e.g. an as_of_date the
    underlying vendor tool itself doesn't take as an argument) into the
    cache key without sending them to the tool call -- so a request for the
    same provider/tool/arguments but a different as_of_date is never served
    a cached response computed for a different point in time, even though
    the actual vendor arguments are identical.
    """

    key = _cache_key(server_name, tool_name, arguments, cache_key_extra)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    task = _IN_FLIGHT.get(key)
    if task is None:
        task = asyncio.create_task(call_tool(server_name, tool_name, arguments))
        _IN_FLIGHT[key] = task
    try:
        result = await task
    finally:
        if _IN_FLIGHT.get(key) is task:
            _IN_FLIGHT.pop(key, None)
    _cache_set(key, result, ttl_seconds if ttl_seconds is not None else RESULT_CACHE_TTL_SECONDS)
    return result


async def _list_tools(server_name: str) -> list[mcp.Tool]:
    async with mcp.Client(_transport(MCP_SERVERS[server_name])) as client:
        return (await client.list_tools()).tools


async def _load_tool_definitions(server_name: str, *, cache: bool) -> list[mcp.Tool]:
    if not cache:
        return await _list_tools(server_name)
    if server_name in _TOOL_DEFINITION_CACHE:
        return _TOOL_DEFINITION_CACHE[server_name]

    task = _TOOL_DEFINITION_IN_FLIGHT.get(server_name)
    if task is None:
        task = asyncio.create_task(_list_tools(server_name))
        _TOOL_DEFINITION_IN_FLIGHT[server_name] = task
    try:
        tools = await task
    finally:
        if _TOOL_DEFINITION_IN_FLIGHT.get(server_name) is task:
            _TOOL_DEFINITION_IN_FLIGHT.pop(server_name, None)
    _TOOL_DEFINITION_CACHE[server_name] = tools
    return tools


def _make_tool(server_name: str, tool: mcp.Tool, *, cache_results: bool = False) -> StructuredTool:
    """Still used for internal_data_agent/relationship_notes_agent's raw,
    single-server tool loading (agents/orchestrator.py's
    _load_specialist_tools). external_data_agent no longer goes through
    this at all -- see agents/external_adapters.py, whose curated adapters
    call call_tool_cached directly instead of being auto-wrapped from a raw
    tool catalog.
    """

    async def coroutine(**kwargs: Any) -> str:
        if not cache_results:
            return await call_tool(server_name, tool.name, kwargs)
        return await call_tool_cached(server_name, tool.name, kwargs)

    return StructuredTool.from_function(
        coroutine=coroutine,
        name=tool.name,
        description=tool.description or "",
        args_schema=tool.input_schema or {"type": "object", "properties": {}},
    )


async def load_tools(server_name: str, *, cache_results: bool = False) -> list[StructuredTool]:
    # For cached external sources, cache the server's tool catalog as well as
    # tool results. Rebuilding an agent can then be completely network-free
    # when all required results are already present.
    tools = await _load_tool_definitions(server_name, cache=cache_results)
    return [_make_tool(server_name, tool, cache_results=cache_results) for tool in tools]

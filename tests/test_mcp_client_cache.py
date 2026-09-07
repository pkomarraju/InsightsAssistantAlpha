import asyncio

import mcp
import pytest

from insights_assistant import mcp_client


def _tool():
    return mcp.Tool(
        name="filings",
        description="Fetch filings",
        inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}}},
    )


@pytest.fixture(autouse=True)
def empty_cache():
    mcp_client.clear_result_cache()
    yield
    mcp_client.clear_result_cache()


def test_external_result_is_bounded_before_caching(monkeypatch):
    monkeypatch.setattr(mcp_client, "EXTERNAL_MAX_RESULT_CHARS", 12)

    bounded = mcp_client._bound_external_result("fmp", "abcdefghijklmnopqrstuvwxyz")

    assert bounded.startswith("abcdefghijkl")
    assert "14 additional characters omitted" in bounded
    assert mcp_client._bound_external_result("internal_data", "abcdefghijklmnopqrstuvwxyz") == "abcdefghijklmnopqrstuvwxyz"


@pytest.mark.asyncio
async def test_cached_tool_reuses_successful_result(monkeypatch):
    calls = 0

    async def fake_call_tool(server_name, tool_name, arguments):
        nonlocal calls
        calls += 1
        return f"{server_name}:{tool_name}:{arguments['ticker']}"

    monkeypatch.setattr(mcp_client, "call_tool", fake_call_tool)
    tool = mcp_client._make_tool("edgar", _tool(), cache_results=True)

    first = await tool.ainvoke({"ticker": "AAPL"})
    second = await tool.ainvoke({"ticker": "AAPL"})

    assert first == second == "edgar:filings:AAPL"
    assert calls == 1


@pytest.mark.asyncio
async def test_cached_tool_coalesces_concurrent_calls(monkeypatch):
    calls = 0

    async def fake_call_tool(server_name, tool_name, arguments):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return "filing data"

    monkeypatch.setattr(mcp_client, "call_tool", fake_call_tool)
    tool = mcp_client._make_tool("edgar", _tool(), cache_results=True)

    results = await asyncio.gather(
        tool.ainvoke({"ticker": "AAPL"}),
        tool.ainvoke({"ticker": "AAPL"}),
    )

    assert results == ["filing data", "filing data"]
    assert calls == 1


@pytest.mark.asyncio
async def test_cached_tool_does_not_cache_failures(monkeypatch):
    calls = 0

    async def fake_call_tool(server_name, tool_name, arguments):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary EDGAR failure")
        return "recovered"

    monkeypatch.setattr(mcp_client, "call_tool", fake_call_tool)
    tool = mcp_client._make_tool("edgar", _tool(), cache_results=True)

    with pytest.raises(RuntimeError, match="temporary EDGAR failure"):
        await tool.ainvoke({"ticker": "AAPL"})

    assert await tool.ainvoke({"ticker": "AAPL"}) == "recovered"
    assert calls == 2


@pytest.mark.asyncio
async def test_call_tool_cached_expires_after_its_ttl(monkeypatch):
    """TTL-based, not an unlimited process-lifetime cache -- a stale entry
    must eventually be refetched, not served forever."""
    calls = 0
    fake_now = [1000.0]

    async def fake_call_tool(server_name, tool_name, arguments):
        nonlocal calls
        calls += 1
        return f"value-{calls}"

    monkeypatch.setattr(mcp_client, "call_tool", fake_call_tool)
    monkeypatch.setattr(mcp_client.time, "monotonic", lambda: fake_now[0])

    first = await mcp_client.call_tool_cached("fmp", "get_key_metrics", {"symbol": "XOM"}, ttl_seconds=60)
    assert first == "value-1"
    assert calls == 1

    # Still within the TTL -- cache hit, no new call.
    fake_now[0] += 30
    second = await mcp_client.call_tool_cached("fmp", "get_key_metrics", {"symbol": "XOM"}, ttl_seconds=60)
    assert second == "value-1"
    assert calls == 1

    # Past the TTL -- must refetch.
    fake_now[0] += 31
    third = await mcp_client.call_tool_cached("fmp", "get_key_metrics", {"symbol": "XOM"}, ttl_seconds=60)
    assert third == "value-2"
    assert calls == 2


@pytest.mark.asyncio
async def test_call_tool_cached_key_includes_cache_key_extra(monkeypatch):
    """Same provider/tool/arguments but a different as_of_date (passed as
    cache_key_extra, never forwarded to the tool call itself) must never
    share a cache entry -- a request for a different point in time must
    never be served a response cached for a different one."""
    calls: list[dict] = []

    async def fake_call_tool(server_name, tool_name, arguments):
        calls.append(arguments)
        return f"value-for-{arguments}"

    monkeypatch.setattr(mcp_client, "call_tool", fake_call_tool)

    await mcp_client.call_tool_cached(
        "fmp", "get_key_metrics", {"symbol": "XOM"}, cache_key_extra={"as_of_date": "2026-09-01"}
    )
    await mcp_client.call_tool_cached(
        "fmp", "get_key_metrics", {"symbol": "XOM"}, cache_key_extra={"as_of_date": "2026-06-01"}
    )
    # Same as_of_date as the first call -- must be a cache hit.
    await mcp_client.call_tool_cached(
        "fmp", "get_key_metrics", {"symbol": "XOM"}, cache_key_extra={"as_of_date": "2026-09-01"}
    )

    assert len(calls) == 2  # not 3 -- the third call was a cache hit
    # Neither underlying call ever received as_of_date as an argument.
    for arguments in calls:
        assert "as_of_date" not in arguments


@pytest.mark.asyncio
async def test_call_tool_retries_a_transient_failure_before_raising(monkeypatch):
    attempts = 0

    class _FakeClient:
        async def __aenter__(self):
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise ConnectionError("transient")
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def call_tool(self, tool_name, arguments):
            class _Result:
                content = []
            return _Result()

    monkeypatch.setattr(mcp_client, "_TRANSIENT_RETRY_BACKOFF_SECONDS", 0)
    monkeypatch.setattr(mcp_client.mcp, "Client", lambda *_a, **_k: _FakeClient())

    result = await mcp_client.call_tool("fmp", "get_key_metrics", {"symbol": "XOM"})

    assert attempts == 3
    assert result == ""


@pytest.mark.asyncio
async def test_load_tools_caches_external_tool_definitions(monkeypatch):
    calls = 0

    async def fake_list_tools(server_name):
        nonlocal calls
        calls += 1
        return [_tool()]

    monkeypatch.setattr(mcp_client, "_list_tools", fake_list_tools)

    first = await mcp_client.load_tools("edgar", cache_results=True)
    second = await mcp_client.load_tools("edgar", cache_results=True)

    assert [tool.name for tool in first] == ["filings"]
    assert [tool.name for tool in second] == ["filings"]
    assert calls == 1

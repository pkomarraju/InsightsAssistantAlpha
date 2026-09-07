"""Covers agents/orchestrator.py's build_specialist/run_specialist/
build_supervisor -- the deterministic-dispatch primitives
agents/research_execution.py is built on. MCP tool loading and the LLM
itself are monkeypatched; these tests never hit the network.
"""

from dataclasses import dataclass

import pytest

import insights_assistant.agents.orchestrator as orchestrator
from insights_assistant.contracts.api.enums import EvidenceSourceAgent


@dataclass
class _FakeMessage:
    content: str


@dataclass
class _FakeTool:
    name: str


class _FakeAgent:
    def __init__(self, name):
        self.name = name
        self.calls = []

    async def ainvoke(self, state):
        self.calls.append(state)
        return {"messages": [*state["messages"], _FakeMessage(content=f"answer from {self.name}")]}


@pytest.fixture(autouse=True)
def clear_specialist_cache():
    orchestrator._specialist_cache.clear()
    yield
    orchestrator._specialist_cache.clear()


@pytest.fixture
def fake_build_pieces(monkeypatch):
    """Stubs load_tools and create_agent so build_specialist never touches a
    real MCP server or LLM, while still exercising the real caching logic."""

    created: list[EvidenceSourceAgent] = []

    async def fake_load_tools(server_name, *, cache_results=False):
        return [_FakeTool(name=f"tool-for-{server_name}")]

    def fake_create_agent(model, tools, *, system_prompt, name):
        created.append(name)
        return _FakeAgent(name)

    monkeypatch.setattr(orchestrator, "load_tools", fake_load_tools)
    monkeypatch.setattr(orchestrator, "create_agent", fake_create_agent)
    monkeypatch.setattr(orchestrator, "chat_model", lambda: "fake-model")
    return created


class TestBuildSpecialist:
    @pytest.mark.asyncio
    async def test_builds_and_caches_one_agent_per_source(self, fake_build_pieces):
        first = await orchestrator.build_specialist(EvidenceSourceAgent.EXTERNAL_DATA_AGENT)
        second = await orchestrator.build_specialist(EvidenceSourceAgent.EXTERNAL_DATA_AGENT)

        assert first is second
        assert fake_build_pieces == ["external_data_agent"]  # only built once

    @pytest.mark.asyncio
    async def test_each_source_gets_its_own_agent(self, fake_build_pieces):
        ext = await orchestrator.build_specialist(EvidenceSourceAgent.EXTERNAL_DATA_AGENT)
        internal = await orchestrator.build_specialist(EvidenceSourceAgent.INTERNAL_DATA_AGENT)

        assert ext is not internal
        assert set(fake_build_pieces) == {"external_data_agent", "internal_data_agent"}


class TestRunSpecialist:
    @pytest.mark.asyncio
    async def test_invokes_the_built_agent_with_the_given_prompt(self, fake_build_pieces):
        answer = await orchestrator.run_specialist(EvidenceSourceAgent.RELATIONSHIP_NOTES_AGENT, "research this")

        assert answer == "answer from relationship_notes_agent"
        agent = await orchestrator.build_specialist(EvidenceSourceAgent.RELATIONSHIP_NOTES_AGENT)
        assert agent.calls[0]["messages"] == [{"role": "user", "content": "research this"}]


class TestExternalDataAgentUsesCuratedAdapters:
    """external_data_agent's tools are the five curated adapters
    (agents/external_adapters.py), never a raw per-provider MCP tool union
    -- building them never touches load_tools/the network at all, so
    building this specialist can no longer fail because one or more
    providers are unreachable (a real, observed failure mode of the old
    union-based approach -- see agents/orchestrator.py's
    _load_specialist_tools docstring). Provider-level failure is instead
    handled per-call, inside each adapter (see test_external_adapters.py).
    """

    @pytest.mark.asyncio
    async def test_building_the_specialist_never_calls_load_tools(self, monkeypatch):
        called = []

        async def fail_if_called(server_name, *, cache_results=False):
            called.append(server_name)
            raise AssertionError("load_tools must never be called for external_data_agent")

        monkeypatch.setattr(orchestrator, "load_tools", fail_if_called)
        monkeypatch.setattr(orchestrator, "create_agent", lambda model, tools, *, system_prompt, name: _FakeAgent(name))
        monkeypatch.setattr(orchestrator, "chat_model", lambda: "fake-model")

        agent = await orchestrator.build_specialist(EvidenceSourceAgent.EXTERNAL_DATA_AGENT)

        assert called == []
        assert agent is not None

    @pytest.mark.asyncio
    async def test_specialist_tools_are_exactly_the_five_curated_adapters(self, monkeypatch):
        captured_tools = {}

        def fake_create_agent(model, tools, *, system_prompt, name):
            captured_tools[name] = tools
            return _FakeAgent(name)

        monkeypatch.setattr(orchestrator, "create_agent", fake_create_agent)
        monkeypatch.setattr(orchestrator, "chat_model", lambda: "fake-model")

        await orchestrator.build_specialist(EvidenceSourceAgent.EXTERNAL_DATA_AGENT)

        names = [t.name for t in captured_tools["external_data_agent"]]
        assert names == [
            "fmp_get_financial_health", "fmp_get_valuation",
            "av_get_market_signal", "av_get_earnings_signal", "fred_get_rate_signal",
        ]


class TestBuildSupervisor:
    @pytest.mark.asyncio
    async def test_reuses_build_specialist_for_all_three_agents(self, fake_build_pieces, monkeypatch):
        captured = {}

        def fake_create_supervisor(*, agents, model, prompt):
            captured["agents"] = agents
            captured["prompt"] = prompt

            class _FakeSupervisorBuilder:
                def compile(self_inner):
                    return "compiled-supervisor"

            return _FakeSupervisorBuilder()

        monkeypatch.setattr(orchestrator, "create_supervisor", fake_create_supervisor)

        supervisor = await orchestrator.build_supervisor()

        assert supervisor == "compiled-supervisor"
        assert len(captured["agents"]) == 3
        assert set(fake_build_pieces) == {
            "external_data_agent", "internal_data_agent", "relationship_notes_agent",
        }
        assert "external_data_agent" in captured["prompt"]

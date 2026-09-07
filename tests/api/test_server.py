"""Covers the request-execution path in src/insights_assistant/api/server.py:
company/source resolution guards, InsightRequirementsSelection construction,
InsightPackage -> InsightDto mapping, and the extended ResearchRequest fields
(currentStage, requestVersion/packageVersion, revision counts, sourceErrors,
reviewDecision/reviewComments, auditEvents, unmetRequirements) mirrored live
from a WorkflowState.

`agents.insight_workflow.run_insight_workflow` is the mocked seam -- the
research -> synthesize -> review pipeline itself is covered by
tests/agents/test_insight_workflow.py, test_synthesizer.py, test_reviewer.py,
and test_research_execution.py (and EDGAR/mcp_client caching by
tests/test_mcp_client_cache.py). server.py no longer touches
research_execution/mcp_client directly at all -- it only calls
run_insight_workflow once per request. `_run_request` is exercised directly
(bypassing the FastAPI route and Supabase) by seeding `server.STORE` with a
request and hand-built `CompanyDto` objects. These tests never hit the
network, a real LLM, or Supabase.
"""

import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from insights_assistant.api import server
from insights_assistant.contracts.api.enums import (
    ClaimType,
    EvidenceSourceAgent,
    InsightCategory,
    InsightPersona,
    InsightPriority,
    InsightSubtype,
)
from insights_assistant.contracts.api.evidence import BusinessImpact, EvidenceItem
from insights_assistant.contracts.workflow.enums import ReviewDecisionType, SourcePayloadStatus, WorkflowStage
from insights_assistant.contracts.workflow.packages import InsightPackage, RankedInsight, UnmetRequirement
from insights_assistant.contracts.workflow.research import PayloadKey, SourcePayload
from insights_assistant.contracts.workflow.review import NarrowResearchRevision, ReviewDecision
from insights_assistant.contracts.workflow.state import SourceErrorRecord, WorkflowState

NOW = datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone.utc)


def _company(code: str, name: str, ticker: str) -> server.CompanyDto:
    return server.CompanyDto(companyId=code, companyCode=code, companyName=name, ticker=ticker)


def _payload(**overrides) -> server.CreateRequestInput:
    defaults = dict(
        companyIds=[],
        dataDomainIds=["client_profitability"],
        generalSearchPrompt="Summarize relationship health and any risk flags.",
        edgarEnabled=False,
        filingTypes=[],
        lookbackMonths=12,
        totalCount=5,
        categories=[server.RequestInsightCategory(categoryId="revenue_cross_sell", minimumCount=1)],
        rankingCriteria=["urgency"],
    )
    defaults.update(overrides)
    return server.CreateRequestInput(**defaults)


def _seed_request(request_id: str) -> server.ResearchRequest:
    now = server._now()
    req = server.ResearchRequest(
        requestId=request_id,
        requestedBy="banker-12345",
        status="queued",
        stage="queued",
        currentStage="queued",
        createdAt=now,
        updatedAt=now,
        companyScope={"selectionMode": "explicit", "companies": []},
        externalResearch={"edgarEnabled": False, "filingTypes": [], "lookbackMonths": 12},
        internalResearch={"dataDomains": [], "generalSearchPrompt": "x", "asOfDate": now[:10]},
        insightRequirements={"totalCount": 5, "categories": [], "rankingCriteria": [], "maxInsightsPerCompany": 10},
        resultInsightIds=[],
        progressPct=0,
        errorMessage=None,
    )
    server.STORE[request_id] = req
    return req


@pytest.fixture(autouse=True)
def clean_stores(monkeypatch):
    server.STORE.clear()
    server.INSIGHTS_STORE.clear()
    server._TASKS_BY_REQUEST_ID.clear()
    server._DELETED_REQUEST_IDS.clear()
    # These tests never hit Supabase (see module docstring): _run_request and
    # the review endpoints are exercised directly, but agents/insight_workflow.py
    # now mirrors every request/insight mutation to Supabase in the background
    # (see api/server.py's persistence section) -- stub the three functions
    # that actually call _supabase() out to no-ops so that stays true, rather
    # than quietly writing REQ_TEST_ARGS/REQ_SUCCESS/etc. fixture rows into
    # the real database on every test run.
    monkeypatch.setattr(server, "_persist_request_sync", lambda req: None)
    monkeypatch.setattr(server, "_persist_insight_sync", lambda insight: None)
    monkeypatch.setattr(server, "_delete_request_sync", lambda request_id: None)
    yield
    server.STORE.clear()
    server.INSIGHTS_STORE.clear()
    server._TASKS_BY_REQUEST_ID.clear()
    server._DELETED_REQUEST_IDS.clear()


AMAZON = _company("CLI_002", "Amazon", "AMZN")
ALPHABET = _company("CLI_007", "Alphabet", "GOOGL")
APPLE = _company("CLI_003", "Apple", "AAPL")

INT = EvidenceSourceAgent.INTERNAL_DATA_AGENT


def _source_payload(
    company_code, source_agent, *, status=SourcePayloadStatus.COMPLETED, error=None, evidence=None
) -> SourcePayload:
    return SourcePayload(
        request_id="REQ_1", request_version=1, company_code=company_code, source_agent=source_agent,
        status=status, evidence=evidence or [],
        findings="Some findings." if status == SourcePayloadStatus.COMPLETED else "",
        error=error, started_at=NOW, completed_at=NOW,
    )


def _with_source_error(state: WorkflowState, *, company_code: str, status: SourcePayloadStatus, error: str) -> WorkflowState:
    """Mirrors what agents/insight_workflow.py's _record_source_errors does
    for a non-completed SourcePayload -- test states are built the same way
    the real workflow builds them, so _sync_request_from_state's
    state.source_errors-based derivation is exercised realistically."""

    return state.with_source_error(
        SourceErrorRecord(
            request_id=state.request_id, request_version=state.request_version, company_code=company_code,
            source_agent=INT, status=status, error=error, occurred_at=NOW,
        ),
        occurred_at=NOW,
    )


def _ranked_insight(company_code: str, insight_id: str) -> RankedInsight:
    return RankedInsight(
        insight_id=insight_id, rank=1, company_code=company_code,
        category=InsightCategory.REVENUE_CROSS_SELL, subtype=InsightSubtype.OPPORTUNITY_RISK,
        primary_claim=ClaimType.PRODUCT_OR_CROSS_SELL_OPPORTUNITY,
        persona=InsightPersona.RELATIONSHIP_MANAGER, priority=InsightPriority.HIGH,
        title="Whitespace opportunity", finding="Untapped treasury product.",
        why_it_matters="Revenue upside.", recommended_action="Pitch treasury services.",
        confidence=75, confidence_rationale="Backed by product usage data.",
        business_impact=BusinessImpact(estimated_impact_usd=250_000, impact_basis="Est. annual revenue from the pipeline entry", description="Est. annual revenue"),
        evidence=[
            EvidenceItem(
                id=f"EV_{insight_id}", source_agent=EvidenceSourceAgent.INTERNAL_DATA_AGENT,
                source_type="internal", evidence_code="OPP_015", label="Opportunity",
                detail="Pipeline entry.", date="2026-07-01",
            )
        ],
    )


def _package(request_id: str, insights: list[RankedInsight], *, unmet: list[UnmetRequirement] | None = None) -> InsightPackage:
    refs = [
        PayloadKey(company_code=i.company_code, source_agent=EvidenceSourceAgent.INTERNAL_DATA_AGENT)
        for i in insights
    ] or [PayloadKey(company_code="CLI_002", source_agent=EvidenceSourceAgent.INTERNAL_DATA_AGENT)]
    return InsightPackage(
        request_id=request_id, request_version=1, package_version=1,
        original_user_prompt="p", effective_research_prompt="p",
        preferences=server._preferences_snapshot(),
        source_payload_refs=refs, insights=insights, unmet_requirements=unmet or [], created_at=NOW,
    )


def _pass_decision(request_id: str, package_version: int = 1) -> ReviewDecision:
    return ReviewDecision(
        decision=ReviewDecisionType.PASS, request_id=request_id, request_version=1,
        package_version=package_version, comments="Well supported by the evidence.", created_at=NOW,
    )


def test_company_question_requests_most_recent_external_data_and_ten_signals():
    question = server._build_company_question(
        APPLE,
        _payload(edgarEnabled=True, filingTypes=["10-K", "10-Q"], lookbackMonths=24),
    )

    assert "FMP" in question
    assert "Alpha Vantage" in question
    assert "FRED" in question
    assert "most recent" in question
    assert "at most 10 external signals" in question
    assert "24 months" not in question


class TestRequiredSourcesForPayload:
    def test_edgar_only(self):
        result = server._required_sources_for(_payload(edgarEnabled=True, dataDomainIds=[]))
        assert result == {server.EvidenceSourceAgent.EXTERNAL_DATA_AGENT}

    def test_structured_domain_only(self):
        result = server._required_sources_for(_payload(dataDomainIds=["credit_exposure"]))
        assert result == {server.EvidenceSourceAgent.INTERNAL_DATA_AGENT}

    def test_relationship_interactions_only(self):
        result = server._required_sources_for(_payload(dataDomainIds=["relationship_interactions"]))
        assert result == {server.EvidenceSourceAgent.RELATIONSHIP_NOTES_AGENT}

    def test_nothing_enabled_is_empty(self):
        result = server._required_sources_for(_payload(edgarEnabled=False, dataDomainIds=[]))
        assert result == set()

    def test_a_short_general_search_prompt_does_not_break_routing(self):
        """The wizard's own >=20-character minimum on general_search_prompt
        lives on ExternalResearchSelection/InternalResearchSelection, not on
        this endpoint's CreateRequestInput -- routing must not depend on it."""
        result = server._required_sources_for(_payload(generalSearchPrompt="short", dataDomainIds=["credit_exposure"]))
        assert result == {server.EvidenceSourceAgent.INTERNAL_DATA_AGENT}


class TestStageDisplayMapping:
    """currentStage's mapping from the internal WorkflowStage enum is the
    seam the frontend's whole 9-stage vocabulary depends on -- verify every
    value maps to something, and to the expected bucket."""

    def test_every_workflow_stage_has_a_display_mapping(self):
        for stage in WorkflowStage:
            assert server._display_stage_for(stage) in {
                "researching", "waiting_for_sources", "synthesizing", "reviewing",
                "revising_research", "revising_synthesis", "completed", "failed",
            }

    @pytest.mark.parametrize(
        ("display_stage", "expected_status"),
        [
            ("researching", "running"),
            ("waiting_for_sources", "running"),
            ("synthesizing", "running"),
            ("reviewing", "running"),
            ("revising_synthesis", "running"),
            ("revising_research", "running"),
            ("completed", "completed"),
            ("failed", "failed"),
        ],
    )
    def test_status_derived_from_display_stage(self, display_stage, expected_status):
        assert server._status_for_display_stage(display_stage) == expected_status


@pytest.mark.asyncio
async def test_no_companies_fails_without_dispatch(monkeypatch):
    async def _unexpected(**kwargs):
        raise AssertionError("run_insight_workflow should not be called with no companies")

    monkeypatch.setattr(server, "run_insight_workflow", _unexpected)

    request_id = "REQ_NO_COMPANIES"
    _seed_request(request_id)
    await server._run_request(request_id, [], _payload())

    req = server.STORE[request_id]
    assert req.status == "failed"
    assert req.stage == WorkflowStage.FAILED.value
    assert req.currentStage == "failed"
    assert "No selected companies" in req.errorMessage


@pytest.mark.asyncio
async def test_no_sources_enabled_fails_without_dispatch(monkeypatch):
    async def _unexpected(**kwargs):
        raise AssertionError("run_insight_workflow should not be called with no sources enabled")

    monkeypatch.setattr(server, "run_insight_workflow", _unexpected)

    request_id = "REQ_NO_SOURCES"
    _seed_request(request_id)
    await server._run_request(request_id, [AMAZON], _payload(edgarEnabled=False, dataDomainIds=[]))

    req = server.STORE[request_id]
    assert req.status == "failed"
    assert req.stage == WorkflowStage.FAILED.value
    assert req.currentStage == "failed"
    assert "No research sources" in req.errorMessage


@pytest.mark.asyncio
async def test_run_request_calls_workflow_with_expected_arguments(monkeypatch):
    captured = {}

    async def fake_run_insight_workflow(**kwargs):
        captured.update(kwargs)
        state = WorkflowState.start("REQ_TEST_ARGS", occurred_at=NOW).with_stage(
            WorkflowStage.COMPLETED, message="done", occurred_at=NOW
        )
        return state, _package("REQ_TEST_ARGS", []), [], _pass_decision("REQ_TEST_ARGS")

    monkeypatch.setattr(server, "run_insight_workflow", fake_run_insight_workflow)

    companies = [AMAZON, ALPHABET]
    request_id = "REQ_TEST_ARGS"
    req = _seed_request(request_id)
    await server._run_request(
        request_id, companies, _payload(edgarEnabled=True, dataDomainIds=["client_profitability"])
    )

    assert captured["request_id"] == request_id
    assert captured["company_codes"] == ["CLI_002", "CLI_007"]
    assert captured["required_sources"] == {
        server.EvidenceSourceAgent.EXTERNAL_DATA_AGENT, server.EvidenceSourceAgent.INTERNAL_DATA_AGENT,
    }
    assert set(captured["prompt_by_company"].keys()) == {"CLI_002", "CLI_007"}
    assert captured["original_user_prompt"] == "Summarize relationship health and any risk flags."
    assert captured["insight_requirements"].total_count == 5
    assert captured["insight_requirements"].categories[0].category_id == InsightCategory.REVENUE_CROSS_SELL
    assert captured["insight_requirements"].max_insights_per_company == 10

    # on_state_change is real, live wiring -- not just a name in kwargs.
    # Invoking it with a synthetic mid-flight state must mirror onto `req`
    # immediately, before run_insight_workflow itself has even returned.
    on_state_change = captured["on_state_change"]
    mid_flight_state = WorkflowState.start(request_id, occurred_at=NOW).with_stage(
        WorkflowStage.SYNTHESIZING, message="synthesizing insight package", occurred_at=NOW
    )
    on_state_change(mid_flight_state)
    assert req.currentStage == "synthesizing"
    assert req.status == "running"


@pytest.mark.asyncio
async def test_successful_request_populates_insight_store(monkeypatch):
    companies = [AMAZON, ALPHABET]
    insight_amazon = _ranked_insight("CLI_002", "PKG_REQ_SUCCESS_1_INS_0")
    insight_alphabet = _ranked_insight("CLI_007", "PKG_REQ_SUCCESS_1_INS_1")
    unmet = [UnmetRequirement(category=InsightCategory.CREDIT_RISK, requested_count=2, actual_count=0, reason="No credit-risk evidence.")]
    package = _package("REQ_SUCCESS", [insight_amazon, insight_alphabet], unmet=unmet)

    payloads = [
        _source_payload("CLI_002", EvidenceSourceAgent.INTERNAL_DATA_AGENT, evidence=insight_amazon.evidence),
        _source_payload("CLI_007", EvidenceSourceAgent.INTERNAL_DATA_AGENT, evidence=insight_alphabet.evidence),
    ]
    state = WorkflowState.start("REQ_SUCCESS", occurred_at=NOW).with_stage(
        WorkflowStage.COMPLETED, message="review passed", occurred_at=NOW
    )
    decision = _pass_decision("REQ_SUCCESS")

    async def fake_run_insight_workflow(**kwargs):
        return state, package, payloads, decision

    monkeypatch.setattr(server, "run_insight_workflow", fake_run_insight_workflow)

    request_id = "REQ_SUCCESS"
    _seed_request(request_id)
    await server._run_request(request_id, companies, _payload())

    req = server.STORE[request_id]
    assert req.status == "completed"
    assert req.stage == WorkflowStage.COMPLETED.value
    assert req.currentStage == "completed"
    assert req.progressPct == 100
    assert req.requestVersion == 1
    assert req.packageVersion == 1
    assert req.researchRevisionCount == 0
    assert req.synthesisRevisionCount == 0
    assert req.reviewDecision == "pass"
    assert req.reviewComments == "Well supported by the evidence."
    assert len(req.auditEvents) >= 1
    assert len(req.unmetRequirements) == 1
    assert req.unmetRequirements[0].category == "credit_risk"
    assert req.unmetRequirements[0].actualCount == 0
    assert set(req.resultInsightIds) == {"PKG_REQ_SUCCESS_1_INS_0", "PKG_REQ_SUCCESS_1_INS_1"}
    assert req.sourceErrors == []
    assert "Amazon" in req.resultSummary and "Alphabet" in req.resultSummary

    stored = server.INSIGHTS_STORE["PKG_REQ_SUCCESS_1_INS_0"]
    assert stored.companyId == "CLI_002"
    assert stored.companyName == "Amazon"
    assert stored.category == "revenue_cross_sell"
    assert stored.reviewStatus == "pending"
    assert stored.reviewHistory[0].action == "generated"
    assert stored.evidence[0].evidenceCode == "OPP_015"
    assert stored.evidence[0].date == "2026-07-01"
    assert stored.businessImpact.estimatedImpactUsd == 250_000


@pytest.mark.asyncio
async def test_failed_workflow_sets_error_and_persists_no_insights(monkeypatch):
    companies = [AMAZON]
    payloads = [
        _source_payload(
            "CLI_002", EvidenceSourceAgent.INTERNAL_DATA_AGENT, status=SourcePayloadStatus.FAILED,
            error="specialist blew up",
        )
    ]
    state = _with_source_error(
        WorkflowState.start("REQ_FAILED", occurred_at=NOW),
        company_code="CLI_002", status=SourcePayloadStatus.FAILED, error="specialist blew up",
    ).with_terminal_error("research incomplete: CLI_002/internal_data_agent: failed", occurred_at=NOW)

    async def fake_run_insight_workflow(**kwargs):
        return state, None, payloads, None

    monkeypatch.setattr(server, "run_insight_workflow", fake_run_insight_workflow)

    request_id = "REQ_FAILED"
    _seed_request(request_id)
    await server._run_request(request_id, companies, _payload())

    req = server.STORE[request_id]
    assert req.status == "failed"
    assert req.stage == WorkflowStage.FAILED.value
    assert req.currentStage == "failed"
    assert req.progressPct == 100
    assert req.errorMessage == state.terminal_error
    assert req.resultInsightIds == []
    assert req.reviewDecision is None
    assert req.reviewComments is None
    assert len(req.sourceErrors) == 1
    assert req.sourceErrors[0].companyId == "CLI_002"
    assert req.sourceErrors[0].code == "failed"
    assert server.INSIGHTS_STORE == {}


@pytest.mark.asyncio
async def test_timeout_source_displayed_with_timed_out_code(monkeypatch):
    """A timed-out source (asyncio.wait deadline exceeded, not an exception)
    must be visibly distinguishable from an outright failure in sourceErrors."""
    companies = [AMAZON]
    state = _with_source_error(
        WorkflowState.start("REQ_TIMEOUT", occurred_at=NOW),
        company_code="CLI_002", status=SourcePayloadStatus.TIMED_OUT,
        error="deadline exceeded before the specialist finished",
    ).with_terminal_error("research incomplete: CLI_002/internal_data_agent: timed_out", occurred_at=NOW)

    async def fake_run_insight_workflow(**kwargs):
        return state, None, [], None

    monkeypatch.setattr(server, "run_insight_workflow", fake_run_insight_workflow)

    request_id = "REQ_TIMEOUT"
    _seed_request(request_id)
    await server._run_request(request_id, companies, _payload())

    req = server.STORE[request_id]
    assert req.status == "failed"
    assert len(req.sourceErrors) == 1
    assert req.sourceErrors[0].code == "timed_out"
    assert "deadline exceeded" in req.sourceErrors[0].message


@pytest.mark.asyncio
async def test_synthesis_revision_reflected_in_counts_and_audit_history(monkeypatch):
    companies = [AMAZON]
    package = _package("REQ_SYN_REV", [_ranked_insight("CLI_002", "PKG_REQ_SYN_REV_2_INS_0")])
    revise_decision = ReviewDecision(
        decision=ReviewDecisionType.REVISE_INSIGHTS, request_id="REQ_SYN_REV", request_version=1,
        package_version=1, comments="Consolidate duplicate insights.", created_at=NOW,
        affected_insight_ids=["PKG_REQ_SYN_REV_1_INS_0"],
    )
    state = WorkflowState.start("REQ_SYN_REV", occurred_at=NOW)
    state = state.with_stage(WorkflowStage.REVIEWING, message="reviewing", occurred_at=NOW, detail={
        "decision": revise_decision.decision.value, "comments": revise_decision.comments,
        "affectedInsightIds": revise_decision.affected_insight_ids, "affectedSourceAgents": [],
    })
    state = state.with_synthesis_revision(occurred_at=NOW, message="synthesis revision accepted")
    state = state.with_stage(WorkflowStage.COMPLETED, message="review passed", occurred_at=NOW)
    pass_decision = _pass_decision("REQ_SYN_REV", package_version=2)

    async def fake_run_insight_workflow(**kwargs):
        return state, package, [], pass_decision

    monkeypatch.setattr(server, "run_insight_workflow", fake_run_insight_workflow)

    request_id = "REQ_SYN_REV"
    _seed_request(request_id)
    await server._run_request(request_id, companies, _payload())

    req = server.STORE[request_id]
    assert req.synthesisRevisionCount == 1
    assert req.researchRevisionCount == 0
    assert req.packageVersion == 2
    assert req.reviewDecision == "pass"
    revision_events = [e for e in req.auditEvents if e.detail and e.detail.get("decision") == "revise_insights"]
    assert len(revision_events) == 1
    assert revision_events[0].detail["comments"] == "Consolidate duplicate insights."


@pytest.mark.asyncio
async def test_research_revision_reflected_in_counts_and_audit_history(monkeypatch):
    companies = [AMAZON]
    package = _package("REQ_RES_REV", [_ranked_insight("CLI_002", "PKG_REQ_RES_REV_1_INS_0")])
    narrow = NarrowResearchRevision(company_codes=["CLI_002"], source_agents=[INT], guidance="Re-check the risk score.")
    revise_decision = ReviewDecision(
        decision=ReviewDecisionType.REVISE_RESEARCH, request_id="REQ_RES_REV", request_version=1,
        package_version=1, comments="Evidence looked stale.", created_at=NOW,
        narrow_research_revision=narrow, affected_source_agents=[INT],
    )
    state = WorkflowState.start("REQ_RES_REV", occurred_at=NOW)
    state = state.with_stage(WorkflowStage.REVIEWING, message="reviewing", occurred_at=NOW, detail={
        "decision": revise_decision.decision.value, "comments": revise_decision.comments,
        "affectedInsightIds": [], "affectedSourceAgents": ["internal_data_agent"],
    })
    state = state.with_research_revision(occurred_at=NOW, narrow_revision=narrow, message="research revision accepted")
    state = state.with_stage(WorkflowStage.COMPLETED, message="review passed", occurred_at=NOW)
    pass_decision = _pass_decision("REQ_RES_REV")

    async def fake_run_insight_workflow(**kwargs):
        return state, package, [], pass_decision

    monkeypatch.setattr(server, "run_insight_workflow", fake_run_insight_workflow)

    request_id = "REQ_RES_REV"
    _seed_request(request_id)
    await server._run_request(request_id, companies, _payload())

    req = server.STORE[request_id]
    assert req.researchRevisionCount == 1
    assert req.synthesisRevisionCount == 0
    assert req.requestVersion == 2
    revision_events = [e for e in req.auditEvents if e.detail and e.detail.get("decision") == "revise_research"]
    assert len(revision_events) == 1
    assert revision_events[0].detail["comments"] == "Evidence looked stale."


@pytest.mark.asyncio
async def test_failed_terminal_state_after_retry_exhaustion(monkeypatch):
    """Both budgets exhausted, a third revision attempt forced to fail --
    the terminal state a banker actually sees when retries run out."""
    companies = [AMAZON]
    state = WorkflowState.start("REQ_EXHAUSTED", occurred_at=NOW)
    state = state.with_research_revision(occurred_at=NOW, message="research revision accepted")
    state = state.with_synthesis_revision(occurred_at=NOW, message="synthesis revision accepted")
    state = state.with_terminal_error(
        "synthesis revision rejected: bounded-retry policy allows at most one synthesis revision "
        "per request, and it has already been used",
        occurred_at=NOW,
    )

    async def fake_run_insight_workflow(**kwargs):
        return state, None, [], None

    monkeypatch.setattr(server, "run_insight_workflow", fake_run_insight_workflow)

    request_id = "REQ_EXHAUSTED"
    _seed_request(request_id)
    await server._run_request(request_id, companies, _payload())

    req = server.STORE[request_id]
    assert req.status == "failed"
    assert req.currentStage == "failed"
    assert req.researchRevisionCount == 1
    assert req.synthesisRevisionCount == 1
    assert "bounded-retry" in req.errorMessage
    assert req.resultInsightIds == []


def test_backward_compatible_rendering_when_new_fields_absent():
    """A ResearchRequest constructed the old way (no currentStage,
    requestVersion, reviewDecision, auditEvents, etc.) must still validate --
    every new field is additive with a sensible default, per the
    backward-compatibility requirement."""
    req = server.ResearchRequest(
        requestId="REQ_LEGACY", requestedBy="banker-12345", status="completed",
        createdAt=server._now(), updatedAt=server._now(),
        companyScope={}, externalResearch={}, internalResearch={}, insightRequirements={},
        resultInsightIds=[], progressPct=100, errorMessage=None,
    )
    assert req.currentStage == "queued"
    assert req.requestVersion == 1
    assert req.packageVersion == 1
    assert req.researchRevisionCount == 0
    assert req.synthesisRevisionCount == 0
    assert req.reviewDecision is None
    assert req.reviewComments is None
    assert req.auditEvents == []
    assert req.unmetRequirements == []
    assert req.sourceErrors == []


class TestCancelRequest:
    """Covers POST /api/requests/{id}/cancel (server.cancel_request) and
    _run_request's own asyncio.CancelledError handling -- called directly
    as plain functions/coroutines, matching this file's established
    convention of exercising server.py's logic without a FastAPI TestClient.
    """

    def test_cancel_missing_request_raises_404(self):
        with pytest.raises(HTTPException) as exc_info:
            server.cancel_request("REQ_MISSING")
        assert exc_info.value.status_code == 404

    @pytest.mark.parametrize("terminal_status", ["completed", "failed", "cancelled"])
    def test_cancel_already_terminal_request_raises_409(self, terminal_status):
        req = _seed_request("REQ_1")
        req.status = terminal_status
        with pytest.raises(HTTPException) as exc_info:
            server.cancel_request("REQ_1")
        assert exc_info.value.status_code == 409
        assert req.status == terminal_status  # untouched -- the 409 path never rewrites it

    def test_cancel_running_request_sets_cancelled_terminal_state(self):
        req = _seed_request("REQ_1")
        req.status = "running"
        req.currentStage = "synthesizing"
        req.progressPct = 55

        result = server.cancel_request("REQ_1")

        assert result is server.STORE["REQ_1"]
        assert result.status == "cancelled"
        assert result.currentStage == "cancelled"
        assert result.stage == WorkflowStage.FAILED.value
        assert result.progressPct == 100
        assert result.errorMessage == "Cancelled by user."

    def test_cancel_with_no_registered_task_still_sets_cancelled_state(self):
        """A request between _run_request finishing its own work and the
        done-callback removing it from _TASKS_BY_REQUEST_ID (or any other
        edge case where no task is registered) must still be cancellable
        rather than raising -- the store update is the source of truth the
        UI polls, independent of whether a live task happened to exist."""
        req = _seed_request("REQ_1")
        req.status = "running"
        assert "REQ_1" not in server._TASKS_BY_REQUEST_ID

        result = server.cancel_request("REQ_1")
        assert result.status == "cancelled"

    def test_cancel_actually_cancels_the_registered_asyncio_task(self):
        """End-to-end: a real, still-running asyncio.Task registered the
        same way create_request registers one must actually be cancelled,
        not just have the store optimistically updated."""
        req = _seed_request("REQ_1")
        req.status = "running"

        async def _hangs_forever():
            await asyncio.sleep(999)

        async def _scenario():
            task = asyncio.create_task(_hangs_forever())
            server._TASKS_BY_REQUEST_ID["REQ_1"] = task
            await asyncio.sleep(0)  # let the task actually start

            server.cancel_request("REQ_1")

            with pytest.raises(asyncio.CancelledError):
                await task
            assert task.cancelled()

        asyncio.run(_scenario())
        assert req.status == "cancelled"

    @pytest.mark.asyncio
    async def test_run_request_cancelled_mid_workflow_sets_cancelled_state_not_failed(self, monkeypatch):
        """The task's own CancelledError handler (belt-and-suspenders
        alongside cancel_request's synchronous update) must produce the
        same clean terminal state -- never left as "running" forever, and
        never mislabeled "failed"."""

        async def cancelled_workflow(**kwargs):
            raise asyncio.CancelledError()

        monkeypatch.setattr(server, "run_insight_workflow", cancelled_workflow)

        request_id = "REQ_CANCELLED"
        _seed_request(request_id)
        await server._run_request(request_id, [AMAZON], _payload())

        req = server.STORE[request_id]
        assert req.status == "cancelled"
        assert req.currentStage == "cancelled"
        assert req.errorMessage == "Cancelled by user."
        assert req.resultInsightIds == []

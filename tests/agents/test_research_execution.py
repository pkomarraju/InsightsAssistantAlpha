"""Covers agents/research_execution.py: manifest calculation, the
deterministic join/barrier, and revise_research support.
run_structured_specialist is always monkeypatched -- these tests never hit a
real LLM or MCP server.
"""

import asyncio

import httpx
import pytest
from openai import RateLimitError

import insights_assistant.agents.research_execution as research_execution
from insights_assistant.agents.orchestrator import SpecialistEvidenceItem, SpecialistFindings
from insights_assistant.contracts.api.enums import EvidenceSourceAgent
from insights_assistant.contracts.workflow.enums import ReviewDecisionType, SourcePayloadStatus, WorkflowStage
from insights_assistant.contracts.workflow.invariants import WorkflowInvariantError, ensure_ready_for_synthesis
from insights_assistant.contracts.workflow.research import PayloadKey, ResearchManifest, ResearchTask
from insights_assistant.contracts.workflow.review import NarrowResearchRevision, ReviewDecision
from insights_assistant.contracts.workflow.state import WorkflowState

EXT = EvidenceSourceAgent.EXTERNAL_DATA_AGENT
INT = EvidenceSourceAgent.INTERNAL_DATA_AGENT
NOTES = EvidenceSourceAgent.RELATIONSHIP_NOTES_AGENT

# One real, classifiable evidence_code per source -- see api/evidence_mapping.py.
_EVIDENCE_CODE_BY_SOURCE = {EXT: "FMP_AAPL_RATIOS_2026Q2", INT: "RISK_004", NOTES: "RMN_001"}


@pytest.fixture(autouse=True)
def no_live_internal_context_lookup(monkeypatch):
    """run_research_for_request builds an ExternalResearchPlan per company
    whenever EXTERNAL_DATA_AGENT is required (see
    _build_external_research_plan_for_company), which otherwise calls
    Supabase directly (resolve_ticker_for_company_code/
    build_company_research_context) -- stubbed here to a clean "not found"
    so these tests keep never hitting the network (see module docstring),
    exercising the generic-plan fallback path deterministically rather than
    depending on live data (or its absence) in the real database."""

    monkeypatch.setattr(research_execution, "resolve_ticker_for_company_code", lambda company_code: None)

    def _not_found(company, as_of_date=None):
        raise ValueError(f"no internal context for {company!r} in tests")

    monkeypatch.setattr(research_execution, "build_company_research_context", _not_found)


async def _ok_answer(source_agent, prompt) -> SpecialistFindings:
    return SpecialistFindings(
        summary=f"Finding for {source_agent.value}.",
        evidence=[
            SpecialistEvidenceItem(
                evidence_code=_EVIDENCE_CODE_BY_SOURCE[source_agent],
                date="2026-07-01",
                label="test evidence",
                detail="supporting detail",
            )
        ],
    )


async def _empty_answer(source_agent, prompt) -> SpecialistFindings:
    return SpecialistFindings(summary="", evidence=[])


def _fail_for(*failing_agents):
    async def runner(source_agent, prompt):
        if source_agent in failing_agents:
            raise RuntimeError("specialist blew up")
        return await _ok_answer(source_agent, prompt)
    return runner


def _hang_for(*hanging_agents, seconds=5):
    async def runner(source_agent, prompt):
        if source_agent in hanging_agents:
            await asyncio.sleep(seconds)
        return await _ok_answer(source_agent, prompt)
    return runner


def _use_calculated_workflow_timeout(monkeypatch):
    """Clears both the legacy override and the explicit overall-timeout
    override so compute_research_workflow_timeout_seconds falls through to
    its own formula. Needed because .env may set the legacy
    INSIGHTS_SOURCE_JOIN_TIMEOUT_SECONDS, which (by design -- backward
    compatibility) would otherwise silently win over anything a test tries
    to configure via INSIGHTS_SOURCE_EXECUTION_TIMEOUT_SECONDS/
    RESEARCH_CONCURRENCY, making tests depend on ambient environment state."""
    monkeypatch.setattr(research_execution, "INSIGHTS_SOURCE_JOIN_TIMEOUT_SECONDS", None)
    monkeypatch.setattr(research_execution, "INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_SECONDS", None)


class TestRateLimitRetry:
    """Moved from tests/api/test_server.py: server.py::_research_company no
    longer exists -- this policy now lives in
    research_execution._run_specialist_with_retry, its only implementation."""

    @pytest.mark.asyncio
    async def test_retries_rate_limit_instead_of_failing(self, monkeypatch):
        calls = 0
        sleeps: list[float] = []

        async def fake_run_structured_specialist(source_agent, prompt):
            nonlocal calls
            calls += 1
            if calls == 1:
                request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
                response = httpx.Response(429, headers={"retry-after": "2"}, request=request)
                raise RateLimitError("rate limited", response=response, body=None)
            return SpecialistFindings(summary="recovered answer", evidence=[])

        async def fake_sleep(seconds):
            sleeps.append(seconds)

        monkeypatch.setattr(research_execution, "run_structured_specialist", fake_run_structured_specialist)
        monkeypatch.setattr(research_execution.asyncio, "sleep", fake_sleep)
        monkeypatch.setattr(research_execution, "RATE_LIMIT_RETRY_ATTEMPTS", 3)
        monkeypatch.setattr(research_execution, "RATE_LIMIT_RETRY_FALLBACK_SECONDS", 5)

        result = await research_execution._run_specialist_with_retry(EXT, "research this")

        assert result.summary == "recovered answer"
        assert calls == 2
        assert sleeps == [5]

    @pytest.mark.asyncio
    async def test_gives_up_after_max_attempts(self, monkeypatch):
        async def always_rate_limited(source_agent, prompt):
            request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
            response = httpx.Response(429, request=request)
            raise RateLimitError("rate limited", response=response, body=None)

        async def fake_sleep(seconds):
            pass

        monkeypatch.setattr(research_execution, "run_structured_specialist", always_rate_limited)
        monkeypatch.setattr(research_execution.asyncio, "sleep", fake_sleep)
        monkeypatch.setattr(research_execution, "RATE_LIMIT_RETRY_ATTEMPTS", 2)

        with pytest.raises(RateLimitError):
            await research_execution._run_specialist_with_retry(EXT, "research this")


class TestManifestCalculation:
    def test_manifest_covers_every_company_times_required_source(self, now, preferences):
        manifest, tasks = research_execution.build_manifest_and_tasks(
            request_id="REQ_1", request_version=1, company_codes=["CLI_001", "CLI_002"],
            required_sources={EXT, INT}, prompt_by_company={"CLI_001": "p1", "CLI_002": "p2"},
            original_user_prompt="p", preferences=preferences, now=now,
        )
        assert len(manifest.expected_payload_keys) == 4
        assert len(tasks) == 4
        assert {(t.company_code, t.source_agent) for t in tasks} == {
            ("CLI_001", EXT), ("CLI_001", INT), ("CLI_002", EXT), ("CLI_002", INT),
        }

    def test_narrow_revision_only_augments_targeted_tasks(self, now, preferences):
        narrow = NarrowResearchRevision(
            company_codes=["CLI_001"], source_agents=[INT], guidance="Double-check the latest risk score."
        )
        _, tasks = research_execution.build_manifest_and_tasks(
            request_id="REQ_1", request_version=2, company_codes=["CLI_001", "CLI_002"],
            required_sources={EXT, INT}, prompt_by_company={"CLI_001": "p1", "CLI_002": "p2"},
            original_user_prompt="p", preferences=preferences, now=now, narrow_revision=narrow,
        )
        targeted = next(t for t in tasks if t.company_code == "CLI_001" and t.source_agent == INT)
        others = [t for t in tasks if not (t.company_code == "CLI_001" and t.source_agent == INT)]

        assert "Double-check the latest risk score." in targeted.prompt
        for t in others:
            assert "Double-check the latest risk score." not in t.prompt


class TestDispatchAndJoin:
    @pytest.mark.asyncio
    async def test_all_payloads_received_and_ready_for_synthesis(self, monkeypatch, now, preferences):
        monkeypatch.setattr(research_execution, "run_structured_specialist", _ok_answer)
        manifest, payloads = await research_execution.run_research_for_request(
            request_id="REQ_1", request_version=1, company_codes=["CLI_001"],
            required_sources={EXT, INT, NOTES}, prompt_by_company={"CLI_001": "p"},
            original_user_prompt="p", preferences=preferences, now=now,
        )
        assert len(payloads) == 3
        assert all(p.status == SourcePayloadStatus.COMPLETED for p in payloads)
        ensure_ready_for_synthesis(manifest, payloads)  # no raise

    @pytest.mark.asyncio
    async def test_evidence_carries_the_specialist_s_real_date_and_code(self, monkeypatch, now, preferences):
        """The structured-output path's whole point: no as_of_date fallback."""
        monkeypatch.setattr(research_execution, "run_structured_specialist", _ok_answer)
        _, payloads = await research_execution.run_research_for_request(
            request_id="REQ_1", request_version=1, company_codes=["CLI_001"],
            required_sources={INT}, prompt_by_company={"CLI_001": "p"},
            original_user_prompt="p", preferences=preferences, now=now,
        )
        [item] = payloads[0].evidence
        assert item.evidence_code == "RISK_004"
        assert item.date.isoformat() == "2026-07-01"

    @pytest.mark.asyncio
    async def test_valid_empty_payload_counts_as_received(self, monkeypatch, now, preferences):
        """A completed payload with no evidence/findings is not 'missing'."""
        monkeypatch.setattr(research_execution, "run_structured_specialist", _empty_answer)
        manifest, payloads = await research_execution.run_research_for_request(
            request_id="REQ_1", request_version=1, company_codes=["CLI_001"],
            required_sources={EXT}, prompt_by_company={"CLI_001": "p"},
            original_user_prompt="p", preferences=preferences, now=now,
        )
        assert payloads[0].status == SourcePayloadStatus.COMPLETED
        assert payloads[0].evidence == []
        assert payloads[0].findings == ""
        ensure_ready_for_synthesis(manifest, payloads)  # no raise -- empty is not missing

    @pytest.mark.asyncio
    async def test_one_source_exception_marks_failed(self, monkeypatch, now, preferences):
        monkeypatch.setattr(research_execution, "run_structured_specialist", _fail_for(INT))
        manifest, payloads = await research_execution.run_research_for_request(
            request_id="REQ_1", request_version=1, company_codes=["CLI_001"],
            required_sources={EXT, INT}, prompt_by_company={"CLI_001": "p"},
            original_user_prompt="p", preferences=preferences, now=now,
        )
        by_source = {p.source_agent: p for p in payloads}
        assert by_source[INT].status == SourcePayloadStatus.FAILED
        assert "specialist blew up" in by_source[INT].error
        assert by_source[EXT].status == SourcePayloadStatus.COMPLETED
        with pytest.raises(WorkflowInvariantError):
            ensure_ready_for_synthesis(manifest, payloads)

    @pytest.mark.asyncio
    async def test_one_source_timeout_marks_timed_out(self, monkeypatch, now, preferences):
        """INT's own execution timeout (90s, unpatched) never fires here --
        only the overall 1s manifest deadline can -- so INT ends up as one
        of the two *workflow* timeout flavors. Which one depends on whether
        EXT or INT happened to acquire the semaphore first (build_manifest_and_tasks
        iterates a set), so both are accepted; TestTimeoutAccounting below
        pins down each flavor individually with deterministic ordering."""
        monkeypatch.setattr(research_execution, "run_structured_specialist", _hang_for(INT, seconds=5))
        keys = [PayloadKey(company_code="CLI_001", source_agent=a) for a in (EXT, INT)]
        manifest = ResearchManifest.open(
            request_id="REQ_1", request_version=1, expected_payload_keys=keys, now=now, timeout_seconds=1
        )
        _, tasks = research_execution.build_manifest_and_tasks(
            request_id="REQ_1", request_version=1, company_codes=["CLI_001"],
            required_sources={EXT, INT}, prompt_by_company={"CLI_001": "p"},
            original_user_prompt="p", preferences=preferences, now=now,
        )
        payloads = await research_execution.dispatch_and_join(manifest, tasks)

        by_source = {p.source_agent: p for p in payloads}
        assert by_source[INT].status == SourcePayloadStatus.TIMED_OUT
        assert by_source[INT].error in (
            research_execution._WORKFLOW_TIMEOUT_BEFORE_START_MESSAGE,
            research_execution._WORKFLOW_TIMEOUT_DURING_EXECUTION_MESSAGE,
        )
        with pytest.raises(WorkflowInvariantError):
            ensure_ready_for_synthesis(manifest, payloads)

    @pytest.mark.asyncio
    async def test_timeout_in_isolation_does_not_fail_unblocked_sources(self, monkeypatch, now, preferences):
        """With concurrency > 1, a hung source times out without blocking a
        source that was never gated behind it. Both start immediately (no
        queueing at concurrency=2), so INT deterministically ends up
        during_execution, never before_start."""
        monkeypatch.setattr(research_execution, "run_structured_specialist", _hang_for(INT, seconds=5))
        monkeypatch.setattr(research_execution, "RESEARCH_CONCURRENCY", 2)
        keys = [PayloadKey(company_code="CLI_001", source_agent=a) for a in (EXT, INT)]
        manifest = ResearchManifest.open(
            request_id="REQ_1", request_version=1, expected_payload_keys=keys, now=now, timeout_seconds=1
        )
        _, tasks = research_execution.build_manifest_and_tasks(
            request_id="REQ_1", request_version=1, company_codes=["CLI_001"],
            required_sources={EXT, INT}, prompt_by_company={"CLI_001": "p"},
            original_user_prompt="p", preferences=preferences, now=now,
        )
        payloads = await research_execution.dispatch_and_join(manifest, tasks)

        by_source = {p.source_agent: p for p in payloads}
        assert by_source[EXT].status == SourcePayloadStatus.COMPLETED
        assert by_source[INT].status == SourcePayloadStatus.TIMED_OUT
        assert by_source[INT].error == research_execution._WORKFLOW_TIMEOUT_DURING_EXECUTION_MESSAGE

    @pytest.mark.asyncio
    async def test_multiple_companies_three_sources_each(self, monkeypatch, now, preferences):
        """Batch-processing semantics: 2 companies x 3 sources = 6 tasks, all
        completing independently. Every payload lands under its own correct
        (company_code, source_agent) key -- nothing gets cross-assigned --
        and the manifest is ready for synthesis exactly once."""
        monkeypatch.setattr(research_execution, "run_structured_specialist", _ok_answer)
        manifest, payloads = await research_execution.run_research_for_request(
            request_id="REQ_1", request_version=1, company_codes=["CLI_001", "CLI_002"],
            required_sources={EXT, INT, NOTES}, prompt_by_company={"CLI_001": "p1", "CLI_002": "p2"},
            original_user_prompt="p", preferences=preferences, now=now,
        )
        assert len(payloads) == 6
        assert all(p.status == SourcePayloadStatus.COMPLETED for p in payloads)
        keys = {(p.company_code, p.source_agent) for p in payloads}
        assert keys == {
            ("CLI_001", EXT), ("CLI_001", INT), ("CLI_001", NOTES),
            ("CLI_002", EXT), ("CLI_002", INT), ("CLI_002", NOTES),
        }
        ensure_ready_for_synthesis(manifest, payloads)  # no raise

    @pytest.mark.asyncio
    async def test_sources_completing_in_different_orders_still_produce_correct_payloads(
        self, monkeypatch, now, preferences
    ):
        """Companies and sources finish independently -- completion order
        must never scramble which payload lands under which key. Give each
        source a distinct, deliberately reversed-from-dispatch delay so the
        actual finish order is NOTES, INT, EXT for CLI_001 and
        NOTES, INT, EXT for CLI_002 (fastest to slowest is the reverse of
        dispatch iteration), and confirm every payload still resolves to its
        own correct company/source regardless."""
        monkeypatch.setattr(research_execution, "RESEARCH_CONCURRENCY", 6)
        delay_by_source = {EXT: 0.09, INT: 0.05, NOTES: 0.01}

        async def staggered(source_agent, prompt):
            await asyncio.sleep(delay_by_source[source_agent])
            return await _ok_answer(source_agent, prompt)

        monkeypatch.setattr(research_execution, "run_structured_specialist", staggered)
        manifest, payloads = await research_execution.run_research_for_request(
            request_id="REQ_1", request_version=1, company_codes=["CLI_001", "CLI_002"],
            required_sources={EXT, INT, NOTES}, prompt_by_company={"CLI_001": "p1", "CLI_002": "p2"},
            original_user_prompt="p", preferences=preferences, now=now,
        )
        assert len(payloads) == 6
        for payload in payloads:
            assert payload.status == SourcePayloadStatus.COMPLETED
            assert payload.evidence[0].evidence_code == _EVIDENCE_CODE_BY_SOURCE[payload.source_agent]
            assert f"Finding for {payload.source_agent.value}." == payload.findings
        ensure_ready_for_synthesis(manifest, payloads)  # no raise -- order of arrival never mattered

    @pytest.mark.asyncio
    async def test_no_synthesis_gate_after_incomplete_join(self, monkeypatch, now, preferences):
        """The acceptance criterion from the task spelled out directly: an
        incomplete join must never be treated as ready for synthesis."""
        monkeypatch.setattr(research_execution, "run_structured_specialist", _fail_for(NOTES))
        manifest, payloads = await research_execution.run_research_for_request(
            request_id="REQ_1", request_version=1, company_codes=["CLI_001"],
            required_sources={EXT, INT, NOTES}, prompt_by_company={"CLI_001": "p"},
            original_user_prompt="p", preferences=preferences, now=now,
        )
        synthesis_was_called = False

        try:
            ensure_ready_for_synthesis(manifest, payloads)
            synthesis_was_called = True  # would only be reached if the gate passed
        except WorkflowInvariantError:
            pass

        assert synthesis_was_called is False

    @pytest.mark.asyncio
    async def test_external_cancellation_cleans_up_still_running_specialist_tasks(
        self, monkeypatch, now, preferences
    ):
        """If dispatch_and_join itself is cancelled from outside (e.g. a
        user stops the request via api/server.py's cancel endpoint) while a
        specialist is still running, that specialist's own task must be
        cancelled and awaited too -- never left running detached from the
        event loop after this function stops, the same guarantee the
        ordinary timeout path already provides."""
        specialist_was_cancelled = asyncio.Event()

        async def hanging_specialist(source_agent, prompt):
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                specialist_was_cancelled.set()
                raise
            return await _ok_answer(source_agent, prompt)

        monkeypatch.setattr(research_execution, "run_structured_specialist", hanging_specialist)
        manifest, tasks = research_execution.build_manifest_and_tasks(
            request_id="REQ_1", request_version=1, company_codes=["CLI_001"],
            required_sources={EXT}, prompt_by_company={"CLI_001": "p"},
            original_user_prompt="p", preferences=preferences, now=now,
        )

        join_task = asyncio.create_task(research_execution.dispatch_and_join(manifest, tasks))
        await asyncio.sleep(0.05)  # let the specialist actually start and reach its own await point
        join_task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await join_task

        await asyncio.wait_for(specialist_was_cancelled.wait(), timeout=1)
        assert specialist_was_cancelled.is_set()


class TestNewSchemaSourceScoping:
    """Covers Goal A (REQ_1006): a request selecting only the new internal
    schema (company_profile/credit_exposure/deal_pipeline/
    internal_risk_flags -- what XOM/COST select in the golden demo
    scenario) must never let evidence from the legacy company_master/
    relationship_snapshot/opportunities/risk_assessment tables into its
    internal_data_agent payload, even if the specialist reports some (e.g.
    because it called a legacy tool despite the task prompt's instruction
    not to) -- the deterministic backstop in _build_evidence, not just the
    prompt, is what this test proves."""

    NEW_SCHEMA_DOMAIN_IDS = ["company_profile", "credit_exposure", "deal_pipeline", "internal_risk_flags"]

    @pytest.mark.asyncio
    async def test_new_schema_only_selection_drops_legacy_evidence_the_specialist_still_reported(
        self, monkeypatch, now, preferences
    ):
        async def mixed_new_and_legacy_answer(source_agent, prompt) -> SpecialistFindings:
            return SpecialistFindings(
                summary="Mixed new-schema and legacy findings.",
                evidence=[
                    SpecialistEvidenceItem(
                        evidence_code="EXP_XOM_TLB", date="2026-08-01", label="Credit facility",
                        detail="$850M Term Loan B, fully drawn, matures 2026-11-15.",
                    ),
                    SpecialistEvidenceItem(
                        evidence_code="DEAL_XOM_REFI", date="2026-08-01", label="CRM deal pipeline",
                        detail="Refinancing bond mandate, $4.2M potential fee.",
                    ),
                    SpecialistEvidenceItem(
                        evidence_code="RISKFLAG_XOM_MATURITY", date="2026-08-01", label="Internal risk flag",
                        detail="Maturity wall imminence.",
                    ),
                    # Legacy-schema codes the specialist should never have
                    # reported for this request -- get_company_research_context
                    # (the new schema's one tool) cannot produce these.
                    SpecialistEvidenceItem(
                        evidence_code="OPP_015", date="2026-08-30", label="Lost opportunity",
                        detail="Capital markets bond issuance mandate lost to a named competitor.",
                    ),
                    SpecialistEvidenceItem(
                        evidence_code="RISK_048", date="2026-07-01", label="Risk assessment",
                        detail="Relationship risk score worsening this quarter.",
                    ),
                ],
            )

        monkeypatch.setattr(research_execution, "run_structured_specialist", mixed_new_and_legacy_answer)

        _, payloads = await research_execution.run_research_for_request(
            request_id="REQ_1006", request_version=1, company_codes=["CLI_006"],
            required_sources={INT}, prompt_by_company={"CLI_006": "p"},
            original_user_prompt="p", preferences=preferences, now=now,
            data_domain_ids=self.NEW_SCHEMA_DOMAIN_IDS,
        )

        codes = {item.evidence_code for item in payloads[0].evidence}
        assert codes == {"EXP_XOM_TLB", "DEAL_XOM_REFI", "RISKFLAG_XOM_MATURITY"}
        assert "OPP_015" not in codes
        assert "RISK_048" not in codes


class TestComputeResearchWorkflowTimeoutSeconds:
    """Unit coverage of the formula itself, independent of the async
    dispatch machinery: ceil(number_of_tasks / concurrency) *
    execution_timeout + overhead, with the legacy env var overriding
    everything and an explicit override validated (warned, not clamped)
    against the formula's own minimum."""

    def test_calculates_from_task_count_and_concurrency(self, monkeypatch):
        monkeypatch.setattr(research_execution, "INSIGHTS_SOURCE_JOIN_TIMEOUT_SECONDS", None)
        monkeypatch.setattr(research_execution, "INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_SECONDS", None)
        monkeypatch.setattr(research_execution, "INSIGHTS_SOURCE_EXECUTION_TIMEOUT_SECONDS", 90.0)
        monkeypatch.setattr(research_execution, "INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_OVERHEAD_SECONDS", 30.0)
        monkeypatch.setattr(research_execution, "RESEARCH_CONCURRENCY", 1)

        assert research_execution.compute_research_workflow_timeout_seconds(3) == 3 * 90.0 + 30.0

    def test_rounds_up_for_uneven_division(self, monkeypatch):
        monkeypatch.setattr(research_execution, "INSIGHTS_SOURCE_JOIN_TIMEOUT_SECONDS", None)
        monkeypatch.setattr(research_execution, "INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_SECONDS", None)
        monkeypatch.setattr(research_execution, "INSIGHTS_SOURCE_EXECUTION_TIMEOUT_SECONDS", 90.0)
        monkeypatch.setattr(research_execution, "INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_OVERHEAD_SECONDS", 30.0)
        monkeypatch.setattr(research_execution, "RESEARCH_CONCURRENCY", 3)

        # 8 tasks / concurrency 3 -> ceil(2.67) = 3 sequential rounds.
        assert research_execution.compute_research_workflow_timeout_seconds(8) == 3 * 90.0 + 30.0

    def test_legacy_override_takes_precedence_over_everything(self, monkeypatch):
        monkeypatch.setattr(research_execution, "INSIGHTS_SOURCE_JOIN_TIMEOUT_SECONDS", 45.0)
        monkeypatch.setattr(research_execution, "INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_SECONDS", 999.0)

        assert research_execution.compute_research_workflow_timeout_seconds(10) == 45.0

    def test_explicit_workflow_timeout_is_used_even_when_below_the_formula_minimum(self, monkeypatch, caplog):
        monkeypatch.setattr(research_execution, "INSIGHTS_SOURCE_JOIN_TIMEOUT_SECONDS", None)
        monkeypatch.setattr(research_execution, "INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_SECONDS", 10.0)
        monkeypatch.setattr(research_execution, "INSIGHTS_SOURCE_EXECUTION_TIMEOUT_SECONDS", 90.0)
        monkeypatch.setattr(research_execution, "INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_OVERHEAD_SECONDS", 30.0)
        monkeypatch.setattr(research_execution, "RESEARCH_CONCURRENCY", 1)

        with caplog.at_level("WARNING", logger="insights_assistant.agents.research_execution"):
            result = research_execution.compute_research_workflow_timeout_seconds(3)

        assert result == 10.0  # respected as configured, never silently clamped up
        assert any("less than" in record.message for record in caplog.records)


class TestTimeoutAccounting:
    """Regression coverage for the timeout-accounting fix: a queued
    specialist must never consume its own execution budget while merely
    waiting for an earlier one to finish, and the overall workflow deadline
    must still be a real safety net independent of per-specialist timing."""

    @pytest.mark.asyncio
    async def test_queued_tasks_do_not_time_out_merely_while_waiting(self, monkeypatch, now, preferences):
        """The bug this fix targets: with concurrency=1 and 3 tasks whose
        combined real duration (3 * 0.15s = 0.45s) would have exceeded a
        single shared 0.3s deadline under the old design, each task instead
        gets its OWN fresh 0.3s execution window once it starts -- so all
        three complete."""
        _use_calculated_workflow_timeout(monkeypatch)
        monkeypatch.setattr(research_execution, "INSIGHTS_SOURCE_EXECUTION_TIMEOUT_SECONDS", 0.3)
        monkeypatch.setattr(research_execution, "RESEARCH_CONCURRENCY", 1)

        async def slow_ok_answer(source_agent, prompt):
            await asyncio.sleep(0.15)
            return await _ok_answer(source_agent, prompt)

        monkeypatch.setattr(research_execution, "run_structured_specialist", slow_ok_answer)

        manifest, payloads = await research_execution.run_research_for_request(
            request_id="REQ_1", request_version=1, company_codes=["CLI_001"],
            required_sources={EXT, INT, NOTES}, prompt_by_company={"CLI_001": "p"},
            original_user_prompt="p", preferences=preferences, now=now,
        )

        assert len(payloads) == 3
        assert all(p.status == SourcePayloadStatus.COMPLETED for p in payloads), [
            (p.source_agent.value, p.status.value, p.error) for p in payloads
        ]
        ensure_ready_for_synthesis(manifest, payloads)  # no raise

    @pytest.mark.asyncio
    async def test_actively_running_slow_specialist_receives_execution_timeout(
        self, monkeypatch, now, preferences
    ):
        """A specialist that runs past its OWN execution timeout gets
        execution_timeout specifically -- not one of the workflow-level
        messages -- even though the overall deadline (generously computed)
        never comes close to firing."""
        _use_calculated_workflow_timeout(monkeypatch)
        monkeypatch.setattr(research_execution, "INSIGHTS_SOURCE_EXECUTION_TIMEOUT_SECONDS", 0.1)
        monkeypatch.setattr(research_execution, "run_structured_specialist", _hang_for(INT, seconds=5))

        manifest, tasks = research_execution.build_manifest_and_tasks(
            request_id="REQ_1", request_version=1, company_codes=["CLI_001"],
            required_sources={INT}, prompt_by_company={"CLI_001": "p"},
            original_user_prompt="p", preferences=preferences, now=now,
        )
        payloads = await research_execution.dispatch_and_join(manifest, tasks)

        [payload] = payloads
        assert payload.status == SourcePayloadStatus.TIMED_OUT
        assert payload.error == research_execution._EXECUTION_TIMEOUT_MESSAGE

    @pytest.mark.asyncio
    async def test_overall_workflow_deadline_terminates_a_task_still_running(
        self, monkeypatch, now, preferences
    ):
        """The overall deadline is a hard outer bound even when a
        specialist's own execution timeout is generous enough that it would
        never fire on its own."""
        monkeypatch.setattr(research_execution, "INSIGHTS_SOURCE_EXECUTION_TIMEOUT_SECONDS", 90.0)
        monkeypatch.setattr(research_execution, "run_structured_specialist", _hang_for(INT, seconds=5))

        keys = [PayloadKey(company_code="CLI_001", source_agent=INT)]
        manifest = ResearchManifest.open(
            request_id="REQ_1", request_version=1, expected_payload_keys=keys, now=now, timeout_seconds=0.1,
        )
        _, tasks = research_execution.build_manifest_and_tasks(
            request_id="REQ_1", request_version=1, company_codes=["CLI_001"],
            required_sources={INT}, prompt_by_company={"CLI_001": "p"},
            original_user_prompt="p", preferences=preferences, now=now,
        )
        payloads = await research_execution.dispatch_and_join(manifest, tasks)

        [payload] = payloads
        assert payload.status == SourcePayloadStatus.TIMED_OUT
        assert payload.error == research_execution._WORKFLOW_TIMEOUT_DURING_EXECUTION_MESSAGE

    @pytest.mark.asyncio
    async def test_overall_workflow_deadline_before_a_queued_task_starts(self, monkeypatch, now, preferences):
        """A second task that never gets a turn (concurrency=1, the first
        task holds the semaphore past the overall deadline) is reported as
        before_start, distinctly from the first task's during_execution --
        task order is controlled explicitly here (not via a set) so the
        outcome is deterministic."""
        monkeypatch.setattr(research_execution, "INSIGHTS_SOURCE_EXECUTION_TIMEOUT_SECONDS", 90.0)
        monkeypatch.setattr(research_execution, "RESEARCH_CONCURRENCY", 1)
        monkeypatch.setattr(research_execution, "run_structured_specialist", _hang_for(EXT, seconds=5))

        first_task = ResearchTask(
            request_id="REQ_1", request_version=1, company_code="CLI_001", source_agent=EXT,
            prompt="p", original_user_prompt="p", preferences=preferences, created_at=now,
        )
        second_task = ResearchTask(
            request_id="REQ_1", request_version=1, company_code="CLI_001", source_agent=INT,
            prompt="p", original_user_prompt="p", preferences=preferences, created_at=now,
        )
        manifest = ResearchManifest.open(
            request_id="REQ_1", request_version=1,
            expected_payload_keys=[first_task.key, second_task.key], now=now, timeout_seconds=0.2,
        )

        payloads = await research_execution.dispatch_and_join(manifest, [first_task, second_task])

        by_source = {p.source_agent: p for p in payloads}
        assert by_source[EXT].status == SourcePayloadStatus.TIMED_OUT
        assert by_source[EXT].error == research_execution._WORKFLOW_TIMEOUT_DURING_EXECUTION_MESSAGE
        assert by_source[INT].status == SourcePayloadStatus.TIMED_OUT
        assert by_source[INT].error == research_execution._WORKFLOW_TIMEOUT_BEFORE_START_MESSAGE
        # INT never started -- its started_at falls back to its task's created_at.
        assert by_source[INT].started_at == now

    @pytest.mark.asyncio
    async def test_started_at_occurs_after_semaphore_acquisition(self, monkeypatch, now, preferences):
        """With concurrency=1, the second task's started_at must reflect
        when it actually began running (after the first released the
        semaphore), not when its ResearchTask was created."""
        _use_calculated_workflow_timeout(monkeypatch)
        monkeypatch.setattr(research_execution, "RESEARCH_CONCURRENCY", 1)

        async def slow_ok_answer(source_agent, prompt):
            await asyncio.sleep(0.1)
            return await _ok_answer(source_agent, prompt)

        monkeypatch.setattr(research_execution, "run_structured_specialist", slow_ok_answer)

        manifest, payloads = await research_execution.run_research_for_request(
            request_id="REQ_1", request_version=1, company_codes=["CLI_001"],
            required_sources={EXT, INT}, prompt_by_company={"CLI_001": "p"},
            original_user_prompt="p", preferences=preferences, now=now,
        )

        for payload in payloads:
            assert payload.started_at > now  # never equal to task creation time

        first, second = sorted(payloads, key=lambda p: p.started_at)
        assert (second.started_at - first.started_at).total_seconds() >= 0.05

    @pytest.mark.asyncio
    async def test_cancelled_tasks_are_fully_awaited_before_dispatch_and_join_returns(
        self, monkeypatch, now, preferences
    ):
        """No background model/tool call is left detached: a fake specialist
        that does cleanup in a finally block must have that cleanup
        observably complete by the time dispatch_and_join returns, which
        only holds if the cancelled task was actually awaited (not just
        told to cancel)."""
        monkeypatch.setattr(research_execution, "INSIGHTS_SOURCE_EXECUTION_TIMEOUT_SECONDS", 90.0)
        cleanup_marker: list[EvidenceSourceAgent] = []

        async def hang_then_cleanup(source_agent, prompt):
            try:
                await asyncio.sleep(5)
            finally:
                cleanup_marker.append(source_agent)
            return await _ok_answer(source_agent, prompt)

        monkeypatch.setattr(research_execution, "run_structured_specialist", hang_then_cleanup)

        keys = [PayloadKey(company_code="CLI_001", source_agent=INT)]
        manifest = ResearchManifest.open(
            request_id="REQ_1", request_version=1, expected_payload_keys=keys, now=now, timeout_seconds=0.1,
        )
        _, tasks = research_execution.build_manifest_and_tasks(
            request_id="REQ_1", request_version=1, company_codes=["CLI_001"],
            required_sources={INT}, prompt_by_company={"CLI_001": "p"},
            original_user_prompt="p", preferences=preferences, now=now,
        )

        payloads = await research_execution.dispatch_and_join(manifest, tasks)

        assert payloads[0].status == SourcePayloadStatus.TIMED_OUT
        assert cleanup_marker == [INT]  # the finally block already ran

    @pytest.mark.asyncio
    async def test_no_synthesis_gate_after_execution_timeout(self, monkeypatch, now, preferences):
        """Synthesis must never run after a real timeout -- proven here for
        the execution_timeout path specifically (test_no_synthesis_gate_after_incomplete_join
        above already covers a plain exception's FAILED outcome)."""
        _use_calculated_workflow_timeout(monkeypatch)
        monkeypatch.setattr(research_execution, "INSIGHTS_SOURCE_EXECUTION_TIMEOUT_SECONDS", 0.05)
        monkeypatch.setattr(research_execution, "run_structured_specialist", _hang_for(INT, seconds=5))

        manifest, payloads = await research_execution.run_research_for_request(
            request_id="REQ_1", request_version=1, company_codes=["CLI_001"],
            required_sources={EXT, INT}, prompt_by_company={"CLI_001": "p"},
            original_user_prompt="p", preferences=preferences, now=now,
        )

        by_source = {p.source_agent: p for p in payloads}
        assert by_source[INT].status == SourcePayloadStatus.TIMED_OUT
        assert by_source[INT].error == research_execution._EXECUTION_TIMEOUT_MESSAGE

        with pytest.raises(WorkflowInvariantError):
            ensure_ready_for_synthesis(manifest, payloads)


class TestVersionAndDuplicateInvariantsAtThisLayer:
    @pytest.mark.asyncio
    async def test_revision_run_never_produces_old_version_payloads(self, monkeypatch, now, preferences):
        monkeypatch.setattr(research_execution, "run_structured_specialist", _ok_answer)
        _, v1_payloads = await research_execution.run_research_for_request(
            request_id="REQ_1", request_version=1, company_codes=["CLI_001"],
            required_sources={EXT}, prompt_by_company={"CLI_001": "p"},
            original_user_prompt="p", preferences=preferences, now=now,
        )
        _, v2_payloads = await research_execution.run_research_for_request(
            request_id="REQ_1", request_version=2, company_codes=["CLI_001"],
            required_sources={EXT}, prompt_by_company={"CLI_001": "p"},
            original_user_prompt="p", preferences=preferences, now=now,
        )
        assert all(p.request_version == 1 for p in v1_payloads)
        assert all(p.request_version == 2 for p in v2_payloads)

        # Mixing them must be rejected by the shared invariant layer.
        keys = [PayloadKey(company_code="CLI_001", source_agent=EXT)]
        manifest_v2 = ResearchManifest.open(request_id="REQ_1", request_version=2, expected_payload_keys=keys, now=now)
        with pytest.raises(WorkflowInvariantError, match="must never be mixed"):
            ensure_ready_for_synthesis(manifest_v2, v1_payloads + v2_payloads)

    @pytest.mark.asyncio
    async def test_duplicate_payload_for_same_key_rejected(self, monkeypatch, now, preferences):
        monkeypatch.setattr(research_execution, "run_structured_specialist", _ok_answer)
        manifest, payloads = await research_execution.run_research_for_request(
            request_id="REQ_1", request_version=1, company_codes=["CLI_001"],
            required_sources={EXT}, prompt_by_company={"CLI_001": "p"},
            original_user_prompt="p", preferences=preferences, now=now,
        )
        duplicated = payloads + payloads
        with pytest.raises(WorkflowInvariantError, match="duplicate SourcePayload"):
            ensure_ready_for_synthesis(manifest, duplicated)


class TestApplyResearchRevision:
    def test_rejects_non_revise_research_decision(self, now):
        state = WorkflowState.start("REQ_1", occurred_at=now)
        decision = ReviewDecision(
            decision=ReviewDecisionType.PASS, request_id="REQ_1", request_version=1,
            package_version=1, comments="fine", created_at=now,
        )
        with pytest.raises(ValueError, match="requires decision=revise_research"):
            research_execution.apply_research_revision(state, decision, occurred_at=now)

    def test_successful_research_revision(self, now):
        state = WorkflowState.start("REQ_1", occurred_at=now)
        narrow = NarrowResearchRevision(company_codes=["CLI_001"], source_agents=[EXT], guidance="Look again.")
        decision = ReviewDecision(
            decision=ReviewDecisionType.REVISE_RESEARCH, request_id="REQ_1", request_version=1,
            package_version=1, comments="evidence looked stale", created_at=now,
            narrow_research_revision=narrow,
        )
        revised = research_execution.apply_research_revision(state, decision, occurred_at=now)

        assert revised.request_version == 2
        assert revised.research_revision_count == 1
        assert revised.current_stage == WorkflowStage.REVISING_RESEARCH
        assert revised.active_research_revision == narrow
        assert revised.terminal_error is None

    def test_second_research_revision_rejected_with_bounded_retry_reason(self, now):
        state = WorkflowState.start("REQ_1", occurred_at=now)
        narrow = NarrowResearchRevision(company_codes=["CLI_001"], source_agents=[EXT], guidance="Look again.")
        decision = ReviewDecision(
            decision=ReviewDecisionType.REVISE_RESEARCH, request_id="REQ_1", request_version=1,
            package_version=1, comments="c", created_at=now, narrow_research_revision=narrow,
        )
        once_revised = research_execution.apply_research_revision(state, decision, occurred_at=now)

        second_decision = ReviewDecision(
            decision=ReviewDecisionType.REVISE_RESEARCH, request_id="REQ_1", request_version=2,
            package_version=1, comments="still not good enough", created_at=now, narrow_research_revision=narrow,
        )
        rejected = research_execution.apply_research_revision(once_revised, second_decision, occurred_at=now)

        assert rejected.current_stage == WorkflowStage.FAILED
        assert rejected.request_version == 2  # unchanged -- the second attempt never took effect
        assert rejected.research_revision_count == 1  # unchanged
        assert "bounded-retry" in rejected.terminal_error

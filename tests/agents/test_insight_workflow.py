"""Covers agents/insight_workflow.py: the deterministic research -> synthesize
-> review state machine, both revision budgets (independent, max one each),
and every terminal condition. research_execution.run_research_for_request,
agents.synthesizer.synthesize_insight_package, and agents.reviewer.
review_insight_package are all monkeypatched directly on the insight_workflow
module -- these tests exercise the real budget-enforcement code
(apply_research_revision / apply_synthesis_revision) and the real loop
routing, never a real LLM/MCP server.
"""

from datetime import datetime, timezone

import pytest

import insights_assistant.agents.insight_workflow as insight_workflow
from insights_assistant.agents.synthesizer import SynthesisRevisionValidationError
from insights_assistant.contracts.api.enums import (
    ClaimType,
    EvidenceSourceAgent,
    InsightCategory,
    InsightPersona,
    InsightPriority,
    InsightSubtype,
    RankingCriterion,
)
from insights_assistant.contracts.api.evidence import BusinessImpact, EvidenceItem
from insights_assistant.contracts.api.requests import InsightRequirementsSelection
from insights_assistant.contracts.api.requests import RequestInsightCategory as ReqCategory
from insights_assistant.contracts.workflow.enums import ReviewDecisionType, SourcePayloadStatus, WorkflowStage
from insights_assistant.contracts.workflow.packages import InsightPackage, RankedInsight, UnmetRequirement
from insights_assistant.contracts.workflow.research import PayloadKey, ResearchManifest
from insights_assistant.contracts.workflow.review import NarrowResearchRevision, ReviewDecision

INT = EvidenceSourceAgent.INTERNAL_DATA_AGENT


def _requirements() -> InsightRequirementsSelection:
    return InsightRequirementsSelection(
        total_count=5,
        categories=[ReqCategory(category_id=InsightCategory.CREDIT_RISK, minimum_count=1)],
        ranking_criteria=[RankingCriterion.CONFIDENCE],
        max_insights_per_company=None,
    )


def _build_package_from_payloads(
    request_id, request_version, package_version, preferences, source_payloads, *, unmet=None
) -> InsightPackage:
    insights = [
        RankedInsight(
            insight_id=f"PKG_{request_id}_{package_version}_INS_{i}",
            rank=i + 1,
            company_code=payload.company_code,
            category=InsightCategory.RELATIONSHIP_RISK,
            subtype=InsightSubtype.RELATIONSHIP_RISK,
            primary_claim=ClaimType.RELATIONSHIP_RISK_WORSENING,
            persona=InsightPersona.CREDIT_OFFICER,
            priority=InsightPriority.HIGH,
            title=f"Insight for {payload.company_code}",
            finding="Finding.",
            why_it_matters="Matters.",
            recommended_action="Act.",
            confidence=80,
            confidence_rationale="Rationale.",
            business_impact=BusinessImpact(exposure_usd=100_000, description="Impact"),
            evidence=payload.evidence,
        )
        for i, payload in enumerate(source_payloads)
        if payload.evidence
    ]
    return InsightPackage(
        request_id=request_id, request_version=request_version, package_version=package_version,
        original_user_prompt="p", effective_research_prompt="p", preferences=preferences,
        source_payload_refs=[p.key for p in source_payloads],
        insights=insights, unmet_requirements=unmet or [], created_at=datetime.now(timezone.utc),
    )


def make_fake_run_research(evidence_code="RISK_004", evidence_date="2026-07-01"):
    calls = []

    async def _fake(
        *, request_id, request_version, company_codes, required_sources, prompt_by_company,
        original_user_prompt, preferences, narrow_revision=None, now=None, data_domain_ids=None,
    ):
        calls.append({"request_version": request_version, "narrow_revision": narrow_revision})
        moment = now or datetime.now(timezone.utc)
        keys = [PayloadKey(company_code=c, source_agent=s) for c in company_codes for s in required_sources]
        manifest = ResearchManifest.open(
            request_id=request_id, request_version=request_version, expected_payload_keys=keys, now=moment
        )
        from insights_assistant.contracts.workflow.research import SourcePayload

        payloads = [
            SourcePayload(
                request_id=request_id, request_version=request_version, company_code=c, source_agent=s,
                status=SourcePayloadStatus.COMPLETED,
                evidence=[
                    EvidenceItem(
                        id=f"EV_{c}_{s.value}", source_agent=s, source_type="internal",
                        evidence_code=evidence_code, label="Risk assessment", detail="Score rose.",
                        date=evidence_date,
                    )
                ],
                findings="Risk score climbed.", started_at=moment, completed_at=moment,
            )
            for c in company_codes for s in required_sources
        ]
        return manifest, payloads

    _fake.calls = calls
    return _fake


def make_fake_synthesize(unmet=None):
    calls = []

    async def _fake(
        *, request_id, request_version, package_version, original_user_prompt, effective_research_prompt,
        preferences, insight_requirements, manifest, source_payloads, reviewer_comments=None,
        affected_insight_ids=None, previous_package=None,
    ):
        calls.append({
            "package_version": package_version, "reviewer_comments": reviewer_comments,
            "affected_insight_ids": affected_insight_ids, "previous_package": previous_package,
        })
        return _build_package_from_payloads(
            request_id, request_version, package_version, preferences, source_payloads, unmet=unmet
        )

    _fake.calls = calls
    return _fake


def _pass_decision(package, comments="Looks good."):
    return ReviewDecision(
        decision=ReviewDecisionType.PASS, request_id=package.request_id, request_version=package.request_version,
        package_version=package.package_version, comments=comments, created_at=datetime.now(timezone.utc),
    )


def _fail_decision(package, comments="Not fixable."):
    return ReviewDecision(
        decision=ReviewDecisionType.FAIL, request_id=package.request_id, request_version=package.request_version,
        package_version=package.package_version, comments=comments, created_at=datetime.now(timezone.utc),
    )


def _revise_insights_decision(package, comments="Fix wording."):
    insight_id = package.insights[0].insight_id if package.insights else "PKG_MISSING"
    return ReviewDecision(
        decision=ReviewDecisionType.REVISE_INSIGHTS, request_id=package.request_id,
        request_version=package.request_version, package_version=package.package_version,
        comments=comments, created_at=datetime.now(timezone.utc), affected_insight_ids=[insight_id],
    )


def _revise_research_decision(package, comments="Data looks stale.", company_codes=None, source_agents=None):
    narrow = NarrowResearchRevision(
        company_codes=company_codes or ["CLI_001"], source_agents=source_agents or [INT],
        guidance="Re-check the latest data.",
    )
    return ReviewDecision(
        decision=ReviewDecisionType.REVISE_RESEARCH, request_id=package.request_id,
        request_version=package.request_version, package_version=package.package_version,
        comments=comments, created_at=datetime.now(timezone.utc), narrow_research_revision=narrow,
        affected_source_agents=narrow.source_agents,
    )


class _ReviewSequence:
    """Consumes one decision-factory per call, in order. Raises if the loop
    calls review more times than the test expected -- that would mean a
    revision budget wasn't enforced."""

    def __init__(self, *decision_factories):
        self._factories = list(decision_factories)
        self.calls = 0

    async def __call__(self, *, insight_requirements, manifest, source_payloads, package):
        if self.calls >= len(self._factories):
            raise AssertionError(f"review_insight_package called more than the expected {len(self._factories)} times")
        factory = self._factories[self.calls]
        self.calls += 1
        return factory(package)


def _install(monkeypatch, *, run_research=None, synthesize=None, review=None):
    run_research = run_research or make_fake_run_research()
    synthesize = synthesize or make_fake_synthesize()
    monkeypatch.setattr(insight_workflow, "run_research_for_request", run_research)
    monkeypatch.setattr(insight_workflow, "synthesize_insight_package", synthesize)
    monkeypatch.setattr(insight_workflow, "review_insight_package", review)
    return run_research, synthesize, review


def _pin_max_synthesis_revisions(monkeypatch, value: int):
    """INSIGHTS_MAX_SYNTHESIS_REVISIONS is read as a bare module-level name
    in two places (agents.synthesizer.apply_synthesis_revision and
    contracts.workflow.state.WorkflowState.with_synthesis_revision) --
    both need pinning so a test's expected behavior doesn't depend on
    ambient .env state or import order."""
    import insights_assistant.agents.synthesizer as synthesizer_module
    import insights_assistant.contracts.workflow.state as state_module

    monkeypatch.setattr(synthesizer_module, "INSIGHTS_MAX_SYNTHESIS_REVISIONS", value)
    monkeypatch.setattr(state_module, "INSIGHTS_MAX_SYNTHESIS_REVISIONS", value)


def make_fake_synthesize_with_validation_retry(*, fail_times: int, unmet=None):
    """Like make_fake_synthesize, but raises SynthesisRevisionValidationError
    the first `fail_times` calls for any revision attempt (affected_insight_ids
    set) at a given package_version, then succeeds -- models a single
    reviewer-driven revision whose own synthesis output needs one or more
    internal retries before it satisfies the revision-feedback contract.
    Never raises on the initial (non-revision) call, matching production:
    synthesize_insight_package can only raise this when affected_insight_ids
    is given."""

    calls: list[dict] = []
    attempts_by_package_version: dict[int, int] = {}

    async def _fake(
        *, request_id, request_version, package_version, original_user_prompt, effective_research_prompt,
        preferences, insight_requirements, manifest, source_payloads, reviewer_comments=None,
        affected_insight_ids=None, previous_package=None,
    ):
        calls.append({
            "package_version": package_version, "reviewer_comments": reviewer_comments,
            "affected_insight_ids": affected_insight_ids, "previous_package": previous_package,
        })
        if affected_insight_ids:
            attempts_by_package_version[package_version] = attempts_by_package_version.get(package_version, 0) + 1
            if attempts_by_package_version[package_version] <= fail_times:
                raise SynthesisRevisionValidationError(
                    f"attempt {attempts_by_package_version[package_version]} for package_version="
                    f"{package_version} did not satisfy the revision-feedback contract (simulated)"
                )
        return _build_package_from_payloads(
            request_id, request_version, package_version, preferences, source_payloads, unmet=unmet
        )

    _fake.calls = calls
    return _fake


class TestRunInsightWorkflow:
    @pytest.mark.asyncio
    async def test_pass_on_first_review(self, monkeypatch, now, preferences):
        run_research, synthesize, review = _install(monkeypatch, review=_ReviewSequence(_pass_decision))

        state, package, source_payloads, review_decision = await insight_workflow.run_insight_workflow(
            request_id="REQ_1", company_codes=["CLI_001"], required_sources={INT},
            prompt_by_company={"CLI_001": "p"}, original_user_prompt="p", preferences=preferences,
            insight_requirements=_requirements(), now=now,
        )

        assert state.current_stage == WorkflowStage.COMPLETED
        assert state.terminal_error is None
        assert package is not None
        assert package.package_version == 1
        assert package.request_version == 1
        assert [i.rank for i in package.insights] == list(range(1, len(package.insights) + 1))
        assert len(run_research.calls) == 1
        assert len(synthesize.calls) == 1
        assert review.calls == 1
        assert source_payloads  # returned even on success
        assert review_decision is not None
        assert review_decision.decision == ReviewDecisionType.PASS

    @pytest.mark.asyncio
    async def test_one_synthesis_revision_then_pass(self, monkeypatch, now, preferences):
        run_research, synthesize, review = _install(
            monkeypatch, review=_ReviewSequence(_revise_insights_decision, _pass_decision)
        )

        state, package, _, review_decision = await insight_workflow.run_insight_workflow(
            request_id="REQ_1", company_codes=["CLI_001"], required_sources={INT},
            prompt_by_company={"CLI_001": "p"}, original_user_prompt="p", preferences=preferences,
            insight_requirements=_requirements(), now=now,
        )

        assert state.current_stage == WorkflowStage.COMPLETED
        assert state.synthesis_revision_count == 1
        assert state.research_revision_count == 0
        assert package is not None
        assert package.package_version == 2
        assert package.request_version == 1  # unchanged -- only synthesis was redone
        assert len(run_research.calls) == 1  # research never re-ran
        assert len(synthesize.calls) == 2
        assert review.calls == 2
        assert synthesize.calls[1]["reviewer_comments"] == "Fix wording."
        assert review_decision.decision == ReviewDecisionType.PASS  # the LAST decision, not the first

    @pytest.mark.asyncio
    async def test_two_synthesis_revisions_then_pass(self, monkeypatch, now, preferences):
        """A request may enter synthesis revision twice under the default
        limit (INSIGHTS_MAX_SYNTHESIS_REVISIONS=2) and still complete."""
        _pin_max_synthesis_revisions(monkeypatch, 2)
        run_research, synthesize, review = _install(
            monkeypatch,
            review=_ReviewSequence(_revise_insights_decision, _revise_insights_decision, _pass_decision),
        )

        state, package, _, review_decision = await insight_workflow.run_insight_workflow(
            request_id="REQ_1", company_codes=["CLI_001"], required_sources={INT},
            prompt_by_company={"CLI_001": "p"}, original_user_prompt="p", preferences=preferences,
            insight_requirements=_requirements(), now=now,
        )

        assert state.current_stage == WorkflowStage.COMPLETED
        assert state.synthesis_revision_count == 2
        assert state.research_revision_count == 0
        assert package is not None
        assert package.package_version == 3
        assert package.request_version == 1  # unchanged -- only synthesis was redone, twice
        assert len(run_research.calls) == 1  # research never re-ran
        assert len(synthesize.calls) == 3
        assert review.calls == 3
        assert review_decision.decision == ReviewDecisionType.PASS

    @pytest.mark.asyncio
    async def test_third_synthesis_revision_request_fails(self, monkeypatch, now, preferences):
        """A third reviewer-requested synthesis revision is rejected once
        the configured limit (default 2) is exhausted."""
        _pin_max_synthesis_revisions(monkeypatch, 2)
        run_research, synthesize, review = _install(
            monkeypatch,
            review=_ReviewSequence(
                _revise_insights_decision, _revise_insights_decision, _revise_insights_decision
            ),
        )

        state, package, _, _ = await insight_workflow.run_insight_workflow(
            request_id="REQ_1", company_codes=["CLI_001"], required_sources={INT},
            prompt_by_company={"CLI_001": "p"}, original_user_prompt="p", preferences=preferences,
            insight_requirements=_requirements(), now=now,
        )

        assert state.current_stage == WorkflowStage.FAILED
        assert package is None
        assert state.synthesis_revision_count == 2  # unchanged -- the 3rd attempt never took effect
        assert "bounded-retry" in state.terminal_error
        assert "at most 2 synthesis revision(s)" in state.terminal_error
        assert review.calls == 3  # never a 4th review call
        assert len(synthesize.calls) == 3  # initial + 2 accepted revisions; never a 3rd revision's synthesis

    @pytest.mark.asyncio
    async def test_internal_validation_retry_does_not_consume_reviewer_revision_allowance(
        self, monkeypatch, now, preferences
    ):
        """A single revision attempt whose own synthesis output fails the
        deterministic revision-feedback check once, then succeeds on an
        internal retry, must not be treated as a second reviewer-driven
        revision: synthesis_revision_count and package_version each advance
        by exactly one for the whole attempt, and the Reviewer never sees
        the internally-failed draft."""
        _pin_max_synthesis_revisions(monkeypatch, 2)
        monkeypatch.setattr(insight_workflow, "INSIGHTS_SYNTHESIS_VALIDATION_RETRY_LIMIT", 2)
        synthesize = make_fake_synthesize_with_validation_retry(fail_times=1)
        run_research, _, review = _install(
            monkeypatch, synthesize=synthesize, review=_ReviewSequence(_revise_insights_decision, _pass_decision)
        )

        state, package, _, review_decision = await insight_workflow.run_insight_workflow(
            request_id="REQ_1", company_codes=["CLI_001"], required_sources={INT},
            prompt_by_company={"CLI_001": "p"}, original_user_prompt="p", preferences=preferences,
            insight_requirements=_requirements(), now=now,
        )

        assert state.current_stage == WorkflowStage.COMPLETED
        assert state.synthesis_revision_count == 1  # exactly one reviewer-driven revision, despite 2 synth calls
        assert package is not None
        assert package.package_version == 2  # the internal retry never bumped package_version
        assert review.calls == 2  # initial + one review of the eventually-valid revision -- never a 3rd
        assert len(synthesize.calls) == 3  # initial call + 2 attempts for the one revision (1 failed, 1 succeeded)
        assert review_decision.decision == ReviewDecisionType.PASS

    @pytest.mark.asyncio
    async def test_internal_validation_retry_exhausted_still_fails_terminally(self, monkeypatch, now, preferences):
        """Requirement: do not introduce an unbounded loop -- once every
        internal retry is exhausted, this is still a terminal failure, and
        the Reviewer is never consulted about a package known not to have
        resolved the feedback."""
        _pin_max_synthesis_revisions(monkeypatch, 2)
        monkeypatch.setattr(insight_workflow, "INSIGHTS_SYNTHESIS_VALIDATION_RETRY_LIMIT", 2)
        synthesize = make_fake_synthesize_with_validation_retry(fail_times=99)  # always invalid
        run_research, _, review = _install(
            monkeypatch, synthesize=synthesize, review=_ReviewSequence(_revise_insights_decision)
        )

        state, package, _, _ = await insight_workflow.run_insight_workflow(
            request_id="REQ_1", company_codes=["CLI_001"], required_sources={INT},
            prompt_by_company={"CLI_001": "p"}, original_user_prompt="p", preferences=preferences,
            insight_requirements=_requirements(), now=now,
        )

        assert state.current_stage == WorkflowStage.FAILED
        assert package is None
        assert state.synthesis_revision_count == 1  # the reviewer-driven budget was still only spent once
        assert "synthesis revision validation failed after 2 internal attempt(s)" in state.terminal_error
        assert review.calls == 1  # never reaches a second review call
        assert len(synthesize.calls) == 3  # initial call + 2 exhausted internal attempts

    @pytest.mark.asyncio
    async def test_one_research_revision_then_pass(self, monkeypatch, now, preferences):
        run_research, synthesize, review = _install(
            monkeypatch, review=_ReviewSequence(_revise_research_decision, _pass_decision)
        )

        state, package, _, _ = await insight_workflow.run_insight_workflow(
            request_id="REQ_1", company_codes=["CLI_001"], required_sources={INT},
            prompt_by_company={"CLI_001": "p"}, original_user_prompt="p", preferences=preferences,
            insight_requirements=_requirements(), now=now,
        )

        assert state.current_stage == WorkflowStage.COMPLETED
        assert state.research_revision_count == 1
        assert state.synthesis_revision_count == 0
        assert package is not None
        assert package.request_version == 2
        assert len(run_research.calls) == 2
        assert run_research.calls[1]["narrow_revision"] is not None
        assert len(synthesize.calls) == 2
        assert review.calls == 2

    @pytest.mark.asyncio
    async def test_research_revision_still_insufficient_fails(self, monkeypatch, now, preferences):
        run_research, synthesize, review = _install(
            monkeypatch, review=_ReviewSequence(_revise_research_decision, _revise_research_decision)
        )

        state, package, _, _ = await insight_workflow.run_insight_workflow(
            request_id="REQ_1", company_codes=["CLI_001"], required_sources={INT},
            prompt_by_company={"CLI_001": "p"}, original_user_prompt="p", preferences=preferences,
            insight_requirements=_requirements(), now=now,
        )

        assert state.current_stage == WorkflowStage.FAILED
        assert package is None
        assert state.research_revision_count == 1  # unchanged
        assert "bounded-retry" in state.terminal_error
        assert len(run_research.calls) == 2  # never a 3rd research run
        assert review.calls == 2

    @pytest.mark.asyncio
    async def test_fail_decision_on_first_review_is_terminal(self, monkeypatch, now, preferences):
        run_research, synthesize, review = _install(monkeypatch, review=_ReviewSequence(_fail_decision))

        state, package, _, _ = await insight_workflow.run_insight_workflow(
            request_id="REQ_1", company_codes=["CLI_001"], required_sources={INT},
            prompt_by_company={"CLI_001": "p"}, original_user_prompt="p", preferences=preferences,
            insight_requirements=_requirements(), now=now,
        )

        assert state.current_stage == WorkflowStage.FAILED
        assert package is None
        assert "review failed" in state.terminal_error
        assert review.calls == 1

    @pytest.mark.asyncio
    async def test_combined_path_uses_both_budgets_then_fails_on_a_third_attempt(self, monkeypatch, now, preferences):
        """revise_research (research budget 0->1) -> revise_insights (synthesis
        budget 0->1) -> revise_research again must fail: its own budget is
        already exhausted even though the *other* budget still shows unused."""
        run_research, synthesize, review = _install(
            monkeypatch,
            review=_ReviewSequence(_revise_research_decision, _revise_insights_decision, _revise_research_decision),
        )

        state, package, _, _ = await insight_workflow.run_insight_workflow(
            request_id="REQ_1", company_codes=["CLI_001"], required_sources={INT},
            prompt_by_company={"CLI_001": "p"}, original_user_prompt="p", preferences=preferences,
            insight_requirements=_requirements(), now=now,
        )

        assert state.current_stage == WorkflowStage.FAILED
        assert package is None
        assert state.research_revision_count == 1
        assert state.synthesis_revision_count == 1
        assert review.calls == 3
        assert len(run_research.calls) == 2  # only the accepted research revision re-ran research
        assert len(synthesize.calls) == 3

    @pytest.mark.asyncio
    async def test_incomplete_initial_research_fails_without_synthesis_or_review(self, monkeypatch, now, preferences):
        """No persistence before Reviewer pass, extended one step further:
        research that never completes must not even reach the Synthesizer."""

        async def _incomplete_research(
            *, request_id, request_version, company_codes, required_sources, prompt_by_company,
            original_user_prompt, preferences, narrow_revision=None, now=None, data_domain_ids=None,
        ):
            moment = now or datetime.now(timezone.utc)
            keys = [PayloadKey(company_code=c, source_agent=s) for c in company_codes for s in required_sources]
            manifest = ResearchManifest.open(
                request_id=request_id, request_version=request_version, expected_payload_keys=keys, now=moment
            )
            return manifest, []  # nothing came back

        async def _unexpected(**kwargs):
            raise AssertionError("must not be called when research never completed")

        monkeypatch.setattr(insight_workflow, "run_research_for_request", _incomplete_research)
        monkeypatch.setattr(insight_workflow, "synthesize_insight_package", _unexpected)
        monkeypatch.setattr(insight_workflow, "review_insight_package", _unexpected)

        state, package, source_payloads, review_decision = await insight_workflow.run_insight_workflow(
            request_id="REQ_1", company_codes=["CLI_001"], required_sources={INT},
            prompt_by_company={"CLI_001": "p"}, original_user_prompt="p", preferences=preferences,
            insight_requirements=_requirements(), now=now,
        )

        assert state.current_stage == WorkflowStage.FAILED
        assert package is None
        assert source_payloads == []
        assert "research incomplete" in state.terminal_error
        assert review_decision is None  # review was never reached

    @pytest.mark.asyncio
    async def test_evidence_date_and_code_preserved_through_the_whole_workflow(self, monkeypatch, now, preferences):
        run_research = make_fake_run_research(evidence_code="RISK_048", evidence_date="2026-07-01")
        _install(monkeypatch, run_research=run_research, review=_ReviewSequence(_pass_decision))

        _, package, _, _ = await insight_workflow.run_insight_workflow(
            request_id="REQ_1", company_codes=["CLI_001"], required_sources={INT},
            prompt_by_company={"CLI_001": "p"}, original_user_prompt="p", preferences=preferences,
            insight_requirements=_requirements(), now=now,
        )

        [evidence] = package.insights[0].evidence
        assert evidence.evidence_code == "RISK_048"
        assert evidence.date.isoformat() == "2026-07-01"

    @pytest.mark.asyncio
    async def test_unmet_requirements_reported_in_final_package(self, monkeypatch, now, preferences):
        unmet = [
            UnmetRequirement(
                category=InsightCategory.CREDIT_RISK, requested_count=3, actual_count=1,
                reason="Only one credit-risk signal was found in the available evidence.",
            )
        ]
        synthesize = make_fake_synthesize(unmet=unmet)
        _install(monkeypatch, synthesize=synthesize, review=_ReviewSequence(_pass_decision))

        _, package, _, _ = await insight_workflow.run_insight_workflow(
            request_id="REQ_1", company_codes=["CLI_001"], required_sources={INT},
            prompt_by_company={"CLI_001": "p"}, original_user_prompt="p", preferences=preferences,
            insight_requirements=_requirements(), now=now,
        )

        assert len(package.unmet_requirements) == 1
        assert package.unmet_requirements[0].reason.startswith("Only one credit-risk signal")

    @pytest.mark.asyncio
    async def test_fail_decision_review_decision_is_returned_with_comments(self, monkeypatch, now, preferences):
        """reviewDecision/reviewComments (api/server.py) come from this return
        value -- confirm a fail decision's comments survive to the caller,
        not just its type."""
        _install(monkeypatch, review=_ReviewSequence(_fail_decision))

        _, package, _, review_decision = await insight_workflow.run_insight_workflow(
            request_id="REQ_1", company_codes=["CLI_001"], required_sources={INT},
            prompt_by_company={"CLI_001": "p"}, original_user_prompt="p", preferences=preferences,
            insight_requirements=_requirements(), now=now,
        )

        assert package is None
        assert review_decision.decision == ReviewDecisionType.FAIL
        assert review_decision.comments == "Not fixable."

    @pytest.mark.asyncio
    async def test_on_state_change_observes_every_intermediate_stage_in_order(self, monkeypatch, now, preferences):
        """api/server.py mirrors live progress into a polled resource via this
        callback -- it must see every stage transition as it happens, not just
        the final one this function returns."""
        _install(
            monkeypatch, review=_ReviewSequence(_revise_insights_decision, _pass_decision)
        )

        observed_stages: list[WorkflowStage] = []
        _, package, _, _ = await insight_workflow.run_insight_workflow(
            request_id="REQ_1", company_codes=["CLI_001"], required_sources={INT},
            prompt_by_company={"CLI_001": "p"}, original_user_prompt="p", preferences=preferences,
            insight_requirements=_requirements(), now=now,
            on_state_change=lambda s: observed_stages.append(s.current_stage),
        )

        assert package is not None
        assert observed_stages[0] == WorkflowStage.RESEARCHING
        assert WorkflowStage.AWAITING_SYNTHESIS in observed_stages
        assert WorkflowStage.SYNTHESIZING in observed_stages
        assert WorkflowStage.REVIEWING in observed_stages
        assert WorkflowStage.REVISING_SYNTHESIS in observed_stages
        assert observed_stages[-1] == WorkflowStage.COMPLETED
        # SYNTHESIZING appears twice: the initial pass and the revision.
        assert observed_stages.count(WorkflowStage.SYNTHESIZING) == 2

    @pytest.mark.asyncio
    async def test_on_package_ready_fires_once_per_reviewed_package_with_its_own_decision(
        self, monkeypatch, now, preferences
    ):
        """agents/package_store.py's snapshot writer is wired in exactly
        this way -- it must see every synthesized package paired with the
        ReviewDecision that specific package received, once per attempt,
        not just the final pass."""
        _install(monkeypatch, review=_ReviewSequence(_revise_insights_decision, _pass_decision))

        observed: list[tuple[int, str]] = []
        _, package, _, _ = await insight_workflow.run_insight_workflow(
            request_id="REQ_1", company_codes=["CLI_001"], required_sources={INT},
            prompt_by_company={"CLI_001": "p"}, original_user_prompt="p", preferences=preferences,
            insight_requirements=_requirements(), now=now,
            on_package_ready=lambda pkg, payloads, decision: observed.append(
                (pkg.package_version, decision.decision.value)
            ),
        )

        assert package is not None
        assert observed == [(1, "revise_insights"), (2, "pass")]

    @pytest.mark.asyncio
    async def test_review_decision_detail_recorded_on_audit_trail(self, monkeypatch, now, preferences):
        """auditEvents[].detail is where api/server.py's compact version
        history gets each review decision's comments/affected ids from."""
        _install(monkeypatch, review=_ReviewSequence(_revise_insights_decision, _pass_decision))

        state, package, _, _ = await insight_workflow.run_insight_workflow(
            request_id="REQ_1", company_codes=["CLI_001"], required_sources={INT},
            prompt_by_company={"CLI_001": "p"}, original_user_prompt="p", preferences=preferences,
            insight_requirements=_requirements(), now=now,
        )

        decision_events = [e for e in state.audit_events if e.detail and "decision" in e.detail]
        assert len(decision_events) == 2
        assert decision_events[0].detail["decision"] == "revise_insights"
        assert decision_events[0].detail["comments"] == "Fix wording."
        assert len(decision_events[0].detail["affectedInsightIds"]) == 1
        assert decision_events[1].detail["decision"] == "pass"
        assert package is not None

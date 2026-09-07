"""Covers agents/reviewer.py: assembling a raw LLM draft into a valid
ReviewDecision, the defensive fallback to `fail` when a draft can't be
safely assembled (revise_insights citing no real insight_id, revise_research
with no usable narrow scope), and the deterministic post-check that
overrides a PASS when an obvious claim/category, monetary-labeling, or
confidence-cap violation survived into the package. chat_model() is always
monkeypatched -- these tests never hit a real LLM.
"""

from datetime import datetime, timezone

import pytest

import insights_assistant.agents.reviewer as reviewer
from insights_assistant.agents.reviewer import _ReviewDraft
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
from insights_assistant.contracts.workflow.enums import ReviewDecisionType, SourcePayloadStatus
from insights_assistant.contracts.workflow.packages import InsightPackage, RankedInsight
from insights_assistant.contracts.workflow.research import PayloadKey, ResearchManifest, SourcePayload

INT = EvidenceSourceAgent.INTERNAL_DATA_AGENT
EXT = EvidenceSourceAgent.EXTERNAL_DATA_AGENT


class _FakeStructuredLLM:
    def __init__(self, result):
        self._result = result
        self.calls: list[list[dict]] = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return self._result


class _FakeChatModel:
    def __init__(self, result):
        self._result = result
        self.requested_schema = None
        self.llm: _FakeStructuredLLM | None = None

    def with_structured_output(self, schema):
        self.requested_schema = schema
        self.llm = _FakeStructuredLLM(self._result)
        return self.llm


@pytest.fixture
def install_fake_llm(monkeypatch):
    def _install(result) -> _FakeChatModel:
        fake = _FakeChatModel(result)
        monkeypatch.setattr(reviewer, "chat_model", lambda: fake)
        return fake

    return _install


def _requirements() -> InsightRequirementsSelection:
    return InsightRequirementsSelection(
        total_count=5,
        categories=[ReqCategory(category_id=InsightCategory.CREDIT_RISK, minimum_count=1)],
        ranking_criteria=[RankingCriterion.CONFIDENCE],
        max_insights_per_company=None,
    )


def _manifest_and_payloads(now, *, company_code="CLI_001", source_agent=INT):
    manifest = ResearchManifest.open(
        request_id="REQ_1", request_version=1,
        expected_payload_keys=[PayloadKey(company_code=company_code, source_agent=source_agent)], now=now,
    )
    payload = SourcePayload(
        request_id="REQ_1", request_version=1, company_code=company_code, source_agent=source_agent,
        status=SourcePayloadStatus.COMPLETED,
        evidence=[
            EvidenceItem(
                id="EV_1", source_agent=source_agent, source_type="internal",
                evidence_code="RELM_004", label="Relationship metrics",
                detail="Relationship risk score worsening this quarter.", date="2026-07-01",
                risk_types=["relationship_risk"], supported_claims=["relationship_risk_worsening"],
            )
        ],
        findings="Relationship risk score climbed this quarter.", started_at=now, completed_at=now,
    )
    return manifest, [payload]


def _valid_relationship_risk_insight(insight_id="PKG_1_1_INS_0", **overrides) -> RankedInsight:
    """A well-formed insight that satisfies every deterministic check --
    the baseline for tests confirming a genuinely clean package is left
    alone (no false-positive override)."""

    fields = dict(
        insight_id=insight_id, rank=1, company_code="CLI_001",
        category=InsightCategory.RELATIONSHIP_RISK, subtype=InsightSubtype.RELATIONSHIP_RISK,
        primary_claim=ClaimType.RELATIONSHIP_RISK_WORSENING,
        persona=InsightPersona.RELATIONSHIP_MANAGER, priority=InsightPriority.HIGH,
        title="Relationship risk worsening", finding="Relationship risk score rose this quarter.",
        why_it_matters="Concentration risk.", recommended_action="Schedule a relationship review.",
        confidence=70, confidence_rationale="One corroborating structured metric.",
        business_impact=BusinessImpact(exposure_usd=500_000, description="Potential exposure"),
        evidence=[
            EvidenceItem(
                id="EV_1", source_agent=INT, source_type="internal", evidence_code="RELM_004",
                label="Relationship metrics", detail="Relationship risk score worsening this quarter.",
                date="2026-07-01", risk_types=["relationship_risk"],
                supported_claims=["relationship_risk_worsening"],
            )
        ],
    )
    fields.update(overrides)
    return RankedInsight(**fields)


def _package(now, preferences, *, insight: RankedInsight | None = None, insight_id="PKG_1_1_INS_0") -> InsightPackage:
    insight = insight or _valid_relationship_risk_insight(insight_id)
    return InsightPackage(
        request_id="REQ_1", request_version=1, package_version=1,
        original_user_prompt="What changed for CLI_001?", effective_research_prompt="Research CLI_001.",
        preferences=preferences, source_payload_refs=[PayloadKey(company_code="CLI_001", source_agent=INT)],
        insights=[insight], unmet_requirements=[], created_at=now,
    )


class TestReviewInsightPackage:
    @pytest.mark.asyncio
    async def test_pass_decision_assembled_directly(self, install_fake_llm, now, preferences):
        manifest, payloads = _manifest_and_payloads(now)
        package = _package(now, preferences)
        install_fake_llm(_ReviewDraft(decision=ReviewDecisionType.PASS, comments="Well supported."))

        decision = await reviewer.review_insight_package(
            insight_requirements=_requirements(), manifest=manifest, source_payloads=payloads, package=package,
        )

        assert decision.decision == ReviewDecisionType.PASS
        assert decision.request_id == "REQ_1"
        assert decision.package_version == 1

    @pytest.mark.asyncio
    async def test_revise_insights_with_valid_insight_id(self, install_fake_llm, now, preferences):
        manifest, payloads = _manifest_and_payloads(now)
        package = _package(now, preferences, insight_id="PKG_1_1_INS_0")
        install_fake_llm(
            _ReviewDraft(
                decision=ReviewDecisionType.REVISE_INSIGHTS,
                comments="Dedup this with the other relationship-risk insight.",
                affected_insight_ids=["PKG_1_1_INS_0"],
            )
        )

        decision = await reviewer.review_insight_package(
            insight_requirements=_requirements(), manifest=manifest, source_payloads=payloads, package=package,
        )

        assert decision.decision == ReviewDecisionType.REVISE_INSIGHTS
        assert decision.affected_insight_ids == ["PKG_1_1_INS_0"]

    @pytest.mark.asyncio
    async def test_revise_insights_with_no_valid_insight_id_downgrades_to_fail(
        self, install_fake_llm, now, preferences
    ):
        manifest, payloads = _manifest_and_payloads(now)
        package = _package(now, preferences, insight_id="PKG_1_1_INS_0")
        install_fake_llm(
            _ReviewDraft(
                decision=ReviewDecisionType.REVISE_INSIGHTS,
                comments="Something's wrong.",
                affected_insight_ids=["PKG_9_9_INS_9"],  # not in this package
            )
        )

        decision = await reviewer.review_insight_package(
            insight_requirements=_requirements(), manifest=manifest, source_payloads=payloads, package=package,
        )

        assert decision.decision == ReviewDecisionType.FAIL
        assert "no valid insight_id" in decision.comments

    @pytest.mark.asyncio
    async def test_revise_research_with_valid_narrow_scope(self, install_fake_llm, now, preferences):
        manifest, payloads = _manifest_and_payloads(now)
        package = _package(now, preferences)
        install_fake_llm(
            _ReviewDraft(
                decision=ReviewDecisionType.REVISE_RESEARCH,
                comments="Internal risk data looks stale.",
                narrow_company_codes=["CLI_001"],
                narrow_source_agents=[INT],
                narrow_guidance="Re-check the latest risk_assessment row.",
            )
        )

        decision = await reviewer.review_insight_package(
            insight_requirements=_requirements(), manifest=manifest, source_payloads=payloads, package=package,
        )

        assert decision.decision == ReviewDecisionType.REVISE_RESEARCH
        assert decision.narrow_research_revision is not None
        assert decision.narrow_research_revision.company_codes == ["CLI_001"]
        assert decision.narrow_research_revision.source_agents == [INT]
        assert decision.affected_source_agents == [INT]

    @pytest.mark.asyncio
    async def test_revise_research_with_unknown_company_downgrades_to_fail(
        self, install_fake_llm, now, preferences
    ):
        manifest, payloads = _manifest_and_payloads(now)
        package = _package(now, preferences)
        install_fake_llm(
            _ReviewDraft(
                decision=ReviewDecisionType.REVISE_RESEARCH,
                comments="Needs another look.",
                narrow_company_codes=["CLI_999_NOT_IN_SCOPE"],
                narrow_source_agents=[INT],
                narrow_guidance="Re-check.",
            )
        )

        decision = await reviewer.review_insight_package(
            insight_requirements=_requirements(), manifest=manifest, source_payloads=payloads, package=package,
        )

        assert decision.decision == ReviewDecisionType.FAIL
        assert "usable narrow scope" in decision.comments

    @pytest.mark.asyncio
    async def test_revise_research_missing_guidance_downgrades_to_fail(self, install_fake_llm, now, preferences):
        manifest, payloads = _manifest_and_payloads(now)
        package = _package(now, preferences)
        install_fake_llm(
            _ReviewDraft(
                decision=ReviewDecisionType.REVISE_RESEARCH,
                comments="Needs another look.",
                narrow_company_codes=["CLI_001"],
                narrow_source_agents=[INT],
                narrow_guidance=None,
            )
        )

        decision = await reviewer.review_insight_package(
            insight_requirements=_requirements(), manifest=manifest, source_payloads=payloads, package=package,
        )

        assert decision.decision == ReviewDecisionType.FAIL

    @pytest.mark.asyncio
    async def test_fail_decision_passes_through(self, install_fake_llm, now, preferences):
        manifest, payloads = _manifest_and_payloads(now)
        package = _package(now, preferences)
        install_fake_llm(
            _ReviewDraft(decision=ReviewDecisionType.FAIL, comments="Source data is too contradictory to trust.")
        )

        decision = await reviewer.review_insight_package(
            insight_requirements=_requirements(), manifest=manifest, source_payloads=payloads, package=package,
        )

        assert decision.decision == ReviewDecisionType.FAIL
        assert decision.comments == "Source data is too contradictory to trust."

    @pytest.mark.asyncio
    async def test_comments_never_leak_raw_chain_of_thought_field(self, install_fake_llm, now, preferences):
        """Structural guard: _ReviewDraft has no field for chain-of-thought,
        so nothing downstream of the LLM call could carry one even if asked."""
        assert "reasoning" not in _ReviewDraft.model_fields
        assert "chain_of_thought" not in _ReviewDraft.model_fields


class TestDeterministicFindings:
    """Regression coverage for requirement 8: a deterministic post-check
    that catches obvious violations regardless of what the model reviewer
    decides -- a PASS from the LLM is overridden whenever one survives."""

    @pytest.mark.asyncio
    async def test_clean_package_pass_is_not_overridden(self, install_fake_llm, now, preferences):
        manifest, payloads = _manifest_and_payloads(now)
        package = _package(now, preferences)  # the well-formed baseline fixture
        install_fake_llm(_ReviewDraft(decision=ReviewDecisionType.PASS, comments="Well supported."))

        decision = await reviewer.review_insight_package(
            insight_requirements=_requirements(), manifest=manifest, source_payloads=payloads, package=package,
        )

        assert decision.decision == ReviewDecisionType.PASS

    @pytest.mark.asyncio
    async def test_credit_risk_category_without_credit_quality_evidence_blocks_pass(
        self, install_fake_llm, now, preferences
    ):
        """The REQ_1005 shape reaching the Reviewer directly (bypassing the
        Synthesizer's own gate, e.g. via a bug or a future code path):
        category=credit_risk with only relationship-risk evidence must never
        pass, even if the LLM says PASS."""
        insight = _valid_relationship_risk_insight(
            category=InsightCategory.CREDIT_RISK, subtype=InsightSubtype.CREDIT_RISK,
            primary_claim=ClaimType.CREDIT_QUALITY_DETERIORATING,
        )
        manifest, payloads = _manifest_and_payloads(now)
        package = _package(now, preferences, insight=insight)
        install_fake_llm(_ReviewDraft(decision=ReviewDecisionType.PASS, comments="Looks fine."))

        decision = await reviewer.review_insight_package(
            insight_requirements=_requirements(), manifest=manifest, source_payloads=payloads, package=package,
        )

        assert decision.decision == ReviewDecisionType.REVISE_INSIGHTS
        assert decision.affected_insight_ids == [insight.insight_id]
        assert "credit-quality" in decision.comments

    @pytest.mark.asyncio
    async def test_deal_fee_opportunity_without_deal_evidence_blocks_pass(
        self, install_fake_llm, now, preferences
    ):
        """The REQ_1006 shape: an insight recategorized to deal_fee_opportunity
        on the strength of a legacy lost-mandate/OPP_ record alone, with no
        actual CRM deal pipeline (DEAL_) evidence cited, must never pass --
        the same defense-in-depth pattern as the credit_risk check above,
        now guarding the new schema's own strict category (Goal B)."""
        insight = _valid_relationship_risk_insight(
            category=InsightCategory.DEAL_FEE_OPPORTUNITY, subtype=InsightSubtype.DEAL_FEE_OPPORTUNITY,
            primary_claim=ClaimType.DEAL_FEE_OPPORTUNITY,
            evidence=[
                EvidenceItem(
                    id="EV_1", source_agent=INT, source_type="internal", evidence_code="OPP_015",
                    label="Lost opportunity", detail="Capital markets bond issuance mandate lost to a "
                    "named competitor.", date="2026-08-30",
                )
            ],
        )
        manifest, payloads = _manifest_and_payloads(now)
        package = _package(now, preferences, insight=insight)
        install_fake_llm(_ReviewDraft(decision=ReviewDecisionType.PASS, comments="Looks fine."))

        decision = await reviewer.review_insight_package(
            insight_requirements=_requirements(), manifest=manifest, source_payloads=payloads, package=package,
        )

        assert decision.decision == ReviewDecisionType.REVISE_INSIGHTS
        assert decision.affected_insight_ids == [insight.insight_id]
        assert "DEAL_" in decision.comments

    @pytest.mark.asyncio
    async def test_estimated_impact_equal_to_exposure_blocks_pass(self, install_fake_llm, now, preferences):
        insight = _valid_relationship_risk_insight(
            business_impact=BusinessImpact(
                exposure_usd=10_100_000, estimated_impact_usd=10_100_000,
                impact_basis="Full exposure at risk", description="Credit exposure at risk",
            )
        )
        manifest, payloads = _manifest_and_payloads(now)
        package = _package(now, preferences, insight=insight)
        install_fake_llm(_ReviewDraft(decision=ReviewDecisionType.PASS, comments="Looks fine."))

        decision = await reviewer.review_insight_package(
            insight_requirements=_requirements(), manifest=manifest, source_payloads=payloads, package=package,
        )

        assert decision.decision == ReviewDecisionType.REVISE_INSIGHTS
        assert "bare copy" in decision.comments

    @pytest.mark.asyncio
    async def test_confidence_above_evidence_cap_blocks_pass(self, install_fake_llm, now, preferences):
        insight = _valid_relationship_risk_insight(confidence=95)  # one evidence item -> cap is 70
        manifest, payloads = _manifest_and_payloads(now)
        package = _package(now, preferences, insight=insight)
        install_fake_llm(_ReviewDraft(decision=ReviewDecisionType.PASS, comments="Looks fine."))

        decision = await reviewer.review_insight_package(
            insight_requirements=_requirements(), manifest=manifest, source_payloads=payloads, package=package,
        )

        assert decision.decision == ReviewDecisionType.REVISE_INSIGHTS
        assert "exceeds the evidence-based ceiling" in decision.comments

    @pytest.mark.asyncio
    async def test_deterministic_override_never_downgrades_an_existing_revise_or_fail(
        self, install_fake_llm, now, preferences
    ):
        """A deterministic violation exists, but the model already said
        revise_insights (for an unrelated reason) -- the override must not
        interfere with a decision that already routes the package away from
        persistence."""
        insight = _valid_relationship_risk_insight(confidence=95)
        manifest, payloads = _manifest_and_payloads(now)
        package = _package(now, preferences, insight=insight)
        install_fake_llm(
            _ReviewDraft(
                decision=ReviewDecisionType.REVISE_INSIGHTS, comments="Wording is unclear.",
                affected_insight_ids=[insight.insight_id],
            )
        )

        decision = await reviewer.review_insight_package(
            insight_requirements=_requirements(), manifest=manifest, source_payloads=payloads, package=package,
        )

        assert decision.decision == ReviewDecisionType.REVISE_INSIGHTS
        assert decision.comments == "Wording is unclear."  # untouched -- not overridden


class TestPreferencesInPrompt:
    """The runtime-context gap this covers: package.preferences was never
    serialized into the Reviewer's user message even though the system
    prompt already asks it to check alignment with "the stated preferences".
    These tests capture the real messages list sent to chat_model().
    with_structured_output(...).ainvoke(...) and assert on it directly."""

    @pytest.mark.asyncio
    async def test_system_message_present_and_preferences_in_user_message(
        self, install_fake_llm, now, preferences
    ):
        manifest, payloads = _manifest_and_payloads(now)
        package = _package(now, preferences)
        fake = install_fake_llm(_ReviewDraft(decision=ReviewDecisionType.PASS, comments="Well supported."))

        await reviewer.review_insight_package(
            insight_requirements=_requirements(), manifest=manifest, source_payloads=payloads, package=package,
        )

        messages = fake.llm.calls[0]
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        user_message = messages[1]["content"]

        assert f"role: {preferences.role}" in user_message
        for domain in preferences.default_data_domains:
            assert domain in user_message
        for criterion in preferences.default_ranking_criteria:
            assert criterion.value in user_message
        assert f"default_lookback_months: {preferences.default_lookback_months}" in user_message

    @pytest.mark.asyncio
    async def test_preferences_omit_notification_display_and_identity_fields(
        self, install_fake_llm, now, preferences
    ):
        manifest, payloads = _manifest_and_payloads(now)
        package = _package(now, preferences)
        fake = install_fake_llm(_ReviewDraft(decision=ReviewDecisionType.PASS, comments="Well supported."))

        await reviewer.review_insight_package(
            insight_requirements=_requirements(), manifest=manifest, source_payloads=payloads, package=package,
        )

        user_message = fake.llm.calls[0][1]["content"]
        assert preferences.display_name not in user_message
        assert "email_digest_enabled" not in user_message
        assert "at_risk_alerts_enabled" not in user_message
        assert "display_density" not in user_message

    @pytest.mark.asyncio
    async def test_structured_output_schema_still_enforced(self, install_fake_llm, now, preferences):
        manifest, payloads = _manifest_and_payloads(now)
        package = _package(now, preferences)
        fake = install_fake_llm(_ReviewDraft(decision=ReviewDecisionType.PASS, comments="Well supported."))

        await reviewer.review_insight_package(
            insight_requirements=_requirements(), manifest=manifest, source_payloads=payloads, package=package,
        )

        assert fake.requested_schema is _ReviewDraft

    def test_system_prompt_text_unchanged_by_this_fix(self):
        assert 'the stated preferences' in reviewer.REVIEW_SYSTEM_PROMPT
        assert 'comments must be concise, decision-oriented audit text' in reviewer.REVIEW_SYSTEM_PROMPT

    def test_synthesizer_and_reviewer_render_the_same_preferences_snapshot_identically(self, preferences):
        """Requirements 2+3: the Synthesizer gets the immutable request-time
        snapshot, the Reviewer gets the exact package.preferences snapshot --
        for one banker's preferences, both agents must render the identical
        block, not two independently-drifting summaries of the same data."""
        import insights_assistant.agents.synthesizer as synthesizer

        assert synthesizer._preferences_block(preferences) == reviewer._preferences_block(preferences)

    @pytest.mark.asyncio
    async def test_synthesizer_and_reviewer_prompts_carry_the_same_snapshot_end_to_end(
        self, install_fake_llm, monkeypatch, now, preferences
    ):
        """End-to-end version of the same guarantee: run both agents against
        one InsightPackage built from `preferences`, capture what each
        actually sent the model, and confirm the preferences block is
        identical in both -- not just that the helper functions agree.
        install_fake_llm only patches reviewer.chat_model, so the Synthesizer
        call needs its own fake installed directly on the synthesizer module.
        """
        import insights_assistant.agents.synthesizer as synthesizer

        manifest, payloads = _manifest_and_payloads(now)

        synth_fake = _FakeChatModel(synthesizer._SynthesisOutput(insights=[], unmet_requirements=[]))
        monkeypatch.setattr(synthesizer, "chat_model", lambda: synth_fake)
        synth_result = await synthesizer.synthesize_insight_package(
            request_id="REQ_1", request_version=1, package_version=1,
            original_user_prompt="What changed for CLI_001?", effective_research_prompt="Research CLI_001.",
            preferences=preferences,
            insight_requirements=_requirements(),
            manifest=manifest, source_payloads=payloads,
        )
        synth_user_message = synth_fake.llm.calls[0][1]["content"]

        package = _package(now, preferences)
        assert package.preferences == synth_result.preferences  # same snapshot flowed onto the package

        review_fake = install_fake_llm(_ReviewDraft(decision=ReviewDecisionType.PASS, comments="Well supported."))
        await reviewer.review_insight_package(
            insight_requirements=_requirements(), manifest=manifest, source_payloads=payloads, package=package,
        )
        review_user_message = review_fake.llm.calls[0][1]["content"]

        synth_block = synthesizer._preferences_block(preferences)
        assert synth_block in synth_user_message
        assert synth_block in review_user_message

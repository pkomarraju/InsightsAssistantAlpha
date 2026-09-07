"""Covers agents/synthesizer.py: evidence-code resolution (never manufacture
evidence), deterministic ranking/count-capping independent of the LLM, unmet
-requirement passthrough, the pre-LLM completeness check, the claim/category
alignment gate (REQ_1005), deterministic confidence caps, monetary-field
separation, and apply_synthesis_revision's budget enforcement. chat_model()
is always monkeypatched -- these tests never hit a real LLM.
"""

from datetime import datetime, timezone

import pytest

import insights_assistant.agents.synthesizer as synthesizer
from insights_assistant.api import evidence_mapping
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
from insights_assistant.contracts.workflow.invariants import WorkflowInvariantError
from insights_assistant.contracts.workflow.packages import InsightPackage, RankedInsight
from insights_assistant.contracts.workflow.research import PayloadKey, ResearchManifest, SourcePayload
from insights_assistant.contracts.workflow.review import ReviewDecision
from insights_assistant.contracts.workflow.state import WorkflowState
from insights_assistant.agents.synthesizer import (
    _InsightDraft,
    _RevisionResolution,
    _SynthesisOutput,
    _UnmetRequirementDraft,
)

INT = EvidenceSourceAgent.INTERNAL_DATA_AGENT
EXT = EvidenceSourceAgent.EXTERNAL_DATA_AGENT
RMN = EvidenceSourceAgent.RELATIONSHIP_NOTES_AGENT


class _FakeStructuredLLM:
    def __init__(self, result):
        self._result = result
        self.calls: list[list[dict]] = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        if isinstance(self._result, Exception):
            raise self._result
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
        monkeypatch.setattr(synthesizer, "chat_model", lambda: fake)
        return fake

    return _install


def _draft(**overrides) -> _InsightDraft:
    """A generic, evidence-agnostic draft. Defaults to a relationship-risk
    claim/category pairing paired with the default evidence fixture's
    "relationship risk...worsening" text (see _manifest_and_payload) so it
    survives claim validation unmodified -- tests targeting the claim gate
    itself override company_code/category/subtype/primary_claim/
    evidence_codes together with matching evidence."""

    fields = dict(
        company_code="CLI_001",
        category=InsightCategory.RELATIONSHIP_RISK,
        subtype=InsightSubtype.RELATIONSHIP_RISK,
        primary_claim=ClaimType.RELATIONSHIP_RISK_WORSENING,
        persona=InsightPersona.RELATIONSHIP_MANAGER,
        priority=InsightPriority.HIGH,
        title="Relationship risk rising",
        finding="Relationship risk score rose this quarter.",
        why_it_matters="Concentration risk.",
        recommended_action="Schedule a relationship review.",
        limitations="",
        confidence=80,
        confidence_rationale="Two corroborating structured metrics.",
        urgency_score=60,
        commercial_potential_score=40,
        risk_severity_score=70,
        exposure_usd=None,
        estimated_impact_usd=None,
        impact_basis=None,
        business_impact_description="Potential exposure",
        evidence_codes=["RELM_004"],
    )
    fields.update(overrides)
    return _InsightDraft(**fields)


def _evidence_dict(code: str, agent: EvidenceSourceAgent, source_type: str, label: str, detail: str, date: str) -> dict:
    """Builds a raw evidence dict the same way agents/research_execution.py's
    _build_evidence does -- running the real classifier over label/detail so
    tests exercise the actual semantics pipeline, not hand-specified tags."""

    semantics = evidence_mapping.classify_evidence_semantics(code, label, detail)
    return {
        "id": f"EV_{code}", "source_agent": agent.value, "source_type": source_type,
        "evidence_code": code, "label": label, "detail": detail, "date": date,
        "risk_types": [r.value for r in semantics.risk_types],
        "supported_claims": [c.value for c in semantics.supported_claims],
        "metric_type": semantics.metric_type.value if semantics.metric_type else None,
    }


def _manifest_and_payload(now, *, evidence_code="RELM_004", company_code="CLI_001", source_agent=INT):
    manifest = ResearchManifest.open(
        request_id="REQ_1", request_version=1,
        expected_payload_keys=[PayloadKey(company_code=company_code, source_agent=source_agent)], now=now,
    )
    payload = SourcePayload(
        request_id="REQ_1", request_version=1, company_code=company_code, source_agent=source_agent,
        status=SourcePayloadStatus.COMPLETED,
        evidence=[
            _evidence_dict(
                evidence_code, source_agent, "internal", "Relationship metrics",
                "Relationship risk score rose to 68, a worsening trend from the prior quarter.",
                "2026-07-01",
            )
        ],
        findings="Relationship risk score climbed this quarter.", started_at=now, completed_at=now,
    )
    return manifest, [payload]


def _payloads_with_evidence(now, *, company_code="CLI_006", evidence_specs):
    """evidence_specs: list of (evidence_code, source_agent, source_type, label, detail, date)."""
    by_agent: dict[EvidenceSourceAgent, list[dict]] = {}
    for code, agent, source_type, label, detail, date in evidence_specs:
        by_agent.setdefault(agent, []).append(_evidence_dict(code, agent, source_type, label, detail, date))
    manifest = ResearchManifest.open(
        request_id="REQ_1", request_version=1,
        expected_payload_keys=[PayloadKey(company_code=company_code, source_agent=agent) for agent in by_agent],
        now=now,
    )
    payloads = [
        SourcePayload(
            request_id="REQ_1", request_version=1, company_code=company_code, source_agent=agent,
            status=SourcePayloadStatus.COMPLETED, evidence=evs,
            findings="Findings.", started_at=now, completed_at=now,
        )
        for agent, evs in by_agent.items()
    ]
    return manifest, payloads


def _ranked_insight_for_previous(insight_id: str) -> RankedInsight:
    """The REQ_1005 shape: a credit_risk insight backed by a RISK_ code
    whose text carries no direct credit-quality signal -- passes the old
    prefix-only gate but not the new claim-alignment one. The flaw is in
    the *interpretation*, which the deterministic gates catch structurally
    now, but this fixture still models "a previously-persisted flawed
    insight the Reviewer flagged" for the revision-resolution tests."""

    return RankedInsight(
        insight_id=insight_id, rank=1, company_code="CLI_006",
        category=InsightCategory.CREDIT_RISK, subtype=InsightSubtype.CREDIT_RISK,
        primary_claim=ClaimType.CREDIT_QUALITY_DETERIORATING,
        persona=InsightPersona.CREDIT_OFFICER, priority=InsightPriority.HIGH,
        title="Rising liabilities signal credit risk",
        finding="Liabilities rose, indicating increased credit risk.",
        why_it_matters="Potential deterioration.", recommended_action="Escalate.",
        confidence=70, confidence_rationale="Filing and risk data.",
        business_impact=BusinessImpact(description="n/a"),
        evidence=[
            EvidenceItem(
                id="EV_1", source_agent=INT, source_type="internal", evidence_code="RISK_048",
                label="Risk assessment", detail="Quarterly credit exposure review completed.", date="2026-08-01",
            )
        ],
    )


def _previous_package(preferences, insight: RankedInsight, now) -> InsightPackage:
    return InsightPackage(
        request_id="REQ_1", request_version=1, package_version=1,
        original_user_prompt="p", effective_research_prompt="p", preferences=preferences,
        source_payload_refs=[PayloadKey(company_code="CLI_006", source_agent=INT)],
        insights=[insight], unmet_requirements=[], created_at=now,
    )


def _requirements(**overrides) -> InsightRequirementsSelection:
    fields = dict(
        total_count=5,
        categories=[ReqCategory(category_id=InsightCategory.CREDIT_RISK, minimum_count=1)],
        ranking_criteria=[RankingCriterion.CONFIDENCE],
        max_insights_per_company=None,
    )
    fields.update(overrides)
    return InsightRequirementsSelection(**fields)


class TestSynthesizeInsightPackage:
    @pytest.mark.asyncio
    async def test_basic_pass_through_builds_package(self, install_fake_llm, now, preferences):
        manifest, payloads = _manifest_and_payload(now)
        install_fake_llm(_SynthesisOutput(insights=[_draft()], unmet_requirements=[]))

        package = await synthesizer.synthesize_insight_package(
            request_id="REQ_1", request_version=1, package_version=1,
            original_user_prompt="What changed for CLI_001?", effective_research_prompt="Research CLI_001.",
            preferences=preferences, insight_requirements=_requirements(),
            manifest=manifest, source_payloads=payloads,
        )

        assert len(package.insights) == 1
        insight = package.insights[0]
        assert insight.rank == 1
        assert insight.evidence[0].evidence_code == "RELM_004"
        assert insight.evidence[0].date.isoformat() == "2026-07-01"

    @pytest.mark.asyncio
    async def test_insight_with_unresolvable_evidence_code_is_dropped(self, install_fake_llm, now, preferences):
        """Never manufacture an insight: a cited code that isn't in any
        SourcePayload's real evidence must not survive into the package."""
        manifest, payloads = _manifest_and_payload(now)
        install_fake_llm(
            _SynthesisOutput(insights=[_draft(evidence_codes=["RELM_999_MADE_UP"])], unmet_requirements=[])
        )

        package = await synthesizer.synthesize_insight_package(
            request_id="REQ_1", request_version=1, package_version=1,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences, insight_requirements=_requirements(),
            manifest=manifest, source_payloads=payloads,
        )

        assert package.insights == []

    @pytest.mark.asyncio
    async def test_unmet_requirements_pass_through(self, install_fake_llm, now, preferences):
        manifest, payloads = _manifest_and_payload(now)
        install_fake_llm(
            _SynthesisOutput(
                insights=[],
                unmet_requirements=[
                    _UnmetRequirementDraft(
                        category=InsightCategory.CREDIT_RISK, requested_count=1, actual_count=0,
                        reason="No credit-risk evidence was returned by internal_data_agent.",
                    )
                ],
            )
        )

        package = await synthesizer.synthesize_insight_package(
            request_id="REQ_1", request_version=1, package_version=1,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences, insight_requirements=_requirements(),
            manifest=manifest, source_payloads=payloads,
        )

        assert len(package.unmet_requirements) == 1
        assert package.unmet_requirements[0].category == InsightCategory.CREDIT_RISK
        assert package.unmet_requirements[0].actual_count == 0

    @pytest.mark.asyncio
    async def test_ranking_is_deterministic_by_requested_criteria(self, install_fake_llm, now, preferences):
        manifest, payloads = _manifest_and_payload(now)
        low_confidence = _draft(title="Low confidence", confidence=30, urgency_score=90)
        high_confidence = _draft(title="High confidence", confidence=65, urgency_score=10)
        install_fake_llm(_SynthesisOutput(insights=[low_confidence, high_confidence], unmet_requirements=[]))

        package = await synthesizer.synthesize_insight_package(
            request_id="REQ_1", request_version=1, package_version=1,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences,
            insight_requirements=_requirements(ranking_criteria=[RankingCriterion.CONFIDENCE]),
            manifest=manifest, source_payloads=payloads,
        )

        assert [i.title for i in package.insights] == ["High confidence", "Low confidence"]
        assert [i.rank for i in package.insights] == [1, 2]

    @pytest.mark.asyncio
    async def test_ranking_uses_resolved_post_cap_confidence(self, install_fake_llm, now, preferences):
        """Ranking must reflect the persisted (capped) confidence, not the
        model's raw proposal: draft A claims a higher raw confidence (95)
        but cites only one evidence item (caps at 70); draft B claims a
        lower raw confidence (75) but cites two independent source types
        (cap 90, so its 75 passes through unchanged). Ranking by raw
        confidence would put A first (95 > 75); ranking by resolved
        confidence correctly puts B first (75 > 70)."""
        manifest, single_item_payloads = _manifest_and_payload(now, company_code="CLI_001")
        _, two_type_payloads = _payloads_with_evidence(
            now,
            company_code="CLI_002",
            evidence_specs=[
                (
                    "RISK_060", INT, "internal", "Risk assessment",
                    "Relationship risk score worsening this quarter.", "2026-08-01",
                ),
                (
                    "10-Q", EXT, "external", "SEC filing",
                    "Relationship risk score worsening per management commentary.", "2026-08-01",
                ),
            ],
        )
        manifest = ResearchManifest.open(
            request_id="REQ_1", request_version=1,
            expected_payload_keys=[
                PayloadKey(company_code="CLI_001", source_agent=INT),
                PayloadKey(company_code="CLI_002", source_agent=INT),
                PayloadKey(company_code="CLI_002", source_agent=EXT),
            ],
            now=now,
        )
        payloads = single_item_payloads + two_type_payloads

        draft_a = _draft(company_code="CLI_001", title="A insight", confidence=95, evidence_codes=["RELM_004"])
        draft_b = _draft(
            company_code="CLI_002", title="B insight", confidence=75, evidence_codes=["RISK_060", "10-Q"],
        )
        install_fake_llm(_SynthesisOutput(insights=[draft_a, draft_b], unmet_requirements=[]))

        package = await synthesizer.synthesize_insight_package(
            request_id="REQ_1", request_version=1, package_version=1,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences,
            insight_requirements=_requirements(ranking_criteria=[RankingCriterion.CONFIDENCE]),
            manifest=manifest, source_payloads=payloads,
        )

        by_title = {i.title: i.confidence for i in package.insights}
        assert by_title == {"A insight": 70, "B insight": 75}
        assert [i.title for i in package.insights] == ["B insight", "A insight"]

    @pytest.mark.asyncio
    async def test_ranking_stable_and_reproducible_across_runs(self, install_fake_llm, now, preferences):
        """Same drafts, same criteria -> same order every time (no
        LLM-assigned rank, no nondeterministic tie-breaking)."""
        manifest, payloads = _manifest_and_payload(now)
        drafts = [_draft(title=f"Insight {i}", confidence=50) for i in range(4)]
        requirements = _requirements(ranking_criteria=[RankingCriterion.CONFIDENCE])

        orders = []
        for _ in range(3):
            install_fake_llm(_SynthesisOutput(insights=list(drafts), unmet_requirements=[]))
            package = await synthesizer.synthesize_insight_package(
                request_id="REQ_1", request_version=1, package_version=1,
                original_user_prompt="p", effective_research_prompt="p",
                preferences=preferences, insight_requirements=requirements,
                manifest=manifest, source_payloads=payloads,
            )
            orders.append([i.title for i in package.insights])

        assert orders[0] == orders[1] == orders[2]

    @pytest.mark.asyncio
    async def test_max_insights_per_company_cap_is_enforced_deterministically(
        self, install_fake_llm, now, preferences
    ):
        manifest, payloads = _manifest_and_payload(now)
        drafts = [_draft(title=f"Insight {i}") for i in range(5)]
        install_fake_llm(_SynthesisOutput(insights=drafts, unmet_requirements=[]))

        package = await synthesizer.synthesize_insight_package(
            request_id="REQ_1", request_version=1, package_version=1,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences,
            insight_requirements=_requirements(total_count=10, max_insights_per_company=2),
            manifest=manifest, source_payloads=payloads,
        )

        assert len(package.insights) == 2

    @pytest.mark.asyncio
    async def test_total_count_cap_is_enforced_deterministically(self, install_fake_llm, now, preferences):
        manifest, payloads = _manifest_and_payload(now)
        drafts = [_draft(title=f"Insight {i}") for i in range(5)]
        install_fake_llm(_SynthesisOutput(insights=drafts, unmet_requirements=[]))

        package = await synthesizer.synthesize_insight_package(
            request_id="REQ_1", request_version=1, package_version=1,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences,
            insight_requirements=_requirements(total_count=2, max_insights_per_company=None),
            manifest=manifest, source_payloads=payloads,
        )

        assert len(package.insights) == 2

    @pytest.mark.asyncio
    async def test_raises_before_invoking_llm_when_payloads_incomplete(self, install_fake_llm, now, preferences):
        """Completeness is verified before spending an LLM call -- an LLM
        invocation here would mean synthesis ran against partial data."""
        manifest = ResearchManifest.open(
            request_id="REQ_1", request_version=1,
            expected_payload_keys=[
                PayloadKey(company_code="CLI_001", source_agent=INT),
                PayloadKey(company_code="CLI_002", source_agent=INT),
            ],
            now=now,
        )
        _, payloads = _manifest_and_payload(now)  # only covers CLI_001
        fake = install_fake_llm(_SynthesisOutput(insights=[], unmet_requirements=[]))

        with pytest.raises(WorkflowInvariantError):
            await synthesizer.synthesize_insight_package(
                request_id="REQ_1", request_version=1, package_version=1,
                original_user_prompt="p", effective_research_prompt="p",
                preferences=preferences, insight_requirements=_requirements(),
                manifest=manifest, source_payloads=payloads,
            )

        assert fake.llm is None  # with_structured_output/ainvoke never reached

    @pytest.mark.asyncio
    async def test_reviewer_comments_are_included_in_the_prompt(self, install_fake_llm, now, preferences):
        manifest, payloads = _manifest_and_payload(now)
        fake = install_fake_llm(_SynthesisOutput(insights=[], unmet_requirements=[]))

        await synthesizer.synthesize_insight_package(
            request_id="REQ_1", request_version=1, package_version=2,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences, insight_requirements=_requirements(),
            manifest=manifest, source_payloads=payloads,
            reviewer_comments="Consolidate the two duplicate relationship-risk insights.",
        )

        user_message = fake.llm.calls[0][1]["content"]
        assert "Consolidate the two duplicate relationship-risk insights." in user_message


class TestPreferencesInPrompt:
    """The runtime-context gap this covers: preferences was accepted by
    synthesize_insight_package() and stored on InsightPackage, but never
    actually reached the LLM call. These tests capture the real messages
    list sent to chat_model().with_structured_output(...).ainvoke(...) and
    assert on it directly, not just on the resulting InsightPackage."""

    @pytest.mark.asyncio
    async def test_system_message_present_and_preferences_in_user_message(
        self, install_fake_llm, now, preferences
    ):
        manifest, payloads = _manifest_and_payload(now)
        fake = install_fake_llm(_SynthesisOutput(insights=[], unmet_requirements=[]))

        await synthesizer.synthesize_insight_package(
            request_id="REQ_1", request_version=1, package_version=1,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences, insight_requirements=_requirements(),
            manifest=manifest, source_payloads=payloads,
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
        """Requirement 4: no unrelated user data. Notification/UI settings
        and the banker's own name don't shape insight content, so they must
        not be copied into the prompt."""
        manifest, payloads = _manifest_and_payload(now)
        fake = install_fake_llm(_SynthesisOutput(insights=[], unmet_requirements=[]))

        await synthesizer.synthesize_insight_package(
            request_id="REQ_1", request_version=1, package_version=1,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences, insight_requirements=_requirements(),
            manifest=manifest, source_payloads=payloads,
        )

        user_message = fake.llm.calls[0][1]["content"]
        assert preferences.display_name not in user_message
        assert "email_digest_enabled" not in user_message
        assert "at_risk_alerts_enabled" not in user_message
        assert "display_density" not in user_message

    @pytest.mark.asyncio
    async def test_structured_output_schema_still_enforced(self, install_fake_llm, now, preferences):
        manifest, payloads = _manifest_and_payload(now)
        fake = install_fake_llm(_SynthesisOutput(insights=[], unmet_requirements=[]))

        await synthesizer.synthesize_insight_package(
            request_id="REQ_1", request_version=1, package_version=1,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences, insight_requirements=_requirements(),
            manifest=manifest, source_payloads=payloads,
        )

        assert fake.requested_schema is _SynthesisOutput

    def test_system_prompt_text_unchanged_by_this_fix(self):
        """This fix must only touch the user-message builder -- the system
        prompt (and structured-output schemas, covered above) stay intact."""
        assert "{categories}" in synthesizer.SYNTHESIS_SYSTEM_PROMPT
        assert "{total_count}" in synthesizer.SYNTHESIS_SYSTEM_PROMPT
        assert "{max_per_company}" in synthesizer.SYNTHESIS_SYSTEM_PROMPT
        assert "preferences" not in synthesizer.SYNTHESIS_SYSTEM_PROMPT.lower()


class TestReq1005CreditRiskInterpretation:
    """Regression coverage for the REQ_1005 failure and its full fix: a
    worsening *relationship*-risk score, a lost mandate, and a raw
    credit-exposure balance must never be interpreted as borrower
    credit-risk deterioration; a credit-risk conclusion requires direct
    credit-quality evidence; a mismatched credit-risk draft is safely
    recategorized (not just dropped) when the evidence supports a
    different, well-defined claim; and business impact is never a bare
    copy of exposure.
    """

    @pytest.mark.asyncio
    async def test_exxon_scenario_recategorized_not_credit_risk(self, install_fake_llm, now, preferences):
        """The exact REQ_1005 shape: RISK_048's real text (worsening
        relationship-risk score, a lost mandate, competitor share loss, a
        credit-exposure balance) proposed as credit_risk/
        credit_quality_deteriorating with the exposure copied into
        estimated business impact at 90% confidence. None of that must
        survive: category becomes relationship_risk, confidence is capped
        at 70 (one evidence item), and estimated business impact is absent."""
        manifest, payloads = _payloads_with_evidence(
            now,
            evidence_specs=[
                (
                    "RISK_048", INT, "internal", "Risk assessment",
                    "Credit exposure $10,097,042.03; relationship risk score 63.84 (worsening); a second "
                    "lost mandate to the same named competitor within two quarters signals accelerating "
                    "share loss despite the client's public strength.",
                    "2026-07-01",
                ),
            ],
        )
        draft = _draft(
            company_code="CLI_006", category=InsightCategory.CREDIT_RISK, subtype=InsightSubtype.CREDIT_RISK,
            primary_claim=ClaimType.CREDIT_QUALITY_DETERIORATING,
            title="Worsening Relationship Risk Score",
            finding="Exxon Mobil's credit exposure is $10.1 million with a worsening relationship risk "
            "score of 63.84, indicating accelerating share loss to competitors.",
            why_it_matters="A worsening relationship risk score suggests potential credit risk concerns.",
            risk_severity_score=85, confidence=90,
            exposure_usd=10_100_000, estimated_impact_usd=10_100_000, impact_basis="Full exposure at risk",
            evidence_codes=["RISK_048"],
        )
        install_fake_llm(_SynthesisOutput(insights=[draft], unmet_requirements=[]))

        package = await synthesizer.synthesize_insight_package(
            request_id="REQ_1005", request_version=1, package_version=1,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences, insight_requirements=_requirements(),
            manifest=manifest, source_payloads=payloads,
        )

        assert len(package.insights) == 1
        insight = package.insights[0]
        assert insight.category == InsightCategory.RELATIONSHIP_RISK
        assert insight.subtype == InsightSubtype.RELATIONSHIP_RISK
        assert insight.primary_claim == ClaimType.RELATIONSHIP_RISK_WORSENING
        assert insight.confidence <= 70
        assert insight.confidence != 90
        assert insight.business_impact.exposure_usd == 10_100_000
        assert insight.business_impact.estimated_impact_usd is None
        # The credit-risk category requirement is recorded as unmet even
        # though a (correctly categorized) insight was produced.
        credit_risk_unmet = [u for u in package.unmet_requirements if u.category == InsightCategory.CREDIT_RISK]
        assert len(credit_risk_unmet) == 1
        assert "worsening borrower credit quality" in credit_risk_unmet[0].reason

    @pytest.mark.asyncio
    async def test_liabilities_alone_produces_no_credit_risk_insight(self, install_fake_llm, now, preferences):
        """A generic filing figure, with no relationship or credit-risk
        semantics at all, supports nothing -- dropped, no recategorization
        possible."""
        manifest, payloads = _payloads_with_evidence(
            now,
            evidence_specs=[
                ("10-Q", EXT, "external", "SEC filing", "Total liabilities increased 12% year over year.", "2026-08-01"),
            ],
        )
        draft = _draft(
            company_code="CLI_006", category=InsightCategory.CREDIT_RISK, subtype=InsightSubtype.CREDIT_RISK,
            primary_claim=ClaimType.CREDIT_QUALITY_DETERIORATING,
            title="Rising liabilities signal credit risk", risk_severity_score=80, evidence_codes=["10-Q"],
        )
        install_fake_llm(_SynthesisOutput(insights=[draft], unmet_requirements=[]))

        package = await synthesizer.synthesize_insight_package(
            request_id="REQ_1", request_version=1, package_version=1,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences, insight_requirements=_requirements(),
            manifest=manifest, source_payloads=payloads,
        )

        assert package.insights == []
        assert len(package.unmet_requirements) == 1
        assert "no direct indication of worsening borrower credit quality" in package.unmet_requirements[0].reason

    @pytest.mark.asyncio
    async def test_credit_exposure_amount_alone_produces_no_credit_risk_insight(
        self, install_fake_llm, now, preferences
    ):
        """A bare credit-exposure balance, with no relationship-risk or
        credit-quality language at all, supports nothing -- dropped."""
        manifest, payloads = _payloads_with_evidence(
            now,
            evidence_specs=[
                ("RISK_050", INT, "internal", "Risk assessment", "Credit exposure $25,000,000.", "2026-08-01"),
            ],
        )
        draft = _draft(
            company_code="CLI_006", category=InsightCategory.CREDIT_RISK, subtype=InsightSubtype.CREDIT_RISK,
            primary_claim=ClaimType.CREDIT_QUALITY_DETERIORATING,
            title="Large exposure signals credit risk", risk_severity_score=80, evidence_codes=["RISK_050"],
        )
        install_fake_llm(_SynthesisOutput(insights=[draft], unmet_requirements=[]))

        package = await synthesizer.synthesize_insight_package(
            request_id="REQ_1", request_version=1, package_version=1,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences, insight_requirements=_requirements(),
            manifest=manifest, source_payloads=payloads,
        )

        assert package.insights == []
        assert len(package.unmet_requirements) == 1

    @pytest.mark.asyncio
    async def test_worsening_relationship_risk_score_alone_cannot_become_credit_risk(
        self, install_fake_llm, now, preferences
    ):
        """A worsening relationship-risk score, with no competitor/mandate
        language, still can't stay credit_risk -- but IS recategorized to
        relationship_risk since that claim is supported."""
        manifest, payloads = _payloads_with_evidence(
            now,
            evidence_specs=[
                (
                    "RISK_051", INT, "internal", "Risk assessment",
                    "Relationship risk score worsening this quarter.", "2026-08-01",
                ),
            ],
        )
        draft = _draft(
            company_code="CLI_006", category=InsightCategory.CREDIT_RISK, subtype=InsightSubtype.CREDIT_RISK,
            primary_claim=ClaimType.CREDIT_QUALITY_DETERIORATING,
            title="Worsening relationship risk signals credit risk", risk_severity_score=80,
            evidence_codes=["RISK_051"],
        )
        install_fake_llm(_SynthesisOutput(insights=[draft], unmet_requirements=[]))

        package = await synthesizer.synthesize_insight_package(
            request_id="REQ_1", request_version=1, package_version=1,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences, insight_requirements=_requirements(),
            manifest=manifest, source_payloads=payloads,
        )

        assert len(package.insights) == 1
        assert package.insights[0].category == InsightCategory.RELATIONSHIP_RISK
        assert package.insights[0].subtype == InsightSubtype.RELATIONSHIP_RISK

    @pytest.mark.asyncio
    async def test_relationship_deterioration_plus_competitor_loss_produces_relationship_risk_insight(
        self, install_fake_llm, now, preferences
    ):
        """Requirement 7's corroborating-evidence scenario: a risk score, a
        lost opportunity, a client interaction, and an RM note all
        describing the same deterioration -- consolidated into one
        relationship-risk insight with multiple independent source types
        (internal_data_agent + relationship_notes_agent still both count as
        source_type=internal, so this caps at 80, not 90)."""
        manifest, payloads = _payloads_with_evidence(
            now,
            evidence_specs=[
                (
                    "RISK_048", INT, "internal", "Risk assessment",
                    "Relationship risk score 63.84 (worsening); lost mandate to a named competitor.",
                    "2026-07-01",
                ),
                (
                    "OPP_015", INT, "internal", "Lost opportunity",
                    "Bond issuance mandate lost to a competitor.", "2026-08-30",
                ),
                (
                    "INT_048", INT, "internal", "Client interaction",
                    "Client confirmed the competitor is now leading two additional financing conversations.",
                    "2026-06-26",
                ),
                (
                    "NOTE_029", RMN, "internal", "RM note",
                    "Relationship revenue has been declining and the competitor is gaining share.",
                    "2026-06-26",
                ),
            ],
        )
        draft = _draft(
            company_code="CLI_006", category=InsightCategory.RELATIONSHIP_RISK,
            subtype=InsightSubtype.RELATIONSHIP_RISK, primary_claim=ClaimType.RELATIONSHIP_RISK_WORSENING,
            title="Worsening relationship position amid competitor share loss",
            finding="Exxon Mobil's relationship-risk score rose to 63.84 while opportunity and interaction "
            "evidence shows a lost mandate and increasing competitor involvement.",
            risk_severity_score=75, confidence=90,
            evidence_codes=["RISK_048", "OPP_015", "INT_048", "NOTE_029"],
        )
        install_fake_llm(_SynthesisOutput(insights=[draft], unmet_requirements=[]))

        package = await synthesizer.synthesize_insight_package(
            request_id="REQ_1", request_version=1, package_version=1,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences, insight_requirements=_requirements(),
            manifest=manifest, source_payloads=payloads,
        )

        assert len(package.insights) == 1
        insight = package.insights[0]
        assert insight.category == InsightCategory.RELATIONSHIP_RISK
        assert len(insight.evidence) == 4
        assert insight.confidence <= 80  # both source agents are source_type=internal

    @pytest.mark.asyncio
    async def test_covenant_pressure_produces_credit_risk_insight(self, install_fake_llm, now, preferences):
        """Direct covenant pressure -- genuine credit-quality vocabulary --
        survives the gate and keeps the credit_risk category."""
        manifest, payloads = _payloads_with_evidence(
            now,
            evidence_specs=[
                (
                    "RISK_048", INT, "internal", "Risk assessment",
                    "Covenant pressure noted; repayment capacity reduced following the latest credit review.",
                    "2026-08-01",
                ),
            ],
        )
        draft = _draft(
            company_code="CLI_006", category=InsightCategory.CREDIT_RISK, subtype=InsightSubtype.CREDIT_RISK,
            primary_claim=ClaimType.CREDIT_QUALITY_DETERIORATING,
            title="Covenant pressure signals credit-quality deterioration", risk_severity_score=80,
            evidence_codes=["RISK_048"],
        )
        install_fake_llm(_SynthesisOutput(insights=[draft], unmet_requirements=[]))

        package = await synthesizer.synthesize_insight_package(
            request_id="REQ_1", request_version=1, package_version=1,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences, insight_requirements=_requirements(),
            manifest=manifest, source_payloads=payloads,
        )

        assert len(package.insights) == 1
        assert package.insights[0].category == InsightCategory.CREDIT_RISK
        assert package.insights[0].subtype == InsightSubtype.CREDIT_RISK
        assert package.insights[0].primary_claim == ClaimType.CREDIT_QUALITY_DETERIORATING

    @pytest.mark.asyncio
    async def test_delinquency_produces_credit_risk_insight(self, install_fake_llm, now, preferences):
        manifest, payloads = _payloads_with_evidence(
            now,
            evidence_specs=[
                (
                    "RISK_052", INT, "internal", "Risk assessment",
                    "Delinquency observed on the largest facility this quarter.", "2026-08-01",
                ),
            ],
        )
        draft = _draft(
            company_code="CLI_006", category=InsightCategory.CREDIT_RISK, subtype=InsightSubtype.CREDIT_RISK,
            primary_claim=ClaimType.CREDIT_QUALITY_DETERIORATING,
            title="Delinquency signals credit-quality deterioration", risk_severity_score=80,
            evidence_codes=["RISK_052"],
        )
        install_fake_llm(_SynthesisOutput(insights=[draft], unmet_requirements=[]))

        package = await synthesizer.synthesize_insight_package(
            request_id="REQ_1", request_version=1, package_version=1,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences, insight_requirements=_requirements(),
            manifest=manifest, source_payloads=payloads,
        )

        assert len(package.insights) == 1
        assert package.insights[0].category == InsightCategory.CREDIT_RISK

    @pytest.mark.asyncio
    async def test_mixed_evidence_without_limitations_is_dropped(self, install_fake_llm, now, preferences):
        """Cited evidence containing both a stable and an elevated signal
        must be accompanied by an explicit limitations statement, or it is
        dropped -- ambiguity is never silently resolved either way."""
        manifest, payloads = _payloads_with_evidence(
            now,
            evidence_specs=[
                (
                    "RISK_048", INT, "internal", "Risk assessment",
                    "Overall relationship risk remains stable, but the latest review flagged a covenant "
                    "breach in one segment.",
                    "2026-08-01",
                ),
            ],
        )
        draft = _draft(
            company_code="CLI_006", category=InsightCategory.CREDIT_RISK, subtype=InsightSubtype.CREDIT_RISK,
            primary_claim=ClaimType.CREDIT_QUALITY_DETERIORATING,
            title="Segment covenant breach despite stable overall risk", risk_severity_score=65,
            limitations="", evidence_codes=["RISK_048"],
        )
        install_fake_llm(_SynthesisOutput(insights=[draft], unmet_requirements=[]))

        package = await synthesizer.synthesize_insight_package(
            request_id="REQ_1", request_version=1, package_version=1,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences, insight_requirements=_requirements(),
            manifest=manifest, source_payloads=payloads,
        )

        assert package.insights == []
        assert len(package.unmet_requirements) == 1
        assert "mixed" in package.unmet_requirements[0].reason.lower() or "stable" in package.unmet_requirements[0].reason.lower()

    @pytest.mark.asyncio
    async def test_mixed_evidence_with_limitations_is_retained_with_capped_confidence(
        self, install_fake_llm, now, preferences
    ):
        """The same mixed evidence, WITH an explicit limitations statement,
        is retained -- but confidence is capped at 65 regardless of
        breadth."""
        manifest, payloads = _payloads_with_evidence(
            now,
            evidence_specs=[
                (
                    "RISK_048", INT, "internal", "Risk assessment",
                    "Overall relationship risk remains stable, but the latest review flagged a covenant "
                    "breach in one segment.",
                    "2026-08-01",
                ),
            ],
        )
        draft = _draft(
            company_code="CLI_006", category=InsightCategory.CREDIT_RISK, subtype=InsightSubtype.CREDIT_RISK,
            primary_claim=ClaimType.CREDIT_QUALITY_DETERIORATING,
            title="Segment covenant breach despite stable overall risk", risk_severity_score=65, confidence=90,
            limitations="Overall risk is stable; only one segment shows a covenant breach -- treat as an "
            "early signal, not a confirmed portfolio-wide deterioration.",
            evidence_codes=["RISK_048"],
        )
        install_fake_llm(_SynthesisOutput(insights=[draft], unmet_requirements=[]))

        package = await synthesizer.synthesize_insight_package(
            request_id="REQ_1", request_version=1, package_version=1,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences, insight_requirements=_requirements(),
            manifest=manifest, source_payloads=payloads,
        )

        assert len(package.insights) == 1
        assert package.insights[0].confidence <= 65

    @pytest.mark.asyncio
    async def test_reviewer_feedback_changed_insight_passes_validation(self, install_fake_llm, now, preferences):
        original = _ranked_insight_for_previous("PKG_REQ_1_1_INS_0")
        previous_pkg = _previous_package(preferences, original, now)
        manifest, payloads = _payloads_with_evidence(
            now,
            evidence_specs=[
                (
                    "RISK_048", INT, "internal", "Risk assessment",
                    "Relationship risk score worsening this quarter; no credit-quality concerns identified.",
                    "2026-08-01",
                ),
            ],
        )
        revised_draft = _draft(
            company_code="CLI_006", category=InsightCategory.RELATIONSHIP_RISK,
            subtype=InsightSubtype.RELATIONSHIP_RISK, primary_claim=ClaimType.RELATIONSHIP_RISK_WORSENING,
            title="Relationship risk worsening, not a credit-risk concern",
            finding="The latest risk assessment shows a worsening relationship-risk score with no "
            "credit-quality deterioration.",
            risk_severity_score=55, evidence_codes=["RISK_048"],
            revises_insight_id="PKG_REQ_1_1_INS_0",
        )
        install_fake_llm(
            _SynthesisOutput(
                insights=[revised_draft],
                unmet_requirements=[],
                revision_resolutions=[
                    _RevisionResolution(
                        affected_insight_id="PKG_REQ_1_1_INS_0", action="changed",
                        justification="Evidence shows stable risk, not deterioration; recategorized away "
                        "from credit risk.",
                    ),
                ],
            )
        )

        package = await synthesizer.synthesize_insight_package(
            request_id="REQ_1", request_version=1, package_version=2,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences, insight_requirements=_requirements(),
            manifest=manifest, source_payloads=payloads,
            reviewer_comments="Fix the relationship/credit-risk conflation.",
            affected_insight_ids=["PKG_REQ_1_1_INS_0"],
            previous_package=previous_pkg,
        )

        assert len(package.insights) == 1
        assert package.insights[0].category == InsightCategory.RELATIONSHIP_RISK

    @pytest.mark.asyncio
    async def test_reviewer_feedback_removed_insight_passes_validation(self, install_fake_llm, now, preferences):
        original = _ranked_insight_for_previous("PKG_REQ_1_1_INS_0")
        previous_pkg = _previous_package(preferences, original, now)
        manifest, payloads = _payloads_with_evidence(
            now,
            evidence_specs=[
                ("10-Q", EXT, "external", "SEC filing", "Total liabilities increased 12% year over year.", "2026-08-01"),
            ],
        )
        install_fake_llm(
            _SynthesisOutput(
                insights=[],
                unmet_requirements=[],
                revision_resolutions=[
                    _RevisionResolution(
                        affected_insight_id="PKG_REQ_1_1_INS_0", action="removed",
                        justification="No direct credit-risk evidence supports this claim; dropped rather "
                        "than repeating the same unsupported inference.",
                    ),
                ],
            )
        )

        package = await synthesizer.synthesize_insight_package(
            request_id="REQ_1", request_version=1, package_version=2,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences, insight_requirements=_requirements(),
            manifest=manifest, source_payloads=payloads,
            reviewer_comments="Fix or remove the flawed insight.",
            affected_insight_ids=["PKG_REQ_1_1_INS_0"],
            previous_package=previous_pkg,
        )

        assert package.insights == []

    @pytest.mark.asyncio
    async def test_materially_unchanged_affected_insight_fails_validation(self, install_fake_llm, now, preferences):
        """The exact REQ_1005 repeat-after-revision failure: the Synthesizer
        claims 'changed' but returns the same category/subtype/priority/
        finding/evidence -- this must fail synthesis validation, not reach
        the Reviewer again."""
        original = _ranked_insight_for_previous("PKG_REQ_1_1_INS_0")
        previous_pkg = _previous_package(preferences, original, now)
        manifest, payloads = _payloads_with_evidence(
            now,
            evidence_specs=[
                (
                    "RISK_048", INT, "internal", "Risk assessment",
                    "Covenant pressure noted; quarterly credit exposure review completed.", "2026-08-01",
                ),
            ],
        )
        unchanged_draft = _draft(
            company_code="CLI_006", category=InsightCategory.CREDIT_RISK, subtype=InsightSubtype.CREDIT_RISK,
            primary_claim=ClaimType.CREDIT_QUALITY_DETERIORATING,
            priority=InsightPriority.HIGH,
            title="Rising liabilities signal credit risk",
            finding="Liabilities rose, indicating increased credit risk.",
            risk_severity_score=80, evidence_codes=["RISK_048"],
            revises_insight_id="PKG_REQ_1_1_INS_0",
        )
        install_fake_llm(
            _SynthesisOutput(
                insights=[unchanged_draft],
                unmet_requirements=[],
                revision_resolutions=[
                    _RevisionResolution(
                        affected_insight_id="PKG_REQ_1_1_INS_0", action="changed", justification="Updated.",
                    ),
                ],
            )
        )

        with pytest.raises(synthesizer.SynthesisRevisionValidationError, match="materially unchanged"):
            await synthesizer.synthesize_insight_package(
                request_id="REQ_1", request_version=1, package_version=2,
                original_user_prompt="p", effective_research_prompt="p",
                preferences=preferences, insight_requirements=_requirements(),
                manifest=manifest, source_payloads=payloads,
                reviewer_comments="Fix the liabilities/credit-risk contradiction.",
                affected_insight_ids=["PKG_REQ_1_1_INS_0"],
                previous_package=previous_pkg,
            )

    @pytest.mark.asyncio
    async def test_revision_correcting_only_a_monetary_mislabel_is_accepted_as_changed(
        self, install_fake_llm, now, preferences
    ):
        """The REQ_1008 shape: the Reviewer's only complaint is that a dollar
        figure was mislabeled -- reported as exposure_usd when the cited
        evidence is relationship revenue, not credit exposure -- while the
        finding text, category/subtype/priority, and cited evidence are all
        correctly left unchanged. Relabeling the figure is itself the
        requested fix, so this must be accepted as a genuine 'changed'
        revision, not rejected as materially unchanged."""
        original = RankedInsight(
            insight_id="PKG_REQ_1_1_INS_0", rank=1, company_code="CLI_006",
            category=InsightCategory.RELATIONSHIP_RISK, subtype=InsightSubtype.RELATIONSHIP_RISK,
            primary_claim=ClaimType.RELATIONSHIP_RISK_WORSENING,
            persona=InsightPersona.RELATIONSHIP_MANAGER, priority=InsightPriority.HIGH,
            title="Relationship revenue declining amid a lost mandate",
            finding="Relationship revenue has declined and a mandate was lost to a named competitor.",
            why_it_matters="Wallet share is eroding.", recommended_action="Escalate to the executive sponsor.",
            confidence=80, confidence_rationale="Structured revenue and pipeline data.",
            business_impact=BusinessImpact(
                description="$62M in relationship revenue mislabeled as exposure.", exposure_usd=62_000_000,
            ),
            evidence=[
                EvidenceItem(
                    id="EV_1", source_agent=INT, source_type="internal", evidence_code="RELM_144",
                    label="Relationship metric history",
                    detail="Relationship revenue declined this quarter amid a lost mandate to a named competitor.",
                    date="2026-07-01",
                )
            ],
        )
        previous_pkg = _previous_package(preferences, original, now)
        manifest, payloads = _payloads_with_evidence(
            now,
            evidence_specs=[
                (
                    "RELM_144", INT, "internal", "Relationship metric history",
                    "Relationship revenue declined this quarter amid a lost mandate to a named competitor.",
                    "2026-07-01",
                ),
            ],
        )
        corrected_draft = _draft(
            company_code="CLI_006", category=InsightCategory.RELATIONSHIP_RISK,
            subtype=InsightSubtype.RELATIONSHIP_RISK, primary_claim=ClaimType.RELATIONSHIP_RISK_WORSENING,
            priority=InsightPriority.HIGH,
            title="Relationship revenue declining amid a lost mandate",
            finding="Relationship revenue has declined and a mandate was lost to a named competitor.",
            exposure_usd=None, estimated_impact_usd=None, impact_basis=None,
            business_impact_description="$62M in relationship revenue, correctly labeled.",
            evidence_codes=["RELM_144"],
            revises_insight_id="PKG_REQ_1_1_INS_0",
        )
        install_fake_llm(
            _SynthesisOutput(
                insights=[corrected_draft],
                unmet_requirements=[],
                revision_resolutions=[
                    _RevisionResolution(
                        affected_insight_id="PKG_REQ_1_1_INS_0", action="changed",
                        justification="Relabeled the $62M figure as relationship revenue, not credit exposure.",
                    ),
                ],
            )
        )

        package = await synthesizer.synthesize_insight_package(
            request_id="REQ_1", request_version=1, package_version=2,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences, insight_requirements=_requirements(),
            manifest=manifest, source_payloads=payloads,
            reviewer_comments="Fix the monetary mislabeling.",
            affected_insight_ids=["PKG_REQ_1_1_INS_0"],
            previous_package=previous_pkg,
        )

        assert len(package.insights) == 1
        assert package.insights[0].business_impact.exposure_usd is None

    @pytest.mark.asyncio
    async def test_unaddressed_affected_insight_fails_validation(self, install_fake_llm, now, preferences):
        """The regenerated package must explicitly identify how each
        Reviewer comment was resolved -- silently omitting an affected id
        from revision_resolutions is not a valid outcome."""
        original = _ranked_insight_for_previous("PKG_REQ_1_1_INS_0")
        previous_pkg = _previous_package(preferences, original, now)
        manifest, payloads = _payloads_with_evidence(
            now,
            evidence_specs=[
                ("10-Q", EXT, "external", "SEC filing", "Total liabilities increased 12% year over year.", "2026-08-01"),
            ],
        )
        install_fake_llm(_SynthesisOutput(insights=[], unmet_requirements=[], revision_resolutions=[]))

        with pytest.raises(synthesizer.SynthesisRevisionValidationError, match="not addressed"):
            await synthesizer.synthesize_insight_package(
                request_id="REQ_1", request_version=1, package_version=2,
                original_user_prompt="p", effective_research_prompt="p",
                preferences=preferences, insight_requirements=_requirements(),
                manifest=manifest, source_payloads=payloads,
                reviewer_comments="Fix the liabilities/credit-risk contradiction.",
                affected_insight_ids=["PKG_REQ_1_1_INS_0"],
                previous_package=previous_pkg,
            )


class TestRevisionLinkage:
    """Covers requirement E (the REQ_1006 shape): a replacement draft that
    should obviously revise a flagged insight but omits revises_insight_id
    is linked deterministically when unambiguous, and a replacement that
    genuinely gets dropped by evidence/category validation produces a
    validation error naming the real reason, not the generic "no new
    insight has revises_insight_id set to it"."""

    @pytest.mark.asyncio
    async def test_one_unambiguous_replacement_is_linked_automatically(
        self, install_fake_llm, now, preferences
    ):
        original = _ranked_insight_for_previous("PKG_REQ_1_1_INS_0")
        previous_pkg = _previous_package(preferences, original, now)
        manifest, payloads = _payloads_with_evidence(
            now,
            evidence_specs=[
                (
                    "RISK_048", INT, "internal", "Risk assessment",
                    "Relationship risk score worsening this quarter; no credit-quality concerns identified.",
                    "2026-08-01",
                ),
            ],
        )
        # revises_insight_id is deliberately omitted -- the exact REQ_1006
        # failure shape (the model proposed a materially different, correct
        # replacement but never linked it back to the flagged insight).
        unlinked_replacement = _draft(
            company_code="CLI_006", category=InsightCategory.RELATIONSHIP_RISK,
            subtype=InsightSubtype.RELATIONSHIP_RISK, primary_claim=ClaimType.RELATIONSHIP_RISK_WORSENING,
            title="Relationship risk worsening, not a credit-risk concern",
            finding="The latest risk assessment shows a worsening relationship-risk score with no "
            "credit-quality deterioration.",
            risk_severity_score=55, evidence_codes=["RISK_048"],
        )
        install_fake_llm(
            _SynthesisOutput(
                insights=[unlinked_replacement],
                unmet_requirements=[],
                revision_resolutions=[
                    _RevisionResolution(
                        affected_insight_id="PKG_REQ_1_1_INS_0", action="changed",
                        justification="Recategorized away from credit risk.",
                    ),
                ],
            )
        )

        # Must not raise SynthesisRevisionValidationError -- the one
        # unlinked, same-company, materially-different replacement is
        # auto-linked deterministically before validation runs.
        package = await synthesizer.synthesize_insight_package(
            request_id="REQ_1", request_version=1, package_version=2,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences, insight_requirements=_requirements(),
            manifest=manifest, source_payloads=payloads,
            reviewer_comments="Fix the relationship/credit-risk conflation.",
            affected_insight_ids=["PKG_REQ_1_1_INS_0"],
            previous_package=previous_pkg,
        )

        assert len(package.insights) == 1
        assert package.insights[0].category == InsightCategory.RELATIONSHIP_RISK

    @pytest.mark.asyncio
    async def test_dropped_unsupported_replacement_reports_the_real_reason(
        self, install_fake_llm, now, preferences
    ):
        """The REQ_1006 failure as actually observed: the Reviewer asked for
        a change to deal_fee_opportunity, but the replacement cited only a
        legacy lost-mandate/OPP_ record (no DEAL_ evidence), so it was
        correctly dropped by claim validation -- the resulting error must
        say why (deal_fee_opportunity lacked supporting evidence), not the
        generic message that reads the same regardless of cause."""
        original = _ranked_insight_for_previous("PKG_REQ_1_1_INS_0")
        previous_pkg = _previous_package(preferences, original, now)
        manifest, payloads = _payloads_with_evidence(
            now,
            evidence_specs=[
                (
                    "OPP_015", INT, "internal", "Lost opportunity",
                    "Capital markets bond issuance mandate lost to Harrow & Vance Capital.", "2026-08-30",
                ),
            ],
        )
        unsupported_replacement = _draft(
            company_code="CLI_006", category=InsightCategory.DEAL_FEE_OPPORTUNITY,
            subtype=InsightSubtype.DEAL_FEE_OPPORTUNITY, primary_claim=ClaimType.DEAL_FEE_OPPORTUNITY,
            title="Refinancing fee opportunity", evidence_codes=["OPP_015"],
            revises_insight_id="PKG_REQ_1_1_INS_0",
        )
        install_fake_llm(
            _SynthesisOutput(
                insights=[unsupported_replacement],
                unmet_requirements=[],
                revision_resolutions=[
                    _RevisionResolution(
                        affected_insight_id="PKG_REQ_1_1_INS_0", action="changed",
                        justification="Recategorized as a deal/fee opportunity.",
                    ),
                ],
            )
        )

        with pytest.raises(synthesizer.SynthesisRevisionValidationError) as exc_info:
            await synthesizer.synthesize_insight_package(
                request_id="REQ_1006", request_version=1, package_version=2,
                original_user_prompt="p", effective_research_prompt="p",
                preferences=preferences, insight_requirements=_requirements(),
                manifest=manifest, source_payloads=payloads,
                reviewer_comments="Recategorize as deal_fee_opportunity.",
                affected_insight_ids=["PKG_REQ_1_1_INS_0"],
                previous_package=previous_pkg,
            )

        message = str(exc_info.value)
        assert "deal_fee_opportunity" in message
        assert "no new insight has revises_insight_id set to it" not in message


class TestExternalDataMigrationCrossSourceSynthesis:
    """Covers the FMP/Alpha Vantage/FRED external-data migration's
    cross-source synthesis requirements: internal and external evidence
    about the same underlying situation combine into one insight rather
    than two, and a credit-quality-deterioration conclusion still requires
    direct credit-quality evidence even when the new external sources are
    involved -- ratios/rates alone (no rating downgrade, covenant breach,
    delinquency, etc.) never qualify, exactly as they never did for
    internal RISK_ evidence (REQ_1005).

    Uses the golden Exxon Mobil scenario from the requester's reference
    seed data: an $850M Term Loan B, fully drawn, 3.25x covenant, maturing
    2026-11-15, with a Critical "Maturity Wall Imminence" internal risk
    flag and a pitched refinancing bond deal -- mirrored by mocked FMP
    leverage/liquidity ratios and a FRED benchmark rate.
    """

    def _golden_exxon_payloads(self, now):
        return _payloads_with_evidence(
            now, company_code="CLI_006",
            evidence_specs=[
                (
                    "RISKFLAG_XOM_MATURITY", INT, "internal", "Internal risk flag",
                    "Maturity Wall Imminence: an $850M Term Loan B (100% utilized, 3.25x covenant) "
                    "matures 2026-11-15; a refinancing bond mandate pitch is in progress.",
                    "2026-08-01",
                ),
                (
                    "FMP_XOM_NET_DEBT_TO_EBITDA_20251231", EXT, "external", "FMP financial ratios",
                    "Net debt to EBITDA of 1.8x; current ratio 1.15; free cash flow yield 4.6%.",
                    "2025-12-31",
                ),
                (
                    "FRED_SOFR_20260901", EXT, "external", "FRED benchmark rate",
                    "SOFR benchmark rate observed at 5.33% as of 2026-09-01, relevant to refinancing "
                    "cost of capital ahead of the Term Loan B maturity.",
                    "2026-09-01",
                ),
            ],
        )

    @pytest.mark.asyncio
    async def test_golden_exxon_refinancing_insight_cites_both_internal_and_external_evidence(
        self, install_fake_llm, now, preferences
    ):
        """A single insight, not one "internal" and one "external" insight
        about the same maturity wall -- citing both an internal risk-flag
        evidence code and external FMP/FRED evidence codes together."""
        manifest, payloads = self._golden_exxon_payloads(now)
        draft = _draft(
            company_code="CLI_006",
            category=InsightCategory.CAPITAL_MARKETS_ADVISORY, subtype=InsightSubtype.OPPORTUNITY_RISK,
            primary_claim=ClaimType.PRODUCT_OR_CROSS_SELL_OPPORTUNITY,
            title="Term Loan B maturity creates refinancing urgency",
            finding="Exxon Mobil's $850M Term Loan B matures 2026-11-15 at 100% utilization against a "
            "3.25x covenant, while current leverage (net debt/EBITDA 1.8x) and the prevailing SOFR "
            "benchmark of 5.33% support a timely refinancing.",
            why_it_matters="A maturity this close, combined with a live refinancing bond pitch, makes "
            "proactive refinancing advisory time-sensitive.",
            recommended_action="Advance the refinancing bond mandate pitch ahead of the November maturity.",
            evidence_codes=["RISKFLAG_XOM_MATURITY", "FMP_XOM_NET_DEBT_TO_EBITDA_20251231", "FRED_SOFR_20260901"],
        )
        install_fake_llm(_SynthesisOutput(insights=[draft], unmet_requirements=[]))

        package = await synthesizer.synthesize_insight_package(
            request_id="REQ_GOLDEN_XOM", request_version=1, package_version=1,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences, insight_requirements=_requirements(
                categories=[ReqCategory(category_id=InsightCategory.CAPITAL_MARKETS_ADVISORY, minimum_count=1)]
            ),
            manifest=manifest, source_payloads=payloads,
        )

        assert len(package.insights) == 1
        insight = package.insights[0]
        evidence_codes = {e.evidence_code for e in insight.evidence}
        assert "RISKFLAG_XOM_MATURITY" in evidence_codes
        assert "FMP_XOM_NET_DEBT_TO_EBITDA_20251231" in evidence_codes
        assert "FRED_SOFR_20260901" in evidence_codes
        # Not misclassified as credit-quality deterioration: no direct
        # credit-quality evidence (a rating downgrade, covenant breach,
        # delinquency, etc.) was cited, only leverage/rate figures.
        assert insight.primary_claim != ClaimType.CREDIT_QUALITY_DETERIORATING

    @pytest.mark.asyncio
    async def test_leverage_ratio_and_benchmark_rate_alone_never_support_credit_quality_deterioration(
        self, install_fake_llm, now, preferences
    ):
        """The same golden evidence, this time proposed AS a credit-risk/
        credit-quality-deteriorating insight -- must never survive AS
        credit_risk, exactly like REQ_1005's internal RISK_ evidence, now
        for FMP/FRED-sourced figures too: net debt/EBITDA and a benchmark
        rate are real, relevant numbers, but neither is a rating downgrade,
        covenant breach, delinquency, or any other direct credit-quality
        signal. Since this same evidence genuinely does support the newer
        financing_liquidity_signal claim (a fully-drawn facility nearing
        maturity, contextualized by leverage and rate evidence), the
        underlying finding is safely recategorized rather than silently
        dropped -- the REQ_1005 recategorization behavior, now exercised by
        one of the new four-category claims instead of a legacy one."""
        manifest, payloads = self._golden_exxon_payloads(now)
        draft = _draft(
            company_code="CLI_006", category=InsightCategory.CREDIT_RISK, subtype=InsightSubtype.CREDIT_RISK,
            primary_claim=ClaimType.CREDIT_QUALITY_DETERIORATING,
            title="Exxon Mobil credit quality deteriorating",
            finding="Rising leverage and financing costs signal deteriorating credit quality ahead of "
            "the Term Loan B maturity.",
            risk_severity_score=85,
            evidence_codes=["RISKFLAG_XOM_MATURITY", "FMP_XOM_NET_DEBT_TO_EBITDA_20251231", "FRED_SOFR_20260901"],
        )
        install_fake_llm(_SynthesisOutput(insights=[draft], unmet_requirements=[]))

        package = await synthesizer.synthesize_insight_package(
            request_id="REQ_GOLDEN_XOM_2", request_version=1, package_version=1,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences, insight_requirements=_requirements(),
            manifest=manifest, source_payloads=payloads,
        )

        assert len(package.insights) == 1
        insight = package.insights[0]
        assert insight.category != InsightCategory.CREDIT_RISK
        assert insight.primary_claim != ClaimType.CREDIT_QUALITY_DETERIORATING
        assert insight.category == InsightCategory.FINANCING_LIQUIDITY
        assert insight.primary_claim == ClaimType.FINANCING_LIQUIDITY_SIGNAL
        # The credit_risk requirement itself is still reported unmet, even
        # though a different, correctly-categorized insight was kept from
        # the same evidence -- see _ClaimResolution.credit_risk_requirement_unmet.
        credit_risk_unmet = [u for u in package.unmet_requirements if u.category == InsightCategory.CREDIT_RISK]
        assert len(credit_risk_unmet) == 1

    @pytest.mark.asyncio
    async def test_covenant_breach_language_does_support_credit_quality_deterioration(
        self, install_fake_llm, now, preferences
    ):
        """The positive control: when external evidence genuinely states a
        qualifying credit signal (here, explicit covenant pressure), a
        credit-risk insight is correctly kept, not over-corrected away."""
        manifest, payloads = _payloads_with_evidence(
            now, company_code="CLI_006",
            evidence_specs=[
                (
                    "FMP_XOM_COVENANT_COMPLIANCE_20260930", EXT, "external", "FMP covenant compliance note",
                    "Leverage has risen to within 0.1x of the 3.25x covenant maximum, indicating covenant "
                    "pressure ahead of the required compliance test.",
                    "2026-09-30",
                ),
            ],
        )
        draft = _draft(
            company_code="CLI_006", category=InsightCategory.CREDIT_RISK, subtype=InsightSubtype.CREDIT_RISK,
            primary_claim=ClaimType.CREDIT_QUALITY_DETERIORATING,
            title="Exxon Mobil approaching covenant threshold",
            finding="Leverage has risen to within 0.1x of the 3.25x covenant maximum, indicating covenant "
            "pressure ahead of the required compliance test.",
            risk_severity_score=80,
            evidence_codes=["FMP_XOM_COVENANT_COMPLIANCE_20260930"],
        )
        install_fake_llm(_SynthesisOutput(insights=[draft], unmet_requirements=[]))

        package = await synthesizer.synthesize_insight_package(
            request_id="REQ_GOLDEN_XOM_3", request_version=1, package_version=1,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences, insight_requirements=_requirements(),
            manifest=manifest, source_payloads=payloads,
        )

        assert len(package.insights) == 1
        assert package.insights[0].category == InsightCategory.CREDIT_RISK
        assert package.insights[0].primary_claim == ClaimType.CREDIT_QUALITY_DETERIORATING

    @pytest.mark.asyncio
    async def test_golden_exxon_refinancing_maps_to_financing_liquidity_not_credit_deterioration(
        self, install_fake_llm, now, preferences
    ):
        """The new four-category schema's own version of this class's other
        two tests: the same golden Exxon evidence (fully drawn $850M
        facility nearing its 2026-11-15 maturity, FMP leverage ratios, a
        FRED benchmark rate) supports a financing_liquidity insight -- being
        fully drawn and close to maturity is a liquidity/refinancing signal,
        never on its own a borrower-credit-quality conclusion, so the claim
        must resolve to financing_liquidity_signal, not
        credit_quality_deteriorating, even though the draft's own claim was
        proposed correctly to begin with."""
        manifest, payloads = self._golden_exxon_payloads(now)
        draft = _draft(
            company_code="CLI_006",
            category=InsightCategory.FINANCING_LIQUIDITY, subtype=InsightSubtype.FINANCING_LIQUIDITY,
            primary_claim=ClaimType.FINANCING_LIQUIDITY_SIGNAL,
            title="Term Loan B maturity creates refinancing urgency",
            finding="Exxon Mobil's $850M Term Loan B matures 2026-11-15 at 100% utilization against a "
            "3.25x covenant, while current leverage (net debt/EBITDA 1.8x) and the prevailing SOFR "
            "benchmark of 5.33% support a timely refinancing.",
            why_it_matters="A maturity this close, combined with a live refinancing bond pitch, makes "
            "proactive refinancing advisory time-sensitive.",
            recommended_action="Advance the refinancing bond mandate pitch ahead of the November maturity.",
            evidence_codes=["RISKFLAG_XOM_MATURITY", "FMP_XOM_NET_DEBT_TO_EBITDA_20251231", "FRED_SOFR_20260901"],
        )
        install_fake_llm(_SynthesisOutput(insights=[draft], unmet_requirements=[]))

        package = await synthesizer.synthesize_insight_package(
            request_id="REQ_GOLDEN_XOM_4", request_version=1, package_version=1,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences, insight_requirements=_requirements(
                categories=[ReqCategory(category_id=InsightCategory.FINANCING_LIQUIDITY, minimum_count=0)]
            ),
            manifest=manifest, source_payloads=payloads,
        )

        assert len(package.insights) == 1
        insight = package.insights[0]
        assert insight.category == InsightCategory.FINANCING_LIQUIDITY
        assert insight.subtype == InsightSubtype.FINANCING_LIQUIDITY
        assert insight.primary_claim == ClaimType.FINANCING_LIQUIDITY_SIGNAL
        # A fully-drawn facility nearing maturity must never, on its own,
        # be converted into a borrower-credit-quality-deterioration claim.
        assert insight.primary_claim != ClaimType.CREDIT_QUALITY_DETERIORATING
        assert insight.category != InsightCategory.CREDIT_RISK
        evidence_codes = {e.evidence_code for e in insight.evidence}
        assert "RISKFLAG_XOM_MATURITY" in evidence_codes
        assert "FMP_XOM_NET_DEBT_TO_EBITDA_20251231" in evidence_codes
        assert "FRED_SOFR_20260901" in evidence_codes


class TestDeterministicConfidenceCaps:
    """Regression coverage for requirement 6's evidence-based confidence
    ceilings, applied deterministically regardless of what the model
    proposes."""

    @pytest.mark.asyncio
    async def test_one_evidence_item_caps_at_70(self, install_fake_llm, now, preferences):
        manifest, payloads = _manifest_and_payload(now)
        install_fake_llm(_SynthesisOutput(insights=[_draft(confidence=99)], unmet_requirements=[]))

        package = await synthesizer.synthesize_insight_package(
            request_id="REQ_1", request_version=1, package_version=1,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences, insight_requirements=_requirements(),
            manifest=manifest, source_payloads=payloads,
        )

        assert package.insights[0].confidence == 70

    @pytest.mark.asyncio
    async def test_multiple_items_one_source_type_caps_at_80(self, install_fake_llm, now, preferences):
        manifest, payloads = _payloads_with_evidence(
            now,
            evidence_specs=[
                (
                    "RISK_048", INT, "internal", "Risk assessment",
                    "Relationship risk score worsening this quarter.", "2026-08-01",
                ),
                (
                    "RELM_144", INT, "internal", "Relationship metrics",
                    "Relationship risk score worsening; relationship revenue declining.", "2026-08-01",
                ),
            ],
        )
        draft = _draft(
            company_code="CLI_006", confidence=99, evidence_codes=["RISK_048", "RELM_144"],
        )
        install_fake_llm(_SynthesisOutput(insights=[draft], unmet_requirements=[]))

        package = await synthesizer.synthesize_insight_package(
            request_id="REQ_1", request_version=1, package_version=1,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences, insight_requirements=_requirements(),
            manifest=manifest, source_payloads=payloads,
        )

        assert package.insights[0].confidence == 80

    @pytest.mark.asyncio
    async def test_two_independent_source_types_allow_up_to_90(self, install_fake_llm, now, preferences):
        manifest, payloads = _payloads_with_evidence(
            now,
            evidence_specs=[
                (
                    "RISK_048", INT, "internal", "Risk assessment",
                    "Relationship risk score worsening this quarter.", "2026-08-01",
                ),
                (
                    "10-Q", EXT, "external", "SEC filing",
                    "Relationship risk score worsening per management commentary.", "2026-08-01",
                ),
            ],
        )
        draft = _draft(company_code="CLI_006", confidence=99, evidence_codes=["RISK_048", "10-Q"])
        install_fake_llm(_SynthesisOutput(insights=[draft], unmet_requirements=[]))

        package = await synthesizer.synthesize_insight_package(
            request_id="REQ_1", request_version=1, package_version=1,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences, insight_requirements=_requirements(),
            manifest=manifest, source_payloads=payloads,
        )

        assert package.insights[0].confidence == 90

    @pytest.mark.asyncio
    async def test_unresolved_contradictory_evidence_caps_at_65(self, install_fake_llm, now, preferences):
        manifest, payloads = _payloads_with_evidence(
            now,
            evidence_specs=[
                (
                    "RISK_048", INT, "internal", "Risk assessment",
                    "Relationship risk remains stable, but a covenant breach was flagged.", "2026-08-01",
                ),
            ],
        )
        draft = _draft(
            company_code="CLI_006", category=InsightCategory.CREDIT_RISK, subtype=InsightSubtype.CREDIT_RISK,
            primary_claim=ClaimType.CREDIT_QUALITY_DETERIORATING, confidence=99, risk_severity_score=60,
            limitations="Overall risk is stable; only one covenant flag -- treat as an early signal.",
            evidence_codes=["RISK_048"],
        )
        install_fake_llm(_SynthesisOutput(insights=[draft], unmet_requirements=[]))

        package = await synthesizer.synthesize_insight_package(
            request_id="REQ_1", request_version=1, package_version=1,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences, insight_requirements=_requirements(),
            manifest=manifest, source_payloads=payloads,
        )

        assert package.insights[0].confidence == 65


class TestMonetaryFieldSeparation:
    """Regression coverage for requirement 5: exposure and estimated
    business impact are independent, and impact is never a bare copy of
    exposure."""

    @pytest.mark.asyncio
    async def test_exposure_reported_without_impact_when_none_is_supported(
        self, install_fake_llm, now, preferences
    ):
        manifest, payloads = _manifest_and_payload(now)
        draft = _draft(exposure_usd=10_100_000, estimated_impact_usd=None, impact_basis=None)
        install_fake_llm(_SynthesisOutput(insights=[draft], unmet_requirements=[]))

        package = await synthesizer.synthesize_insight_package(
            request_id="REQ_1", request_version=1, package_version=1,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences, insight_requirements=_requirements(),
            manifest=manifest, source_payloads=payloads,
        )

        impact = package.insights[0].business_impact
        assert impact.exposure_usd == 10_100_000
        assert impact.estimated_impact_usd is None

    @pytest.mark.asyncio
    async def test_impact_equal_to_exposure_is_nulled_out(self, install_fake_llm, now, preferences):
        manifest, payloads = _manifest_and_payload(now)
        draft = _draft(
            exposure_usd=10_100_000, estimated_impact_usd=10_100_000,
            impact_basis="Potential risk to the full credit exposure",
        )
        install_fake_llm(_SynthesisOutput(insights=[draft], unmet_requirements=[]))

        package = await synthesizer.synthesize_insight_package(
            request_id="REQ_1", request_version=1, package_version=1,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences, insight_requirements=_requirements(),
            manifest=manifest, source_payloads=payloads,
        )

        assert package.insights[0].business_impact.estimated_impact_usd is None

    @pytest.mark.asyncio
    async def test_impact_without_basis_is_nulled_out(self, install_fake_llm, now, preferences):
        manifest, payloads = _manifest_and_payload(now)
        draft = _draft(exposure_usd=None, estimated_impact_usd=2_000_000, impact_basis=None)
        install_fake_llm(_SynthesisOutput(insights=[draft], unmet_requirements=[]))

        package = await synthesizer.synthesize_insight_package(
            request_id="REQ_1", request_version=1, package_version=1,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences, insight_requirements=_requirements(),
            manifest=manifest, source_payloads=payloads,
        )

        assert package.insights[0].business_impact.estimated_impact_usd is None

    @pytest.mark.asyncio
    async def test_impact_with_real_basis_and_different_from_exposure_is_kept(
        self, install_fake_llm, now, preferences
    ):
        manifest, payloads = _manifest_and_payload(now)
        draft = _draft(
            exposure_usd=10_100_000, estimated_impact_usd=2_000_000,
            impact_basis="20% of the $10.1M exposure, based on the historical recovery rate for this segment",
        )
        install_fake_llm(_SynthesisOutput(insights=[draft], unmet_requirements=[]))

        package = await synthesizer.synthesize_insight_package(
            request_id="REQ_1", request_version=1, package_version=1,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences, insight_requirements=_requirements(),
            manifest=manifest, source_payloads=payloads,
        )

        impact = package.insights[0].business_impact
        assert impact.exposure_usd == 10_100_000
        assert impact.estimated_impact_usd == 2_000_000
        assert impact.impact_basis


class TestUnsupportedClaimsDropped:
    """Regression coverage: an unsupported material inference is dropped
    entirely, not merely assigned lower confidence."""

    @pytest.mark.asyncio
    async def test_unsupported_competitor_share_loss_claim_is_dropped_not_downgraded(
        self, install_fake_llm, now, preferences
    ):
        manifest, payloads = _payloads_with_evidence(
            now,
            evidence_specs=[
                (
                    "RELM_144", INT, "internal", "Relationship metrics",
                    "Transaction volume steady; nothing notable this quarter.", "2026-08-01",
                ),
            ],
        )
        draft = _draft(
            company_code="CLI_006", category=InsightCategory.RELATIONSHIP_RISK,
            subtype=InsightSubtype.RELATIONSHIP_RISK, primary_claim=ClaimType.COMPETITOR_SHARE_LOSS,
            title="Competitor is winning share", confidence=20,  # already low -- must still be dropped, not kept
            evidence_codes=["RELM_144"],
        )
        install_fake_llm(_SynthesisOutput(insights=[draft], unmet_requirements=[]))

        package = await synthesizer.synthesize_insight_package(
            request_id="REQ_1", request_version=1, package_version=1,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences, insight_requirements=_requirements(),
            manifest=manifest, source_payloads=payloads,
        )

        assert package.insights == []
        assert len(package.unmet_requirements) == 1

    @pytest.mark.asyncio
    async def test_no_material_impact_claim_is_dropped_silently(self, install_fake_llm, now, preferences):
        manifest, payloads = _manifest_and_payload(now)
        draft = _draft(primary_claim=ClaimType.NO_MATERIAL_IMPACT)
        install_fake_llm(_SynthesisOutput(insights=[draft], unmet_requirements=[]))

        package = await synthesizer.synthesize_insight_package(
            request_id="REQ_1", request_version=1, package_version=1,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences, insight_requirements=_requirements(),
            manifest=manifest, source_payloads=payloads,
        )

        assert package.insights == []
        assert package.unmet_requirements == []  # no_material_impact is not a requirement gap

    @pytest.mark.asyncio
    async def test_legacy_lost_mandate_alone_never_becomes_deal_fee_opportunity_and_minimum_zero_is_silent(
        self, install_fake_llm, now, preferences
    ):
        """The REQ_1006 shape at the synthesizer level (Goals B+C): a draft
        proposed as deal_fee_opportunity citing only a legacy lost-mandate/
        OPP_ record (no DEAL_ evidence) must never survive as
        deal_fee_opportunity -- an OPP_ record is relationship/competitive
        evidence, not an actual CRM deal. And since the new wizard always
        sends its selected focus areas with minimum_count=0 (an optional
        area, never a quota), the resulting drop must not surface as an
        unmet requirement either -- nothing here should prompt a Reviewer
        revision merely because this optional category produced nothing."""
        manifest, payloads = _payloads_with_evidence(
            now,
            evidence_specs=[
                (
                    "OPP_015", INT, "internal", "Lost opportunity",
                    "Capital markets bond issuance mandate lost to Harrow & Vance Capital.", "2026-08-30",
                ),
            ],
        )
        draft = _draft(
            company_code="CLI_006", category=InsightCategory.DEAL_FEE_OPPORTUNITY,
            subtype=InsightSubtype.DEAL_FEE_OPPORTUNITY, primary_claim=ClaimType.DEAL_FEE_OPPORTUNITY,
            title="Refinancing fee opportunity", evidence_codes=["OPP_015"],
        )
        install_fake_llm(_SynthesisOutput(insights=[draft], unmet_requirements=[]))

        package = await synthesizer.synthesize_insight_package(
            request_id="REQ_1006", request_version=1, package_version=1,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences,
            insight_requirements=_requirements(
                categories=[ReqCategory(category_id=InsightCategory.DEAL_FEE_OPPORTUNITY, minimum_count=0)]
            ),
            manifest=manifest, source_payloads=payloads,
        )

        assert package.insights == []
        assert package.unmet_requirements == []  # minimum_count=0 -> never reported as unmet


class TestApplySynthesisRevision:
    def test_rejects_non_revise_insights_decision(self, now):
        state = WorkflowState.start("REQ_1", occurred_at=now)
        decision = ReviewDecision(
            decision=ReviewDecisionType.PASS, request_id="REQ_1", request_version=1,
            package_version=1, comments="fine", created_at=now,
        )
        with pytest.raises(ValueError, match="requires decision=revise_insights"):
            synthesizer.apply_synthesis_revision(state, decision, occurred_at=now)

    def test_successful_synthesis_revision(self, now):
        state = WorkflowState.start("REQ_1", occurred_at=now)
        decision = ReviewDecision(
            decision=ReviewDecisionType.REVISE_INSIGHTS, request_id="REQ_1", request_version=1,
            package_version=1, comments="dedup these", created_at=now, affected_insight_ids=["PKG_1_1_INS_0"],
        )
        revised = synthesizer.apply_synthesis_revision(state, decision, occurred_at=now)

        assert revised.package_version == 2
        assert revised.synthesis_revision_count == 1
        assert revised.current_stage == WorkflowStage.REVISING_SYNTHESIS
        assert revised.terminal_error is None

    def test_synthesis_revision_audit_message_says_initiated_not_accepted(self, now):
        """Requirement: 'initiated' means the attempt started, not that its
        output was already validated -- 'accepted' overclaimed that."""
        state = WorkflowState.start("REQ_1", occurred_at=now)
        decision = ReviewDecision(
            decision=ReviewDecisionType.REVISE_INSIGHTS, request_id="REQ_1", request_version=1,
            package_version=1, comments="dedup these", created_at=now, affected_insight_ids=["PKG_1_1_INS_0"],
        )
        revised = synthesizer.apply_synthesis_revision(state, decision, occurred_at=now)

        message = revised.audit_events[-1].message
        assert message.startswith("synthesis revision initiated:")
        assert "accepted" not in message

    def test_second_synthesis_revision_succeeds_under_the_default_limit_of_two(self, now):
        state = WorkflowState.start("REQ_1", occurred_at=now)
        first_decision = ReviewDecision(
            decision=ReviewDecisionType.REVISE_INSIGHTS, request_id="REQ_1", request_version=1,
            package_version=1, comments="c1", created_at=now, affected_insight_ids=["PKG_1_1_INS_0"],
        )
        once_revised = synthesizer.apply_synthesis_revision(state, first_decision, occurred_at=now)

        second_decision = ReviewDecision(
            decision=ReviewDecisionType.REVISE_INSIGHTS, request_id="REQ_1", request_version=1,
            package_version=2, comments="c2", created_at=now, affected_insight_ids=["PKG_1_2_INS_0"],
        )
        twice_revised = synthesizer.apply_synthesis_revision(once_revised, second_decision, occurred_at=now)

        assert twice_revised.current_stage == WorkflowStage.REVISING_SYNTHESIS
        assert twice_revised.package_version == 3
        assert twice_revised.synthesis_revision_count == 2
        assert twice_revised.terminal_error is None

    def test_third_synthesis_revision_rejected_with_bounded_retry_reason(self, now):
        state = WorkflowState.start("REQ_1", occurred_at=now)
        first_decision = ReviewDecision(
            decision=ReviewDecisionType.REVISE_INSIGHTS, request_id="REQ_1", request_version=1,
            package_version=1, comments="c1", created_at=now, affected_insight_ids=["PKG_1_1_INS_0"],
        )
        once_revised = synthesizer.apply_synthesis_revision(state, first_decision, occurred_at=now)

        second_decision = ReviewDecision(
            decision=ReviewDecisionType.REVISE_INSIGHTS, request_id="REQ_1", request_version=1,
            package_version=2, comments="c2", created_at=now, affected_insight_ids=["PKG_1_2_INS_0"],
        )
        twice_revised = synthesizer.apply_synthesis_revision(once_revised, second_decision, occurred_at=now)

        third_decision = ReviewDecision(
            decision=ReviewDecisionType.REVISE_INSIGHTS, request_id="REQ_1", request_version=1,
            package_version=3, comments="still not good enough", created_at=now,
            affected_insight_ids=["PKG_1_3_INS_0"],
        )
        rejected = synthesizer.apply_synthesis_revision(twice_revised, third_decision, occurred_at=now)

        assert rejected.current_stage == WorkflowStage.FAILED
        assert rejected.package_version == 3  # unchanged -- the third attempt never took effect
        assert rejected.synthesis_revision_count == 2  # unchanged
        assert "bounded-retry" in rejected.terminal_error
        assert "at most 2 synthesis revision(s)" in rejected.terminal_error

    def test_synthesis_revision_limit_override_is_honored(self, now, monkeypatch):
        """The configured value overrides the default of 2: with the limit
        lowered to 1, a second revision is rejected exactly like the old
        hardcoded behavior."""
        monkeypatch.setattr(synthesizer, "INSIGHTS_MAX_SYNTHESIS_REVISIONS", 1)
        import insights_assistant.contracts.workflow.state as state_module
        monkeypatch.setattr(state_module, "INSIGHTS_MAX_SYNTHESIS_REVISIONS", 1)

        state = WorkflowState.start("REQ_1", occurred_at=now)
        first_decision = ReviewDecision(
            decision=ReviewDecisionType.REVISE_INSIGHTS, request_id="REQ_1", request_version=1,
            package_version=1, comments="c1", created_at=now, affected_insight_ids=["PKG_1_1_INS_0"],
        )
        once_revised = synthesizer.apply_synthesis_revision(state, first_decision, occurred_at=now)
        assert once_revised.current_stage == WorkflowStage.REVISING_SYNTHESIS

        second_decision = ReviewDecision(
            decision=ReviewDecisionType.REVISE_INSIGHTS, request_id="REQ_1", request_version=1,
            package_version=2, comments="c2", created_at=now, affected_insight_ids=["PKG_1_2_INS_0"],
        )
        rejected = synthesizer.apply_synthesis_revision(once_revised, second_decision, occurred_at=now)
        assert rejected.current_stage == WorkflowStage.FAILED
        assert "at most 1 synthesis revision(s)" in rejected.terminal_error

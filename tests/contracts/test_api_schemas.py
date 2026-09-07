"""Round-trip and validation tests for insights_assistant.contracts.api."""

import pytest
from pydantic import ValidationError

from insights_assistant.contracts.api import (
    ApproveInsightRequest,
    BusinessImpact,
    CompanyOption,
    CompanyScopeSelection,
    CreateInsightRequestBody,
    EvidenceItem,
    ExternalResearchSelection,
    Insight,
    InsightRequirementsSelection,
    InternalResearchSelection,
    ListInsightsQuery,
    Metadata,
    RejectInsightRequest,
    RequestInsightCategory,
    ResearchRequestDetail,
    ReviewEvent,
    UserPreferences,
)
from insights_assistant.contracts.api.enums import (
    CompanySelectionMode,
    EvidenceSourceAgent,
    EvidenceSourceType,
    FilingType,
    InsightCategory,
    InsightPersona,
    InsightPriority,
    InsightSubtype,
    RankingCriterion,
    RejectReason,
    RelationshipTier,
    RequestStatus,
    ReviewEventAction,
    ReviewStatus,
    SourceAgentStatus,
)


def _evidence_item(**overrides) -> dict:
    base = dict(
        id="ev-1",
        source_agent=EvidenceSourceAgent.INTERNAL_DATA_AGENT,
        source_type=EvidenceSourceType.INTERNAL,
        evidence_code="RISK_016",
        label="Quarterly risk assessment",
        detail="Relationship risk score 66.87 (worsening).",
        date="2026-07-01",
    )
    base.update(overrides)
    return base


def _review_event(**overrides) -> dict:
    base = dict(
        id="rh-1",
        action=ReviewEventAction.GENERATED,
        actor_id="system",
        actor_display_name="system",
        timestamp="2026-08-14T09:12:00Z",
    )
    base.update(overrides)
    return base


def _insight(**overrides) -> dict:
    base = dict(
        id="ins-1",
        version=1,
        request_id="req-1",
        company_id="company-1",
        company_code="CLI_002",
        company_name="Amazon",
        category=InsightCategory.CREDIT_RISK,
        subtype=InsightSubtype.RELATIONSHIP_RISK,
        persona=InsightPersona.EXECUTIVE_SPONSOR,
        title="Amazon relationship flagged at risk",
        finding="Relationship revenue is down 20% YoY.",
        why_it_matters="Amazon is a tier-1 relationship worth $140M in annual revenue.",
        recommended_action="Escalate to the executive sponsor within one week.",
        priority=InsightPriority.CRITICAL,
        confidence=88,
        confidence_rationale="Three independent, dated RM notes explicitly use at-risk language.",
        business_impact=dict(exposure_usd=35_000_000, description="Annualized relationship revenue at risk."),
        generated_at="2026-08-14T09:12:00Z",
        review_status=ReviewStatus.PENDING,
        review_history=[_review_event()],
        evidence=[_evidence_item()],
        evidence_count=1,
    )
    base.update(overrides)
    return base


class TestCamelCaseWireFormat:
    def test_evidence_item_serializes_to_camel_case(self):
        item = EvidenceItem.model_validate(_evidence_item())
        wire = item.model_dump(mode="json", by_alias=True)
        assert wire["sourceAgent"] == "internal_data_agent"
        assert wire["sourceType"] == "internal"
        assert wire["evidenceCode"] == "RISK_016"
        assert "source_agent" not in wire

    def test_insight_round_trips_by_alias(self):
        insight = Insight.model_validate(_insight())
        wire = insight.model_dump(mode="json", by_alias=True)
        assert wire["whyItMatters"] == insight.why_it_matters
        assert wire["businessImpact"]["exposureUsd"] == 35_000_000
        assert wire["reviewHistory"][0]["actorId"] == "system"

        # populate_by_name=True means the model also accepts its own camelCase output back.
        round_tripped = Insight.model_validate(wire)
        assert round_tripped == insight


class TestOptimisticConcurrencyFields:
    def test_approve_request_requires_expected_version(self):
        with pytest.raises(ValidationError):
            ApproveInsightRequest.model_validate({})

        req = ApproveInsightRequest.model_validate({"expectedVersion": 3})
        assert req.expected_version == 3

    def test_reject_request_requires_reason_and_version(self):
        with pytest.raises(ValidationError):
            RejectInsightRequest.model_validate({"expectedVersion": 1})

        req = RejectInsightRequest.model_validate({"expectedVersion": 1, "reason": "duplicate"})
        assert req.reason == RejectReason.DUPLICATE

    def test_insight_carries_a_version_for_optimistic_concurrency(self):
        insight = Insight.model_validate(_insight(version=7))
        assert insight.version == 7


class TestCompanyScopeSelectionModeValidation:
    def test_explicit_mode_requires_company_ids(self):
        with pytest.raises(ValidationError, match="company_ids is required"):
            CompanyScopeSelection.model_validate(
                {"selectionMode": "explicit", "universe": "fortune_500"}
            )

    def test_explicit_mode_with_company_ids_is_valid(self):
        scope = CompanyScopeSelection.model_validate(
            {"selectionMode": "explicit", "universe": "fortune_500", "companyIds": ["c-1", "c-2"]}
        )
        assert scope.selection_mode == CompanySelectionMode.EXPLICIT

    def test_top_n_mode_requires_top_n(self):
        with pytest.raises(ValidationError, match="top_n is required"):
            CompanyScopeSelection.model_validate({"selectionMode": "top_n", "universe": "fortune_500"})

    def test_industry_filter_mode_requires_industry_filters(self):
        with pytest.raises(ValidationError, match="industry_filters is required"):
            CompanyScopeSelection.model_validate(
                {"selectionMode": "industry_filter", "universe": "fortune_500"}
            )


class TestCreateInsightRequestBody:
    def _valid_body(self, **overrides) -> dict:
        base = dict(
            request_id="11111111-1111-1111-1111-111111111111",
            company_scope=dict(
                universe="fortune_500", selection_mode="explicit", company_ids=["c-1", "c-2"]
            ),
            external_research=dict(edgar_enabled=True, filing_types=["10-K", "10-Q"], lookback_months=24),
            internal_research=dict(
                data_domain_ids=["client_profitability"],
                general_search_prompt="Identify material changes in strategy and liquidity for these companies.",
            ),
            insight_requirements=dict(
                total_count=8,
                categories=[{"category_id": "revenue_cross_sell", "minimum_count": 3}],
                ranking_criteria=["urgency", "commercial_potential"],
            ),
        )
        base.update(overrides)
        return base

    def test_valid_body_parses(self):
        body = CreateInsightRequestBody.model_validate(self._valid_body())
        assert body.company_scope.company_ids == ["c-1", "c-2"]
        assert body.insight_requirements.categories[0].category_id == InsightCategory.REVENUE_CROSS_SELL

    def test_general_search_prompt_below_min_length_is_rejected(self):
        body = self._valid_body()
        body["internal_research"]["general_search_prompt"] = "too short"
        with pytest.raises(ValidationError):
            CreateInsightRequestBody.model_validate(body)

    def test_filing_types_restricted_to_enum(self):
        body = self._valid_body()
        body["external_research"]["filing_types"] = ["10-K", "S-1"]
        with pytest.raises(ValidationError):
            CreateInsightRequestBody.model_validate(body)

    def test_unknown_field_is_rejected(self):
        """extra='forbid' catches typos/drift between client and contract early."""
        body = self._valid_body()
        body["totally_unknown_field"] = True
        with pytest.raises(ValidationError):
            CreateInsightRequestBody.model_validate(body)


class TestListQueriesDefaultsAndBounds:
    def test_list_insights_query_defaults(self):
        query = ListInsightsQuery.model_validate({})
        assert query.page == 1
        assert query.page_size == 20
        assert query.sort_direction.value == "desc"

    def test_list_insights_query_page_size_cap(self):
        with pytest.raises(ValidationError):
            ListInsightsQuery.model_validate({"pageSize": 101})

    def test_confidence_bounds_are_enforced(self):
        with pytest.raises(ValidationError):
            ListInsightsQuery.model_validate({"confidenceMin": 101})


class TestResearchRequestDetail:
    def test_full_request_detail_round_trips(self):
        detail = ResearchRequestDetail.model_validate(
            dict(
                request_id="req-1",
                requested_by="banker-12345",
                status=RequestStatus.PARTIALLY_COMPLETED,
                created_at="2026-08-13T08:00:00Z",
                updated_at="2026-08-15T08:10:00Z",
                company_ids=["c-1", "c-2"],
                company_names=["Amazon", "Alphabet"],
                progress_pct=75,
                counts=dict(generated=8, approved=2, rejected=1, pending=5),
                company_scope=dict(
                    universe="fortune_500",
                    selection_mode="explicit",
                    company_ids=["c-1", "c-2"],
                    companies=[
                        CompanyOption(
                            company_id="c-1",
                            company_code="CLI_002",
                            company_name="Amazon",
                            ticker="AMZN",
                            cik=None,
                            industry="E-Commerce",
                            sector="Consumer Discretionary",
                            relationship_tier=RelationshipTier.TIER_1,
                            fortune_rank=2,
                        )
                    ],
                ),
                external_research=dict(edgar_enabled=True, filing_types=["10-K"], lookback_months=24),
                internal_research=dict(
                    data_domain_ids=["credit_exposure"],
                    general_search_prompt="Identify material changes in strategy and liquidity for these companies.",
                ),
                insight_requirements=dict(
                    total_count=8,
                    categories=[{"category_id": "credit_risk", "minimum_count": 3}],
                    ranking_criteria=["urgency"],
                ),
                result_insight_ids=["ins-1"],
                company_progress=[
                    dict(company_id="c-1", company_name="Amazon", status=SourceAgentStatus.COMPLETED, insights_generated=4),
                    dict(company_id="c-2", company_name="Alphabet", status=SourceAgentStatus.FAILED, insights_generated=0),
                ],
                source_errors=[
                    dict(
                        id="err-1",
                        source=EvidenceSourceAgent.EXTERNAL_DATA_AGENT,
                        company_id="c-2",
                        code="timeout",
                        message="EDGAR tool timed out after 3 retries while fetching 8-K filings.",
                        occurred_at="2026-08-15T08:05:00Z",
                        retryable=True,
                    )
                ],
                error_message=None,
            )
        )
        assert detail.status == RequestStatus.PARTIALLY_COMPLETED
        assert detail.counts.pending == 5
        assert detail.company_progress[1].status == SourceAgentStatus.FAILED
        assert detail.source_errors[0].retryable is True

        wire = detail.model_dump(mode="json", by_alias=True)
        assert wire["resultInsightIds"] == ["ins-1"]
        assert wire["companyScope"]["companies"][0]["companyCode"] == "CLI_002"


def test_user_preferences_round_trips():
    prefs = UserPreferences.model_validate(
        dict(
            display_name="Alex Bianchi",
            role="Relationship Banker",
            default_data_domains=["client_profitability", "credit_exposure"],
            default_ranking_criteria=[RankingCriterion.URGENCY, RankingCriterion.COMMERCIAL_POTENTIAL],
            email_digest_enabled=True,
            at_risk_alerts_enabled=True,
            display_density="comfortable",
            default_lookback_months=24,
        )
    )
    wire = prefs.model_dump(mode="json", by_alias=True)
    assert wire["defaultDataDomains"] == ["client_profitability", "credit_exposure"]
    assert wire["defaultLookbackMonths"] == 24


def test_metadata_round_trips_with_companies_and_filing_types():
    metadata = Metadata.model_validate(
        dict(
            companies=[
                dict(
                    company_id="c-1",
                    company_code="CLI_001",
                    company_name="Walmart",
                    ticker="WMT",
                    cik=None,
                    industry="Retail",
                    sector="Consumer Staples",
                    relationship_tier="tier_1",
                    fortune_rank=1,
                )
            ],
            categories=[{"id": "credit_risk", "label": "Credit risk"}],
            subtypes=[{"id": "relationship_risk", "label": "Relationship risk"}],
            priorities=[{"id": "critical", "label": "Critical"}],
            personas=[{"id": "risk_officer", "label": "Risk Officer"}],
            review_statuses=[{"id": "pending", "label": "Pending review"}],
            reject_reasons=[{"id": "duplicate", "label": "Duplicate"}],
            evidence_source_types=[{"id": "internal", "label": "Internal"}],
            data_domains=[{"id": "credit_exposure", "label": "Credit exposure", "description": "..."}],
            filing_types=[FilingType.FORM_10K, FilingType.FORM_10Q],
            ranking_criteria=[{"id": "urgency", "label": "Urgency"}],
            confidence_tiers=[{"id": "high", "label": "High (>=80)", "min": 80, "max": 100}],
            generated_at="2026-08-20T00:00:00Z",
        )
    )
    assert metadata.companies[0].company_code == "CLI_001"
    wire = metadata.model_dump(mode="json", by_alias=True)
    assert wire["filingTypes"] == ["10-K", "10-Q"]

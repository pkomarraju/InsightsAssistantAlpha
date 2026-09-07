import pytest
from pydantic import ValidationError

from insights_assistant.contracts.api.enums import (
    ClaimType,
    EvidenceSourceAgent,
    EvidenceSourceType,
    InsightCategory,
    InsightPersona,
    InsightPriority,
    InsightSubtype,
)
from insights_assistant.contracts.api.evidence import BusinessImpact, EvidenceItem
from insights_assistant.contracts.workflow.packages import InsightPackage, RankedInsight
from insights_assistant.contracts.workflow.research import PayloadKey


def _evidence_item() -> EvidenceItem:
    return EvidenceItem(
        id="EV_1",
        source_agent=EvidenceSourceAgent.RELATIONSHIP_NOTES_AGENT,
        source_type=EvidenceSourceType.INTERNAL,
        evidence_code="RMN_007",
        label="RM note",
        detail="Client flagged pricing concerns.",
        date="2026-08-20",
    )


def _ranked_insight(**overrides) -> RankedInsight:
    fields = dict(
        insight_id="PKG_1_INS_0",
        rank=1,
        company_code="CLI_001",
        category=InsightCategory.RELATIONSHIP_RISK,
        subtype=InsightSubtype.RELATIONSHIP_RISK,
        primary_claim=ClaimType.RELATIONSHIP_RISK_WORSENING,
        persona=InsightPersona.CREDIT_OFFICER,
        priority=InsightPriority.HIGH,
        title="Credit exposure rising",
        finding="Exposure grew 20% QoQ.",
        why_it_matters="Concentration risk.",
        recommended_action="Schedule a credit review.",
        confidence=80,
        confidence_rationale="Backed by two structured metrics.",
        business_impact=BusinessImpact(exposure_usd=500_000, description="Potential exposure"),
        evidence=[_evidence_item()],
    )
    fields.update(overrides)
    return RankedInsight(**fields)


class TestRankedInsight:
    def test_valid_ranked_insight(self):
        insight = _ranked_insight()
        assert insight.rank == 1

    def test_requires_at_least_one_evidence_item(self):
        with pytest.raises(ValidationError):
            _ranked_insight(evidence=[])

    def test_confidence_must_be_within_0_100(self):
        with pytest.raises(ValidationError):
            _ranked_insight(confidence=101)

    def test_rank_must_be_at_least_one(self):
        with pytest.raises(ValidationError):
            _ranked_insight(rank=0)

    def test_invalid_company_code_rejected(self):
        with pytest.raises(ValidationError):
            _ranked_insight(company_code="Walmart")


class TestInsightPackage:
    def test_valid_package(self, now, preferences):
        package = InsightPackage(
            request_id="REQ_1",
            request_version=1,
            package_version=1,
            original_user_prompt="What's changed for Walmart?",
            effective_research_prompt="Research Walmart's latest 10-K and internal risk data.",
            preferences=preferences,
            source_payload_refs=[
                PayloadKey(company_code="CLI_001", source_agent=EvidenceSourceAgent.RELATIONSHIP_NOTES_AGENT)
            ],
            insights=[_ranked_insight()],
            created_at=now,
        )
        assert package.package_version == 1
        assert len(package.insights) == 1

    def test_requires_at_least_one_source_payload_ref(self, now, preferences):
        with pytest.raises(ValidationError):
            InsightPackage(
                request_id="REQ_1", request_version=1, package_version=1,
                original_user_prompt="p", effective_research_prompt="p",
                preferences=preferences, source_payload_refs=[], insights=[], created_at=now,
            )

    def test_package_version_must_be_at_least_one(self, now, preferences):
        with pytest.raises(ValidationError):
            InsightPackage(
                request_id="REQ_1", request_version=1, package_version=0,
                original_user_prompt="p", effective_research_prompt="p",
                preferences=preferences,
                source_payload_refs=[PayloadKey(company_code="CLI_001", source_agent=EvidenceSourceAgent.EXTERNAL_DATA_AGENT)],
                insights=[], created_at=now,
            )

    def test_insights_list_may_be_empty(self, now, preferences):
        """A package with no supported findings is valid -- synthesis.py's
        existing rule is 'don't manufacture a finding to avoid an empty list'."""
        package = InsightPackage(
            request_id="REQ_1", request_version=1, package_version=1,
            original_user_prompt="p", effective_research_prompt="p",
            preferences=preferences,
            source_payload_refs=[PayloadKey(company_code="CLI_001", source_agent=EvidenceSourceAgent.EXTERNAL_DATA_AGENT)],
            insights=[], created_at=now,
        )
        assert package.insights == []

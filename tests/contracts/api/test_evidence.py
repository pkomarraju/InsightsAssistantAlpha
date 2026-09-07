"""Covers contracts/api/evidence.py: BusinessImpact's estimated_impact_usd/
impact_basis pairing, and EvidenceItem's risk_types/supported_claims/
metric_type default handling.
"""

import pytest
from pydantic import ValidationError

from insights_assistant.contracts.api.enums import (
    ClaimType,
    EvidenceSourceAgent,
    EvidenceSourceType,
    MonetaryMetricType,
    RiskType,
)
from insights_assistant.contracts.api.evidence import BusinessImpact, EvidenceItem


class TestBusinessImpact:
    def test_exposure_only_is_valid(self):
        impact = BusinessImpact(exposure_usd=10_100_000, description="Credit exposure")
        assert impact.exposure_usd == 10_100_000
        assert impact.estimated_impact_usd is None

    def test_neither_field_is_valid(self):
        impact = BusinessImpact(description="No quantified impact")
        assert impact.exposure_usd is None
        assert impact.estimated_impact_usd is None

    def test_estimated_impact_without_basis_is_rejected(self):
        with pytest.raises(ValidationError, match="requires a non-empty impact_basis"):
            BusinessImpact(estimated_impact_usd=2_000_000, description="x")

    def test_estimated_impact_with_basis_is_valid(self):
        impact = BusinessImpact(
            exposure_usd=10_100_000, estimated_impact_usd=2_000_000,
            impact_basis="20% of exposure per historical recovery rate", description="x",
        )
        assert impact.estimated_impact_usd == 2_000_000
        assert impact.impact_basis

    def test_negative_exposure_rejected(self):
        with pytest.raises(ValidationError):
            BusinessImpact(exposure_usd=-1, description="x")


class TestEvidenceItemSemanticsDefaults:
    def test_defaults_are_empty_not_none(self):
        item = EvidenceItem(
            id="EV_1", source_agent=EvidenceSourceAgent.INTERNAL_DATA_AGENT, source_type=EvidenceSourceType.INTERNAL,
            evidence_code="RELM_004", label="Relationship metrics", detail="Transaction volume steady.",
            date="2026-07-01",
        )
        assert item.risk_types == []
        assert item.supported_claims == []
        assert item.metric_type is None

    def test_semantics_fields_accept_real_values(self):
        item = EvidenceItem(
            id="EV_1", source_agent=EvidenceSourceAgent.INTERNAL_DATA_AGENT, source_type=EvidenceSourceType.INTERNAL,
            evidence_code="RISK_048", label="Risk assessment",
            detail="Relationship risk score worsening; a lost mandate to a competitor.",
            date="2026-07-01",
            risk_types=[RiskType.RELATIONSHIP_RISK],
            supported_claims=[ClaimType.RELATIONSHIP_RISK_WORSENING, ClaimType.COMPETITOR_SHARE_LOSS],
            metric_type=MonetaryMetricType.CREDIT_EXPOSURE,
        )
        assert RiskType.RELATIONSHIP_RISK in item.risk_types
        assert ClaimType.CREDIT_QUALITY_DETERIORATING not in item.supported_claims
        assert item.metric_type == MonetaryMetricType.CREDIT_EXPOSURE

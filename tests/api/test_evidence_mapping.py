"""Covers api/evidence_mapping.py's evidence-semantics classifier
(classify_evidence_semantics, evidence_is_mixed, compute_confidence_cap,
has_direct_credit_quality_evidence) -- the deterministic layer the REQ_1005
fix is built on. All pattern-based, no LLM/network call.
"""

from insights_assistant.api import evidence_mapping
from insights_assistant.contracts.api.enums import (
    ClaimType,
    EvidenceSourceAgent,
    EvidenceSourceType,
    MonetaryMetricType,
    RiskType,
)
from insights_assistant.contracts.api.evidence import EvidenceItem


def _item(evidence_code, label, detail, *, source_type=EvidenceSourceType.INTERNAL) -> EvidenceItem:
    semantics = evidence_mapping.classify_evidence_semantics(evidence_code, label, detail)
    return EvidenceItem(
        id=f"EV_{evidence_code}", source_agent=EvidenceSourceAgent.INTERNAL_DATA_AGENT, source_type=source_type,
        evidence_code=evidence_code, label=label, detail=detail, date="2026-07-01",
        risk_types=list(semantics.risk_types), supported_claims=list(semantics.supported_claims),
        metric_type=semantics.metric_type,
    )


class TestClassifyEvidenceSemantics:
    def test_risk_048_supports_relationship_risk_not_credit_risk(self):
        """The exact acceptance case: RISK_048's real explanatory_comment
        must support relationship_risk_worsening and competitor_share_loss,
        and must NOT support credit_quality_deteriorating or any credit-risk
        risk_type."""
        semantics = evidence_mapping.classify_evidence_semantics(
            "RISK_048", "Risk assessment",
            "Relationship risk trending sharply worse; a second lost mandate to the same named competitor "
            "within two quarters signals accelerating share loss despite the client's public strength.",
        )
        assert semantics.risk_types == (RiskType.RELATIONSHIP_RISK,)
        assert set(semantics.supported_claims) == {
            ClaimType.RELATIONSHIP_RISK_WORSENING, ClaimType.COMPETITOR_SHARE_LOSS,
        }
        assert ClaimType.CREDIT_QUALITY_DETERIORATING not in semantics.supported_claims
        assert RiskType.CREDIT_RISK not in semantics.risk_types

    def test_credit_exposure_amount_does_not_imply_credit_risk(self):
        """A raw credit-exposure figure, on its own, establishes only the
        existence/size of the exposure -- never that it is impaired."""
        semantics = evidence_mapping.classify_evidence_semantics(
            "RISK_050", "Risk assessment", "Credit exposure $25,000,000.",
        )
        assert semantics.metric_type == MonetaryMetricType.CREDIT_EXPOSURE
        assert RiskType.CREDIT_RISK not in semantics.risk_types
        assert ClaimType.CREDIT_QUALITY_DETERIORATING not in semantics.supported_claims

    def test_genuine_credit_quality_vocabulary_is_recognized(self):
        for phrase in [
            "Rating downgrade issued this quarter.",
            "Covenant pressure noted on the largest facility.",
            "Delinquency observed on the revolving facility.",
            "Rising probability of default flagged by the credit team.",
            "Criticized exposure per the latest classification review.",
            "Reduced repayment capacity following the earnings miss.",
            "Liquidity stress evident in the latest cash flow review.",
        ]:
            semantics = evidence_mapping.classify_evidence_semantics("RISK_099", "Risk assessment", phrase)
            assert RiskType.CREDIT_RISK in semantics.risk_types, phrase
            assert ClaimType.CREDIT_QUALITY_DETERIORATING in semantics.supported_claims, phrase

    def test_relationship_risk_without_worsening_direction_has_no_worsening_claim(self):
        semantics = evidence_mapping.classify_evidence_semantics(
            "RISK_008", "Risk assessment", "Relationship risk score stable at 16.4.",
        )
        assert RiskType.RELATIONSHIP_RISK in semantics.risk_types
        assert ClaimType.RELATIONSHIP_RISK_WORSENING not in semantics.supported_claims

    def test_unrelated_text_yields_no_semantics(self):
        semantics = evidence_mapping.classify_evidence_semantics(
            "RELM_004", "Relationship metrics", "Transaction volume steady this quarter.",
        )
        assert semantics.risk_types == ()
        assert semantics.supported_claims == ()
        assert semantics.metric_type is None

    def test_opportunity_prefix_defaults_to_opportunity_value_metric(self):
        semantics = evidence_mapping.classify_evidence_semantics(
            "OPP_015", "Lost opportunity", "Bond issuance mandate, $22,000,000, lost to a competitor.",
        )
        assert semantics.metric_type == MonetaryMetricType.OPPORTUNITY_VALUE
        assert ClaimType.COMPETITOR_SHARE_LOSS in semantics.supported_claims


class TestEvidenceIsMixed:
    def test_stable_and_elevated_together_is_mixed(self):
        items = [
            _item(
                "RISK_048", "Risk assessment",
                "Overall relationship risk remains stable, but a covenant breach was flagged in one segment.",
            )
        ]
        assert evidence_mapping.evidence_is_mixed(items) is True

    def test_stable_only_is_not_mixed(self):
        items = [_item("RISK_001", "Risk assessment", "Risk profile low and stable.")]
        assert evidence_mapping.evidence_is_mixed(items) is False

    def test_elevated_only_is_not_mixed(self):
        items = [_item("RISK_048", "Risk assessment", "Relationship risk score worsening this quarter.")]
        assert evidence_mapping.evidence_is_mixed(items) is False


class TestComputeConfidenceCap:
    def test_one_item_caps_at_70(self):
        items = [_item("RISK_048", "Risk assessment", "Relationship risk score worsening this quarter.")]
        assert evidence_mapping.compute_confidence_cap(items) == 70

    def test_multiple_items_one_source_type_caps_at_80(self):
        items = [
            _item("RISK_048", "Risk assessment", "Relationship risk score worsening this quarter."),
            _item("RELM_144", "Relationship metrics", "Relationship risk score worsening; revenue declining."),
        ]
        assert evidence_mapping.compute_confidence_cap(items) == 80

    def test_two_independent_source_types_allow_90(self):
        items = [
            _item("RISK_048", "Risk assessment", "Relationship risk score worsening this quarter."),
            _item(
                "10-Q", "SEC filing", "Relationship risk score worsening per management commentary.",
                source_type=EvidenceSourceType.EXTERNAL,
            ),
        ]
        assert evidence_mapping.compute_confidence_cap(items) == 90

    def test_mixed_evidence_caps_at_65_even_with_multiple_source_types(self):
        items = [
            _item(
                "RISK_048", "Risk assessment",
                "Overall relationship risk remains stable, but a covenant breach was flagged in one segment.",
            ),
            _item(
                "10-Q", "SEC filing", "Management commentary described risk as stable.",
                source_type=EvidenceSourceType.EXTERNAL,
            ),
        ]
        assert evidence_mapping.compute_confidence_cap(items) == 65

    def test_duplicate_evidence_code_counts_once(self):
        item = _item("RISK_048", "Risk assessment", "Relationship risk score worsening this quarter.")
        assert evidence_mapping.compute_confidence_cap([item, item]) == 70


class TestHasDirectCreditQualityEvidence:
    def test_true_when_a_credit_quality_claim_is_present(self):
        items = [_item("RISK_048", "Risk assessment", "Covenant pressure noted this quarter.")]
        assert evidence_mapping.has_direct_credit_quality_evidence(items) is True

    def test_false_for_relationship_risk_only(self):
        items = [_item("RISK_048", "Risk assessment", "Relationship risk score worsening this quarter.")]
        assert evidence_mapping.has_direct_credit_quality_evidence(items) is False

    def test_false_for_empty_evidence(self):
        assert evidence_mapping.has_direct_credit_quality_evidence([]) is False

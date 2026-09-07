import pytest
from pydantic import ValidationError

from insights_assistant.contracts.api.enums import EvidenceSourceAgent
from insights_assistant.contracts.workflow.enums import ReviewDecisionType
from insights_assistant.contracts.workflow.review import NarrowResearchRevision, ReviewDecision


def _narrow_revision(**overrides) -> NarrowResearchRevision:
    fields = dict(
        company_codes=["CLI_001"],
        source_agents=[EvidenceSourceAgent.EXTERNAL_DATA_AGENT],
        guidance="Re-check the latest 10-Q for a restated figure.",
    )
    fields.update(overrides)
    return NarrowResearchRevision(**fields)


class TestNarrowResearchRevision:
    def test_valid(self):
        revision = _narrow_revision()
        assert revision.company_codes == ["CLI_001"]

    def test_invalid_company_code_rejected(self):
        with pytest.raises(ValidationError, match="invalid company_code"):
            _narrow_revision(company_codes=["Walmart"])

    def test_requires_at_least_one_company_code(self):
        with pytest.raises(ValidationError):
            _narrow_revision(company_codes=[])

    def test_requires_at_least_one_source_agent(self):
        with pytest.raises(ValidationError):
            _narrow_revision(source_agents=[])


class TestReviewDecision:
    def test_pass_requires_no_narrow_revision(self, now):
        decision = ReviewDecision(
            decision=ReviewDecisionType.PASS, request_id="REQ_1", request_version=1,
            package_version=1, comments="Looks good.", created_at=now,
        )
        assert decision.narrow_research_revision is None

    def test_pass_with_narrow_revision_rejected(self, now):
        with pytest.raises(ValidationError, match="only meaningful when decision is revise_research"):
            ReviewDecision(
                decision=ReviewDecisionType.PASS, request_id="REQ_1", request_version=1,
                package_version=1, comments="c", created_at=now,
                narrow_research_revision=_narrow_revision(),
            )

    def test_revise_research_requires_narrow_revision(self, now):
        with pytest.raises(ValidationError, match="narrow_research_revision is required"):
            ReviewDecision(
                decision=ReviewDecisionType.REVISE_RESEARCH, request_id="REQ_1", request_version=1,
                package_version=1, comments="Evidence is stale.", created_at=now,
            )

    def test_revise_research_with_narrow_revision_valid(self, now):
        decision = ReviewDecision(
            decision=ReviewDecisionType.REVISE_RESEARCH, request_id="REQ_1", request_version=1,
            package_version=1, comments="Evidence is stale.", created_at=now,
            narrow_research_revision=_narrow_revision(),
        )
        assert decision.narrow_research_revision is not None

    def test_revise_insights_requires_affected_insight_ids(self, now):
        with pytest.raises(ValidationError, match="affected_insight_ids is required"):
            ReviewDecision(
                decision=ReviewDecisionType.REVISE_INSIGHTS, request_id="REQ_1", request_version=1,
                package_version=1, comments="Priority looks wrong.", created_at=now,
            )

    def test_revise_insights_with_affected_ids_valid(self, now):
        decision = ReviewDecision(
            decision=ReviewDecisionType.REVISE_INSIGHTS, request_id="REQ_1", request_version=1,
            package_version=1, comments="Priority looks wrong.", created_at=now,
            affected_insight_ids=["PKG_1_INS_0"],
        )
        assert decision.affected_insight_ids == ["PKG_1_INS_0"]

    def test_fail_decision_valid_without_extras(self, now):
        decision = ReviewDecision(
            decision=ReviewDecisionType.FAIL, request_id="REQ_1", request_version=2,
            package_version=2, comments="Revision limits exhausted.", created_at=now,
        )
        assert decision.decision == ReviewDecisionType.FAIL

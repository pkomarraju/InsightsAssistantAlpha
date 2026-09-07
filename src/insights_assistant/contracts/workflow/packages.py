"""InsightPackage -- the Synthesizer's output, prior to Reviewer sign-off
and persistence.
"""

from datetime import datetime

from pydantic import Field

from insights_assistant.contracts.api.common import ApiModel
from insights_assistant.contracts.api.enums import (
    ClaimType,
    InsightCategory,
    InsightPersona,
    InsightPriority,
    InsightSubtype,
)
from insights_assistant.contracts.api.evidence import BusinessImpact, EvidenceItem
from insights_assistant.contracts.api.preferences import UserPreferences
from insights_assistant.contracts.workflow.research import COMPANY_CODE_PATTERN, PayloadKey


class RankedInsight(ApiModel):
    """A synthesizer-proposed insight, before it is registered as a
    persisted contracts.api.insights.Insight. Same shape as Insight minus
    the persistence-assigned id/version and the human review_status/
    review_history (those only exist once a package passes Reviewer and gets
    registered) -- plus insight_id (a synthesis-time-scoped identifier that
    ReviewDecision.affected_insight_ids cites) and rank.
    """

    insight_id: str = Field(description="Stable within this package/package_version; not the eventual Insight.id.")
    rank: int = Field(ge=1, description="Position within this package's ranking; 1 = highest ranked.")
    company_code: str = Field(pattern=COMPANY_CODE_PATTERN)
    category: InsightCategory
    subtype: InsightSubtype
    primary_claim: ClaimType = Field(
        description="The semantic claim family this insight makes, deterministically validated against "
        "its cited evidence's own supported_claims before persistence (see agents/synthesizer.py) -- e.g. "
        "relationship_risk_worsening vs. credit_quality_deteriorating, never conflated."
    )
    persona: InsightPersona
    priority: InsightPriority
    title: str
    finding: str
    why_it_matters: str
    recommended_action: str
    confidence: int = Field(ge=0, le=100)
    confidence_rationale: str
    business_impact: BusinessImpact
    evidence: list[EvidenceItem] = Field(min_length=1, description="Evidence-backed only -- never empty.")


class UnmetRequirement(ApiModel):
    """A requested count/category the Synthesizer could not satisfy from the
    available evidence -- recorded explicitly rather than papered over by
    manufacturing a weakly-supported insight to hit a number."""

    category: InsightCategory | None = Field(
        default=None, description="Null for an unmet total_count requirement not tied to one category."
    )
    requested_count: int = Field(ge=0)
    actual_count: int = Field(ge=0)
    reason: str = Field(min_length=1)


class InsightPackage(ApiModel):
    request_id: str
    request_version: int = Field(ge=1)
    package_version: int = Field(ge=1)
    original_user_prompt: str = Field(min_length=1)
    effective_research_prompt: str = Field(
        min_length=1, description="The (possibly revised) prompt actually used for this package's research."
    )
    preferences: UserPreferences
    source_payload_refs: list[PayloadKey] = Field(
        min_length=1, description="Which SourcePayloads (within this request_id/request_version) this was synthesized from."
    )
    insights: list[RankedInsight] = Field(default_factory=list)
    unmet_requirements: list[UnmetRequirement] = Field(default_factory=list)
    created_at: datetime

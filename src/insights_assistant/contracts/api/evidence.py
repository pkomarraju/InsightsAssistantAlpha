"""Evidence citations and review-history entries, shared by Insight."""

from datetime import date, datetime

from pydantic import Field, model_validator

from insights_assistant.contracts.api.common import ApiModel
from insights_assistant.contracts.api.enums import (
    ClaimType,
    EvidenceSourceAgent,
    EvidenceSourceType,
    MonetaryMetricType,
    RejectReason,
    ReviewEventAction,
    RiskType,
)


class EvidenceItem(ApiModel):
    id: str
    source_agent: EvidenceSourceAgent
    source_type: EvidenceSourceType
    evidence_code: str = Field(
        description="Stable citation id from the source system, e.g. RISK_016, "
        "RMN_007, OPP_004. Preserved verbatim, never regenerated."
    )
    label: str
    detail: str
    date: date
    risk_types: list[RiskType] = Field(
        default_factory=list,
        description="Which risk domain(s) this evidence item's own content concerns, deterministically "
        "classified from its label/detail text (api/evidence_mapping.py::classify_evidence_semantics) -- "
        "never inferred from an insight's generated prose. Empty when the item is not risk-relevant "
        "(e.g. a plain revenue or opportunity figure).",
    )
    supported_claims: list[ClaimType] = Field(
        default_factory=list,
        description="Which claim families this evidence item's own content directly supports (e.g. a "
        "worsening relationship_risk_score supports relationship_risk_worsening but not "
        "credit_quality_deteriorating). Used to gate which conclusions a synthesized insight may draw "
        "from citing this item -- see agents/synthesizer.py.",
    )
    metric_type: MonetaryMetricType | None = Field(
        default=None,
        description="What kind of dollar figure this item documents, if any (credit exposure, revenue, "
        "opportunity value, ...). Never implies the amount is itself at risk of being lost -- that "
        "requires a separately justified BusinessImpact.estimated_impact_usd.",
    )


class ReviewEvent(ApiModel):
    id: str
    action: ReviewEventAction
    actor_id: str = Field(
        description="Stable banker identifier (matches ResearchRequestSummary.requested_by); "
        "'system' for the initial generated event."
    )
    actor_display_name: str = Field(
        description="Denormalized display label — never used as a filter/reference value."
    )
    timestamp: datetime
    reason: RejectReason | None = None


class BusinessImpact(ApiModel):
    """The monetary picture for one insight, split by what it actually
    means -- not a single opaque amount. This replaces a prior amount_usd
    field that conflated a raw credit-exposure balance with "business
    impact" (the REQ_1005 failure: a $10.1M credit-exposure figure reported
    as business impact, implying the full exposure was at risk, when
    nothing in the cited evidence supported that).

    exposure_usd / estimated_impact_usd are independent: an insight can
    report exposure without any impact estimate (the common case when no
    documented calculation supports one), or an impact estimate without a
    credit-exposure figure at all (e.g. a revenue or opportunity-value
    insight). estimated_impact_usd must never be set to a bare copy of
    exposure_usd -- the validator below only enforces that a basis is
    given, since Python cannot judge whether a stated calculation is
    sound, but agents/synthesizer.py's deterministic checks additionally
    reject an estimated_impact_usd that exactly equals exposure_usd with a
    basis that does not actually justify treating the full exposure as
    impact.
    """

    exposure_usd: int | None = Field(
        default=None, ge=0, description="Credit exposure evidence establishes, if any. Not a claim of loss."
    )
    estimated_impact_usd: int | None = Field(
        default=None,
        ge=0,
        description="Estimated business impact, present only when impact_basis documents how it was "
        "derived from cited evidence. Absent (null) when no such estimate is supported -- never "
        "defaulted to exposure_usd.",
    )
    impact_basis: str | None = Field(
        default=None,
        min_length=1,
        description="How estimated_impact_usd was derived from cited evidence. Required whenever "
        "estimated_impact_usd is set; must be null/absent otherwise.",
    )
    description: str

    @model_validator(mode="after")
    def _impact_requires_basis(self) -> "BusinessImpact":
        if self.estimated_impact_usd is not None and not (self.impact_basis or "").strip():
            raise ValueError("estimated_impact_usd requires a non-empty impact_basis")
        return self

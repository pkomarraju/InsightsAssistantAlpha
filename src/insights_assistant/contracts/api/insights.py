"""GET /v1/insights, GET /v1/insights/{id}, and the approve/reject/reset
review actions.
"""

from datetime import datetime

from pydantic import Field

from insights_assistant.contracts.api.common import ApiModel, ErrorDetail
from insights_assistant.contracts.api.enums import (
    EvidenceSourceType,
    InsightCategory,
    InsightPersona,
    InsightPriority,
    InsightSortField,
    InsightSubtype,
    RejectReason,
    ReviewStatus,
    SortDirection,
)
from insights_assistant.contracts.api.evidence import BusinessImpact, EvidenceItem, ReviewEvent


class InsightSummary(ApiModel):
    """Lightweight row shape for list responses — omits evidence[] and
    reviewHistory[] to keep list payloads small; fetch GET
    /v1/insights/{id} for the full record.
    """

    id: str
    version: int = Field(ge=1, description="Optimistic-concurrency version.")
    request_id: str
    company_id: str
    company_code: str
    company_name: str
    category: InsightCategory
    subtype: InsightSubtype
    persona: InsightPersona
    title: str
    priority: InsightPriority
    confidence: int = Field(ge=0, le=100)
    business_impact: BusinessImpact
    generated_at: datetime
    review_status: ReviewStatus
    evidence_count: int = Field(ge=0)


class Insight(InsightSummary):
    """Full insight detail, returned by GET /v1/insights/{id} and by every
    review action."""

    finding: str
    why_it_matters: str
    recommended_action: str
    confidence_rationale: str
    review_history: list[ReviewEvent]
    evidence: list[EvidenceItem]


class InsightCounts(ApiModel):
    generated: int = Field(ge=0, description="Total insights matching the current filters (== total).")
    approved: int = Field(ge=0)
    rejected: int = Field(ge=0)
    pending: int = Field(ge=0)


class ListInsightsResponse(ApiModel):
    items: list[InsightSummary]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)
    counts: InsightCounts = Field(description="Reflects the current filter set, not the global table.")


class ListInsightsQuery(ApiModel):
    """Query-parameter shape for GET /v1/insights."""

    review_status: ReviewStatus | None = None
    category: InsightCategory | None = None
    company_id: str | None = None
    persona: InsightPersona | None = None
    priority: InsightPriority | None = None
    confidence_min: int | None = Field(default=None, ge=0, le=100)
    confidence_max: int | None = Field(default=None, ge=0, le=100)
    date_from: str | None = None
    date_to: str | None = None
    request_id: str | None = None
    evidence_source_type: EvidenceSourceType | None = None
    search: str | None = Field(default=None, max_length=200)
    sort_field: InsightSortField = InsightSortField.GENERATED_AT
    sort_direction: SortDirection = SortDirection.DESC
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class ApproveInsightRequest(ApiModel):
    expected_version: int = Field(ge=1)


class RejectInsightRequest(ApiModel):
    expected_version: int = Field(ge=1)
    reason: RejectReason


class ResetInsightReviewRequest(ApiModel):
    expected_version: int = Field(ge=1)


class VersionConflictResponse(ApiModel):
    error: ErrorDetail
    current: Insight = Field(description="The resource's current server-side state, for client reconciliation.")

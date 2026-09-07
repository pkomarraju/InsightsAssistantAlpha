"""Pydantic models for the HTTP API contract defined in docs/api/openapi.yaml.

This package defines the request/response shapes that will replace the
frontend's mock repository layer (`frontend/src/api/mock/*`). It does not
wire up routes, a web framework, or agent orchestration — see
docs/api/MIGRATION_PLAN.md for what comes next.

Field names are snake_case in Python and serialize as camelCase on the wire
(`model_dump(by_alias=True)`), matching `frontend/src/api/contracts.ts` and
the OpenAPI spec exactly.
"""

from insights_assistant.contracts.api.enums import (
    ClaimType,
    CompanySelectionMode,
    ConfidenceTierId,
    DisplayDensity,
    ErrorCode,
    EvidenceSourceAgent,
    EvidenceSourceType,
    FilingType,
    InsightCategory,
    InsightPersona,
    InsightPriority,
    InsightSortField,
    InsightSubtype,
    MonetaryMetricType,
    RankingCriterion,
    RejectReason,
    RelationshipTier,
    RequestSortField,
    RequestStatus,
    ReviewEventAction,
    ReviewStatus,
    RiskType,
    SortDirection,
    SourceAgentStatus,
)
from insights_assistant.contracts.api.common import (
    ApiModel,
    ErrorDetail,
    ErrorResponse,
    IdLabel,
)
from insights_assistant.contracts.api.evidence import (
    BusinessImpact,
    EvidenceItem,
    ReviewEvent,
)
from insights_assistant.contracts.api.metadata import (
    CompanyOption,
    ConfidenceTierOption,
    DataDomainOption,
    Metadata,
)
from insights_assistant.contracts.api.preferences import (
    UpdatePreferencesRequest,
    UserPreferences,
)
from insights_assistant.contracts.api.insights import (
    ApproveInsightRequest,
    Insight,
    InsightCounts,
    InsightSummary,
    ListInsightsQuery,
    ListInsightsResponse,
    RejectInsightRequest,
    ResetInsightReviewRequest,
    VersionConflictResponse,
)
from insights_assistant.contracts.api.requests import (
    CompanyProgress,
    CompanyScopeSelection,
    CreateInsightRequestBody,
    ExternalResearchSelection,
    InsightRequirementsSelection,
    InternalResearchSelection,
    ListInsightRequestsQuery,
    ListInsightRequestsResponse,
    RequestCounts,
    RequestInsightCategory,
    ResearchRequestDetail,
    ResearchRequestSummary,
    SourceError,
)

__all__ = [
    # enums
    "ClaimType",
    "CompanySelectionMode",
    "ConfidenceTierId",
    "DisplayDensity",
    "ErrorCode",
    "EvidenceSourceAgent",
    "EvidenceSourceType",
    "FilingType",
    "InsightCategory",
    "InsightPersona",
    "InsightPriority",
    "InsightSortField",
    "InsightSubtype",
    "MonetaryMetricType",
    "RankingCriterion",
    "RejectReason",
    "RelationshipTier",
    "RequestSortField",
    "RequestStatus",
    "ReviewEventAction",
    "ReviewStatus",
    "RiskType",
    "SortDirection",
    "SourceAgentStatus",
    # common
    "ApiModel",
    "ErrorDetail",
    "ErrorResponse",
    "IdLabel",
    # evidence / review
    "BusinessImpact",
    "EvidenceItem",
    "ReviewEvent",
    # metadata
    "CompanyOption",
    "ConfidenceTierOption",
    "DataDomainOption",
    "Metadata",
    # preferences
    "UpdatePreferencesRequest",
    "UserPreferences",
    # insights
    "ApproveInsightRequest",
    "Insight",
    "InsightCounts",
    "InsightSummary",
    "ListInsightsQuery",
    "ListInsightsResponse",
    "RejectInsightRequest",
    "ResetInsightReviewRequest",
    "VersionConflictResponse",
    # requests
    "CompanyProgress",
    "CompanyScopeSelection",
    "CreateInsightRequestBody",
    "ExternalResearchSelection",
    "InsightRequirementsSelection",
    "InternalResearchSelection",
    "ListInsightRequestsQuery",
    "ListInsightRequestsResponse",
    "RequestCounts",
    "RequestInsightCategory",
    "ResearchRequestDetail",
    "ResearchRequestSummary",
    "SourceError",
]

"""POST /v1/requests, GET /v1/requests, GET /v1/requests/{id}.

CompanyScopeSelection/ExternalResearchSelection/InternalResearchSelection/
InsightRequirementsSelection together are the guided-wizard equivalent of
contracts/research/research_scope_schema.json, addressed by stable
companyId instead of name/ticker. See docs/api/MAPPING.md for the exact
transform from CreateInsightRequestBody into a full research_scope payload.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import Field, model_validator

from insights_assistant.contracts.api.common import ApiModel
from insights_assistant.contracts.api.enums import (
    CompanySelectionMode,
    EvidenceSourceAgent,
    FilingType,
    InsightCategory,
    RankingCriterion,
    RequestSortField,
    RequestStatus,
    SortDirection,
    SourceAgentStatus,
)
from insights_assistant.contracts.api.metadata import CompanyOption


class CompanyScopeSelection(ApiModel):
    """Mirrors research_scope_schema.json#companyScope, addressed by stable
    companyId rather than name/ticker."""

    universe: Literal["fortune_500"] = "fortune_500"
    list_year: int | None = Field(default=None, ge=1955, le=2100)
    selection_mode: CompanySelectionMode
    company_ids: list[str] | None = Field(default=None, description="Required when selection_mode = explicit.")
    top_n: int | None = Field(default=None, ge=1, le=500, description="Required when selection_mode = top_n.")
    industry_filters: list[str] | None = Field(
        default=None, description="Required when selection_mode = industry_filter."
    )

    @model_validator(mode="after")
    def _check_mode_specific_fields(self) -> "CompanyScopeSelection":
        if self.selection_mode == CompanySelectionMode.EXPLICIT and not self.company_ids:
            raise ValueError("company_ids is required when selection_mode is 'explicit'")
        if self.selection_mode == CompanySelectionMode.TOP_N and self.top_n is None:
            raise ValueError("top_n is required when selection_mode is 'top_n'")
        if self.selection_mode == CompanySelectionMode.INDUSTRY_FILTER and not self.industry_filters:
            raise ValueError("industry_filters is required when selection_mode is 'industry_filter'")
        return self


class ExternalResearchSelection(ApiModel):
    """Provider-neutral shape: `enabled`/`providers` (one or more of "fmp",
    "alpha_vantage", "fred") replace the EDGAR-specific `edgar_enabled`/
    `filing_types`, which are now deprecated but kept for backward
    compatibility with an existing client that still sends them --
    `edgar_enabled=true` is accepted as equivalent to `enabled=true` with
    the default provider set (see the validator below), and `filing_types`
    is accepted but never used by anything (see MAPPING.md/agents/orchestrator.py:
    external_data_agent's five curated adapters don't take a filing type at
    all). New requests should set `enabled`/`providers` directly and omit
    both legacy fields.
    """

    edgar_enabled: bool | None = Field(default=None, deprecated=True, description="Deprecated -- use `enabled`.")
    filing_types: list[FilingType] = Field(
        default_factory=list, deprecated=True,
        description="Deprecated and ignored: external_data_agent's curated adapters (FMP/Alpha Vantage/"
        "FRED) have no concept of a filing type. Accepted only for backward compatibility.",
    )
    enabled: bool | None = Field(default=None, description="Whether to run external research at all.")
    providers: list[str] = Field(
        default_factory=list,
        description="Which external providers to use, e.g. ['fmp', 'alpha_vantage', 'fred']. Defaults to "
        "all three when `enabled` is true and this is left empty.",
    )
    lookback_months: int = Field(ge=1, le=60)

    @model_validator(mode="after")
    def _apply_legacy_compatibility(self) -> "ExternalResearchSelection":
        if self.enabled is None:
            if self.edgar_enabled is None:
                raise ValueError("one of `enabled` or the deprecated `edgar_enabled` is required")
            self.enabled = self.edgar_enabled
        if self.enabled and not self.providers:
            self.providers = ["fmp", "alpha_vantage", "fred"]
        return self


class InternalResearchSelection(ApiModel):
    data_domain_ids: list[str] = Field(min_length=1)
    general_search_prompt: str = Field(min_length=20, max_length=8000)
    as_of_date: date | None = Field(default=None, description="Defaults server-side to today if omitted.")


class RequestInsightCategory(ApiModel):
    category_id: InsightCategory
    minimum_count: int = Field(ge=0, le=100)


class InsightRequirementsSelection(ApiModel):
    total_count: int = Field(ge=1, le=100)
    categories: list[RequestInsightCategory] = Field(min_length=1)
    ranking_criteria: list[RankingCriterion] = Field(min_length=1)
    max_insights_per_company: int | None = Field(default=None, ge=1, le=20)


class CreateInsightRequestBody(ApiModel):
    request_id: str = Field(
        description="Client-generated idempotency key (UUID). Reusing it replays the existing request "
        "rather than creating another job."
    )
    company_scope: CompanyScopeSelection
    external_research: ExternalResearchSelection
    internal_research: InternalResearchSelection
    insight_requirements: InsightRequirementsSelection


class SourceError(ApiModel):
    id: str
    source: EvidenceSourceAgent
    company_id: str | None = Field(
        default=None, description="Null if the failure is request-level rather than company-specific."
    )
    code: str = Field(description="Machine-readable failure code, e.g. timeout, rate_limited, no_data, auth_error.")
    message: str
    occurred_at: datetime
    retryable: bool


class CompanyProgress(ApiModel):
    company_id: str
    company_name: str
    status: SourceAgentStatus
    insights_generated: int = Field(ge=0)


class RequestCounts(ApiModel):
    generated: int = Field(ge=0)
    approved: int = Field(ge=0)
    rejected: int = Field(ge=0)
    pending: int = Field(ge=0)


class ResearchRequestSummary(ApiModel):
    request_id: str
    requested_by: str = Field(description="Stable banker identifier, e.g. banker-12345.")
    status: RequestStatus
    created_at: datetime
    updated_at: datetime
    company_ids: list[str]
    company_names: list[str] = Field(
        description="Denormalized for list-view display — never used as a filter/reference value."
    )
    progress_pct: int = Field(ge=0, le=100)
    counts: RequestCounts


class _ResolvedCompanyScope(CompanyScopeSelection):
    companies: list[CompanyOption] = Field(default_factory=list)


class ResearchRequestDetail(ResearchRequestSummary):
    company_scope: _ResolvedCompanyScope
    external_research: ExternalResearchSelection
    internal_research: InternalResearchSelection
    insight_requirements: InsightRequirementsSelection
    result_insight_ids: list[str]
    company_progress: list[CompanyProgress]
    source_errors: list[SourceError]
    error_message: str | None = Field(
        default=None,
        description="Top-level summary error retained for the current UI; source_errors is the structured replacement.",
    )


class ListInsightRequestsResponse(ApiModel):
    items: list[ResearchRequestSummary]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)


class ListInsightRequestsQuery(ApiModel):
    """Query-parameter shape for GET /v1/requests."""

    status: RequestStatus | None = None
    company_id: str | None = None
    requested_by: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    sort_field: RequestSortField = RequestSortField.CREATED_AT
    sort_direction: SortDirection = SortDirection.DESC
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

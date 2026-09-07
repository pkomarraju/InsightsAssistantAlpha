"""GET /v1/metadata — the single source of truth for every enum/option list
the frontend currently hardcodes in filterOptions.ts and wizardState.ts.
"""

from datetime import datetime

from pydantic import Field

from insights_assistant.contracts.api.common import ApiModel, IdLabel
from insights_assistant.contracts.api.enums import ConfidenceTierId, FilingType, RelationshipTier


class CompanyOption(ApiModel):
    company_id: str = Field(description="Stable primary key (company_master.company_id).")
    company_code: str = Field(
        pattern=r"^CLI_[0-9]{3,}$",
        description="Stable business key (company_master.company_code).",
    )
    company_name: str = Field(description="Display label — never used as a filter/reference value.")
    ticker: str
    cik: str | None = Field(default=None, pattern=r"^[0-9]{10}$")
    industry: str
    sector: str
    relationship_tier: RelationshipTier
    fortune_rank: int | None = Field(default=None, ge=1, le=500)


class DataDomainOption(ApiModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9._-]{1,99}$")
    label: str
    description: str


class ConfidenceTierOption(ApiModel):
    id: ConfidenceTierId
    label: str
    min: int = Field(ge=0, le=100)
    max: int = Field(ge=0, le=100)


class Metadata(ApiModel):
    companies: list[CompanyOption]
    categories: list[IdLabel]
    subtypes: list[IdLabel]
    priorities: list[IdLabel]
    personas: list[IdLabel]
    review_statuses: list[IdLabel]
    reject_reasons: list[IdLabel]
    evidence_source_types: list[IdLabel]
    data_domains: list[DataDomainOption]
    filing_types: list[FilingType]
    ranking_criteria: list[IdLabel]
    confidence_tiers: list[ConfidenceTierOption]
    generated_at: datetime

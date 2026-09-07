"""GET/PATCH /v1/preferences."""

from pydantic import Field

from insights_assistant.contracts.api.common import ApiModel
from insights_assistant.contracts.api.enums import DisplayDensity, RankingCriterion


class UserPreferences(ApiModel):
    display_name: str
    role: str
    default_data_domains: list[str] = Field(description="References Metadata.data_domains[].id")
    default_ranking_criteria: list[RankingCriterion]
    email_digest_enabled: bool
    at_risk_alerts_enabled: bool
    display_density: DisplayDensity
    default_lookback_months: int = Field(ge=1, le=60)


class UpdatePreferencesRequest(ApiModel):
    """All fields optional; only provided fields are updated (PATCH semantics)."""

    display_name: str | None = None
    role: str | None = None
    default_data_domains: list[str] | None = None
    default_ranking_criteria: list[RankingCriterion] | None = None
    email_digest_enabled: bool | None = None
    at_risk_alerts_enabled: bool | None = None
    display_density: DisplayDensity | None = None
    default_lookback_months: int | None = Field(default=None, ge=1, le=60)

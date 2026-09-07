"""ReviewDecision -- the Evidence and Quality Review Agent's output."""

import re
from datetime import datetime

from pydantic import Field, model_validator

from insights_assistant.contracts.api.common import ApiModel
from insights_assistant.contracts.api.enums import EvidenceSourceAgent
from insights_assistant.contracts.workflow.enums import ReviewDecisionType
from insights_assistant.contracts.workflow.research import COMPANY_CODE_PATTERN


class NarrowResearchRevision(ApiModel):
    """The 'Refined Research Prompt: record prompt version and narrow the
    retry' behavior from the design doc -- a revise_research decision must
    say exactly what to re-run, not trigger a blind full re-run."""

    company_codes: list[str] = Field(min_length=1)
    source_agents: list[EvidenceSourceAgent] = Field(min_length=1)
    guidance: str = Field(min_length=1, description="Targeted instruction for what the re-run should address.")

    @model_validator(mode="after")
    def _check_company_codes(self) -> "NarrowResearchRevision":
        for code in self.company_codes:
            if not re.match(COMPANY_CODE_PATTERN, code):
                raise ValueError(f"company_codes contains an invalid company_code: {code!r}")
        return self


class ReviewDecision(ApiModel):
    decision: ReviewDecisionType
    request_id: str
    request_version: int = Field(ge=1)
    package_version: int = Field(ge=1)
    comments: str = Field(min_length=1)
    affected_insight_ids: list[str] = Field(default_factory=list)
    affected_source_agents: list[EvidenceSourceAgent] = Field(default_factory=list)
    narrow_research_revision: NarrowResearchRevision | None = None
    created_at: datetime

    @model_validator(mode="after")
    def _check_decision_consistency(self) -> "ReviewDecision":
        has_narrow = self.narrow_research_revision is not None
        if self.decision == ReviewDecisionType.REVISE_RESEARCH and not has_narrow:
            raise ValueError("narrow_research_revision is required when decision is revise_research")
        if self.decision != ReviewDecisionType.REVISE_RESEARCH and has_narrow:
            raise ValueError("narrow_research_revision is only meaningful when decision is revise_research")
        if self.decision == ReviewDecisionType.REVISE_INSIGHTS and not self.affected_insight_ids:
            raise ValueError("affected_insight_ids is required when decision is revise_insights")
        return self

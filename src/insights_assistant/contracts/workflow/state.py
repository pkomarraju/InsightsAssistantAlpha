"""WorkflowState -- the Orchestrator's deterministic revision-handling
state. Frozen and updated only through the with_*() transition methods below,
so the invariants that are structural (which method you call) rather than
purely field-shaped -- the revision-count caps, and which counter each kind
of revision is allowed to touch -- are enforced by ordinary Python code, not
just by a validator that only runs once at construction.
"""

from datetime import datetime

from pydantic import ConfigDict, Field
from pydantic.alias_generators import to_camel

from insights_assistant.contracts.api.common import ApiModel
from insights_assistant.contracts.api.enums import EvidenceSourceAgent
from insights_assistant.contracts.workflow.config import INSIGHTS_MAX_SYNTHESIS_REVISIONS
from insights_assistant.contracts.workflow.enums import SourcePayloadStatus, WorkflowStage
from insights_assistant.contracts.workflow.invariants import WorkflowInvariantError
from insights_assistant.contracts.workflow.research import COMPANY_CODE_PATTERN
from insights_assistant.contracts.workflow.review import NarrowResearchRevision

# synthesis_revision_count's Pydantic upper bound (below) is a generous,
# fixed *structural sanity ceiling* -- not the policy value. The actual
# policy cap is INSIGHTS_MAX_SYNTHESIS_REVISIONS, enforced dynamically in
# with_synthesis_revision below (and again in agents.synthesizer.
# apply_synthesis_revision). Deliberately not wired to
# INSIGHTS_MAX_SYNTHESIS_REVISIONS directly: a Field(le=...) bound is baked
# into the model class at import time, so it wouldn't honor a later
# monkeypatch of the module-level constant the way the runtime check below
# does, and a structural "is this state corrupt" check shouldn't silently
# change shape based on today's operator-configured policy value anyway.
_SYNTHESIS_REVISION_COUNT_SANITY_CEILING = 50


class SourceErrorRecord(ApiModel):
    request_id: str
    request_version: int = Field(ge=1)
    company_code: str = Field(pattern=COMPANY_CODE_PATTERN)
    source_agent: EvidenceSourceAgent
    status: SourcePayloadStatus
    error: str = Field(min_length=1)
    occurred_at: datetime


class AuditEvent(ApiModel):
    stage: WorkflowStage
    message: str
    occurred_at: datetime
    detail: dict | None = None


class WorkflowState(ApiModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        use_enum_values=False,
        frozen=True,
    )

    request_id: str
    current_stage: WorkflowStage
    request_version: int = Field(default=1, ge=1)
    package_version: int = Field(default=1, ge=1)
    research_revision_count: int = Field(default=0, ge=0, le=1)
    synthesis_revision_count: int = Field(default=0, ge=0, le=_SYNTHESIS_REVISION_COUNT_SANITY_CEILING)
    source_errors: list[SourceErrorRecord] = Field(default_factory=list)
    terminal_error: str | None = None
    audit_events: list[AuditEvent] = Field(default_factory=list)
    active_research_revision: NarrowResearchRevision | None = Field(
        default=None,
        description="The Reviewer's narrow revision scope, stored separately from the effective "
        "prompts built from it -- set only by with_research_revision, never mutated afterward.",
    )

    @classmethod
    def start(cls, request_id: str, *, occurred_at: datetime) -> "WorkflowState":
        return cls(
            request_id=request_id,
            current_stage=WorkflowStage.RESEARCHING,
            audit_events=[
                AuditEvent(stage=WorkflowStage.RESEARCHING, message="workflow started", occurred_at=occurred_at)
            ],
        )

    def with_stage(
        self,
        stage: WorkflowStage,
        *,
        message: str,
        occurred_at: datetime,
        detail: dict | None = None,
    ) -> "WorkflowState":
        return self.model_copy(
            update={
                "current_stage": stage,
                "audit_events": [
                    *self.audit_events,
                    AuditEvent(stage=stage, message=message, occurred_at=occurred_at, detail=detail),
                ],
            }
        )

    def with_research_revision(
        self,
        *,
        occurred_at: datetime,
        narrow_revision: NarrowResearchRevision | None = None,
        message: str = "",
    ) -> "WorkflowState":
        """The only transition allowed to increment request_version.
        request_version increments only for revised research. narrow_revision
        is stored on active_research_revision, separate from whatever effective
        prompts get built from it -- see contracts.workflow.review.NarrowResearchRevision."""

        if self.research_revision_count >= 1:
            raise WorkflowInvariantError("research_revision_count is already at its maximum of 1")

        new_version = self.request_version + 1
        note = message or f"request_version incremented to {new_version} for revised research"
        return self.model_copy(
            update={
                "request_version": new_version,
                "research_revision_count": self.research_revision_count + 1,
                "current_stage": WorkflowStage.REVISING_RESEARCH,
                "active_research_revision": narrow_revision,
                "audit_events": [
                    *self.audit_events,
                    AuditEvent(stage=WorkflowStage.REVISING_RESEARCH, message=note, occurred_at=occurred_at),
                ],
            }
        )

    def with_synthesis_revision(self, *, occurred_at: datetime, message: str = "") -> "WorkflowState":
        """The only transition allowed to increment package_version.
        package_version increments only for synthesis regeneration, up to
        INSIGHTS_MAX_SYNTHESIS_REVISIONS (contracts.workflow.config) times
        per request -- read as a bare module-level name so it stays
        monkeypatchable in tests, matching this repo's established
        convention for every other INSIGHTS_* constant."""

        if self.synthesis_revision_count >= INSIGHTS_MAX_SYNTHESIS_REVISIONS:
            raise WorkflowInvariantError(
                f"synthesis_revision_count is already at its maximum of {INSIGHTS_MAX_SYNTHESIS_REVISIONS}"
            )

        new_version = self.package_version + 1
        note = message or f"package_version incremented to {new_version} for synthesis regeneration"
        return self.model_copy(
            update={
                "package_version": new_version,
                "synthesis_revision_count": self.synthesis_revision_count + 1,
                "current_stage": WorkflowStage.REVISING_SYNTHESIS,
                "audit_events": [
                    *self.audit_events,
                    AuditEvent(stage=WorkflowStage.REVISING_SYNTHESIS, message=note, occurred_at=occurred_at),
                ],
            }
        )

    def with_source_error(self, error: SourceErrorRecord, *, occurred_at: datetime) -> "WorkflowState":
        return self.model_copy(
            update={
                "source_errors": [*self.source_errors, error],
                "audit_events": [
                    *self.audit_events,
                    AuditEvent(
                        stage=self.current_stage,
                        message=f"source error: {error.source_agent.value} / {error.company_code}: {error.error}",
                        occurred_at=occurred_at,
                    ),
                ],
            }
        )

    def with_terminal_error(self, message: str, *, occurred_at: datetime) -> "WorkflowState":
        return self.model_copy(
            update={
                "current_stage": WorkflowStage.FAILED,
                "terminal_error": message,
                "audit_events": [
                    *self.audit_events,
                    AuditEvent(stage=WorkflowStage.FAILED, message=message, occurred_at=occurred_at),
                ],
            }
        )

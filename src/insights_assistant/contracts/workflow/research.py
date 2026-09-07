"""ResearchTask, SourcePayload, ResearchManifest, and the required-source
derivation used by deterministic revision handling in the Orchestrator.
"""

from datetime import datetime, timedelta

from pydantic import Field, model_validator

from insights_assistant.contracts.api.common import ApiModel
from insights_assistant.contracts.api.enums import EvidenceSourceAgent
from insights_assistant.contracts.api.evidence import EvidenceItem
from insights_assistant.contracts.api.preferences import UserPreferences
from insights_assistant.contracts.api.requests import ExternalResearchSelection, InternalResearchSelection
from insights_assistant.contracts.workflow.config import (
    INSIGHTS_SOURCE_EXECUTION_TIMEOUT_SECONDS,
    RELATIONSHIP_INTERACTIONS_DOMAIN_ID,
    STRUCTURED_DATA_DOMAIN_IDS,
)
from insights_assistant.contracts.workflow.enums import ManifestStatus, SourcePayloadStatus
from insights_assistant.contracts.workflow.external_research import ProviderStatusReport

COMPANY_CODE_PATTERN = r"^CLI_[0-9]{3,}$"


def required_sources(
    external_research: ExternalResearchSelection,
    internal_research: InternalResearchSelection,
) -> set[EvidenceSourceAgent]:
    """Which specialists a request needs, derived from the same research-scope
    configuration CreateInsightRequestBody carries -- never wait on a
    disabled source.
    """

    sources: set[EvidenceSourceAgent] = set()

    # ExternalResearchSelection.enabled is always populated by its own
    # validator (from the deprecated edgar_enabled when that's all a caller
    # gave) -- this never needs to check edgar_enabled itself.
    if external_research.enabled:
        sources.add(EvidenceSourceAgent.EXTERNAL_DATA_AGENT)

    domain_ids = set(internal_research.data_domain_ids)
    if domain_ids & STRUCTURED_DATA_DOMAIN_IDS:
        sources.add(EvidenceSourceAgent.INTERNAL_DATA_AGENT)
    if RELATIONSHIP_INTERACTIONS_DOMAIN_ID in domain_ids:
        sources.add(EvidenceSourceAgent.RELATIONSHIP_NOTES_AGENT)

    return sources


class PayloadKey(ApiModel):
    """Composite identity of one specialist's work for one company: the
    'source key' the task's invariants refer to (request_id/request_version
    live on the containing SourcePayload/ResearchManifest, not here, since a
    key is only ever compared within one request/version scope)."""

    company_code: str = Field(pattern=COMPANY_CODE_PATTERN)
    source_agent: EvidenceSourceAgent

    def as_tuple(self) -> tuple[str, EvidenceSourceAgent]:
        return (self.company_code, self.source_agent)


class ResearchTask(ApiModel):
    request_id: str
    request_version: int = Field(ge=1)
    company_code: str = Field(pattern=COMPANY_CODE_PATTERN)
    source_agent: EvidenceSourceAgent
    prompt: str = Field(min_length=1, description="The task-specific prompt actually sent to the specialist.")
    original_user_prompt: str = Field(min_length=1, description="The banker's unmodified request, for traceability.")
    preferences: UserPreferences
    created_at: datetime = Field(description="When this task was created/queued -- not when it actually started executing; see SourcePayload.started_at for that.")
    data_domain_ids: list[str] = Field(
        default_factory=list,
        description="The request's selected internal data domain ids, carried through from "
        "CreateRequestInput so agents.research_execution._build_evidence can deterministically drop "
        "any legacy-schema evidence a source_agent=internal_data_agent task reports when this "
        "selection is new-schema-only (contracts.workflow.config.is_new_schema_only_selection) -- see "
        "that config module's module-level comment for why 'credit_exposure' alone can't disambiguate "
        "this on its own. Empty for every other source_agent and for a legacy/mixed selection, where "
        "no such filtering applies.",
    )

    @property
    def key(self) -> PayloadKey:
        return PayloadKey(company_code=self.company_code, source_agent=self.source_agent)


class SourcePayload(ApiModel):
    request_id: str
    request_version: int = Field(ge=1)
    company_code: str = Field(pattern=COMPANY_CODE_PATTERN)
    source_agent: EvidenceSourceAgent
    status: SourcePayloadStatus
    evidence: list[EvidenceItem] = Field(default_factory=list)
    findings: str = Field(
        default="", description="Free-text findings/signals returned by the specialist, prior to synthesis."
    )
    provider_statuses: list[ProviderStatusReport] = Field(
        default_factory=list,
        description="external_data_agent only: per-provider (FMP/Alpha Vantage/FRED) status for this "
        "company, self-reported by the specialist from its adapters' own ProviderCallResult responses "
        "(agents/external_adapters.py) -- see agents/orchestrator.py's SpecialistFindings.provider_statuses. "
        "A COMPLETED overall SourcePayload can still carry a non-completed entry here (e.g. FRED "
        "unavailable while FMP/Alpha Vantage succeeded) -- this is exactly the finer-grained status this "
        "field exists to preserve, never collapsed into the one coarse SourcePayloadStatus above. Always "
        "empty for internal_data_agent/relationship_notes_agent.",
    )
    error: str | None = None
    started_at: datetime = Field(
        description="When the specialist actually acquired the concurrency semaphore and began "
        "executing -- not when its ResearchTask was created/queued (contrast ResearchTask.created_at). "
        "For a source that never got to start before the workflow deadline, this is the best available "
        "timestamp (its task's created_at), since it never began."
    )
    completed_at: datetime

    @property
    def key(self) -> PayloadKey:
        return PayloadKey(company_code=self.company_code, source_agent=self.source_agent)

    @model_validator(mode="after")
    def _check_status_consistency(self) -> "SourcePayload":
        if self.status == SourcePayloadStatus.COMPLETED and self.error is not None:
            raise ValueError("error must be null when status is completed")
        if self.status != SourcePayloadStatus.COMPLETED and self.error is None:
            raise ValueError(f"error is required when status is {self.status.value}")
        if self.completed_at < self.started_at:
            raise ValueError("completed_at must not be before started_at")
        return self


class ResearchManifest(ApiModel):
    request_id: str
    request_version: int = Field(ge=1)
    expected_payload_keys: list[PayloadKey] = Field(min_length=1)
    received_payload_keys: list[PayloadKey] = Field(default_factory=list)
    deadline: datetime
    status: ManifestStatus = ManifestStatus.AWAITING

    @classmethod
    def open(
        cls,
        *,
        request_id: str,
        request_version: int,
        expected_payload_keys: list[PayloadKey],
        now: datetime,
        timeout_seconds: float = INSIGHTS_SOURCE_EXECUTION_TIMEOUT_SECONDS,
    ) -> "ResearchManifest":
        """Convenience constructor: sets deadline = now + timeout_seconds --
        the *overall research-workflow* deadline (every task, every
        company/source), not any one specialist's own execution timeout.
        `now`/`timeout_seconds` are explicit parameters (not read from the
        clock/env internally) so callers and tests stay deterministic.

        The bare default here (one specialist's execution timeout) only
        covers a single-task manifest; the real production call site
        (agents.research_execution.build_manifest_and_tasks) always computes
        and passes an explicit value sized for its actual task count via
        agents.research_execution.compute_research_workflow_timeout_seconds.
        """

        return cls(
            request_id=request_id,
            request_version=request_version,
            expected_payload_keys=expected_payload_keys,
            deadline=now + timedelta(seconds=timeout_seconds),
        )

"""Enumerations for the Synthesizer/Reviewer workflow layer.

Deliberately does not redefine a source-agent enum -- contracts.api.enums
already has EvidenceSourceAgent (external_data_agent / internal_data_agent /
relationship_notes_agent), and everything in this package reuses it.
"""

from enum import StrEnum


class SourcePayloadStatus(StrEnum):
    """Terminal outcome of one specialist's run for one (request_id,
    request_version, company_code, source_agent) key. Unlike
    contracts.api.enums.SourceAgentStatus, there is no pending/running value
    here -- a SourcePayload only exists once a specialist has finished, one
    way or another."""

    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class ManifestStatus(StrEnum):
    """Join-wait status for one request_id/request_version's expected set of
    source payloads."""

    AWAITING = "awaiting"
    READY = "ready"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class WorkflowStage(StrEnum):
    """current_stage on WorkflowState -- the coarse state machine driving
    deterministic revision handling in the Orchestrator, per
    docs/INSIGHTS_ASSISTANT_MULTI_AGENT_DESIGN.md's flow."""

    RESEARCHING = "researching"
    AWAITING_SYNTHESIS = "awaiting_synthesis"
    SYNTHESIZING = "synthesizing"
    AWAITING_REVIEW = "awaiting_review"
    REVIEWING = "reviewing"
    REVISING_RESEARCH = "revising_research"
    REVISING_SYNTHESIS = "revising_synthesis"
    COMPLETED = "completed"
    FAILED = "failed"


class ReviewDecisionType(StrEnum):
    """The Evidence and Quality Review Agent's decision on an InsightPackage."""

    PASS = "pass"
    REVISE_INSIGHTS = "revise_insights"
    REVISE_RESEARCH = "revise_research"
    FAIL = "fail"

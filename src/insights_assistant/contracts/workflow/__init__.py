"""Typed contracts and workflow state for the Insights Synthesizer, Reviewer,
and deterministic revision handling in the Orchestrator (see
docs/INSIGHTS_ASSISTANT_MULTI_AGENT_DESIGN.md for the target agent design
this supports).

This package does not implement any LLM prompts or the execution loop --
it defines the shapes and invariants those will operate on. It reuses
contracts.api.* wherever a shape already exists there (EvidenceSourceAgent,
EvidenceItem, BusinessImpact, UserPreferences, ExternalResearchSelection,
InternalResearchSelection) rather than redefining parallel versions, and is
not yet wired into any HTTP route or docs/api/openapi.yaml.
"""

from insights_assistant.contracts.workflow.config import (
    DEFAULT_RESEARCH_WORKFLOW_TIMEOUT_OVERHEAD_SECONDS,
    DEFAULT_SOURCE_EXECUTION_TIMEOUT_SECONDS,
    INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_OVERHEAD_SECONDS,
    INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_SECONDS,
    INSIGHTS_SOURCE_EXECUTION_TIMEOUT_SECONDS,
    INSIGHTS_SOURCE_JOIN_TIMEOUT_SECONDS,
    RELATIONSHIP_INTERACTIONS_DOMAIN_ID,
    STRUCTURED_DATA_DOMAIN_IDS,
)
from insights_assistant.contracts.workflow.enums import (
    ManifestStatus,
    ReviewDecisionType,
    SourcePayloadStatus,
    WorkflowStage,
)
from insights_assistant.contracts.workflow.invariants import (
    WorkflowInvariantError,
    ensure_ready_for_synthesis,
    is_manifest_ready,
    validate_single_request_version,
    validate_unique_payload_keys,
)
from insights_assistant.contracts.workflow.packages import InsightPackage, RankedInsight, UnmetRequirement
from insights_assistant.contracts.workflow.research import (
    COMPANY_CODE_PATTERN,
    PayloadKey,
    ResearchManifest,
    ResearchTask,
    SourcePayload,
    required_sources,
)
from insights_assistant.contracts.workflow.review import NarrowResearchRevision, ReviewDecision
from insights_assistant.contracts.workflow.state import AuditEvent, SourceErrorRecord, WorkflowState

__all__ = [
    # config
    "DEFAULT_RESEARCH_WORKFLOW_TIMEOUT_OVERHEAD_SECONDS",
    "DEFAULT_SOURCE_EXECUTION_TIMEOUT_SECONDS",
    "INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_OVERHEAD_SECONDS",
    "INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_SECONDS",
    "INSIGHTS_SOURCE_EXECUTION_TIMEOUT_SECONDS",
    "INSIGHTS_SOURCE_JOIN_TIMEOUT_SECONDS",
    "RELATIONSHIP_INTERACTIONS_DOMAIN_ID",
    "STRUCTURED_DATA_DOMAIN_IDS",
    # enums
    "ManifestStatus",
    "ReviewDecisionType",
    "SourcePayloadStatus",
    "WorkflowStage",
    # invariants
    "WorkflowInvariantError",
    "ensure_ready_for_synthesis",
    "is_manifest_ready",
    "validate_single_request_version",
    "validate_unique_payload_keys",
    # packages
    "InsightPackage",
    "RankedInsight",
    "UnmetRequirement",
    # research
    "COMPANY_CODE_PATTERN",
    "PayloadKey",
    "ResearchManifest",
    "ResearchTask",
    "SourcePayload",
    "required_sources",
    # review
    "NarrowResearchRevision",
    "ReviewDecision",
    # state
    "AuditEvent",
    "SourceErrorRecord",
    "WorkflowState",
]

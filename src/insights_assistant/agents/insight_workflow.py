"""The deterministic state machine tying research, synthesis, and review
together for one insight request.

Routing (see docs/INSIGHTS_ASSISTANT_MULTI_AGENT_DESIGN.md):
    research -> synthesize -> review
        pass            -> completed, return the package
        fail            -> failed, no package
        revise_insights -> synthesize again (synthesis_revision_count budget) -> review
        revise_research -> re-run research once more (research_revision_count budget)
                            -> synthesize -> review

The two budgets are independent WorkflowState counters and are NOT
symmetric: research_revision_count has a fixed cap of 1 (contracts.workflow.
state.WorkflowState.with_research_revision); synthesis_revision_count is
capped at INSIGHTS_MAX_SYNTHESIS_REVISIONS (contracts.workflow.config,
default 2). apply_research_revision (agents.research_execution) and
apply_synthesis_revision (agents.synthesizer) each turn an exhausted budget
into a graceful terminal failure rather than a raised exception, so this
loop is structurally bounded -- at most 1 research revision and
INSIGHTS_MAX_SYNTHESIS_REVISIONS synthesis revisions can ever be applied, in
any order, which caps this loop at 2 + INSIGHTS_MAX_SYNTHESIS_REVISIONS
Reviewer calls (the initial call, plus one more per accepted revision of
either kind) no matter what the Reviewer asks for.

Separately, _synthesize_with_validation_retry wraps every synthesize call
with a small, fixed-by-config internal retry (INSIGHTS_SYNTHESIS_VALIDATION_
RETRY_LIMIT) for SynthesisRevisionValidationError specifically -- a
deterministic, Python-side check of whether one synthesis call's own output
actually satisfies the revision-feedback contract, not a Reviewer decision.
This never touches synthesis_revision_count or package_version, and never
calls the Reviewer again in between attempts: it exists so that ordinary LLM
sampling variance on a single synthesis call doesn't burn a reviewer-driven
revision the Reviewer never actually got another chance to weigh in on.

Every review decision is recorded onto the audit trail (WorkflowState.
audit_events[].detail) as it happens, and the caller may pass
on_state_change to observe every intermediate WorkflowState the moment it's
produced -- both exist so a caller like api/server.py can mirror live
progress into a polled resource instead of only seeing the state this
function returns after it's already finished.

A second optional callback, on_package_ready, fires once per synthesized
InsightPackage the instant it has been reviewed -- with that package, the
SourcePayloads it was built from, and the ReviewDecision it received --
regardless of whether the decision was pass/fail/revise_insights/
revise_research. This is the seam api/server.py uses to persist a
debug/review snapshot of every attempt (agents/package_store.py), without
this module knowing anything about JSON or the filesystem; the state
machine itself stays pure.

A revise_insights round carries the Reviewer's affected_insight_ids and the
previous InsightPackage into the next synthesize call, and
agents.synthesizer.synthesize_insight_package validates that every flagged
insight was demonstrably changed, removed, or explicitly retained with a
justification. If it wasn't, synthesize_insight_package raises
SynthesisRevisionValidationError -- retried internally a few times (see
above), and only turned into a terminal failed state once those internal
retries are exhausted, never a wasted Reviewer call on a package already
known not to have addressed the feedback.
"""

import logging
from datetime import datetime, timezone
from typing import Callable

from insights_assistant.agents.reviewer import review_insight_package
from insights_assistant.agents.research_execution import apply_research_revision, run_research_for_request
from insights_assistant.agents.synthesizer import (
    SynthesisRevisionValidationError,
    apply_synthesis_revision,
    synthesize_insight_package,
)
from insights_assistant.contracts.api.enums import EvidenceSourceAgent
from insights_assistant.contracts.api.preferences import UserPreferences
from insights_assistant.contracts.api.requests import InsightRequirementsSelection
from insights_assistant.contracts.workflow.config import INSIGHTS_SYNTHESIS_VALIDATION_RETRY_LIMIT
from insights_assistant.contracts.workflow.enums import ReviewDecisionType, SourcePayloadStatus, WorkflowStage
from insights_assistant.contracts.workflow.invariants import is_manifest_ready
from insights_assistant.contracts.workflow.packages import InsightPackage
from insights_assistant.contracts.workflow.research import ResearchManifest, SourcePayload
from insights_assistant.contracts.workflow.review import NarrowResearchRevision, ReviewDecision
from insights_assistant.contracts.workflow.state import SourceErrorRecord, WorkflowState

logger = logging.getLogger(__name__)


def _describe_incomplete_manifest(manifest: ResearchManifest, source_payloads: list[SourcePayload]) -> str:
    by_key = {payload.key.as_tuple(): payload for payload in source_payloads}
    problems: list[str] = []
    for key in manifest.expected_payload_keys:
        payload = by_key.get(key.as_tuple())
        if payload is None:
            problems.append(f"{key.company_code}/{key.source_agent.value}: missing")
        elif payload.status != SourcePayloadStatus.COMPLETED:
            problems.append(f"{payload.company_code}/{payload.source_agent.value}: {payload.status.value}")
    return "research incomplete: " + "; ".join(problems)


def _record_source_errors(
    state: WorkflowState, source_payloads: list[SourcePayload], *, occurred_at: datetime
) -> WorkflowState:
    for payload in source_payloads:
        if payload.status != SourcePayloadStatus.COMPLETED:
            state = state.with_source_error(
                SourceErrorRecord(
                    request_id=payload.request_id,
                    request_version=payload.request_version,
                    company_code=payload.company_code,
                    source_agent=payload.source_agent,
                    status=payload.status,
                    error=payload.error or "unknown error",
                    occurred_at=occurred_at,
                ),
                occurred_at=occurred_at,
            )
    return state


def _record_review_decision(state: WorkflowState, decision: ReviewDecision, *, occurred_at: datetime) -> WorkflowState:
    """Attaches the Reviewer's decision to the audit trail without changing
    current_stage -- the decision was reached while still in the REVIEWING
    stage; what happens next (pass/fail/revise) is a separate transition.
    detail carries only the Reviewer's own designed-to-be-shown output
    (decision type, its own audit-text comments, affected ids) -- never
    hidden chain-of-thought, which the Reviewer's contract never produces in
    the first place (see agents/reviewer.py).
    """

    return state.with_stage(
        state.current_stage,
        message=f"review decision: {decision.decision.value}",
        occurred_at=occurred_at,
        detail={
            "decision": decision.decision.value,
            "comments": decision.comments,
            "affectedInsightIds": decision.affected_insight_ids,
            "affectedSourceAgents": [agent.value for agent in decision.affected_source_agents],
        },
    )


def _build_effective_prompt(original_user_prompt: str, narrow_revision: NarrowResearchRevision | None) -> str:
    if narrow_revision is None:
        return original_user_prompt
    companies = ", ".join(narrow_revision.company_codes)
    sources = ", ".join(agent.value for agent in narrow_revision.source_agents)
    return (
        f"{original_user_prompt}\n\nRevision guidance ({companies} / {sources}): {narrow_revision.guidance}"
    )


async def _synthesize_with_validation_retry(
    *,
    request_id: str,
    request_version: int,
    package_version: int,
    original_user_prompt: str,
    effective_research_prompt: str,
    preferences: UserPreferences,
    insight_requirements: InsightRequirementsSelection,
    manifest: ResearchManifest,
    source_payloads: list[SourcePayload],
    reviewer_comments: str | None,
    affected_insight_ids: list[str] | None,
    previous_package: InsightPackage | None,
) -> InsightPackage:
    """Retries synthesize_insight_package internally, up to
    INSIGHTS_SYNTHESIS_VALIDATION_RETRY_LIMIT (contracts.workflow.config)
    times, specifically for SynthesisRevisionValidationError -- a
    deterministic, Python-side check of whether one synthesis call's own
    output actually satisfies the revision-feedback contract (every
    previously affected insight demonstrably changed, removed, or retained
    with a justification), not a Reviewer decision. A single synthesis call
    producing a non-compliant revision (e.g. the model claims "changed" but
    the regenerated content is materially identical) can be ordinary LLM
    sampling variance rather than a fundamental inability to satisfy the
    request, so this retries the exact same synthesis attempt -- same
    request_id/request_version/package_version, same affected_insight_ids/
    previous_package -- without ever touching synthesis_revision_count or
    package_version (both already fixed for this attempt by
    apply_synthesis_revision before this is called) and without calling the
    Reviewer again in between attempts. Each retry's reviewer_comments is
    augmented with the specific validation failure, giving the model a
    concrete reason to actually fix it rather than a blind re-roll.

    Only ever matters when affected_insight_ids is set -- synthesize_
    insight_package cannot raise SynthesisRevisionValidationError on a
    first (non-revision) call -- but wraps every call unconditionally so
    there is one call site to keep in sync, not two.

    Re-raises the last SynthesisRevisionValidationError once every retry is
    exhausted; the caller turns that into a terminal WorkflowState.
    """

    comments = reviewer_comments
    last_exc: SynthesisRevisionValidationError | None = None

    for attempt in range(INSIGHTS_SYNTHESIS_VALIDATION_RETRY_LIMIT):
        try:
            return await synthesize_insight_package(
                request_id=request_id,
                request_version=request_version,
                package_version=package_version,
                original_user_prompt=original_user_prompt,
                effective_research_prompt=effective_research_prompt,
                preferences=preferences,
                insight_requirements=insight_requirements,
                manifest=manifest,
                source_payloads=source_payloads,
                reviewer_comments=comments,
                affected_insight_ids=affected_insight_ids,
                previous_package=previous_package,
            )
        except SynthesisRevisionValidationError as exc:
            last_exc = exc
            logger.warning(
                "Synthesis revision validation failed on internal attempt %d/%d for request_id=%s "
                "package_version=%s (not a reviewer-driven revision -- retrying internally): %s",
                attempt + 1, INSIGHTS_SYNTHESIS_VALIDATION_RETRY_LIMIT, request_id, package_version, exc,
            )
            if affected_insight_ids:
                comments = (
                    f"{reviewer_comments}\n\nA deterministic check rejected your previous revision attempt "
                    f"(not the Reviewer): {exc}. Fix this specifically: every previously affected insight "
                    "listed above needs exactly one revision_resolutions entry, and a 'changed' resolution's "
                    "replacement insight must be materially different (category, subtype, priority, "
                    "finding, or evidence), not just reworded."
                )

    assert last_exc is not None  # loop runs at least once (limit is validated > 0) and only exits via return/here
    raise last_exc


async def run_insight_workflow(
    *,
    request_id: str,
    company_codes: list[str],
    required_sources: set[EvidenceSourceAgent],
    prompt_by_company: dict[str, str],
    original_user_prompt: str,
    preferences: UserPreferences,
    insight_requirements: InsightRequirementsSelection,
    now: datetime | None = None,
    on_state_change: Callable[[WorkflowState], None] | None = None,
    on_package_ready: Callable[[InsightPackage, list[SourcePayload], ReviewDecision], None] | None = None,
    data_domain_ids: list[str] | None = None,
) -> tuple[WorkflowState, InsightPackage | None, list[SourcePayload], ReviewDecision | None]:
    """Runs one request end to end. Returns the final WorkflowState, the
    InsightPackage only when the Reviewer passed it (never for a failed
    state, since nothing has been reviewed or approved for persistence at
    that point), the most recent SourcePayload set used (post-revision if a
    research revision occurred), and the last ReviewDecision the Reviewer
    produced (None if research never even reached synthesis).

    on_state_change, if given, is called synchronously with every
    intermediate WorkflowState the instant it's produced -- not just the
    final one this function returns -- so a caller polling a separate
    resource (api/server.py's ResearchRequest) can mirror live progress
    instead of only learning the outcome after this coroutine finishes.

    data_domain_ids (the request's selected internal data domains) is
    passed straight through to every run_research_for_request call below
    (initial run and any research revision) -- see
    agents.research_execution.build_manifest_and_tasks's docstring for what
    it's used for. Omitted by a caller that hasn't been updated, which is
    equivalent to an empty selection: no new-schema-only evidence filtering
    applies, unchanged from this function's pre-existing behavior.
    """

    def _apply(new_state: WorkflowState) -> WorkflowState:
        if on_state_change is not None:
            on_state_change(new_state)
        return new_state

    started_at = now or datetime.now(timezone.utc)
    state = _apply(WorkflowState.start(request_id, occurred_at=started_at))
    last_decision: ReviewDecision | None = None

    manifest, source_payloads = await run_research_for_request(
        request_id=request_id,
        request_version=state.request_version,
        company_codes=company_codes,
        required_sources=required_sources,
        prompt_by_company=prompt_by_company,
        original_user_prompt=original_user_prompt,
        preferences=preferences,
        now=started_at,
        data_domain_ids=data_domain_ids,
    )
    state = _apply(_record_source_errors(state, source_payloads, occurred_at=datetime.now(timezone.utc)))
    if not is_manifest_ready(manifest, source_payloads):
        state = _apply(
            state.with_terminal_error(
                _describe_incomplete_manifest(manifest, source_payloads), occurred_at=datetime.now(timezone.utc)
            )
        )
        return state, None, source_payloads, last_decision

    state = _apply(
        state.with_stage(
            WorkflowStage.AWAITING_SYNTHESIS, message="research complete", occurred_at=datetime.now(timezone.utc)
        )
    )

    effective_research_prompt = original_user_prompt
    reviewer_comments: str | None = None
    affected_insight_ids: list[str] | None = None
    previous_package: InsightPackage | None = None

    while True:
        state = _apply(
            state.with_stage(
                WorkflowStage.SYNTHESIZING,
                message="synthesizing insight package",
                occurred_at=datetime.now(timezone.utc),
            )
        )
        try:
            package = await _synthesize_with_validation_retry(
                request_id=request_id,
                request_version=state.request_version,
                package_version=state.package_version,
                original_user_prompt=original_user_prompt,
                effective_research_prompt=effective_research_prompt,
                preferences=preferences,
                insight_requirements=insight_requirements,
                manifest=manifest,
                source_payloads=source_payloads,
                reviewer_comments=reviewer_comments,
                affected_insight_ids=affected_insight_ids,
                previous_package=previous_package,
            )
        except SynthesisRevisionValidationError as exc:
            # Every internal validation retry (_synthesize_with_validation_
            # retry, INSIGHTS_SYNTHESIS_VALIDATION_RETRY_LIMIT attempts) is
            # already exhausted -- this specific revision genuinely cannot
            # be produced, not just a one-off sampling miss. Fail now,
            # before spending another Reviewer call on a package already
            # known not to have resolved the feedback. This does NOT
            # consume synthesis_revision_count a second time -- that budget
            # was already spent, once, by apply_synthesis_revision before
            # this loop iteration started.
            state = _apply(
                state.with_terminal_error(
                    f"synthesis revision validation failed after {INSIGHTS_SYNTHESIS_VALIDATION_RETRY_LIMIT} "
                    f"internal attempt(s): {exc}",
                    occurred_at=datetime.now(timezone.utc),
                )
            )
            return state, None, source_payloads, last_decision

        state = _apply(
            state.with_stage(
                WorkflowStage.AWAITING_REVIEW,
                message="package ready for review",
                occurred_at=datetime.now(timezone.utc),
            )
        )
        state = _apply(
            state.with_stage(
                WorkflowStage.REVIEWING, message="reviewing package", occurred_at=datetime.now(timezone.utc)
            )
        )
        decision = await review_insight_package(
            insight_requirements=insight_requirements,
            manifest=manifest,
            source_payloads=source_payloads,
            package=package,
        )
        last_decision = decision
        state = _apply(_record_review_decision(state, decision, occurred_at=datetime.now(timezone.utc)))
        if on_package_ready is not None:
            on_package_ready(package, source_payloads, decision)

        if decision.decision == ReviewDecisionType.PASS:
            state = _apply(
                state.with_stage(WorkflowStage.COMPLETED, message="review passed", occurred_at=datetime.now(timezone.utc))
            )
            return state, package, source_payloads, last_decision

        if decision.decision == ReviewDecisionType.FAIL:
            state = _apply(
                state.with_terminal_error(f"review failed: {decision.comments}", occurred_at=datetime.now(timezone.utc))
            )
            return state, None, source_payloads, last_decision

        if decision.decision == ReviewDecisionType.REVISE_INSIGHTS:
            state = _apply(apply_synthesis_revision(state, decision, occurred_at=datetime.now(timezone.utc)))
            if state.current_stage == WorkflowStage.FAILED:
                return state, None, source_payloads, last_decision
            reviewer_comments = decision.comments
            affected_insight_ids = decision.affected_insight_ids
            previous_package = package
            continue

        # decision.decision == ReviewDecisionType.REVISE_RESEARCH
        state = _apply(apply_research_revision(state, decision, occurred_at=datetime.now(timezone.utc)))
        if state.current_stage == WorkflowStage.FAILED:
            return state, None, source_payloads, last_decision

        state = _apply(
            state.with_stage(
                WorkflowStage.RESEARCHING,
                message="re-running research per review",
                occurred_at=datetime.now(timezone.utc),
            )
        )
        manifest, source_payloads = await run_research_for_request(
            request_id=request_id,
            request_version=state.request_version,
            company_codes=company_codes,
            required_sources=required_sources,
            prompt_by_company=prompt_by_company,
            original_user_prompt=original_user_prompt,
            preferences=preferences,
            narrow_revision=state.active_research_revision,
            now=datetime.now(timezone.utc),
            data_domain_ids=data_domain_ids,
        )
        state = _apply(_record_source_errors(state, source_payloads, occurred_at=datetime.now(timezone.utc)))
        if not is_manifest_ready(manifest, source_payloads):
            state = _apply(
                state.with_terminal_error(
                    _describe_incomplete_manifest(manifest, source_payloads), occurred_at=datetime.now(timezone.utc)
                )
            )
            return state, None, source_payloads, last_decision

        effective_research_prompt = _build_effective_prompt(original_user_prompt, state.active_research_revision)
        state = _apply(
            state.with_stage(
                WorkflowStage.AWAITING_SYNTHESIS,
                message="revised research complete",
                occurred_at=datetime.now(timezone.utc),
            )
        )
        reviewer_comments = decision.comments
        # A research revision means new/updated source data, not a request to
        # re-justify the old insights against it -- the revision-resolution
        # contract (affected_insight_ids/previous_package) is specific to the
        # revise_insights path.
        affected_insight_ids = None
        previous_package = None

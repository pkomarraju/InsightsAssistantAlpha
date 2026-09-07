"""Deterministic research execution.

Builds a ResearchManifest per (request_id, request_version), dispatches each
required (company, source) pair as a distinct ResearchTask against
agents.orchestrator.run_structured_specialist (bounded concurrency,
sequential by default), joins them with an asyncio.wait timeout barrier, and
turns every specialist's structured findings into a typed SourcePayload.
Nothing in this module lets an LLM's output decide counters, versions,
timeout/terminal status, or which sources run for a company -- those are the
plain-Python rules below and in contracts.workflow.invariants; only the
SourcePayload's own findings/evidence content comes from the LLM call.

Two separate, deliberately independent timeouts govern dispatch:
  - INSIGHTS_SOURCE_EXECUTION_TIMEOUT_SECONDS bounds one specialist's own
    run, starting only once it has acquired the concurrency semaphore (see
    _run_one_task) -- queue wait time is never charged against it.
  - The manifest's overall deadline (manifest.deadline, sized by
    compute_research_workflow_timeout_seconds below) is the whole research
    stage's safety net -- every task, every company/source -- and is what
    actually terminates dispatch_and_join's asyncio.wait barrier.

A specialist that runs past its own execution timeout gets execution_timeout;
a task still queued (never acquired the semaphore) when the overall deadline
fires gets workflow_timeout_before_start; a task that HAD started but was
still running when the overall deadline fires gets
workflow_timeout_during_execution. All three are SourcePayloadStatus.TIMED_OUT
-- the distinction lives only in the human-readable `error` text (see the
three _*_MESSAGE constants), since nothing downstream needs to branch on
which kind of timeout occurred, only on whether the source is usable.

Batch-processing semantics: specialist agents may legitimately run for
several minutes -- the per-specialist execution timeout defaults to one hour
(contracts.workflow.config.DEFAULT_SOURCE_EXECUTION_TIMEOUT_SECONDS) so a
slow-but-working specialist is never confused with a stuck one, and the
overall manifest deadline scales with company_count * enabled_source_count /
concurrency (compute_research_workflow_timeout_seconds below), not a fixed
number. Companies and sources complete independently and in any order;
nothing here (or in contracts.workflow.invariants.ensure_ready_for_synthesis,
which the workflow layer calls before ever invoking the Synthesizer) treats
"still running" as failure, or lets synthesis start until every expected
SourcePayload for the exact request_id/request_version is COMPLETED.

Durable-queue-ready seam: dispatch_and_join is the *entire* in-process
execution mechanism, isolated behind one signature --
`(ResearchManifest, list[ResearchTask]) -> list[SourcePayload]` -- built
from nothing but contracts.workflow.research/enums. A future durable job
queue (submit each ResearchTask as a job keyed by its PayloadKey, poll for
completion up to manifest.deadline, translate terminal job states into
SourcePayloads) can replace this function's body wholesale without touching
SourcePayload, ResearchManifest, ResearchTask, or InsightPackage -- callers
(build_manifest_and_tasks, run_research_for_request, and the workflow layer
above them) only ever see this same typed input/output shape. _payload_for
below is the one place SourcePayload construction happens, so a queue-backed
implementation can reuse it verbatim for its own terminal/timeout/failure
cases instead of re-deriving the same validation rules.
"""

import asyncio
import logging
import math
import os
from datetime import date as date_type
from datetime import datetime, timezone

from openai import RateLimitError
from pydantic import ValidationError

from insights_assistant.agents.external_research_plan import build_external_research_plan
from insights_assistant.agents.orchestrator import SpecialistFindings, run_structured_specialist
from insights_assistant.api import evidence_mapping
from insights_assistant.contracts.api.enums import EvidenceSourceAgent, EvidenceSourceType
from insights_assistant.contracts.api.evidence import EvidenceItem
from insights_assistant.contracts.api.preferences import UserPreferences
from insights_assistant.contracts.workflow.config import (
    INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_OVERHEAD_SECONDS,
    INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_SECONDS,
    INSIGHTS_SOURCE_EXECUTION_TIMEOUT_SECONDS,
    INSIGHTS_SOURCE_JOIN_TIMEOUT_SECONDS,
    is_new_schema_only_selection,
)
from insights_assistant.contracts.workflow.enums import ReviewDecisionType, SourcePayloadStatus
from insights_assistant.contracts.workflow.external_research import ExternalResearchPlan, ProviderStatusReport
from insights_assistant.contracts.workflow.research import PayloadKey, ResearchManifest, ResearchTask, SourcePayload
from insights_assistant.contracts.workflow.review import NarrowResearchRevision, ReviewDecision
from insights_assistant.contracts.workflow.state import WorkflowState
from insights_assistant.mcp_servers.internal_data_server import (
    build_company_research_context,
    resolve_ticker_for_company_code,
)

logger = logging.getLogger(__name__)

# Bounded, configurable concurrency for specialist dispatch -- default 1
# reproduces today's strictly-sequential behavior, the safe default against
# this project's low OpenAI rate limit. Raising it never uses unbounded
# asyncio.gather; it's still one asyncio.Semaphore(N) gate.
RESEARCH_CONCURRENCY = max(int(os.environ.get("INSIGHTS_RESEARCH_CONCURRENCY") or 1), 1)

# Same retry-on-RateLimitError policy previously in api/server.py::_research_company
# (its only caller) -- moved here, not duplicated, since specialist dispatch
# now lives in this module.
RATE_LIMIT_RETRY_ATTEMPTS = int(os.environ.get("INSIGHTS_RATE_LIMIT_RETRY_ATTEMPTS") or 3)
RATE_LIMIT_RETRY_FALLBACK_SECONDS = float(os.environ.get("INSIGHTS_RATE_LIMIT_RETRY_FALLBACK_SECONDS") or 20)

_EXECUTION_TIMEOUT_MESSAGE = "The agent exceeded its execution time limit."
_WORKFLOW_TIMEOUT_BEFORE_START_MESSAGE = "The research workflow ended before this agent could start."
_WORKFLOW_TIMEOUT_DURING_EXECUTION_MESSAGE = (
    "The research workflow's overall time limit was reached while this agent was still running."
)


def compute_research_workflow_timeout_seconds(number_of_tasks: int) -> float:
    """The overall research-stage safety deadline (manifest.deadline): sized
    so sequential execution of every task at the configured concurrency gets
    its full per-specialist execution timeout, never a shrinking share of a
    fixed shared budget -- the bug this module's timeout split fixes was a
    queued specialist consuming its own execution budget while merely
    waiting for an earlier one to finish, because the whole join shared one
    fixed 90s deadline regardless of task count or concurrency.

    Every module-level constant is read as a bare name here (not bound as a
    default parameter value) so it stays live-monkeypatchable in tests,
    matching RESEARCH_CONCURRENCY's existing convention.

    Precedence:
      1. The legacy INSIGHTS_SOURCE_JOIN_TIMEOUT_SECONDS, if set, overrides
         everything else (backward compatibility -- see config.py's
         deprecation warning).
      2. An explicit INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_SECONDS is used as
         given, but validated (a warning, never a raise) against this
         formula's minimum -- number_of_tasks is only known here, per
         request, not in config.py.
      3. Otherwise, the formula's own result:
         ceil(number_of_tasks / concurrency) * execution_timeout + overhead.
    """

    minimum_required = (
        math.ceil(number_of_tasks / RESEARCH_CONCURRENCY) * INSIGHTS_SOURCE_EXECUTION_TIMEOUT_SECONDS
        + INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_OVERHEAD_SECONDS
    )

    if INSIGHTS_SOURCE_JOIN_TIMEOUT_SECONDS is not None:
        return INSIGHTS_SOURCE_JOIN_TIMEOUT_SECONDS

    if INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_SECONDS is not None:
        if INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_SECONDS < minimum_required:
            logger.warning(
                "INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_SECONDS=%.0fs is less than the %.0fs this request's "
                "%d task(s) at concurrency=%d need to each get their full %.0fs execution timeout -- "
                "queued specialists may still be timed out before they can start.",
                INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_SECONDS, minimum_required, number_of_tasks,
                RESEARCH_CONCURRENCY, INSIGHTS_SOURCE_EXECUTION_TIMEOUT_SECONDS,
            )
        return INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_SECONDS

    return minimum_required


async def _run_specialist_with_retry(source_agent: EvidenceSourceAgent, prompt: str) -> SpecialistFindings:
    for attempt in range(RATE_LIMIT_RETRY_ATTEMPTS):
        try:
            return await run_structured_specialist(source_agent, prompt)
        except RateLimitError as exc:
            if attempt == RATE_LIMIT_RETRY_ATTEMPTS - 1:
                raise
            retry_after = None
            response = getattr(exc, "response", None)
            if response is not None:
                raw_retry_after = response.headers.get("retry-after")
                try:
                    retry_after = float(raw_retry_after) if raw_retry_after else None
                except ValueError:
                    retry_after = None
            wait_seconds = max(retry_after or 0, RATE_LIMIT_RETRY_FALLBACK_SECONDS)
            logger.warning(
                "Rate limit for %s; retrying attempt %d/%d after %.1fs",
                source_agent.value, attempt + 2, RATE_LIMIT_RETRY_ATTEMPTS, wait_seconds,
            )
            await asyncio.sleep(wait_seconds)
    raise AssertionError("unreachable")


def _build_evidence(task: ResearchTask, findings: SpecialistFindings) -> list[EvidenceItem]:
    """Converts the specialist's structured findings into EvidenceItems.
    evidence_code is still run through evidence_mapping.classify() -- same
    safety policy as before, dropping anything unclassifiable or reported
    under the wrong source_agent -- but the code, date, label, and detail
    all come from the LLM's own structured report of what it saw in a real
    tool result, not a regex scrape over prose. A malformed date (not real
    ISO YYYY-MM-DD) drops that one item rather than failing the whole task
    or falling back to a placeholder date.

    A second, deterministic gate applies only to source_agent=
    internal_data_agent tasks whose request selected the new schema
    exclusively (contracts.workflow.config.is_new_schema_only_selection):
    any evidence_code carrying a legacy prefix (evidence_mapping.
    LEGACY_INTERNAL_DATA_AGENT_PREFIXES -- REL_/RELM_/PROD_/OPP_/RISK_/
    INT_/NOTE_) is dropped, regardless of what the specialist reported.
    api/server.py's task prompt and agents/orchestrator.py's system prompt
    already instruct the specialist not to call the legacy tools that
    produce these codes for such a request, but a prompt is not a
    guarantee the model won't call one anyway (or that it won't otherwise
    fabricate a legacy-looking code) -- this is the backstop that makes the
    scoping actually hold, the same "never trust the model to police itself
    a second time" principle every other deterministic check in this
    module and agents/synthesizer.py already applies. A legacy/mixed or
    relationship_interactions-only selection (data_domain_ids empty or not
    new-schema-only) is unaffected -- nothing here changes for a request
    against the original schema.
    """

    new_schema_only = task.source_agent == EvidenceSourceAgent.INTERNAL_DATA_AGENT and is_new_schema_only_selection(
        task.data_domain_ids
    )

    items: list[EvidenceItem] = []
    for i, ev in enumerate(findings.evidence):
        classified = evidence_mapping.classify(ev.evidence_code)
        if not classified:
            continue
        source_agent_value, source_type_value = classified
        if source_agent_value != task.source_agent.value:
            continue
        if new_schema_only and ev.evidence_code.startswith(
            tuple(evidence_mapping.LEGACY_INTERNAL_DATA_AGENT_PREFIXES)
        ):
            logger.warning(
                "Dropping legacy-schema evidence %s for %s/%s: request selected the new internal "
                "schema exclusively (%r)",
                ev.evidence_code, task.company_code, task.source_agent.value, task.data_domain_ids,
            )
            continue
        label = ev.label or evidence_mapping.label_for(ev.evidence_code)
        semantics = evidence_mapping.classify_evidence_semantics(ev.evidence_code, label, ev.detail)
        try:
            item = EvidenceItem(
                id=f"EV_{task.request_id}_{task.request_version}_{task.company_code}_{task.source_agent.value}_{i}",
                source_agent=task.source_agent,
                source_type=EvidenceSourceType(source_type_value),
                evidence_code=ev.evidence_code,
                label=label,
                detail=ev.detail,
                date=date_type.fromisoformat(ev.date),
                risk_types=list(semantics.risk_types),
                supported_claims=list(semantics.supported_claims),
                metric_type=semantics.metric_type,
            )
        except (ValidationError, ValueError):
            logger.warning(
                "Dropping evidence %s for %s/%s: unparseable date %r",
                ev.evidence_code, task.company_code, task.source_agent.value, ev.date,
            )
            continue
        items.append(item)
    return items


def _payload_for(
    task: ResearchTask,
    *,
    status: SourcePayloadStatus,
    started_at: datetime,
    completed_at: datetime,
    error: str | None = None,
    evidence: list[EvidenceItem] | None = None,
    findings: str = "",
    provider_statuses: list[ProviderStatusReport] | None = None,
) -> SourcePayload:
    """The single place a ResearchTask's outcome becomes a SourcePayload,
    regardless of which of the five terminal cases produced it (completed,
    execution_timeout, workflow_timeout_before_start,
    workflow_timeout_during_execution, or an unhandled exception). Kept as
    one pure function -- no asyncio, no I/O -- so a future durable-queue
    execution mechanism can reuse it exactly (see module docstring)."""

    return SourcePayload(
        request_id=task.request_id,
        request_version=task.request_version,
        company_code=task.company_code,
        source_agent=task.source_agent,
        status=status,
        error=error,
        evidence=evidence or [],
        findings=findings,
        provider_statuses=provider_statuses or [],
        started_at=started_at,
        completed_at=completed_at,
    )


async def _run_one_task(
    task: ResearchTask,
    semaphore: asyncio.Semaphore,
    started_at_by_key: dict[tuple[str, EvidenceSourceAgent], datetime],
) -> SourcePayload:
    """Never raises: a source exception, or its own execution timeout,
    becomes a typed SourcePayload, never an exception propagating out of the
    join.

    started_at_by_key is populated the instant this task acquires the
    semaphore -- before the specialist call itself, and before its own
    execution-timeout clock starts -- so a caller that has to cancel this
    task from the OUTSIDE (dispatch_and_join's overall-deadline path) can
    still tell whether it had started running or was still queued, without
    needing this coroutine's return value (which a cancelled task never
    produces).
    """

    async with semaphore:
        started_at = datetime.now(timezone.utc)
        started_at_by_key[task.key.as_tuple()] = started_at
        queued_seconds = (started_at - task.created_at).total_seconds()
        if queued_seconds > 1:
            logger.info(
                "Specialist %s/%s started after queueing for %.1fs",
                task.company_code, task.source_agent.value, queued_seconds,
            )
        try:
            findings = await asyncio.wait_for(
                _run_specialist_with_retry(task.source_agent, task.prompt),
                timeout=INSIGHTS_SOURCE_EXECUTION_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            logger.warning(
                "Source execution timed out: request=%s version=%s company=%s source=%s after %.0fs",
                task.request_id, task.request_version, task.company_code, task.source_agent.value,
                INSIGHTS_SOURCE_EXECUTION_TIMEOUT_SECONDS,
            )
            return _payload_for(
                task,
                status=SourcePayloadStatus.TIMED_OUT,
                error=_EXECUTION_TIMEOUT_MESSAGE,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
            )
        except Exception as exc:  # noqa: BLE001 -- one source's failure must become a typed payload, not propagate
            logger.warning(
                "Source failed: request=%s version=%s company=%s source=%s: %s",
                task.request_id, task.request_version, task.company_code, task.source_agent.value, exc,
            )
            return _payload_for(
                task,
                status=SourcePayloadStatus.FAILED,
                error=f"{type(exc).__name__}: {exc}",
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
            )

    evidence = _build_evidence(task, findings)
    return _payload_for(
        task,
        status=SourcePayloadStatus.COMPLETED,
        evidence=evidence,
        findings=findings.summary,
        provider_statuses=findings.provider_statuses,
        started_at=started_at,
        completed_at=datetime.now(timezone.utc),
    )


async def dispatch_and_join(manifest: ResearchManifest, tasks: list[ResearchTask]) -> list[SourcePayload]:
    """The deterministic join/barrier, outside the LLM: runs every task
    (bounded concurrency, sequential by default -- never unbounded
    asyncio.gather), waits up to manifest.deadline via asyncio.wait, and
    returns exactly one SourcePayload per task -- completed, failed, or
    timed_out (in one of its three distinct flavors -- see module docstring)
    for whatever is still pending at the deadline. Never raises on a normal
    timeout; callers decide what a non-ready result set means via
    contracts.workflow.invariants.ensure_ready_for_synthesis.

    If THIS coroutine itself is cancelled from outside (e.g. a user stops
    the request from api/server.py's cancel endpoint while research is
    still in flight), every still-running specialist task is cancelled and
    awaited here before the CancelledError propagates -- the same
    no-orphaned-background-work guarantee the ordinary timeout path below
    already provides, just triggered by external cancellation instead of
    the deadline.
    """

    semaphore = asyncio.Semaphore(RESEARCH_CONCURRENCY)
    started_at_by_key: dict[tuple[str, EvidenceSourceAgent], datetime] = {}
    aio_task_by_research_task: dict[asyncio.Task, ResearchTask] = {
        asyncio.create_task(_run_one_task(task, semaphore, started_at_by_key)): task for task in tasks
    }

    try:
        remaining_seconds = max((manifest.deadline - datetime.now(timezone.utc)).total_seconds(), 0)
        _done, pending = await asyncio.wait(aio_task_by_research_task.keys(), timeout=remaining_seconds)
    except asyncio.CancelledError:
        for aio_task in aio_task_by_research_task:
            aio_task.cancel()
        await asyncio.gather(*aio_task_by_research_task.keys(), return_exceptions=True)
        raise

    payloads: list[SourcePayload] = []
    cancelled: list[asyncio.Task] = []
    for aio_task, research_task in aio_task_by_research_task.items():
        if aio_task in pending:
            aio_task.cancel()
            cancelled.append(aio_task)
            key = research_task.key.as_tuple()
            had_started = key in started_at_by_key
            payloads.append(
                _payload_for(
                    research_task,
                    status=SourcePayloadStatus.TIMED_OUT,
                    error=(
                        _WORKFLOW_TIMEOUT_DURING_EXECUTION_MESSAGE
                        if had_started
                        else _WORKFLOW_TIMEOUT_BEFORE_START_MESSAGE
                    ),
                    # Never started -- created_at is the best available timestamp for it.
                    started_at=started_at_by_key.get(key, research_task.created_at),
                    completed_at=datetime.now(timezone.utc),
                )
            )
            continue
        try:
            payloads.append(aio_task.result())
        except Exception as exc:  # noqa: BLE001 -- defense in depth; _run_one_task already catches internally
            payloads.append(
                _payload_for(
                    research_task,
                    status=SourcePayloadStatus.FAILED,
                    error=f"{type(exc).__name__}: {exc}",
                    started_at=research_task.created_at,
                    completed_at=datetime.now(timezone.utc),
                )
            )

    if cancelled:
        # Requirement: no background model/tool call is left detached from
        # the event loop after this function returns -- .cancel() only
        # schedules a CancelledError at the task's next await point; without
        # awaiting it here, the task (and whatever HTTP/MCP call it's mid-
        # flight on) keeps running in the background on its own schedule.
        await asyncio.gather(*cancelled, return_exceptions=True)

    return payloads


async def _build_external_research_plan_for_company(
    company_code: str, *, as_of_date: date_type, internal_research_enabled: bool
) -> ExternalResearchPlan:
    """Builds one company's ExternalResearchPlan without ever handing
    external_data_agent Supabase credentials or a live DB connection --
    this runs in-process (research_execution.py, not external_data_agent
    itself), and only the resulting plan's rendered text
    (ExternalResearchPlan.render_for_prompt) ever reaches that specialist's
    task prompt (see build_manifest_and_tasks below).

    Falls back to the bounded generic plan (build_external_research_plan's
    own context=None branch) whenever internal research is disabled for
    this request, ticker resolution fails, or fetching the internal context
    itself fails for any reason (including the new target_companies/
    bank_credit_exposures/crm_deal_pipeline/internal_risk_flags schema --
    sql/new_internal_data_tables.sql -- not existing yet in a given
    environment) -- external research must still work either way, per the
    requirement this exists to satisfy, not raise and fail the whole task.
    """

    if not internal_research_enabled:
        return build_external_research_plan(None, ticker=company_code, as_of_date=as_of_date)

    try:
        ticker = await asyncio.to_thread(resolve_ticker_for_company_code, company_code)
        context = await asyncio.to_thread(
            build_company_research_context, ticker or company_code, as_of_date.isoformat()
        )
    except Exception as exc:  # noqa: BLE001 -- any failure here degrades to the generic plan, never raises
        logger.info(
            "No internal research context for company_code=%s (%s: %s); using the generic external plan",
            company_code, type(exc).__name__, exc,
        )
        return build_external_research_plan(None, ticker=company_code, as_of_date=as_of_date)

    return build_external_research_plan(context, ticker=context.ticker, as_of_date=as_of_date)


async def _build_external_research_plans(
    company_codes: list[str], *, as_of_date: date_type, internal_research_enabled: bool
) -> dict[str, ExternalResearchPlan]:
    plans = await asyncio.gather(
        *(
            _build_external_research_plan_for_company(
                code, as_of_date=as_of_date, internal_research_enabled=internal_research_enabled
            )
            for code in company_codes
        )
    )
    return dict(zip(company_codes, plans))


def build_manifest_and_tasks(
    *,
    request_id: str,
    request_version: int,
    company_codes: list[str],
    required_sources: set[EvidenceSourceAgent],
    prompt_by_company: dict[str, str],
    original_user_prompt: str,
    preferences: UserPreferences,
    now: datetime,
    narrow_revision: NarrowResearchRevision | None = None,
    external_plans_by_company: dict[str, ExternalResearchPlan] | None = None,
    data_domain_ids: list[str] | None = None,
) -> tuple[ResearchManifest, list[ResearchTask]]:
    """Every required (company, source) pair becomes one ResearchTask. If
    narrow_revision is given, only tasks whose (company_code, source_agent)
    it names get the reviewer's guidance appended -- every other task reuses
    its original prompt, just re-run fresh under the new request_version
    (never reusing an old version's payload).

    external_plans_by_company (built by run_research_for_request via
    _build_external_research_plans, when EXTERNAL_DATA_AGENT is required)
    has its one entry per company rendered into that company's
    EXTERNAL_DATA_AGENT task prompt specifically -- every other task's
    prompt is unaffected. This is the only path by which anything
    internal-derived ever reaches external_data_agent, and it's already
    bounded, structured prose (ExternalResearchPlan.render_for_prompt),
    never a raw internal record.

    data_domain_ids (the request's selected internal data domains, from
    CreateRequestInput) is carried onto every ResearchTask verbatim -- only
    _build_evidence actually reads it, and only for source_agent=
    internal_data_agent, to decide whether to apply the new-schema-only
    legacy-evidence filter (contracts.workflow.config.
    is_new_schema_only_selection). Omitted (None) by any caller that hasn't
    been updated to pass it, which is equivalent to an empty selection --
    no filtering applies, matching this function's pre-existing behavior.
    """

    expected_keys = [
        PayloadKey(company_code=code, source_agent=source)
        for code in company_codes
        for source in required_sources
    ]
    manifest = ResearchManifest.open(
        request_id=request_id,
        request_version=request_version,
        expected_payload_keys=expected_keys,
        now=now,
        timeout_seconds=compute_research_workflow_timeout_seconds(len(expected_keys)),
    )

    narrowed_keys: set[tuple[str, EvidenceSourceAgent]] = set()
    if narrow_revision is not None:
        narrowed_keys = {
            (code, source) for code in narrow_revision.company_codes for source in narrow_revision.source_agents
        }

    tasks: list[ResearchTask] = []
    for code in company_codes:
        for source in required_sources:
            prompt = prompt_by_company[code]
            if source == EvidenceSourceAgent.EXTERNAL_DATA_AGENT and external_plans_by_company:
                plan = external_plans_by_company.get(code)
                if plan is not None:
                    prompt = f"{prompt}\n\n{plan.render_for_prompt()}"
            if (code, source) in narrowed_keys:
                prompt = f"{prompt}\n\nAdditional guidance from review: {narrow_revision.guidance}"
            tasks.append(
                ResearchTask(
                    request_id=request_id,
                    request_version=request_version,
                    company_code=code,
                    source_agent=source,
                    prompt=prompt,
                    original_user_prompt=original_user_prompt,
                    preferences=preferences,
                    created_at=now,
                    data_domain_ids=data_domain_ids or [],
                )
            )
    return manifest, tasks


async def run_research_for_request(
    *,
    request_id: str,
    request_version: int,
    company_codes: list[str],
    required_sources: set[EvidenceSourceAgent],
    prompt_by_company: dict[str, str],
    original_user_prompt: str,
    preferences: UserPreferences,
    narrow_revision: NarrowResearchRevision | None = None,
    now: datetime | None = None,
    data_domain_ids: list[str] | None = None,
) -> tuple[ResearchManifest, list[SourcePayload]]:
    """Build a fresh ResearchManifest for this exact request_id/request_version
    and dispatch+join every required (company, source) task. Every returned
    payload carries this request_version; callers must never combine these
    with a different version's payloads (see
    contracts.workflow.invariants.validate_single_request_version).

    Called identically for a request's first run and for a research revision
    -- a revision is just this function called again with request_version + 1
    and narrow_revision set, per apply_research_revision below.

    data_domain_ids is passed straight through to build_manifest_and_tasks
    -- see that function's docstring.
    """

    now = now or datetime.now(timezone.utc)

    external_plans_by_company: dict[str, ExternalResearchPlan] | None = None
    if EvidenceSourceAgent.EXTERNAL_DATA_AGENT in required_sources:
        external_plans_by_company = await _build_external_research_plans(
            company_codes,
            as_of_date=now.date(),
            internal_research_enabled=EvidenceSourceAgent.INTERNAL_DATA_AGENT in required_sources,
        )

    manifest, tasks = build_manifest_and_tasks(
        request_id=request_id,
        request_version=request_version,
        company_codes=company_codes,
        required_sources=required_sources,
        prompt_by_company=prompt_by_company,
        external_plans_by_company=external_plans_by_company,
        original_user_prompt=original_user_prompt,
        preferences=preferences,
        now=now,
        narrow_revision=narrow_revision,
        data_domain_ids=data_domain_ids,
    )
    payloads = await dispatch_and_join(manifest, tasks)
    return manifest, payloads


def apply_research_revision(
    state: WorkflowState, decision: ReviewDecision, *, occurred_at: datetime
) -> WorkflowState:
    """Orchestrator-side handling of a Reviewer's revise_research decision.

    Accepts only when research_revision_count is 0. A second revise_research
    is rejected: the workflow transitions to failed with a bounded-retry
    reason instead of raising WorkflowInvariantError past the caller --
    "reject a second research revision and fail with a bounded-retry reason"
    is a workflow-state transition, not an exception to handle upstream.
    """

    if decision.decision != ReviewDecisionType.REVISE_RESEARCH:
        raise ValueError(
            f"apply_research_revision requires decision=revise_research, got {decision.decision.value!r}"
        )

    if state.research_revision_count >= 1:
        return state.with_terminal_error(
            "research revision rejected: bounded-retry policy allows at most one research revision "
            "per request, and it has already been used",
            occurred_at=occurred_at,
        )

    return state.with_research_revision(
        occurred_at=occurred_at,
        narrow_revision=decision.narrow_research_revision,
        message=f"research revision accepted: {decision.comments}",
    )

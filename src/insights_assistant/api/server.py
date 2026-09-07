"""Minimal dev server wiring the frontend to real backends: the live agent
orchestrator (agents/orchestrator.py) for assistant chat, agents/insight_workflow.py
(research -> synthesize -> review, with bounded revision loops) for requests,
and Supabase for companies. Preferences are computed/derived in-memory on
this process since there's no auth/multi-user model yet.

This is intentionally a thin, single-process bridge for a click-through
prototype, not the full contract in docs/api/openapi.yaml: no persistence
(everything resets on restart), no auth, no optimistic-concurrency
`version`/`expectedVersion`, no client-generated idempotency keys. See
docs/api/MIGRATION_PLAN.md's Phase 6 ("Cutover") for what real production
hardening still requires.

Run: uv run uvicorn insights_assistant.api.server:app --reload --port 8000
"""

import asyncio
import logging
import os
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal

# Must run before any insights_assistant.* import: several modules
# (llm.py, contracts/workflow/config.py, agents/research_execution.py) read
# INSIGHTS_*/OPENAI_* env vars into module-level constants at import time,
# not lazily. Loading .env after those imports (as this used to do) means
# every INSIGHTS_* override in .env is silently ignored for the process's
# entire lifetime -- the module already captured os.environ's pre-dotenv
# state. This must stay the first non-stdlib statement in this file.
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client

from insights_assistant.agents.insight_workflow import run_insight_workflow
from insights_assistant.agents.orchestrator import run as run_orchestrator
from insights_assistant.agents.package_store import INSIGHTS_PACKAGES_DIR, save_package_snapshot
from insights_assistant.api import evidence_mapping
from insights_assistant.contracts.api.enums import DisplayDensity, EvidenceSourceAgent, InsightCategory, RankingCriterion
from insights_assistant.contracts.api.preferences import UserPreferences
from insights_assistant.contracts.api.requests import InsightRequirementsSelection
from insights_assistant.contracts.api.requests import RequestInsightCategory as InsightRequirementsCategory
from insights_assistant.contracts.workflow.config import (
    RELATIONSHIP_INTERACTIONS_DOMAIN_ID,
    STRUCTURED_DATA_DOMAIN_IDS,
    is_new_schema_only_selection,
)
from insights_assistant.contracts.workflow.enums import SourcePayloadStatus, WorkflowStage
from insights_assistant.contracts.workflow.packages import InsightPackage, RankedInsight, UnmetRequirement
from insights_assistant.contracts.workflow.research import SourcePayload
from insights_assistant.contracts.workflow.state import AuditEvent, SourceErrorRecord, WorkflowState

logging.basicConfig(level=logging.INFO)
logging.getLogger("insights_assistant").setLevel(logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # _load_persisted_state is defined later in this module (it needs
    # ResearchRequest/InsightDto/STORE/INSIGHTS_STORE, all defined further
    # down) -- looked up by name here, at call time, once the app actually
    # starts, long after the whole module has finished importing, so the
    # definition order doesn't matter.
    _load_persisted_state()
    yield


app = FastAPI(title="Insights Assistant API (dev)", lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _supabase():
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


DOMAIN_LABELS = {
    "client_profitability": "Client profitability",
    "credit_exposure": "Credit exposure",
    "deposits_treasury_payments": "Deposits, treasury & payments",
    "capital_markets_advisory": "Capital markets & advisory",
    "product_whitespace": "Product whitespace",
    "relationship_interactions": "Relationship interactions",
}

CATEGORY_LABELS = {
    # Legacy -- no longer offered by the wizard's category selector (see
    # frontend/src/features/requests/wizard/wizardState.ts's CATEGORY_OPTIONS),
    # kept so an existing stored insight/request using one still displays a
    # real label instead of falling back to its raw id.
    "revenue_cross_sell": "Revenue & cross-sell",
    "credit_risk": "Credit risk",
    "capital_markets_advisory": "Capital markets advisory",
    "treasury_payments_liquidity": "Treasury, payments & liquidity",
    "relationship_risk": "Relationship risk",
    # Current -- selectable in the wizard.
    "financing_liquidity": "Financing & liquidity",
    "deal_fee_opportunity": "Deal & fee opportunities",
    "financial_performance": "Financial performance",
    "risk_coverage_attention": "Risk & coverage attention",
}

# currentStage: a coarser, frontend-facing vocabulary than the internal
# WorkflowStage enum (contracts/workflow/enums.py). Two internal stages fold
# into one displayed value because they aren't independently observable with
# today's synchronous-await pipeline: AWAITING_SYNTHESIS is the instant
# research finishes and synthesis is about to start, and AWAITING_REVIEW is
# the same instant between synthesis finishing and review starting -- both
# are momentary handoffs, not stages a poller could ever catch mid-flight, so
# they're folded into the more meaningful neighboring stage rather than
# invented as their own displayed value. `queued` has no WorkflowStage
# counterpart at all -- it's set directly by create_request, before
# run_insight_workflow (and therefore any WorkflowState) exists.
_STAGE_DISPLAY_MAP: dict[WorkflowStage, str] = {
    WorkflowStage.RESEARCHING: "researching",
    WorkflowStage.AWAITING_SYNTHESIS: "waiting_for_sources",
    WorkflowStage.SYNTHESIZING: "synthesizing",
    WorkflowStage.AWAITING_REVIEW: "reviewing",
    WorkflowStage.REVIEWING: "reviewing",
    WorkflowStage.REVISING_RESEARCH: "revising_research",
    WorkflowStage.REVISING_SYNTHESIS: "revising_synthesis",
    WorkflowStage.COMPLETED: "completed",
    WorkflowStage.FAILED: "failed",
}

# Indicative, not measured: there's no incremental progress callback inside
# a single specialist/synthesis/review call, so this is "how far through the
# coarse pipeline are we", not "% of work done". Monotonic within one run
# except across a revision loop, where it can legitimately step backward
# (e.g. reviewing -> revising_research) -- that's accurate, not a bug.
_PROGRESS_BY_DISPLAY_STAGE: dict[str, int] = {
    "queued": 0,
    "researching": 15,
    "waiting_for_sources": 35,
    "synthesizing": 55,
    "reviewing": 70,
    "revising_synthesis": 80,
    "revising_research": 45,
    "completed": 100,
    "failed": 100,
}

_RUNNING_DISPLAY_STAGES = {
    "researching", "waiting_for_sources", "synthesizing", "reviewing", "revising_synthesis", "revising_research",
}


def _display_stage_for(stage: WorkflowStage) -> str:
    return _STAGE_DISPLAY_MAP[stage]


def _status_for_display_stage(display_stage: str) -> str:
    """Maps the detailed currentStage back onto the small, already-polled
    status field (draft|queued|running|completed|failed) so existing
    frontend polling logic keeps working unchanged -- see requirement to
    not force an immediate frontend rewrite."""

    if display_stage == "completed":
        return "completed"
    if display_stage == "failed":
        return "failed"
    if display_stage in _RUNNING_DISPLAY_STAGES:
        return "running"
    return "queued"


# --- Requests ---------------------------------------------------------------


class CompanyDto(BaseModel):
    companyId: str
    companyCode: str
    companyName: str
    ticker: str


class RequestInsightCategory(BaseModel):
    categoryId: str
    minimumCount: int


class CreateRequestInput(BaseModel):
    companyIds: list[str]
    dataDomainIds: list[str]
    generalSearchPrompt: str
    # edgarEnabled/filingTypes are deprecated -- kept for backward
    # compatibility with an existing client. providers (defaulting to all
    # three when omitted and edgarEnabled/enabled is true -- see
    # _effective_providers) is the provider-neutral replacement; filingTypes
    # is accepted but never used by anything (external_data_agent's curated
    # adapters have no concept of a filing type -- see
    # agents/external_adapters.py).
    edgarEnabled: bool
    filingTypes: list[str] = []
    enabled: bool | None = None
    providers: list[str] = []
    lookbackMonths: int
    totalCount: int
    categories: list[RequestInsightCategory]
    rankingCriteria: list[str]


class SourceErrorDto(BaseModel):
    """Matches contracts.api.requests.SourceError's camelCase shape (not
    imported directly: that's an ApiModel with alias generation, and this
    server's DTOs are plain already-camelCase BaseModels -- see module
    docstring). One row per failed or timed_out SourcePayload."""

    id: str
    source: str
    companyId: str | None
    code: str
    message: str
    occurredAt: str
    retryable: bool


class AuditEventDto(BaseModel):
    """One entry of the compact version history: every stage transition and
    every review decision the workflow recorded, in order. detail is only
    ever the structured, designed-to-be-shown fields a step produced (e.g. a
    review decision's own comments/affected ids) -- never hidden model
    reasoning, since nothing upstream of this ever captures that."""

    stage: str
    message: str
    occurredAt: str
    detail: dict | None = None


class UnmetRequirementDto(BaseModel):
    category: str | None
    requestedCount: int
    actualCount: int
    reason: str


class ResearchRequest(BaseModel):
    requestId: str
    requestedBy: str
    status: Literal["draft", "queued", "running", "completed", "failed", "cancelled"]
    # Legacy field: the raw internal WorkflowStage value. Kept unchanged for
    # existing consumers -- currentStage below is the new, coarser,
    # frontend-facing vocabulary (queued/researching/waiting_for_sources/
    # synthesizing/reviewing/revising_synthesis/revising_research/completed/
    # failed) that maps onto `status` the same way `stage` always has.
    stage: str = WorkflowStage.RESEARCHING.value
    currentStage: str = "queued"
    createdAt: str
    updatedAt: str
    companyScope: dict
    externalResearch: dict
    internalResearch: dict
    insightRequirements: dict
    resultInsightIds: list[str]
    progressPct: int
    errorMessage: str | None
    sourceErrors: list[SourceErrorDto] = []
    resultSummary: str | None = None
    requestVersion: int = 1
    packageVersion: int = 1
    researchRevisionCount: int = 0
    synthesisRevisionCount: int = 0
    reviewDecision: str | None = None
    reviewComments: str | None = None
    auditEvents: list[AuditEventDto] = []
    unmetRequirements: list[UnmetRequirementDto] = []


STORE: dict[str, ResearchRequest] = {}
_next_id = 1005
# Keyed by request_id so POST /api/requests/{id}/cancel can find and cancel
# the exact background task for one request -- also keeps a strong
# reference so it isn't garbage-collected mid-flight (asyncio only holds a
# weak reference to a running task otherwise). Entries are removed once the
# task finishes, whatever the outcome.
_TASKS_BY_REQUEST_ID: dict[str, asyncio.Task] = {}

# Rate-limit pacing (retry-on-RateLimitError, concurrency bound) now lives in
# agents/research_execution.py, since specialist dispatch does too --
# INSIGHTS_RATE_LIMIT_RETRY_ATTEMPTS / INSIGHTS_RATE_LIMIT_RETRY_FALLBACK_SECONDS
# / INSIGHTS_RESEARCH_CONCURRENCY. The old per-company COMPANY_REQUEST_DELAY_SECONDS
# knob is retired rather than moved: requests are no longer one call per
# company, they're one call per (company, source), so concurrency there is
# the more direct knob, on top of the always-on process-wide LLM_RATE_LIMITER
# in llm.py that every chat_model() call already goes through regardless.


def _resolve_companies(company_codes: list[str]) -> list[CompanyDto]:
    client = _supabase()
    result = (
        client.table("company_master")
        .select("company_id,company_code,company_name,ticker")
        .in_("company_code", company_codes)
        .execute()
    )
    by_code = {r["company_code"]: r for r in result.data}
    # Preserve the order the banker selected them in, not Supabase's return order.
    # companyId is deliberately the company_code (not the Supabase UUID) so it
    # stays stable and matches the frontend mock's id convention.
    return [
        CompanyDto(
            companyId=by_code[code]["company_code"],
            companyCode=by_code[code]["company_code"],
            companyName=by_code[code]["company_name"],
            ticker=by_code[code]["ticker"] or "",
        )
        for code in company_codes
        if code in by_code
    ]


def _external_research_enabled(payload: CreateRequestInput) -> bool:
    """payload.enabled (provider-neutral) wins when given; otherwise falls
    back to the deprecated payload.edgarEnabled -- see CreateRequestInput's
    own docstring. The single place this mapping happens, so
    _build_company_question/_required_sources_for/create_request's stored
    externalResearch dict can never disagree with each other."""

    return payload.enabled if payload.enabled is not None else payload.edgarEnabled


def _effective_providers(payload: CreateRequestInput) -> list[str]:
    if payload.providers:
        return payload.providers
    return ["fmp", "alpha_vantage", "fred"] if _external_research_enabled(payload) else []


def _build_company_question(company: CompanyDto, payload: CreateRequestInput) -> str:
    """One company's research question -- never mentions any other selected
    company, so the orchestrator's context (and any per-call token cost)
    scales with one company at a time, not the whole request's scope.
    """
    categories = ", ".join(CATEGORY_LABELS.get(c.categoryId, c.categoryId) for c in payload.categories)

    parts = [
        f"For {company.companyName} ({company.ticker}, internal company_code {company.companyCode}): "
        f"{payload.generalSearchPrompt}"
    ]
    parts.append(
        f"When a tool takes a company_codes or company_code filter, pass {company.companyCode!r} verbatim -- "
        "never the ticker or company name, and never a guessed or invented code."
    )
    if categories:
        parts.append(f"Focus the findings on these categories: {categories}.")
    if is_new_schema_only_selection(payload.dataDomainIds):
        # Goal A: a request scoped exclusively to the new schema
        # (target_companies/bank_credit_exposures/crm_deal_pipeline/
        # internal_risk_flags) must never pull evidence from the legacy
        # company_master/relationship_snapshot/opportunities/risk_assessment/
        # internal_notes tables just because internal_data_agent still has
        # those tools loaded -- see agents/orchestrator.py's
        # SPECIALIST_PROMPTS[INTERNAL_DATA_AGENT] for the matching tool-level
        # instruction, and agents/research_execution.py's _build_evidence for
        # the deterministic backstop that drops any legacy-prefixed evidence
        # this instruction fails to prevent.
        parts.append(
            "For internal company data specifically: this request selected only the new internal "
            "schema (Company & Coverage Profile, Credit Exposure & Facilities, CRM Deal Pipeline, "
            "Internal Risk Flags). Call get_company_research_context only, passing the company_code "
            "given above -- never get_relationship_history, get_opportunities, get_risk_assessment, or "
            "search_internal_notes, which read the older, unrelated dataset and must not be used for "
            "this request. If get_company_research_context itself reports an error, state that "
            "plainly as a source/configuration problem for this company; do not substitute a legacy "
            "tool's data for it or imply the internal data was checked and found clean."
        )
    if _external_research_enabled(payload):
        # payload.filingTypes no longer applies to any live tool and is
        # intentionally unused here -- see the wizard's External research
        # step, which still collects it for backward compatibility with the
        # request contract, and CreateRequestInput's own docstring.
        parts.append(
            "Use the most recent available data for each metric: pre-calculated ratios, enterprise "
            "value, and financial statement line items from FMP; company overview, recent price "
            "action, and earnings from Alpha Vantage; and, where a benchmark lending rate or macro "
            "indicator is relevant, the most recent observation from FRED. Do not retrieve redundant "
            "historical periods beyond what's needed to establish a trend. "
            "Return at most 10 external signals, ranked by materiality and relevance to the requested categories."
        )
    parts.append("Cite note IDs, evidence codes, and filing sources for every conclusion.")
    return " ".join(parts)


def _combine_company_answers(
    successes: list[tuple[CompanyDto, str]], failures: list[tuple[CompanyDto, str]]
) -> str:
    """One clearly-labeled combined answer, in selection order, with a
    trailing section listing any companies that failed -- evidence codes and
    citations inside each company's own answer are untouched, so they
    survive this aggregation verbatim.
    """
    sections = [f"## {company.companyName} ({company.ticker})\n\n{answer}" for company, answer in successes]
    if failures:
        noun = "company" if len(failures) == 1 else "companies"
        failure_lines = "\n".join(
            f"- {company.companyName} ({company.ticker}): {message}" for company, message in failures
        )
        sections.append(f"## Research not completed for {len(failures)} {noun}\n\n{failure_lines}")
    return "\n\n".join(sections)


def _required_sources_for(payload: CreateRequestInput) -> set[EvidenceSourceAgent]:
    """Same rule as contracts.workflow.research.required_sources(), applied
    directly to this endpoint's flat CreateRequestInput fields rather than
    routing through ExternalResearchSelection/InternalResearchSelection --
    those carry wizard-only constraints (e.g. a 20-character minimum on
    general_search_prompt) that have nothing to do with source routing and
    shouldn't be able to break it for an otherwise-valid legacy payload.
    required_sources() itself is exercised directly in
    tests/contracts/workflow/test_research.py against the real contracts.
    """

    sources: set[EvidenceSourceAgent] = set()
    if _external_research_enabled(payload):
        sources.add(EvidenceSourceAgent.EXTERNAL_DATA_AGENT)
    domain_ids = set(payload.dataDomainIds)
    if domain_ids & STRUCTURED_DATA_DOMAIN_IDS:
        sources.add(EvidenceSourceAgent.INTERNAL_DATA_AGENT)
    if RELATIONSHIP_INTERACTIONS_DOMAIN_ID in domain_ids:
        sources.add(EvidenceSourceAgent.RELATIONSHIP_NOTES_AGENT)
    return sources


def _preferences_snapshot() -> UserPreferences:
    """Adapts this process's single in-memory PreferencesDto (server.py's
    own flat DTO) into the real UserPreferences contract ResearchTask
    carries -- both describe the same banker, just in the two different
    model layers server.py currently straddles (see module docstring)."""

    return UserPreferences(
        display_name=PREFS_STORE.displayName,
        role=PREFS_STORE.role,
        default_data_domains=PREFS_STORE.defaultDataDomains,
        default_ranking_criteria=[RankingCriterion(c) for c in PREFS_STORE.defaultRankingCriteria],
        email_digest_enabled=PREFS_STORE.emailDigestEnabled,
        at_risk_alerts_enabled=PREFS_STORE.atRiskAlertsEnabled,
        display_density=DisplayDensity(PREFS_STORE.displayDensity),
        default_lookback_months=PREFS_STORE.defaultLookbackMonths,
    )


def _source_errors_from_state(state: WorkflowState) -> list[SourceErrorDto]:
    """One row per failed/timed_out SourcePayload the workflow has recorded
    so far -- sourced from WorkflowState.source_errors (accumulated live by
    agents/insight_workflow.py, including any post-revision re-research), not
    re-derived from a SourcePayload snapshot, so it updates incrementally via
    _sync_request_from_state exactly like every other polled field."""

    return [
        SourceErrorDto(
            id=f"SRCERR_{r.request_id}_{r.request_version}_{i}",
            source=r.source_agent.value,
            companyId=r.company_code,
            code=r.status.value,
            message=r.error,
            occurredAt=r.occurred_at.isoformat().replace("+00:00", "Z"),
            retryable=True,
        )
        for i, r in enumerate(state.source_errors)
    ]


def _audit_event_dto(event: AuditEvent) -> AuditEventDto:
    return AuditEventDto(
        stage=event.stage.value,
        message=event.message,
        occurredAt=event.occurred_at.isoformat().replace("+00:00", "Z"),
        detail=event.detail,
    )


def _unmet_requirement_dto(unmet: UnmetRequirement) -> UnmetRequirementDto:
    return UnmetRequirementDto(
        category=unmet.category.value if unmet.category else None,
        requestedCount=unmet.requested_count,
        actualCount=unmet.actual_count,
        reason=unmet.reason,
    )


def _sync_request_from_state(req: ResearchRequest, state: WorkflowState) -> None:
    """The single place ResearchRequest is updated from a WorkflowState --
    called both mid-flight (as agents.insight_workflow.run_insight_workflow's
    on_state_change callback, so polling GET /api/requests/{id} sees live
    progress) and once more after it returns. Never touches resultInsightIds/
    resultSummary/unmetRequirements: those depend on the InsightPackage,
    which only exists once the Reviewer has passed something, handled
    separately in _run_request.
    """

    display_stage = _display_stage_for(state.current_stage)
    req.stage = state.current_stage.value
    req.currentStage = display_stage
    req.status = _status_for_display_stage(display_stage)
    req.progressPct = _PROGRESS_BY_DISPLAY_STAGE[display_stage]
    req.requestVersion = state.request_version
    req.packageVersion = state.package_version
    req.researchRevisionCount = state.research_revision_count
    req.synthesisRevisionCount = state.synthesis_revision_count
    req.sourceErrors = _source_errors_from_state(state)
    req.auditEvents = [_audit_event_dto(e) for e in state.audit_events]
    if state.terminal_error:
        req.errorMessage = state.terminal_error
    req.updatedAt = _now()
    _persist_request(req)


def _summarize_source_errors(errors: list[SourceErrorDto]) -> str | None:
    if not errors:
        return None
    return "; ".join(f"{e.companyId}/{e.source}: {e.code} - {e.message}" for e in errors)


def _adapt_payloads_to_answers(
    companies: list[CompanyDto], payloads: list[SourcePayload]
) -> tuple[list[tuple[CompanyDto, str]], list[tuple[CompanyDto, str]]]:
    """Reconstitutes the (CompanyDto, str) shape _combine_company_answers
    consumes, from typed SourcePayloads -- used only to build resultSummary
    for display; the actual insights come from the InsightPackage the
    Synthesizer/Reviewer produce, via agents/insight_workflow.py.
    """

    by_company_code: dict[str, list[SourcePayload]] = {}
    for p in payloads:
        by_company_code.setdefault(p.company_code, []).append(p)

    successes: list[tuple[CompanyDto, str]] = []
    failures: list[tuple[CompanyDto, str]] = []
    for company in companies:
        completed = [
            p for p in by_company_code.get(company.companyCode, []) if p.status == SourcePayloadStatus.COMPLETED
        ]
        if not completed:
            failures.append((company, "no completed research payloads"))
            continue
        answer = "\n\n".join(p.findings for p in completed if p.findings)
        successes.append((company, answer))
    return successes, failures


def _build_insight_requirements(payload: CreateRequestInput) -> InsightRequirementsSelection:
    return InsightRequirementsSelection(
        total_count=payload.totalCount,
        categories=[
            InsightRequirementsCategory(category_id=InsightCategory(c.categoryId), minimum_count=c.minimumCount)
            for c in payload.categories
        ],
        ranking_criteria=[RankingCriterion(c) for c in payload.rankingCriteria],
        max_insights_per_company=10,
    )


async def _run_request(request_id: str, companies: list[CompanyDto], payload: CreateRequestInput) -> None:
    req = STORE[request_id]
    req.status = "running"
    req.stage = WorkflowStage.RESEARCHING.value
    req.currentStage = "researching"
    req.progressPct = _PROGRESS_BY_DISPLAY_STAGE["researching"]
    req.updatedAt = _now()

    if not companies:
        req.status = "failed"
        req.stage = WorkflowStage.FAILED.value
        req.currentStage = "failed"
        req.progressPct = 100
        req.errorMessage = "No selected companies could be resolved."
        req.updatedAt = _now()
        _persist_request(req)
        return

    required = _required_sources_for(payload)
    if not required:
        req.status = "failed"
        req.stage = WorkflowStage.FAILED.value
        req.currentStage = "failed"
        req.progressPct = 100
        req.errorMessage = "No research sources are enabled for this request."
        req.updatedAt = _now()
        _persist_request(req)
        return

    prompt_by_company = {company.companyCode: _build_company_question(company, payload) for company in companies}
    companies_by_code = {company.companyCode: company for company in companies}

    # Deterministic research -> synthesize -> review state machine (see
    # agents/insight_workflow.py). No LLM output decides counters, versions,
    # revision eligibility, or the request's terminal status -- only the
    # content of findings/insights/review comments comes from a model.
    # on_state_change mirrors every intermediate WorkflowState into `req`
    # live, so GET /api/requests/{id} reflects real mid-flight progress
    # (e.g. a research revision) instead of only the eventual outcome.
    try:
        state, package, source_payloads, review_decision = await run_insight_workflow(
            request_id=request_id,
            company_codes=[company.companyCode for company in companies],
            required_sources=required,
            prompt_by_company=prompt_by_company,
            original_user_prompt=payload.generalSearchPrompt,
            preferences=_preferences_snapshot(),
            insight_requirements=_build_insight_requirements(payload),
            on_state_change=lambda s: _sync_request_from_state(req, s),
            on_package_ready=save_package_snapshot,
            data_domain_ids=payload.dataDomainIds,
        )
    except asyncio.CancelledError:
        # POST /api/requests/{id}/cancel called task.cancel() on us. Set a
        # clean terminal state here rather than letting CancelledError
        # propagate out of this coroutine -- this IS the task's own body,
        # so catching it (and not re-raising) lets the task finish
        # normally instead of asyncio reporting it as cancelled, which
        # nothing downstream of `req` would ever observe anyway.
        # run_insight_workflow's own awaited calls (dispatch_and_join, the
        # Synthesizer/Reviewer LLM calls) each handle this same
        # cancellation on their own await point, so nothing is left
        # running detached from the event loop after this returns.
        req.status = "cancelled"
        req.stage = WorkflowStage.FAILED.value  # no dedicated WorkflowStage value; status/currentStage carry the real distinction
        req.currentStage = "cancelled"
        req.progressPct = 100
        req.errorMessage = "Cancelled by user."
        req.updatedAt = _now()
        _persist_request(req)
        return

    _sync_request_from_state(req, state)

    successes, failures = _adapt_payloads_to_answers(companies, source_payloads)
    req.resultSummary = _combine_company_answers(successes, failures)
    req.reviewDecision = review_decision.decision.value if review_decision else None
    req.reviewComments = review_decision.comments if review_decision else None
    req.updatedAt = _now()

    if package is None:
        req.status = "failed"
        req.errorMessage = (
            state.terminal_error or _summarize_source_errors(req.sourceErrors) or "Insight workflow did not complete."
        )
        req.updatedAt = _now()
        _persist_request(req)
        return

    req.unmetRequirements = [_unmet_requirement_dto(u) for u in package.unmet_requirements]

    generated_at = _now()
    records = [
        _insight_dto_from_ranked(insight, package, companies_by_code, generated_at) for insight in package.insights
    ]

    for record in records:
        INSIGHTS_STORE[record.id] = record
        _persist_insight(record)
    req.resultInsightIds = [record.id for record in records]

    req.status = "completed"
    req.updatedAt = _now()
    _persist_request(req)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/requests")
def list_requests() -> list[ResearchRequest]:
    return sorted(STORE.values(), key=lambda r: r.createdAt, reverse=True)


@app.get("/api/requests/{request_id}")
def get_request(request_id: str) -> ResearchRequest:
    req = STORE.get(request_id)
    if not req:
        raise HTTPException(status_code=404, detail=f"No request found for id {request_id}")
    return req


_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


@app.post("/api/requests/{request_id}/cancel")
def cancel_request(request_id: str) -> ResearchRequest:
    """Stops an in-flight request's background task. Idempotent-ish: a
    request already in a terminal state returns 409 rather than silently
    no-op'ing, so a caller can tell "already stopped" apart from "actually
    stopped it just now". The task's own CancelledError handler
    (_run_request) also sets this same terminal state -- set here too,
    synchronously, so the caller sees it reflected immediately rather than
    waiting for the cancelled task to actually unwind on the next event-loop
    tick.
    """

    req = STORE.get(request_id)
    if not req:
        raise HTTPException(status_code=404, detail=f"No request found for id {request_id}")
    if req.status in _TERMINAL_STATUSES:
        raise HTTPException(
            status_code=409, detail=f"Request {request_id} already {req.status}; nothing to cancel"
        )

    task = _TASKS_BY_REQUEST_ID.get(request_id)
    if task is not None and not task.done():
        task.cancel()

    req.status = "cancelled"
    req.stage = WorkflowStage.FAILED.value
    req.currentStage = "cancelled"
    req.progressPct = 100
    req.errorMessage = "Cancelled by user."
    req.updatedAt = _now()
    _persist_request(req)
    return req


@app.delete("/api/requests/{request_id}", status_code=204)
def delete_request(request_id: str) -> Response:
    """Permanently removes a request and its generated insights, from both
    the in-memory STORE/INSIGHTS_STORE this process serves reads from and
    Supabase (see _delete_request_sync). An in-flight request is cancelled
    first rather than rejected -- deleting is a stronger action than
    stopping, so it should never be blocked by "still running" the way
    cancel_request's own idempotency check blocks a second stop.
    """

    req = STORE.get(request_id)
    if not req:
        raise HTTPException(status_code=404, detail=f"No request found for id {request_id}")

    # Recorded before anything else: task.cancel() only raises CancelledError
    # at the task's *next* await point, not synchronously, so its own
    # cancellation handler (or an already-in-flight on_state_change
    # callback) can still fire after this function returns -- this guard
    # (checked by _persist_request_sync/_persist_insight_sync) stops any
    # such write from resurrecting the row this function is about to delete.
    _DELETED_REQUEST_IDS.add(request_id)

    task = _TASKS_BY_REQUEST_ID.get(request_id)
    if task is not None and not task.done():
        task.cancel()

    for insight_id in req.resultInsightIds:
        INSIGHTS_STORE.pop(insight_id, None)
    STORE.pop(request_id, None)

    _fire_and_forget(_delete_request_sync, request_id)
    return Response(status_code=204)


@app.post("/api/requests", status_code=201)
async def create_request(payload: CreateRequestInput) -> ResearchRequest:
    global _next_id
    companies = await asyncio.to_thread(_resolve_companies, payload.companyIds)

    request_id = f"REQ_{_next_id}"
    _next_id += 1
    now = _now()
    as_of_date = now[:10]

    req = ResearchRequest(
        requestId=request_id,
        requestedBy="banker-12345",
        status="queued",
        stage="queued",
        currentStage="queued",
        createdAt=now,
        updatedAt=now,
        companyScope={"selectionMode": "explicit", "companies": [c.model_dump() for c in companies]},
        externalResearch={
            # Provider-neutral fields first -- these are what a new/updated
            # frontend reads (see RequestDetailPage.tsx). edgarEnabled/
            # filingTypes are kept alongside only for a client still reading
            # the deprecated shape; never the leading/persisted-as-primary
            # representation for a new request.
            "enabled": _external_research_enabled(payload),
            "providers": _effective_providers(payload),
            "edgarEnabled": payload.edgarEnabled,
            "filingTypes": payload.filingTypes,
            "lookbackMonths": payload.lookbackMonths,
        },
        internalResearch={
            "dataDomains": [
                {"domainId": d, "label": DOMAIN_LABELS.get(d, d), "enabled": True} for d in payload.dataDomainIds
            ],
            "generalSearchPrompt": payload.generalSearchPrompt,
            "asOfDate": as_of_date,
        },
        insightRequirements={
            "totalCount": payload.totalCount,
            "categories": [c.model_dump() for c in payload.categories],
            "rankingCriteria": payload.rankingCriteria,
            "maxInsightsPerCompany": 10,
        },
        resultInsightIds=[],
        progressPct=0,
        errorMessage=None,
    )
    STORE[request_id] = req
    _persist_request(req)

    task = asyncio.create_task(_run_request(request_id, companies, payload))
    _TASKS_BY_REQUEST_ID[request_id] = task
    task.add_done_callback(lambda _t, rid=request_id: _TASKS_BY_REQUEST_ID.pop(rid, None))

    return req


# --- Insights -----------------------------------------------------------------


class BusinessImpactDto(BaseModel):
    exposureUsd: int | None = None
    estimatedImpactUsd: int | None = None
    impactBasis: str | None = None
    description: str


class EvidenceItemDto(BaseModel):
    id: str
    sourceAgent: str
    sourceType: str
    evidenceCode: str
    label: str
    detail: str
    date: str
    riskTypes: list[str] = []
    supportedClaims: list[str] = []
    metricType: str | None = None


class ReviewEventDto(BaseModel):
    id: str
    action: str
    actor: str
    timestamp: str
    reason: str | None = None


class InsightDto(BaseModel):
    id: str
    requestId: str
    companyId: str
    companyCode: str
    companyName: str
    category: str
    subtype: str
    primaryClaim: str
    persona: str
    title: str
    finding: str
    whyItMatters: str
    recommendedAction: str
    priority: str
    confidence: int
    confidenceRationale: str
    businessImpact: BusinessImpactDto
    generatedAt: str
    reviewStatus: str
    reviewHistory: list[ReviewEventDto]
    evidence: list[EvidenceItemDto]


def _insight_dto_from_ranked(
    insight: RankedInsight, package: InsightPackage, companies_by_code: dict[str, CompanyDto], generated_at: str
) -> InsightDto:
    company = companies_by_code.get(insight.company_code)
    company_id = company.companyId if company else insight.company_code
    company_name = company.companyName if company else insight.company_code
    evidence = [
        EvidenceItemDto(
            id=e.id,
            sourceAgent=e.source_agent.value,
            sourceType=e.source_type.value,
            evidenceCode=e.evidence_code,
            label=e.label,
            detail=e.detail,
            date=e.date.isoformat(),
            riskTypes=[r.value for r in e.risk_types],
            supportedClaims=[c.value for c in e.supported_claims],
            metricType=e.metric_type.value if e.metric_type else None,
        )
        for e in insight.evidence
    ]
    return InsightDto(
        id=insight.insight_id,
        requestId=package.request_id,
        companyId=company_id,
        companyCode=insight.company_code,
        companyName=company_name,
        category=insight.category.value,
        subtype=insight.subtype.value,
        primaryClaim=insight.primary_claim.value,
        persona=insight.persona.value,
        title=insight.title,
        finding=insight.finding,
        whyItMatters=insight.why_it_matters,
        recommendedAction=insight.recommended_action,
        priority=insight.priority.value,
        confidence=insight.confidence,
        confidenceRationale=insight.confidence_rationale,
        businessImpact=BusinessImpactDto(
            exposureUsd=insight.business_impact.exposure_usd,
            estimatedImpactUsd=insight.business_impact.estimated_impact_usd,
            impactBasis=insight.business_impact.impact_basis,
            description=insight.business_impact.description,
        ),
        generatedAt=generated_at,
        reviewStatus="pending",
        reviewHistory=[
            ReviewEventDto(
                id=f"{insight.insight_id}_ev0", action="generated", actor="system", timestamp=generated_at
            )
        ],
        evidence=evidence,
    )


class InsightsPageResponse(BaseModel):
    items: list[InsightDto]
    total: int
    page: int
    pageSize: int


class RejectInsightBody(BaseModel):
    reason: str


INSIGHTS_STORE: dict[str, InsightDto] = {}


# --- Supabase persistence for request/insight history (app_requests/app_insights) ---
#
# STORE/INSIGHTS_STORE above remain the source of truth this process actually
# serves reads from -- every request handler reads/writes those dicts
# directly, unchanged. These two tables exist purely so a process restart (or
# a fresh `uv run uvicorn ...`) doesn't lose request/insight history,
# including failed runs: on startup, _load_persisted_state() repopulates
# STORE/INSIGHTS_STORE from Supabase before the app accepts traffic; every
# mutation below is then mirrored to Supabase, best-effort. See
# sql/app_state_tables.sql for why this is a flat jsonb snapshot per row
# rather than docs/api/PROPOSED_SCHEMA.md's normalized design.
#
# Persistence writes are fire-and-forget background tasks, never awaited by
# the request handler that triggered them: Supabase being slow or briefly
# unreachable must never add latency to (or fail) the actual API response,
# and a write failure here must never surface to the caller -- it's logged
# and swallowed, exactly like agents/package_store.py's existing debug
# snapshot. _PERSIST_TASKS holds a strong reference to each in-flight task so
# asyncio doesn't garbage-collect it mid-write (it only holds a weak
# reference to a "fire and forget" task otherwise).
_PERSIST_TASKS: set[asyncio.Task] = set()

# request_ids delete_request has removed. A request's background task can
# still be mid-flight when it's deleted (task.cancel() only raises
# CancelledError at the task's *next* await point, not synchronously) --
# without this guard, that task's own cancellation handler (or any
# already-in-flight on_state_change callback) would race the delete and
# resurrect the just-deleted row in Supabase moments later. Checked by both
# _persist_request_sync and _persist_insight_sync before every write; never
# cleared, since a request_id is never reused (see create_request's
# monotonic _next_id) and this process's memory is cheap to hold onto for
# ids that will never be written again.
_DELETED_REQUEST_IDS: set[str] = set()


def _persist_request_sync(req: ResearchRequest) -> None:
    if req.requestId in _DELETED_REQUEST_IDS:
        return
    try:
        _supabase().table("app_requests").upsert(
            {
                "request_id": req.requestId,
                "requested_by": req.requestedBy,
                "status": req.status,
                "current_stage": req.currentStage,
                "state": req.model_dump(mode="json"),
                "updated_at": _now(),
            }
        ).execute()
    except Exception:
        logger.exception("Failed to persist request snapshot for request_id=%s", req.requestId)


def _fire_and_forget(fn, *args) -> None:
    """Runs fn(*args) in a background thread without blocking the caller,
    when called from a coroutine/async task on the running event loop (the
    common case: create_request, _run_request, and every on_state_change
    callback run there). A handful of call sites are plain sync FastAPI
    endpoints (e.g. cancel_request), which FastAPI runs in a worker thread
    with no event loop of its own -- asyncio.create_task would raise
    RuntimeError there, so this falls back to calling fn synchronously
    (acceptable: those are infrequent, explicit user actions, not the
    high-frequency mid-workflow progress updates)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        fn(*args)
        return
    task = loop.create_task(asyncio.to_thread(fn, *args))
    _PERSIST_TASKS.add(task)
    task.add_done_callback(_PERSIST_TASKS.discard)


def _persist_request(req: ResearchRequest) -> None:
    _fire_and_forget(_persist_request_sync, req)


def _persist_insight_sync(insight: InsightDto) -> None:
    if insight.requestId in _DELETED_REQUEST_IDS:
        return
    try:
        _supabase().table("app_insights").upsert(
            {
                "id": insight.id,
                "request_id": insight.requestId,
                "review_status": insight.reviewStatus,
                "state": insight.model_dump(mode="json"),
                "updated_at": _now(),
            }
        ).execute()
    except Exception:
        logger.exception("Failed to persist insight snapshot for insight_id=%s", insight.id)


def _persist_insight(insight: InsightDto) -> None:
    _fire_and_forget(_persist_insight_sync, insight)


def _delete_row_sync(request_id: str) -> None:
    try:
        _supabase().table("app_requests").delete().eq("request_id", request_id).execute()
    except Exception:
        logger.exception("Failed to delete persisted request request_id=%s", request_id)


def _delete_request_sync(request_id: str) -> None:
    """Deletes the Supabase row (app_insights cascades via its request_id FK)
    and the on-disk debug package snapshot directory (agents/package_store.py)
    for this request. Best-effort like every other persistence call here --
    logged and swallowed, never raised, since STORE/INSIGHTS_STORE have
    already been updated by the caller regardless of whether this succeeds.

    Deletes the row twice, a few seconds apart: deleting a request whose
    background workflow task is still actively persisting mid-flight
    updates (e.g. deleted moments after it was created) has a narrow but
    real race -- a write already past _persist_request_sync's
    _DELETED_REQUEST_IDS check, but not yet landed on the server, can commit
    after this function's first delete runs, resurrecting the row. That
    write is necessarily in flight *now* (nothing new gets dispatched once
    the guard is set), so a second delete after a short grace period, once
    any such straggler has had time to land, closes the window this
    function's own caller (delete_request) already runs in a background
    thread, so the extra delay costs nothing on the request/response path.
    """
    _delete_row_sync(request_id)

    time.sleep(3)
    _delete_row_sync(request_id)

    package_dir = INSIGHTS_PACKAGES_DIR / request_id
    try:
        shutil.rmtree(package_dir, ignore_errors=True)
    except OSError:
        logger.exception("Failed to remove package snapshot directory for request_id=%s", request_id)


def _load_persisted_state() -> None:
    """Repopulates STORE/INSIGHTS_STORE from Supabase before the app accepts
    traffic, so a restart doesn't present as "no requests ever ran". A
    request still `queued`/`running` in a persisted snapshot has no
    background task behind it any more (nothing resumes a workflow across a
    process restart) -- it's relabeled `failed` here rather than left
    showing progress that will never advance and can never be cancelled.
    """
    global _next_id

    try:
        result = _supabase().table("app_requests").select("state").execute()
    except Exception:
        logger.exception("Failed to load persisted requests from Supabase; starting with an empty store")
        result = None

    if result is not None:
        for row in result.data:
            try:
                req = ResearchRequest.model_validate(row["state"])
            except Exception:
                logger.exception("Skipping malformed persisted request row: %r", row.get("state"))
                continue
            if req.status in ("queued", "running"):
                req.status = "failed"
                req.stage = WorkflowStage.FAILED.value
                req.currentStage = "failed"
                req.progressPct = 100
                req.errorMessage = (req.errorMessage + " " if req.errorMessage else "") + (
                    "Interrupted by a server restart before it finished."
                )
                req.updatedAt = _now()
                _persist_request(req)
            STORE[req.requestId] = req

        numeric_suffixes = [
            int(rid.rsplit("_", 1)[1])
            for rid in STORE
            if rid.startswith("REQ_") and rid.rsplit("_", 1)[1].isdigit()
        ]
        if numeric_suffixes:
            _next_id = max(_next_id, max(numeric_suffixes) + 1)

    try:
        insights_result = _supabase().table("app_insights").select("state").execute()
    except Exception:
        logger.exception("Failed to load persisted insights from Supabase; starting with an empty store")
        insights_result = None

    if insights_result is not None:
        for row in insights_result.data:
            try:
                insight = InsightDto.model_validate(row["state"])
            except Exception:
                logger.exception("Skipping malformed persisted insight row: %r", row.get("state"))
                continue
            INSIGHTS_STORE[insight.id] = insight

    logger.info(
        "Loaded %d persisted request(s) and %d persisted insight(s) from Supabase",
        len(STORE), len(INSIGHTS_STORE),
    )


PRIORITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def _insight_matches(
    insight: InsightDto,
    *,
    reviewStatus: str | None,
    category: str | None,
    companyId: str | None,
    persona: str | None,
    priority: str | None,
    confidenceMin: int | None,
    confidenceMax: int | None,
    dateFrom: str | None,
    dateTo: str | None,
    requestId: str | None,
    evidenceSourceType: str | None,
    search: str | None,
) -> bool:
    if reviewStatus and insight.reviewStatus != reviewStatus:
        return False
    if category and insight.category != category:
        return False
    if companyId and insight.companyId != companyId:
        return False
    if persona and insight.persona != persona:
        return False
    if priority and insight.priority != priority:
        return False
    if confidenceMin is not None and insight.confidence < confidenceMin:
        return False
    if confidenceMax is not None and insight.confidence > confidenceMax:
        return False
    if requestId and insight.requestId != requestId:
        return False
    if evidenceSourceType and not any(e.sourceType == evidenceSourceType for e in insight.evidence):
        return False
    if dateFrom or dateTo:
        generated_date = insight.generatedAt[:10]
        if dateFrom and generated_date < dateFrom:
            return False
        if dateTo and generated_date > dateTo:
            return False
    if search:
        needle = search.lower()
        haystack = f"{insight.title} {insight.finding} {insight.companyName}".lower()
        if needle not in haystack:
            return False
    return True


def _business_impact_sort_value(impact: BusinessImpactDto) -> int:
    """Sorts by whichever monetary figure is actually meaningful: an
    estimated impact when one is supported, else the raw exposure, else 0
    -- never conflating the two into one ambiguous "amount"."""
    if impact.estimatedImpactUsd is not None:
        return impact.estimatedImpactUsd
    return impact.exposureUsd or 0


def _sort_insights(items: list[InsightDto], sortField: str | None, sortDirection: str | None) -> list[InsightDto]:
    field = sortField or "generatedAt"
    reverse = (sortDirection or "desc") == "desc"
    if field == "priority":
        key = lambda i: PRIORITY_RANK.get(i.priority, 0)  # noqa: E731
    elif field == "confidence":
        key = lambda i: i.confidence  # noqa: E731
    elif field == "businessImpact":
        key = lambda i: _business_impact_sort_value(i.businessImpact)  # noqa: E731
    else:
        key = lambda i: i.generatedAt  # noqa: E731
    return sorted(items, key=key, reverse=reverse)


def _append_review_event(insight: InsightDto, action: str, reason: str | None = None) -> InsightDto:
    insight.reviewHistory = [
        *insight.reviewHistory,
        ReviewEventDto(
            id=f"{insight.id}_{uuid.uuid4().hex[:8]}",
            action=action,
            actor=PREFS_STORE.displayName,
            timestamp=_now(),
            reason=reason,
        ),
    ]
    _persist_insight(insight)
    return insight


def _get_insight_or_404(insight_id: str) -> InsightDto:
    insight = INSIGHTS_STORE.get(insight_id)
    if not insight:
        raise HTTPException(status_code=404, detail=f"No insight found for id {insight_id}")
    return insight


@app.get("/api/insights")
def list_insights(
    reviewStatus: str | None = None,
    category: str | None = None,
    companyId: str | None = None,
    persona: str | None = None,
    priority: str | None = None,
    confidenceMin: int | None = None,
    confidenceMax: int | None = None,
    dateFrom: str | None = None,
    dateTo: str | None = None,
    requestId: str | None = None,
    evidenceSourceType: str | None = None,
    search: str | None = None,
    sortField: str | None = None,
    sortDirection: str | None = None,
    page: int = 1,
    pageSize: int = 10,
) -> InsightsPageResponse:
    filtered = [
        i
        for i in INSIGHTS_STORE.values()
        if _insight_matches(
            i,
            reviewStatus=reviewStatus,
            category=category,
            companyId=companyId,
            persona=persona,
            priority=priority,
            confidenceMin=confidenceMin,
            confidenceMax=confidenceMax,
            dateFrom=dateFrom,
            dateTo=dateTo,
            requestId=requestId,
            evidenceSourceType=evidenceSourceType,
            search=search,
        )
    ]
    ordered = _sort_insights(filtered, sortField, sortDirection)
    start = (page - 1) * pageSize
    return InsightsPageResponse(
        items=ordered[start : start + pageSize], total=len(ordered), page=page, pageSize=pageSize
    )


@app.get("/api/insights/request-ids")
def list_insight_request_ids() -> list[str]:
    return sorted({i.requestId for i in INSIGHTS_STORE.values()})


@app.get("/api/insights/{insight_id}")
def get_insight(insight_id: str) -> InsightDto:
    return _get_insight_or_404(insight_id)


@app.post("/api/insights/{insight_id}/approve")
def approve_insight(insight_id: str) -> InsightDto:
    insight = _get_insight_or_404(insight_id)
    insight.reviewStatus = "approved"
    return _append_review_event(insight, "approved")


@app.post("/api/insights/{insight_id}/reject")
def reject_insight(insight_id: str, body: RejectInsightBody) -> InsightDto:
    insight = _get_insight_or_404(insight_id)
    insight.reviewStatus = "rejected"
    return _append_review_event(insight, "rejected", reason=body.reason)


@app.post("/api/insights/{insight_id}/reset")
def reset_insight(insight_id: str) -> InsightDto:
    insight = _get_insight_or_404(insight_id)
    insight.reviewStatus = "pending"
    return _append_review_event(insight, "reset")


# --- Preferences ----------------------------------------------------------


class PreferencesDto(BaseModel):
    displayName: str
    role: str
    defaultDataDomains: list[str]
    defaultRankingCriteria: list[str]
    emailDigestEnabled: bool
    atRiskAlertsEnabled: bool
    displayDensity: str
    defaultLookbackMonths: int


class UpdatePreferencesBody(BaseModel):
    displayName: str | None = None
    role: str | None = None
    defaultDataDomains: list[str] | None = None
    defaultRankingCriteria: list[str] | None = None
    emailDigestEnabled: bool | None = None
    atRiskAlertsEnabled: bool | None = None
    displayDensity: str | None = None
    defaultLookbackMonths: int | None = None


# Single in-memory, single-user preferences record -- there's no auth/session
# model yet, so this mirrors frontend/src/api/mock/preferences.ts's one
# hardcoded default rather than modeling multiple users.
PREFS_STORE = PreferencesDto(
    displayName="Alex Bianchi",
    role="Relationship Banker",
    defaultDataDomains=[
        "client_profitability",
        "credit_exposure",
        "deposits_treasury_payments",
        "relationship_interactions",
    ],
    defaultRankingCriteria=["urgency", "commercial_potential", "confidence"],
    emailDigestEnabled=True,
    atRiskAlertsEnabled=True,
    displayDensity="comfortable",
    defaultLookbackMonths=24,
)


@app.get("/api/preferences")
def get_preferences() -> PreferencesDto:
    return PREFS_STORE


@app.patch("/api/preferences")
def update_preferences(patch: UpdatePreferencesBody) -> PreferencesDto:
    global PREFS_STORE
    PREFS_STORE = PREFS_STORE.model_copy(update=patch.model_dump(exclude_unset=True))
    return PREFS_STORE


# --- Companies --------------------------------------------------------------


class CompanyFullDto(BaseModel):
    companyId: str
    companyCode: str
    companyName: str
    ticker: str
    industry: str
    sector: str
    relationshipTier: str
    relationshipStartDate: str
    fortuneRank: int | None


class RelationshipSnapshotDto(BaseModel):
    companyId: str
    relationshipStrength: str
    currentAnnualRevenue: float
    priorYearRevenue: float
    yoyGrowthPct: float
    transactionVolumeYtd: float
    relationshipStatus: str
    relationshipManager: str
    executiveSponsor: str
    asOfDate: str


class ProductDto(BaseModel):
    productId: str
    companyId: str
    productName: str
    annualRevenue: float
    productStatus: str
    growthTrend: str
    renewalDate: str | None


class OpportunityDto(BaseModel):
    opportunityId: str
    companyId: str
    opportunityName: str
    opportunityValue: float
    stage: str
    probabilityPct: float
    expectedCloseDate: str | None
    strategicImportance: str
    status: str
    competitivePressure: str
    competitorName: str | None


class RiskAssessmentDto(BaseModel):
    riskId: str
    companyId: str
    asOfDate: str
    creditExposure: float
    relationshipRiskScore: float
    concentrationRiskScore: float
    operationalRiskScore: float
    riskTrend: str
    explanatoryComment: str


class ClientInteractionDto(BaseModel):
    interactionId: str
    companyId: str
    interactionDate: str
    interactionType: str
    topic: str
    attendees: list[str]
    summary: str
    sentiment: str


class RelationshipMetricMonthlyDto(BaseModel):
    observationMonth: str
    transactionVolume: float
    relationshipRevenue: float
    pipelineValue: float
    riskScore: float
    sentimentLabel: str
    trendLabel: str


class CompanyBriefDto(BaseModel):
    company: CompanyFullDto
    snapshot: RelationshipSnapshotDto
    products: list[ProductDto]
    opportunities: list[OpportunityDto]
    risk: list[RiskAssessmentDto]
    interactions: list[ClientInteractionDto]
    # Relationship-manager notes (RMN_* evidence codes) live in a
    # FAISS-indexed JSON file (data/relationship_manager_notes.json via
    # rag/retriever.py), not a Supabase table -- see docs/api/MAPPING.md.
    # getBrief() has no UI caller today (grep-confirmed), so this endpoint
    # doesn't wire up that second data source for dead code.
    notes: list[dict] = []
    monthlyMetrics: list[RelationshipMetricMonthlyDto]


def _list_companies_sync() -> list[dict]:
    result = (
        _supabase()
        .table("company_master")
        .select("company_id,company_code,company_name,ticker,industry,sector,relationship_tier,relationship_start_date,fortune_rank")
        .order("company_name")
        .execute()
    )
    return result.data


def _list_snapshots_sync() -> list[dict]:
    client = _supabase()
    companies = client.table("company_master").select("company_id,company_code").execute().data
    code_by_uuid = {c["company_id"]: c["company_code"] for c in companies}
    snapshots = (
        client.table("relationship_snapshot")
        .select(
            "company_id,relationship_strength,current_annual_revenue,prior_year_revenue,"
            "yoy_growth_pct,transaction_volume_ytd,relationship_status,relationship_manager,"
            "executive_sponsor,as_of_date"
        )
        .execute()
        .data
    )
    return [{**s, "company_code": code_by_uuid.get(s["company_id"])} for s in snapshots]


def _get_company_brief_sync(company_code: str) -> dict:
    client = _supabase()
    company_rows = (
        client.table("company_master")
        .select(
            "company_id,company_code,company_name,ticker,industry,sector,relationship_tier,"
            "relationship_start_date,fortune_rank"
        )
        .eq("company_code", company_code)
        .execute()
        .data
    )
    if not company_rows:
        raise ValueError(f"No company found for code {company_code}")
    company = company_rows[0]
    company_uuid = company["company_id"]

    snapshot_rows = client.table("relationship_snapshot").select("*").eq("company_id", company_uuid).execute().data
    products = (
        client.table("products")
        .select("product_id,product_name,annual_revenue,product_status,growth_trend,renewal_date")
        .eq("company_id", company_uuid)
        .execute()
        .data
    )
    opportunities = (
        client.table("opportunities")
        .select(
            "opportunity_id,opportunity_name,opportunity_value,stage,probability_pct,"
            "expected_close_date,strategic_importance,status,competitive_pressure,competitor_name"
        )
        .eq("company_id", company_uuid)
        .execute()
        .data
    )
    risk = (
        client.table("risk_assessment")
        .select(
            "risk_id,as_of_date,credit_exposure,relationship_risk_score,"
            "concentration_risk_score,operational_risk_score,risk_trend,explanatory_comment"
        )
        .eq("company_id", company_uuid)
        .order("as_of_date", desc=True)
        .execute()
        .data
    )
    interactions = (
        client.table("client_interactions")
        .select("interaction_id,interaction_date,interaction_type,topic,attendees,summary,sentiment")
        .eq("company_id", company_uuid)
        .order("interaction_date", desc=True)
        .execute()
        .data
    )
    metrics = (
        client.table("relationship_metrics_monthly")
        .select(
            "observation_month,transaction_volume,relationship_revenue,pipeline_value,"
            "risk_score,sentiment_label,trend_label"
        )
        .eq("company_id", company_uuid)
        .order("observation_month", desc=True)
        .execute()
        .data
    )

    return {
        "company": company,
        "snapshot": snapshot_rows[0] if snapshot_rows else None,
        "products": products,
        "opportunities": opportunities,
        "risk": risk,
        "interactions": interactions,
        "metrics": metrics,
    }


@app.get("/api/companies")
async def list_companies_route() -> list[CompanyFullDto]:
    rows = await asyncio.to_thread(_list_companies_sync)
    return [
        CompanyFullDto(
            companyId=r["company_code"],
            companyCode=r["company_code"],
            companyName=r["company_name"],
            ticker=r["ticker"] or "",
            industry=r["industry"],
            sector=r["sector"],
            relationshipTier=r["relationship_tier"],
            relationshipStartDate=str(r["relationship_start_date"]),
            fortuneRank=r["fortune_rank"],
        )
        for r in rows
    ]


@app.get("/api/companies/snapshots")
async def list_snapshots_route() -> list[RelationshipSnapshotDto]:
    rows = await asyncio.to_thread(_list_snapshots_sync)
    return [
        RelationshipSnapshotDto(
            companyId=r["company_code"],
            relationshipStrength=r["relationship_strength"],
            currentAnnualRevenue=float(r["current_annual_revenue"]),
            priorYearRevenue=float(r["prior_year_revenue"]),
            yoyGrowthPct=float(r["yoy_growth_pct"]),
            transactionVolumeYtd=float(r["transaction_volume_ytd"]),
            relationshipStatus=r["relationship_status"],
            relationshipManager=r["relationship_manager"],
            executiveSponsor=r["executive_sponsor"],
            asOfDate=str(r["as_of_date"]),
        )
        for r in rows
        if r["company_code"]
    ]


@app.get("/api/companies/{company_code}/brief")
async def get_company_brief(company_code: str) -> CompanyBriefDto:
    try:
        raw = await asyncio.to_thread(_get_company_brief_sync, company_code)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if raw["snapshot"] is None:
        raise HTTPException(status_code=404, detail=f"No relationship snapshot for {company_code}")

    c = raw["company"]
    s = raw["snapshot"]
    return CompanyBriefDto(
        company=CompanyFullDto(
            companyId=c["company_code"],
            companyCode=c["company_code"],
            companyName=c["company_name"],
            ticker=c["ticker"] or "",
            industry=c["industry"],
            sector=c["sector"],
            relationshipTier=c["relationship_tier"],
            relationshipStartDate=str(c["relationship_start_date"]),
            fortuneRank=c["fortune_rank"],
        ),
        snapshot=RelationshipSnapshotDto(
            companyId=company_code,
            relationshipStrength=s["relationship_strength"],
            currentAnnualRevenue=float(s["current_annual_revenue"]),
            priorYearRevenue=float(s["prior_year_revenue"]),
            yoyGrowthPct=float(s["yoy_growth_pct"]),
            transactionVolumeYtd=float(s["transaction_volume_ytd"]),
            relationshipStatus=s["relationship_status"],
            relationshipManager=s["relationship_manager"],
            executiveSponsor=s["executive_sponsor"],
            asOfDate=str(s["as_of_date"]),
        ),
        products=[
            ProductDto(
                productId=p["product_id"],
                companyId=company_code,
                productName=p["product_name"],
                annualRevenue=float(p["annual_revenue"]),
                productStatus=p["product_status"],
                growthTrend=p["growth_trend"],
                renewalDate=str(p["renewal_date"]) if p["renewal_date"] else None,
            )
            for p in raw["products"]
        ],
        opportunities=[
            OpportunityDto(
                opportunityId=o["opportunity_id"],
                companyId=company_code,
                opportunityName=o["opportunity_name"],
                opportunityValue=float(o["opportunity_value"]),
                stage=o["stage"],
                probabilityPct=float(o["probability_pct"]),
                expectedCloseDate=str(o["expected_close_date"]) if o["expected_close_date"] else None,
                strategicImportance=o["strategic_importance"],
                status=o["status"],
                competitivePressure=o["competitive_pressure"],
                competitorName=o["competitor_name"],
            )
            for o in raw["opportunities"]
        ],
        risk=[
            RiskAssessmentDto(
                riskId=r["risk_id"],
                companyId=company_code,
                asOfDate=str(r["as_of_date"]),
                creditExposure=float(r["credit_exposure"]),
                relationshipRiskScore=float(r["relationship_risk_score"]),
                concentrationRiskScore=float(r["concentration_risk_score"]),
                operationalRiskScore=float(r["operational_risk_score"]),
                riskTrend=r["risk_trend"],
                explanatoryComment=r["explanatory_comment"],
            )
            for r in raw["risk"]
        ],
        interactions=[
            ClientInteractionDto(
                interactionId=i["interaction_id"],
                companyId=company_code,
                interactionDate=str(i["interaction_date"]),
                interactionType=i["interaction_type"],
                topic=i["topic"],
                attendees=i["attendees"] or [],
                summary=i["summary"],
                sentiment=i["sentiment"],
            )
            for i in raw["interactions"]
        ],
        notes=[],
        monthlyMetrics=[
            RelationshipMetricMonthlyDto(
                observationMonth=str(m["observation_month"]),
                transactionVolume=float(m["transaction_volume"]),
                relationshipRevenue=float(m["relationship_revenue"]),
                pipelineValue=float(m["pipeline_value"]),
                riskScore=float(m["risk_score"]),
                sentimentLabel=m["sentiment_label"],
                trendLabel=m["trend_label"],
            )
            for m in raw["metrics"]
        ],
    )


# --- Assistant chat ---------------------------------------------------------


class ChatMessageBody(BaseModel):
    role: str
    content: str


class AssistantChatRequest(BaseModel):
    content: str
    history: list[ChatMessageBody] = []


class AssistantCitationDto(BaseModel):
    sourceAgent: str
    evidenceCode: str
    label: str


class AssistantMessageDto(BaseModel):
    id: str
    role: str
    content: str
    createdAt: str
    citations: list[AssistantCitationDto] = []
    activeAgent: str | None = None


SEED_ASSISTANT_MESSAGE = AssistantMessageDto(
    id="MSG_0",
    role="assistant",
    content=(
        "Hello, I'm the Insights Assistant. Ask me about relationship health, "
        "at-risk flags, or market and financial signals for a client, and I'll "
        "route your question to the right specialist and cite the evidence."
    ),
    createdAt="2026-08-20T13:00:00Z",
    activeAgent="supervisor",
)


@app.get("/api/assistant/history")
def get_assistant_history() -> list[AssistantMessageDto]:
    return [SEED_ASSISTANT_MESSAGE]


@app.post("/api/assistant/chat")
async def assistant_chat(body: AssistantChatRequest) -> AssistantMessageDto:
    history = [{"role": m.role, "content": m.content} for m in body.history]
    answer = await run_orchestrator(body.content, history=history)

    # Regex-based citation extraction, not a second LLM call (see
    # api/evidence_mapping.py) -- keeps chat latency to one orchestrator
    # round trip per turn instead of two.
    citations: list[AssistantCitationDto] = []
    for code in evidence_mapping.extract_codes(answer):
        classified = evidence_mapping.classify(code)
        if not classified:
            continue
        source_agent, _source_type = classified
        citations.append(
            AssistantCitationDto(sourceAgent=source_agent, evidenceCode=code, label=evidence_mapping.label_for(code))
        )

    return AssistantMessageDto(
        id=f"MSG_{uuid.uuid4().hex[:8]}",
        role="assistant",
        content=answer,
        createdAt=_now(),
        citations=citations,
        activeAgent=citations[0].sourceAgent if citations else "supervisor",
    )

"""Module-level configuration for the workflow layer, following the same
convention as llm.py's LLM_MIN_INTERVAL_SECONDS: a plain constant read via
os.environ.get(...), validated at import time. This repo does not use
pydantic-settings anywhere, so process configuration stays consistent with
that rather than introducing a second pattern here.

Two separate timeout concepts (see agents/research_execution.py):
  - INSIGHTS_SOURCE_EXECUTION_TIMEOUT_SECONDS: how long ONE specialist may
    run, starting only once it has acquired the concurrency semaphore.
  - INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_SECONDS: the overall research stage's
    safety deadline (every task, every company/source). When unset, this is
    *calculated* per request from task count, concurrency, and the execution
    timeout (agents.research_execution.compute_research_workflow_timeout_seconds)
    rather than a fixed number -- a fixed number can't be right for every
    request size, and a value too small for sequential execution is exactly
    the bug this split fixes: a queued specialist consuming its own budget
    while merely waiting for an earlier one to finish.

INSIGHTS_SOURCE_JOIN_TIMEOUT_SECONDS is the retired single-timeout knob that
predates this split. If set, it overrides INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_SECONDS
entirely (matching its old behavior -- one shared deadline for the whole
join) and logs a deprecation warning; it no longer has any default value of
its own; prefer the two settings above.

Two revision-related settings (see agents/synthesizer.py, agents/insight_workflow.py):
  - INSIGHTS_MAX_SYNTHESIS_REVISIONS: how many times, across one request's
    lifetime, the Reviewer's revise_insights decision is honored --
    independent of and unrelated to research_revision_count's own fixed
    cap of 1 (contracts.workflow.state.WorkflowState.with_research_revision).
    Enforced in two places, both reading this same value: agents.synthesizer.
    apply_synthesis_revision (turns an exhausted budget into a graceful
    terminal-failure state) and WorkflowState.with_synthesis_revision itself
    (a structural invariant, defense-in-depth against any other caller).
  - INSIGHTS_SYNTHESIS_VALIDATION_RETRY_LIMIT: a *separate*, small internal
    retry count for when a single revise_insights attempt's own synthesis
    call fails contracts.workflow's revision-feedback validation (see
    agents.synthesizer.SynthesisRevisionValidationError) -- a deterministic
    check of whether the regenerated package actually accounted for what
    the Reviewer flagged, not a Reviewer decision. These retries never
    touch synthesis_revision_count or package_version; they exist so LLM
    sampling variance on one synthesis call doesn't burn a reviewer-driven
    revision the Reviewer never actually got to weigh in on again.
"""

import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_SOURCE_EXECUTION_TIMEOUT_SECONDS = 3600.0
DEFAULT_RESEARCH_WORKFLOW_TIMEOUT_OVERHEAD_SECONDS = 30.0
DEFAULT_MAX_SYNTHESIS_REVISIONS = 2
DEFAULT_SYNTHESIS_VALIDATION_RETRY_LIMIT = 2


def _read_positive_float(env_var: str, default: float) -> float:
    raw = os.environ.get(env_var)
    value = float(raw) if raw else default
    if value <= 0:
        raise ValueError(f"{env_var} must be positive, got {value}")
    return value


def _read_positive_int(env_var: str, default: int) -> int:
    """Same convention as _read_positive_float (int() is left to raise its
    own clear ValueError on a non-numeric string, matching float()'s
    behavior above -- not caught/rewrapped, so invalid values fail exactly
    the same way every other INSIGHTS_* setting does)."""

    raw = os.environ.get(env_var)
    value = int(raw) if raw else default
    if value <= 0:
        raise ValueError(f"{env_var} must be positive, got {value}")
    return value


def _read_optional_positive_float(env_var: str) -> float | None:
    """Like _read_positive_float, but None (not a default) when unset --
    for settings whose absence is meaningfully different from any concrete
    value (an explicit override to validate, vs. nothing to validate)."""

    raw = os.environ.get(env_var)
    if not raw:
        return None
    value = float(raw)
    if value <= 0:
        raise ValueError(f"{env_var} must be positive, got {value}")
    return value


INSIGHTS_SOURCE_EXECUTION_TIMEOUT_SECONDS = _read_positive_float(
    "INSIGHTS_SOURCE_EXECUTION_TIMEOUT_SECONDS", DEFAULT_SOURCE_EXECUTION_TIMEOUT_SECONDS
)

INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_OVERHEAD_SECONDS = _read_positive_float(
    "INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_OVERHEAD_SECONDS", DEFAULT_RESEARCH_WORKFLOW_TIMEOUT_OVERHEAD_SECONDS
)

# None unless an operator explicitly opts in to overriding the calculated
# default. Validated against the formula's minimum where it's actually
# computed (agents.research_execution.compute_research_workflow_timeout_seconds,
# which is the only place number_of_tasks -- a per-request value -- is known).
INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_SECONDS = _read_optional_positive_float(
    "INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_SECONDS"
)

_LEGACY_JOIN_TIMEOUT_ENV_VAR = "INSIGHTS_SOURCE_JOIN_TIMEOUT_SECONDS"
INSIGHTS_SOURCE_JOIN_TIMEOUT_SECONDS: float | None = _read_optional_positive_float(_LEGACY_JOIN_TIMEOUT_ENV_VAR)
if INSIGHTS_SOURCE_JOIN_TIMEOUT_SECONDS is not None:
    logger.warning(
        "%s is deprecated and will be removed; treating it as the legacy overall research-workflow "
        "timeout (%.0fs), overriding any calculated or explicit "
        "INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_SECONDS. Prefer INSIGHTS_SOURCE_EXECUTION_TIMEOUT_SECONDS "
        "(per-specialist) and INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_SECONDS (overall) instead.",
        _LEGACY_JOIN_TIMEOUT_ENV_VAR, INSIGHTS_SOURCE_JOIN_TIMEOUT_SECONDS,
    )


INSIGHTS_MAX_SYNTHESIS_REVISIONS = _read_positive_int(
    "INSIGHTS_MAX_SYNTHESIS_REVISIONS", DEFAULT_MAX_SYNTHESIS_REVISIONS
)

INSIGHTS_SYNTHESIS_VALIDATION_RETRY_LIMIT = _read_positive_int(
    "INSIGHTS_SYNTHESIS_VALIDATION_RETRY_LIMIT", DEFAULT_SYNTHESIS_VALIDATION_RETRY_LIMIT
)


# The domainId pattern in contracts/research/research_scope_schema.json is an
# unconstrained string, not a fixed enum -- these are a code-level
# convention. relationship_interactions is the one unstructured (notes-
# based) domain; the rest are structured internal data.
#
# Two generations of domain ids exist. LEGACY_STRUCTURED_DATA_DOMAIN_IDS
# matches docs/api/MAPPING.md's original six-domain mapping and
# api/server.py's DOMAIN_LABELS -- no live UI can submit these any more
# (frontend/src/features/requests/wizard/wizardState.ts's DATA_DOMAIN_OPTIONS
# was replaced with the four ids below), but a pre-existing stored request or
# a direct API caller may still carry one. NEW_SCHEMA_DATA_DOMAIN_IDS matches
# that wizard's own ids, backed by sql/new_internal_data_tables.sql
# (target_companies/bank_credit_exposures/crm_deal_pipeline/
# internal_risk_flags) and served through
# mcp_servers.internal_data_server.get_company_research_context. "credit_
# exposure" is deliberately reused by both generations (the wizard kept the
# id when it renamed the concept to "Credit Exposure & Facilities") -- it
# routes to internal_data_agent under either generation and is excluded from
# is_new_schema_only_selection's legacy/new distinction below since its
# presence alone never disambiguates which generation a request means.
LEGACY_STRUCTURED_DATA_DOMAIN_IDS = frozenset(
    {
        "client_profitability",
        "credit_exposure",
        "deposits_treasury_payments",
        "capital_markets_advisory",
        "product_whitespace",
    }
)
NEW_SCHEMA_DATA_DOMAIN_IDS = frozenset(
    {
        "company_profile",
        "credit_exposure",
        "deal_pipeline",
        "internal_risk_flags",
    }
)
STRUCTURED_DATA_DOMAIN_IDS = LEGACY_STRUCTURED_DATA_DOMAIN_IDS | NEW_SCHEMA_DATA_DOMAIN_IDS
RELATIONSHIP_INTERACTIONS_DOMAIN_ID = "relationship_interactions"

# Ids that only ever meant the legacy six-domain schema -- their presence in
# a request's selection is what actually disambiguates "this request means
# the legacy schema" from "this request means the new one", since
# "credit_exposure" alone is ambiguous between the two (see above).
_LEGACY_ONLY_DATA_DOMAIN_IDS = LEGACY_STRUCTURED_DATA_DOMAIN_IDS - NEW_SCHEMA_DATA_DOMAIN_IDS


def is_new_schema_only_selection(data_domain_ids: list[str] | set[str]) -> bool:
    """True when a request's selected data domains request structured
    internal data (at least one id in STRUCTURED_DATA_DOMAIN_IDS) and name
    no id that only ever meant the legacy six-domain schema. Used to decide
    whether internal_data_agent should be constrained to
    get_company_research_context (the new schema's one tool) instead of the
    legacy per-metric tools (get_relationship_history, get_opportunities,
    get_risk_assessment, search_internal_notes) -- see
    api/server.py::_build_company_question and
    agents/research_execution.py::_build_evidence. A selection naming no
    structured domain at all (e.g. relationship_interactions only) is not
    "new-schema-only": there is nothing structured to scope, so the
    question does not apply and this returns False.
    """

    ids = set(data_domain_ids)
    structured_selected = ids & STRUCTURED_DATA_DOMAIN_IDS
    if not structured_selected:
        return False
    return not (ids & _LEGACY_ONLY_DATA_DOMAIN_IDS)

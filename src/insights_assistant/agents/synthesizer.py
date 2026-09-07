"""Insights Synthesizer: consolidates a request's complete SourcePayload
collection into a typed, ranked InsightPackage.

Never invokes a specialist agent -- it only reasons over evidence already
collected by agents/research_execution.py. Verifies completeness (every
expected payload present and completed) before spending an LLM call, via the
same contracts.workflow.invariants.ensure_ready_for_synthesis the rest of the
workflow is gated by.

Deterministic guardrails sit between the LLM's draft output and the final
InsightPackage, all in Python, none relying on the model to police itself a
second time:
  - evidence-code/company resolution (pre-existing): drop anything whose
    cited codes don't resolve to real evidence, or that spans more than one
    company.
  - mixed-evidence gate: cited evidence containing both a stable/controlled
    signal and an elevated/worsening signal must be accompanied by an
    explicit `limitations` statement, or the insight is dropped -- evidence
    that points in mixed directions may not be silently resolved either way.
  - claim/category alignment (_resolve_claim): every draft declares a
    primary_claim (relationship_risk_worsening, credit_quality_deteriorating,
    competitor_share_loss, revenue_decline, product_or_cross_sell_opportunity,
    or no_material_impact). A draft flagged credit_risk (by category, subtype,
    or primary_claim) is only kept as credit_risk when its cited evidence's
    own classified semantics (api/evidence_mapping.py) actually support
    credit_quality_deteriorating -- a worsening *relationship*-risk score,
    a lost mandate, or a raw credit-exposure balance never qualify on their
    own. When the evidence instead supports one of the other well-defined
    claims, the insight is safely recategorized (not dropped) to the claim's
    correct category/subtype -- this is what turns the REQ_1005 failure into
    a correctly labeled relationship-risk insight rather than either a
    fabricated credit-risk conclusion or a silently lost finding. When
    nothing supports any known claim, the draft is dropped and reported in
    unmet_requirements. This subsumes and replaces the old prefix-only
    credit-risk evidence gate.
  - the contradiction check: an insight claiming elevated risk (via its own
    structured risk_severity_score) is dropped if every piece of cited
    evidence describing risk says stable/improving/controlled and none says
    otherwise -- evidence controls the inference, not the reverse.
  - monetary-field resolution: estimated_impact_usd is kept only alongside a
    real, non-trivial impact_basis, and is never a bare, unexplained copy of
    exposure_usd -- a credit-exposure balance is never reported as business
    impact unless a documented calculation justifies it.
  - deterministic confidence caps, applied after generation regardless of
    what the model proposed: one evidence item caps at 70, multiple items
    from a single source type cap at 80, at least two independent source
    types allow up to 90, and any mixed/contradictory evidence caps at 65
    regardless of breadth.

On a synthesis revision, the regenerated package must explicitly account for
every insight the Reviewer flagged (changed, removed, or retained with a
justification) -- see _validate_revision_resolutions. A package that doesn't
raises SynthesisRevisionValidationError, which agents/insight_workflow.py
turns into a terminal failure rather than spending another Reviewer call on
a package already known not to have addressed the feedback.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Literal, NamedTuple

from pydantic import BaseModel, Field

from insights_assistant.api import evidence_mapping
from insights_assistant.contracts.api.enums import (
    ClaimType,
    InsightCategory,
    InsightPersona,
    InsightPriority,
    InsightSubtype,
    RankingCriterion,
)
from insights_assistant.contracts.api.evidence import BusinessImpact, EvidenceItem
from insights_assistant.contracts.api.preferences import UserPreferences
from insights_assistant.contracts.api.requests import InsightRequirementsSelection
from insights_assistant.contracts.workflow.config import INSIGHTS_MAX_SYNTHESIS_REVISIONS
from insights_assistant.contracts.workflow.enums import ReviewDecisionType
from insights_assistant.contracts.workflow.invariants import ensure_ready_for_synthesis
from insights_assistant.contracts.workflow.packages import InsightPackage, RankedInsight, UnmetRequirement
from insights_assistant.contracts.workflow.research import PayloadKey, ResearchManifest, SourcePayload
from insights_assistant.contracts.workflow.review import ReviewDecision
from insights_assistant.contracts.workflow.state import WorkflowState
from insights_assistant.llm import chat_model

logger = logging.getLogger(__name__)


class SynthesisRevisionValidationError(Exception):
    """Raised when a synthesis revision doesn't satisfy the revision-feedback
    contract: every insight_id the Reviewer flagged must be demonstrably
    removed, changed, or explicitly retained with a supported justification.
    Never raised on a first (non-revision) synthesis call, since there is no
    prior feedback to have addressed."""


SYNTHESIS_SYSTEM_PROMPT = """You are the Insights Synthesizer for a relationship-banking research workflow. \
You combine research findings from external (FMP financial statements/ratios, Alpha Vantage company/price \
data, FRED macro/benchmark rates), internal (structured banking data), and relationship-manager-note \
sources into evidence-backed insights for a banker.

Rules:
1. Only cite evidence_codes from the "Available evidence" list in the user message, copied verbatim. \
Never invent, alter, or guess an evidence code.
2. Every insight must cite at least one real evidence_code from that list. Never emit an insight with \
no evidence.
3. Never manufacture an insight merely to reach a requested count or category minimum. If you cannot \
support the requested number of insights (or a category minimum) with real evidence, report it in \
unmet_requirements with a clear reason instead of inventing a weak insight. A category listed below with \
minimum count 0 is an optional focus area the banker is interested in, not a quota -- never report it in \
unmet_requirements just because no insight was produced for it, and never treat total_count as license to \
manufacture an insight that would not otherwise meet these rules; it is a target, not a requirement.
4. Consolidate corroborating signals from different sources into ONE insight rather than repeating the \
same underlying finding as several near-duplicate insights. When several evidence items describe the \
same underlying situation from different angles (e.g. a risk score, a lost opportunity, a client \
interaction, and a relationship-manager note all describing the same deterioration), cite all of them on \
one insight -- a single insight backed by several independent, corroborating evidence items is stronger \
and more useful than the same items split across several thinner insights. This applies across source \
types just as much as within one: when internal evidence (e.g. a near-term debt maturity, a covenant, a \
high-utilization credit facility) and external evidence (e.g. FMP leverage ratios, a FRED benchmark rate, \
an Alpha Vantage price/earnings trend) describe the same company situation, combine them into one insight \
-- never emit a separate "internal" insight and a separate "external" insight about the same underlying \
fact pattern.
5. finding must state only what the evidence directly supports (the directly observed fact); \
why_it_matters is your interpretation of why that fact matters; recommended_action is what should happen \
next. Keep these three clearly separate -- do not let interpretation leak into finding. limitations \
states any uncertainty, gaps, or mixed signals in the evidence -- leave it empty only when there is \
genuinely no caveat to state.
6. confidence, urgency_score, commercial_potential_score, and risk_severity_score are independent \
0-100 estimates you provide for each insight; a downstream process uses them to rank insights \
deterministically -- do not try to order insights yourself, and do not let one score influence another. \
confidence is capped deterministically after you respond based on how much and how independent your \
cited evidence is (one item caps at 70, several items from a single source type cap at 80, two or more \
independent source types allow up to 90) -- propose confidence honestly; do not inflate it to compensate.
7. If reviewer comments are given, address them directly: they describe specific problems with a \
previous draft of this package that must be fixed, not general feedback to keep in mind.

Declaring the claim -- primary_claim and category/subtype:
8. Every insight must declare exactly one primary_claim, the semantic family of what you are actually \
asserting:
   - relationship_risk_worsening: the client relationship itself (score, status, revenue, sentiment) is \
deteriorating. Supported by relationship-risk trends, lost mandates, declining relationship revenue, \
negative interactions, or relationship-manager notes describing deterioration.
   - credit_quality_deteriorating: the client's own creditworthiness/repayment capacity is deteriorating. \
Requires DIRECT credit-quality evidence: a rating downgrade, covenant pressure or breach, delinquency, a \
rising probability of default, criticized/classified exposure, reduced repayment capacity, liquidity \
stress, or an explicit credit-quality assessment showing deterioration. A worsening relationship-risk \
score, a lost mandate, a competitor gaining ground, or a credit-exposure balance are NOT credit-quality \
evidence on their own -- a downstream check will recategorize or drop a credit_risk insight that cites \
none of the evidence above, regardless of what you conclude.
   - competitor_share_loss: a named or unnamed competitor is winning business, mandates, or share that \
was previously the bank's. Requires competitor activity, lost opportunities, or equivalent direct evidence.
   - revenue_decline: relationship or product revenue is declining. Requires evidence of an actual \
revenue decline, not just exposure or volume figures.
   - product_or_cross_sell_opportunity: an opportunity to grow revenue via a new product, cross-sell, or \
expansion.
   - financing_liquidity_signal: a facility/covenant/maturity/utilization signal or the broader financing \
and liquidity picture around it. Supported by a credit facility's utilization, an upcoming maturity, \
covenant terms (EXP_ evidence), FMP leverage/liquidity/cash-flow metrics, or a FRED benchmark rate. A \
facility being fully drawn, a maturity being near, a large exposure amount, or a rate increase is a fact \
about financing/liquidity, never by itself a claim of borrower credit-quality deterioration -- use \
credit_quality_deteriorating instead only when you also have the direct credit-quality evidence that \
claim requires.
   - deal_fee_opportunity: an active financing, refinancing, M&A, or advisory opportunity. Requires an \
actual CRM pipeline record (DEAL_ evidence) -- external evidence (FMP/Alpha Vantage/FRED) may strengthen \
or qualify the opportunity (e.g. valuation, earnings trend, or the rate environment) but can never invent \
one; without a cited DEAL_ record, do not use this claim.
   - financial_performance_signal: a material change in the client's own earnings, margins, leverage, \
liquidity, valuation, or market/price performance. Requires FMP or Alpha Vantage evidence -- a fact about \
the company's public financial profile, not an interpretation of what it means for the relationship.
   - risk_coverage_attention: the client's internal status or an internal risk flag warrants banker \
follow-up. Supported by company status or an internal risk flag (RISKFLAG_ evidence, or legacy RISK_ \
evidence). This means attention is warranted -- it does NOT by itself mean the relationship or the \
client's credit quality is deteriorating; use relationship_risk_worsening or credit_quality_deteriorating \
instead only when their own required direct evidence is also present.
   - no_material_impact: the evidence is genuinely uneventful; nothing here should be surfaced as an \
insight. Prefer using this (and letting the insight be omitted) over stretching thin evidence into a claim.

The current internal dataset (target_companies/bank_credit_exposures/crm_deal_pipeline/
internal_risk_flags) has no product revenue, payment activity, wallet-share, interaction-history, or \
relationship-trend data at all -- do not produce a revenue_decline, product_or_cross_sell_opportunity \
(outside deal_fee_opportunity's own CRM-pipeline basis), competitor_share_loss, or \
relationship_risk_worsening conclusion unless you are actually citing relationship-manager-note or \
legacy relationship-metric evidence that genuinely supports it.
9. category and subtype must match primary_claim and be consistent with what your cited evidence \
actually supports -- a downstream check validates this and will recategorize or drop insights that don't \
align, so choose carefully rather than relying on the check to fix a mismatch.
10. If the evidence is insufficient, mixed, or points in different directions, say so explicitly in \
limitations (state the uncertainty) rather than resolving the ambiguity by guessing, or omit the insight \
entirely -- a downstream check drops any insight whose cited evidence contains both a stable/controlled \
signal and an elevated/worsening signal with no limitations stated.

Monetary fields -- exposure_usd, estimated_impact_usd, impact_basis:
11. exposure_usd is a raw balance (e.g. credit exposure) your evidence establishes -- it is never itself \
a claim that the amount is at risk of being lost.
12. estimated_impact_usd is your OWN estimate of business impact, and requires impact_basis: a concrete, \
specific explanation of how you derived it from the cited evidence (e.g. "20% of the $X relationship \
revenue this insight documents, based on the stated deceleration"). Never set estimated_impact_usd to a \
bare copy of exposure_usd, revenue, or any other raw figure without deriving it -- a downstream check \
will null out an estimate that has no real basis or that just restates another figure. Leave both \
estimated_impact_usd and impact_basis unset when you cannot support a real estimate; do not report a \
credit-exposure balance as business impact. A DEAL_ record's potential_fee_usd is an opportunity value, \
not exposure; an EXP_ facility's committed or drawn amount is exposure, not an estimate of impact -- never \
relabel one as the other. The one estimate you may compute from a DEAL_ record is a probability-weighted \
fee (potential_fee_usd x probability, both copied from the same cited deal) -- show that exact \
calculation in impact_basis; never invent a recovery rate or any other unsourced percentage for any \
monetary figure.

Interpreting financial metrics -- read this before writing any finding, why_it_matters, or credit_risk \
insight:
13. Directional change alone is not inherently positive or negative. Increased liabilities, debt, \
utilization, deposits, revenue, expenses, or exposure must never be automatically read as increased \
risk, and must never be automatically read as improved performance either -- the direction of a number \
by itself tells you nothing about whether it is good or bad news.
14. Interpret a metric only together with its definition, the period it covers, what it is being \
compared against, any relevant threshold, management's own explanation for it, and whatever other \
evidence corroborates or contradicts that interpretation.
15. When the evidence you cited contradicts an inference you were about to draw, the evidence controls \
-- change the inference, not the evidence. A downstream check will also drop an insight that claims \
elevated risk while its own cited evidence says stable, improving, or controlled and nothing else you \
cited says otherwise.

Requested categories and minimum counts: {categories}
Total insights requested: {total_count}
Maximum insights per company: {max_per_company}
"""


class _InsightDraft(BaseModel):
    company_code: str = Field(
        description="Which company this insight is about, as a hint for your own reasoning -- the real "
        "attribution is derived from evidence_codes, not trusted verbatim from this field."
    )
    category: InsightCategory
    subtype: InsightSubtype
    primary_claim: ClaimType = Field(
        description="The semantic claim this insight makes -- see the system prompt's definitions. "
        "Validated against category/subtype and cited evidence before persistence."
    )
    persona: InsightPersona
    priority: InsightPriority
    title: str
    finding: str = Field(description="Directly observed fact only -- what the cited evidence states.")
    why_it_matters: str = Field(description="Your interpretation of why the finding matters.")
    recommended_action: str
    limitations: str = Field(
        default="", description="Uncertainty, gaps, or mixed signals in the evidence. Empty only when none apply."
    )
    confidence: int = Field(ge=0, le=100)
    confidence_rationale: str
    urgency_score: int = Field(ge=0, le=100)
    commercial_potential_score: int = Field(ge=0, le=100)
    risk_severity_score: int = Field(ge=0, le=100)
    exposure_usd: int | None = Field(
        default=None, ge=0, description="Raw exposure/balance figure the evidence establishes, if any."
    )
    estimated_impact_usd: int | None = Field(
        default=None,
        ge=0,
        description="Your own estimate of business impact -- requires impact_basis. Leave unset if unsupported.",
    )
    impact_basis: str | None = Field(
        default=None, description="How estimated_impact_usd was derived. Required whenever it is set."
    )
    business_impact_description: str = Field(description="Human-readable summary of the monetary picture.")
    evidence_codes: list[str] = Field(
        min_length=1, description="Evidence codes copied verbatim from the Available evidence list."
    )
    revises_insight_id: str | None = Field(
        default=None,
        description="If this insight is the revised replacement for one of the 'Previously affected "
        "insights' listed below, the exact insight_id it replaces, copied verbatim. Null for an insight "
        "not tied to any reviewer comment.",
    )


class _UnmetRequirementDraft(BaseModel):
    category: InsightCategory | None = None
    requested_count: int = Field(ge=0)
    actual_count: int = Field(ge=0)
    reason: str


class _RevisionResolution(BaseModel):
    """Required, per flagged insight_id, whenever this call is a synthesis
    revision -- see _validate_revision_resolutions. Not optional feedback:
    every previously-affected insight_id must get exactly one of these."""

    affected_insight_id: str
    action: Literal["changed", "removed", "retained"]
    justification: str = Field(min_length=1, description="How this specific reviewer comment was addressed.")


class _SynthesisOutput(BaseModel):
    insights: list[_InsightDraft] = Field(default_factory=list)
    unmet_requirements: list[_UnmetRequirementDraft] = Field(default_factory=list)
    revision_resolutions: list[_RevisionResolution] = Field(default_factory=list)


class _ResolvedInsight(NamedTuple):
    """One insight draft with its evidence resolved to real EvidenceItems,
    its company_code deterministically derived from that evidence (never
    trusted verbatim from the LLM's own _InsightDraft.company_code, which can
    drift to the company's name instead of its CLI_xxx code), and its
    category/subtype/primary_claim/confidence/monetary fields resolved by
    the deterministic checks in synthesize_insight_package -- these may
    differ from the draft's own proposed values (see _resolve_claim)."""

    draft: _InsightDraft
    evidence: list[EvidenceItem]
    company_code: str
    category: InsightCategory
    subtype: InsightSubtype
    primary_claim: ClaimType
    confidence: int
    exposure_usd: int | None
    estimated_impact_usd: int | None
    impact_basis: str | None


_SCORE_LOOKUP = {
    RankingCriterion.CONFIDENCE: lambda r: r.confidence,
    RankingCriterion.URGENCY: lambda r: r.draft.urgency_score,
    RankingCriterion.COMMERCIAL_POTENTIAL: lambda r: r.draft.commercial_potential_score,
    RankingCriterion.RISK_SEVERITY: lambda r: r.draft.risk_severity_score,
}


def _rank_drafts(
    resolved: list[_ResolvedInsight], ranking_criteria: list[RankingCriterion]
) -> list[_ResolvedInsight]:
    """Deterministic stable multi-key sort -- the same reverse-order-stable-sort
    pattern rag/retriever.py::_sort_results uses for ranking by several keys
    in priority order. The LLM never assigns a rank directly. Ranking uses
    the deterministically *resolved* confidence (post-cap), not the model's
    raw proposal, so two insights of equal claimed confidence but different
    evidence breadth rank in the order their actual, persisted confidence
    will show."""

    ranked = sorted(resolved, key=lambda r: (r.company_code, r.draft.title))
    criteria = ranking_criteria or [RankingCriterion.CONFIDENCE]
    for criterion in reversed(criteria):
        score_fn = _SCORE_LOOKUP[criterion]
        ranked.sort(key=score_fn, reverse=True)
    return ranked


def _apply_count_caps(
    ranked: list[_ResolvedInsight], insight_requirements: InsightRequirementsSelection
) -> list[_ResolvedInsight]:
    """Deterministic count enforcement, independent of whether the LLM
    actually honored the requested limits: caps each company to
    max_insights_per_company (keeping its highest-ranked insights, since
    `ranked` is already in rank order) and the whole package to total_count.
    """

    if insight_requirements.max_insights_per_company is not None:
        per_company_counts: dict[str, int] = {}
        capped: list[_ResolvedInsight] = []
        for r in ranked:
            count = per_company_counts.get(r.company_code, 0)
            if count >= insight_requirements.max_insights_per_company:
                continue
            per_company_counts[r.company_code] = count + 1
            capped.append(r)
        ranked = capped

    return ranked[: insight_requirements.total_count]


def _is_credit_risk_draft(draft: _InsightDraft) -> bool:
    return draft.category == InsightCategory.CREDIT_RISK or draft.subtype == InsightSubtype.CREDIT_RISK


def _evidence_text_matches(items: list[EvidenceItem], pattern: re.Pattern) -> bool:
    return any(pattern.search(f"{item.label} {item.detail}") for item in items)


# Applied only to the *cited evidence's* own label/detail text (real,
# grounded source data already verified to exist -- see evidence_by_code
# resolution below), never to the insight's own generated finding/
# why_it_matters. That distinction is what keeps this a check on whether the
# evidence was actually read, not "keyword matching over the final prose".
# The patterns themselves, evidence_is_mixed, and compute_confidence_cap
# live in api/evidence_mapping.py so agents/reviewer.py can apply the exact
# same deterministic rules as a defense-in-depth check on an already-
# assembled RankedInsight.
_STABLE_RISK_PATTERN = evidence_mapping._STABLE_RISK_PATTERN
_ELEVATED_RISK_PATTERN = evidence_mapping._ELEVATED_RISK_PATTERN

# A draft is treated as "claiming elevated risk" (for the contradiction
# check) purely via this structured, LLM-provided-but-numeric field -- never
# by scanning the draft's own finding/why_it_matters prose.
_ELEVATED_RISK_SCORE_THRESHOLD = 50


def _claims_elevated_risk(draft: _InsightDraft) -> bool:
    return draft.risk_severity_score >= _ELEVATED_RISK_SCORE_THRESHOLD


def _contradicts_cited_evidence(draft: _InsightDraft, items: list[EvidenceItem]) -> bool:
    """True when the draft claims elevated risk but every risk-relevant
    signal in its own cited evidence says otherwise, with nothing cited
    supporting the elevated claim -- evidence controls the inference."""

    if not _claims_elevated_risk(draft):
        return False
    stable = _evidence_text_matches(items, _STABLE_RISK_PATTERN)
    elevated = _evidence_text_matches(items, _ELEVATED_RISK_PATTERN)
    return stable and not elevated


# --- Claim/category alignment (requirement 3: claim-level grounding) --------

# Which claims have a well-defined, evidence-derivable correct
# category/subtype pairing -- used both to validate a draft's own
# category/subtype and, when a credit_risk-flagged draft's claim isn't
# actually supported, to safely recategorize it instead of only dropping it.
_CLAIM_CATEGORY_SUBTYPE: dict[ClaimType, tuple[InsightCategory, InsightSubtype]] = {
    ClaimType.RELATIONSHIP_RISK_WORSENING: (InsightCategory.RELATIONSHIP_RISK, InsightSubtype.RELATIONSHIP_RISK),
    ClaimType.COMPETITOR_SHARE_LOSS: (InsightCategory.RELATIONSHIP_RISK, InsightSubtype.RELATIONSHIP_RISK),
    ClaimType.REVENUE_DECLINE: (InsightCategory.RELATIONSHIP_RISK, InsightSubtype.RELATIONSHIP_RISK),
    # The four new-schema demo categories: a credit_risk-flagged draft citing
    # e.g. a facility nearing maturity (EXP_) is recategorized here instead
    # of being dropped -- the underlying finding is real and useful, just
    # mislabeled; see this function's own docstring and _resolve_claim's.
    ClaimType.FINANCING_LIQUIDITY_SIGNAL: (InsightCategory.FINANCING_LIQUIDITY, InsightSubtype.FINANCING_LIQUIDITY),
    ClaimType.DEAL_FEE_OPPORTUNITY: (InsightCategory.DEAL_FEE_OPPORTUNITY, InsightSubtype.DEAL_FEE_OPPORTUNITY),
    ClaimType.FINANCIAL_PERFORMANCE_SIGNAL: (InsightCategory.FINANCIAL_PERFORMANCE, InsightSubtype.FINANCIAL_PERFORMANCE),
    ClaimType.RISK_COVERAGE_ATTENTION: (InsightCategory.RISK_COVERAGE_ATTENTION, InsightSubtype.RISK_COVERAGE_ATTENTION),
}

# Checked in this priority order when a credit-risk-flagged draft's claim
# isn't supported -- most specific/credit-adjacent signal first, since
# cited evidence can support more than one claim family at once. The four
# new-schema claims are appended after the legacy three so an insight that
# genuinely is (say) a worsening relationship risk is never recategorized
# into risk_coverage_attention just because it also cites a risk flag.
_ALTERNATIVE_CLAIM_PRIORITY = (
    ClaimType.RELATIONSHIP_RISK_WORSENING,
    ClaimType.COMPETITOR_SHARE_LOSS,
    ClaimType.REVENUE_DECLINE,
    ClaimType.FINANCING_LIQUIDITY_SIGNAL,
    ClaimType.DEAL_FEE_OPPORTUNITY,
    ClaimType.FINANCIAL_PERFORMANCE_SIGNAL,
    ClaimType.RISK_COVERAGE_ATTENTION,
)

# Claims strict enough, and common enough as a mislabeling risk, to enforce
# even outside the credit-risk-flagged path -- product_or_cross_sell_
# opportunity and no_material_impact are deliberately excluded: they're
# lower-stakes framing claims for categories (revenue_cross_sell, capital
# markets, treasury) this fix is not targeted at, and forcing the same
# strict evidence-membership check onto them risks dropping legitimate,
# already-working insights outside this bug's scope. The four new-schema
# claims ARE included: deal_fee_opportunity in particular must never survive
# without an actual cited CRM pipeline record (DEAL_ evidence), and the
# other three each need their own real evidence the same way.
_STRICTLY_VALIDATED_CLAIMS = frozenset(
    {
        ClaimType.RELATIONSHIP_RISK_WORSENING,
        ClaimType.CREDIT_QUALITY_DETERIORATING,
        ClaimType.COMPETITOR_SHARE_LOSS,
        ClaimType.REVENUE_DECLINE,
        ClaimType.FINANCING_LIQUIDITY_SIGNAL,
        ClaimType.DEAL_FEE_OPPORTUNITY,
        ClaimType.FINANCIAL_PERFORMANCE_SIGNAL,
        ClaimType.RISK_COVERAGE_ATTENTION,
    }
)

_NO_CREDIT_RISK_EVIDENCE_REASON = (
    "No credit-risk insight generated: available evidence contains no direct indication of worsening "
    "borrower credit quality (e.g. a rating downgrade, covenant pressure or breach, delinquency, a rising "
    "probability of default, criticized/classified exposure, reduced repayment capacity, liquidity "
    "stress, or an explicit credit-quality assessment showing deterioration)."
)


def _best_supported_alternative_claim(items: list[EvidenceItem]) -> ClaimType | None:
    for claim in _ALTERNATIVE_CLAIM_PRIORITY:
        if any(claim in item.supported_claims for item in items):
            return claim
    return None


def _claim_supported_by_evidence(claim: ClaimType, items: list[EvidenceItem]) -> bool:
    return any(claim in item.supported_claims for item in items)


class _ClaimResolution(NamedTuple):
    kept: bool
    category: InsightCategory
    subtype: InsightSubtype
    primary_claim: ClaimType
    unmet_reason: str | None
    # True only for the credit-risk-flagged path recategorized away from
    # credit_risk -- the caller additionally records that the credit_risk
    # requirement specifically went unmet, even though a (different,
    # correctly-categorized) insight was kept from the same evidence.
    credit_risk_requirement_unmet: bool = False


def _resolve_claim(draft: _InsightDraft, items: list[EvidenceItem]) -> _ClaimResolution:
    """The core anti-conflation gate (requirements 2 and 3). Evidence, not
    the model's stated category/subtype/primary_claim, decides what an
    insight is actually about:

    - primary_claim=no_material_impact is always dropped silently (nothing
      to report -- not a requirement gap).
    - Any draft flagged as credit risk (by category, subtype, or
      primary_claim) is kept as credit_risk only when has_direct_credit_
      quality_evidence is true for its cited evidence. Otherwise, if that
      same evidence supports one of the other well-defined claims
      (relationship_risk_worsening, competitor_share_loss, revenue_decline),
      the insight is safely recategorized to that claim's correct
      category/subtype rather than dropped -- this is the REQ_1005 fix:
      the same finding survives, correctly labeled. If no known claim is
      supported at all, the insight is dropped and reported as an unmet
      credit-risk requirement.
    - A non-credit-risk draft whose primary_claim is one of the other
      strictly-validated claims must cite evidence that actually supports
      that specific claim, or it is dropped and reported.
    """

    if draft.primary_claim == ClaimType.NO_MATERIAL_IMPACT:
        return _ClaimResolution(False, draft.category, draft.subtype, draft.primary_claim, None)

    credit_risk_flagged = _is_credit_risk_draft(draft) or draft.primary_claim == ClaimType.CREDIT_QUALITY_DETERIORATING
    if credit_risk_flagged:
        if draft.primary_claim == ClaimType.CREDIT_QUALITY_DETERIORATING and evidence_mapping.has_direct_credit_quality_evidence(
            items
        ):
            return _ClaimResolution(
                True, InsightCategory.CREDIT_RISK, InsightSubtype.CREDIT_RISK, ClaimType.CREDIT_QUALITY_DETERIORATING, None
            )

        alternative = _best_supported_alternative_claim(items)
        if alternative is not None:
            category, subtype = _CLAIM_CATEGORY_SUBTYPE[alternative]
            return _ClaimResolution(True, category, subtype, alternative, None, credit_risk_requirement_unmet=True)

        return _ClaimResolution(
            False, draft.category, draft.subtype, draft.primary_claim, _NO_CREDIT_RISK_EVIDENCE_REASON
        )

    if draft.primary_claim in _STRICTLY_VALIDATED_CLAIMS and not _claim_supported_by_evidence(
        draft.primary_claim, items
    ):
        return _ClaimResolution(
            False,
            draft.category,
            draft.subtype,
            draft.primary_claim,
            f"No {draft.primary_claim.value} insight generated: cited evidence does not directly support "
            "this claim.",
        )

    return _ClaimResolution(True, draft.category, draft.subtype, draft.primary_claim, None)


# --- Monetary field resolution (requirement 5) -------------------------------


def _resolve_monetary_fields(draft: _InsightDraft) -> tuple[int | None, int | None, str | None]:
    """Deterministic enforcement: estimated_impact_usd survives only with a
    non-empty impact_basis, and is never equal to exposure_usd -- "credit
    exposure: $10.1M" and "business impact: $10.1M" citing the same figure
    is exactly the REQ_1005 pattern ("potential risk to $10.1M when $10.1M
    is merely total exposure"), and no free-text justification can be
    trusted by a deterministic check to actually establish that the full
    exposure is at risk -- Python cannot judge whether a stated calculation
    is sound, so equality itself, not the basis text's length or wording,
    is the bright-line rule. exposure_usd itself always passes through
    unchanged; only what gets called "impact" is gated."""

    exposure = draft.exposure_usd
    impact = draft.estimated_impact_usd
    basis = (draft.impact_basis or "").strip() or None

    if impact is None or not basis:
        return exposure, None, None
    if exposure is not None and impact == exposure:
        return exposure, None, None
    return exposure, impact, basis


def _normalize(text: str) -> str:
    return " ".join(text.split()).strip().lower()


def _content_equal(original: RankedInsight, new: _ResolvedInsight) -> bool:
    """Whether a proposed 'changed' revision is actually materially
    different from the insight it claims to replace. Deliberately strict on
    the fields that carry the actual claim (resolved category/subtype/
    priority/finding/evidence/monetary labeling) -- not on wording alone,
    since the REQ_1005 failure mode was the underlying interpretation not
    changing, not the phrasing. Compares the *resolved* category/subtype
    (post claim-validation), not the draft's raw proposal, since that's what
    actually gets persisted.

    Monetary fields (exposure_usd/estimated_impact_usd/impact_basis) are
    included alongside category/subtype/priority/finding/evidence: a
    revision whose only real fix is relabeling a dollar figure (e.g. a
    relationship-revenue amount the Reviewer correctly flagged as having
    been mislabeled as credit exposure -- the REQ_1008 failure) is a
    genuine, material change even when the finding's prose and the cited
    evidence codes are unchanged, since the finding itself doesn't need to
    change, only which field/label the figure sits under. Without this, that
    kind of legitimate fix would be misreported as a no-op revision and
    rejected by _validate_revision_resolutions."""

    original_codes = {e.evidence_code for e in original.evidence}
    new_codes = {e.evidence_code for e in new.evidence}
    original_basis = _normalize(original.business_impact.impact_basis) if original.business_impact.impact_basis else None
    new_basis = _normalize(new.impact_basis) if new.impact_basis else None
    return (
        original.category == new.category
        and original.subtype == new.subtype
        and original.priority == new.draft.priority
        and _normalize(original.finding) == _normalize(new.draft.finding)
        and original_codes == new_codes
        and original.business_impact.exposure_usd == new.exposure_usd
        and original.business_impact.estimated_impact_usd == new.estimated_impact_usd
        and original_basis == new_basis
    )


def _auto_link_unambiguous_revisions(
    *,
    affected_insight_ids: list[str],
    previous_by_id: dict[str, RankedInsight],
    resolutions: list[_RevisionResolution],
    resolved: list[_ResolvedInsight],
) -> None:
    """Deterministic linkage repair (requirement E), run before
    _validate_revision_resolutions: the model is required to set a
    replacement draft's revises_insight_id itself, but in practice
    sometimes proposes an obviously-intended replacement without it -- the
    exact REQ_1006 failure shape (a "changed" resolution with no
    revises_insight_id anywhere in the regenerated package). Mutates the
    matching draft's revises_insight_id in place, in `resolved`, only when
    the match is unambiguous:

    - the resolution's action is "changed" or "retained" (never "removed",
      which by definition claims no replacement exists);
    - exactly one still-unlinked resolved insight belongs to the same
      company as the original; and
    - for "changed", that candidate is actually materially different from
      the original (_content_equal) -- an unchanged candidate is never
      auto-linked, since linking it would just hide the same problem
      _validate_revision_resolutions exists to catch.

    Never auto-links when more than one replacement could plausibly be the
    one meant, including when two different affected ids would otherwise
    both resolve to the very same single unlinked candidate -- that
    contention makes both genuinely ambiguous, and both are left for
    _validate_revision_resolutions's own terminal failure, unchanged. This
    function only ever sets a previously-null revises_insight_id; it never
    overrides one the model already supplied.
    """

    resolution_by_id: dict[str, _RevisionResolution] = {r.affected_insight_id: r for r in resolutions}
    unlinked = [r for r in resolved if not r.draft.revises_insight_id]

    candidate_by_affected_id: dict[str, _ResolvedInsight] = {}
    for affected_id in affected_insight_ids:
        original = previous_by_id.get(affected_id)
        resolution = resolution_by_id.get(affected_id)
        if original is None or resolution is None or resolution.action not in ("changed", "retained"):
            continue
        same_company = [r for r in unlinked if r.company_code == original.company_code]
        if resolution.action == "changed":
            same_company = [r for r in same_company if not _content_equal(original, r)]
        if len(same_company) == 1:
            candidate_by_affected_id[affected_id] = same_company[0]

    claim_counts: dict[int, int] = {}
    for candidate in candidate_by_affected_id.values():
        claim_counts[id(candidate)] = claim_counts.get(id(candidate), 0) + 1

    for affected_id, candidate in candidate_by_affected_id.items():
        if claim_counts[id(candidate)] == 1:
            candidate.draft.revises_insight_id = affected_id


def _validate_revision_resolutions(
    *,
    affected_insight_ids: list[str],
    previous_by_id: dict[str, RankedInsight],
    resolutions: list[_RevisionResolution],
    resolved: list[_ResolvedInsight],
    dropped_reason_by_revises_id: dict[str, str] | None = None,
) -> None:
    """Enforces the revision-feedback contract: every insight_id the
    Reviewer flagged must be accounted for by exactly one resolution, and
    that resolution's claim must actually hold against the regenerated
    package. Raises SynthesisRevisionValidationError naming exactly which
    affected id(s) failed and why -- never silently accepted.

    dropped_reason_by_revises_id (built by the caller's main synthesis
    loop) lets the "no replacement" problem below report the real reason a
    replacement draft that DID name this affected_id never survived into
    `resolved` (e.g. "replacement was dropped because deal_fee_opportunity
    lacked DEAL_ evidence"), instead of the misleading generic message that
    reads the same whether the model never linked a replacement at all or
    linked one that was then dropped for an unrelated evidence reason (E).
    """

    dropped_reason_by_revises_id = dropped_reason_by_revises_id or {}
    resolution_by_id: dict[str, _RevisionResolution] = {r.affected_insight_id: r for r in resolutions}
    new_drafts_by_revises_id: dict[str, list[_ResolvedInsight]] = {}
    for r in resolved:
        if r.draft.revises_insight_id:
            new_drafts_by_revises_id.setdefault(r.draft.revises_insight_id, []).append(r)

    problems: list[str] = []
    for affected_id in affected_insight_ids:
        original = previous_by_id.get(affected_id)
        if original is None:
            continue  # not a real prior insight_id; nothing to validate against

        resolution = resolution_by_id.get(affected_id)
        if resolution is None:
            problems.append(f"{affected_id}: no revision_resolutions entry -- Reviewer feedback not addressed")
            continue

        replacements = new_drafts_by_revises_id.get(affected_id, [])

        if resolution.action == "removed":
            if replacements:
                problems.append(
                    f"{affected_id}: resolution claims 'removed' but a new insight still revises it"
                )
            continue

        if not replacements:
            drop_reason = dropped_reason_by_revises_id.get(affected_id)
            if drop_reason:
                problems.append(
                    f"{affected_id}: resolution claims {resolution.action!r} but its replacement "
                    f"(revises_insight_id={affected_id}) was dropped: {drop_reason}"
                )
            else:
                problems.append(
                    f"{affected_id}: resolution claims {resolution.action!r} but no new insight has "
                    "revises_insight_id set to it"
                )
            continue

        if resolution.action == "changed" and all(_content_equal(original, r) for r in replacements):
            problems.append(
                f"{affected_id}: resolution claims 'changed' but the regenerated insight is materially "
                "unchanged (same category, subtype, priority, finding, and evidence)"
            )

        # action == "retained": any non-empty justification is accepted (pydantic already
        # enforces non-empty) -- Python cannot judge whether disagreeing with the Reviewer
        # was itself correct, only that it was done explicitly rather than silently.

    if problems:
        raise SynthesisRevisionValidationError(
            "synthesis revision did not satisfy the revision-feedback contract: " + "; ".join(problems)
        )


def _preferences_block(preferences: UserPreferences) -> str:
    """Concise, decision-relevant subset of the banker's standing
    preferences, using the model's own stable field names. Deliberately
    excludes display_name (identity, not decision-relevant), and
    email_digest_enabled/at_risk_alerts_enabled/display_density (notification
    delivery and UI rendering settings -- none of them affect insight
    content, ranking, or review judgment, so including them would be
    unrelated user data in a prompt that has no use for it.
    """

    domains = ", ".join(preferences.default_data_domains) or "none"
    ranking = ", ".join(c.value for c in preferences.default_ranking_criteria) or "none"
    return "\n".join(
        [
            "Banker preferences:",
            f"- role: {preferences.role}",
            f"- default_data_domains: {domains}",
            f"- default_ranking_criteria: {ranking}",
            f"- default_lookback_months: {preferences.default_lookback_months}",
        ]
    )


def _evidence_catalog(source_payloads: list[SourcePayload]) -> str:
    lines = [
        f"- {item.evidence_code} [{payload.company_code} / {payload.source_agent.value}, {item.date.isoformat()}]: "
        f"{item.label} -- {item.detail}"
        for payload in source_payloads
        for item in payload.evidence
    ]
    return "\n".join(lines) if lines else "(no evidence items available)"


def _findings_block(source_payloads: list[SourcePayload]) -> str:
    lines = [
        f"[{payload.company_code} / {payload.source_agent.value}] {payload.findings}"
        for payload in source_payloads
        if payload.findings
    ]
    return "\n\n".join(lines) if lines else "(no findings reported)"


def _previous_affected_block(
    previous_package: InsightPackage | None, affected_insight_ids: list[str] | None
) -> str:
    if not previous_package or not affected_insight_ids:
        return ""
    affected = [i for i in previous_package.insights if i.insight_id in affected_insight_ids]
    if not affected:
        return ""

    lines = ["Previously affected insights (the Reviewer flagged these -- see the reviewer comments above):"]
    for insight in affected:
        evidence_desc = "; ".join(f"{e.evidence_code} ({e.date.isoformat()}): {e.detail}" for e in insight.evidence)
        lines.append(
            f"- insight_id={insight.insight_id} category={insight.category.value} "
            f"subtype={insight.subtype.value} priority={insight.priority.value}\n"
            f"  title: {insight.title}\n"
            f"  finding: {insight.finding}\n"
            f"  why_it_matters: {insight.why_it_matters}\n"
            f"  cited evidence: {evidence_desc}"
        )
    lines.append(
        "\nFor every insight_id listed above, you MUST include exactly one entry in "
        "revision_resolutions: action=\"changed\" (and also emit a replacement insight in `insights` with "
        "revises_insight_id set to that id -- it must be materially different, not reworded), "
        "action=\"removed\" (emit no replacement for it), or action=\"retained\" (emit an equivalent "
        "insight with revises_insight_id set, only when the original evidence genuinely does not support "
        "the Reviewer's concern -- explain exactly why in justification)."
    )
    return "\n".join(lines)


def _build_user_message(
    original_user_prompt: str,
    effective_research_prompt: str,
    preferences: UserPreferences,
    source_payloads: list[SourcePayload],
    reviewer_comments: str | None,
    previous_package: InsightPackage | None,
    affected_insight_ids: list[str] | None,
) -> str:
    parts = [
        f"Original user request: {original_user_prompt}",
        f"Effective research prompt: {effective_research_prompt}",
        "",
        _preferences_block(preferences),
        "",
        "Specialist findings:",
        _findings_block(source_payloads),
        "",
        "Available evidence (cite evidence_code verbatim; never use a code not listed here):",
        _evidence_catalog(source_payloads),
    ]
    if reviewer_comments:
        parts += ["", f"Reviewer comments to address: {reviewer_comments}"]
    previous_block = _previous_affected_block(previous_package, affected_insight_ids)
    if previous_block:
        parts += ["", previous_block]
    return "\n".join(parts)


async def synthesize_insight_package(
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
    reviewer_comments: str | None = None,
    affected_insight_ids: list[str] | None = None,
    previous_package: InsightPackage | None = None,
) -> InsightPackage:
    """Builds one InsightPackage from a complete SourcePayload collection.
    Raises contracts.workflow.invariants.WorkflowInvariantError if the
    payloads aren't actually complete for this request_id/request_version --
    synthesis never runs against partial data, even if a caller forgets to
    check first. Raises SynthesisRevisionValidationError when
    affected_insight_ids is given and the regenerated package doesn't
    demonstrably account for every one of them.
    """

    ensure_ready_for_synthesis(manifest, source_payloads)

    evidence_by_code: dict[str, EvidenceItem] = {
        item.evidence_code: item for payload in source_payloads for item in payload.evidence
    }
    evidence_company_by_code: dict[str, str] = {
        item.evidence_code: payload.company_code for payload in source_payloads for item in payload.evidence
    }

    category_labels = ", ".join(
        f"{c.category_id.value} (>= {c.minimum_count})" for c in insight_requirements.categories
    ) or "none specified"
    system = SYNTHESIS_SYSTEM_PROMPT.format(
        categories=category_labels,
        total_count=insight_requirements.total_count,
        max_per_company=insight_requirements.max_insights_per_company or "unlimited",
    )
    user_message = _build_user_message(
        original_user_prompt,
        effective_research_prompt,
        preferences,
        source_payloads,
        reviewer_comments,
        previous_package,
        affected_insight_ids,
    )

    llm = chat_model().with_structured_output(_SynthesisOutput)
    result = await llm.ainvoke(
        [{"role": "system", "content": system}, {"role": "user", "content": user_message}]
    )

    synthetic_unmet: list[UnmetRequirement] = []
    resolved: list[_ResolvedInsight] = []
    # Keyed by revises_insight_id, populated only for a dropped draft that
    # named one -- lets _validate_revision_resolutions report the real
    # reason a claimed replacement never made it into `resolved`, instead
    # of the generic "no new insight has revises_insight_id set to it" (E).
    dropped_reason_by_revises_id: dict[str, str] = {}

    def _record_drop(reason: str) -> None:
        if draft.revises_insight_id:
            dropped_reason_by_revises_id[draft.revises_insight_id] = reason

    for draft in result.insights:
        items = [evidence_by_code[code] for code in draft.evidence_codes if code in evidence_by_code]
        if not items:
            reason = f"no resolvable evidence codes in {draft.evidence_codes!r}"
            logger.warning("Dropping synthesized insight %r for request %s: %s", draft.title, request_id, reason)
            _record_drop(reason)
            continue
        owning_companies = {
            evidence_company_by_code[code] for code in draft.evidence_codes if code in evidence_company_by_code
        }
        if len(owning_companies) != 1:
            reason = (
                f"cited evidence spans {len(owning_companies)} companies ({sorted(owning_companies)}), "
                "not exactly one"
            )
            logger.warning("Dropping synthesized insight %r for request %s: %s", draft.title, request_id, reason)
            _record_drop(reason)
            continue

        if evidence_mapping.evidence_is_mixed(items) and not draft.limitations.strip():
            reason = (
                f"cited evidence ({', '.join(draft.evidence_codes)}) contains both stable/controlled and "
                "elevated/worsening signals; the insight did not state the uncertainty explicitly, so it "
                "was dropped rather than resolved by guessing"
            )
            logger.warning("Dropping synthesized insight %r for request %s: %s", draft.title, request_id, reason)
            synthetic_unmet.append(
                UnmetRequirement(category=draft.category, requested_count=1, actual_count=0, reason=f"{draft.title!r} {reason}.")
            )
            _record_drop(reason)
            continue

        claim_resolution = _resolve_claim(draft, items)
        if not claim_resolution.kept:
            if claim_resolution.unmet_reason is not None:
                logger.warning(
                    "Dropping synthesized insight %r for request %s: %s",
                    draft.title, request_id, claim_resolution.unmet_reason,
                )
                synthetic_unmet.append(
                    UnmetRequirement(
                        category=draft.category, requested_count=1, actual_count=0,
                        reason=claim_resolution.unmet_reason,
                    )
                )
                _record_drop(claim_resolution.unmet_reason)
            else:
                logger.info(
                    "Dropping synthesized insight %r for request %s: primary_claim=no_material_impact",
                    draft.title, request_id,
                )
                _record_drop("primary_claim was no_material_impact")
            continue

        if claim_resolution.credit_risk_requirement_unmet:
            synthetic_unmet.append(
                UnmetRequirement(
                    category=InsightCategory.CREDIT_RISK,
                    requested_count=1,
                    actual_count=0,
                    reason=_NO_CREDIT_RISK_EVIDENCE_REASON,
                )
            )

        if _contradicts_cited_evidence(draft, items):
            reason = (
                f"claimed elevated risk, but its own cited evidence ({', '.join(draft.evidence_codes)}) "
                "describes the situation as stable, improving, or controlled and no other cited evidence "
                "supported the elevated conclusion -- evidence controls the inference, so the insight was "
                "dropped rather than kept"
            )
            logger.warning(
                "Dropping synthesized insight %r for request %s: claims elevated risk "
                "(risk_severity_score=%d) but its cited evidence describes stable/controlled risk with no "
                "cited evidence supporting an elevated conclusion",
                draft.title, request_id, draft.risk_severity_score,
            )
            synthetic_unmet.append(
                UnmetRequirement(category=draft.category, requested_count=1, actual_count=0, reason=f"{draft.title!r} {reason}.")
            )
            _record_drop(reason)
            continue

        exposure_usd, estimated_impact_usd, impact_basis = _resolve_monetary_fields(draft)
        confidence_cap = evidence_mapping.compute_confidence_cap(items)
        final_confidence = min(draft.confidence, confidence_cap)

        resolved.append(
            _ResolvedInsight(
                draft=draft,
                evidence=items,
                company_code=owning_companies.pop(),
                category=claim_resolution.category,
                subtype=claim_resolution.subtype,
                primary_claim=claim_resolution.primary_claim,
                confidence=final_confidence,
                exposure_usd=exposure_usd,
                estimated_impact_usd=estimated_impact_usd,
                impact_basis=impact_basis,
            )
        )

    if affected_insight_ids:
        previous_by_id = {i.insight_id: i for i in (previous_package.insights if previous_package else [])}
        _auto_link_unambiguous_revisions(
            affected_insight_ids=affected_insight_ids,
            previous_by_id=previous_by_id,
            resolutions=result.revision_resolutions,
            resolved=resolved,
        )
        _validate_revision_resolutions(
            affected_insight_ids=affected_insight_ids,
            previous_by_id=previous_by_id,
            resolutions=result.revision_resolutions,
            resolved=resolved,
            dropped_reason_by_revises_id=dropped_reason_by_revises_id,
        )

    ranked = _rank_drafts(resolved, insight_requirements.ranking_criteria)
    ranked = _apply_count_caps(ranked, insight_requirements)

    insights = [
        RankedInsight(
            insight_id=f"PKG_{request_id}_{package_version}_INS_{i}",
            rank=i + 1,
            company_code=r.company_code,
            category=r.category,
            subtype=r.subtype,
            primary_claim=r.primary_claim,
            persona=r.draft.persona,
            priority=r.draft.priority,
            title=r.draft.title,
            finding=r.draft.finding,
            why_it_matters=r.draft.why_it_matters,
            recommended_action=r.draft.recommended_action,
            confidence=r.confidence,
            confidence_rationale=r.draft.confidence_rationale,
            business_impact=BusinessImpact(
                exposure_usd=r.exposure_usd,
                estimated_impact_usd=r.estimated_impact_usd,
                impact_basis=r.impact_basis,
                description=r.draft.business_impact_description,
            ),
            evidence=r.evidence,
        )
        for i, r in enumerate(ranked)
    ]

    # Requirement C: a requested category with minimum_count == 0 is an
    # optional focus area, never a quota -- it can never be reported as an
    # unmet minimum, regardless of whether the drop came from this
    # function's own deterministic checks (synthetic_unmet) or the model's
    # own self-reported result.unmet_requirements. Filtered here, once, at
    # the single point every unmet requirement is combined, rather than at
    # each append site above, so nothing can bypass it. A "total" entry
    # (category=None, about insight_requirements.total_count rather than
    # any one category) is never filtered by this -- total_count is a
    # target the model may fall short of, not something this rule concerns.
    zero_minimum_categories = {c.category_id for c in insight_requirements.categories if c.minimum_count == 0}
    unmet_requirements = [
        u
        for u in (
            synthetic_unmet
            + [
                UnmetRequirement(
                    category=u.category, requested_count=u.requested_count, actual_count=u.actual_count,
                    reason=u.reason,
                )
                for u in result.unmet_requirements
            ]
        )
        if u.category not in zero_minimum_categories
    ]

    return InsightPackage(
        request_id=request_id,
        request_version=request_version,
        package_version=package_version,
        original_user_prompt=original_user_prompt,
        effective_research_prompt=effective_research_prompt,
        preferences=preferences,
        source_payload_refs=[
            PayloadKey(company_code=p.company_code, source_agent=p.source_agent) for p in source_payloads
        ],
        insights=insights,
        unmet_requirements=unmet_requirements,
        created_at=datetime.now(timezone.utc),
    )


def apply_synthesis_revision(state: WorkflowState, decision: ReviewDecision, *, occurred_at: datetime) -> WorkflowState:
    """Orchestrator-side handling of a Reviewer's revise_insights decision.

    Mirrors agents.research_execution.apply_research_revision: accepted only
    while synthesis_revision_count is below INSIGHTS_MAX_SYNTHESIS_REVISIONS
    (contracts.workflow.config -- read as a bare module-level name so it
    stays monkeypatchable in tests). Once the configured limit is reached,
    a further revise_insights is rejected by transitioning to failed with a
    bounded-retry reason that names the actual configured limit, not by
    raising past the caller -- exceeding the budget is a workflow-state
    transition, not an exception to handle upstream.

    The accepted-branch's audit message says "initiated", not "accepted":
    this call only marks that a revision attempt has *started* --
    synthesize_insight_package still has to run and produce a package that
    actually satisfies the revision-feedback contract (see
    SynthesisRevisionValidationError and agents.insight_workflow's internal
    validation-retry wrapper) before this revision can be considered valid.
    """

    if decision.decision != ReviewDecisionType.REVISE_INSIGHTS:
        raise ValueError(
            f"apply_synthesis_revision requires decision=revise_insights, got {decision.decision.value!r}"
        )

    if state.synthesis_revision_count >= INSIGHTS_MAX_SYNTHESIS_REVISIONS:
        return state.with_terminal_error(
            "synthesis revision rejected: bounded-retry policy allows at most "
            f"{INSIGHTS_MAX_SYNTHESIS_REVISIONS} synthesis revision(s) per request, and the limit has "
            "already been reached",
            occurred_at=occurred_at,
        )

    return state.with_synthesis_revision(
        occurred_at=occurred_at, message=f"synthesis revision initiated: {decision.comments}"
    )

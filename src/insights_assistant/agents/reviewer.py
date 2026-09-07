"""Evidence and Quality Review Agent: the sole gate between a synthesized
InsightPackage and persistence/publication.

Receives only what the spec allows -- the user request and preferences
(carried on the package itself), the insight requirements, the complete
source manifest/payloads, and the InsightPackage -- and returns exactly one
ReviewDecision. Never invokes a specialist or the Synthesizer itself.

The LLM's raw output is a looser draft schema than ReviewDecision. If that
draft can't be assembled into a valid, self-consistent ReviewDecision (e.g.
revise_research with no usable narrow scope, or revise_insights citing no
real insight_id), that is treated as "not safely repairable" and downgraded
to a fail decision with an explanatory comment -- never raised as an
exception, and never silently coerced into a decision the draft didn't
actually support.

A deterministic post-check (_deterministic_findings) runs on every package
after the LLM decision is assembled: it recomputes, in Python, the same
claim/category alignment, monetary-labeling, and confidence-cap rules
agents/synthesizer.py already enforces (api/evidence_mapping.py's
has_direct_credit_quality_evidence and compute_confidence_cap). This is
defense-in-depth, not duplicated trust in the Synthesizer -- a package that
somehow reaches the Reviewer with an obvious violation (e.g. a future code
path that bypasses synthesize_insight_package, or a bug in it) cannot
receive PASS: a PASS decision from the model is overridden to
revise_insights, naming the exact insight_id(s) and issue(s), before this
function returns.
"""

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from insights_assistant.api import evidence_mapping
from insights_assistant.contracts.api.enums import ClaimType, EvidenceSourceAgent, InsightCategory, InsightSubtype
from insights_assistant.contracts.api.evidence import BusinessImpact
from insights_assistant.contracts.api.preferences import UserPreferences
from insights_assistant.contracts.api.requests import InsightRequirementsSelection
from insights_assistant.contracts.workflow.enums import ReviewDecisionType
from insights_assistant.contracts.workflow.packages import InsightPackage, RankedInsight
from insights_assistant.contracts.workflow.research import ResearchManifest, SourcePayload
from insights_assistant.contracts.workflow.review import NarrowResearchRevision, ReviewDecision
from insights_assistant.llm import chat_model

REVIEW_SYSTEM_PROMPT = """You are the Evidence and Quality Review Agent for a relationship-banking \
insights workflow. You review one InsightPackage produced by the Insights Synthesizer and decide \
exactly one outcome for it.

Evaluate:
1. Does each insight align with the original user request and the stated preferences?
2. Is every factual statement in `finding` actually supported by its cited evidence -- directly \
traceable to the evidence shown, not merely plausible? why_it_matters and recommended_action are \
interpretation and should be labeled as such, never presented as directly observed fact.
3. Are citations accurate: the right evidence for the claim, not a mismatched or generic one?
4. Does the evidence's own semantics (what it actually documents) support the selected category and \
subtype? In particular:
   - financing_liquidity: needs facility/maturity/utilization/covenant evidence, FMP financial-health \
metrics, or a FRED rate. A facility being fully drawn, a maturity being near, an exposure amount, or a \
rate move is a financing/liquidity fact -- never by itself borrower credit deterioration.
   - deal_fee_opportunity: needs at least one cited DEAL_ evidence record (an actual CRM pipeline deal). \
A legacy lost mandate, a stalled opportunity, a competitor mention, or an OPP_ record is relationship or \
competitive evidence, not a CRM deal -- never request recategorizing an insight into deal_fee_opportunity \
on the strength of that evidence alone, and flag it (revise_insights) if the package already does.
   - financial_performance: needs FMP_ or AV_ evidence (earnings, margins, leverage, liquidity, \
valuation, or price performance).
   - risk_coverage_attention: needs target-company status or RISKFLAG_ evidence (or, for a pre-existing \
legacy insight only, RISK_ evidence) -- this means banker attention is warranted, not that the \
relationship or credit quality is deteriorating.
   - relationship risk (a worsening relationship-risk score, lost mandates, competitor activity, \
declining relationship revenue) must never be conflated with borrower credit risk (a rating downgrade, \
covenant pressure, delinquency, or another direct credit-quality signal). A credit-exposure balance alone \
is evidence only of the exposure's existence and size, never of deterioration or an intent to \
characterize it as at risk.
   - legacy relationship-manager-note or relationship-metric evidence may still support relationship_risk \
for a pre-existing insight, but a request scoped exclusively to the new internal schema (see the source \
payload status below) should not be citing that kind of evidence at all -- flag it as a synthesis or \
source-data issue if it is.
5. Is each monetary amount labeled correctly as exposure, revenue, opportunity value, estimated \
impact, or another defined type -- and if reported as estimated business impact, is it something \
other than a bare, unexplained copy of the exposure or revenue figure? A DEAL_ record's potential_fee_usd \
is an opportunity value, never exposure; an EXP_ facility's committed or drawn amount is exposure, never \
an estimated-impact figure; neither should be relabeled as the other, and no recovery rate or other \
unsourced percentage should appear in impact_basis.
6. Does the recommended action actually address the issue the finding and why_it_matters demonstrate, \
not a generic or mismatched action?
7. Is confidence consistent with the breadth and independence of cited evidence, and with whether that \
evidence is mixed or contradictory? A single evidence item or evidence limited to one source type \
should not carry very high confidence.
8. Does the package follow the requested categories, minimum counts, and ranking criteria as well as \
the evidence allows? A category listed with minimum count 0 is an optional focus area, not a quota -- \
never request revise_insights or revise_research, and never treat the package as deficient, merely \
because no insight was produced for a minimum-0 category or because total_count fell short; that is \
expected when the evidence does not support more, not a defect to fix.
9. Are there duplicate or contradictory insights that should have been consolidated or resolved?
10. If something is wrong, is the root cause the synthesis (wording, ranking, dedup, categorization, \
evidence linkage) or the underlying source data (missing, ambiguous, contradictory, or erroneous)?

Decide exactly one of:
- pass: the insights are sufficiently supported and aligned with intent.
- revise_insights: the source evidence is sufficient, but synthesis (wording, ranking, dedup, \
categorization, or evidence linkage) needs a fix. List every affected insight_id.
- revise_research: only when missing, ambiguous, contradictory, or erroneous source data makes a \
reliable result impossible. List the affected source agents and give a narrow, targeted instruction: \
specific companies, specific source agents, and exactly what to clarify or re-check. Never change the \
original business objective -- only narrow what gets re-checked.
- fail: the issue cannot be safely fixed by one more revision, or is out of scope for revision.

comments must be concise, decision-oriented audit text a banker or engineer can act on directly. State \
the finding and what needs to happen next -- do not narrate how you reached the decision.
"""


class _ReviewDraft(BaseModel):
    decision: ReviewDecisionType
    comments: str = Field(min_length=1)
    affected_insight_ids: list[str] = Field(default_factory=list)
    narrow_company_codes: list[str] = Field(default_factory=list)
    narrow_source_agents: list[EvidenceSourceAgent] = Field(default_factory=list)
    narrow_guidance: str | None = None


def _preferences_block(preferences: UserPreferences) -> str:
    """Concise, decision-relevant subset of the banker's standing
    preferences, using the model's own stable field names -- identical
    rendering to agents/synthesizer.py's helper of the same name, so the
    Synthesizer and Reviewer see the same snapshot rendered the same way.
    Deliberately excludes display_name (identity, not decision-relevant),
    and email_digest_enabled/at_risk_alerts_enabled/display_density
    (notification delivery and UI rendering settings -- none of them affect
    review judgment, so including them would be unrelated user data in a
    prompt that has no use for it.
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


def _monetary_summary(impact: BusinessImpact) -> str:
    """Renders exposure and estimated impact as clearly separate figures --
    never a single amount that could read as either -- so the Reviewer can
    check requirement 8's monetary-labeling rule directly from the prompt."""

    exposure = f"${impact.exposure_usd:,}" if impact.exposure_usd is not None else "none reported"
    if impact.estimated_impact_usd is not None:
        estimated = f"${impact.estimated_impact_usd:,} (basis: {impact.impact_basis})"
    else:
        estimated = "none reported"
    return f"exposure={exposure}; estimated_impact={estimated}; {impact.description}"


def _insights_block(package: InsightPackage) -> str:
    lines = []
    for insight in package.insights:
        evidence_desc = "; ".join(f"{e.evidence_code} ({e.date.isoformat()})" for e in insight.evidence)
        lines.append(
            f"[{insight.insight_id}] rank={insight.rank} company={insight.company_code} "
            f"category={insight.category.value} subtype={insight.subtype.value} "
            f"primary_claim={insight.primary_claim.value} priority={insight.priority.value} "
            f"confidence={insight.confidence}\n"
            f"  title: {insight.title}\n"
            f"  finding: {insight.finding}\n"
            f"  why_it_matters: {insight.why_it_matters}\n"
            f"  recommended_action: {insight.recommended_action}\n"
            f"  monetary: {_monetary_summary(insight.business_impact)}\n"
            f"  evidence: {evidence_desc}"
        )
    return "\n\n".join(lines) if lines else "(no insights produced)"


def _unmet_requirements_block(package: InsightPackage) -> str:
    if not package.unmet_requirements:
        return "(none reported)"
    return "\n".join(
        f"- category={u.category.value if u.category else 'total'} requested={u.requested_count} "
        f"actual={u.actual_count}: {u.reason}"
        for u in package.unmet_requirements
    )


def _source_status_block(source_payloads: list[SourcePayload]) -> str:
    lines = [
        f"- {payload.company_code}/{payload.source_agent.value}: {payload.status.value}"
        + (f" ({payload.error})" if payload.error else "")
        for payload in source_payloads
    ]
    return "\n".join(lines) if lines else "(no source payloads)"


def _evidence_catalog(source_payloads: list[SourcePayload]) -> str:
    lines = [
        f"- {item.evidence_code} [{payload.company_code} / {payload.source_agent.value}, {item.date.isoformat()}]: "
        f"{item.label} -- {item.detail}"
        for payload in source_payloads
        for item in payload.evidence
    ]
    return "\n".join(lines) if lines else "(no evidence items available)"


def _build_user_message(
    insight_requirements: InsightRequirementsSelection,
    source_payloads: list[SourcePayload],
    package: InsightPackage,
) -> str:
    category_labels = ", ".join(
        f"{c.category_id.value} (>= {c.minimum_count})" for c in insight_requirements.categories
    ) or "none specified"
    ranking_labels = ", ".join(c.value for c in insight_requirements.ranking_criteria) or "none specified"

    return "\n".join(
        [
            f"Original user request: {package.original_user_prompt}",
            f"Effective research prompt: {package.effective_research_prompt}",
            "",
            _preferences_block(package.preferences),
            "",
            f"Requested categories and minimums: {category_labels}",
            f"Total insights requested: {insight_requirements.total_count}",
            f"Ranking criteria (priority order): {ranking_labels}",
            f"Max insights per company: {insight_requirements.max_insights_per_company or 'unlimited'}",
            "",
            "Source payload status:",
            _source_status_block(source_payloads),
            "",
            "Available evidence (for cross-checking citation accuracy):",
            _evidence_catalog(source_payloads),
            "",
            "Insights in this package:",
            _insights_block(package),
            "",
            "Unmet requirements reported by the Synthesizer:",
            _unmet_requirements_block(package),
        ]
    )


def _is_credit_risk_insight(insight: RankedInsight) -> bool:
    return insight.category == InsightCategory.CREDIT_RISK or insight.subtype == InsightSubtype.CREDIT_RISK


def _is_deal_fee_opportunity_insight(insight: RankedInsight) -> bool:
    return (
        insight.category == InsightCategory.DEAL_FEE_OPPORTUNITY
        or insight.subtype == InsightSubtype.DEAL_FEE_OPPORTUNITY
        or insight.primary_claim == ClaimType.DEAL_FEE_OPPORTUNITY
    )


def _has_deal_evidence(insight: RankedInsight) -> bool:
    return any(item.evidence_code.startswith("DEAL_") for item in insight.evidence)


def _deterministic_findings(package: InsightPackage) -> list[tuple[str, str]]:
    """Recomputes, in Python, the same rules agents/synthesizer.py already
    enforces on every persisted insight -- defense-in-depth so an obvious
    violation cannot receive PASS regardless of what the model reviewer
    decides. Returns (insight_id, issue) pairs; empty when nothing is
    wrong. See the module docstring for why this exists alongside (not
    instead of) the LLM review."""

    findings: list[tuple[str, str]] = []
    for insight in package.insights:
        if _is_credit_risk_insight(insight) and not (
            insight.primary_claim == ClaimType.CREDIT_QUALITY_DETERIORATING
            and evidence_mapping.has_direct_credit_quality_evidence(insight.evidence)
        ):
            findings.append(
                (
                    insight.insight_id,
                    "categorized as credit_risk but its cited evidence contains no direct credit-quality "
                    "signal (rating downgrade, covenant pressure, delinquency, or an explicit "
                    "credit-quality assessment showing deterioration) -- relationship risk, competitor "
                    "activity, and a credit-exposure balance alone do not establish borrower credit risk",
                )
            )

        if _is_deal_fee_opportunity_insight(insight) and not _has_deal_evidence(insight):
            findings.append(
                (
                    insight.insight_id,
                    "categorized as deal_fee_opportunity but cites no DEAL_ evidence (an actual CRM deal "
                    "pipeline record) -- a legacy lost mandate, stalled opportunity, competitor mention, "
                    "or OPP_ record does not by itself establish a deal or fee opportunity",
                )
            )

        impact = insight.business_impact
        if impact.estimated_impact_usd is not None and impact.exposure_usd is not None and (
            impact.estimated_impact_usd == impact.exposure_usd
        ):
            findings.append(
                (
                    insight.insight_id,
                    "estimated_impact_usd is a bare copy of exposure_usd -- a credit-exposure (or other "
                    "raw) balance is not itself a documented business-impact estimate",
                )
            )
        if impact.estimated_impact_usd is not None and not (impact.impact_basis or "").strip():
            findings.append((insight.insight_id, "estimated_impact_usd is set with no impact_basis"))

        cap = evidence_mapping.compute_confidence_cap(insight.evidence)
        if insight.confidence > cap:
            findings.append(
                (
                    insight.insight_id,
                    f"confidence={insight.confidence} exceeds the evidence-based ceiling of {cap} for "
                    f"{len({e.evidence_code for e in insight.evidence})} cited evidence item(s)",
                )
            )

    return findings


def _apply_deterministic_findings(decision: ReviewDecision, findings: list[tuple[str, str]]) -> ReviewDecision:
    """Overrides a PASS decision when deterministic findings exist -- never
    downgrades an already-corrective decision (revise_insights/
    revise_research/fail), since those already route the package away from
    persistence."""

    if not findings or decision.decision != ReviewDecisionType.PASS:
        return decision

    affected = sorted({insight_id for insight_id, _issue in findings})
    issues = "; ".join(f"[{insight_id}] {issue}" for insight_id, issue in findings)
    return decision.model_copy(
        update={
            "decision": ReviewDecisionType.REVISE_INSIGHTS,
            "comments": f"Deterministic review check overrode a PASS decision: {issues}",
            "affected_insight_ids": affected,
        }
    )


def _assemble_decision(
    draft: _ReviewDraft,
    *,
    request_id: str,
    request_version: int,
    package_version: int,
    known_insight_ids: set[str],
    known_company_codes: set[str],
    known_source_agents: set[EvidenceSourceAgent],
) -> ReviewDecision:
    now = datetime.now(timezone.utc)
    common = {"request_id": request_id, "request_version": request_version, "package_version": package_version}

    if draft.decision == ReviewDecisionType.REVISE_INSIGHTS:
        affected = [i for i in draft.affected_insight_ids if i in known_insight_ids]
        if not affected:
            return ReviewDecision(
                decision=ReviewDecisionType.FAIL,
                comments=(
                    "revise_insights was requested but cited no valid insight_id from this package "
                    f"(reviewer comments: {draft.comments})"
                ),
                created_at=now,
                **common,
            )
        return ReviewDecision(
            decision=ReviewDecisionType.REVISE_INSIGHTS,
            comments=draft.comments,
            affected_insight_ids=affected,
            created_at=now,
            **common,
        )

    if draft.decision == ReviewDecisionType.REVISE_RESEARCH:
        company_codes = [c for c in draft.narrow_company_codes if c in known_company_codes]
        source_agents = [a for a in draft.narrow_source_agents if a in known_source_agents]
        guidance = (draft.narrow_guidance or "").strip()
        narrow: NarrowResearchRevision | None = None
        if company_codes and source_agents and guidance:
            try:
                narrow = NarrowResearchRevision(
                    company_codes=company_codes, source_agents=source_agents, guidance=guidance
                )
            except ValueError:
                narrow = None
        if narrow is None:
            return ReviewDecision(
                decision=ReviewDecisionType.FAIL,
                comments=(
                    "revise_research was requested but did not include a usable narrow scope "
                    f"(company codes, source agents, and guidance) (reviewer comments: {draft.comments})"
                ),
                created_at=now,
                **common,
            )
        return ReviewDecision(
            decision=ReviewDecisionType.REVISE_RESEARCH,
            comments=draft.comments,
            affected_source_agents=source_agents,
            narrow_research_revision=narrow,
            created_at=now,
            **common,
        )

    return ReviewDecision(decision=draft.decision, comments=draft.comments, created_at=now, **common)


async def review_insight_package(
    *,
    insight_requirements: InsightRequirementsSelection,
    manifest: ResearchManifest,
    source_payloads: list[SourcePayload],
    package: InsightPackage,
) -> ReviewDecision:
    known_insight_ids = {insight.insight_id for insight in package.insights}
    known_company_codes = {key.company_code for key in manifest.expected_payload_keys}
    known_source_agents = {key.source_agent for key in manifest.expected_payload_keys}

    user_message = _build_user_message(insight_requirements, source_payloads, package)

    llm = chat_model().with_structured_output(_ReviewDraft)
    draft = await llm.ainvoke(
        [{"role": "system", "content": REVIEW_SYSTEM_PROMPT}, {"role": "user", "content": user_message}]
    )

    decision = _assemble_decision(
        draft,
        request_id=package.request_id,
        request_version=package.request_version,
        package_version=package.package_version,
        known_insight_ids=known_insight_ids,
        known_company_codes=known_company_codes,
        known_source_agents=known_source_agents,
    )
    return _apply_deterministic_findings(decision, _deterministic_findings(package))

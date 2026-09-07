"""Enumerations shared across the API contract. Values match
docs/api/openapi.yaml component schemas and frontend/src/api/contracts.ts
exactly -- do not add or rename a value in one place without the others.
"""

from enum import StrEnum


class RelationshipTier(StrEnum):
    TIER_1 = "tier_1"
    TIER_2 = "tier_2"


class InsightCategory(StrEnum):
    """Business area the insight was requested under (research_scope_schema.json).

    RELATIONSHIP_RISK was added alongside the credit-risk/relationship-risk
    semantic split (see contracts.api.evidence.EvidenceItem, RiskType,
    ClaimType, and agents/synthesizer.py): the source dataset's own
    evaluation taxonomy (insight_ground_truth.expected_insight_category in
    sql/internal_tables.sql) already treats "RELATIONSHIP_RISK" as a
    first-class category distinct from credit risk, and a worsening
    relationship-risk score or a lost mandate to a competitor must never be
    forced into credit_risk merely because that category pre-existed.
    """

    REVENUE_CROSS_SELL = "revenue_cross_sell"
    CREDIT_RISK = "credit_risk"
    CAPITAL_MARKETS_ADVISORY = "capital_markets_advisory"
    TREASURY_PAYMENTS_LIQUIDITY = "treasury_payments_liquidity"
    RELATIONSHIP_RISK = "relationship_risk"

    # The four categories the new-request wizard's category selector actually
    # offers (frontend/src/features/requests/wizard/wizardState.ts's
    # CATEGORY_OPTIONS) -- the five above are legacy: no longer selectable
    # there (the new target_companies/bank_credit_exposures/crm_deal_pipeline/
    # internal_risk_flags schema has no product revenue, payment activity,
    # wallet share, interaction history, or relationship-trend data to
    # support them), but kept here, still fully valid, so an existing stored
    # insight or mock record using one still deserializes and displays
    # correctly (see components/domain/badges.tsx's CATEGORY_LABELS, which
    # covers all nine).
    FINANCING_LIQUIDITY = "financing_liquidity"
    DEAL_FEE_OPPORTUNITY = "deal_fee_opportunity"
    FINANCIAL_PERFORMANCE = "financial_performance"
    RISK_COVERAGE_ATTENTION = "risk_coverage_attention"


class InsightSubtype(StrEnum):
    """The risk/opportunity driver, orthogonal to category. See
    rag/risk_classifier.py for the relationship_risk vs. project_risk
    distinction this models."""

    RELATIONSHIP_RISK = "relationship_risk"
    OPPORTUNITY_RISK = "opportunity_risk"
    PROJECT_RISK = "project_risk"
    CREDIT_RISK = "credit_risk"
    OPERATIONAL_RISK = "operational_risk"

    # One new subtype per new InsightCategory above, kept 1:1 for these four
    # rather than reused from the legacy set -- e.g. financing_liquidity is
    # deliberately not OPERATIONAL_RISK or CREDIT_RISK, since neither name
    # matches what actually drives it (a facility/covenant/rate signal) and
    # subtype is user-facing (SubtypeBadge).
    FINANCING_LIQUIDITY = "financing_liquidity"
    DEAL_FEE_OPPORTUNITY = "deal_fee_opportunity"
    FINANCIAL_PERFORMANCE = "financial_performance"
    RISK_COVERAGE_ATTENTION = "risk_coverage_attention"


class RiskType(StrEnum):
    """Which risk domain a piece of evidence (contracts.api.evidence.
    EvidenceItem.risk_types) or a synthesized claim concerns. Orthogonal to
    InsightCategory/InsightSubtype: a single evidence item can carry more
    than one, and a category/subtype pairing is only valid for an insight
    once its cited evidence's risk_types/supported_claims actually justify
    it (see agents/synthesizer.py's claim-alignment validation). Deliberately
    distinct from a raw dollar amount: the presence of a credit_exposure
    figure never by itself implies RiskType.CREDIT_RISK -- see
    MonetaryMetricType and api/evidence_mapping.py.
    """

    RELATIONSHIP_RISK = "relationship_risk"
    CREDIT_RISK = "credit_risk"
    CONCENTRATION_RISK = "concentration_risk"
    OPERATIONAL_RISK = "operational_risk"


class ClaimType(StrEnum):
    """The semantic claim family a synthesized insight makes, and/or that one
    piece of evidence is capable of supporting (contracts.api.evidence.
    EvidenceItem.supported_claims). This is the fix for the REQ_1005 failure:
    a worsening relationship_risk_score is direct evidence of
    relationship_risk_worsening and, alongside competitor/opportunity
    evidence, competitor_share_loss -- but neither one is, by itself,
    credit_quality_deteriorating, which requires its own direct
    credit-quality evidence (see api/evidence_mapping.py's
    has_direct_credit_quality_evidence).
    """

    RELATIONSHIP_RISK_WORSENING = "relationship_risk_worsening"
    CREDIT_QUALITY_DETERIORATING = "credit_quality_deteriorating"
    COMPETITOR_SHARE_LOSS = "competitor_share_loss"
    REVENUE_DECLINE = "revenue_decline"
    PRODUCT_OR_CROSS_SELL_OPPORTUNITY = "product_or_cross_sell_opportunity"
    NO_MATERIAL_IMPACT = "no_material_impact"

    # Back the four new-schema demo categories (see InsightCategory) --
    # each requires its own kind of direct evidence (api/evidence_mapping.py's
    # classify_evidence_semantics), the same "evidence controls the
    # conclusion, never the model's own stated category" discipline
    # credit_quality_deteriorating already enforces. None of these implies
    # credit-quality deterioration or relationship deterioration by itself:
    # a facility/covenant/rate signal, a CRM pipeline record, an earnings/
    # valuation figure, or an internal risk flag each says only what it
    # actually says.
    FINANCING_LIQUIDITY_SIGNAL = "financing_liquidity_signal"
    DEAL_FEE_OPPORTUNITY = "deal_fee_opportunity"
    FINANCIAL_PERFORMANCE_SIGNAL = "financial_performance_signal"
    RISK_COVERAGE_ATTENTION = "risk_coverage_attention"


class MonetaryMetricType(StrEnum):
    """What kind of dollar figure a cited evidence item's amount represents
    (contracts.api.evidence.EvidenceItem.metric_type) -- deliberately
    distinct from whether that amount is itself at risk of being lost. A
    credit_exposure figure documents the size of an exposure, not an
    estimate of loss or business impact; only a value explicitly computed
    and justified (contracts.api.evidence.BusinessImpact.impact_basis) may
    be reported as estimated_impact_usd or business_impact.
    """

    CREDIT_EXPOSURE = "credit_exposure"
    ESTIMATED_LOSS = "estimated_loss"
    BUSINESS_IMPACT = "business_impact"
    REVENUE = "revenue"
    OPPORTUNITY_VALUE = "opportunity_value"


class InsightPriority(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class InsightPersona(StrEnum):
    RELATIONSHIP_MANAGER = "relationship_manager"
    CREDIT_OFFICER = "credit_officer"
    CAPITAL_MARKETS_BANKER = "capital_markets_banker"
    TREASURY_SALES_OFFICER = "treasury_sales_officer"
    RISK_OFFICER = "risk_officer"
    EXECUTIVE_SPONSOR = "executive_sponsor"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class RejectReason(StrEnum):
    INCORRECT = "incorrect"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    DUPLICATE = "duplicate"
    NOT_MATERIAL = "not_material"
    OUTDATED = "outdated"
    WRONG_AUDIENCE = "wrong_audience"
    ACTION_NOT_USEFUL = "action_not_useful"


class EvidenceSourceAgent(StrEnum):
    EXTERNAL_DATA_AGENT = "external_data_agent"
    INTERNAL_DATA_AGENT = "internal_data_agent"
    RELATIONSHIP_NOTES_AGENT = "relationship_notes_agent"


class EvidenceSourceType(StrEnum):
    """internal_data_agent and relationship_notes_agent both read the bank's
    own systems; only external_data_agent (FMP/Alpha Vantage/FRED) is a
    public source."""

    INTERNAL = "internal"
    EXTERNAL = "external"


class ExternalProvider(StrEnum):
    """The three vendors external_data_agent's curated adapters call
    (agents/external_adapters.py), and mcp_servers/registry.py's matching
    MCP server keys. Never exposed to a third-party tool call itself --
    purely an internal/typed identifier for provider-level status and
    evidence provenance (ExternalEvidenceRecord.provider)."""

    FMP = "fmp"
    ALPHA_VANTAGE = "alpha_vantage"
    FRED = "fred"


class ProviderStatus(StrEnum):
    """Per-provider outcome of one external_data_agent research pass
    (agents/external_adapters.py, contracts/workflow/external_research.py's
    ProviderCallResult) -- finer-grained than SourcePayloadStatus, which
    only ever describes the specialist as a whole. One provider being
    unavailable/rate_limited/etc. must never be reported to the Synthesizer
    as "checked and found nothing" (that's NO_DATA, a genuinely different,
    positive fact) -- see agents/external_adapters.py's module docstring."""

    COMPLETED = "completed"
    NO_DATA = "no_data"
    UNAVAILABLE = "unavailable"
    AUTH_ERROR = "auth_error"
    RATE_LIMITED = "rate_limited"
    TIMED_OUT = "timed_out"


class ExternalResearchTrigger(StrEnum):
    """Which internal signal (agents/external_research_plan.py) justified
    calling out to a given external provider/adapter for a company -- the
    audit trail behind ExternalResearchPlan.adapter_calls[].reason. NONE
    means no company-specific trigger fired; GENERIC means the plan was
    built without internal context at all (internal research disabled for
    this request) and used the bounded default plan instead."""

    NEAR_MATURITY = "near_maturity"
    HIGH_UTILIZATION = "high_utilization"
    COVENANT_THRESHOLD = "covenant_threshold"
    REFINANCING_OPPORTUNITY = "refinancing_opportunity"
    MA_OPPORTUNITY = "ma_opportunity"
    MARGIN_RISK = "margin_risk"
    NONE = "none"
    GENERIC = "generic"


class RequestStatus(StrEnum):
    """PARTIALLY_COMPLETED distinguishes "some companies/sources finished,
    some failed" from a clean completed/failed terminal state. CANCELLED is
    a distinct terminal state from FAILED: the request was deliberately
    stopped (POST /v1/requests/{requestId}/cancel), not a run that hit an
    error."""

    DRAFT = "draft"
    QUEUED = "queued"
    RUNNING = "running"
    PARTIALLY_COMPLETED = "partially_completed"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SourceAgentStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class CompanySelectionMode(StrEnum):
    EXPLICIT = "explicit"
    TOP_N = "top_n"
    INDUSTRY_FILTER = "industry_filter"


class RankingCriterion(StrEnum):
    COMMERCIAL_POTENTIAL = "commercial_potential"
    URGENCY = "urgency"
    CONFIDENCE = "confidence"
    RISK_SEVERITY = "risk_severity"


class InsightSortField(StrEnum):
    GENERATED_AT = "generatedAt"
    PRIORITY = "priority"
    CONFIDENCE = "confidence"
    BUSINESS_IMPACT = "businessImpact"


class RequestSortField(StrEnum):
    CREATED_AT = "createdAt"
    UPDATED_AT = "updatedAt"


class SortDirection(StrEnum):
    ASC = "asc"
    DESC = "desc"


class DisplayDensity(StrEnum):
    COMFORTABLE = "comfortable"
    COMPACT = "compact"


class ReviewEventAction(StrEnum):
    GENERATED = "generated"
    APPROVED = "approved"
    REJECTED = "rejected"
    RESET = "reset"


class FilingType(StrEnum):
    FORM_10K = "10-K"
    FORM_10Q = "10-Q"
    FORM_8K = "8-K"
    DEF_14A = "DEF 14A"


class ConfidenceTierId(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ErrorCode(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    SEMANTIC_ERROR = "SEMANTIC_ERROR"

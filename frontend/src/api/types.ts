/**
 * Domain types mirror the backend schema directly:
 * - Company / RelationshipSnapshot / RelationshipMetricMonthly / Product /
 *   Opportunity / RiskAssessment / ClientInteraction / RelationshipNote map
 *   to src/insights_assistant/sql/internal_tables.sql.
 * - ResearchRequest mirrors src/insights_assistant/contracts/research/research_scope_schema.json.
 * - Insight is the synthesized output of the agent orchestrator
 *   (src/insights_assistant/agents/orchestrator.py).
 */

export type RelationshipTier = 'tier_1' | 'tier_2'

export interface Company {
  companyId: string
  companyCode: string
  companyName: string
  ticker: string
  industry: string
  sector: string
  relationshipTier: RelationshipTier
  relationshipStartDate: string
  /** From the newer target_companies dataset -- optional because the current backend
   * still serves companies from the original company_master table, which has no
   * equivalent field. Render only when present; never fabricate a value client-side. */
  currentStatus?: 'At risk' | 'Developing opportunity' | 'Stable' | 'Strong'
  /** From target_companies.internal_coverage_lead -- same availability caveat as currentStatus. */
  internalCoverageLead?: string
  fortuneRank: number | null
}

export type RelationshipStrength = 'strong' | 'moderate' | 'developing' | 'at_risk'
export type RelationshipStatus =
  | 'strong'
  | 'stable'
  | 'developing_opportunity'
  | 'at_risk'
  | 'critical'

export interface RelationshipSnapshot {
  companyId: string
  relationshipStrength: RelationshipStrength
  currentAnnualRevenue: number
  priorYearRevenue: number
  yoyGrowthPct: number
  transactionVolumeYtd: number
  relationshipStatus: RelationshipStatus
  relationshipManager: string
  executiveSponsor: string
  asOfDate: string
}

export type SentimentLabel = 'positive' | 'neutral' | 'negative' | 'mixed'
export type TrendLabel =
  | 'rapid_growth'
  | 'slow_growth'
  | 'stable'
  | 'declining'
  | 'sudden_deterioration'
  | 'recovering'

export interface RelationshipMetricMonthly {
  observationMonth: string
  transactionVolume: number
  relationshipRevenue: number
  pipelineValue: number
  riskScore: number
  sentimentLabel: SentimentLabel
  trendLabel: TrendLabel
}

export type ProductName =
  | 'payments'
  | 'treasury_services'
  | 'lending'
  | 'investment_banking'
  | 'capital_markets'
  | 'fx'
  | 'trade_finance'
  | 'liquidity_management'
  | 'custody'
export type ProductStatus = 'active' | 'inactive' | 'pilot' | 'churned'
export type GrowthTrend = 'rapid_growth' | 'growing' | 'stable' | 'declining' | 'at_risk'

export interface Product {
  productId: string
  companyId: string
  productName: ProductName
  annualRevenue: number
  productStatus: ProductStatus
  growthTrend: GrowthTrend
  renewalDate: string | null
}

export type OpportunityStage =
  | 'prospecting'
  | 'qualification'
  | 'proposal'
  | 'negotiation'
  | 'closed_won'
  | 'closed_lost'
  | 'stalled'
export type StrategicImportance = 'low' | 'medium' | 'high' | 'critical'
export type OpportunityStatus = 'active' | 'won' | 'lost' | 'stalled'
export type CompetitivePressure = 'none' | 'low' | 'moderate' | 'high'

export interface Opportunity {
  opportunityId: string
  companyId: string
  opportunityName: string
  opportunityValue: number
  stage: OpportunityStage
  probabilityPct: number
  expectedCloseDate: string | null
  strategicImportance: StrategicImportance
  status: OpportunityStatus
  competitivePressure: CompetitivePressure
  competitorName: string | null
}

export type RiskTrend = 'improving' | 'stable' | 'worsening'

export interface RiskAssessment {
  riskId: string
  companyId: string
  asOfDate: string
  creditExposure: number
  relationshipRiskScore: number
  concentrationRiskScore: number
  operationalRiskScore: number
  riskTrend: RiskTrend
  explanatoryComment: string
}

export type InteractionType = 'meeting' | 'call' | 'email' | 'conference'
export type InteractionTopic =
  | 'expansion_plans'
  | 'investment_priorities'
  | 'relationship_concerns'
  | 'product_discussion'
  | 'competitor_activity'
  | 'renewal_discussion'
  | 'strategic_opportunity'

export interface ClientInteraction {
  interactionId: string
  companyId: string
  interactionDate: string
  interactionType: InteractionType
  topic: InteractionTopic
  attendees: string[]
  summary: string
  sentiment: SentimentLabel
}

export type RelationshipRiskFlag = 'at_risk' | 'not_at_risk' | 'no_signal'

export interface RelationshipNote {
  noteId: string
  companyCode: string
  companyName: string
  relationshipManager: string
  noteDate: string
  noteText: string
  sourceType: 'relationship_manager_note'
  riskFlag: RelationshipRiskFlag
}

// --- Insights (orchestrator output) ---------------------------------------

/**
 * Business area the insight was requested under (mirrors research_scope_schema.json).
 * relationship_risk is distinct from credit_risk: a worsening relationship-risk score,
 * lost mandates, or competitor activity are relationship_risk, never credit_risk, unless
 * direct borrower credit-quality evidence (a rating downgrade, covenant pressure,
 * delinquency, etc.) is also cited.
 */
export type InsightCategory =
  // Legacy -- no longer offered by the wizard's category selector; kept so
  // an existing stored insight/request still deserializes and displays.
  | 'revenue_cross_sell'
  | 'credit_risk'
  | 'capital_markets_advisory'
  | 'treasury_payments_liquidity'
  | 'relationship_risk'
  // Current -- selectable in the wizard (wizardState.ts's CATEGORY_OPTIONS).
  | 'financing_liquidity'
  | 'deal_fee_opportunity'
  | 'financial_performance'
  | 'risk_coverage_attention'

/** Which risk domain a piece of evidence or a synthesized claim concerns. */
export type RiskType = 'relationship_risk' | 'credit_risk' | 'concentration_risk' | 'operational_risk'

/**
 * The semantic claim family a synthesized insight makes, and/or that one piece of
 * evidence is capable of supporting. A credit_risk insight requires
 * primaryClaim='credit_quality_deteriorating' backed by direct credit-quality evidence --
 * a worsening relationship-risk score alone never qualifies.
 */
export type ClaimType =
  | 'relationship_risk_worsening'
  | 'credit_quality_deteriorating'
  | 'competitor_share_loss'
  | 'revenue_decline'
  | 'product_or_cross_sell_opportunity'
  | 'no_material_impact'

/** What kind of dollar figure a cited evidence item's amount represents. */
export type MonetaryMetricType = 'credit_exposure' | 'estimated_loss' | 'business_impact' | 'revenue' | 'opportunity_value'

/**
 * The specific risk/opportunity driver behind the insight. Orthogonal to
 * category: e.g. a revenue_cross_sell insight can be driven by
 * opportunity_risk (a deal stalling) or project_risk (an implementation
 * delay blocking it). This is the distinction the orchestrator's
 * relationship_notes_agent prompt draws explicitly (see
 * agents/orchestrator.py and rag/risk_classifier.py) between an explicit
 * relationship-level risk flag and hard negatives like project, opportunity,
 * or operational risk.
 */
export type InsightSubtype =
  | 'relationship_risk'
  | 'opportunity_risk'
  | 'project_risk'
  | 'credit_risk'
  | 'operational_risk'
  | 'financing_liquidity'
  | 'deal_fee_opportunity'
  | 'financial_performance'
  | 'risk_coverage_attention'

export type InsightPriority = 'critical' | 'high' | 'medium' | 'low'

/** The banker role this insight is primarily routed to. */
export type InsightPersona =
  | 'relationship_manager'
  | 'credit_officer'
  | 'capital_markets_banker'
  | 'treasury_sales_officer'
  | 'risk_officer'
  | 'executive_sponsor'

export type ReviewStatus = 'pending' | 'approved' | 'rejected'

export type RejectReason =
  | 'incorrect'
  | 'insufficient_evidence'
  | 'duplicate'
  | 'not_material'
  | 'outdated'
  | 'wrong_audience'
  | 'action_not_useful'

export interface ReviewEvent {
  id: string
  action: 'generated' | 'approved' | 'rejected' | 'reset'
  actor: string
  timestamp: string
  reason?: RejectReason
}

/**
 * The monetary picture for one insight. amountUsd/description are the
 * original, undifferentiated fields -- kept so legacy data (existing mock
 * rows) keeps rendering unchanged. exposureUsd/estimatedImpactUsd/
 * impactBasis are additive: a raw exposure balance is never itself a claim
 * that the amount is at risk, and estimatedImpactUsd is only ever set
 * alongside impactBasis documenting how it was derived -- never a bare copy
 * of exposureUsd. New data populates the split fields; components should
 * prefer them when present and fall back to amountUsd otherwise (see
 * formatBusinessImpact in features/insights).
 */
export interface BusinessImpact {
  amountUsd: number
  description: string
  exposureUsd?: number | null
  estimatedImpactUsd?: number | null
  impactBasis?: string | null
}

export type EvidenceSourceAgent = 'external_data_agent' | 'internal_data_agent' | 'relationship_notes_agent'

/** internal_data_agent and relationship_notes_agent both read the bank's own systems; only external_data_agent (FMP/Alpha Vantage/FRED) is a public source. */
export type EvidenceSourceType = 'internal' | 'external'

export interface EvidenceItem {
  id: string
  sourceAgent: EvidenceSourceAgent
  sourceType: EvidenceSourceType
  evidenceCode: string
  label: string
  detail: string
  date: string
  /** Which risk domain(s) this evidence item's own content concerns. Absent on legacy mock data. */
  riskTypes?: RiskType[]
  /** Which claim families this evidence item's own content directly supports. Absent on legacy mock data. */
  supportedClaims?: ClaimType[]
  metricType?: MonetaryMetricType | null
}

export interface Insight {
  id: string
  requestId: string
  companyId: string
  companyCode: string
  companyName: string
  category: InsightCategory
  subtype: InsightSubtype
  /** The semantic claim this insight makes. Absent on legacy mock data. */
  primaryClaim?: ClaimType
  persona: InsightPersona
  title: string
  /** Concise finding, one or two sentences. */
  finding: string
  /** Why it matters to the banking relationship. */
  whyItMatters: string
  recommendedAction: string
  priority: InsightPriority
  confidence: number
  confidenceRationale: string
  businessImpact: BusinessImpact
  generatedAt: string
  reviewStatus: ReviewStatus
  reviewHistory: ReviewEvent[]
  evidence: EvidenceItem[]
}

// --- Research requests (mirrors research_scope_schema.json) ---------------

/** `cancelled` is a distinct terminal state from `failed`: the banker
 * deliberately stopped the request (POST /requests/{id}/cancel), not a run
 * that hit an error. */
export type RequestStatus = 'draft' | 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'

/**
 * The two-agent workflow's coarse, frontend-facing stage vocabulary (see
 * agents/insight_workflow.py and api/server.py's _STAGE_DISPLAY_MAP). Two
 * internal stages fold into `waiting_for_sources`/`reviewing` respectively
 * because they're momentary handoffs, not stages a poller could ever catch
 * mid-flight with today's synchronous pipeline. `status` above remains the
 * small, already-polled field every stage maps onto (queued/running for
 * every non-terminal stage, completed/failed/cancelled for the terminal
 * ones) — this is the richer field for display, not a replacement for
 * `status`.
 */
export type RequestStage =
  | 'queued'
  | 'researching'
  | 'waiting_for_sources'
  | 'synthesizing'
  | 'reviewing'
  | 'revising_synthesis'
  | 'revising_research'
  | 'completed'
  | 'failed'
  | 'cancelled'

export type ReviewDecisionType = 'pass' | 'revise_insights' | 'revise_research' | 'fail'

export interface RequestDataDomain {
  domainId: string
  label: string
  enabled: boolean
}

export interface RequestInsightCategory {
  categoryId: InsightCategory
  minimumCount: number
}

/** One failed or timed_out specialist source -- never a row for a source
 * that completed successfully. */
export interface RequestSourceError {
  id: string
  source: EvidenceSourceAgent
  companyId: string | null
  code: string
  message: string
  occurredAt: string
  retryable: boolean
}

/** One entry of the compact version history: a stage transition or a
 * Reviewer decision, in order. `detail` (when present) only ever carries
 * the Reviewer's own designed-to-be-shown output (decision type, its
 * audit-text comments, affected insight/source ids) -- never hidden model
 * reasoning, since nothing upstream of the API ever produces that. */
export interface RequestAuditEvent {
  stage: string
  message: string
  occurredAt: string
  detail?: {
    decision?: ReviewDecisionType
    comments?: string
    affectedInsightIds?: string[]
    affectedSourceAgents?: EvidenceSourceAgent[]
  } | null
}

/** A requested insight count/category the Synthesizer couldn't satisfy from
 * the available evidence -- reported explicitly rather than an insight
 * being manufactured to hit a number. */
export interface RequestUnmetRequirement {
  category: InsightCategory | null
  requestedCount: number
  actualCount: number
  reason: string
}

export interface ResearchRequest {
  requestId: string
  requestedBy: string
  status: RequestStatus
  createdAt: string
  updatedAt: string
  companyScope: {
    selectionMode: 'explicit' | 'top_n' | 'industry_filter'
    companies: { companyId: string; companyCode: string; companyName: string; ticker: string }[]
  }
  externalResearch: {
    /** Provider-neutral: whether external market-data research (FMP/Alpha Vantage/FRED) runs at all.
     * Falls back to `edgarEnabled` for a request persisted before this field existed. */
    enabled?: boolean
    /** e.g. ['fmp', 'alpha_vantage', 'fred']. Empty/absent on an older persisted request. */
    providers?: string[]
    /** @deprecated use `enabled` */
    edgarEnabled: boolean
    /** @deprecated ignored -- external_data_agent's curated adapters have no concept of a filing type. */
    filingTypes: string[]
    lookbackMonths: number
  }
  internalResearch: {
    dataDomains: RequestDataDomain[]
    generalSearchPrompt: string
    asOfDate: string
  }
  insightRequirements: {
    totalCount: number
    categories: RequestInsightCategory[]
    rankingCriteria: ('commercial_potential' | 'urgency' | 'confidence' | 'risk_severity')[]
    maxInsightsPerCompany: number
  }
  resultInsightIds: string[]
  progressPct: number
  errorMessage: string | null
  /**
   * Raw text answer from a real orchestrator run (agents/orchestrator.py),
   * when this request was created against the live backend
   * (src/insights_assistant/api/server.py) instead of the mock repository.
   * The orchestrator doesn't yet emit structured per-insight records, so
   * this is the only research output available until that changes — see
   * docs/api/MAPPING.md#what-the-orchestrator-doesnt-produce-yet.
   */
  resultSummary?: string | null
  /**
   * The following fields all come from the two-agent workflow's
   * WorkflowState (src/insights_assistant/contracts/workflow/state.py) and
   * are additive/optional on this type: older stored requests, the mock
   * repository (until it's updated), or an older backend simply won't send
   * them, and the UI must render sensibly without them.
   */
  currentStage?: RequestStage
  requestVersion?: number
  packageVersion?: number
  researchRevisionCount?: number
  synthesisRevisionCount?: number
  sourceErrors?: RequestSourceError[]
  reviewDecision?: ReviewDecisionType | null
  reviewComments?: string | null
  auditEvents?: RequestAuditEvent[]
  unmetRequirements?: RequestUnmetRequirement[]
}

// --- Assistant (chat over the supervisor agent) ----------------------------

export type AssistantAgent = EvidenceSourceAgent | 'supervisor'

export interface AssistantCitation {
  sourceAgent: EvidenceSourceAgent
  evidenceCode: string
  label: string
}

export interface AssistantMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  createdAt: string
  citations?: AssistantCitation[]
  activeAgent?: AssistantAgent
}

// --- Preferences -------------------------------------------------------------

export type DisplayDensity = 'comfortable' | 'compact'

export interface UserPreferences {
  displayName: string
  role: string
  defaultDataDomains: string[]
  defaultRankingCriteria: ('commercial_potential' | 'urgency' | 'confidence' | 'risk_severity')[]
  emailDigestEnabled: boolean
  atRiskAlertsEnabled: boolean
  displayDensity: DisplayDensity
  defaultLookbackMonths: number
}

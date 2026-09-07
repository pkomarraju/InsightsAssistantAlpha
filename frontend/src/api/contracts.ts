/**
 * Wire-level DTO types for the HTTP API defined in docs/api/openapi.yaml.
 * These mirror `components.schemas` there field-for-field — this file
 * should be regenerated (or hand-kept in sync) whenever the OpenAPI spec
 * changes, not treated as an independent source of truth.
 *
 * This is deliberately a separate layer from the domain types in
 * `api/types.ts`. Those types are shaped for the UI (e.g. `Insight` always
 * carries `evidence`/`reviewHistory`); the wire contract distinguishes a
 * lightweight `InsightSummaryDto` (list rows) from a full `InsightDto`
 * (detail), matching what the API actually returns over the network. A
 * future `httpClient`-based repository maps these DTOs onto the domain
 * types — see docs/api/MIGRATION_PLAN.md.
 */

// --- Enums (identical string-union values to api/types.ts) -----------------

export type RelationshipTierDto = 'tier_1' | 'tier_2'
export type InsightCategoryDto =
  | 'revenue_cross_sell'
  | 'credit_risk'
  | 'capital_markets_advisory'
  | 'treasury_payments_liquidity'
  | 'relationship_risk'
export type InsightSubtypeDto = 'relationship_risk' | 'opportunity_risk' | 'project_risk' | 'credit_risk' | 'operational_risk'
export type RiskTypeDto = 'relationship_risk' | 'credit_risk' | 'concentration_risk' | 'operational_risk'
export type ClaimTypeDto =
  | 'relationship_risk_worsening'
  | 'credit_quality_deteriorating'
  | 'competitor_share_loss'
  | 'revenue_decline'
  | 'product_or_cross_sell_opportunity'
  | 'no_material_impact'
export type MonetaryMetricTypeDto = 'credit_exposure' | 'estimated_loss' | 'business_impact' | 'revenue' | 'opportunity_value'
export type InsightPriorityDto = 'critical' | 'high' | 'medium' | 'low'
export type InsightPersonaDto =
  | 'relationship_manager'
  | 'credit_officer'
  | 'capital_markets_banker'
  | 'treasury_sales_officer'
  | 'risk_officer'
  | 'executive_sponsor'
export type ReviewStatusDto = 'pending' | 'approved' | 'rejected'
export type RejectReasonDto =
  | 'incorrect'
  | 'insufficient_evidence'
  | 'duplicate'
  | 'not_material'
  | 'outdated'
  | 'wrong_audience'
  | 'action_not_useful'
export type EvidenceSourceAgentDto = 'external_data_agent' | 'internal_data_agent' | 'relationship_notes_agent'
export type EvidenceSourceTypeDto = 'internal' | 'external'
export type RequestStatusDto = 'draft' | 'queued' | 'running' | 'partially_completed' | 'completed' | 'failed' | 'cancelled'
export type SourceAgentStatusDto = 'pending' | 'running' | 'completed' | 'failed'

/** The two-agent workflow's coarse, frontend-facing stage vocabulary --
 * mirrors docs/api/openapi.yaml's RequestStage. Not a mirror of the
 * internal WorkflowStage enum: waiting_for_sources/reviewing each fold two
 * WorkflowStage values together (see the OpenAPI schema's description). */
export type RequestStageDto =
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

/** The Evidence and Quality Review Agent's decision on one InsightPackage. */
export type ReviewDecisionTypeDto = 'pass' | 'revise_insights' | 'revise_research' | 'fail'
export type CompanySelectionModeDto = 'explicit' | 'top_n' | 'industry_filter'
export type RankingCriterionDto = 'commercial_potential' | 'urgency' | 'confidence' | 'risk_severity'
export type InsightSortFieldDto = 'generatedAt' | 'priority' | 'confidence' | 'businessImpact'
export type RequestSortFieldDto = 'createdAt' | 'updatedAt'
export type SortDirectionDto = 'asc' | 'desc'
export type DisplayDensityDto = 'comfortable' | 'compact'
export type ReviewEventActionDto = 'generated' | 'approved' | 'rejected' | 'reset'
export type FilingTypeDto = '10-K' | '10-Q' | '8-K' | 'DEF 14A'
export type ConfidenceTierIdDto = 'high' | 'medium' | 'low'
export type ErrorCodeDto = 'NOT_FOUND' | 'VALIDATION_ERROR' | 'VERSION_CONFLICT' | 'INVALID_STATE_TRANSITION' | 'SEMANTIC_ERROR'

// --- Shared building blocks --------------------------------------------

export interface IdLabelDto {
  id: string
  label: string
}

export interface ErrorResponseDto {
  error: {
    code: ErrorCodeDto
    message: string
    details?: Record<string, unknown>
  }
}

export interface VersionConflictResponseDto extends ErrorResponseDto {
  /** The resource's current server-side state, for client reconciliation. */
  current: InsightDto
}

// --- Metadata ------------------------------------------------------------

export interface CompanyOptionDto {
  companyId: string
  /** Stable business key (company_master.company_code), e.g. "CLI_002". */
  companyCode: string
  /** Display label — never used as a filter/reference value. */
  companyName: string
  ticker: string
  cik: string | null
  industry: string
  sector: string
  relationshipTier: RelationshipTierDto
  fortuneRank: number | null
}

export interface DataDomainOptionDto {
  id: string
  label: string
  description: string
}

export interface ConfidenceTierOptionDto {
  id: ConfidenceTierIdDto
  label: string
  min: number
  max: number
}

export interface MetadataDto {
  companies: CompanyOptionDto[]
  categories: IdLabelDto[]
  subtypes: IdLabelDto[]
  priorities: IdLabelDto[]
  personas: IdLabelDto[]
  reviewStatuses: IdLabelDto[]
  rejectReasons: IdLabelDto[]
  evidenceSourceTypes: IdLabelDto[]
  dataDomains: DataDomainOptionDto[]
  filingTypes: FilingTypeDto[]
  rankingCriteria: IdLabelDto[]
  confidenceTiers: ConfidenceTierOptionDto[]
  generatedAt: string
}

// --- Preferences -----------------------------------------------------------

export interface UserPreferencesDto {
  displayName: string
  role: string
  /** References MetadataDto.dataDomains[].id. */
  defaultDataDomains: string[]
  defaultRankingCriteria: RankingCriterionDto[]
  emailDigestEnabled: boolean
  atRiskAlertsEnabled: boolean
  displayDensity: DisplayDensityDto
  defaultLookbackMonths: number
}

/** All fields optional; only provided fields are updated (PATCH semantics). */
export type UpdatePreferencesRequestDto = Partial<UserPreferencesDto>

// --- Evidence & review history ----------------------------------------------

export interface EvidenceItemDto {
  id: string
  sourceAgent: EvidenceSourceAgentDto
  sourceType: EvidenceSourceTypeDto
  /** Stable citation id from the source system, e.g. RISK_016, RMN_007, OPP_004. Preserved verbatim. */
  evidenceCode: string
  label: string
  detail: string
  /** ISO date (YYYY-MM-DD). */
  date: string
  riskTypes?: RiskTypeDto[]
  supportedClaims?: ClaimTypeDto[]
  metricType?: MonetaryMetricTypeDto | null
}

export interface ReviewEventDto {
  id: string
  action: ReviewEventActionDto
  /** Stable banker identifier (matches ResearchRequestSummaryDto.requestedBy); "system" for the initial generated event. */
  actorId: string
  /** Denormalized display label — never used as a filter/reference value. */
  actorDisplayName: string
  timestamp: string
  reason?: RejectReasonDto
}

/**
 * amountUsd/description are the original, undifferentiated fields (kept for
 * legacy mock data). exposureUsd/estimatedImpactUsd/impactBasis are
 * additive: exposureUsd is never itself a claim that the amount is at risk,
 * and estimatedImpactUsd is only ever set alongside impactBasis -- never a
 * bare copy of exposureUsd.
 */
export interface BusinessImpactDto {
  amountUsd: number
  description: string
  exposureUsd?: number | null
  estimatedImpactUsd?: number | null
  impactBasis?: string | null
}

// --- Insights --------------------------------------------------------------

/** Lightweight row shape for list responses — omits evidence[]/reviewHistory[]. */
export interface InsightSummaryDto {
  id: string
  /** Optimistic-concurrency version; required as expectedVersion on approve/reject/reset. */
  version: number
  requestId: string
  companyId: string
  companyCode: string
  companyName: string
  category: InsightCategoryDto
  subtype: InsightSubtypeDto
  /** The semantic claim this insight makes. Absent on legacy mock data. */
  primaryClaim?: ClaimTypeDto
  persona: InsightPersonaDto
  title: string
  priority: InsightPriorityDto
  confidence: number
  businessImpact: BusinessImpactDto
  generatedAt: string
  reviewStatus: ReviewStatusDto
  evidenceCount: number
}

/** Full insight detail — returned by GET /v1/insights/{id} and by review actions. */
export interface InsightDto extends InsightSummaryDto {
  finding: string
  whyItMatters: string
  recommendedAction: string
  confidenceRationale: string
  reviewHistory: ReviewEventDto[]
  evidence: EvidenceItemDto[]
}

export interface InsightCountsDto {
  /** Total insights matching the current filters (== total on the envelope). */
  generated: number
  approved: number
  rejected: number
  pending: number
}

export interface ListInsightsResponseDto {
  items: InsightSummaryDto[]
  page: number
  pageSize: number
  total: number
  /** Reflects the current filter set, not the global table. */
  counts: InsightCountsDto
}

export interface ListInsightsQueryDto {
  reviewStatus?: ReviewStatusDto
  category?: InsightCategoryDto
  companyId?: string
  persona?: InsightPersonaDto
  priority?: InsightPriorityDto
  confidenceMin?: number
  confidenceMax?: number
  /** Inclusive bounds on generatedAt, YYYY-MM-DD. */
  dateFrom?: string
  dateTo?: string
  requestId?: string
  evidenceSourceType?: EvidenceSourceTypeDto
  search?: string
  sortField?: InsightSortFieldDto
  sortDirection?: SortDirectionDto
  page?: number
  pageSize?: number
}

export interface ApproveInsightRequestDto {
  expectedVersion: number
}

export interface RejectInsightRequestDto {
  expectedVersion: number
  reason: RejectReasonDto
}

export interface ResetInsightReviewRequestDto {
  expectedVersion: number
}

// --- Research requests -----------------------------------------------------

/** Mirrors contracts/research/research_scope_schema.json#companyScope, addressed by stable companyId. */
export interface CompanyScopeSelectionDto {
  universe: 'fortune_500'
  listYear?: number
  selectionMode: CompanySelectionModeDto
  /** Required when selectionMode = explicit. */
  companyIds?: string[]
  /** Required when selectionMode = top_n. */
  topN?: number
  /** Required when selectionMode = industry_filter. */
  industryFilters?: string[]
}

export interface ExternalResearchSelectionDto {
  edgarEnabled: boolean
  filingTypes: FilingTypeDto[]
  lookbackMonths: number
}

export interface InternalResearchSelectionDto {
  dataDomainIds: string[]
  generalSearchPrompt: string
  /** ISO date; defaults server-side to today if omitted. */
  asOfDate?: string
}

export interface RequestInsightCategoryDto {
  categoryId: InsightCategoryDto
  minimumCount: number
}

export interface InsightRequirementsSelectionDto {
  totalCount: number
  categories: RequestInsightCategoryDto[]
  rankingCriteria: RankingCriterionDto[]
  maxInsightsPerCompany?: number
}

export interface CreateInsightRequestBodyDto {
  /** Client-generated idempotency key (UUID). Reusing it replays the existing request. */
  requestId: string
  companyScope: CompanyScopeSelectionDto
  externalResearch: ExternalResearchSelectionDto
  internalResearch: InternalResearchSelectionDto
  insightRequirements: InsightRequirementsSelectionDto
}

export interface SourceErrorDto {
  id: string
  source: EvidenceSourceAgentDto
  /** Null if the failure is request-level rather than company-specific. */
  companyId: string | null
  /** Machine-readable failure code, e.g. "timeout", "rate_limited", "no_data", "auth_error". */
  code: string
  message: string
  occurredAt: string
  retryable: boolean
}

export interface CompanyProgressDto {
  companyId: string
  companyName: string
  status: SourceAgentStatusDto
  insightsGenerated: number
}

export interface RequestCountsDto {
  generated: number
  approved: number
  rejected: number
  pending: number
}

/** One entry of the compact workflow version history: a stage transition or
 * a Reviewer decision, in order. `detail` (when present) only ever carries
 * the Reviewer's own designed-to-be-shown output -- never hidden model
 * reasoning. */
export interface AuditEventDto {
  /** The internal WorkflowStage value at this event, not the coarser RequestStageDto. */
  stage: string
  message: string
  occurredAt: string
  detail?: {
    decision?: ReviewDecisionTypeDto
    comments?: string
    affectedInsightIds?: string[]
    affectedSourceAgents?: EvidenceSourceAgentDto[]
  } | null
}

/** A requested insight count/category the Synthesizer couldn't satisfy from
 * the available evidence. */
export interface UnmetRequirementDto {
  category: InsightCategoryDto | null
  requestedCount: number
  actualCount: number
  reason: string
}

export interface ResearchRequestSummaryDto {
  requestId: string
  /** Stable banker identifier, e.g. "banker-12345". */
  requestedBy: string
  status: RequestStatusDto
  currentStage: RequestStageDto
  createdAt: string
  updatedAt: string
  companyIds: string[]
  /** Denormalized for list-view display — never used as a filter/reference value. */
  companyNames: string[]
  /** Indicative position in the coarse pipeline, not a measured percentage of work done. */
  progressPct: number
  counts: RequestCountsDto
  /** Increments only when a research revision is accepted. */
  requestVersion: number
  /** Increments only when a synthesis revision is accepted. */
  packageVersion: number
  /** 0 or 1 -- whether the single research-revision budget has been used. */
  researchRevisionCount: number
  /** 0 or 1 -- whether the single synthesis-revision budget has been used. */
  synthesisRevisionCount: number
}

export interface ResearchRequestDetailDto extends ResearchRequestSummaryDto {
  companyScope: CompanyScopeSelectionDto & { companies: CompanyOptionDto[] }
  externalResearch: ExternalResearchSelectionDto
  internalResearch: InternalResearchSelectionDto
  insightRequirements: InsightRequirementsSelectionDto
  resultInsightIds: string[]
  companyProgress: CompanyProgressDto[]
  sourceErrors: SourceErrorDto[]
  /** Top-level summary error retained for the current UI; sourceErrors is the structured replacement. */
  errorMessage: string | null
  /** The last decision the Reviewer made, if research ever reached synthesis+review. */
  reviewDecision: ReviewDecisionTypeDto | null
  /** The Reviewer's own concise, decision-oriented audit text -- never hidden model reasoning. */
  reviewComments: string | null
  /** Compact version history -- every stage transition and every review decision, in order. */
  auditEvents: AuditEventDto[]
  /** Only ever non-empty on a request whose InsightPackage passed review. */
  unmetRequirements: UnmetRequirementDto[]
}

export interface ListInsightRequestsResponseDto {
  items: ResearchRequestSummaryDto[]
  page: number
  pageSize: number
  total: number
}

export interface ListInsightRequestsQueryDto {
  status?: RequestStatusDto
  companyId?: string
  requestedBy?: string
  dateFrom?: string
  dateTo?: string
  sortField?: RequestSortFieldDto
  sortDirection?: SortDirectionDto
  page?: number
  pageSize?: number
}

import type {
  AssistantMessage,
  ClientInteraction,
  Company,
  EvidenceSourceType,
  Insight,
  InsightCategory,
  InsightPersona,
  InsightPriority,
  Opportunity,
  Product,
  RejectReason,
  RelationshipMetricMonthly,
  RelationshipNote,
  RelationshipSnapshot,
  RequestStatus,
  ResearchRequest,
  ReviewStatus,
  RiskAssessment,
  UserPreferences,
} from '@/api/types'

export interface CompanyBrief {
  company: Company
  snapshot: RelationshipSnapshot
  products: Product[]
  opportunities: Opportunity[]
  risk: RiskAssessment[]
  interactions: ClientInteraction[]
  notes: RelationshipNote[]
  monthlyMetrics: RelationshipMetricMonthly[]
}

export interface CompaniesRepository {
  list(): Promise<Company[]>
  listSnapshots(): Promise<RelationshipSnapshot[]>
  getBrief(companyId: string): Promise<CompanyBrief>
}

export type InsightSortField = 'generatedAt' | 'priority' | 'confidence' | 'businessImpact'
export type SortDirection = 'asc' | 'desc'

export interface InsightsQuery {
  reviewStatus?: ReviewStatus
  category?: InsightCategory
  companyId?: string
  persona?: InsightPersona
  priority?: InsightPriority
  /** Inclusive confidence bounds, 0-100. */
  confidenceMin?: number
  confidenceMax?: number
  /** Inclusive date bounds on generatedAt, YYYY-MM-DD. */
  dateFrom?: string
  dateTo?: string
  requestId?: string
  evidenceSourceType?: EvidenceSourceType
  search?: string
  sortField?: InsightSortField
  sortDirection?: SortDirection
  page?: number
  pageSize?: number
}

export interface InsightsPage {
  items: Insight[]
  total: number
  page: number
  pageSize: number
}

export interface InsightsRepository {
  list(query?: InsightsQuery): Promise<InsightsPage>
  getById(insightId: string): Promise<Insight>
  /** Distinct request ids present across all insights, for the Request ID filter. */
  listRequestIds(): Promise<string[]>
  approve(insightId: string): Promise<Insight>
  reject(insightId: string, reason: RejectReason): Promise<Insight>
  /** Reverts the most recent approve/reject decision back to pending. */
  undo(insightId: string): Promise<Insight>
}

export interface CreateRequestInput {
  companyIds: string[]
  dataDomainIds: string[]
  generalSearchPrompt: string
  /** Provider-neutral: whether external market research runs at all. */
  enabled: boolean
  /** e.g. ['fmp', 'alpha_vantage', 'fred']. */
  providers: string[]
  /** @deprecated kept only because the current backend contract still requires it on the wire;
   * always mirrors `enabled`. Never read anywhere outside the request-creation adapter. */
  edgarEnabled: boolean
  /** @deprecated kept only because the current backend contract still requires it on the wire;
   * always sent empty -- no live tool uses filing types any more. */
  filingTypes: string[]
  lookbackMonths: number
  totalCount: number
  categories: { categoryId: InsightCategory; minimumCount: number }[]
  rankingCriteria: ResearchRequest['insightRequirements']['rankingCriteria']
}

export interface RequestsRepository {
  list(filters?: { status?: RequestStatus }): Promise<ResearchRequest[]>
  getById(requestId: string): Promise<ResearchRequest>
  create(input: CreateRequestInput): Promise<ResearchRequest>
  /** Stops an in-flight request's research/synthesis/review generation.
   * Only valid while status is draft/queued/running; throws ApiError(409)
   * if the request has already reached a terminal state. */
  cancel(requestId: string): Promise<ResearchRequest>
  /** Permanently deletes a request and its generated insights. Valid in any
   * status -- an in-flight request is stopped first rather than rejected,
   * since deleting is a stronger action than cancel's "still running" guard. */
  remove(requestId: string): Promise<void>
}

export interface AssistantRepository {
  getHistory(): Promise<AssistantMessage[]>
  sendMessage(content: string, history: AssistantMessage[]): Promise<AssistantMessage>
}

export interface PreferencesRepository {
  get(): Promise<UserPreferences>
  update(patch: Partial<UserPreferences>): Promise<UserPreferences>
}

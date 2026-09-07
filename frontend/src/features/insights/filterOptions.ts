import type { InsightCategory, InsightPersona, InsightPriority, ReviewStatus } from '@/api/types'
import type { InsightSortField, SortDirection } from '@/api/repositories/types'
import { CATEGORY_LABELS } from '@/components/domain/badges'

export const REVIEW_STATUS_OPTIONS: { value: ReviewStatus | 'all'; label: string }[] = [
  { value: 'all', label: 'All statuses' },
  { value: 'pending', label: 'Pending review' },
  { value: 'approved', label: 'Approved' },
  { value: 'rejected', label: 'Rejected' },
]

export const CATEGORY_OPTIONS: { value: InsightCategory | 'all'; label: string }[] = [
  { value: 'all', label: 'All categories' },
  // Current -- see wizardState.ts's own CATEGORY_OPTIONS for the
  // new-request selector, which offers only these four.
  { value: 'financing_liquidity', label: CATEGORY_LABELS.financing_liquidity },
  { value: 'deal_fee_opportunity', label: CATEGORY_LABELS.deal_fee_opportunity },
  { value: 'financial_performance', label: CATEGORY_LABELS.financial_performance },
  { value: 'risk_coverage_attention', label: CATEGORY_LABELS.risk_coverage_attention },
  // Legacy -- filterable so an existing stored insight is still reachable,
  // even though no new insight is generated under one of these any more.
  { value: 'revenue_cross_sell', label: CATEGORY_LABELS.revenue_cross_sell },
  { value: 'credit_risk', label: CATEGORY_LABELS.credit_risk },
  { value: 'capital_markets_advisory', label: CATEGORY_LABELS.capital_markets_advisory },
  { value: 'treasury_payments_liquidity', label: CATEGORY_LABELS.treasury_payments_liquidity },
  { value: 'relationship_risk', label: CATEGORY_LABELS.relationship_risk },
]

export const PRIORITY_OPTIONS: { value: InsightPriority | 'all'; label: string }[] = [
  { value: 'all', label: 'All priorities' },
  { value: 'critical', label: 'Critical' },
  { value: 'high', label: 'High' },
  { value: 'medium', label: 'Medium' },
  { value: 'low', label: 'Low' },
]

export const PERSONA_OPTIONS: { value: InsightPersona | 'all'; label: string }[] = [
  { value: 'all', label: 'All personas' },
  { value: 'relationship_manager', label: 'Relationship Manager' },
  { value: 'credit_officer', label: 'Credit Officer' },
  { value: 'capital_markets_banker', label: 'Capital Markets Banker' },
  { value: 'treasury_sales_officer', label: 'Treasury Sales Officer' },
  { value: 'risk_officer', label: 'Risk Officer' },
  { value: 'executive_sponsor', label: 'Executive Sponsor' },
]

export type ConfidenceTier = 'all' | 'high' | 'medium' | 'low'

export const CONFIDENCE_OPTIONS: { value: ConfidenceTier; label: string }[] = [
  { value: 'all', label: 'All confidence levels' },
  { value: 'high', label: 'High (≥80)' },
  { value: 'medium', label: 'Medium (60–79)' },
  { value: 'low', label: 'Low (<60)' },
]

export function confidenceTierToRange(tier: ConfidenceTier): { min?: number; max?: number } {
  switch (tier) {
    case 'high':
      return { min: 80, max: 100 }
    case 'medium':
      return { min: 60, max: 79 }
    case 'low':
      return { min: 0, max: 59 }
    default:
      return {}
  }
}

export const EVIDENCE_SOURCE_OPTIONS: { value: 'all' | 'internal' | 'external'; label: string }[] = [
  { value: 'all', label: 'All sources' },
  { value: 'internal', label: 'Internal' },
  { value: 'external', label: 'External' },
]

export const SORT_OPTIONS: { value: string; label: string; field: InsightSortField; direction: SortDirection }[] = [
  { value: 'generatedAt_desc', label: 'Generated (newest first)', field: 'generatedAt', direction: 'desc' },
  { value: 'generatedAt_asc', label: 'Generated (oldest first)', field: 'generatedAt', direction: 'asc' },
  { value: 'priority_desc', label: 'Priority (high to low)', field: 'priority', direction: 'desc' },
  { value: 'confidence_desc', label: 'Confidence (high to low)', field: 'confidence', direction: 'desc' },
  { value: 'businessImpact_desc', label: 'Business impact (high to low)', field: 'businessImpact', direction: 'desc' },
]

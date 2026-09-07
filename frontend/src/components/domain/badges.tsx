import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  Cog,
  CreditCard,
  Handshake,
  Hammer,
  Landmark,
  LineChart,
  ShieldAlert,
  Target,
  TrendingDown,
  TrendingUp,
  Users,
  type LucideIcon,
} from 'lucide-react'

import type {
  EvidenceSourceType,
  InsightCategory,
  InsightPersona,
  InsightPriority,
  InsightSubtype,
  RelationshipRiskFlag,
  RelationshipStatus,
  RequestStage,
  RequestStatus,
  ReviewDecisionType,
  ReviewStatus,
} from '@/api/types'
import { Badge } from '@/components/ui/badge'

export const CATEGORY_LABELS: Record<InsightCategory, string> = {
  // Legacy -- see InsightCategory's own comment.
  revenue_cross_sell: 'Revenue & cross-sell',
  credit_risk: 'Credit risk',
  capital_markets_advisory: 'Capital markets advisory',
  treasury_payments_liquidity: 'Treasury, payments & liquidity',
  relationship_risk: 'Relationship risk',
  // Current.
  financing_liquidity: 'Financing & liquidity',
  deal_fee_opportunity: 'Deal & fee opportunities',
  financial_performance: 'Financial performance',
  risk_coverage_attention: 'Risk & coverage attention',
}

export function CategoryBadge({ category }: { category: InsightCategory }) {
  return <Badge variant="accent">{CATEGORY_LABELS[category]}</Badge>
}

const RELATIONSHIP_STATUS_VARIANT: Record<RelationshipStatus, 'success' | 'accent' | 'warning' | 'danger' | 'neutral'> = {
  strong: 'success',
  stable: 'accent',
  developing_opportunity: 'neutral',
  at_risk: 'warning',
  critical: 'danger',
}

const RELATIONSHIP_STATUS_LABELS: Record<RelationshipStatus, string> = {
  strong: 'Strong',
  stable: 'Stable',
  developing_opportunity: 'Developing opportunity',
  at_risk: 'At risk',
  critical: 'Critical',
}

export function RelationshipStatusBadge({ status }: { status: RelationshipStatus }) {
  return <Badge variant={RELATIONSHIP_STATUS_VARIANT[status]}>{RELATIONSHIP_STATUS_LABELS[status]}</Badge>
}

const RISK_FLAG_CONFIG: Record<RelationshipRiskFlag, { label: string; variant: 'danger' | 'success' | 'neutral'; icon: LucideIcon }> = {
  at_risk: { label: 'Flagged at risk', variant: 'danger', icon: AlertTriangle },
  not_at_risk: { label: 'Not at risk', variant: 'success', icon: CheckCircle2 },
  no_signal: { label: 'No explicit signal', variant: 'neutral', icon: CircleDashed },
}

export function RiskFlagBadge({ flag }: { flag: RelationshipRiskFlag }) {
  const config = RISK_FLAG_CONFIG[flag]
  const Icon = config.icon
  return (
    <Badge variant={config.variant}>
      <Icon className="size-3" />
      {config.label}
    </Badge>
  )
}

const REQUEST_STATUS_CONFIG: Record<RequestStatus, { label: string; variant: 'neutral' | 'accent' | 'success' | 'danger' }> = {
  draft: { label: 'Draft', variant: 'neutral' },
  queued: { label: 'Queued', variant: 'neutral' },
  running: { label: 'Running', variant: 'accent' },
  completed: { label: 'Completed', variant: 'success' },
  failed: { label: 'Failed', variant: 'danger' },
  cancelled: { label: 'Cancelled', variant: 'neutral' },
}

export function RequestStatusBadge({ status }: { status: RequestStatus }) {
  const config = REQUEST_STATUS_CONFIG[status]
  return <Badge variant={config.variant}>{config.label}</Badge>
}

/**
 * The two-agent workflow's coarse stage vocabulary (see api/types.ts's
 * RequestStage) -- a finer-grained companion to RequestStatusBadge, not a
 * replacement for it. revising_* get their own warning-toned look since
 * they represent the system correcting itself, distinct from the steady
 * "in progress" accent used for the rest of the pipeline.
 */
export const REQUEST_STAGE_CONFIG: Record<RequestStage, { label: string; variant: 'neutral' | 'accent' | 'warning' | 'success' | 'danger' }> = {
  queued: { label: 'Queued', variant: 'neutral' },
  researching: { label: 'Researching', variant: 'accent' },
  waiting_for_sources: { label: 'Waiting for sources', variant: 'accent' },
  synthesizing: { label: 'Synthesizing', variant: 'accent' },
  reviewing: { label: 'Reviewing', variant: 'accent' },
  revising_synthesis: { label: 'Revising synthesis', variant: 'warning' },
  revising_research: { label: 'Revising research', variant: 'warning' },
  completed: { label: 'Completed', variant: 'success' },
  failed: { label: 'Failed', variant: 'danger' },
  cancelled: { label: 'Cancelled', variant: 'neutral' },
}

export function RequestStageBadge({ stage }: { stage: RequestStage }) {
  const config = REQUEST_STAGE_CONFIG[stage]
  return <Badge variant={config.variant}>{config.label}</Badge>
}

export const REVIEW_DECISION_CONFIG: Record<ReviewDecisionType, { label: string; variant: 'success' | 'warning' | 'danger' }> = {
  pass: { label: 'Passed', variant: 'success' },
  revise_insights: { label: 'Revise insights', variant: 'warning' },
  revise_research: { label: 'Revise research', variant: 'warning' },
  fail: { label: 'Failed review', variant: 'danger' },
}

export function ReviewDecisionBadge({ decision }: { decision: ReviewDecisionType }) {
  const config = REVIEW_DECISION_CONFIG[decision]
  return <Badge variant={config.variant}>{config.label}</Badge>
}

/**
 * The five risk/opportunity drivers the orchestrator's prompts require
 * distinguishing (agents/orchestrator.py, rag/risk_classifier.py). Each gets
 * its own icon + color so they read as visually distinct at a glance, not
 * just by label text.
 */
export const SUBTYPE_CONFIG: Record<InsightSubtype, { label: string; variant: 'danger' | 'accent' | 'neutral' | 'warning' | 'outline'; icon: LucideIcon }> = {
  // Legacy -- see InsightCategory's own comment in api/types.ts.
  relationship_risk: { label: 'Relationship risk', variant: 'danger', icon: Users },
  opportunity_risk: { label: 'Opportunity risk', variant: 'accent', icon: Target },
  project_risk: { label: 'Project / implementation risk', variant: 'neutral', icon: Hammer },
  credit_risk: { label: 'Credit risk', variant: 'warning', icon: CreditCard },
  operational_risk: { label: 'Operational risk', variant: 'outline', icon: Cog },
  // Current.
  financing_liquidity: { label: 'Financing & liquidity', variant: 'warning', icon: Landmark },
  deal_fee_opportunity: { label: 'Deal & fee opportunity', variant: 'accent', icon: Handshake },
  financial_performance: { label: 'Financial performance', variant: 'neutral', icon: LineChart },
  risk_coverage_attention: { label: 'Risk & coverage attention', variant: 'danger', icon: ShieldAlert },
}

export function SubtypeBadge({ subtype }: { subtype: InsightSubtype }) {
  const config = SUBTYPE_CONFIG[subtype]
  const Icon = config.icon
  return (
    <Badge variant={config.variant}>
      <Icon className="size-3" />
      {config.label}
    </Badge>
  )
}

export const PRIORITY_CONFIG: Record<InsightPriority, { label: string; variant: 'danger' | 'warning' | 'accent' | 'neutral' }> = {
  critical: { label: 'Critical', variant: 'danger' },
  high: { label: 'High', variant: 'warning' },
  medium: { label: 'Medium', variant: 'accent' },
  low: { label: 'Low', variant: 'neutral' },
}

export function PriorityBadge({ priority }: { priority: InsightPriority }) {
  const config = PRIORITY_CONFIG[priority]
  return <Badge variant={config.variant}>{config.label}</Badge>
}

export const REVIEW_STATUS_CONFIG: Record<ReviewStatus, { label: string; variant: 'neutral' | 'success' | 'danger' }> = {
  pending: { label: 'Pending review', variant: 'neutral' },
  approved: { label: 'Approved', variant: 'success' },
  rejected: { label: 'Rejected', variant: 'danger' },
}

export function ReviewStatusBadge({ status }: { status: ReviewStatus }) {
  const config = REVIEW_STATUS_CONFIG[status]
  return <Badge variant={config.variant}>{config.label}</Badge>
}

export const EVIDENCE_SOURCE_LABELS: Record<EvidenceSourceType, string> = {
  internal: 'Internal',
  external: 'External',
}

export function EvidenceSourceBadge({ sourceType }: { sourceType: EvidenceSourceType }) {
  return <Badge variant={sourceType === 'external' ? 'accent' : 'outline'}>{EVIDENCE_SOURCE_LABELS[sourceType]}</Badge>
}

export const PERSONA_LABELS: Record<InsightPersona, string> = {
  relationship_manager: 'Relationship Manager',
  credit_officer: 'Credit Officer',
  capital_markets_banker: 'Capital Markets Banker',
  treasury_sales_officer: 'Treasury Sales Officer',
  risk_officer: 'Risk Officer',
  executive_sponsor: 'Executive Sponsor',
}

export const REJECT_REASON_LABELS: Record<string, string> = {
  incorrect: 'Incorrect',
  insufficient_evidence: 'Insufficient evidence',
  duplicate: 'Duplicate',
  not_material: 'Not material',
  outdated: 'Outdated',
  wrong_audience: 'Wrong audience',
  action_not_useful: 'Action not useful',
}

export function TrendIndicator({ value }: { value: number }) {
  const positive = value >= 0
  return (
    <span className={`inline-flex items-center gap-1 text-sm font-medium ${positive ? 'text-success' : 'text-danger'}`}>
      {positive ? <TrendingUp className="size-3.5" /> : <TrendingDown className="size-3.5" />}
      {positive ? '+' : ''}
      {value.toFixed(1)}%
    </span>
  )
}

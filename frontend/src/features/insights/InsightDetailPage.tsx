import { useState, type ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Check, FileText, History, Undo2, X } from 'lucide-react'

import type { Insight } from '@/api/types'
import { useRepositories } from '@/app/RepositoriesProvider'
import { useToast } from '@/app/ToastProvider'
import { useAsync } from '@/hooks/useAsync'
import { formatBusinessImpact, formatDate } from '@/lib/format'
import { PageHeader } from '@/components/layout/PageHeader'
import { LoadingState } from '@/components/states/LoadingState'
import { ErrorState } from '@/components/states/ErrorState'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import {
  CategoryBadge,
  EvidenceSourceBadge,
  PERSONA_LABELS,
  PriorityBadge,
  REJECT_REASON_LABELS,
  ReviewStatusBadge,
  SubtypeBadge,
} from '@/components/domain/badges'
import { AGENT_LABELS } from '@/features/assistant/agentLabels'
import { ApproveConfirmDialog } from '@/features/insights/ApproveConfirmDialog'
import { RejectReasonDialog } from '@/features/insights/RejectReasonDialog'
import { useInsightReviewActions } from '@/features/insights/useInsightReviewActions'

function ScoreBlock({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1 rounded-md border border-border bg-surface-raised p-3">
      <span className="text-xs text-ink-faint">{label}</span>
      <span className="text-lg font-semibold text-ink">{children}</span>
    </div>
  )
}

const REVIEW_EVENT_LABELS: Record<Insight['reviewHistory'][number]['action'], string> = {
  generated: 'Generated',
  approved: 'Approved',
  rejected: 'Rejected',
  reset: 'Reset to pending',
}

export function InsightDetailPage() {
  const { insightId } = useParams<{ insightId: string }>()
  const { insights } = useRepositories()
  const { showToast } = useToast()
  const navigate = useNavigate()
  const result = useAsync(() => insights.getById(insightId!), [insights, insightId])
  const [localInsight, setLocalInsight] = useState<Insight | null>(null)

  const insight = localInsight ?? (result.status === 'success' ? result.data : null)
  const monetary = insight ? formatBusinessImpact(insight.businessImpact) : { exposure: null, estimatedImpact: null }

  const { approveTarget, rejectTarget, busy, openApprove, openReject, closeApprove, closeReject, confirmApprove, confirmReject, restoreFocus } =
    useInsightReviewActions((updated) => setLocalInsight(updated))

  async function handleUndo() {
    if (!insight) return
    const reverted = await insights.undo(insight.id)
    setLocalInsight(reverted)
    showToast({ message: `Review decision for "${reverted.title}" was undone.` })
  }

  return (
    <div>
      <Button variant="ghost" size="sm" className="mb-3 -ml-2" onClick={() => navigate('/insights')}>
        <ArrowLeft className="size-4" />
        Back to insights
      </Button>

      {result.status === 'loading' ? <LoadingState rows={5} label="Loading insight" /> : null}
      {result.status === 'error' ? <ErrorState message={result.error.message} onRetry={result.reload} /> : null}

      {insight ? (
        <>
          <PageHeader
            title={insight.title}
            description={`${insight.companyName} · Generated ${formatDate(insight.generatedAt, { withTime: true })} · For ${PERSONA_LABELS[insight.persona]}`}
            actions={
              insight.reviewStatus === 'pending' ? (
                <div className="flex items-center gap-2">
                  <Button variant="outline" size="sm" onClick={() => openReject(insight)}>
                    <X className="size-4" />
                    Reject
                  </Button>
                  <Button size="sm" onClick={() => openApprove(insight)}>
                    <Check className="size-4" />
                    Approve
                  </Button>
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <ReviewStatusBadge status={insight.reviewStatus} />
                  <Button variant="ghost" size="sm" onClick={handleUndo} aria-label="Undo review decision">
                    <Undo2 className="size-4" />
                    Undo
                  </Button>
                </div>
              )
            }
          />

          <div className="mb-6 flex flex-wrap items-center gap-2">
            <CategoryBadge category={insight.category} />
            <SubtypeBadge subtype={insight.subtype} />
            {insight.reviewStatus === 'pending' ? <ReviewStatusBadge status={insight.reviewStatus} /> : null}
            <Link to={`/requests/${insight.requestId}`} className="text-xs font-medium text-accent hover:underline">
              View source request ({insight.requestId})
            </Link>
          </div>

          <div className="grid grid-cols-2 gap-3 sm:max-w-lg sm:grid-cols-4">
            <ScoreBlock label="Priority">
              <PriorityBadge priority={insight.priority} />
            </ScoreBlock>
            <ScoreBlock label="Confidence">{insight.confidence}%</ScoreBlock>
            {monetary.exposure !== null ? <ScoreBlock label="Credit exposure">{monetary.exposure}</ScoreBlock> : null}
            {monetary.estimatedImpact !== null ? (
              <ScoreBlock label="Business impact">{monetary.estimatedImpact}</ScoreBlock>
            ) : null}
          </div>
          {insight.businessImpact.description ? (
            <p className="mt-2 text-xs text-ink-faint">{insight.businessImpact.description}</p>
          ) : null}

          <div className="mt-6 grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Concise finding</CardTitle>
              </CardHeader>
              <CardContent className="text-sm leading-relaxed text-ink-muted">{insight.finding}</CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Why it matters</CardTitle>
              </CardHeader>
              <CardContent className="text-sm leading-relaxed text-ink-muted">{insight.whyItMatters}</CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Recommended action</CardTitle>
              </CardHeader>
              <CardContent className="text-sm leading-relaxed text-ink-muted">{insight.recommendedAction}</CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Confidence rationale</CardTitle>
              </CardHeader>
              <CardContent className="text-sm leading-relaxed text-ink-muted">{insight.confidenceRationale}</CardContent>
            </Card>
          </div>

          <Card className="mt-4">
            <CardHeader className="flex-row items-center justify-between gap-2 space-y-0">
              <CardTitle>Supporting evidence ({insight.evidence.length})</CardTitle>
              {new Set(insight.evidence.map((item) => item.sourceType)).size > 1 ? (
                <Badge variant="accent">Cross-source insight</Badge>
              ) : null}
            </CardHeader>
            <CardContent className="p-0">
              <ul>
                {insight.evidence.map((item, index) => (
                  <li key={item.id}>
                    {index > 0 ? <Separator /> : null}
                    <div className="flex items-start gap-3 px-5 py-4">
                      <FileText className="mt-0.5 size-4 shrink-0 text-ink-faint" />
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2 text-xs text-ink-faint">
                          <span className="font-medium text-ink-muted">{AGENT_LABELS[item.sourceAgent]}</span>
                          <span>·</span>
                          <span className="font-mono">{item.evidenceCode}</span>
                          <span>·</span>
                          <span>{formatDate(item.date)}</span>
                          <EvidenceSourceBadge sourceType={item.sourceType} />
                        </div>
                        <p className="mt-1 text-sm font-medium text-ink">{item.label}</p>
                        <p className="mt-0.5 text-sm text-ink-muted">{item.detail}</p>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>

          <Card className="mt-4">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <History className="size-4" />
                Review history
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <ul>
                {[...insight.reviewHistory].reverse().map((event, index) => (
                  <li key={event.id}>
                    {index > 0 ? <Separator /> : null}
                    <div className="flex items-center justify-between gap-3 px-5 py-3 text-sm">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-ink">{REVIEW_EVENT_LABELS[event.action]}</span>
                        {event.reason ? <span className="text-ink-faint">— {REJECT_REASON_LABELS[event.reason]}</span> : null}
                        <span className="text-ink-faint">by {event.actor}</span>
                      </div>
                      <span className="whitespace-nowrap text-xs text-ink-faint">{formatDate(event.timestamp, { withTime: true })}</span>
                    </div>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </>
      ) : null}

      <ApproveConfirmDialog
        insight={approveTarget}
        busy={busy}
        onOpenChange={(open) => !open && closeApprove()}
        onConfirm={confirmApprove}
        onCloseAutoFocus={(e) => {
          e.preventDefault()
          restoreFocus()
        }}
      />
      <RejectReasonDialog
        insight={rejectTarget}
        busy={busy}
        onOpenChange={(open) => !open && closeReject()}
        onConfirm={confirmReject}
        onCloseAutoFocus={(e) => {
          e.preventDefault()
          restoreFocus()
        }}
      />
    </div>
  )
}

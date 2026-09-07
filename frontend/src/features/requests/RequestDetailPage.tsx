import { useEffect, useState } from 'react'
import { ArrowLeft, Square, Trash2 } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { useRepositories } from '@/app/RepositoriesProvider'
import { useToast } from '@/app/ToastProvider'
import { useAsync } from '@/hooks/useAsync'
import { formatDate } from '@/lib/format'
import { PageHeader } from '@/components/layout/PageHeader'
import { LoadingState } from '@/components/states/LoadingState'
import { ErrorState } from '@/components/states/ErrorState'
import { EmptyState } from '@/components/states/EmptyState'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import {
  RequestStatusBadge,
  RequestStageBadge,
  ReviewDecisionBadge,
  CategoryBadge,
  CATEGORY_LABELS,
  ReviewStatusBadge,
} from '@/components/domain/badges'
import { AGENT_LABELS } from '@/features/assistant/agentLabels'
import { DeleteRequestConfirmDialog } from '@/features/requests/DeleteRequestConfirmDialog'
import { StopRequestConfirmDialog } from '@/features/requests/StopRequestConfirmDialog'
import type { RequestStage, ResearchRequest } from '@/api/types'

/** Provider-neutral display names for externalResearch.providers -- replaces
 * the old "EDGAR" terminology now that external_data_agent is backed by
 * FMP/Alpha Vantage/FRED instead of SEC EDGAR. */
const PROVIDER_LABELS: Record<string, string> = {
  fmp: 'Financial Modeling Prep',
  alpha_vantage: 'Alpha Vantage',
  fred: 'FRED',
}

/** Progress-card label for each in-flight stage -- a slightly more
 * descriptive companion to RequestStageBadge for the one place it's shown
 * alongside a percentage. */
const REQUEST_STAGE_PROGRESS_LABEL: Record<RequestStage, string> = {
  queued: 'Waiting to start',
  // The backend doesn't yet expose per-provider progress (loading internal
  // context, building the external research plan, retrieving FMP/Alpha
  // Vantage/FRED data individually) through this stage field -- see
  // RequestDetailPage's own "Provider status" note below. This label
  // describes what's actually happening without implying more granularity
  // than the API currently reports.
  researching: 'Gathering internal context and external market data',
  waiting_for_sources: 'Waiting for sources',
  synthesizing: 'Synthesizing insights',
  reviewing: 'Reviewing insights',
  revising_synthesis: 'Revising synthesis',
  revising_research: 'Revising research',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
}

export function RequestDetailPage() {
  const { requestId } = useParams<{ requestId: string }>()
  const { requests, insights } = useRepositories()
  const { showToast } = useToast()
  const navigate = useNavigate()
  const result = useAsync(() => requests.getById(requestId!), [requests, requestId])
  const { reload: reloadRequest } = result
  const [stopTarget, setStopTarget] = useState<ResearchRequest | null>(null)
  const [stopping, setStopping] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<ResearchRequest | null>(null)
  const [deleting, setDeleting] = useState(false)

  async function handleConfirmStop() {
    if (!stopTarget) return
    setStopping(true)
    try {
      await requests.cancel(stopTarget.requestId)
      setStopTarget(null)
      reloadRequest()
      showToast({ message: `Request ${stopTarget.requestId} stopped.` })
    } catch (error) {
      showToast({ message: error instanceof Error ? error.message : 'Failed to stop the request.' })
    } finally {
      setStopping(false)
    }
  }

  async function handleConfirmDelete() {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await requests.remove(deleteTarget.requestId)
      showToast({ message: `Request ${deleteTarget.requestId} deleted.` })
      navigate('/requests')
    } catch (error) {
      showToast({ message: error instanceof Error ? error.message : 'Failed to delete the request.' })
      setDeleting(false)
      setDeleteTarget(null)
    }
  }
  const insightsResult = useAsync(
    () => insights.list({ requestId, pageSize: 100 }),
    [insights, requestId],
  )
  const { reload: reloadInsights } = insightsResult

  // A request created against the live backend (see .env.local /
  // VITE_API_BASE_URL) starts queued/running while the orchestrator is
  // actually working; poll until it reaches a terminal state so the
  // banker doesn't have to manually refresh to see it finish. Insights are
  // synthesized server-side before the request flips to a terminal status
  // (see src/insights_assistant/api/server.py's _run_request), so both
  // reloads fire together on every tick -- reloading only the request would
  // leave resultInsights empty forever, since insightsResult was fetched
  // once on mount, before any insights existed. `reloadRequest`/
  // `reloadInsights` are stable across renders (see useAsync), so this
  // effect only resets when the in-flight status itself actually changes.
  const isInFlight = result.status === 'success' && (result.data.status === 'queued' || result.data.status === 'running')
  useEffect(() => {
    if (!isInFlight) return
    const timer = setInterval(() => {
      reloadRequest()
      reloadInsights()
    }, 4000)
    return () => clearInterval(timer)
  }, [isInFlight, reloadRequest, reloadInsights])

  const resultInsights =
    insightsResult.status === 'success' && result.status === 'success'
      ? insightsResult.data.items.filter((i) => result.data.resultInsightIds.includes(i.id))
      : []

  // Derived directly from the fetched insights, never from a separately
  // stored total, so these counts cannot drift out of sync with the list
  // below them.
  const reviewCounts = {
    generated: resultInsights.length,
    approved: resultInsights.filter((i) => i.reviewStatus === 'approved').length,
    rejected: resultInsights.filter((i) => i.reviewStatus === 'rejected').length,
    pending: resultInsights.filter((i) => i.reviewStatus === 'pending').length,
  }

  return (
    <div>
      <Button variant="ghost" size="sm" className="mb-3 -ml-2" onClick={() => navigate('/requests')}>
        <ArrowLeft className="size-4" />
        Back to requests
      </Button>

      {result.status === 'loading' ? <LoadingState rows={5} label="Loading request" /> : null}
      {result.status === 'error' ? <ErrorState message={result.error.message} onRetry={result.reload} /> : null}

      {result.status === 'success' ? (
        <>
          <PageHeader
            title={`Request ${result.data.requestId}`}
            description={`Requested by ${result.data.requestedBy} · Created ${formatDate(result.data.createdAt, { withTime: true })}`}
            actions={
              <div className="flex flex-wrap items-center gap-2">
                <RequestStatusBadge status={result.data.status} />
                {result.data.currentStage ? <RequestStageBadge stage={result.data.currentStage} /> : null}
                {isInFlight ? (
                  <Button variant="outline" size="sm" onClick={() => setStopTarget(result.data)}>
                    <Square className="size-4" />
                    Stop generation
                  </Button>
                ) : null}
                <Button variant="outline" size="sm" onClick={() => setDeleteTarget(result.data)}>
                  <Trash2 className="size-4" />
                  Delete
                </Button>
              </div>
            }
          />

          {(result.data.status === 'running' || result.data.status === 'queued') ? (
            <Card className="mb-4">
              <CardContent className="flex flex-col gap-2 p-5">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-ink-muted">
                    {result.data.currentStage ? REQUEST_STAGE_PROGRESS_LABEL[result.data.currentStage] : 'Research in progress'}
                  </span>
                  <span className="font-medium text-ink">{result.data.progressPct}%</span>
                </div>
                <Progress value={result.data.progressPct} aria-label="Request progress" />
              </CardContent>
            </Card>
          ) : null}

          {(result.data.requestVersion !== undefined || result.data.reviewDecision) ? (
            <Card className="mb-4">
              <CardHeader>
                <CardTitle>Workflow</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-3 text-sm">
                <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs text-ink-muted sm:grid-cols-4">
                  <span>
                    Request version <span className="font-medium text-ink">{result.data.requestVersion ?? 1}</span>
                  </span>
                  <span>
                    Package version <span className="font-medium text-ink">{result.data.packageVersion ?? 1}</span>
                  </span>
                  <span>
                    Research revision{' '}
                    <span className="font-medium text-ink">
                      {(result.data.researchRevisionCount ?? 0) > 0 ? 'used' : 'not used'}
                    </span>
                  </span>
                  <span>
                    Synthesis revision{' '}
                    <span className="font-medium text-ink">
                      {(result.data.synthesisRevisionCount ?? 0) > 0 ? 'used' : 'not used'}
                    </span>
                  </span>
                </div>
                {result.data.reviewDecision ? (
                  <div className="flex flex-col gap-1 border-t border-border pt-3">
                    <div className="flex items-center gap-2">
                      <span className="text-ink-muted">Reviewer decision</span>
                      <ReviewDecisionBadge decision={result.data.reviewDecision} />
                    </div>
                    {/* reviewComments is the Reviewer's own audit-text output
                        (agents/reviewer.py) -- concise and decision-oriented
                        by design, never raw model reasoning. */}
                    {result.data.reviewComments ? (
                      <p className="text-ink-muted">{result.data.reviewComments}</p>
                    ) : null}
                  </div>
                ) : null}
              </CardContent>
            </Card>
          ) : null}

          {result.data.status === 'failed' ? (
            <Card className="mb-4 border-danger/30 bg-danger-soft">
              <CardHeader>
                <CardTitle>Terminal error</CardTitle>
              </CardHeader>
              <CardContent className="p-5 pt-0 text-sm text-danger">{result.data.errorMessage}</CardContent>
            </Card>
          ) : null}

          {result.data.sourceErrors && result.data.sourceErrors.length > 0 ? (
            <Card className="mb-4">
              <CardHeader>
                <CardTitle>Source status</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-2">
                {result.data.sourceErrors.map((sourceError) => (
                  <div
                    key={sourceError.id}
                    className="flex flex-col gap-1 rounded-md border border-danger/20 bg-danger-soft px-3 py-2 text-sm"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-medium text-ink">{AGENT_LABELS[sourceError.source]}</span>
                      <Badge variant={sourceError.code === 'timed_out' ? 'warning' : 'danger'}>
                        {sourceError.code === 'timed_out' ? 'Timed out' : 'Failed'}
                      </Badge>
                    </div>
                    <span className="text-xs text-ink-muted">{sourceError.message}</span>
                  </div>
                ))}
              </CardContent>
            </Card>
          ) : null}

          {result.data.unmetRequirements && result.data.unmetRequirements.length > 0 ? (
            <Card className="mb-4 border-warning/30 bg-warning-soft">
              <CardHeader>
                <CardTitle>Unmet requirements</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-2 text-sm text-ink-muted">
                {result.data.unmetRequirements.map((unmet, index) => (
                  <p key={index}>
                    Requested {unmet.requestedCount}
                    {unmet.category ? ` ${CATEGORY_LABELS[unmet.category]}` : ''} insight
                    {unmet.requestedCount === 1 ? '' : 's'}, got {unmet.actualCount} — {unmet.reason}
                  </p>
                ))}
              </CardContent>
            </Card>
          ) : null}

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Company scope</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-1.5">
                {result.data.companyScope.companies.map((c) => (
                  <Badge key={c.companyId} variant="outline">
                    {c.companyName} ({c.ticker})
                  </Badge>
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>External research</CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-ink-muted">
                {(result.data.externalResearch.enabled ?? result.data.externalResearch.edgarEnabled) ? (
                  <p>
                    External market research enabled ·{' '}
                    {(result.data.externalResearch.providers ?? ['fmp', 'alpha_vantage', 'fred'])
                      .map((p) => PROVIDER_LABELS[p] ?? p)
                      .join(', ')}
                  </p>
                ) : (
                  <p>External market research disabled</p>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Internal data domains</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-1.5">
                {result.data.internalResearch.dataDomains.map((d) => (
                  <Badge key={d.domainId} variant="outline">
                    {d.label}
                  </Badge>
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Insight requirements</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-2 text-sm text-ink-muted">
                <p>
                  {result.data.insightRequirements.totalCount} total, up to{' '}
                  {result.data.insightRequirements.maxInsightsPerCompany} per company
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {result.data.insightRequirements.categories.map((c) => (
                    <CategoryBadge key={c.categoryId} category={c.categoryId} />
                  ))}
                </div>
                <p className="text-xs text-ink-faint">
                  Ranked by {result.data.insightRequirements.rankingCriteria.join(', ')}
                </p>
              </CardContent>
            </Card>
          </div>

          <Card className="mt-4">
            <CardHeader>
              <CardTitle>Search prompt</CardTitle>
            </CardHeader>
            <CardContent className="text-sm text-ink-muted">{result.data.internalResearch.generalSearchPrompt}</CardContent>
          </Card>

          {result.data.resultSummary ? (
            <Card className="mt-4">
              <CardHeader>
                <CardTitle>Research findings</CardTitle>
              </CardHeader>
              <CardContent className="whitespace-pre-wrap text-sm text-ink-muted">{result.data.resultSummary}</CardContent>
            </Card>
          ) : null}

          {result.data.auditEvents && result.data.auditEvents.length > 0 ? (
            <Card className="mt-4">
              <CardHeader>
                <CardTitle>Version history</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-3">
                {result.data.auditEvents.map((event, index) => (
                  <div key={index} className="flex flex-col gap-0.5 border-l-2 border-border-strong pl-3 text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium text-ink">{event.message}</span>
                      <span className="text-xs text-ink-faint">{formatDate(event.occurredAt, { withTime: true })}</span>
                    </div>
                    {event.detail?.comments ? (
                      <p className="text-xs text-ink-muted">{event.detail.comments}</p>
                    ) : null}
                  </div>
                ))}
              </CardContent>
            </Card>
          ) : null}

          <div className="mt-6">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-ink">Resulting insights</h2>
              {insightsResult.status === 'success' && resultInsights.length > 0 ? (
                <div className="flex flex-wrap items-center gap-3 text-xs text-ink-muted">
                  <span>{reviewCounts.generated} generated</span>
                  <span aria-hidden="true">·</span>
                  <span>{reviewCounts.approved} approved</span>
                  <span aria-hidden="true">·</span>
                  <span>{reviewCounts.rejected} rejected</span>
                  <span aria-hidden="true">·</span>
                  <span>{reviewCounts.pending} pending</span>
                </div>
              ) : null}
            </div>
            {insightsResult.status === 'loading' ? <LoadingState rows={2} /> : null}
            {resultInsights.length === 0 && insightsResult.status === 'success' ? (
              <EmptyState
                title="No insights generated yet"
                description="Insights will appear here once this request finishes running."
              />
            ) : null}
            <div className="flex flex-col gap-2">
              {resultInsights.map((insight) => (
                <Link
                  key={insight.id}
                  to={`/insights/${insight.id}`}
                  className="flex items-center justify-between gap-3 rounded-md border border-border bg-surface-raised px-4 py-3 text-sm hover:bg-surface-hover"
                >
                  <span className="font-medium text-ink">{insight.title}</span>
                  <div className="flex shrink-0 items-center gap-2">
                    <ReviewStatusBadge status={insight.reviewStatus} />
                    <CategoryBadge category={insight.category} />
                  </div>
                </Link>
              ))}
            </div>
          </div>
        </>
      ) : null}

      <StopRequestConfirmDialog
        request={stopTarget}
        busy={stopping}
        onOpenChange={(open) => !open && setStopTarget(null)}
        onConfirm={handleConfirmStop}
      />

      <DeleteRequestConfirmDialog
        request={deleteTarget}
        busy={deleting}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        onConfirm={handleConfirmDelete}
      />
    </div>
  )
}

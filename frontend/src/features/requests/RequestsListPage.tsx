import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ListChecks, Plus, Trash2 } from 'lucide-react'

import { useRepositories } from '@/app/RepositoriesProvider'
import { useToast } from '@/app/ToastProvider'
import { useAsync } from '@/hooks/useAsync'
import { formatDate } from '@/lib/format'
import { PageHeader } from '@/components/layout/PageHeader'
import { LoadingState } from '@/components/states/LoadingState'
import { ErrorState } from '@/components/states/ErrorState'
import { EmptyState } from '@/components/states/EmptyState'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { RequestStatusBadge } from '@/components/domain/badges'
import { DeleteRequestConfirmDialog } from '@/features/requests/DeleteRequestConfirmDialog'
import type { ResearchRequest } from '@/api/types'

export function RequestsListPage() {
  const { requests } = useRepositories()
  const { showToast } = useToast()
  const navigate = useNavigate()
  const result = useAsync(() => requests.list(), [requests])
  const [deleteTarget, setDeleteTarget] = useState<ResearchRequest | null>(null)
  const [deleting, setDeleting] = useState(false)

  async function handleConfirmDelete() {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await requests.remove(deleteTarget.requestId)
      setDeleteTarget(null)
      result.reload()
      showToast({ message: `Request ${deleteTarget.requestId} deleted.` })
    } catch (error) {
      showToast({ message: error instanceof Error ? error.message : 'Failed to delete the request.' })
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div>
      <PageHeader
        title="Research requests"
        description="Scope and track banker-initiated research jobs that generate insights."
        actions={
          <Button size="sm" onClick={() => navigate('/requests/new')}>
            <Plus className="size-4" />
            New request
          </Button>
        }
      />

      {result.status === 'loading' ? <LoadingState rows={4} label="Loading requests" /> : null}
      {result.status === 'error' ? <ErrorState message={result.error.message} onRetry={result.reload} /> : null}
      {result.status === 'success' && result.data.length === 0 ? (
        <EmptyState
          icon={ListChecks}
          title="No research requests yet"
          description="Start a guided request to scope a company research job for the assistant."
          action={{ label: 'New request', onClick: () => navigate('/requests/new') }}
        />
      ) : null}
      {result.status === 'success' && result.data.length > 0 ? (
        <div className="flex flex-col gap-3">
          {result.data.map((request) => (
            <Card key={request.requestId} className="relative transition-colors hover:border-accent-soft-border hover:bg-surface-hover">
              <Link to={`/requests/${request.requestId}`} className="block">
                <CardContent className="flex flex-col gap-3 p-5">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-xs text-ink-faint">{request.requestId}</span>
                        <RequestStatusBadge status={request.status} />
                      </div>
                      <p className="mt-1.5 text-sm font-medium text-ink">
                        {request.companyScope.companies.map((c) => c.companyName).join(', ')}
                      </p>
                      <p className="mt-1 text-xs text-ink-faint">Created {formatDate(request.createdAt, { withTime: true })}</p>
                    </div>
                    <span className="pr-8 text-xs text-ink-faint">
                      {request.resultInsightIds.length} / {request.insightRequirements.totalCount} insights
                    </span>
                  </div>
                  {request.status === 'running' || request.status === 'queued' ? (
                    <Progress value={request.progressPct} aria-label="Request progress" />
                  ) : null}
                  {request.status === 'failed' && request.errorMessage ? (
                    <p className="text-xs text-danger">{request.errorMessage}</p>
                  ) : null}
                </CardContent>
              </Link>
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Delete request ${request.requestId}`}
                className="absolute right-3 top-3 text-ink-faint hover:text-danger"
                onClick={(event) => {
                  event.preventDefault()
                  event.stopPropagation()
                  setDeleteTarget(request)
                }}
              >
                <Trash2 className="size-4" />
              </Button>
            </Card>
          ))}
        </div>
      ) : null}

      <DeleteRequestConfirmDialog
        request={deleteTarget}
        busy={deleting}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        onConfirm={handleConfirmDelete}
      />
    </div>
  )
}

import { useMemo, useState } from 'react'
import { ChevronLeft, ChevronRight, Lightbulb, Search, SlidersHorizontal } from 'lucide-react'

import type { Insight, InsightCategory, InsightPersona, InsightPriority, ReviewStatus } from '@/api/types'
import type { InsightsQuery } from '@/api/repositories/types'
import { useRepositories } from '@/app/RepositoriesProvider'
import { useAsync } from '@/hooks/useAsync'
import { PageHeader } from '@/components/layout/PageHeader'
import { LoadingState } from '@/components/states/LoadingState'
import { ErrorState } from '@/components/states/ErrorState'
import { EmptyState } from '@/components/states/EmptyState'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ApproveConfirmDialog } from '@/features/insights/ApproveConfirmDialog'
import { RejectReasonDialog } from '@/features/insights/RejectReasonDialog'
import { InsightTableRow } from '@/features/insights/InsightTableRow'
import { useInsightReviewActions } from '@/features/insights/useInsightReviewActions'
import { useToast } from '@/app/ToastProvider'
import {
  CATEGORY_OPTIONS,
  CONFIDENCE_OPTIONS,
  EVIDENCE_SOURCE_OPTIONS,
  PERSONA_OPTIONS,
  PRIORITY_OPTIONS,
  REVIEW_STATUS_OPTIONS,
  SORT_OPTIONS,
  confidenceTierToRange,
  type ConfidenceTier,
} from '@/features/insights/filterOptions'

const PAGE_SIZE = 10

interface FiltersState {
  reviewStatus: ReviewStatus | 'all'
  category: InsightCategory | 'all'
  companyId: string
  persona: InsightPersona | 'all'
  priority: InsightPriority | 'all'
  confidenceTier: ConfidenceTier
  dateFrom: string
  dateTo: string
  requestId: string
  evidenceSourceType: 'all' | 'internal' | 'external'
  search: string
}

const DEFAULT_FILTERS: FiltersState = {
  reviewStatus: 'all',
  category: 'all',
  companyId: 'all',
  persona: 'all',
  priority: 'all',
  confidenceTier: 'all',
  dateFrom: '',
  dateTo: '',
  requestId: 'all',
  evidenceSourceType: 'all',
  search: '',
}

function isActive(filters: FiltersState): boolean {
  return (
    filters.reviewStatus !== 'all' ||
    filters.category !== 'all' ||
    filters.companyId !== 'all' ||
    filters.persona !== 'all' ||
    filters.priority !== 'all' ||
    filters.confidenceTier !== 'all' ||
    filters.dateFrom !== '' ||
    filters.dateTo !== '' ||
    filters.requestId !== 'all' ||
    filters.evidenceSourceType !== 'all' ||
    filters.search.trim() !== ''
  )
}

export function InsightsListPage() {
  const { insights, companies } = useRepositories()
  const { showToast } = useToast()

  const [filters, setFilters] = useState<FiltersState>(DEFAULT_FILTERS)
  const [sortKey, setSortKey] = useState(SORT_OPTIONS[0].value)
  const [page, setPage] = useState(1)

  const companiesResult = useAsync(() => companies.list(), [companies])
  const requestIdsResult = useAsync(() => insights.listRequestIds(), [insights])

  const query: InsightsQuery = useMemo(() => {
    const { min, max } = confidenceTierToRange(filters.confidenceTier)
    const sortOption = SORT_OPTIONS.find((o) => o.value === sortKey) ?? SORT_OPTIONS[0]
    return {
      reviewStatus: filters.reviewStatus === 'all' ? undefined : filters.reviewStatus,
      category: filters.category === 'all' ? undefined : filters.category,
      companyId: filters.companyId === 'all' ? undefined : filters.companyId,
      persona: filters.persona === 'all' ? undefined : filters.persona,
      priority: filters.priority === 'all' ? undefined : filters.priority,
      confidenceMin: min,
      confidenceMax: max,
      dateFrom: filters.dateFrom || undefined,
      dateTo: filters.dateTo || undefined,
      requestId: filters.requestId === 'all' ? undefined : filters.requestId,
      evidenceSourceType: filters.evidenceSourceType === 'all' ? undefined : filters.evidenceSourceType,
      search: filters.search.trim() || undefined,
      sortField: sortOption.field,
      sortDirection: sortOption.direction,
      page,
      pageSize: PAGE_SIZE,
    }
  }, [filters, sortKey, page])

  const result = useAsync(() => insights.list(query), [insights, query])
  const filtersActive = isActive(filters)

  function updateFilter<K extends keyof FiltersState>(key: K, value: FiltersState[K]) {
    setFilters((prev) => ({ ...prev, [key]: value }))
    setPage(1)
  }

  function clearFilters() {
    setFilters(DEFAULT_FILTERS)
    setPage(1)
  }

  const { approveTarget, rejectTarget, busy, openApprove, openReject, closeApprove, closeReject, confirmApprove, confirmReject, restoreFocus } =
    useInsightReviewActions((_updated: Insight) => result.reload())

  async function handleUndo(insight: Insight) {
    const reverted = await insights.undo(insight.id)
    showToast({ message: `Review decision for "${reverted.title}" was undone.` })
    result.reload()
  }

  const totalPages = result.status === 'success' ? Math.max(1, Math.ceil(result.data.total / PAGE_SIZE)) : 1

  return (
    <div>
      <PageHeader
        title="Insights"
        description="Synthesized findings from the research pipeline, ranked and ready for banker review."
      />

      <Card className="mb-5">
        <CardContent className="flex flex-col gap-4 p-4">
          <div className="flex items-center gap-2 text-sm font-medium text-ink-muted">
            <SlidersHorizontal className="size-4" />
            Filters
          </div>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            <div>
              <Label className="mb-1.5 block text-xs font-medium text-ink-muted">Review status</Label>
              <Select value={filters.reviewStatus} onValueChange={(v) => updateFilter('reviewStatus', v as ReviewStatus | 'all')}>
                <SelectTrigger aria-label="Filter by review status">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {REVIEW_STATUS_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label className="mb-1.5 block text-xs font-medium text-ink-muted">Category</Label>
              <Select value={filters.category} onValueChange={(v) => updateFilter('category', v as InsightCategory | 'all')}>
                <SelectTrigger aria-label="Filter by category">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CATEGORY_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label className="mb-1.5 block text-xs font-medium text-ink-muted">Company</Label>
              <Select value={filters.companyId} onValueChange={(v) => updateFilter('companyId', v)}>
                <SelectTrigger aria-label="Filter by company">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All companies</SelectItem>
                  {companiesResult.status === 'success'
                    ? companiesResult.data.map((c) => (
                        <SelectItem key={c.companyId} value={c.companyId}>
                          {c.companyName}
                        </SelectItem>
                      ))
                    : null}
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label className="mb-1.5 block text-xs font-medium text-ink-muted">Persona</Label>
              <Select value={filters.persona} onValueChange={(v) => updateFilter('persona', v as InsightPersona | 'all')}>
                <SelectTrigger aria-label="Filter by persona">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PERSONA_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label className="mb-1.5 block text-xs font-medium text-ink-muted">Priority</Label>
              <Select value={filters.priority} onValueChange={(v) => updateFilter('priority', v as InsightPriority | 'all')}>
                <SelectTrigger aria-label="Filter by priority">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PRIORITY_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label className="mb-1.5 block text-xs font-medium text-ink-muted">Confidence</Label>
              <Select value={filters.confidenceTier} onValueChange={(v) => updateFilter('confidenceTier', v as ConfidenceTier)}>
                <SelectTrigger aria-label="Filter by confidence">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CONFIDENCE_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label className="mb-1.5 block text-xs font-medium text-ink-muted">Request ID</Label>
              <Select value={filters.requestId} onValueChange={(v) => updateFilter('requestId', v)}>
                <SelectTrigger aria-label="Filter by request ID">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All requests</SelectItem>
                  {requestIdsResult.status === 'success'
                    ? requestIdsResult.data.map((id) => (
                        <SelectItem key={id} value={id}>
                          {id}
                        </SelectItem>
                      ))
                    : null}
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label className="mb-1.5 block text-xs font-medium text-ink-muted">Evidence source</Label>
              <Select
                value={filters.evidenceSourceType}
                onValueChange={(v) => updateFilter('evidenceSourceType', v as 'all' | 'internal' | 'external')}
              >
                <SelectTrigger aria-label="Filter by evidence source type">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {EVIDENCE_SOURCE_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label htmlFor="dateFrom" className="mb-1.5 block text-xs font-medium text-ink-muted">
                Generated from
              </Label>
              <Input id="dateFrom" type="date" value={filters.dateFrom} onChange={(e) => updateFilter('dateFrom', e.target.value)} />
            </div>

            <div>
              <Label htmlFor="dateTo" className="mb-1.5 block text-xs font-medium text-ink-muted">
                Generated to
              </Label>
              <Input id="dateTo" type="date" value={filters.dateTo} onChange={(e) => updateFilter('dateTo', e.target.value)} />
            </div>

            <div className="col-span-2 sm:col-span-1">
              <Label htmlFor="search" className="mb-1.5 block text-xs font-medium text-ink-muted">
                Search
              </Label>
              <div className="relative">
                <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-faint" />
                <Input
                  id="search"
                  value={filters.search}
                  onChange={(e) => updateFilter('search', e.target.value)}
                  placeholder="Search insights…"
                  className="pl-9"
                />
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3">
            <Button variant="ghost" size="sm" onClick={clearFilters} disabled={!filtersActive}>
              Clear filters
            </Button>
            <div className="flex items-center gap-2">
              <Label htmlFor="sort" className="text-xs font-medium text-ink-muted">
                Sort by
              </Label>
              <Select value={sortKey} onValueChange={setSortKey}>
                <SelectTrigger id="sort" className="w-56" aria-label="Sort insights">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SORT_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardContent>
      </Card>

      {result.status === 'loading' ? <LoadingState rows={6} label="Loading insights" /> : null}
      {result.status === 'error' ? <ErrorState message={result.error.message} onRetry={result.reload} /> : null}

      {result.status === 'success' && result.data.total === 0 ? (
        filtersActive ? (
          <EmptyState
            icon={Search}
            title="No insights match your filters"
            description="Try widening the date range or clearing some filters."
            action={{ label: 'Clear filters', onClick: clearFilters }}
          />
        ) : (
          <EmptyState icon={Lightbulb} title="No insights yet" description="Insights will appear here once a research request completes." />
        )
      ) : null}

      {result.status === 'success' && result.data.total > 0 ? (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Title</TableHead>
                  <TableHead>Company</TableHead>
                  <TableHead>Category / Subtype</TableHead>
                  <TableHead>Priority</TableHead>
                  <TableHead>Confidence</TableHead>
                  <TableHead>Business impact</TableHead>
                  <TableHead>Generated</TableHead>
                  <TableHead>Request ID</TableHead>
                  <TableHead>Review status</TableHead>
                  <TableHead>Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {result.data.items.map((insight) => (
                  <InsightTableRow
                    key={insight.id}
                    insight={insight}
                    onApprove={openApprove}
                    onReject={openReject}
                    onUndo={handleUndo}
                  />
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ) : null}

      {result.status === 'success' && result.data.total > 0 ? (
        <div className="mt-4 flex items-center justify-between text-sm text-ink-muted">
          <span>
            Showing {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, result.data.total)} of {result.data.total}
          </span>
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1}>
              <ChevronLeft className="size-4" />
              Previous
            </Button>
            <span>
              Page {page} of {totalPages}
            </span>
            <Button variant="secondary" size="sm" onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page >= totalPages}>
              Next
              <ChevronRight className="size-4" />
            </Button>
          </div>
        </div>
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

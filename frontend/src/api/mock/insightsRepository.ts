import type { Insight, ReviewEvent } from '@/api/types'
import type { InsightsPage, InsightsQuery, InsightsRepository } from '@/api/repositories/types'
import { ApiError } from '@/api/client'
import { delay } from '@/api/mock/latency'
import { insights } from '@/api/mock/insights'
import { defaultPreferences } from '@/api/mock/preferences'

const store: Insight[] = insights.map((insight) => ({
  ...insight,
  reviewHistory: [...insight.reviewHistory],
  evidence: [...insight.evidence],
}))

function matches(insight: Insight, query: InsightsQuery): boolean {
  if (query.reviewStatus && insight.reviewStatus !== query.reviewStatus) return false
  if (query.category && insight.category !== query.category) return false
  if (query.companyId && insight.companyId !== query.companyId) return false
  if (query.persona && insight.persona !== query.persona) return false
  if (query.priority && insight.priority !== query.priority) return false
  if (query.confidenceMin !== undefined && insight.confidence < query.confidenceMin) return false
  if (query.confidenceMax !== undefined && insight.confidence > query.confidenceMax) return false
  if (query.requestId && insight.requestId !== query.requestId) return false
  if (query.evidenceSourceType) {
    const hasSource = insight.evidence.some((e) => e.sourceType === query.evidenceSourceType)
    if (!hasSource) return false
  }
  if (query.dateFrom || query.dateTo) {
    const generatedDate = insight.generatedAt.slice(0, 10)
    if (query.dateFrom && generatedDate < query.dateFrom) return false
    if (query.dateTo && generatedDate > query.dateTo) return false
  }
  if (query.search) {
    const needle = query.search.toLowerCase()
    const haystack = `${insight.title} ${insight.finding} ${insight.companyName}`.toLowerCase()
    if (!haystack.includes(needle)) return false
  }
  return true
}

const PRIORITY_RANK: Record<Insight['priority'], number> = { critical: 4, high: 3, medium: 2, low: 1 }

function sortInsights(items: Insight[], query: InsightsQuery): Insight[] {
  const field = query.sortField ?? 'generatedAt'
  const direction = query.sortDirection ?? 'desc'
  const factor = direction === 'asc' ? 1 : -1

  return [...items].sort((a, b) => {
    switch (field) {
      case 'priority':
        return (PRIORITY_RANK[a.priority] - PRIORITY_RANK[b.priority]) * factor
      case 'confidence':
        return (a.confidence - b.confidence) * factor
      case 'businessImpact':
        return (a.businessImpact.amountUsd - b.businessImpact.amountUsd) * factor
      case 'generatedAt':
      default:
        return a.generatedAt.localeCompare(b.generatedAt) * factor
    }
  })
}

function findOrThrow(insightId: string): Insight {
  const found = store.find((i) => i.id === insightId)
  if (!found) throw new ApiError(`No insight found for id ${insightId}`, 404)
  return found
}

/**
 * Public reads must never hand out the live store object: callers (React
 * state, "before" snapshots in tests) would otherwise alias the same array
 * references and appear to mutate retroactively when a later approve/reject
 * call reassigns reviewStatus/reviewHistory on that same object.
 */
function clone(insight: Insight): Insight {
  return { ...insight, reviewHistory: [...insight.reviewHistory], evidence: [...insight.evidence] }
}

function appendEvent(insight: Insight, event: ReviewEvent): Insight {
  insight.reviewHistory = [...insight.reviewHistory, event]
  return insight
}

export function createMockInsightsRepository(): InsightsRepository {
  return {
    async list(query: InsightsQuery = {}): Promise<InsightsPage> {
      await delay()
      const filtered = sortInsights(store.filter((insight) => matches(insight, query)), query)
      const page = query.page ?? 1
      const pageSize = query.pageSize ?? 10
      const start = (page - 1) * pageSize
      return {
        items: filtered.slice(start, start + pageSize).map(clone),
        total: filtered.length,
        page,
        pageSize,
      }
    },

    async getById(insightId: string) {
      await delay()
      return clone(findOrThrow(insightId))
    },

    async listRequestIds() {
      await delay(150)
      return [...new Set(store.map((i) => i.requestId))].sort()
    },

    async approve(insightId: string) {
      await delay(300)
      const insight = findOrThrow(insightId)
      insight.reviewStatus = 'approved'
      appendEvent(insight, {
        id: `${insightId}_${Date.now()}`,
        action: 'approved',
        actor: defaultPreferences.displayName,
        timestamp: new Date().toISOString(),
      })
      return clone(insight)
    },

    async reject(insightId: string, reason) {
      await delay(300)
      const insight = findOrThrow(insightId)
      insight.reviewStatus = 'rejected'
      appendEvent(insight, {
        id: `${insightId}_${Date.now()}`,
        action: 'rejected',
        actor: defaultPreferences.displayName,
        timestamp: new Date().toISOString(),
        reason,
      })
      return clone(insight)
    },

    async undo(insightId: string) {
      await delay(300)
      const insight = findOrThrow(insightId)
      insight.reviewStatus = 'pending'
      appendEvent(insight, {
        id: `${insightId}_${Date.now()}`,
        action: 'reset',
        actor: defaultPreferences.displayName,
        timestamp: new Date().toISOString(),
      })
      return clone(insight)
    },
  }
}

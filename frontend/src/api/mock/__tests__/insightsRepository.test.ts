import { describe, expect, it } from 'vitest'

import { createMockInsightsRepository } from '@/api/mock/insightsRepository'
import { ApiError } from '@/api/client'

// Read-only query tests run first and rely on the seeded data being
// untouched — mutating tests (approve/reject/undo) live in a later describe
// block and use insight ids not referenced here, since the mock repository's
// store is a module-level singleton shared across the whole test file.
describe('mock insights repository — querying', () => {
  it('paginates with the default page size of 10', async () => {
    const repo = createMockInsightsRepository()
    const page1 = await repo.list()
    expect(page1.items).toHaveLength(10)
    expect(page1.total).toBe(30)
    expect(page1.page).toBe(1)
    expect(page1.pageSize).toBe(10)
  })

  it('returns distinct pages with no overlap and an empty page past the end', async () => {
    const repo = createMockInsightsRepository()
    const page1 = await repo.list({ page: 1, pageSize: 10 })
    const page2 = await repo.list({ page: 2, pageSize: 10 })
    const page3 = await repo.list({ page: 3, pageSize: 10 })
    const page4 = await repo.list({ page: 4, pageSize: 10 })

    const ids1 = new Set(page1.items.map((i) => i.id))
    const ids2 = page2.items.map((i) => i.id)
    expect(ids2.every((id) => !ids1.has(id))).toBe(true)
    expect(page3.items).toHaveLength(10)
    expect(page4.items).toHaveLength(0)
  })

  it('filters by category', async () => {
    const repo = createMockInsightsRepository()
    const result = await repo.list({ category: 'credit_risk', pageSize: 100 })
    expect(result.total).toBeGreaterThan(0)
    expect(result.items.every((i) => i.category === 'credit_risk')).toBe(true)
  })

  it('filters by review status', async () => {
    const repo = createMockInsightsRepository()
    const approved = await repo.list({ reviewStatus: 'approved', pageSize: 100 })
    const rejected = await repo.list({ reviewStatus: 'rejected', pageSize: 100 })
    expect(approved.items.every((i) => i.reviewStatus === 'approved')).toBe(true)
    expect(rejected.items.every((i) => i.reviewStatus === 'rejected')).toBe(true)
    expect(approved.total).toBe(4)
    expect(rejected.total).toBe(3)
  })

  it('filters by company, returning exactly the three seeded insights per company', async () => {
    const repo = createMockInsightsRepository()
    const result = await repo.list({ companyId: 'CLI_002', pageSize: 100 })
    expect(result.total).toBe(3)
    expect(result.items.every((i) => i.companyId === 'CLI_002')).toBe(true)
  })

  it('filters by persona', async () => {
    const repo = createMockInsightsRepository()
    const result = await repo.list({ persona: 'executive_sponsor', pageSize: 100 })
    expect(result.total).toBeGreaterThan(0)
    expect(result.items.every((i) => i.persona === 'executive_sponsor')).toBe(true)
  })

  it('filters by priority', async () => {
    const repo = createMockInsightsRepository()
    const result = await repo.list({ priority: 'critical', pageSize: 100 })
    expect(result.total).toBeGreaterThan(0)
    expect(result.items.every((i) => i.priority === 'critical')).toBe(true)
  })

  it('filters by confidence range', async () => {
    const repo = createMockInsightsRepository()
    const result = await repo.list({ confidenceMin: 80, confidenceMax: 100, pageSize: 100 })
    expect(result.total).toBeGreaterThan(0)
    expect(result.items.every((i) => i.confidence >= 80 && i.confidence <= 100)).toBe(true)
  })

  it('filters by generated-date range', async () => {
    const repo = createMockInsightsRepository()
    const result = await repo.list({ dateFrom: '2026-08-13', dateTo: '2026-08-16', pageSize: 100 })
    expect(result.total).toBeGreaterThan(0)
    expect(
      result.items.every((i) => {
        const d = i.generatedAt.slice(0, 10)
        return d >= '2026-08-13' && d <= '2026-08-16'
      }),
    ).toBe(true)
  })

  it('filters by request id, matching the seeded resultInsightIds counts', async () => {
    const repo = createMockInsightsRepository()
    const req1001 = await repo.list({ requestId: 'REQ_1001', pageSize: 100 })
    const req1002 = await repo.list({ requestId: 'REQ_1002', pageSize: 100 })
    const req0995 = await repo.list({ requestId: 'REQ_0995', pageSize: 100 })
    expect(req1001.total).toBe(12)
    expect(req1002.total).toBe(12)
    expect(req0995.total).toBe(6)
  })

  it('filters by evidence source type', async () => {
    const repo = createMockInsightsRepository()
    const external = await repo.list({ evidenceSourceType: 'external', pageSize: 100 })
    expect(external.total).toBeGreaterThan(0)
    expect(external.items.every((i) => i.evidence.some((e) => e.sourceType === 'external'))).toBe(true)
  })

  it('sorts by confidence descending', async () => {
    const repo = createMockInsightsRepository()
    const result = await repo.list({ sortField: 'confidence', sortDirection: 'desc', pageSize: 100 })
    const confidences = result.items.map((i) => i.confidence)
    const sorted = [...confidences].sort((a, b) => b - a)
    expect(confidences).toEqual(sorted)
  })

  it('sorts by priority ascending', async () => {
    const repo = createMockInsightsRepository()
    const rank = { low: 1, medium: 2, high: 3, critical: 4 }
    const result = await repo.list({ sortField: 'priority', sortDirection: 'asc', pageSize: 100 })
    const ranks = result.items.map((i) => rank[i.priority])
    for (let i = 1; i < ranks.length; i++) {
      expect(ranks[i]).toBeGreaterThanOrEqual(ranks[i - 1])
    }
  })

  it('combines multiple filters together', async () => {
    const repo = createMockInsightsRepository()
    const result = await repo.list({ requestId: 'REQ_1001', category: 'capital_markets_advisory', pageSize: 100 })
    expect(result.total).toBeGreaterThan(0)
    expect(result.items.every((i) => i.requestId === 'REQ_1001' && i.category === 'capital_markets_advisory')).toBe(true)
  })

  it('returns an empty page when no insight matches the filters', async () => {
    const repo = createMockInsightsRepository()
    const result = await repo.list({ search: 'no-such-insight-xyz' })
    expect(result.total).toBe(0)
    expect(result.items).toEqual([])
  })

  it('lists distinct request ids for the Request ID filter', async () => {
    const repo = createMockInsightsRepository()
    const ids = await repo.listRequestIds()
    expect(ids).toEqual(['REQ_0995', 'REQ_1001', 'REQ_1002'])
  })

  it('throws an ApiError for an unknown insight id', async () => {
    const repo = createMockInsightsRepository()
    await expect(repo.getById('NOT_REAL')).rejects.toBeInstanceOf(ApiError)
  })
})

describe('mock insights repository — review actions', () => {
  it('approves an insight, sets reviewStatus, and appends a review history event', async () => {
    const repo = createMockInsightsRepository()
    const before = await repo.getById('INS_001')
    expect(before.reviewStatus).toBe('pending')

    const updated = await repo.approve('INS_001')
    expect(updated.reviewStatus).toBe('approved')
    expect(updated.reviewHistory).toHaveLength(before.reviewHistory.length + 1)
    const lastEvent = updated.reviewHistory[updated.reviewHistory.length - 1];
    expect(lastEvent.action).toBe('approved')

    const refetched = await repo.getById('INS_001')
    expect(refetched.reviewStatus).toBe('approved')
  })

  it('rejects an insight with a predefined reason and appends a review history event', async () => {
    const repo = createMockInsightsRepository()
    const updated = await repo.reject('INS_002', 'insufficient_evidence')
    expect(updated.reviewStatus).toBe('rejected')
    const lastEvent = updated.reviewHistory[updated.reviewHistory.length - 1];
    expect(lastEvent.action).toBe('rejected')
    expect(lastEvent.reason).toBe('insufficient_evidence')
  })

  it('undo reverts a decision back to pending and appends a reset event', async () => {
    const repo = createMockInsightsRepository()
    await repo.approve('INS_003')
    const approved = await repo.getById('INS_003')
    expect(approved.reviewStatus).toBe('approved')

    const reverted = await repo.undo('INS_003')
    expect(reverted.reviewStatus).toBe('pending')
    const lastEvent = reverted.reviewHistory[reverted.reviewHistory.length - 1];
    expect(lastEvent.action).toBe('reset')

    const refetched = await repo.getById('INS_003')
    expect(refetched.reviewStatus).toBe('pending')
  })

  it('reflects status changes immediately without needing a refetch of the whole list', async () => {
    const repo = createMockInsightsRepository()
    await repo.reject('INS_004', 'outdated')
    const filtered = await repo.list({ reviewStatus: 'rejected', pageSize: 100 })
    expect(filtered.items.some((i) => i.id === 'INS_004')).toBe(true)
  })
})

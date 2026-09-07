import type { ApiClient } from '@/api/client'
import { buildQuery } from '@/api/client'
import type { InsightsPage, InsightsQuery, InsightsRepository } from '@/api/repositories/types'
import type { Insight } from '@/api/types'

/**
 * Real HTTP-backed InsightsRepository, talking to
 * src/insights_assistant/api/server.py. Insights there are synthesized by a
 * second LLM call over the orchestrator's answer (api/synthesis.py) --
 * see docs/api/MAPPING.md's "What the orchestrator doesn't produce yet".
 */
export function createHttpInsightsRepository(client: ApiClient): InsightsRepository {
  return {
    async list(query: InsightsQuery = {}): Promise<InsightsPage> {
      const qs = buildQuery({
        reviewStatus: query.reviewStatus,
        category: query.category,
        companyId: query.companyId,
        persona: query.persona,
        priority: query.priority,
        confidenceMin: query.confidenceMin,
        confidenceMax: query.confidenceMax,
        dateFrom: query.dateFrom,
        dateTo: query.dateTo,
        requestId: query.requestId,
        evidenceSourceType: query.evidenceSourceType,
        search: query.search,
        sortField: query.sortField,
        sortDirection: query.sortDirection,
        page: query.page,
        pageSize: query.pageSize,
      })
      return client.get<InsightsPage>(`/insights${qs}`)
    },

    async getById(insightId: string) {
      return client.get<Insight>(`/insights/${insightId}`)
    },

    async listRequestIds() {
      return client.get<string[]>('/insights/request-ids')
    },

    async approve(insightId: string) {
      return client.post<Insight>(`/insights/${insightId}/approve`, {})
    },

    async reject(insightId: string, reason) {
      return client.post<Insight>(`/insights/${insightId}/reject`, { reason })
    },

    async undo(insightId: string) {
      return client.post<Insight>(`/insights/${insightId}/reset`, {})
    },
  }
}

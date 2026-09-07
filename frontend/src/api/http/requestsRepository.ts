import type { ApiClient } from '@/api/client'
import type { CreateRequestInput, RequestsRepository } from '@/api/repositories/types'
import type { RequestStatus, ResearchRequest } from '@/api/types'

/**
 * Real HTTP-backed RequestsRepository, talking to
 * src/insights_assistant/api/server.py — the one part of the backend that's
 * actually wired to the live agent orchestrator today. Every other
 * repository is still mock-backed; see docs/api/MIGRATION_PLAN.md.
 */
export function createHttpRequestsRepository(client: ApiClient): RequestsRepository {
  return {
    async list(filters?: { status?: RequestStatus }) {
      const all = await client.get<ResearchRequest[]>('/requests')
      return filters?.status ? all.filter((r) => r.status === filters.status) : all
    },

    async getById(requestId: string) {
      return client.get<ResearchRequest>(`/requests/${requestId}`)
    },

    async create(input: CreateRequestInput) {
      return client.post<ResearchRequest>('/requests', input)
    },

    async cancel(requestId: string) {
      return client.post<ResearchRequest>(`/requests/${requestId}/cancel`, {})
    },

    async remove(requestId: string) {
      return client.delete(`/requests/${requestId}`)
    },
  }
}

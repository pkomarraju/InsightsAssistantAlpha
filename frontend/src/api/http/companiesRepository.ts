import type { ApiClient } from '@/api/client'
import type { CompaniesRepository, CompanyBrief } from '@/api/repositories/types'
import type { Company, RelationshipSnapshot } from '@/api/types'

/**
 * Real HTTP-backed CompaniesRepository, talking to
 * src/insights_assistant/api/server.py's Supabase-backed /api/companies*
 * endpoints. getBrief() is confirmed dead code (no page calls it -- see
 * docs/api/MIGRATION_PLAN.md) but is implemented for real rather than
 * stubbed, since the backend already has to touch these tables.
 */
export function createHttpCompaniesRepository(client: ApiClient): CompaniesRepository {
  return {
    async list() {
      return client.get<Company[]>('/companies')
    },

    async listSnapshots() {
      return client.get<RelationshipSnapshot[]>('/companies/snapshots')
    },

    async getBrief(companyId: string) {
      return client.get<CompanyBrief>(`/companies/${companyId}/brief`)
    },
  }
}

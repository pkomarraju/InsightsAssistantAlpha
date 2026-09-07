import type { CompaniesRepository, CompanyBrief } from '@/api/repositories/types'
import { ApiError } from '@/api/client'
import { delay } from '@/api/mock/latency'
import { getMonthlyMetricsByCompany } from '@/api/mock/metrics'
import {
  clientInteractions,
  companies,
  opportunities,
  products,
  relationshipNotes,
  relationshipSnapshots,
  riskAssessments,
} from '@/api/mock/seed'

export function createMockCompaniesRepository(): CompaniesRepository {
  return {
    async list() {
      await delay()
      return companies
    },

    async listSnapshots() {
      await delay()
      return relationshipSnapshots
    },

    async getBrief(companyId: string): Promise<CompanyBrief> {
      await delay()
      const company = companies.find((c) => c.companyId === companyId)
      const snapshot = relationshipSnapshots.find((s) => s.companyId === companyId)
      if (!company || !snapshot) {
        throw new ApiError(`No company found for id ${companyId}`, 404)
      }
      return {
        company,
        snapshot,
        products: products.filter((p) => p.companyId === companyId),
        opportunities: opportunities.filter((o) => o.companyId === companyId),
        risk: riskAssessments.filter((r) => r.companyId === companyId),
        interactions: clientInteractions.filter((i) => i.companyId === companyId),
        notes: relationshipNotes.filter((n) => n.companyCode === companyId),
        monthlyMetrics: getMonthlyMetricsByCompany(companyId),
      }
    },
  }
}

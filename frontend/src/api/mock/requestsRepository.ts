import type { CreateRequestInput, RequestsRepository } from '@/api/repositories/types'
import type { ResearchRequest } from '@/api/types'
import { ApiError } from '@/api/client'
import { delay } from '@/api/mock/latency'
import { companies } from '@/api/mock/seed'
import { researchRequests } from '@/api/mock/requests'

const store = [...researchRequests]
let nextId = 1005

const DOMAIN_LABELS: Record<string, string> = {
  company_profile: 'Company & Coverage Profile',
  credit_exposure: 'Credit Exposure & Facilities',
  deal_pipeline: 'CRM Deal Pipeline',
  internal_risk_flags: 'Internal Risk Flags',
}

export function createMockRequestsRepository(): RequestsRepository {
  return {
    async list(filters) {
      await delay()
      if (!filters?.status) return [...store].sort((a, b) => b.createdAt.localeCompare(a.createdAt))
      return store
        .filter((r) => r.status === filters.status)
        .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
    },

    async getById(requestId: string) {
      await delay()
      const found = store.find((r) => r.requestId === requestId)
      if (!found) throw new ApiError(`No request found for id ${requestId}`, 404)
      return found
    },

    async create(input: CreateRequestInput) {
      await delay(500)
      const now = new Date().toISOString()
      const scopedCompanies = companies
        .filter((c) => input.companyIds.includes(c.companyId))
        .map((c) => ({ companyId: c.companyId, companyCode: c.companyCode, companyName: c.companyName, ticker: c.ticker }))

      const request: ResearchRequest = {
        requestId: `REQ_${nextId++}`,
        requestedBy: 'banker-12345',
        status: 'queued',
        createdAt: now,
        updatedAt: now,
        companyScope: { selectionMode: 'explicit', companies: scopedCompanies },
        externalResearch: {
          enabled: input.enabled,
          providers: input.providers,
          edgarEnabled: input.edgarEnabled,
          filingTypes: input.filingTypes,
          lookbackMonths: input.lookbackMonths,
        },
        internalResearch: {
          dataDomains: input.dataDomainIds.map((domainId) => ({
            domainId,
            label: DOMAIN_LABELS[domainId] ?? domainId,
            enabled: true,
          })),
          generalSearchPrompt: input.generalSearchPrompt,
          asOfDate: now.slice(0, 10),
        },
        insightRequirements: {
          totalCount: input.totalCount,
          categories: input.categories,
          rankingCriteria: input.rankingCriteria,
          maxInsightsPerCompany: 10,
        },
        resultInsightIds: [],
        progressPct: 0,
        errorMessage: null,
        // Mirrors the live backend's initial state (api/server.py's
        // create_request) so mock-mode exercises the same shape a real
        // in-flight request would have.
        currentStage: 'queued',
        requestVersion: 1,
        packageVersion: 1,
        researchRevisionCount: 0,
        synthesisRevisionCount: 0,
        sourceErrors: [],
        reviewDecision: null,
        reviewComments: null,
        auditEvents: [],
        unmetRequirements: [],
      }

      store.unshift(request)
      return request
    },

    async cancel(requestId: string) {
      await delay()
      const found = store.find((r) => r.requestId === requestId)
      if (!found) throw new ApiError(`No request found for id ${requestId}`, 404)
      if (found.status === 'completed' || found.status === 'failed' || found.status === 'cancelled') {
        throw new ApiError(`Request ${requestId} already ${found.status}; nothing to cancel`, 409)
      }

      const now = new Date().toISOString()
      found.status = 'cancelled'
      found.currentStage = 'cancelled'
      found.progressPct = 100
      found.errorMessage = 'Cancelled by user.'
      found.updatedAt = now
      return found
    },

    async remove(requestId: string) {
      await delay()
      const index = store.findIndex((r) => r.requestId === requestId)
      if (index === -1) throw new ApiError(`No request found for id ${requestId}`, 404)
      store.splice(index, 1)
    },
  }
}

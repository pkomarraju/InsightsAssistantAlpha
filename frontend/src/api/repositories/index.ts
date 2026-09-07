import { httpClient } from '@/api/client'
import { createHttpAssistantRepository } from '@/api/http/assistantRepository'
import { createHttpCompaniesRepository } from '@/api/http/companiesRepository'
import { createHttpInsightsRepository } from '@/api/http/insightsRepository'
import { createHttpPreferencesRepository } from '@/api/http/preferencesRepository'
import { createHttpRequestsRepository } from '@/api/http/requestsRepository'
import { createMockAssistantRepository } from '@/api/mock/assistantRepository'
import { createMockCompaniesRepository } from '@/api/mock/companiesRepository'
import { createMockInsightsRepository } from '@/api/mock/insightsRepository'
import { createMockPreferencesRepository } from '@/api/mock/preferencesRepository'
import { createMockRequestsRepository } from '@/api/mock/requestsRepository'
import type {
  AssistantRepository,
  CompaniesRepository,
  InsightsRepository,
  PreferencesRepository,
  RequestsRepository,
} from '@/api/repositories/types'

export interface Repositories {
  companies: CompaniesRepository
  insights: InsightsRepository
  requests: RequestsRepository
  assistant: AssistantRepository
  preferences: PreferencesRepository
}

/**
 * Single seam for swapping mock repositories for real HTTP-backed ones.
 * Every repository goes live (talking to
 * src/insights_assistant/api/server.py — Supabase for companies, the real
 * agent orchestrator for requests and assistant chat, and an in-memory
 * store for insights/preferences) whenever VITE_API_BASE_URL is set — see
 * frontend/.env.development.local. Falls back to the fully mock
 * repositories otherwise (including in tests and production builds, which
 * don't load that dev-only env file). See docs/api/MIGRATION_PLAN.md for
 * the full mock→HTTP contract this deviates from in scope (no optimistic
 * concurrency, no persistence).
 */
export function createRepositories(): Repositories {
  const hasLiveBackend = Boolean(import.meta.env.VITE_API_BASE_URL)

  return {
    companies: hasLiveBackend ? createHttpCompaniesRepository(httpClient) : createMockCompaniesRepository(),
    insights: hasLiveBackend ? createHttpInsightsRepository(httpClient) : createMockInsightsRepository(),
    requests: hasLiveBackend ? createHttpRequestsRepository(httpClient) : createMockRequestsRepository(),
    assistant: hasLiveBackend ? createHttpAssistantRepository(httpClient) : createMockAssistantRepository(),
    preferences: hasLiveBackend ? createHttpPreferencesRepository(httpClient) : createMockPreferencesRepository(),
  }
}

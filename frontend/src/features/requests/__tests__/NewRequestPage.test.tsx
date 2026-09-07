import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { CreateRequestInput, RequestsRepository } from '@/api/repositories/types'
import type { ResearchRequest } from '@/api/types'
import { NewRequestPage } from '@/features/requests/NewRequestPage'
import { renderWithProviders } from '@/test/renderWithProviders'

const FAKE_CREATED_REQUEST: ResearchRequest = {
  requestId: 'REQ_TEST', requestedBy: 'banker-12345',
  status: 'queued', createdAt: '2026-09-06T00:00:00Z', updatedAt: '2026-09-06T00:00:00Z',
  companyScope: { selectionMode: 'explicit', companies: [] },
  externalResearch: { enabled: true, providers: ['fmp', 'alpha_vantage', 'fred'], edgarEnabled: true, filingTypes: [], lookbackMonths: 24 },
  internalResearch: { dataDomains: [], generalSearchPrompt: 'x', asOfDate: '2026-09-06' },
  insightRequirements: { totalCount: 8, categories: [], rankingCriteria: [], maxInsightsPerCompany: 10 },
  resultInsightIds: [], progressPct: 0, errorMessage: null,
}

describe('NewRequestPage — data sources step', () => {
  it('shows the new internal datasets and external providers, with no EDGAR/filing terminology, and submits the provider-neutral selection', async () => {
    const createSpy = vi.fn<RequestsRepository['create']>(async (_input: CreateRequestInput) => FAKE_CREATED_REQUEST)
    const fakeRequests: RequestsRepository = {
      list: async () => [],
      getById: async () => FAKE_CREATED_REQUEST,
      create: createSpy,
      cancel: async () => FAKE_CREATED_REQUEST,
      remove: async () => {},
    }

    renderWithProviders(<NewRequestPage />, { overrides: { requests: fakeRequests } })
    const user = userEvent.setup()

    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument())

    // Step 0: select a company so the wizard can advance.
    const firstCompanyLabel = (await screen.findAllByRole('checkbox'))[0].closest('label')!
    await user.click(within(firstCompanyLabel).getByRole('checkbox'))
    await user.click(screen.getByRole('button', { name: /next/i }))

    // Step 1: Data sources. The scope-summary sidebar also echoes selected
    // domain/provider labels, so assert presence (>=1), not uniqueness.
    expect(screen.getAllByText('Company & Coverage Profile').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Credit Exposure & Facilities').length).toBeGreaterThan(0)
    expect(screen.getAllByText('CRM Deal Pipeline').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Internal Risk Flags').length).toBeGreaterThan(0)
    expect(screen.getByText('Always included')).toBeInTheDocument()

    const companyProfileLabel = screen.getAllByText('Company & Coverage Profile')[0].closest('label')!
    const companyProfileCheckbox = within(companyProfileLabel).getByRole('checkbox')
    expect(companyProfileCheckbox).toBeDisabled()
    expect(companyProfileCheckbox).toHaveAttribute('aria-checked', 'true')

    expect(screen.getAllByText('Financial Modeling Prep').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Alpha Vantage').length).toBeGreaterThan(0)
    expect(screen.getAllByText('FRED').length).toBeGreaterThan(0)

    expect(screen.queryByText(/EDGAR/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/filing/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/10-K|10-Q|8-K|DEF 14A/)).not.toBeInTheDocument()

    // Advance through Requirements (defaults already satisfy its own
    // canAdvance check) to Review, then submit.
    await user.click(screen.getByRole('button', { name: /next/i }))
    await user.click(screen.getByRole('button', { name: /next/i }))
    await user.click(screen.getByRole('button', { name: /submit request/i }))

    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1))
    const submitted = createSpy.mock.calls[0][0]
    expect(submitted.enabled).toBe(true)
    expect(submitted.providers).toEqual(['fmp', 'alpha_vantage', 'fred'])
    expect(submitted.dataDomainIds).toContain('company_profile')
  })
})

describe('NewRequestPage — insight requirements step', () => {
  it('offers only the four current focus areas, hides minimum-count inputs, defaults to three target insights, and submits minimumCount: 0', async () => {
    const createSpy = vi.fn<RequestsRepository['create']>(async (_input: CreateRequestInput) => FAKE_CREATED_REQUEST)
    const fakeRequests: RequestsRepository = {
      list: async () => [],
      getById: async () => FAKE_CREATED_REQUEST,
      create: createSpy,
      cancel: async () => FAKE_CREATED_REQUEST,
      remove: async () => {},
    }

    renderWithProviders(<NewRequestPage />, { overrides: { requests: fakeRequests } })
    const user = userEvent.setup()

    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument())

    // Step 0: select a company, then advance through Data sources to
    // Insight requirements.
    const firstCompanyLabel = (await screen.findAllByRole('checkbox'))[0].closest('label')!
    await user.click(within(firstCompanyLabel).getByRole('checkbox'))
    await user.click(screen.getByRole('button', { name: /next/i }))
    await user.click(screen.getByRole('button', { name: /next/i }))

    // Step 2: Insight requirements.
    expect(screen.getByText('Insight focus areas')).toBeInTheDocument()
    expect(
      screen.getByText(
        /select the areas most relevant to this request\. the assistant may return fewer insights/i,
      ),
    ).toBeInTheDocument()

    // Exactly the four current categories are offered -- none of the
    // legacy five. (The scope-summary sidebar also echoes selected focus
    // areas, so assert presence, not uniqueness.)
    expect(screen.getAllByText('Financing & liquidity').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Deal & fee opportunities').length).toBeGreaterThan(0)
    expect(screen.getByText('Financial performance')).toBeInTheDocument()
    expect(screen.getAllByText('Risk & coverage attention').length).toBeGreaterThan(0)
    expect(screen.queryByText('Revenue & cross-sell')).not.toBeInTheDocument()
    expect(screen.queryByText('Credit risk')).not.toBeInTheDocument()
    expect(screen.queryByText('Capital markets advisory')).not.toBeInTheDocument()
    expect(screen.queryByText(/Treasury.*payments.*liquidity/i)).not.toBeInTheDocument()
    expect(screen.queryByText('Relationship risk')).not.toBeInTheDocument()

    // No per-category minimum-count inputs remain -- only the single
    // target-insight-count number input.
    const numberInputs = screen.getAllByRole('spinbutton')
    expect(numberInputs).toHaveLength(1)
    expect(numberInputs[0]).toHaveValue(3)
    expect(screen.queryByText(/minimum count/i)).not.toBeInTheDocument()

    // Advance to Review and submit.
    await user.click(screen.getByRole('button', { name: /next/i }))
    await user.click(screen.getByRole('button', { name: /submit request/i }))

    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1))
    const submitted = createSpy.mock.calls[0][0]
    expect(submitted.totalCount).toBe(3)
    expect(submitted.categories.length).toBeGreaterThan(0)
    for (const category of submitted.categories) {
      expect(category.minimumCount).toBe(0)
    }
    expect(submitted.categories.map((c) => c.categoryId).sort()).toEqual(
      ['deal_fee_opportunity', 'financing_liquidity', 'risk_coverage_attention'].sort(),
    )
  })
})

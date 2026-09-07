import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { InsightsRepository } from '@/api/repositories/types'
import { ApiError } from '@/api/client'
import { InsightsListPage } from '@/features/insights/InsightsListPage'
import { renderWithProviders } from '@/test/renderWithProviders'

async function waitForLoaded() {
  await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument())
}

function dataRows() {
  // First row returned by getAllByRole('row') is the header row.
  return screen.getAllByRole('row').slice(1)
}

describe('InsightsListPage — loading, filtering, sorting, pagination', () => {
  it('shows a loading state, then renders a page of insights with the expected columns', async () => {
    renderWithProviders(<InsightsListPage />)

    expect(screen.getByRole('status')).toBeInTheDocument()
    await waitForLoaded()

    expect(screen.getByRole('columnheader', { name: /title/i })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: /business impact/i })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: /review status/i })).toBeInTheDocument()
    expect(dataRows()).toHaveLength(10)
    expect(screen.getByText(/showing 1–10 of 30/i)).toBeInTheDocument()
  })

  it('filters by company down to exactly the three seeded insights', async () => {
    const user = userEvent.setup()
    renderWithProviders(<InsightsListPage />)
    await waitForLoaded()

    await user.click(screen.getByLabelText(/filter by company/i))
    await user.click(await screen.findByRole('option', { name: 'Amazon' }))

    await waitFor(() => expect(dataRows()).toHaveLength(3))
    expect(screen.getAllByText('Amazon').length).toBeGreaterThan(0)
  })

  it('filters by review status', async () => {
    const user = userEvent.setup()
    renderWithProviders(<InsightsListPage />)
    await waitForLoaded()

    await user.click(screen.getByLabelText(/filter by review status/i))
    await user.click(await screen.findByRole('option', { name: 'Approved' }))

    await waitFor(() => expect(screen.getByText(/showing 1–4 of 4/i)).toBeInTheDocument())
    for (const row of dataRows()) {
      expect(within(row).getByText('Approved')).toBeInTheDocument()
    }
  })

  it('filters by request id', async () => {
    const user = userEvent.setup()
    renderWithProviders(<InsightsListPage />)
    await waitForLoaded()

    await user.click(screen.getByLabelText(/filter by request id/i))
    await user.click(await screen.findByRole('option', { name: 'REQ_0995' }))

    await waitFor(() => expect(screen.getByText(/showing 1–6 of 6/i)).toBeInTheDocument())
  })

  it('shows a no-filter-results empty state when filters exclude everything, and Clear filters recovers', async () => {
    const user = userEvent.setup()
    renderWithProviders(<InsightsListPage />)
    await waitForLoaded()

    await user.type(screen.getByLabelText(/^search$/i), 'zzz-no-such-insight-zzz')

    await waitFor(() => expect(screen.getByText(/no insights match your filters/i)).toBeInTheDocument())

    // Both the toolbar and the empty state expose a "Clear filters" action; click the empty state's.
    await user.click(screen.getAllByRole('button', { name: /clear filters/i })[0])
    await waitFor(() => expect(screen.getByText(/showing 1–10 of 30/i)).toBeInTheDocument())
  })

  it('paginates to the next page', async () => {
    const user = userEvent.setup()
    renderWithProviders(<InsightsListPage />)
    await waitForLoaded()

    const firstPageTitles = dataRows().map((r) => within(r).getAllByRole('link')[0].textContent)

    await user.click(screen.getByRole('button', { name: /^next$/i }))

    await waitFor(() => expect(screen.getByText(/showing 11–20 of 30/i)).toBeInTheDocument())
    const secondPageTitles = dataRows().map((r) => within(r).getAllByRole('link')[0].textContent)
    expect(secondPageTitles.some((t) => firstPageTitles.includes(t))).toBe(false)
  })

  it('sorts by confidence, high to low', async () => {
    const user = userEvent.setup()
    renderWithProviders(<InsightsListPage />)
    await waitForLoaded()

    await user.click(screen.getByLabelText(/sort insights/i))
    await user.click(await screen.findByRole('option', { name: /confidence \(high to low\)/i }))

    await waitFor(() => {
      const confidences = dataRows().map((r) => Number(within(r).getAllByRole('cell')[4].textContent?.replace('%', '')))
      const sorted = [...confidences].sort((a, b) => b - a)
      expect(confidences).toEqual(sorted)
    })
  })
})

describe('InsightsListPage — approve and reject', () => {
  it('approves a pending insight after confirmation and shows success feedback', async () => {
    const user = userEvent.setup()
    renderWithProviders(<InsightsListPage />)
    await waitForLoaded()

    // Cencora (CLI_009) has exactly one pending insight among its three.
    await user.click(screen.getByLabelText(/filter by company/i))
    await user.click(await screen.findByRole('option', { name: 'Cencora' }))
    await waitFor(() => expect(dataRows()).toHaveLength(3))

    const pendingRow = dataRows().find((r) => within(r).queryByRole('button', { name: /^approve/i }))!
    const title = within(pendingRow).getAllByRole('link')[0].textContent

    await user.click(within(pendingRow).getByRole('button', { name: /^approve/i }))
    expect(await screen.findByText(/approve this insight/i)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /^approve$/i, hidden: false }))

    await waitFor(() => expect(screen.getByText(`"${title}" approved.`)).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /undo/i })).toBeInTheDocument()
  })

  it('requires a predefined reason to reject, and reflects rejection immediately', async () => {
    const user = userEvent.setup()
    renderWithProviders(<InsightsListPage />)
    await waitForLoaded()

    // Use a different company than the approve test above (McKesson), since
    // the mock repository's store is shared across tests in this file.
    await user.click(screen.getByLabelText(/filter by company/i))
    await user.click(await screen.findByRole('option', { name: 'McKesson' }))
    await waitFor(() => expect(dataRows()).toHaveLength(3))

    const pendingRow = dataRows().find((r) => within(r).queryByRole('button', { name: /^reject/i }))!
    const title = within(pendingRow).getAllByRole('link')[0].textContent

    await user.click(within(pendingRow).getByRole('button', { name: /^reject/i }))
    expect(await screen.findByText(/reject this insight/i)).toBeInTheDocument()

    const confirmRejectButton = screen.getByRole('button', { name: /^reject$/i })
    expect(confirmRejectButton).toBeDisabled()

    await user.click(screen.getByLabelText('Duplicate'))
    expect(confirmRejectButton).toBeEnabled()

    await user.click(confirmRejectButton)

    await waitFor(() => expect(screen.getByText(`"${title}" rejected.`)).toBeInTheDocument())

    // Filtering to rejected-only should now include this insight.
    await user.click(screen.getByLabelText(/filter by review status/i))
    await user.click(await screen.findByRole('option', { name: 'Rejected' }))
    await waitFor(() => expect(screen.getAllByText('Rejected').length).toBeGreaterThan(0))
  })
})

describe('InsightsListPage — true empty and error states', () => {
  const noopRepo: Partial<InsightsRepository> = {
    getById: async () => {
      throw new ApiError('not used')
    },
    approve: async () => {
      throw new ApiError('not used')
    },
    reject: async () => {
      throw new ApiError('not used')
    },
    undo: async () => {
      throw new ApiError('not used')
    },
  }

  it('shows a true empty state when the repository has no insights at all', async () => {
    renderWithProviders(<InsightsListPage />, {
      overrides: {
        insights: {
          ...noopRepo,
          list: async () => ({ items: [], total: 0, page: 1, pageSize: 10 }),
          listRequestIds: async () => [],
        } as InsightsRepository,
      },
    })

    await waitForLoaded()
    expect(screen.getByText(/no insights yet/i)).toBeInTheDocument()
  })

  it('shows an error state with retry when the repository call fails', async () => {
    let attempt = 0
    renderWithProviders(<InsightsListPage />, {
      overrides: {
        insights: {
          ...noopRepo,
          list: async () => {
            attempt += 1
            if (attempt === 1) throw new Error('Network unavailable')
            return { items: [], total: 0, page: 1, pageSize: 10 }
          },
          listRequestIds: async () => [],
        } as InsightsRepository,
      },
    })

    await waitFor(() => expect(screen.getByText(/network unavailable/i)).toBeInTheDocument())
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /try again/i }))
    await waitFor(() => expect(screen.getByText(/no insights yet/i)).toBeInTheDocument())
  })
})

import { Route, Routes } from 'react-router-dom'
import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { InsightsRepository, RequestsRepository } from '@/api/repositories/types'
import type { ResearchRequest } from '@/api/types'
import { RequestDetailPage } from '@/features/requests/RequestDetailPage'
import { renderWithProviders } from '@/test/renderWithProviders'

function renderDetail(requestId: string, overrides?: Partial<{ requests: RequestsRepository; insights: InsightsRepository }>) {
  return renderWithProviders(
    <Routes>
      <Route path="/requests/:requestId" element={<RequestDetailPage />} />
    </Routes>,
    { route: `/requests/${requestId}`, overrides },
  )
}

async function waitForLoaded() {
  await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument())
}

describe('RequestDetailPage', () => {
  it('shows a timed-out source distinctly in Source status', async () => {
    // REQ_0998 (frontend/src/api/mock/requests.ts): a provider timed out for CLI_004
    // after one research revision was attempted and still didn't recover it.
    renderDetail('REQ_0998')
    await waitForLoaded()

    expect(screen.getByText('Source status')).toBeInTheDocument()
    expect(screen.getByText('Timed out')).toBeInTheDocument()
    // Also shown in the Terminal error card -- both are legitimate displays
    // of the same underlying errorMessage/sourceError.message.
    expect(screen.getAllByText(/FRED tool timed out after 3 retries/i).length).toBeGreaterThan(0)
    expect(screen.getByText(/External data agent/i)).toBeInTheDocument()
  })

  it('shows research revision history and the revise_research reviewer decision', async () => {
    renderDetail('REQ_0998')
    await waitForLoaded()

    expect(screen.getByText('Revise research')).toBeInTheDocument()
    // Shown both as the Workflow card's reviewComments and as the matching
    // Version history audit event's detail.comments.
    expect(screen.getAllByText(/could not be retrieved; re-check provider access/i).length).toBeGreaterThan(0)
    expect(screen.getByText('Version history')).toBeInTheDocument()
    expect(screen.getByText('review decision: revise_research')).toBeInTheDocument()
  })

  it('reflects the failed terminal state after the research revision budget was used and still failed', async () => {
    renderDetail('REQ_0998')
    await waitForLoaded()

    expect(screen.getAllByText('Failed').length).toBeGreaterThan(0)
    expect(screen.getByText('Terminal error')).toBeInTheDocument()
    expect(screen.getByText('Research revision')).toBeInTheDocument()
    expect(screen.getByText('Synthesis revision')).toBeInTheDocument()
    expect(screen.getByText('used')).toBeInTheDocument() // research revision was used
    expect(screen.getByText('not used')).toBeInTheDocument() // synthesis revision was not
  })

  it('shows synthesis revision history and a passed reviewer decision for a completed request', async () => {
    // REQ_1002: one revise_insights round before the Reviewer passed the
    // consolidated package.
    renderDetail('REQ_1002')
    await waitForLoaded()

    expect(screen.getByText('Passed')).toBeInTheDocument()
    expect(screen.getByText(/well supported and ranked correctly/i)).toBeInTheDocument()
    expect(screen.getByText('review decision: revise_insights')).toBeInTheDocument()
    expect(screen.getByText(/Consolidate two overlapping credit-risk insights/i)).toBeInTheDocument()
  })

  it('renders without the new workflow fields when the backend/mock omits them (backward compatibility)', async () => {
    // REQ_0995 and REQ_1001 predate the workflow-state fields entirely.
    renderDetail('REQ_0995')
    await waitForLoaded()

    expect(screen.queryByText('Workflow')).not.toBeInTheDocument()
    expect(screen.queryByText('Source status')).not.toBeInTheDocument()
    expect(screen.queryByText('Version history')).not.toBeInTheDocument()
    expect(screen.queryByText('Unmet requirements')).not.toBeInTheDocument()
    // The pre-existing fields must still render normally.
    expect(screen.getAllByText('Completed').length).toBeGreaterThan(0)
  })

  it('shows the current stage badge and stage-specific progress label while running', async () => {
    // REQ_1003 is seeded mid-synthesis.
    renderDetail('REQ_1003')
    await waitForLoaded()

    expect(screen.getByText('Synthesizing')).toBeInTheDocument()
    expect(screen.getByText('Synthesizing insights')).toBeInTheDocument()
  })

  it('stops polling once the request reaches a terminal status', async () => {
    vi.useFakeTimers()
    let calls = 0
    const base: ResearchRequest = {
      requestId: 'REQ_POLL', requestedBy: 'banker-12345', status: 'running',
      createdAt: '2026-09-01T00:00:00Z', updatedAt: '2026-09-01T00:00:00Z',
      companyScope: { selectionMode: 'explicit', companies: [] },
      externalResearch: { edgarEnabled: false, filingTypes: [], lookbackMonths: 12 },
      internalResearch: { dataDomains: [], generalSearchPrompt: 'x', asOfDate: '2026-09-01' },
      insightRequirements: { totalCount: 1, categories: [], rankingCriteria: [], maxInsightsPerCompany: 1 },
      resultInsightIds: [], progressPct: 50, errorMessage: null,
    }
    const fakeRequests: RequestsRepository = {
      async list() {
        return []
      },
      async getById() {
        calls += 1
        const terminal = calls >= 3
        return { ...base, status: terminal ? 'completed' : 'running', currentStage: terminal ? 'completed' : 'researching' }
      },
      async create() {
        throw new Error('not used by this test')
      },
      async cancel() {
        throw new Error('not used by this test')
      },
      async remove() {
        throw new Error('not used by this test')
      },
    }
    const fakeInsights: InsightsRepository = {
      async list() {
        return { items: [], total: 0, page: 1, pageSize: 100 }
      },
      async getById() {
        throw new Error('not used by this test')
      },
      async listRequestIds() {
        return []
      },
      async approve() {
        throw new Error('not used by this test')
      },
      async reject() {
        throw new Error('not used by this test')
      },
      async undo() {
        throw new Error('not used by this test')
      },
    }

    renderDetail('REQ_POLL', { requests: fakeRequests, insights: fakeInsights })

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(calls).toBe(1) // initial load

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000)
    })
    expect(calls).toBe(2) // still running -> polled again

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000)
    })
    expect(calls).toBe(3) // this response flips to completed

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000)
    })
    expect(calls).toBe(3) // polling must have stopped -- no 4th call

    vi.useRealTimers()
  })

  it('shows a Stop generation button only while the request is in flight', async () => {
    renderDetail('REQ_1003') // seeded status: 'running'
    await waitForLoaded()
    expect(screen.getByRole('button', { name: /stop generation/i })).toBeInTheDocument()
  })

  it('hides the Stop generation button once the request is terminal', async () => {
    renderDetail('REQ_1002') // seeded status: 'completed'
    await waitForLoaded()
    expect(screen.queryByRole('button', { name: /stop generation/i })).not.toBeInTheDocument()
  })

  it('confirming Stop generation calls cancel and reflects the cancelled state', async () => {
    const user = userEvent.setup()
    const base: ResearchRequest = {
      requestId: 'REQ_STOP', requestedBy: 'banker-12345', status: 'running',
      createdAt: '2026-09-01T00:00:00Z', updatedAt: '2026-09-01T00:00:00Z',
      companyScope: { selectionMode: 'explicit', companies: [] },
      externalResearch: { edgarEnabled: false, filingTypes: [], lookbackMonths: 12 },
      internalResearch: { dataDomains: [], generalSearchPrompt: 'x', asOfDate: '2026-09-01' },
      insightRequirements: { totalCount: 1, categories: [], rankingCriteria: [], maxInsightsPerCompany: 1 },
      resultInsightIds: [], progressPct: 40, errorMessage: null, currentStage: 'researching',
    }
    let cancelled = false
    const cancelSpy = vi.fn(async (requestId: string) => {
      cancelled = true
      return { ...base, requestId, status: 'cancelled' as const, currentStage: 'cancelled' as const, progressPct: 100, errorMessage: 'Cancelled by user.' }
    })
    const fakeRequests: RequestsRepository = {
      async list() {
        return []
      },
      async getById() {
        return cancelled
          ? { ...base, status: 'cancelled', currentStage: 'cancelled', progressPct: 100, errorMessage: 'Cancelled by user.' }
          : base
      },
      async create() {
        throw new Error('not used by this test')
      },
      cancel: cancelSpy,
      async remove() {
        throw new Error('not used by this test')
      },
    }
    const fakeInsights: InsightsRepository = {
      async list() {
        return { items: [], total: 0, page: 1, pageSize: 100 }
      },
      async getById() {
        throw new Error('not used by this test')
      },
      async listRequestIds() {
        return []
      },
      async approve() {
        throw new Error('not used by this test')
      },
      async reject() {
        throw new Error('not used by this test')
      },
      async undo() {
        throw new Error('not used by this test')
      },
    }

    renderDetail('REQ_STOP', { requests: fakeRequests, insights: fakeInsights })
    await waitForLoaded()

    await user.click(screen.getByRole('button', { name: /stop generation/i }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText(/stop this request/i)).toBeInTheDocument()

    await user.click(within(dialog).getByRole('button', { name: /stop generation/i }))

    expect(cancelSpy).toHaveBeenCalledWith('REQ_STOP')
    await waitFor(() => expect(screen.getAllByText('Cancelled').length).toBeGreaterThan(0))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})

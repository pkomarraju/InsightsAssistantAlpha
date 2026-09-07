import { Route, Routes } from 'react-router-dom'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { InsightDetailPage } from '@/features/insights/InsightDetailPage'
import { renderWithProviders } from '@/test/renderWithProviders'

function renderDetail(insightId: string) {
  return renderWithProviders(
    <Routes>
      <Route path="/insights/:insightId" element={<InsightDetailPage />} />
    </Routes>,
    { route: `/insights/${insightId}` },
  )
}

async function waitForLoaded() {
  await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument())
}

function dialog() {
  return screen.getByRole('dialog')
}

describe('InsightDetailPage', () => {
  it('renders the concise finding, why it matters, recommended action, and confidence rationale', async () => {
    renderDetail('INS_001')
    await waitForLoaded()

    expect(screen.getByRole('heading', { name: /amazon relationship flagged at risk/i })).toBeInTheDocument()
    expect(screen.getByText('Concise finding')).toBeInTheDocument()
    expect(screen.getByText('Why it matters')).toBeInTheDocument()
    expect(screen.getByText('Recommended action')).toBeInTheDocument()
    expect(screen.getByText('Confidence rationale')).toBeInTheDocument()
    expect(screen.getByText(/supporting evidence/i)).toBeInTheDocument()
    expect(screen.getByText(/review history/i)).toBeInTheDocument()
  })

  it('shows credit exposure separately from business impact, and hides business impact when no estimate is supported', async () => {
    // INS_013 (Exxon Mobil, relationship_risk) documents a $10.1M credit
    // exposure with no separately calculated business-impact estimate --
    // the exposure must render under its own label, and "Business impact"
    // must not appear at all (never as the exposure figure, never as $0).
    renderDetail('INS_013')
    await waitForLoaded()

    expect(screen.getByText('Credit exposure')).toBeInTheDocument()
    expect(screen.getByText('$10.1M')).toBeInTheDocument()
    expect(screen.queryByText('Business impact')).not.toBeInTheDocument()
  })

  it('labels evidence with internal/external source, shows evidence codes and dates, and flags it as a cross-source insight', async () => {
    // INS_016 (Costco) mixes internal opportunity/interaction evidence with an external market-data signal.
    renderDetail('INS_016')
    await waitForLoaded()

    expect(screen.getAllByText('Internal').length).toBeGreaterThan(0)
    expect(screen.getByText('External')).toBeInTheDocument()
    expect(screen.getByText('SIG_COST_Q2')).toBeInTheDocument()
    // Grouped/distinguished by source agent too -- never EDGAR-branded.
    expect(screen.getByText('External data agent')).toBeInTheDocument()
    expect(screen.queryByText(/EDGAR/i)).not.toBeInTheDocument()
    // Both an internal and an external evidence item are cited together --
    // the badge that flags exactly that.
    expect(screen.getByText('Cross-source insight')).toBeInTheDocument()
  })

  it('approves after confirmation, updates the review status, and records review history', async () => {
    const user = userEvent.setup()
    renderDetail('INS_005')
    await waitForLoaded()

    await user.click(screen.getByRole('button', { name: /^approve$/i }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(within(dialog()).getByText(/approve this insight/i)).toBeInTheDocument()

    await user.click(within(dialog()).getByRole('button', { name: /^approve$/i }))

    await waitFor(() => expect(screen.getAllByText('Approved').length).toBeGreaterThan(0))
    expect(screen.getByRole('button', { name: /undo review decision/i })).toBeInTheDocument()
    expect(screen.getByText(/by alex bianchi/i)).toBeInTheDocument()
  })

  it('rejects with a required predefined reason and records it in review history', async () => {
    const user = userEvent.setup()
    renderDetail('INS_006')
    await waitForLoaded()

    await user.click(screen.getByRole('button', { name: /^reject$/i }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()

    const dialogRejectButton = within(dialog()).getByRole('button', { name: /^reject$/i })
    expect(dialogRejectButton).toBeDisabled()

    await user.click(within(dialog()).getByLabelText('Outdated'))
    expect(dialogRejectButton).toBeEnabled()
    await user.click(dialogRejectButton)

    await waitFor(() => expect(screen.getAllByText('Rejected').length).toBeGreaterThan(0))
    expect(screen.getByText(/outdated/i)).toBeInTheDocument()
    expect(screen.getByText(/by alex bianchi/i)).toBeInTheDocument()
  })

  it('undoes a review decision back to pending', async () => {
    const user = userEvent.setup()
    renderDetail('INS_003')
    await waitForLoaded()

    await user.click(screen.getByRole('button', { name: /^approve$/i }))
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: /^approve$/i }))
    await waitFor(() => expect(screen.getAllByText('Approved').length).toBeGreaterThan(0))

    await user.click(screen.getByRole('button', { name: /undo review decision/i }))

    await waitFor(() => expect(screen.getByText(/pending review/i)).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /^approve$/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^reject$/i })).toBeInTheDocument()
  })

  it('shows an error state when the insight cannot be found', async () => {
    renderDetail('NOT_A_REAL_ID')
    await waitFor(() => expect(screen.getByText(/something went wrong/i)).toBeInTheDocument())
  })
})

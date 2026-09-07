import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { RequestsListPage } from '@/features/requests/RequestsListPage'
import { renderWithProviders } from '@/test/renderWithProviders'

describe('RequestsListPage', () => {
  it('renders a loading state, then the list of requests with status badges', async () => {
    renderWithProviders(<RequestsListPage />)

    expect(screen.getByRole('status')).toBeInTheDocument()

    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument())
    expect(screen.getAllByText('Completed').length).toBeGreaterThan(0)
  })

  it('shows a progress bar for a running request', async () => {
    renderWithProviders(<RequestsListPage />)

    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument())
    expect(screen.getByLabelText(/request progress/i)).toBeInTheDocument()
  })

  it('exposes a New request action', async () => {
    renderWithProviders(<RequestsListPage />)

    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument())
    expect(screen.getByRole('button', { name: /new request/i })).toBeInTheDocument()
  })
})

import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { AssistantPage } from '@/features/assistant/AssistantPage'
import { renderWithProviders } from '@/test/renderWithProviders'

describe('AssistantPage', () => {
  it('shows the greeting message and suggested prompts once loaded', async () => {
    renderWithProviders(<AssistantPage />)

    await waitFor(() => expect(screen.getByText(/hello, i'm the insights assistant/i)).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /which companies has the relationship manager flagged at risk/i })).toBeInTheDocument()
  })

  it('sends a message and renders the assistant reply with citations', async () => {
    const user = userEvent.setup()
    renderWithProviders(<AssistantPage />)

    await waitFor(() => expect(screen.getByText(/hello, i'm the insights assistant/i)).toBeInTheDocument())

    await user.click(
      screen.getByRole('button', { name: /which companies has the relationship manager flagged at risk/i }),
    )

    expect(screen.getByText('Which companies has the relationship manager flagged at risk?')).toBeInTheDocument()

    await waitFor(
      () => expect(screen.getByText(/flagged at risk by/i)).toBeInTheDocument(),
      { timeout: 3000 },
    )
    expect(screen.getByText('RMN_007')).toBeInTheDocument()
  })

  it('disables the composer while a reply is pending', async () => {
    const user = userEvent.setup()
    renderWithProviders(<AssistantPage />)

    await waitFor(() => expect(screen.getByRole('textbox', { name: /message/i })).toBeEnabled())
    await user.type(screen.getByRole('textbox', { name: /message/i }), "What is Apple's relationship status?")
    await user.click(screen.getByRole('button', { name: /send message/i }))

    expect(screen.getByRole('textbox', { name: /message/i })).toBeDisabled()
    await waitFor(() => expect(screen.getByRole('textbox', { name: /message/i })).toBeEnabled())
  })
})

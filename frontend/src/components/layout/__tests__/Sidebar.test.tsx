import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { Sidebar } from '@/components/layout/Sidebar'

describe('Sidebar', () => {
  it('renders a link for each primary route', () => {
    render(
      <MemoryRouter initialEntries={['/assistant']}>
        <Sidebar mobileOpen={false} onCloseMobile={() => {}} />
      </MemoryRouter>,
    )

    expect(screen.getByRole('link', { name: /assistant/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /insights/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /requests/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /preferences/i })).toBeInTheDocument()
  })

  it('marks the current route as active', () => {
    render(
      <MemoryRouter initialEntries={['/insights']}>
        <Sidebar mobileOpen={false} onCloseMobile={() => {}} />
      </MemoryRouter>,
    )

    expect(screen.getByRole('link', { name: /insights/i })).toHaveClass('text-accent')
  })
})

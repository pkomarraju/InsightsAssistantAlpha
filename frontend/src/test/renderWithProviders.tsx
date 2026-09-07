import type { ReactElement } from 'react'
import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import type { Repositories } from '@/api/repositories'
import { PreferencesProvider } from '@/app/PreferencesProvider'
import { RepositoriesProvider } from '@/app/RepositoriesProvider'
import { ToastProvider } from '@/app/ToastProvider'

interface RenderOptions {
  route?: string
  overrides?: Partial<Repositories>
}

export function renderWithProviders(ui: ReactElement, { route = '/', overrides }: RenderOptions = {}) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <RepositoriesProvider overrides={overrides}>
        <PreferencesProvider>
          <ToastProvider>{ui}</ToastProvider>
        </PreferencesProvider>
      </RepositoriesProvider>
    </MemoryRouter>,
  )
}

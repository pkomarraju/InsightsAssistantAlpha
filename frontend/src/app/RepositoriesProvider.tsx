import * as React from 'react'
import { createContext, useContext, useMemo } from 'react'

import type { Repositories } from '@/api/repositories'
import { createRepositories } from '@/api/repositories'

const RepositoriesContext = createContext<Repositories | null>(null)

interface RepositoriesProviderProps {
  children: React.ReactNode
  /** Test-only seam: replaces one or more repositories with fakes (e.g. an empty insights repository). */
  overrides?: Partial<Repositories>
}

export function RepositoriesProvider({ children, overrides }: RepositoriesProviderProps) {
  const base = useMemo(() => createRepositories(), [])
  const repositories = useMemo(() => ({ ...base, ...overrides }), [base, overrides])
  return (
    <RepositoriesContext.Provider value={repositories}>{children}</RepositoriesContext.Provider>
  )
}

export function useRepositories(): Repositories {
  const context = useContext(RepositoriesContext)
  if (!context) {
    throw new Error('useRepositories must be used within a RepositoriesProvider')
  }
  return context
}

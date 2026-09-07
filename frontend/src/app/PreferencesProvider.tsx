import * as React from 'react'
import { createContext, useCallback, useContext, useEffect, useState } from 'react'

import type { UserPreferences } from '@/api/types'
import { useRepositories } from '@/app/RepositoriesProvider'

type PreferencesStatus = 'loading' | 'success' | 'error'

interface PreferencesContextValue {
  preferences: UserPreferences | null
  status: PreferencesStatus
  error: Error | null
  /** Persists a patch and updates every consumer immediately (Header, wizard defaults, this page). */
  update: (patch: Partial<UserPreferences>) => Promise<UserPreferences>
  reload: () => void
}

const PreferencesContext = createContext<PreferencesContextValue | null>(null)

/**
 * Single fetch, shared across the app, so "saved preferences" actually
 * behaves like a saved preference everywhere at once: the header identity,
 * the new-request wizard's defaults, and the preferences form itself all
 * read the same value instead of each holding an independent, potentially
 * stale copy.
 */
export function PreferencesProvider({ children }: { children: React.ReactNode }) {
  const { preferences: preferencesRepo } = useRepositories()
  const [preferences, setPreferences] = useState<UserPreferences | null>(null)
  const [status, setStatus] = useState<PreferencesStatus>('loading')
  const [error, setError] = useState<Error | null>(null)
  const [reloadToken, setReloadToken] = useState(0)

  useEffect(() => {
    let cancelled = false
    setStatus('loading')
    preferencesRepo
      .get()
      .then((data) => {
        if (!cancelled) {
          setPreferences(data)
          setStatus('success')
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err : new Error(String(err)))
          setStatus('error')
        }
      })
    return () => {
      cancelled = true
    }
  }, [preferencesRepo, reloadToken])

  const update = useCallback(
    async (patch: Partial<UserPreferences>) => {
      const updated = await preferencesRepo.update(patch)
      setPreferences(updated)
      return updated
    },
    [preferencesRepo],
  )

  const reload = useCallback(() => setReloadToken((t) => t + 1), [])

  return (
    <PreferencesContext.Provider value={{ preferences, status, error, update, reload }}>
      {children}
    </PreferencesContext.Provider>
  )
}

export function usePreferences(): PreferencesContextValue {
  const context = useContext(PreferencesContext)
  if (!context) {
    throw new Error('usePreferences must be used within a PreferencesProvider')
  }
  return context
}

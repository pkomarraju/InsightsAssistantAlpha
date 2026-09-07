import type { PreferencesRepository } from '@/api/repositories/types'
import { delay } from '@/api/mock/latency'
import { defaultPreferences } from '@/api/mock/preferences'

const STORAGE_KEY = 'insights-assistant.preferences'

function load() {
  if (typeof localStorage === 'undefined') return { ...defaultPreferences }
  const raw = localStorage.getItem(STORAGE_KEY)
  if (!raw) return { ...defaultPreferences }
  try {
    return { ...defaultPreferences, ...JSON.parse(raw) }
  } catch {
    return { ...defaultPreferences }
  }
}

function save(prefs: ReturnType<typeof load>) {
  if (typeof localStorage === 'undefined') return
  localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs))
}

export function createMockPreferencesRepository(): PreferencesRepository {
  let current = load()

  return {
    async get() {
      await delay(200)
      return current
    },

    async update(patch) {
      await delay(300)
      current = { ...current, ...patch }
      save(current)
      return current
    },
  }
}

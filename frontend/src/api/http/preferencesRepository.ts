import type { ApiClient } from '@/api/client'
import type { PreferencesRepository } from '@/api/repositories/types'
import type { UserPreferences } from '@/api/types'

/**
 * Real HTTP-backed PreferencesRepository, talking to
 * src/insights_assistant/api/server.py. Single in-memory record -- there's
 * no auth/session model yet, so this is one shared demo user, not
 * per-browser storage like the mock's localStorage.
 */
export function createHttpPreferencesRepository(client: ApiClient): PreferencesRepository {
  return {
    async get() {
      return client.get<UserPreferences>('/preferences')
    },

    async update(patch) {
      return client.patch<UserPreferences>('/preferences', patch)
    },
  }
}

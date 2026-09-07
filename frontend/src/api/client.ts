/**
 * Thin fetch wrapper reserved for when a real backend HTTP API exists.
 * Repositories depend on ApiError, not on fetch directly, so swapping a
 * mock repository for an HTTP one later doesn't touch calling components.
 */

export class ApiError extends Error {
  readonly status?: number

  constructor(message: string, status?: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export interface ApiClient {
  get<T>(path: string): Promise<T>
  post<T>(path: string, body: unknown): Promise<T>
  patch<T>(path: string, body: unknown): Promise<T>
  delete(path: string): Promise<void>
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!response.ok) {
    throw new ApiError(`Request to ${path} failed with status ${response.status}`, response.status)
  }
  return (await response.json()) as T
}

export const httpClient: ApiClient = {
  get: (path) => request(path),
  post: (path, body) => request(path, { method: 'POST', body: JSON.stringify(body) }),
  patch: (path, body) => request(path, { method: 'PATCH', body: JSON.stringify(body) }),
  // No response body expected (204 No Content) -- unlike request<T>, never
  // calls response.json() on a delete response.
  async delete(path) {
    const response = await fetch(`${API_BASE_URL}${path}`, { method: 'DELETE' })
    if (!response.ok) {
      throw new ApiError(`Request to ${path} failed with status ${response.status}`, response.status)
    }
  },
}

/** Builds a `?a=1&b=2` query string, skipping undefined/null/empty values. */
export function buildQuery(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    search.set(key, String(value))
  }
  const query = search.toString()
  return query ? `?${query}` : ''
}

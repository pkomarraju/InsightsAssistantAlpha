import { useCallback, useEffect, useRef, useState, type DependencyList } from 'react'

export type AsyncState<T> =
  | { status: 'loading'; data: null; error: null }
  | { status: 'error'; data: null; error: Error }
  | { status: 'success'; data: T; error: null }

/**
 * Standardizes loading/success/error state for a repository call so every
 * page renders the same three states consistently. Re-runs whenever a value
 * in `deps` changes; call `reload` to re-run manually (e.g. after a mutation).
 */
export function useAsync<T>(fn: () => Promise<T>, deps: DependencyList): AsyncState<T> & { reload: () => void } {
  const [state, setState] = useState<AsyncState<T>>({ status: 'loading', data: null, error: null })
  const fnRef = useRef(fn)
  fnRef.current = fn
  const [reloadToken, setReloadToken] = useState(0)

  useEffect(() => {
    let cancelled = false
    setState({ status: 'loading', data: null, error: null })

    fnRef.current()
      .then((data) => {
        if (!cancelled) setState({ status: 'success', data, error: null })
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({ status: 'error', data: null, error: error instanceof Error ? error : new Error(String(error)) })
        }
      })

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, reloadToken])

  const reload = useCallback(() => setReloadToken((t) => t + 1), [])

  return { ...state, reload }
}

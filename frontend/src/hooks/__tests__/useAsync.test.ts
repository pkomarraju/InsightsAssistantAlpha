import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { useAsync } from '@/hooks/useAsync'

describe('useAsync', () => {
  it('starts in loading state and transitions to success', async () => {
    const { result } = renderHook(() => useAsync(() => Promise.resolve('done'), []))

    expect(result.current.status).toBe('loading')

    await waitFor(() => expect(result.current.status).toBe('success'))
    expect(result.current.data).toBe('done')
    expect(result.current.error).toBeNull()
  })

  it('transitions to error state when the promise rejects', async () => {
    const { result } = renderHook(() => useAsync(() => Promise.reject(new Error('boom')), []))

    await waitFor(() => expect(result.current.status).toBe('error'))
    expect(result.current.error?.message).toBe('boom')
    expect(result.current.data).toBeNull()
  })

  it('reload re-invokes the async function', async () => {
    const fn = vi.fn().mockResolvedValue('first')
    const { result } = renderHook(() => useAsync(fn, []))

    await waitFor(() => expect(result.current.status).toBe('success'))
    expect(fn).toHaveBeenCalledTimes(1)

    act(() => result.current.reload())

    await waitFor(() => expect(fn).toHaveBeenCalledTimes(2))
  })
})

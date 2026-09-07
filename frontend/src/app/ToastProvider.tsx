import * as React from 'react'
import { createContext, useCallback, useContext, useRef, useState } from 'react'
import { CheckCircle2, X } from 'lucide-react'

import { cn } from '@/lib/utils'

interface ToastAction {
  label: string
  onClick: () => void
}

interface ToastInput {
  message: string
  action?: ToastAction
  durationMs?: number
}

interface ToastItem extends ToastInput {
  id: string
}

interface ToastContextValue {
  showToast: (toast: ToastInput) => void
}

const ToastContext = createContext<ToastContextValue | null>(null)

const DEFAULT_DURATION_MS = 6000

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>())

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
    const timer = timers.current.get(id)
    if (timer) {
      clearTimeout(timer)
      timers.current.delete(id)
    }
  }, [])

  const showToast = useCallback(
    (toast: ToastInput) => {
      const id = `toast_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
      setToasts((prev) => [...prev, { ...toast, id }])
      const timer = setTimeout(() => dismiss(id), toast.durationMs ?? DEFAULT_DURATION_MS)
      timers.current.set(id, timer)
    },
    [dismiss],
  )

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      <div
        className="pointer-events-none fixed inset-x-0 bottom-4 z-50 flex flex-col items-center gap-2 px-4"
        aria-live="polite"
      >
        {toasts.map((toast) => (
          <div
            key={toast.id}
            role="status"
            className={cn(
              'pointer-events-auto flex w-full max-w-sm items-center gap-3 rounded-lg border border-border bg-ink px-4 py-3 text-sm text-white shadow-lg',
            )}
          >
            <CheckCircle2 className="size-4 shrink-0 text-success" />
            <span className="flex-1">{toast.message}</span>
            {toast.action ? (
              <button
                type="button"
                className="cursor-pointer whitespace-nowrap font-medium text-accent-soft underline underline-offset-2 hover:text-white"
                onClick={() => {
                  toast.action?.onClick()
                  dismiss(toast.id)
                }}
              >
                {toast.action.label}
              </button>
            ) : null}
            <button
              type="button"
              aria-label="Dismiss"
              className="cursor-pointer text-white/60 hover:text-white"
              onClick={() => dismiss(toast.id)}
            >
              <X className="size-3.5" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext)
  if (!context) throw new Error('useToast must be used within a ToastProvider')
  return context
}

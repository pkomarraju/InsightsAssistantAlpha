import { AlertTriangle } from 'lucide-react'

import { Button } from '@/components/ui/button'

interface ErrorStateProps {
  title?: string
  message?: string
  onRetry?: () => void
}

export function ErrorState({ title = 'Something went wrong', message, onRetry }: ErrorStateProps) {
  return (
    <div
      role="alert"
      className="flex flex-col items-center justify-center gap-2 rounded-lg border border-danger/30 bg-danger-soft px-6 py-14 text-center"
    >
      <div className="mb-2 flex size-10 items-center justify-center rounded-full bg-surface-raised text-danger">
        <AlertTriangle className="size-5" />
      </div>
      <p className="text-sm font-medium text-danger">{title}</p>
      {message ? <p className="max-w-sm text-sm text-ink-muted">{message}</p> : null}
      {onRetry ? (
        <Button variant="secondary" size="sm" className="mt-2" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  )
}

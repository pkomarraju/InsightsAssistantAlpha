import { Skeleton } from '@/components/ui/skeleton'

export function LoadingState({ rows = 4, label }: { rows?: number; label?: string }) {
  return (
    <div className="flex flex-col gap-3" role="status" aria-live="polite">
      <span className="sr-only">{label ?? 'Loading'}</span>
      {Array.from({ length: rows }).map((_, index) => (
        <Skeleton key={index} className="h-16 w-full" />
      ))}
    </div>
  )
}

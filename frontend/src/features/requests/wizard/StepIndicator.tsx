import { Check } from 'lucide-react'

import { cn } from '@/lib/utils'
import { WIZARD_STEPS } from '@/features/requests/wizard/wizardState'

export function StepIndicator({ current }: { current: number }) {
  return (
    <ol className="mb-6 flex flex-wrap items-center gap-2" aria-label="Request steps">
      {WIZARD_STEPS.map((label, index) => {
        const state = index < current ? 'done' : index === current ? 'current' : 'upcoming'
        return (
          <li key={label} className="flex items-center gap-2">
            <span
              className={cn(
                'flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-medium',
                state === 'done' && 'bg-accent text-white',
                state === 'current' && 'border-2 border-accent text-accent',
                state === 'upcoming' && 'border border-border-strong text-ink-faint',
              )}
            >
              {state === 'done' ? <Check className="size-3.5" /> : index + 1}
            </span>
            <span className={cn('text-sm', state === 'upcoming' ? 'text-ink-faint' : 'font-medium text-ink')}>
              {label}
            </span>
            {index < WIZARD_STEPS.length - 1 ? <span className="mx-1 h-px w-6 bg-border-strong" /> : null}
          </li>
        )
      })}
    </ol>
  )
}

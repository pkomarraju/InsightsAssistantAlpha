import type { AssistantMessage } from '@/api/types'
import { formatDate } from '@/lib/format'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { AGENT_LABELS } from '@/features/assistant/agentLabels'

export function MessageBubble({ message }: { message: AssistantMessage }) {
  const isUser = message.role === 'user'

  return (
    <div className={cn('flex min-w-0 flex-col gap-1', isUser ? 'items-end' : 'items-start')}>
      {!isUser && message.activeAgent ? (
        <span className="px-1 text-xs font-medium text-ink-faint">{AGENT_LABELS[message.activeAgent]}</span>
      ) : null}
      <div
        className={cn(
          'max-w-full whitespace-pre-wrap rounded-lg px-4 py-2.5 text-sm leading-relaxed sm:max-w-2xl',
          isUser ? 'bg-accent text-white' : 'border border-border bg-surface-raised text-ink',
        )}
      >
        {message.content}
      </div>
      {message.citations && message.citations.length > 0 ? (
        <div className="flex flex-wrap gap-1.5 px-1">
          {message.citations.map((citation) => (
            <Badge key={citation.evidenceCode} variant="outline" title={citation.label}>
              {citation.evidenceCode}
            </Badge>
          ))}
        </div>
      ) : null}
      <span className="px-1 text-xs text-ink-faint">{formatDate(message.createdAt, { withTime: true })}</span>
    </div>
  )
}

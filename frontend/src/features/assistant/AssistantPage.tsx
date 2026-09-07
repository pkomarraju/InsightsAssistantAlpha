import { useEffect, useRef, useState } from 'react'

import type { AssistantMessage } from '@/api/types'
import { useRepositories } from '@/app/RepositoriesProvider'
import { useAsync } from '@/hooks/useAsync'
import { PageHeader } from '@/components/layout/PageHeader'
import { LoadingState } from '@/components/states/LoadingState'
import { ErrorState } from '@/components/states/ErrorState'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Button } from '@/components/ui/button'
import { MessageBubble } from '@/features/assistant/MessageBubble'
import { MessageComposer } from '@/features/assistant/MessageComposer'

const SUGGESTED_PROMPTS = [
  'Which companies has the relationship manager flagged at risk?',
  "What is Amazon's relationship status?",
  "What is Apple's relationship status?",
]

export function AssistantPage() {
  const { assistant } = useRepositories()
  const history = useAsync(() => assistant.getHistory(), [assistant])
  const [messages, setMessages] = useState<AssistantMessage[]>([])
  const [pending, setPending] = useState(false)
  const scrollEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (history.status === 'success') setMessages(history.data)
  }, [history.status, history.data])

  useEffect(() => {
    scrollEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, pending])

  async function handleSend(content: string) {
    const userMessage: AssistantMessage = {
      id: `MSG_USER_${Date.now()}`,
      role: 'user',
      content,
      createdAt: new Date().toISOString(),
    }
    setMessages((prev) => [...prev, userMessage])
    setPending(true)
    try {
      const reply = await assistant.sendMessage(content, [...messages, userMessage])
      setMessages((prev) => [...prev, reply])
    } finally {
      setPending(false)
    }
  }

  return (
    <div className="flex h-[calc(100dvh-6.5rem)] flex-col lg:h-[calc(100dvh-7.5rem)]">
      <PageHeader
        title="Assistant"
        description="Ask about relationship health, at-risk flags, or filing-based signals. Answers cite the underlying evidence."
      />

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-border bg-surface">
        <ScrollArea className="min-h-0 flex-1">
          <div className="flex flex-col gap-5 p-4">
            {history.status === 'loading' ? <LoadingState label="Loading conversation" /> : null}
            {history.status === 'error' ? <ErrorState message={history.error.message} onRetry={history.reload} /> : null}
            {history.status === 'success' ? (
              <>
                {messages.map((message) => (
                  <MessageBubble key={message.id} message={message} />
                ))}
                {pending ? (
                  <div className="flex items-center gap-2 px-1 text-sm text-ink-faint">
                    <span className="size-1.5 animate-pulse rounded-full bg-ink-faint" />
                    <span className="size-1.5 animate-pulse rounded-full bg-ink-faint [animation-delay:150ms]" />
                    <span className="size-1.5 animate-pulse rounded-full bg-ink-faint [animation-delay:300ms]" />
                    Thinking…
                  </div>
                ) : null}
                {messages.length <= 1 && !pending ? (
                  <div className="flex flex-wrap gap-2 px-1 pt-2">
                    {SUGGESTED_PROMPTS.map((prompt) => (
                      <Button
                        key={prompt}
                        variant="secondary"
                        size="sm"
                        className="h-auto max-w-full whitespace-normal text-left"
                        onClick={() => handleSend(prompt)}
                      >
                        {prompt}
                      </Button>
                    ))}
                  </div>
                ) : null}
              </>
            ) : null}
            <div ref={scrollEndRef} />
          </div>
        </ScrollArea>

        <MessageComposer onSend={handleSend} disabled={pending || history.status !== 'success'} />
      </div>
    </div>
  )
}

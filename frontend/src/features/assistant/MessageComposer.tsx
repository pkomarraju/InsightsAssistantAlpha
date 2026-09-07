import { useState, type KeyboardEvent } from 'react'
import { Send } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'

interface MessageComposerProps {
  onSend: (content: string) => void
  disabled?: boolean
}

export function MessageComposer({ onSend, disabled }: MessageComposerProps) {
  const [value, setValue] = useState('')

  const submit = () => {
    const trimmed = value.trim()
    if (!trimmed || disabled) return
    onSend(trimmed)
    setValue('')
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <div className="flex items-end gap-2 border-t border-border bg-surface-raised p-3">
      <Textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Ask about a client relationship, an at-risk flag, or a filing-based signal…"
        className="min-h-11 flex-1 resize-none"
        rows={1}
        disabled={disabled}
        aria-label="Message"
      />
      <Button size="icon" onClick={submit} disabled={disabled || !value.trim()} aria-label="Send message">
        <Send className="size-4" />
      </Button>
    </div>
  )
}

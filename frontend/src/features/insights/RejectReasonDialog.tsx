import { useState } from 'react'
import { Loader2 } from 'lucide-react'

import type { Insight, RejectReason } from '@/api/types'
import { REJECT_REASON_LABELS } from '@/components/domain/badges'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'

const REJECT_REASONS: RejectReason[] = [
  'incorrect',
  'insufficient_evidence',
  'duplicate',
  'not_material',
  'outdated',
  'wrong_audience',
  'action_not_useful',
]

interface RejectReasonDialogProps {
  insight: Insight | null
  busy: boolean
  onOpenChange: (open: boolean) => void
  onConfirm: (reason: RejectReason) => void
  /** Called instead of Radix's default close-focus heuristic; caller decides what to refocus. */
  onCloseAutoFocus?: (event: Event) => void
}

export function RejectReasonDialog({ insight, busy, onOpenChange, onConfirm, onCloseAutoFocus }: RejectReasonDialogProps) {
  const [reason, setReason] = useState<RejectReason | ''>('')

  const handleOpenChange = (open: boolean) => {
    if (!open) setReason('')
    onOpenChange(open)
  }

  return (
    <Dialog open={insight !== null} onOpenChange={handleOpenChange}>
      <DialogContent onCloseAutoFocus={onCloseAutoFocus}>
        <DialogHeader>
          <DialogTitle>Reject this insight</DialogTitle>
          <DialogDescription>
            {insight ? <>Select a reason for rejecting "{insight.title}".</> : null}
          </DialogDescription>
        </DialogHeader>

        <RadioGroup value={reason} onValueChange={(v) => setReason(v as RejectReason)} className="flex flex-col gap-2.5">
          {REJECT_REASONS.map((r) => (
            <label key={r} htmlFor={`reject-${r}`} className="flex cursor-pointer items-center gap-2.5 text-sm text-ink">
              <RadioGroupItem value={r} id={`reject-${r}`} />
              <Label htmlFor={`reject-${r}`} className="cursor-pointer font-normal">
                {REJECT_REASON_LABELS[r]}
              </Label>
            </label>
          ))}
        </RadioGroup>

        <DialogFooter>
          <Button variant="secondary" onClick={() => handleOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={() => reason && onConfirm(reason)} disabled={busy || !reason}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : null}
            Reject
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

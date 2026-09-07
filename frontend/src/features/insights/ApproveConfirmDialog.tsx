import { Loader2 } from 'lucide-react'

import type { Insight } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'

interface ApproveConfirmDialogProps {
  insight: Insight | null
  busy: boolean
  onOpenChange: (open: boolean) => void
  onConfirm: () => void
  /** Called instead of Radix's default close-focus heuristic; caller decides what to refocus. */
  onCloseAutoFocus?: (event: Event) => void
}

export function ApproveConfirmDialog({ insight, busy, onOpenChange, onConfirm, onCloseAutoFocus }: ApproveConfirmDialogProps) {
  return (
    <Dialog open={insight !== null} onOpenChange={onOpenChange}>
      <DialogContent onCloseAutoFocus={onCloseAutoFocus}>
        <DialogHeader>
          <DialogTitle>Approve this insight?</DialogTitle>
          <DialogDescription>
            {insight ? (
              <>
                "{insight.title}" will be marked approved immediately and routed to{' '}
                {insight.companyName}'s account team.
              </>
            ) : null}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={onConfirm} disabled={busy}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : null}
            Approve
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

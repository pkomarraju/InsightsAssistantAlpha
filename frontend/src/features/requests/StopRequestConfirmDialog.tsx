import { Loader2 } from 'lucide-react'

import type { ResearchRequest } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'

interface StopRequestConfirmDialogProps {
  request: ResearchRequest | null
  busy: boolean
  onOpenChange: (open: boolean) => void
  onConfirm: () => void
  /** Called instead of Radix's default close-focus heuristic; caller decides what to refocus. */
  onCloseAutoFocus?: (event: Event) => void
}

export function StopRequestConfirmDialog({ request, busy, onOpenChange, onConfirm, onCloseAutoFocus }: StopRequestConfirmDialogProps) {
  return (
    <Dialog open={request !== null} onOpenChange={onOpenChange}>
      <DialogContent onCloseAutoFocus={onCloseAutoFocus}>
        <DialogHeader>
          <DialogTitle>Stop this request?</DialogTitle>
          <DialogDescription>
            {request ? (
              <>
                Research, synthesis, and review for {request.requestId} will stop immediately. Nothing
                generated so far will be saved, and this can't be undone.
              </>
            ) : null}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={busy}>
            Keep running
          </Button>
          <Button variant="destructive" onClick={onConfirm} disabled={busy}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : null}
            Stop generation
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

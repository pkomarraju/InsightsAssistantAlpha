import { Loader2 } from 'lucide-react'

import type { ResearchRequest } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'

interface DeleteRequestConfirmDialogProps {
  request: ResearchRequest | null
  busy: boolean
  onOpenChange: (open: boolean) => void
  onConfirm: () => void
  /** Called instead of Radix's default close-focus heuristic; caller decides what to refocus. */
  onCloseAutoFocus?: (event: Event) => void
}

const IN_FLIGHT_STATUSES: ResearchRequest['status'][] = ['draft', 'queued', 'running']

export function DeleteRequestConfirmDialog({
  request,
  busy,
  onOpenChange,
  onConfirm,
  onCloseAutoFocus,
}: DeleteRequestConfirmDialogProps) {
  const isInFlight = request ? IN_FLIGHT_STATUSES.includes(request.status) : false

  return (
    <Dialog open={request !== null} onOpenChange={onOpenChange}>
      <DialogContent onCloseAutoFocus={onCloseAutoFocus}>
        <DialogHeader>
          <DialogTitle>Delete this request?</DialogTitle>
          <DialogDescription>
            {request ? (
              <>
                {request.requestId} and its {request.resultInsightIds.length} generated insight
                {request.resultInsightIds.length === 1 ? '' : 's'} will be permanently removed.
                {isInFlight ? ' Generation in progress will stop immediately.' : ''} This can't be undone.
              </>
            ) : null}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={onConfirm} disabled={busy}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : null}
            Delete request
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

import { useRef, useState } from 'react'

import type { Insight, RejectReason } from '@/api/types'
import { useRepositories } from '@/app/RepositoriesProvider'
import { useToast } from '@/app/ToastProvider'

/**
 * Shared approve/reject/undo orchestration used by both the insights table
 * and the detail page: owns the confirm/reject dialog state, calls the
 * repository, and shows an undo-able toast on success. `onUpdated` lets the
 * caller patch its own local list/detail state so the UI reflects the
 * change immediately without a refetch.
 *
 * Also owns explicit focus restoration: these dialogs are opened from many
 * different trigger buttons (one per table row, or the detail page's
 * header), so rather than relying on Radix's default close-focus heuristic
 * (which doesn't reliably find the right element across a dynamic list),
 * we capture whatever was focused right before opening and hand it back to
 * `restoreFocus` for the dialog's `onCloseAutoFocus` to use.
 */
export function useInsightReviewActions(onUpdated: (insight: Insight) => void) {
  const { insights } = useRepositories()
  const { showToast } = useToast()

  const [approveTarget, setApproveTarget] = useState<Insight | null>(null)
  const [rejectTarget, setRejectTarget] = useState<Insight | null>(null)
  const [busy, setBusy] = useState(false)
  const triggerElementRef = useRef<HTMLElement | null>(null)

  function openApprove(insight: Insight) {
    triggerElementRef.current = document.activeElement as HTMLElement | null
    setApproveTarget(insight)
  }

  function openReject(insight: Insight) {
    triggerElementRef.current = document.activeElement as HTMLElement | null
    setRejectTarget(insight)
  }

  function restoreFocus() {
    triggerElementRef.current?.focus()
  }

  async function confirmApprove() {
    if (!approveTarget) return
    setBusy(true)
    try {
      const updated = await insights.approve(approveTarget.id)
      onUpdated(updated)
      setApproveTarget(null)
      showToast({
        message: `"${updated.title}" approved.`,
        action: {
          label: 'Undo',
          onClick: async () => {
            const reverted = await insights.undo(updated.id)
            onUpdated(reverted)
          },
        },
      })
    } finally {
      setBusy(false)
    }
  }

  async function confirmReject(reason: RejectReason) {
    if (!rejectTarget) return
    setBusy(true)
    try {
      const updated = await insights.reject(rejectTarget.id, reason)
      onUpdated(updated)
      setRejectTarget(null)
      showToast({
        message: `"${updated.title}" rejected.`,
        action: {
          label: 'Undo',
          onClick: async () => {
            const reverted = await insights.undo(updated.id)
            onUpdated(reverted)
          },
        },
      })
    } finally {
      setBusy(false)
    }
  }

  return {
    approveTarget,
    rejectTarget,
    busy,
    openApprove,
    openReject,
    closeApprove: () => setApproveTarget(null),
    closeReject: () => setRejectTarget(null),
    confirmApprove,
    confirmReject,
    restoreFocus,
  }
}

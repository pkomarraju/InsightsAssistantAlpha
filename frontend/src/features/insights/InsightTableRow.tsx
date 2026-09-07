import { Link } from 'react-router-dom'
import { Check, Undo2, X } from 'lucide-react'

import type { Insight } from '@/api/types'
import { formatBusinessImpact, formatDate } from '@/lib/format'
import { CategoryBadge, PriorityBadge, ReviewStatusBadge, SubtypeBadge } from '@/components/domain/badges'
import { Button } from '@/components/ui/button'
import { TableCell, TableRow } from '@/components/ui/table'

interface InsightTableRowProps {
  insight: Insight
  onApprove: (insight: Insight) => void
  onReject: (insight: Insight) => void
  onUndo: (insight: Insight) => void
}

export function InsightTableRow({ insight, onApprove, onReject, onUndo }: InsightTableRowProps) {
  const monetary = formatBusinessImpact(insight.businessImpact)
  return (
    <TableRow>
      <TableCell className="max-w-72">
        <Link to={`/insights/${insight.id}`} className="font-medium text-ink hover:text-accent hover:underline">
          {insight.title}
        </Link>
      </TableCell>
      <TableCell className="whitespace-nowrap">{insight.companyName}</TableCell>
      <TableCell>
        <div className="flex flex-col items-start gap-1">
          <CategoryBadge category={insight.category} />
          <SubtypeBadge subtype={insight.subtype} />
        </div>
      </TableCell>
      <TableCell>
        <PriorityBadge priority={insight.priority} />
      </TableCell>
      <TableCell className="whitespace-nowrap">{insight.confidence}%</TableCell>
      <TableCell className="whitespace-nowrap">
        {monetary.estimatedImpact !== null ? (
          monetary.estimatedImpact
        ) : monetary.exposure !== null ? (
          <span className="text-ink-faint">
            {monetary.exposure} <span className="text-xs">exposure</span>
          </span>
        ) : (
          '—'
        )}
      </TableCell>
      <TableCell className="whitespace-nowrap">{formatDate(insight.generatedAt)}</TableCell>
      <TableCell className="whitespace-nowrap font-mono text-xs text-ink-faint">{insight.requestId}</TableCell>
      <TableCell>
        <ReviewStatusBadge status={insight.reviewStatus} />
      </TableCell>
      <TableCell>
        {insight.reviewStatus === 'pending' ? (
          <div className="flex items-center gap-1.5">
            <Button variant="secondary" size="sm" onClick={() => onApprove(insight)} aria-label={`Approve ${insight.title}`}>
              <Check className="size-3.5" />
              Approve
            </Button>
            <Button variant="outline" size="sm" onClick={() => onReject(insight)} aria-label={`Reject ${insight.title}`}>
              <X className="size-3.5" />
              Reject
            </Button>
          </div>
        ) : (
          <Button variant="ghost" size="sm" onClick={() => onUndo(insight)} aria-label={`Undo review decision for ${insight.title}`}>
            <Undo2 className="size-3.5" />
            Undo
          </Button>
        )}
      </TableCell>
    </TableRow>
  )
}

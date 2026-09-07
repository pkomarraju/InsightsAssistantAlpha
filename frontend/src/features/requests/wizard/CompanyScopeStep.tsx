import type { Company, RelationshipStatus } from '@/api/types'
import { RelationshipStatusBadge } from '@/components/domain/badges'
import { Checkbox } from '@/components/ui/checkbox'
import type { RelationshipSnapshot } from '@/api/types'

interface CompanyScopeStepProps {
  companies: Company[]
  snapshots: RelationshipSnapshot[]
  selected: string[]
  onToggle: (companyId: string) => void
}

// Maps target_companies.current_status's human-readable values onto the
// existing RelationshipStatus badge's keys, so a newer API response reuses
// the same visual treatment rather than a second status component.
const CURRENT_STATUS_TO_RELATIONSHIP_STATUS: Record<NonNullable<Company['currentStatus']>, RelationshipStatus> = {
  'At risk': 'at_risk',
  'Developing opportunity': 'developing_opportunity',
  Stable: 'stable',
  Strong: 'strong',
}

export function CompanyScopeStep({ companies, snapshots, selected, onToggle }: CompanyScopeStepProps) {
  return (
    <div className="flex flex-col gap-1">
      <p className="mb-2 text-sm text-ink-muted">Select the companies to research in this request.</p>
      <div className="grid gap-2 sm:grid-cols-2">
        {companies.map((company) => {
          const snapshot = snapshots.find((s) => s.companyId === company.companyId)
          const checked = selected.includes(company.companyId)
          // Prefer the newer target_companies status when the API supplies
          // one; fall back to the original relationship-snapshot status.
          // Never both, and never a fabricated value when neither is present.
          const status = company.currentStatus
            ? CURRENT_STATUS_TO_RELATIONSHIP_STATUS[company.currentStatus]
            : snapshot?.relationshipStatus
          return (
            <label
              key={company.companyId}
              className="flex cursor-pointer items-center gap-3 rounded-md border border-border bg-surface-raised p-3 text-sm hover:bg-surface-hover has-[[data-state=checked]]:border-accent-soft-border has-[[data-state=checked]]:bg-accent-soft"
            >
              <Checkbox checked={checked} onCheckedChange={() => onToggle(company.companyId)} />
              <span className="min-w-0 flex-1">
                <span className="block font-medium text-ink">
                  {company.companyName} <span className="text-ink-faint">({company.ticker})</span>
                </span>
                <span className="block text-xs text-ink-faint">
                  {company.industry}
                  {company.internalCoverageLead ? ` · ${company.internalCoverageLead}` : ''}
                </span>
              </span>
              {status ? <RelationshipStatusBadge status={status} /> : null}
            </label>
          )
        })}
      </div>
    </div>
  )
}

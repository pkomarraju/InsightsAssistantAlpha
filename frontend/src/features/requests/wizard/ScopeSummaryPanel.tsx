import type { ReactNode } from 'react'

import type { Company } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import {
  CATEGORY_OPTIONS,
  DATA_DOMAIN_OPTIONS,
  EXTERNAL_PROVIDER_OPTIONS,
  type WizardState,
} from '@/features/requests/wizard/wizardState'

interface ScopeSummaryPanelProps {
  state: WizardState
  companies: Company[]
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wide text-ink-faint">{label}</p>
      <div className="mt-1.5">{children}</div>
    </div>
  )
}

/**
 * Live scope summary shown alongside every wizard step (not just Review),
 * so the banker always sees the request scope they've accumulated so far.
 * It renders directly from the same `state` object the steps mutate, so it
 * cannot drift out of sync with what's actually selected.
 */
export function ScopeSummaryPanel({ state, companies }: ScopeSummaryPanelProps) {
  const selectedCompanies = companies.filter((c) => state.companyIds.includes(c.companyId))

  return (
    <Card className="lg:sticky lg:top-6">
      <CardHeader>
        <CardTitle>Request scope</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <Row label={`Companies (${selectedCompanies.length})`}>
          {selectedCompanies.length === 0 ? (
            <p className="text-sm text-ink-faint">None selected yet</p>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {selectedCompanies.map((c) => (
                <Badge key={c.companyId} variant="outline">
                  {c.companyName}
                </Badge>
              ))}
            </div>
          )}
        </Row>

        <Separator />

        <Row label="External research">
          <p className="text-sm text-ink-muted">
            {state.externalResearchEnabled
              ? state.externalProviders.length > 0
                ? state.externalProviders.map((id) => EXTERNAL_PROVIDER_OPTIONS.find((p) => p.id === id)?.label ?? id).join(', ')
                : 'Enabled, no providers selected'
              : 'Disabled'}
          </p>
        </Row>

        <Row label={`Internal datasets (${state.dataDomainIds.length})`}>
          {state.dataDomainIds.length === 0 ? (
            <p className="text-sm text-ink-faint">None selected yet</p>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {state.dataDomainIds.map((id) => (
                <Badge key={id} variant="outline">
                  {DATA_DOMAIN_OPTIONS.find((d) => d.id === id)?.label ?? id}
                </Badge>
              ))}
            </div>
          )}
        </Row>

        <Separator />

        <Row label={`Focus areas (${state.categories.length})`}>
          {state.categories.length === 0 ? (
            <p className="text-sm text-ink-faint">None selected yet</p>
          ) : (
            <ul className="flex flex-col gap-1 text-sm text-ink-muted">
              {state.categories.map((c) => (
                <li key={c.categoryId}>{CATEGORY_OPTIONS.find((o) => o.id === c.categoryId)?.label}</li>
              ))}
            </ul>
          )}
        </Row>

        <Row label="Target insight count">
          <p className="text-sm text-ink-muted">{state.totalCount}</p>
        </Row>
      </CardContent>
    </Card>
  )
}

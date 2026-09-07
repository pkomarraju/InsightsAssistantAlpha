import type { Company } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  CATEGORY_OPTIONS,
  DATA_DOMAIN_OPTIONS,
  EXTERNAL_PROVIDER_OPTIONS,
  RANKING_OPTIONS,
} from '@/features/requests/wizard/wizardState'
import type { WizardState } from '@/features/requests/wizard/wizardState'

export function ReviewStep({ state, companies }: { state: WizardState; companies: Company[] }) {
  const selectedCompanies = companies.filter((c) => state.companyIds.includes(c.companyId))

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Company scope</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-1.5">
            {selectedCompanies.map((c) => (
              <Badge key={c.companyId} variant="outline">
                {c.companyName}
              </Badge>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Internal datasets</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-1.5">
            {state.dataDomainIds.map((id) => (
              <Badge key={id} variant="outline">
                {DATA_DOMAIN_OPTIONS.find((d) => d.id === id)?.label ?? id}
              </Badge>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>External providers</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-ink-muted">
            {!state.externalResearchEnabled ? (
              <p>Disabled</p>
            ) : state.externalProviders.length === 0 ? (
              <p>Enabled, no providers selected</p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {state.externalProviders.map((id) => (
                  <Badge key={id} variant="outline">
                    {EXTERNAL_PROVIDER_OPTIONS.find((p) => p.id === id)?.label ?? id}
                  </Badge>
                ))}
              </div>
            )}
            <p className="mt-2 text-xs text-ink-faint">Lookback: {state.lookbackMonths} months</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Insight requirements</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-ink-muted">
            <p>Target: up to {state.totalCount} insights</p>
            <ul className="mt-1 list-disc pl-4">
              {state.categories.map((c) => (
                <li key={c.categoryId}>{CATEGORY_OPTIONS.find((o) => o.id === c.categoryId)?.label}</li>
              ))}
            </ul>
            <p className="mt-2 text-xs text-ink-faint">
              Ranked by {state.rankingCriteria.map((id) => RANKING_OPTIONS.find((o) => o.id === id)?.label ?? id).join(', ')}
            </p>
          </CardContent>
        </Card>

        <Card className="sm:col-span-2">
          <CardHeader>
            <CardTitle>Search prompt</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-ink-muted">
            {state.generalSearchPrompt || <span className="italic text-ink-faint">No prompt provided</span>}
          </CardContent>
        </Card>
      </div>

      <p className="text-xs text-ink-faint">
        Internal company context guides targeted external research. Findings are then combined and
        reviewed with source-level evidence.
      </p>
    </div>
  )
}

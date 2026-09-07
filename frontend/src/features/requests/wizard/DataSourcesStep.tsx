import { Checkbox } from '@/components/ui/checkbox'
import { Badge } from '@/components/ui/badge'
import {
  ALWAYS_INCLUDED_DOMAIN_ID,
  DATA_DOMAIN_OPTIONS,
  EXTERNAL_PROVIDER_OPTIONS,
} from '@/features/requests/wizard/wizardState'

interface DataSourcesStepProps {
  externalResearchEnabled: boolean
  externalProviders: string[]
  dataDomainIds: string[]
  onChange: (patch: Partial<{
    externalResearchEnabled: boolean
    externalProviders: string[]
    dataDomainIds: string[]
  }>) => void
}

export function DataSourcesStep({
  externalResearchEnabled, externalProviders, dataDomainIds, onChange,
}: DataSourcesStepProps) {
  const toggleDomain = (id: string) => {
    if (id === ALWAYS_INCLUDED_DOMAIN_ID) return // always included, never toggleable
    onChange({
      dataDomainIds: dataDomainIds.includes(id) ? dataDomainIds.filter((d) => d !== id) : [...dataDomainIds, id],
    })
  }

  const toggleProvider = (id: string) => {
    onChange({
      externalProviders: externalProviders.includes(id)
        ? externalProviders.filter((p) => p !== id)
        : [...externalProviders, id],
    })
  }

  return (
    <div className="flex flex-col gap-6">
      <section>
        <h3 className="mb-2 text-sm font-semibold text-ink">Internal bank data</h3>
        <div className="grid gap-2 sm:grid-cols-2">
          {DATA_DOMAIN_OPTIONS.map((domain) => {
            const alwaysIncluded = domain.id === ALWAYS_INCLUDED_DOMAIN_ID
            const checked = alwaysIncluded || dataDomainIds.includes(domain.id)
            return (
              <label
                key={domain.id}
                className="flex items-start gap-3 rounded-md border border-border bg-surface-raised p-3 text-sm hover:bg-surface-hover has-[[data-state=checked]]:border-accent-soft-border has-[[data-state=checked]]:bg-accent-soft"
              >
                <Checkbox checked={checked} disabled={alwaysIncluded} onCheckedChange={() => toggleDomain(domain.id)} />
                <span>
                  <span className="flex items-center gap-1.5">
                    <span className="block font-medium text-ink">{domain.label}</span>
                    {alwaysIncluded ? (
                      <Badge variant="outline" className="text-[10px]">
                        Always included
                      </Badge>
                    ) : null}
                  </span>
                  <span className="block text-xs text-ink-faint">{domain.description}</span>
                </span>
              </label>
            )
          })}
        </div>
      </section>

      <section>
        <h3 className="mb-2 text-sm font-semibold text-ink">External market data</h3>
        <label className="flex items-center gap-2 text-sm text-ink">
          <Checkbox
            checked={externalResearchEnabled}
            onCheckedChange={(checked) => onChange({ externalResearchEnabled: checked === true })}
          />
          Enable external market research
        </label>
        <div className="mt-3 flex flex-col gap-2 rounded-md border border-border bg-surface-raised p-4">
          {EXTERNAL_PROVIDER_OPTIONS.map((provider) => (
            <label
              key={provider.id}
              className={`flex items-start gap-3 text-sm ${externalResearchEnabled ? 'text-ink' : 'text-ink-faint'}`}
            >
              <Checkbox
                checked={externalProviders.includes(provider.id)}
                disabled={!externalResearchEnabled}
                onCheckedChange={() => toggleProvider(provider.id)}
              />
              <span>
                <span className="block font-medium">{provider.label}</span>
                <span className="block text-xs text-ink-faint">{provider.description}</span>
              </span>
            </label>
          ))}
        </div>
      </section>
    </div>
  )
}

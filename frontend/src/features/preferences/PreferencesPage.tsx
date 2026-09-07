import { useEffect, useState } from 'react'
import { Check } from 'lucide-react'

import type { UserPreferences } from '@/api/types'
import { usePreferences } from '@/app/PreferencesProvider'
import { PageHeader } from '@/components/layout/PageHeader'
import { LoadingState } from '@/components/states/LoadingState'
import { ErrorState } from '@/components/states/ErrorState'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { DATA_DOMAIN_OPTIONS, RANKING_OPTIONS } from '@/features/requests/wizard/wizardState'

export function PreferencesPage() {
  const { preferences, status, error, update, reload } = usePreferences()
  const [draft, setDraft] = useState<UserPreferences | null>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (status === 'success' && preferences) setDraft(preferences)
  }, [status, preferences])

  if (status === 'loading') {
    return (
      <div>
        <PageHeader title="Preferences" description="Defaults applied to new research requests and alerts." />
        <LoadingState rows={4} label="Loading preferences" />
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div>
        <PageHeader title="Preferences" description="Defaults applied to new research requests and alerts." />
        <ErrorState message={error?.message} onRetry={reload} />
      </div>
    )
  }

  if (!draft) return null

  const patch = (p: Partial<UserPreferences>) => {
    setDraft((prev) => (prev ? { ...prev, ...p } : prev))
    setSaved(false)
  }

  const toggleDomain = (id: string) => {
    patch({
      defaultDataDomains: draft.defaultDataDomains.includes(id)
        ? draft.defaultDataDomains.filter((d) => d !== id)
        : [...draft.defaultDataDomains, id],
    })
  }

  const toggleRanking = (id: UserPreferences['defaultRankingCriteria'][number]) => {
    patch({
      defaultRankingCriteria: draft.defaultRankingCriteria.includes(id)
        ? draft.defaultRankingCriteria.filter((r) => r !== id)
        : [...draft.defaultRankingCriteria, id],
    })
  }

  async function handleSave() {
    if (!draft) return
    setSaving(true)
    try {
      const updated = await update(draft)
      setDraft(updated)
      setSaved(true)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="max-w-2xl">
      <PageHeader
        title="Preferences"
        description="Defaults applied to new research requests and alerts."
        actions={
          <Button onClick={handleSave} disabled={saving}>
            {saved ? <Check className="size-4" /> : null}
            {saving ? 'Saving…' : saved ? 'Saved' : 'Save changes'}
          </Button>
        }
      />

      <div className="flex flex-col gap-4">
        <Card>
          <CardHeader>
            <CardTitle>Profile</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <div>
              <Label htmlFor="displayName" className="mb-1.5 block text-xs font-medium text-ink-muted">
                Display name
              </Label>
              <Input id="displayName" value={draft.displayName} onChange={(e) => patch({ displayName: e.target.value })} />
            </div>
            <div>
              <Label htmlFor="role" className="mb-1.5 block text-xs font-medium text-ink-muted">
                Role
              </Label>
              <Input id="role" value={draft.role} onChange={(e) => patch({ role: e.target.value })} />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Default data domains</CardTitle>
            <CardDescription>Pre-selected when starting a new research request.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-2 sm:grid-cols-2">
            {DATA_DOMAIN_OPTIONS.map((domain) => (
              <label key={domain.id} className="flex items-center gap-2 text-sm text-ink">
                <Checkbox
                  checked={draft.defaultDataDomains.includes(domain.id)}
                  onCheckedChange={() => toggleDomain(domain.id)}
                />
                {domain.label}
              </label>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Default ranking criteria</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-4">
            {RANKING_OPTIONS.map((option) => (
              <label key={option.id} className="flex items-center gap-2 text-sm text-ink">
                <Checkbox
                  checked={draft.defaultRankingCriteria.includes(option.id)}
                  onCheckedChange={() => toggleRanking(option.id)}
                />
                {option.label}
              </label>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Alerts</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <label className="flex items-center gap-2 text-sm text-ink">
              <Checkbox
                checked={draft.emailDigestEnabled}
                onCheckedChange={(checked) => patch({ emailDigestEnabled: checked === true })}
              />
              Send a weekly email digest of new insights
            </label>
            <label className="flex items-center gap-2 text-sm text-ink">
              <Checkbox
                checked={draft.atRiskAlertsEnabled}
                onCheckedChange={(checked) => patch({ atRiskAlertsEnabled: checked === true })}
              />
              Alert me immediately when a relationship is flagged at risk
            </label>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Display density</CardTitle>
          </CardHeader>
          <CardContent>
            <RadioGroup
              value={draft.displayDensity}
              onValueChange={(v) => patch({ displayDensity: v as UserPreferences['displayDensity'] })}
              className="flex gap-6"
            >
              <label className="flex items-center gap-2 text-sm text-ink">
                <RadioGroupItem value="comfortable" />
                Comfortable
              </label>
              <label className="flex items-center gap-2 text-sm text-ink">
                <RadioGroupItem value="compact" />
                Compact
              </label>
            </RadioGroup>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

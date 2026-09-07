import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, ArrowRight, Loader2 } from 'lucide-react'

import { usePreferences } from '@/app/PreferencesProvider'
import { useRepositories } from '@/app/RepositoriesProvider'
import { useAsync } from '@/hooks/useAsync'
import { PageHeader } from '@/components/layout/PageHeader'
import { LoadingState } from '@/components/states/LoadingState'
import { ErrorState } from '@/components/states/ErrorState'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { CompanyScopeStep } from '@/features/requests/wizard/CompanyScopeStep'
import { DataSourcesStep } from '@/features/requests/wizard/DataSourcesStep'
import { RequirementsStep } from '@/features/requests/wizard/RequirementsStep'
import { ReviewStep } from '@/features/requests/wizard/ReviewStep'
import { ScopeSummaryPanel } from '@/features/requests/wizard/ScopeSummaryPanel'
import { StepIndicator } from '@/features/requests/wizard/StepIndicator'
import {
  buildDefaultSearchPrompt,
  buildInitialWizardState,
  WIZARD_STEPS,
  type WizardState,
} from '@/features/requests/wizard/wizardState'

export function NewRequestPage() {
  const { companies, requests } = useRepositories()
  const { preferences } = usePreferences()
  const navigate = useNavigate()
  const companiesResult = useAsync(() => companies.list(), [companies])
  const snapshotsResult = useAsync(() => companies.listSnapshots(), [companies])

  const [state, setState] = useState<WizardState>(() => buildInitialWizardState(preferences))
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  // Preferences usually load before this route is reached (fetched once at
  // app mount), but guard the case where a banker navigates here before
  // that resolves: apply preferences the moment they arrive, as long as the
  // wizard is still untouched (step 0, nothing selected yet) so we never
  // clobber in-progress input.
  const appliedPreferencesRef = useRef(false)
  useEffect(() => {
    if (appliedPreferencesRef.current || !preferences) return
    appliedPreferencesRef.current = true
    setState((prev) => (prev.step === 0 && prev.companyIds.length === 0 ? buildInitialWizardState(preferences) : prev))
  }, [preferences])

  const patch = (p: Partial<WizardState>) => setState((prev) => ({ ...prev, ...p }))

  const toggleCompany = (companyId: string) => {
    patch({
      companyIds: state.companyIds.includes(companyId)
        ? state.companyIds.filter((id) => id !== companyId)
        : [...state.companyIds, companyId],
    })
  }

  // The search prompt is auto-composed from the selections below (see
  // buildDefaultSearchPrompt) so the wizard never requires typing to
  // advance. Track whether the banker has since hand-edited it so their
  // edit is never silently overwritten.
  const promptTouchedRef = useRef(false)
  useEffect(() => {
    if (promptTouchedRef.current) return
    if (companiesResult.status !== 'success') return
    const selected = companiesResult.data.filter((c) => state.companyIds.includes(c.companyId))
    const generated = buildDefaultSearchPrompt(selected, state.categories)
    setState((prev) => (prev.generalSearchPrompt === generated ? prev : { ...prev, generalSearchPrompt: generated }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.companyIds, state.categories, companiesResult.status])

  const canAdvance = (() => {
    switch (state.step) {
      case 0:
        return state.companyIds.length > 0
      case 1:
        return state.dataDomainIds.length > 0
      case 2:
        return state.categories.length > 0
      default:
        return true
    }
  })()

  async function handleSubmit() {
    setSubmitting(true)
    setSubmitError(null)
    try {
      const request = await requests.create({
        companyIds: state.companyIds,
        dataDomainIds: state.dataDomainIds,
        generalSearchPrompt: state.generalSearchPrompt,
        // Provider-neutral fields the current backend contract reads.
        enabled: state.externalResearchEnabled,
        providers: state.externalProviders,
        // Deprecated fields the backend still requires on the wire (see
        // CreateRequestInput) -- kept here, in this one adapter call, so
        // nothing else in the app ever needs to know EDGAR terminology.
        edgarEnabled: state.externalResearchEnabled,
        filingTypes: [],
        lookbackMonths: state.lookbackMonths,
        totalCount: state.totalCount,
        categories: state.categories,
        rankingCriteria: state.rankingCriteria,
      })
      navigate(`/requests/${request.requestId}`)
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : 'Failed to submit request')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div>
      <Button variant="ghost" size="sm" className="mb-3 -ml-2" onClick={() => navigate('/requests')}>
        <ArrowLeft className="size-4" />
        Back to requests
      </Button>
      <PageHeader title="New research request" description="Scope a guided research job for the assistant to run." />

      <StepIndicator current={state.step} />

      {(companiesResult.status === 'loading' || snapshotsResult.status === 'loading') ? (
        <LoadingState rows={4} label="Loading company data" />
      ) : null}
      {companiesResult.status === 'error' ? (
        <ErrorState message={companiesResult.error.message} onRetry={companiesResult.reload} />
      ) : null}

      {companiesResult.status === 'success' && snapshotsResult.status === 'success' ? (
        <div className="grid gap-4 lg:grid-cols-3 lg:items-start">
          <Card className="lg:col-span-2">
            <CardContent className="p-5">
              {state.step === 0 ? (
                <CompanyScopeStep
                  companies={companiesResult.data}
                  snapshots={snapshotsResult.data}
                  selected={state.companyIds}
                  onToggle={toggleCompany}
                />
              ) : null}
              {state.step === 1 ? (
                <DataSourcesStep
                  externalResearchEnabled={state.externalResearchEnabled}
                  externalProviders={state.externalProviders}
                  dataDomainIds={state.dataDomainIds}
                  onChange={patch}
                />
              ) : null}
              {state.step === 2 ? (
                <RequirementsStep
                  totalCount={state.totalCount}
                  categories={state.categories}
                  rankingCriteria={state.rankingCriteria}
                  generalSearchPrompt={state.generalSearchPrompt}
                  onChange={(p) => {
                    if (p.generalSearchPrompt !== undefined) promptTouchedRef.current = true
                    patch(p)
                  }}
                />
              ) : null}
              {state.step === 3 ? <ReviewStep state={state} companies={companiesResult.data} /> : null}

              {submitError ? <p className="mt-4 text-sm text-danger">{submitError}</p> : null}

              <div className="mt-6 flex items-center justify-between border-t border-border pt-4">
                <Button
                  variant="secondary"
                  onClick={() => patch({ step: state.step - 1 })}
                  disabled={state.step === 0}
                >
                  Previous
                </Button>
                {state.step < WIZARD_STEPS.length - 1 ? (
                  <Button onClick={() => patch({ step: state.step + 1 })} disabled={!canAdvance}>
                    Next
                    <ArrowRight className="size-4" />
                  </Button>
                ) : (
                  <Button onClick={handleSubmit} disabled={submitting}>
                    {submitting ? <Loader2 className="size-4 animate-spin" /> : null}
                    Submit request
                  </Button>
                )}
              </div>
            </CardContent>
          </Card>

          <ScopeSummaryPanel state={state} companies={companiesResult.data} />
        </div>
      ) : null}
    </div>
  )
}

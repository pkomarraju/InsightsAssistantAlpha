import type { Company, InsightCategory, ResearchRequest, UserPreferences } from '@/api/types'

export interface WizardState {
  step: number
  companyIds: string[]
  /** Provider-neutral: whether external market research (FMP/Alpha Vantage/FRED) runs at all. */
  externalResearchEnabled: boolean
  /** Which of EXTERNAL_PROVIDER_OPTIONS are active. Ignored (but preserved) while
   * externalResearchEnabled is false, so re-enabling restores the previous selection. */
  externalProviders: string[]
  lookbackMonths: number
  dataDomainIds: string[]
  generalSearchPrompt: string
  totalCount: number
  categories: { categoryId: InsightCategory; minimumCount: number }[]
  rankingCriteria: ResearchRequest['insightRequirements']['rankingCriteria']
}

/** The one internal dataset every request always includes -- rendered checked
 * and disabled in the wizard (see DataSourcesStep). */
export const ALWAYS_INCLUDED_DOMAIN_ID = 'company_profile'

export const DATA_DOMAIN_OPTIONS: { id: string; label: string; description: string }[] = [
  {
    id: 'company_profile', label: 'Company & Coverage Profile',
    description: 'Company identity, industry, relationship status, and internal coverage lead.',
  },
  {
    id: 'credit_exposure', label: 'Credit Exposure & Facilities',
    description: 'Committed and drawn amounts, utilization, pricing, covenants, and facility maturities.',
  },
  {
    id: 'deal_pipeline', label: 'CRM Deal Pipeline',
    description: 'Active opportunities, potential fees, deal stages, probabilities, and target close dates.',
  },
  {
    id: 'internal_risk_flags', label: 'Internal Risk Flags',
    description: 'Current internal risk and opportunity signals, severity, reported date, and supporting rationale.',
  },
]

export const EXTERNAL_PROVIDER_OPTIONS: { id: string; label: string; description: string }[] = [
  { id: 'fmp', label: 'Financial Modeling Prep', description: 'Financial statements, valuation, leverage, liquidity, and debt capacity.' },
  { id: 'alpha_vantage', label: 'Alpha Vantage', description: 'Company profiles, earnings, and equity-price signals.' },
  { id: 'fred', label: 'FRED', description: 'Benchmark rates, Treasury yields, and macroeconomic indicators.' },
]

// The new-request wizard's own category selector -- deliberately only the
// four categories the current internal dataset (target_companies/
// bank_credit_exposures/crm_deal_pipeline/internal_risk_flags) can actually
// support with real evidence. Legacy categories (revenue & cross-sell,
// credit risk, capital markets advisory, treasury/payments/liquidity,
// relationship risk) still exist on the wire (see api/types.ts's
// InsightCategory and components/domain/badges.tsx's CATEGORY_LABELS, which
// cover all nine) for reading/displaying an existing stored insight -- they
// are just never offered here.
export const CATEGORY_OPTIONS: { id: InsightCategory; label: string; description: string }[] = [
  {
    id: 'financing_liquidity', label: 'Financing & liquidity',
    description: 'Facility utilization, upcoming maturities, covenant headroom, debt capacity, cash flow, and the rate environment.',
  },
  {
    id: 'deal_fee_opportunity', label: 'Deal & fee opportunities',
    description: 'Active financing, refinancing, M&A, and advisory opportunities supported by internal pipeline and external company signals.',
  },
  {
    id: 'financial_performance', label: 'Financial performance',
    description: 'Material changes in earnings, margins, leverage, liquidity, valuation, and market performance.',
  },
  {
    id: 'risk_coverage_attention', label: 'Risk & coverage attention',
    description: 'Internal risk flags or relationship status that warrant banker follow-up, corroborated or qualified by external evidence.',
  },
]

/** Selected by default when a fresh wizard is seeded -- financial_performance
 * is deliberately left out (available, not pre-selected). */
export const DEFAULT_CATEGORY_IDS: InsightCategory[] = ['financing_liquidity', 'deal_fee_opportunity', 'risk_coverage_attention']

export const RANKING_OPTIONS: { id: ResearchRequest['insightRequirements']['rankingCriteria'][number]; label: string }[] = [
  { id: 'urgency', label: 'Urgency' },
  { id: 'commercial_potential', label: 'Commercial potential' },
  { id: 'confidence', label: 'Confidence' },
  { id: 'risk_severity', label: 'Risk severity' },
]

export const initialWizardState: WizardState = {
  step: 0,
  companyIds: [],
  externalResearchEnabled: true,
  externalProviders: EXTERNAL_PROVIDER_OPTIONS.map((p) => p.id),
  lookbackMonths: 24,
  dataDomainIds: [ALWAYS_INCLUDED_DOMAIN_ID, 'credit_exposure', 'internal_risk_flags'],
  generalSearchPrompt: '',
  // A target the assistant aims for, not a requirement to manufacture --
  // see RequirementsStep's helper copy. minimumCount below is always 0 for
  // the same reason: banker interest, not a forced quota per category.
  totalCount: 3,
  categories: DEFAULT_CATEGORY_IDS.map((categoryId) => ({ categoryId, minimumCount: 0 })),
  rankingCriteria: ['urgency', 'commercial_potential'],
}

/** Keeps only recognized domain ids and guarantees the always-included one
 * is present -- a banker's saved preferences (or an older persisted wizard
 * state) may still list a retired domain id, which must never surface as a
 * silently-broken selection. */
function normalizeDataDomainIds(ids: string[]): string[] {
  const known = new Set(DATA_DOMAIN_OPTIONS.map((d) => d.id))
  const filtered = ids.filter((id) => known.has(id))
  return filtered.includes(ALWAYS_INCLUDED_DOMAIN_ID) ? filtered : [ALWAYS_INCLUDED_DOMAIN_ID, ...filtered]
}

/**
 * Seeds a fresh wizard from the banker's saved preferences (falls back to
 * `initialWizardState`'s defaults for anything the preferences don't cover,
 * e.g. company selection, which is always request-specific).
 */
export function buildInitialWizardState(preferences: UserPreferences | null): WizardState {
  if (!preferences) return initialWizardState
  return {
    ...initialWizardState,
    dataDomainIds: normalizeDataDomainIds(
      preferences.defaultDataDomains.length > 0 ? preferences.defaultDataDomains : initialWizardState.dataDomainIds,
    ),
    rankingCriteria: preferences.defaultRankingCriteria.length > 0 ? preferences.defaultRankingCriteria : initialWizardState.rankingCriteria,
    lookbackMonths: initialWizardState.lookbackMonths,
  }
}

/**
 * A guided request should never require a banker to hand-type a prompt just
 * to advance the wizard: this composes a specific, editable default from
 * what they've already selected, so the free-text field is a refinement,
 * not a gate.
 */
export function buildDefaultSearchPrompt(
  selectedCompanies: Company[],
  categories: { categoryId: InsightCategory }[],
): string {
  const companyPhrase =
    selectedCompanies.length === 0
      ? 'the selected companies'
      : selectedCompanies.length <= 3
        ? selectedCompanies.map((c) => c.companyName).join(', ')
        : `${selectedCompanies
            .slice(0, 2)
            .map((c) => c.companyName)
            .join(', ')}, and ${selectedCompanies.length - 2} other companies`

  const categoryLabels = categories
    .map((c) => CATEGORY_OPTIONS.find((o) => o.id === c.categoryId)?.label)
    .filter((label): label is string => Boolean(label))

  const focusPhrase =
    categoryLabels.length > 0
      ? categoryLabels.join(', ').toLowerCase()
      : 'financing, liquidity, deal, and risk-coverage'

  return `Identify ${focusPhrase} opportunities and risks for ${companyPhrase}. Connect external market research to internal company, credit, and pipeline context and recommend a concrete banker action.`
}

export const WIZARD_STEPS = ['Company scope', 'Data sources', 'Insight requirements', 'Review'] as const

import type { UserPreferences } from '@/api/types'

export const defaultPreferences: UserPreferences = {
  displayName: 'Alex Bianchi',
  role: 'Relationship Banker',
  defaultDataDomains: [
    'client_profitability',
    'credit_exposure',
    'deposits_treasury_payments',
    'relationship_interactions',
  ],
  defaultRankingCriteria: ['urgency', 'commercial_potential', 'confidence'],
  emailDigestEnabled: true,
  atRiskAlertsEnabled: true,
  displayDensity: 'comfortable',
  defaultLookbackMonths: 24,
}

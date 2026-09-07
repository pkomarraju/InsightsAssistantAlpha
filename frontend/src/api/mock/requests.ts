import type { ResearchRequest } from '@/api/types'
import { companies } from '@/api/mock/seed'

const byCode = (code: string) => {
  const c = companies.find((company) => company.companyCode === code)!
  return { companyId: c.companyId, companyCode: c.companyCode, companyName: c.companyName, ticker: c.ticker }
}

/** Mirrors contracts/research/research_scope_schema.json — one row per submitted job. */
export const researchRequests: ResearchRequest[] = [
  {
    requestId: 'REQ_0995',
    requestedBy: 'banker-12345',
    status: 'completed',
    createdAt: '2026-07-20T08:00:00Z',
    updatedAt: '2026-07-24T16:00:00Z',
    companyScope: {
      selectionMode: 'explicit',
      companies: [byCode('CLI_005'), byCode('CLI_008')],
    },
    externalResearch: { enabled: true, providers: ['fmp', 'alpha_vantage', 'fred'], edgarEnabled: true, filingTypes: ['10-K', '10-Q'], lookbackMonths: 12 },
    internalResearch: {
      dataDomains: [
        { domainId: 'client_profitability', label: 'Client profitability', enabled: true },
        { domainId: 'deposits_treasury_payments', label: 'Deposits, treasury & payments', enabled: true },
        { domainId: 'relationship_interactions', label: 'Relationship interactions', enabled: true },
      ],
      generalSearchPrompt: 'Identify cross-sell whitespace in treasury and lending products following recent renewal and pilot discussions.',
      asOfDate: '2026-07-20',
    },
    insightRequirements: {
      totalCount: 6,
      categories: [
        { categoryId: 'revenue_cross_sell', minimumCount: 3 },
        { categoryId: 'treasury_payments_liquidity', minimumCount: 2 },
        { categoryId: 'credit_risk', minimumCount: 1 },
      ],
      rankingCriteria: ['commercial_potential', 'confidence'],
      maxInsightsPerCompany: 4,
    },
    resultInsightIds: ['INS_025', 'INS_026', 'INS_027', 'INS_028', 'INS_029', 'INS_030'],
    progressPct: 100,
    errorMessage: null,
  },
  {
    requestId: 'REQ_1001',
    requestedBy: 'banker-12345',
    status: 'completed',
    createdAt: '2026-08-13T08:00:00Z',
    updatedAt: '2026-08-15T08:10:00Z',
    companyScope: {
      selectionMode: 'explicit',
      companies: [byCode('CLI_002'), byCode('CLI_007'), byCode('CLI_003'), byCode('CLI_004')],
    },
    externalResearch: { enabled: true, providers: ['fmp', 'alpha_vantage', 'fred'], edgarEnabled: true, filingTypes: ['10-K', '10-Q', '8-K', 'DEF 14A'], lookbackMonths: 24 },
    internalResearch: {
      dataDomains: [
        { domainId: 'client_profitability', label: 'Client profitability', enabled: true },
        { domainId: 'credit_exposure', label: 'Credit exposure', enabled: true },
        { domainId: 'deposits_treasury_payments', label: 'Deposits, treasury & payments', enabled: true },
        { domainId: 'relationship_interactions', label: 'Relationship interactions', enabled: true },
      ],
      generalSearchPrompt:
        'Identify material changes in strategy, capital allocation, liquidity, and disclosed risks. Connect external filing evidence to internal relationship signals and recommend a concrete banker action.',
      asOfDate: '2026-08-13',
    },
    insightRequirements: {
      totalCount: 12,
      categories: [
        { categoryId: 'revenue_cross_sell', minimumCount: 8 },
        { categoryId: 'credit_risk', minimumCount: 5 },
        { categoryId: 'capital_markets_advisory', minimumCount: 4 },
        { categoryId: 'treasury_payments_liquidity', minimumCount: 3 },
      ],
      rankingCriteria: ['urgency', 'commercial_potential', 'confidence'],
      maxInsightsPerCompany: 5,
    },
    resultInsightIds: [
      'INS_001', 'INS_002', 'INS_003', 'INS_004', 'INS_005', 'INS_006',
      'INS_007', 'INS_008', 'INS_009', 'INS_010', 'INS_011', 'INS_012',
    ],
    progressPct: 100,
    errorMessage: null,
  },
  {
    requestId: 'REQ_1002',
    requestedBy: 'banker-12345',
    status: 'completed',
    createdAt: '2026-08-15T09:30:00Z',
    updatedAt: '2026-08-16T13:50:00Z',
    companyScope: {
      selectionMode: 'explicit',
      companies: [byCode('CLI_006'), byCode('CLI_010'), byCode('CLI_001'), byCode('CLI_009')],
    },
    externalResearch: { enabled: true, providers: ['fmp', 'alpha_vantage', 'fred'], edgarEnabled: true, filingTypes: ['10-K', '10-Q', '8-K'], lookbackMonths: 12 },
    internalResearch: {
      dataDomains: [
        { domainId: 'credit_exposure', label: 'Credit exposure', enabled: true },
        { domainId: 'deposits_treasury_payments', label: 'Deposits, treasury & payments', enabled: true },
        { domainId: 'relationship_interactions', label: 'Relationship interactions', enabled: true },
        { domainId: 'product_whitespace', label: 'Product whitespace', enabled: true },
      ],
      generalSearchPrompt:
        'Surface any relationship at risk of competitive displacement, and any liquidity or working-capital need implied by recent public commentary.',
      asOfDate: '2026-08-15',
    },
    insightRequirements: {
      totalCount: 12,
      categories: [
        { categoryId: 'credit_risk', minimumCount: 3 },
        { categoryId: 'treasury_payments_liquidity', minimumCount: 3 },
        { categoryId: 'revenue_cross_sell', minimumCount: 2 },
      ],
      rankingCriteria: ['risk_severity', 'urgency'],
      maxInsightsPerCompany: 4,
    },
    resultInsightIds: [
      'INS_013', 'INS_014', 'INS_015', 'INS_016', 'INS_017', 'INS_018',
      'INS_019', 'INS_020', 'INS_021', 'INS_022', 'INS_023', 'INS_024',
    ],
    progressPct: 100,
    errorMessage: null,
    // Demonstrates a synthesis revision that resolved before completion --
    // the Reviewer flagged overlapping insights once, the Synthesizer
    // consolidated them, and the second pass was clean.
    currentStage: 'completed',
    requestVersion: 1,
    packageVersion: 2,
    researchRevisionCount: 0,
    synthesisRevisionCount: 1,
    sourceErrors: [],
    reviewDecision: 'pass',
    reviewComments: 'Insights are well supported and ranked correctly after consolidation.',
    auditEvents: [
      { stage: 'researching', message: 'workflow started', occurredAt: '2026-08-15T09:30:00Z' },
      {
        stage: 'reviewing', message: 'review decision: revise_insights', occurredAt: '2026-08-16T10:00:00Z',
        detail: {
          decision: 'revise_insights',
          comments: 'Consolidate two overlapping credit-risk insights for CLI_006.',
          affectedInsightIds: ['INS_014'],
          affectedSourceAgents: [],
        },
      },
      { stage: 'completed', message: 'review passed', occurredAt: '2026-08-16T13:50:00Z' },
    ],
    unmetRequirements: [],
  },
  {
    requestId: 'REQ_1003',
    requestedBy: 'banker-12345',
    status: 'running',
    createdAt: '2026-08-20T13:05:00Z',
    updatedAt: '2026-08-20T13:07:00Z',
    companyScope: {
      selectionMode: 'explicit',
      companies: [byCode('CLI_005'), byCode('CLI_008')],
    },
    externalResearch: { enabled: true, providers: ['fmp', 'alpha_vantage', 'fred'], edgarEnabled: true, filingTypes: ['10-K', '10-Q'], lookbackMonths: 18 },
    internalResearch: {
      dataDomains: [
        { domainId: 'client_profitability', label: 'Client profitability', enabled: true },
        { domainId: 'product_whitespace', label: 'Product whitespace', enabled: true },
      ],
      generalSearchPrompt: 'Look for cross-sell whitespace in treasury and lending products following recent renewal discussions.',
      asOfDate: '2026-08-20',
    },
    insightRequirements: {
      totalCount: 6,
      categories: [
        { categoryId: 'revenue_cross_sell', minimumCount: 4 },
        { categoryId: 'treasury_payments_liquidity', minimumCount: 2 },
      ],
      rankingCriteria: ['commercial_potential'],
      maxInsightsPerCompany: 4,
    },
    resultInsightIds: [],
    progressPct: 55,
    errorMessage: null,
    currentStage: 'synthesizing',
    requestVersion: 1,
    packageVersion: 1,
    researchRevisionCount: 0,
    synthesisRevisionCount: 0,
    sourceErrors: [],
    auditEvents: [
      { stage: 'researching', message: 'workflow started', occurredAt: '2026-08-20T13:05:00Z' },
      { stage: 'synthesizing', message: 'synthesizing insight package', occurredAt: '2026-08-20T13:07:00Z' },
    ],
  },
  {
    requestId: 'REQ_1004',
    requestedBy: 'banker-12345',
    status: 'draft',
    createdAt: '2026-08-19T17:22:00Z',
    updatedAt: '2026-08-19T17:22:00Z',
    companyScope: { selectionMode: 'explicit', companies: [byCode('CLI_003')] },
    externalResearch: { enabled: true, providers: ['fmp', 'alpha_vantage', 'fred'], edgarEnabled: true, filingTypes: ['10-K'], lookbackMonths: 12 },
    internalResearch: {
      dataDomains: [{ domainId: 'capital_markets_advisory', label: 'Capital markets & advisory', enabled: true }],
      generalSearchPrompt: 'Draft scope pending sign-off — capital markets advisory follow-through for Apple.',
      asOfDate: '2026-08-19',
    },
    insightRequirements: {
      totalCount: 4,
      categories: [{ categoryId: 'capital_markets_advisory', minimumCount: 2 }],
      rankingCriteria: ['confidence'],
      maxInsightsPerCompany: 4,
    },
    resultInsightIds: [],
    progressPct: 0,
    errorMessage: null,
  },
  {
    requestId: 'REQ_0998',
    requestedBy: 'banker-77821',
    status: 'failed',
    createdAt: '2026-08-11T07:40:00Z',
    updatedAt: '2026-08-11T07:52:00Z',
    companyScope: { selectionMode: 'explicit', companies: [byCode('CLI_004')] },
    externalResearch: { enabled: true, providers: ['fmp', 'alpha_vantage', 'fred'], edgarEnabled: true, filingTypes: ['10-K', '10-Q', '8-K', 'DEF 14A'], lookbackMonths: 24 },
    internalResearch: {
      dataDomains: [{ domainId: 'credit_exposure', label: 'Credit exposure', enabled: true }],
      generalSearchPrompt: 'Investigate regulatory transformation exposure ahead of Q3 review.',
      asOfDate: '2026-08-11',
    },
    insightRequirements: {
      totalCount: 5,
      categories: [{ categoryId: 'credit_risk', minimumCount: 3 }],
      rankingCriteria: ['risk_severity'],
      maxInsightsPerCompany: 5,
    },
    resultInsightIds: [],
    progressPct: 20,
    errorMessage: 'FRED tool timed out after 3 retries while fetching benchmark rate data for CLI_004.',
    // Demonstrates a research revision that was attempted but still didn't
    // recover the missing source -- the terminal state a banker sees when a
    // revision budget is used but doesn't fix the underlying problem.
    currentStage: 'failed',
    requestVersion: 2,
    packageVersion: 1,
    researchRevisionCount: 1,
    synthesisRevisionCount: 0,
    sourceErrors: [
      {
        id: 'SRCERR_0998_2_0',
        source: 'external_data_agent',
        companyId: byCode('CLI_004').companyId,
        code: 'timed_out',
        message: 'FRED tool timed out after 3 retries while fetching benchmark rate data for CLI_004.',
        occurredAt: '2026-08-11T07:52:00Z',
        retryable: true,
      },
    ],
    reviewDecision: 'revise_research',
    reviewComments: 'External market data for CLI_004 could not be retrieved; re-check provider access before retrying.',
    auditEvents: [
      { stage: 'researching', message: 'workflow started', occurredAt: '2026-08-11T07:40:00Z' },
      {
        stage: 'reviewing', message: 'review decision: revise_research', occurredAt: '2026-08-11T07:48:00Z',
        detail: {
          decision: 'revise_research',
          comments: 'External market data for CLI_004 could not be retrieved; re-check provider access before retrying.',
          affectedInsightIds: [],
          affectedSourceAgents: ['external_data_agent'],
        },
      },
      { stage: 'failed', message: 'research incomplete: CLI_004/external_data_agent: timed_out', occurredAt: '2026-08-11T07:52:00Z' },
    ],
  },
]

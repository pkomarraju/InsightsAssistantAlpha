import type { RelationshipMetricMonthly, SentimentLabel, TrendLabel } from '@/api/types'
import { relationshipSnapshots } from '@/api/mock/seed'

/**
 * relationship_metrics_monthly has 240 real rows (24 months x 10 companies)
 * in seed_data.sql. Rather than transcribe all of them, this generates a
 * 12-month trailing series per company that lands on the real
 * relationship_snapshot endpoint (revenue, risk trend) so the shape stays
 * internally consistent with the transcribed snapshot data.
 */

function seededRandom(seed: number) {
  let value = seed
  return () => {
    value = (value * 9301 + 49297) % 233280
    return value / 233280
  }
}

function trendForStatus(status: string): { slope: number; sentiment: SentimentLabel; trendLabel: TrendLabel } {
  switch (status) {
    case 'at_risk':
      return { slope: 0.9, sentiment: 'negative', trendLabel: 'sudden_deterioration' }
    case 'strong':
      return { slope: -0.35, sentiment: 'positive', trendLabel: 'rapid_growth' }
    case 'developing_opportunity':
      return { slope: -0.1, sentiment: 'neutral', trendLabel: 'slow_growth' }
    default:
      return { slope: 0, sentiment: 'neutral', trendLabel: 'stable' }
  }
}

function monthsBack(from: string, count: number): string[] {
  const [year, month] = from.split('-').map(Number)
  const months: string[] = []
  for (let i = count - 1; i >= 0; i--) {
    const d = new Date(Date.UTC(year, month - 1 - i, 1))
    months.push(d.toISOString().slice(0, 7) + '-01')
  }
  return months
}

function generateForCompany(companyId: string): RelationshipMetricMonthly[] {
  const snapshot = relationshipSnapshots.find((s) => s.companyId === companyId)
  if (!snapshot) return []

  const rand = seededRandom((snapshot.companyId.length * 97 + snapshot.currentAnnualRevenue) % 100000)
  const { slope, sentiment, trendLabel } = trendForStatus(snapshot.relationshipStatus)
  const months = monthsBack(snapshot.asOfDate, 12)
  const baseRisk = snapshot.relationshipStrength === 'at_risk' ? 66 : snapshot.relationshipStrength === 'strong' ? 17 : 30

  return months.map((month, index) => {
    const stepsFromEnd = months.length - 1 - index
    const noise = (rand() - 0.5) * 0.06
    const revenueFactor = 1 - (slope * stepsFromEnd) / 12 + noise
    const riskDrift = slope * stepsFromEnd * 4.5

    return {
      observationMonth: month,
      transactionVolume: Math.round((snapshot.transactionVolumeYtd / 12) * revenueFactor),
      relationshipRevenue: Math.round((snapshot.currentAnnualRevenue / 12) * revenueFactor),
      pipelineValue: Math.round(snapshot.currentAnnualRevenue * 0.35 * revenueFactor),
      riskScore: Math.round(Math.max(4, Math.min(95, baseRisk - riskDrift + (rand() - 0.5) * 3)) * 100) / 100,
      sentimentLabel: stepsFromEnd < 3 ? sentiment : 'neutral',
      trendLabel: stepsFromEnd < 4 ? trendLabel : 'stable',
    }
  })
}

const cache = new Map<string, RelationshipMetricMonthly[]>()

export function getMonthlyMetricsByCompany(companyId: string): RelationshipMetricMonthly[] {
  if (!cache.has(companyId)) {
    cache.set(companyId, generateForCompany(companyId))
  }
  return cache.get(companyId) ?? []
}

import { describe, expect, it } from 'vitest'

import { formatBusinessImpact, formatCurrency, formatDate, formatPercent, initials } from '@/lib/format'

describe('formatCurrency', () => {
  it('formats whole dollar amounts with no decimals', () => {
    expect(formatCurrency(180_000_000)).toBe('$180,000,000')
  })

  it('formats compact notation when requested', () => {
    expect(formatCurrency(180_000_000, { compact: true })).toBe('$180M')
  })
})

describe('formatPercent', () => {
  it('formats a positive value without a forced sign by default', () => {
    expect(formatPercent(9.02)).toBe('9.0%')
  })

  it('prefixes a positive value with + when signed is requested', () => {
    expect(formatPercent(9.02, { signed: true })).toBe('+9.0%')
  })

  it('does not add a redundant sign to negative values', () => {
    expect(formatPercent(-20, { signed: true })).toBe('-20.0%')
  })
})

describe('formatDate', () => {
  it('formats an ISO date string', () => {
    expect(formatDate('2026-07-01')).toBe('Jul 1, 2026')
  })

  it('returns the raw input when the date cannot be parsed', () => {
    expect(formatDate('not-a-date')).toBe('not-a-date')
  })
})

describe('formatBusinessImpact', () => {
  it('shows exposure separately from business impact when both are present', () => {
    const result = formatBusinessImpact({
      amountUsd: 10_100_000,
      description: 'x',
      exposureUsd: 10_100_000,
      estimatedImpactUsd: 2_000_000,
      impactBasis: '20% of exposure',
    })
    expect(result.exposure).toBe('$10.1M')
    expect(result.estimatedImpact).toBe('$2M')
  })

  it('hides business impact (returns null) when no estimate is supported, without falling back to exposure', () => {
    const result = formatBusinessImpact({
      amountUsd: 10_100_000, // legacy field left populated -- must not leak into estimatedImpact
      description: 'Credit exposure',
      exposureUsd: 10_100_000,
      estimatedImpactUsd: null,
    })
    expect(result.exposure).toBe('$10.1M')
    expect(result.estimatedImpact).toBeNull()
  })

  it('falls back to the legacy amountUsd for estimatedImpact only when exposureUsd is entirely absent', () => {
    const result = formatBusinessImpact({ amountUsd: 5_000_000, description: 'Legacy row' })
    expect(result.exposure).toBeNull()
    expect(result.estimatedImpact).toBe('$5M')
  })

  it('hides business impact for a legacy row with a zero amount', () => {
    const result = formatBusinessImpact({ amountUsd: 0, description: 'No impact' })
    expect(result.exposure).toBeNull()
    expect(result.estimatedImpact).toBeNull()
  })
})

describe('initials', () => {
  it('takes the first letter of up to two words', () => {
    expect(initials('Alex Bianchi')).toBe('AB')
  })

  it('handles a single-word name', () => {
    expect(initials('Cher')).toBe('C')
  })
})

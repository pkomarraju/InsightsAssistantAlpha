import type { BusinessImpact } from '@/api/types'

export function formatCurrency(value: number, options?: { compact?: boolean }): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 0,
    maximumFractionDigits: options?.compact ? 1 : 0,
    notation: options?.compact ? 'compact' : 'standard',
  }).format(value)
}

/**
 * Splits an insight's monetary picture into separately displayable exposure
 * and estimated-impact strings -- never a single ambiguous "amount" that
 * could read as either, and never exposure standing in for impact. A value
 * is `null` when nothing should be shown for that field at all (the caller
 * hides the block, rather than rendering a "$0" or "—" that could imply a
 * supported-but-zero estimate).
 *
 * Falls back to the legacy `amountUsd` field for `estimatedImpact` only
 * when `exposureUsd` is entirely absent (a pre-split mock/legacy row) --
 * once a row carries a real `exposureUsd`, `amountUsd` is never trusted for
 * the impact figure, so exposure can never leak into the impact slot.
 */
export function formatBusinessImpact(impact: BusinessImpact): { exposure: string | null; estimatedImpact: string | null } {
  const exposure = impact.exposureUsd != null ? formatCurrency(impact.exposureUsd, { compact: true }) : null

  if (impact.exposureUsd != null || impact.estimatedImpactUsd != null) {
    const estimatedImpact = impact.estimatedImpactUsd != null ? formatCurrency(impact.estimatedImpactUsd, { compact: true }) : null
    return { exposure, estimatedImpact }
  }

  // Legacy shape: amountUsd was the only figure ever reported.
  const estimatedImpact = impact.amountUsd > 0 ? formatCurrency(impact.amountUsd, { compact: true }) : null
  return { exposure, estimatedImpact }
}

export function formatPercent(value: number, options?: { signed?: boolean }): string {
  const formatted = new Intl.NumberFormat('en-US', {
    style: 'percent',
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(value / 100)
  if (options?.signed && value > 0) return `+${formatted}`
  return formatted
}

const DATE_ONLY_PATTERN = /^\d{4}-\d{2}-\d{2}$/

export function formatDate(value: string, options?: { withTime?: boolean }): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  // Date-only strings (e.g. "2026-07-01") parse as UTC midnight; formatting
  // them in the viewer's local timezone can shift the displayed calendar
  // date by a day, so pin those to UTC. Full timestamps still show local time.
  const isDateOnly = DATE_ONLY_PATTERN.test(value)
  return new Intl.DateTimeFormat('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    ...(isDateOnly ? { timeZone: 'UTC' } : {}),
    ...(options?.withTime ? { hour: 'numeric', minute: '2-digit' } : {}),
  }).format(date)
}

export function formatRelativeToNow(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const diffMs = date.getTime() - Date.now()
  const diffDays = Math.round(diffMs / (1000 * 60 * 60 * 24))
  const rtf = new Intl.RelativeTimeFormat('en-US', { numeric: 'auto' })
  if (Math.abs(diffDays) < 1) {
    const diffHours = Math.round(diffMs / (1000 * 60 * 60))
    return rtf.format(diffHours, 'hour')
  }
  if (Math.abs(diffDays) < 30) return rtf.format(diffDays, 'day')
  return rtf.format(Math.round(diffDays / 30), 'month')
}

export function initials(name: string): string {
  return name
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join('')
}

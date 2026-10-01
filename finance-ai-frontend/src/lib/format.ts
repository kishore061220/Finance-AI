/**
 * Presentation helpers.
 *
 * Money arrives from the API as a string because the backend uses `Decimal`.
 * Parsing to `number` for display is fine; parsing for *submission* must not be
 * (see `toAmountString`).
 */

const currencyFormatter = new Intl.NumberFormat(undefined, {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

const compactFormatter = new Intl.NumberFormat(undefined, {
  notation: 'compact',
  maximumFractionDigits: 1,
})

const plainFormatter = new Intl.NumberFormat(undefined, {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

export function toNumber(value: string | number | null | undefined): number {
  if (value === null || value === undefined || value === '') return 0
  const parsed = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

/**
 * Format a money string for display.
 *
 * Returns an em dash for absent values rather than "0.00", because a missing
 * amount and a zero amount are different facts and a budget card showing
 * "0.00" implies the latter.
 */
export function formatCurrency(value: string | number | null | undefined, fallback = '—'): string {
  if (value === null || value === undefined || value === '') return fallback
  const parsed = toNumber(value)
  return currencyFormatter.format(parsed)
}

export function formatNumber(value: string | number | null | undefined, fallback = '—'): string {
  if (value === null || value === undefined || value === '') return fallback
  return plainFormatter.format(toNumber(value))
}

export function formatCompactCurrency(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  return `$${compactFormatter.format(toNumber(value))}`
}

export function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return `${value.toFixed(digits)}%`
}

/**
 * Convert a user-entered amount to the string the API expects.
 *
 * Kept as a string rather than `String(Number(value))` so precision beyond two
 * decimals is not silently rewritten, and so `""` cannot become `0` and be sent
 * as a valid-looking zero.
 */
export function toAmountString(input: string): string {
  const trimmed = input.trim()
  if (trimmed === '') {
    throw new Error('Amount is required.')
  }
  const parsed = Number(trimmed)
  if (!Number.isFinite(parsed)) {
    throw new Error('Amount must be a number.')
  }
  if (parsed <= 0) {
    throw new Error('Amount must be greater than zero.')
  }
  if (parsed > 999_999_999_999.99) {
    throw new Error('Amount is too large.')
  }
  return parsed.toFixed(2)
}

/** `2026-03-14T09:30:00` to a short local date. */
export function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** `datetime-local` input value from a Date. */
export function toDateTimeLocal(date: Date): string {
  const offset = date.getTimezoneOffset() * 60_000
  return new Date(date.getTime() - offset).toISOString().slice(0, 16)
}

/**
 * ISO string the API will parse, from a `datetime-local` input value.
 *
 * `toISOString()` would treat the naive input as UTC and shift it, so the local
 * wall-clock time is sent as-is with an explicit offset.
 */
export function fromDateTimeLocal(value: string): string {
  if (!value) return new Date().toISOString()
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return new Date().toISOString()
  return date.toISOString()
}

export const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

export function monthName(month: number): string {
  return MONTH_NAMES[month - 1] ?? String(month)
}

export function currentPeriod(now = new Date()): { month: number; year: number } {
  return { month: now.getMonth() + 1, year: now.getFullYear() }
}

/** Human-readable risk band from a score, matching the backend's thresholds. */
export function riskLevelFor(score: number): 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL' {
  if (score >= 80) return 'CRITICAL'
  if (score >= 60) return 'HIGH'
  if (score >= 30) return 'MEDIUM'
  return 'LOW'
}

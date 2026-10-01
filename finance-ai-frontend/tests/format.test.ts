/**
 * Formatting and money-safety tests.
 *
 * These matter more than they look: `toAmountString` is the boundary where user
 * input becomes an API payload, and the backend rejects a non-positive amount.
 * If it returned "0" for an empty field, a blank form would submit a real-looking
 * zero transaction.
 */

import { describe, expect, it } from 'vitest'

import {
  currentPeriod,
  formatCompactCurrency,
  formatCurrency,
  formatDate,
  formatDateTime,
  formatPercent,
  fromDateTimeLocal,
  monthName,
  riskLevelFor,
  toAmountString,
  toDateTimeLocal,
  toNumber,
} from '@/lib/format'

describe('toNumber', () => {
  it('parses decimal strings from the API', () => {
    expect(toNumber('1234.50')).toBe(1234.5)
  })

  it('treats absent values as zero rather than NaN', () => {
    expect(toNumber(null)).toBe(0)
    expect(toNumber(undefined)).toBe(0)
    expect(toNumber('')).toBe(0)
  })

  it('never returns NaN for garbage input', () => {
    expect(toNumber('not-a-number')).toBe(0)
    expect(toNumber(Number.NaN)).toBe(0)
  })
})

describe('toAmountString', () => {
  it('normalises to two decimal places', () => {
    expect(toAmountString('10')).toBe('10.00')
    expect(toAmountString('10.5')).toBe('10.50')
    expect(toAmountString(' 10.567 ')).toBe('10.57')
  })

  it('rounds rather than truncating, which is what toFixed does', () => {
    // 10.555 is not exactly representable as a double: it is 10.55499... so
    // toFixed(2) correctly yields 10.55. Documented here because the naive
    // expectation of 10.56 looks like a bug and is not one.
    expect(toAmountString('10.555')).toBe('10.55')
    expect(toAmountString('0.005')).toBe('0.01')
  })

  it('rejects an empty field instead of sending zero', () => {
    // The backend rejects amount <= 0. Turning "" into "0.00" would submit a
    // transaction that looks valid to a human but is not.
    expect(() => toAmountString('')).toThrow(/required/i)
    expect(() => toAmountString('   ')).toThrow(/required/i)
  })

  it('rejects zero and negative amounts', () => {
    expect(() => toAmountString('0')).toThrow(/greater than zero/i)
    expect(() => toAmountString('-5')).toThrow(/greater than zero/i)
  })

  it('rejects non-numeric input', () => {
    expect(() => toAmountString('abc')).toThrow(/must be a number/i)
  })

  it('rejects absurd amounts that would overflow the column', () => {
    expect(() => toAmountString('99999999999999999')).toThrow(/too large/i)
  })
})

describe('currency formatting', () => {
  it('formats a valid amount', () => {
    expect(formatCurrency('1234.5')).toMatch(/1,234\.50/)
  })

  it('shows a dash for missing money, not zero', () => {
    // A missing amount and a zero amount are different facts.
    expect(formatCurrency(null)).toBe('—')
    expect(formatCurrency(undefined)).toBe('—')
    expect(formatCurrency('')).toBe('—')
  })

  it('can still show zero when that is the real value', () => {
    expect(formatCurrency('0')).toMatch(/0\.00/)
  })

  it('compacts large values for tight spaces', () => {
    expect(formatCompactCurrency('12500')).toMatch(/12\.5K/)
  })
})

describe('formatPercent', () => {
  it('formats a number', () => {
    expect(formatPercent(23.456)).toBe('23.5%')
  })

  it('does not print NaN%', () => {
    expect(formatPercent(Number.NaN)).toBe('—')
    expect(formatPercent(undefined)).toBe('—')
  })
})

describe('date handling', () => {
  it('formats valid dates', () => {
    expect(formatDate('2026-03-14T09:30:00')).toMatch(/2026/)
  })

  it('returns a dash for missing or invalid dates', () => {
    expect(formatDate(null)).toBe('—')
    expect(formatDate('not-a-date')).toBe('—')
    expect(formatDateTime(undefined)).toBe('—')
  })

  it('round-trips a datetime-local value without shifting the hour', () => {
    // The naive input is local wall-clock time. Sending toISOString() on it
    // unconverted would treat it as UTC and shift every timestamp.
    const original = new Date(2026, 2, 14, 9, 30)
    const input = toDateTimeLocal(original)
    expect(input).toBe('2026-03-14T09:30')

    const roundTripped = new Date(fromDateTimeLocal(input))
    expect(roundTripped.getHours()).toBe(9)
    expect(roundTripped.getMinutes()).toBe(30)
    expect(roundTripped.getDate()).toBe(14)
  })

  it('falls back to now for an unparseable input', () => {
    expect(() => fromDateTimeLocal('')).not.toThrow()
    expect(() => fromDateTimeLocal('garbage')).not.toThrow()
  })
})

describe('period helpers', () => {
  it('names months', () => {
    expect(monthName(1)).toBe('January')
    expect(monthName(12)).toBe('December')
  })

  it('returns the current period', () => {
    const now = new Date(2026, 6, 15)
    expect(currentPeriod(now)).toEqual({ month: 7, year: 2026 })
  })
})

describe('riskLevelFor', () => {
  it('matches the backend score bands', () => {
    expect(riskLevelFor(0)).toBe('LOW')
    expect(riskLevelFor(29)).toBe('LOW')
    expect(riskLevelFor(30)).toBe('MEDIUM')
    expect(riskLevelFor(60)).toBe('HIGH')
    expect(riskLevelFor(80)).toBe('CRITICAL')
    expect(riskLevelFor(100)).toBe('CRITICAL')
  })
})

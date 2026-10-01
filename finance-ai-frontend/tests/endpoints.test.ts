/**
 * Endpoint-wrapper tests.
 *
 * These guard the contract with the backend: right path, right query
 * construction, and - most importantly - that no request carries a user id.
 * The backend derives ownership from the bearer token and rejects anything
 * else, so a stray `user_id` in a request is a silent 422 at best.
 */

import { AxiosError } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, api } from '@/lib/api'
import {
  backupApi,
  budgetApi,
  dashboardApi,
  extractForecast,
  familyApi,
  fraudApi,
  loanApi,
  mlApi,
  notificationApi,
  transactionApi,
} from '@/lib/endpoints'

/** Capture what would have gone over the wire. */
let captured: { method?: string; url?: string; params?: unknown; data?: unknown } = {}

function respond(body: unknown, status = 200) {
  captured = {}
  return vi.spyOn(api, 'request').mockImplementation((config) => {
    captured = config as typeof captured
    if (status >= 400) {
      // Must be a real AxiosError: `request()` normalises via isAxiosError, so a
      // plain Error would pass through untouched and never become an ApiError.
      const error = new AxiosError('request failed')
      error.response = { status, data: body, statusText: '', headers: {}, config: undefined }
      return Promise.reject(error)
    }
    return Promise.resolve({ data: body } as never)
  })
}

beforeEach(() => {
  captured = {}
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('no client-supplied user id', () => {
  const calls: [string, () => Promise<unknown>][] = [
    ['transactions.list', () => transactionApi.list()],
    ['budgets.list', () => budgetApi.list()],
    ['budgets.create', () => budgetApi.create({ category: 'Food', amount: '10.00', month: 1, year: 2026 })],
    ['fraud.alerts', () => fraudApi.alerts()],
    ['loans.list', () => loanApi.list()],
    ['family.groups', () => familyApi.groups()],
    ['notifications.list', () => notificationApi.list()],
    ['backups.list', () => backupApi.list()],
    ['ml.status', () => mlApi.status()],
    ['dashboard.full', () => dashboardApi.full()],
  ]

  it.each(calls)('%s sends no user id', async (_name, call) => {
    respond({})
    await call()

    const serialised = JSON.stringify({ url: captured.url, params: captured.params, data: captured.data })
    // The backend routes are all token-scoped, so a user id in the URL is both
    // wrong and a sign the old pre-migration client shape crept back in.
    expect(serialised).not.toMatch(/user_id/i)
  })

  it('uses the token-scoped path shapes the backend actually exposes', async () => {
    respond({})
    await transactionApi.list()
    expect(captured.url).toBe('/api/transactions')

    respond({})
    await fraudApi.alerts()
    expect(captured.url).toBe('/api/fraud/alerts')

    respond({})
    await budgetApi.list()
    // The legacy client called /api/budgets/user/{id}, which no longer exists.
    expect(captured.url).toBe('/api/budgets')
  })
})

describe('transaction filters', () => {
  it('drops blank values so they do not become "match nothing" filters', async () => {
    respond({ items: [], total: 0, page: 1, page_size: 50, pages: 0 })
    await transactionApi.list({
      category: '',
      merchant: undefined,
      search: '',
      min_amount: '',
      page: 1,
      page_size: 25,
    })

    const params = captured.params as Record<string, unknown>
    expect(params).not.toHaveProperty('category')
    expect(params).not.toHaveProperty('merchant')
    expect(params).not.toHaveProperty('search')
    expect(params).not.toHaveProperty('min_amount')
    expect(params.page).toBe(1)
    expect(params.page_size).toBe(25)
  })

  it('drops a false flag instead of sending flagged_only=false', async () => {
    respond({ items: [], total: 0, page: 1, page_size: 50, pages: 0 })
    await transactionApi.list({ flagged_only: false })
    expect(captured.params).not.toHaveProperty('flagged_only')
  })

  it('keeps flagged_only when it is true', async () => {
    respond({ items: [], total: 0, page: 1, page_size: 50, pages: 0 })
    await transactionApi.list({ flagged_only: true })
    expect((captured.params as Record<string, unknown>).flagged_only).toBe(true)
  })

  it('keeps real filter values', async () => {
    respond({ items: [], total: 0, page: 1, page_size: 50, pages: 0 })
    await transactionApi.list({ transaction_type: 'expense', category: 'Food', min_amount: '10' })
    const params = captured.params as Record<string, unknown>
    expect(params.transaction_type).toBe('expense')
    expect(params.category).toBe('Food')
    expect(params.min_amount).toBe('10')
  })
})

describe('budgets', () => {
  it('omits period params when no month or year is given', async () => {
    respond({ items: [], total: 0, month: 1, year: 2026 })
    await budgetApi.list()
    expect(captured.params).toEqual({})
  })

  it('sends both period params when given', async () => {
    respond({ items: [], total: 0, month: 3, year: 2026 })
    await budgetApi.list(3, 2026)
    expect(captured.params).toEqual({ month: 3, year: 2026 })
  })
})

describe('restore', () => {
  it('previews without sending confirm', async () => {
    respond({ backup_id: 1, backup_version: 1, checksum_verified: true, checksum: 'abc', tables: [], totals: { inserts: 0, updates: 0, skips: 0, conflicts: 0 }, warnings: [], applied: false })
    await backupApi.restorePreview(1)

    // A preview must never mutate. The endpoint is GET and carries no flag.
    expect(captured.method).toBe('GET')
    expect(captured.url).toBe('/api/backups/1/restore/preview')
    expect(captured.data).toBeUndefined()
  })

  it('applies only with an explicit confirm flag', async () => {
    respond({ backup_id: 1, backup_version: 1, checksum_verified: true, checksum: 'abc', tables: [], totals: { inserts: 1, updates: 0, skips: 0, conflicts: 0 }, warnings: [], applied: true })
    await backupApi.restoreApply(1)

    expect(captured.method).toBe('POST')
    // The backend rejects an unconfirmed restore, and so should this client.
    expect(captured.data).toEqual({ confirm: true })
  })
})

describe('fraud filters', () => {
  it('omits empty level filter', async () => {
    respond({ items: [], total: 0, unread: 0, by_level: {} })
    await fraudApi.alerts({ risk_level: '', is_read: undefined })
    expect(captured.params).toEqual({})
  })

  it('sends a real level filter', async () => {
    respond({ items: [], total: 0, unread: 0, by_level: {} })
    await fraudApi.alerts({ risk_level: 'HIGH' })
    expect(captured.params).toEqual({ risk_level: 'HIGH' })
  })
})

describe('loan detail', () => {
  it('is loaded on demand rather than with the list', async () => {
    respond({})
    await loanApi.detail(7)
    expect(captured.url).toBe('/api/loans/7')
  })
})

describe('family membership', () => {
  it('invites by email, not by user id', async () => {
    respond({})
    await familyApi.invite(3, 'person@example.com', true)
    expect(captured.url).toBe('/api/family/3/members')
    // The member does not exist yet, so the invite is keyed by email. Sending a
    // user id here would be meaningless for an un-registered member.
    expect(captured.data).toEqual({ email: 'person@example.com', can_view_all: true })
  })
})

describe('extractForecast', () => {
  const base = {
    required_months: 3,
    available_months: 3,
    months_needed: 0,
    history: [],
    categories: [],
    budget_projection: [],
  }

  it('returns the forecast when one exists', () => {
    const forecast = {
      month: 4,
      year: 2026,
      label: 'April 2026',
      predicted_expense: '1200.00',
      range: { low: '1000.00', high: '1400.00' },
      average_monthly_expense: '1100.00',
      months_of_history: 3,
      volatility: '150.00',
      basis: 'linear trend',
      notes: [],
    }
    expect(
      // "predicted" is the status the backend actually sends on success.
      extractForecast({ ...base, status: 'predicted', message: '', prediction: forecast }),
    ).toEqual(forecast)
  })

  it('returns null for insufficient_data, so the UI can say so', () => {
    // The backend returns this as HTTP 200. Rendering prediction fields
    // without checking would print "undefined" as a forecast.
    expect(
      extractForecast({
        ...base,
        status: 'insufficient_data',
        message: 'Needs 3 months of expense history.',
        prediction: null,
        months_needed: 2,
        available_months: 1,
      }),
    ).toBeNull()
  })

  it('returns null even if a prediction is present on a non-ok status', () => {
    // Defensive: status is the authority, not the presence of an object.
    expect(
      extractForecast({
        ...base,
        status: 'degraded',
        message: 'x',
        prediction: {
          month: 4, year: 2026, label: '', predicted_expense: '1',
          range: { low: '0', high: '2' }, average_monthly_expense: '1',
          months_of_history: 3, volatility: '0', basis: '', notes: [],
        },
      }),
    ).toBeNull()
  })
})

describe('error propagation', () => {
  it('surfaces the server message to the caller', async () => {
    respond({ detail: 'Budget already exists for that category and period.' }, 409)
    await expect(
      budgetApi.create({ category: 'Food', amount: '10.00', month: 1, year: 2026 }),
    ).rejects.toBeInstanceOf(ApiError)
  })
})

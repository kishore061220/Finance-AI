/**
 * Session and routing behaviour.
 *
 * The important assertions are the redirect rules: an anonymous visitor must not
 * reach a protected screen, and an authenticated one must not be stranded on the
 * login page. A screen that renders without its guard is a data-exposure bug,
 * because every one of them fetches on mount.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AxiosError } from 'axios'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from '@/App'
import { SessionProvider } from '@/auth/SessionContext'
import { api } from '@/lib/api'
import type { AuthConfig, UserResponse } from '@/types'

const TEST_USER: UserResponse = {
  id: 1,
  name: 'Ada Lovelace',
  email: 'ada@example.com',
  role: 'USER',
  is_active: true,
  email_verified: true,
  phone_number: null,
  created_at: '2026-01-01T00:00:00',
  last_login_at: null,
}

const DEV_CONFIG: AuthConfig = {
  provider: 'dev',
  firebase_enabled: false,
  registration_enabled: false,
  app_env: 'development',
}

/**
 * Route requests by URL.
 *
 * Every endpoint the app hits on boot is answered here. Anything unmocked falls
 * through to a rejected promise so an unexpected call shows up as a test failure
 * rather than a hang.
 */
function mockApi(overrides: Record<string, unknown> = {}) {
  const defaults: Record<string, unknown> = {
    '/api/auth/config': DEV_CONFIG,
    '/api/auth/me': TEST_USER,
    '/api/auth/logout': { signed_out: true },
    '/api/dashboard': {
      totals: { income: '5000.00', expense: '3000.00', net: '2000.00', savings_rate_percent: 40 },
      category_breakdown: [
        { category: 'Food', amount: '1200.00', percent: 40 },
        { category: 'Transport', amount: '800.00', percent: 26.7 },
      ],
      top_merchants: [],
      budget_progress: [],
      monthly_trend: [],
      insights: [],
      fraud_summary: { total: 0, unread: 0 },
      recurring: [],
      generated_at: '2026-10-01T12:00:00',
    },
    '/api/dashboard/prediction': {
      status: 'insufficient_data',
      message: 'Needs 3 months of expense history.',
      prediction: null,
      required_months: 3,
      available_months: 1,
      months_needed: 2,
      observed_average: '900.00',
      history: [],
      categories: [],
      budget_projection: [],
    },
    '/api/transactions': { items: [], total: 0, page: 1, page_size: 25, pages: 0 },
    '/api/budgets': { items: [], total: 0, month: 10, year: 2026 },
    '/api/fraud/alerts': { items: [], total: 0, unread: 0, by_level: {} },
    '/api/fraud/summary': { total: 0, unread: 0 },
    '/api/notifications/unread-count': { unread: 0 },
    '/api/loans': [],
    '/api/auth/profile': { ...TEST_USER, transaction_count: 4, budget_count: 2, family_count: 0, loan_count: 1 },
    '/api/ml/status': { model_loaded: false, model: null, trained_at: null, features: [], error: 'no artifact' },
    '/api/backups': { items: [], total: 0, provider: null, configured: false, message: 'No provider configured.' },
    '/api/family': [],
  }

  const table = { ...defaults, ...overrides }
  const seen: { url?: string; method?: string }[] = []

  vi.spyOn(api, 'request').mockImplementation((config) => {
    const url = String(config.url)
    seen.push({ url, method: config.method })
    const body = table[url]
    if (body === undefined) {
      return Promise.reject(
        Object.assign(new AxiosError(`unmocked ${url}`), {
          response: { status: 404, data: { detail: `unmocked ${url}` }, statusText: '', headers: {}, config: undefined },
        }),
      )
    }
    return Promise.resolve({ data: body } as never)
  })

  return seen
}

/**
 * Waiting budget for a code-split screen.
 *
 * Every page is a `lazy()` chunk, so the first render of one also pays for
 * transforming that chunk - and the dashboard drags in Recharts, which is the
 * slowest. Testing Library's 1s default is not enough on a cold module cache, so
 * a timeout-driven failure here would say nothing about the app.
 */
const LAZY_TIMEOUT = 10_000

function renderApp(initialPath = '/') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <SessionProvider>
        <App />
      </SessionProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  sessionStorage.clear()
})

afterEach(() => {
  vi.restoreAllMocks()
  sessionStorage.clear()
})

describe('anonymous access', () => {
  it('redirects a protected route to the login screen', async () => {
    mockApi()
    renderApp('/transactions')

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /finance ai/i })).toBeInTheDocument()
    })
    // The transactions screen must never have mounted.
    expect(screen.queryByRole('heading', { name: /^transactions$/i })).not.toBeInTheDocument()
  })

  it('shows the developer form when the server reports dev auth', async () => {
    mockApi()
    renderApp()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /continue as developer/i })).toBeInTheDocument()
    })
    expect(screen.getByText(/development authentication/i)).toBeInTheDocument()
  })

  it('does not offer email sign-in forms on a dev-only server', async () => {
    mockApi()
    renderApp()

    await waitFor(() => {
      expect(screen.getByLabelText(/email/i)).toBeInTheDocument()
    })
    // Email sign-in cannot work without Firebase; showing it would be a dead end.
    expect(screen.queryByRole('button', { name: /^sign in$/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /continue with google/i })).not.toBeInTheDocument()
  })

  it('renders the login screen even when the config endpoint is unreachable', async () => {
    vi.spyOn(api, 'request').mockImplementation((config) => {
      if (String(config.url).includes('/api/auth/config')) {
        return Promise.reject(Object.assign(new AxiosError('down'), { response: undefined }))
      }
      return Promise.resolve({ data: [] } as never)
    })

    renderApp('/transactions')

    // A dead config endpoint must not leave the user on a blank screen: some
    // sign-in affordance has to render either way.
    await waitFor(() => {
      const buttons = screen.getAllByRole('button')
      expect(
        buttons.some((button) => /sign in|continue/i.test(button.textContent ?? '')),
      ).toBe(true)
    })
  })
})

describe('authenticated access', () => {
  it('restores a session from a stored development token', async () => {
    const seen = mockApi()
    // The dev token stands in for a Firebase ID token re-derived on load.
    sessionStorage.setItem('finance_ai.dev_token', 'stored-token')

    renderApp('/transactions')

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /^transactions$/i })).toBeInTheDocument()
    })

    // The stored token must actually be used to identify the caller.
    expect(seen.some((call) => call.url === '/api/auth/me')).toBe(true)
  })

  it('redirects away from /login once signed in', async () => {
    mockApi()
    sessionStorage.setItem('finance_ai.dev_token', 'stored-token')

    renderApp('/login')

    // "/login" redirects to "/", the dashboard. Asserting on the absence of the
    // login form is enough here: waiting for a transactions heading would never
    // resolve, since the redirect does not go there.
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /continue as developer/i })).not.toBeInTheDocument()
    })
    expect(
      await screen.findByRole('heading', { name: /welcome back/i }, { timeout: LAZY_TIMEOUT }),
    ).toBeInTheDocument()
  })

  it('sends the developer sign-in through the backend dev-token endpoint', async () => {
    const seen = mockApi({
      '/api/auth/dev-token': { access_token: 'fresh-token', token_type: 'bearer', expires_in: 28800, provider: 'dev' },
    })

    renderApp()
    await userEvent.type(await screen.findByLabelText(/email/i), 'dev@example.com')
    await userEvent.click(screen.getByRole('button', { name: /continue as developer/i }))

    await waitFor(() => {
      expect(seen.some((call) => call.url === '/api/auth/dev-token')).toBe(true)
    })
    expect(sessionStorage.getItem('finance_ai.dev_token')).toBe('fresh-token')
  })

  it('discards the session when the stored token is rejected', async () => {
    mockApi({
      '/api/auth/me': undefined as unknown,
    })

    vi.spyOn(api, 'request').mockImplementation((config) => {
      const url = String(config.url)
      if (url === '/api/auth/me') {
        return Promise.reject(
          Object.assign(new AxiosError('unauthorized'), {
            response: { status: 401, data: { detail: 'Invalid token' }, statusText: '', headers: {}, config: undefined },
          }),
        )
      }
      if (url === '/api/auth/config') {
        return Promise.resolve({ data: DEV_CONFIG } as never)
      }
      return Promise.resolve({ data: [] } as never)
    })

    sessionStorage.setItem('finance_ai.dev_token', 'stale-token')
    renderApp('/transactions')

    // A rejected token must leave the user anonymous, not on a screen whose
    // every request is about to fail.
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /continue as developer/i })).toBeInTheDocument()
    })
  })

  it('clears the session and returns to login on sign-out', async () => {
    mockApi()
    sessionStorage.setItem('finance_ai.dev_token', 'stored-token')

    renderApp('/transactions')
    await screen.findByRole('heading', { name: /^transactions$/i })

    await userEvent.click(screen.getAllByRole('button', { name: /sign out/i })[0])

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /continue as developer/i })).toBeInTheDocument()
    })
    expect(sessionStorage.getItem('finance_ai.dev_token')).toBeNull()
  })

  it('signs out locally even when the server acknowledgement fails', async () => {
    mockApi()
    sessionStorage.setItem('finance_ai.dev_token', 'stored-token')

    vi.spyOn(api, 'request').mockImplementation((config) => {
      const url = String(config.url)
      if (url === '/api/auth/logout') {
        return Promise.reject(new AxiosError('gateway down'))
      }
      if (url === '/api/auth/config') return Promise.resolve({ data: DEV_CONFIG } as never)
      if (url === '/api/auth/me') return Promise.resolve({ data: TEST_USER } as never)
      return Promise.resolve({ data: [] } as never)
    })

    renderApp('/transactions')
    await screen.findByRole('heading', { name: /^transactions$/i })
    await userEvent.click(screen.getAllByRole('button', { name: /sign out/i })[0])

    // The token must be discarded locally regardless of the audit call's fate.
    await waitFor(() => {
      expect(sessionStorage.getItem('finance_ai.dev_token')).toBeNull()
    })
  })
})

describe('not found', () => {
  it('shows a 404 page for an unknown route', async () => {
    mockApi()
    sessionStorage.setItem('finance_ai.dev_token', 'stored-token')

    renderApp('/nope')

    await waitFor(() => {
      expect(screen.getByText(/page not found/i)).toBeInTheDocument()
    })
  })
})

describe('protected routes', () => {
  /**
   * Each screen's heading.
   *
   * Asserting on the real heading rather than the absence of the login button is
   * the point: the login button is also absent while a lazy screen is still
   * suspended behind the Suspense fallback, so that assertion passes even when the
   * screen never renders.
   */
  const SCREENS: [path: string, heading: RegExp][] = [
    ['/', /welcome back/i],
    ['/transactions', /^transactions$/i],
    ['/budgets', /^budgets$/i],
    ['/fraud', /fraud alerts/i],
    ['/loans', /^loans$/i],
    ['/profile', /^profile$/i],
    ['/settings', /^settings$/i],
  ]

  for (const [path, heading] of SCREENS) {
    it(`renders ${path} for a signed-in user`, async () => {
      const seen = mockApi()
      sessionStorage.setItem('finance_ai.dev_token', 'stored-token')

      const view = render(
        <MemoryRouter initialEntries={[path]}>
          <SessionProvider>
            <Routes>
              <Route path="*" element={<App />} />
            </Routes>
          </SessionProvider>
        </MemoryRouter>,
      )

      // The heading proves the chunk loaded and the page rendered; the signed-in
      // chrome proves the route guard let it through. Both a sidebar and a mobile
      // header render a sign-out button, so the count is what matters.
      expect(
        await screen.findByRole('heading', { name: heading }, { timeout: LAZY_TIMEOUT }),
      ).toBeInTheDocument()
      expect(screen.getAllByRole('button', { name: /sign out/i }).length).toBeGreaterThan(0)
      expect(seen.length).toBeGreaterThan(0)

      view.unmount()
      vi.restoreAllMocks()
    })
  }
})

/**
 * Session and routing behaviour.
 *
 * All sessions are Firebase-only. Tests drive the provider through the real
 * `onIdTokenChanged` listener, mocking just the Firebase modules behind the
 * boundaries the app imports. The important assertions are the redirect rules:
 * an anonymous visitor must not reach a protected screen, and an authenticated
 * one must not be stranded on the login page. A screen that renders without its
 * guard is a data-exposure bug, because every one of them fetches on mount.
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
import { fb } from './firebaseMock'

vi.mock('firebase/auth', async () => (await import('./firebaseMock')).authModule())
vi.mock('@/lib/firebase', async () => (await import('./firebaseMock')).firebaseLibModule())

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

const FIREBASE_CONFIG: AuthConfig = {
  provider: 'firebase',
  firebase_enabled: true,
  registration_enabled: true,
  project_id: 'finance-ai-test',
  app_env: 'development',
}

const DEV_CONFIG: AuthConfig = {
  provider: 'dev',
  firebase_enabled: false,
  registration_enabled: false,
  project_id: null,
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
    '/api/auth/config': FIREBASE_CONFIG,
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

/** Preserved so the adapter a single test installs cannot leak into the next. */
const ORIGINAL_ADAPTER = api.defaults.adapter

function renderApp(initialPath = '/') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <SessionProvider>
        <App />
      </SessionProvider>
    </MemoryRouter>,
  )
}

/** A signed-in Firebase user, as `onIdTokenChanged` would report it. */
function signInFirebase(email = 'ada@example.com') {
  fb.setConfigured(true)
  fb.setProjectId('finance-ai-test')
  fb.setUser({ email, uid: 'uid-9', displayName: 'Ada Lovelace' })
}

beforeEach(() => {
  fb.reset()
})

afterEach(() => {
  api.defaults.adapter = ORIGINAL_ADAPTER
  vi.restoreAllMocks()
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

  it('shows an explanatory notice on a dev-only server and offers no forms', async () => {
    mockApi({ '/api/auth/config': DEV_CONFIG })
    renderApp()

    await waitFor(() => {
      expect(screen.getByText(/no sign-in form can succeed/i)).toBeInTheDocument()
    })
    expect(
      screen.queryByRole('button', { name: /continue as developer/i }),
    ).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/email/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^sign in$/i })).not.toBeInTheDocument()
  })

  it('shows an explanatory notice on an unconfigured server', async () => {
    mockApi({
      '/api/auth/config': {
        provider: 'unconfigured',
        firebase_enabled: false,
        registration_enabled: false,
        project_id: null,
        app_env: 'production',
      } satisfies AuthConfig,
    })
    renderApp()

    await waitFor(() => {
      expect(screen.getByText(/no sign-in form can succeed/i)).toBeInTheDocument()
    })
    expect(screen.queryByLabelText(/email/i)).not.toBeInTheDocument()
  })

  it('renders the login screen even when the config endpoint is unreachable', async () => {
    fb.setConfigured(true)
    vi.spyOn(api, 'request').mockImplementation((config) => {
      if (String(config.url).includes('/api/auth/config')) {
        return Promise.reject(Object.assign(new AxiosError('down'), { response: undefined }))
      }
      return Promise.resolve({ data: TEST_USER } as never)
    })

    renderApp('/transactions')

    // A dead config endpoint must not leave the user on a blank screen: a
    // Firebase-ready build still offers the forms.
    await waitFor(() => {
      expect(screen.getByLabelText(/email/i)).toBeInTheDocument()
    })
  })

  it('warns when the build points at a different Firebase project than the server', async () => {
    mockApi({ '/api/auth/config': { ...FIREBASE_CONFIG, project_id: 'server-project' } })
    fb.setConfigured(true)
    fb.setProjectId('client-project')
    renderApp()

    await waitFor(() => {
      expect(screen.getByText(/different one/i)).toBeInTheDocument()
    })
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument()
  })

  it('warns when the server is on Firebase but this build is not configured', async () => {
    mockApi()
    fb.setConfigured(false)
    renderApp()

    await waitFor(() => {
      expect(screen.getByText(/VITE_FIREBASE/i)).toBeInTheDocument()
    })
  })
})

describe('authenticated access', () => {
  it('restores a session when Firebase reports a signed-in user', async () => {
    const seen = mockApi()
    signInFirebase()

    renderApp('/transactions')

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /^transactions$/i })).toBeInTheDocument()
    })

    // The Firebase token must actually be used to identify the caller.
    expect(seen.some((call) => call.url === '/api/auth/me')).toBe(true)
  })

  it('redirects away from /login once signed in', async () => {
    const seen = mockApi()
    signInFirebase()

    renderApp('/login')

    // "/login" redirects to "/", the dashboard. Wait for that heading first: it
    // proves the token was adopted and the redirect ran. Asserting on the
    // absence of the login form instead would also be true during the loading
    // spinner, so it would pass without proving anything.
    expect(
      await screen.findByRole('heading', { name: /welcome back/i }, { timeout: LAZY_TIMEOUT }),
    ).toBeInTheDocument()
    expect(screen.queryByLabelText(/email/i)).not.toBeInTheDocument()
    expect(seen.some((call) => call.url === '/api/auth/me')).toBe(true)
  })

  it('discards the session when the server rejects the Firebase token', async () => {
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
        return Promise.resolve({ data: FIREBASE_CONFIG } as never)
      }
      return Promise.resolve({ data: [] } as never)
    })
    signInFirebase()

    renderApp('/transactions')

    // A rejected token must leave the user anonymous, not on a screen whose
    // every request is about to fail.
    await waitFor(() => {
      expect(screen.getByLabelText(/email/i)).toBeInTheDocument()
    })
  })

  it('clears the session and returns to login on sign-out', async () => {
    mockApi()
    signInFirebase()

    renderApp('/transactions')
    await screen.findByRole('heading', { name: /^transactions$/i })

    await userEvent.click(screen.getAllByRole('button', { name: /sign out/i })[0])

    await waitFor(() => {
      expect(screen.getByLabelText(/email/i)).toBeInTheDocument()
    })
    // Firebase itself was signed out, not just the local state.
    expect(fb.user).toBeNull()
  })

  it('signs out locally even when the server acknowledgement fails', async () => {
    vi.spyOn(api, 'request').mockImplementation((config) => {
      const url = String(config.url)
      if (url === '/api/auth/logout') {
        return Promise.reject(new AxiosError('gateway down'))
      }
      if (url === '/api/auth/config') return Promise.resolve({ data: FIREBASE_CONFIG } as never)
      if (url === '/api/auth/me') return Promise.resolve({ data: TEST_USER } as never)
      return Promise.resolve({ data: [] } as never)
    })
    signInFirebase()

    renderApp('/transactions')
    await screen.findByRole('heading', { name: /^transactions$/i })
    await userEvent.click(screen.getAllByRole('button', { name: /sign out/i })[0])

    // The session must end locally regardless of the audit call's fate.
    await waitFor(() => {
      expect(screen.getByLabelText(/email/i)).toBeInTheDocument()
    })
    expect(fb.user).toBeNull()
  })

  it('re-adopts the refreshed ID token when Firebase renews it', async () => {
    const captured: Array<string | null> = []
    api.defaults.adapter = async (config) => {
      captured.push(config.headers.get('Authorization') as string | null)
      const url = String(config.url)
      const data = url === '/api/auth/me'
        ? TEST_USER
        : url === '/api/auth/config'
          ? FIREBASE_CONFIG
          : []
      return {
        data,
        status: 200,
        statusText: 'OK',
        headers: {},
        config,
      } as never
    }
    signInFirebase()

    renderApp('/transactions')
    await screen.findByRole('heading', { name: /^transactions$/i })

    // The initial session used the first token.
    expect(captured.some((header) => header === 'Bearer signed-in-token')).toBe(true)

    // Firebase renews the ID token mid-session; the provider must adopt it so
    // subsequent requests carry the fresh credential instead of 401ing an hour
    // in.
    fb.setToken('refreshed-token')

    await waitFor(() => {
      expect(captured.some((header) => header === 'Bearer refreshed-token')).toBe(true)
    })
  })
})

describe('not found', () => {
  it('shows a 404 page for an unknown route', async () => {
    mockApi()
    signInFirebase()

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
      signInFirebase()

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
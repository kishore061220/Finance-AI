/**
 * Settings page - regression tests for the blank-page bug and resilience.
 *
 * P2: the MlStatus shape did not match the backend. When `model_loaded` became
 * `true`, accessing `status.features.length` threw and, because the page had no
 * ErrorBoundary wrapping it, the entire app could blank out. These tests make
 * sure:
 *
 * - a loaded model renders safely without crashing;
 * - a failed `/api/ml/status` still lets Settings render (and offers a retry);
 * - a failed `/api/backups` list does not mislead the user with "No backups yet";
 * - malformed/partial responses do not crash the page;
 * - retries actually reload data.
 */

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AxiosError } from 'axios'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from '@/App'
import { SessionProvider } from '@/auth/SessionContext'
import { api } from '@/lib/api'
import type { UserResponse } from '@/types'
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

const LAZY_TIMEOUT = 15_000

const FIREBASE_CONFIG = {
  provider: 'firebase',
  firebase_enabled: true,
  registration_enabled: true,
  project_id: 'finance-ai-test',
  app_env: 'development',
}

// Real backend MlStatus shape (not loaded)
const ML_NOT_LOADED = {
  sklearn_available: true,
  sklearn_reason: null,
  model_loaded: false,
  model_name: null,
  feature_count: 12,
  load_error: 'no artifact',
  user_transaction_count: 4,
  scoring_mode: 'rules_only',
  message: 'No trained model is available, so scoring uses the rule engine only.',
}

// Real backend MlStatus shape (loaded) - this would have crashed the old UI.
const ML_LOADED = {
  sklearn_available: true,
  sklearn_reason: null,
  model_loaded: true,
  model_name: 'fraud_xgb_v1',
  feature_count: 15,
  load_error: null,
  user_transaction_count: 87,
  scoring_mode: 'combined',
  message: 'The trained model is loaded; scores combine it with the rule engine.',
}

const BACKUPS_OK = {
  items: [
    {
      id: 1,
      provider: 'GOOGLE_DRIVE',
      status: 'SUCCESS',
      checksum: 'abc123',
      record_count: 12,
      created_at: '2026-10-15T10:00:00',
      error_message: null,
    },
  ],
  total: 1,
  provider: 'GOOGLE_DRIVE',
  configured: true,
  message: null,
}

const BACKUPS_NOT_CONFIGURED = {
  items: [],
  total: 0,
  provider: null,
  configured: false,
  message: 'No provider configured.',
}

type RouteTable = Record<string, unknown>

function renderApp(initial: string = '/settings') {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <SessionProvider>
        <Routes>
          <Route path="*" element={<App />} />
        </Routes>
      </SessionProvider>
    </MemoryRouter>,
  )
}

function signInFirebase() {
  fb.setConfigured(true)
  fb.setProjectId('finance-ai-test')
  fb.setUser({ uid: 'uid-9', email: TEST_USER.email, displayName: TEST_USER.name })
}

/**
 * Install a routing adapter. A value of `'error'` makes that URL reject with a
 * 500, a value of a function is resolved per call (for retry tests).
 */
function installApi(table: RouteTable) {
  const calls: Array<{ url: string; method?: string }> = []
  const base: RouteTable = {
    '/api/auth/config': FIREBASE_CONFIG,
    '/api/auth/me': TEST_USER,
    '/api/fraud/summary': { total: 0, unread: 0 },
    ...table,
  }

  api.defaults.adapter = (async (config) => {
    const url = String(config.url)
    calls.push({ url, method: config.method })
    const entry = base[url]
    if (entry === 'error') {
      throw Object.assign(new AxiosError('boom'), {
        response: { status: 500, data: { detail: 'boom' }, statusText: '', headers: {}, config },
      })
    }
    const data = typeof entry === 'function' ? (entry as () => unknown)() : entry
    return { data, status: 200, statusText: 'OK', headers: {}, config }
  }) as never

  return calls
}

function fraudCard(): HTMLElement {
  const heading = screen.getByRole('heading', { name: /^Fraud model$/i })
  return heading.closest('section') as HTMLElement
}

beforeEach(() => {
  fb.reset()
  fb.setToken('signed-in-token')
})

afterEach(() => {
  vi.restoreAllMocks()
})

async function openSettings() {
  const result = renderApp('/settings')
  await screen.findByRole('heading', { name: /^settings$/i }, { timeout: LAZY_TIMEOUT })
  return result
}

describe('Settings page', () => {
  it('renders with model not loaded and backups present', async () => {
    installApi({ '/api/ml/status': ML_NOT_LOADED, '/api/backups': BACKUPS_OK })
    signInFirebase()
    await openSettings()

    await waitFor(() => expect(within(fraudCard()).getByText(/not loaded/i)).toBeInTheDocument())
    expect(within(fraudCard()).getByText(/rules only/i)).toBeInTheDocument()
    expect(within(fraudCard()).getByText(/4 of your transactions are available/i)).toBeInTheDocument()
    expect(await screen.findByText(/GOOGLE_DRIVE/i)).toBeInTheDocument()
    expect(screen.queryByText(/Could not read the model status/i)).not.toBeInTheDocument()
  })

  it('regression: model loaded still renders without crash (no features.length access)', async () => {
    installApi({ '/api/ml/status': ML_LOADED, '/api/backups': BACKUPS_NOT_CONFIGURED })
    signInFirebase()
    await openSettings()

    await waitFor(() => {
      const card = fraudCard()
      expect(within(card).getByText('Loaded', { exact: true })).toBeInTheDocument()
    })
    const card = fraudCard()
    expect(within(card).getByText(/fraud_xgb_v1/i)).toBeInTheDocument()
    expect(within(card).getByText(/Scores 15 features/i)).toBeInTheDocument()
    expect(screen.queryByText(/Could not read the model status/i)).not.toBeInTheDocument()
  })

  it('when ml/status fails, Settings still renders and offers retry; backups still load', async () => {
    let mlAttempts = 0
    installApi({
      '/api/ml/status': () => {
        mlAttempts += 1
        if (mlAttempts === 1) throw Object.assign(new AxiosError('boom'), {
          response: { status: 500, data: { detail: 'ml down' }, statusText: '', headers: {}, config: undefined },
        })
        return ML_NOT_LOADED
      },
      '/api/backups': BACKUPS_NOT_CONFIGURED,
    })
    signInFirebase()
    await openSettings()

    // Heading remains; ML panel shows error with retry.
    expect(await screen.findByText(/Could not read the model status/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument()
    // Backups section still rendered.
    expect(await screen.findByText(/No provider configured/i)).toBeInTheDocument()

    // Retry succeeds and ML becomes healthy.
    await userEvent.click(screen.getByRole('button', { name: /try again/i }))
    await waitFor(() => expect(within(fraudCard()).getByText(/not loaded/i)).toBeInTheDocument())
  })

  it('when backups list fails, show backups error and do NOT show "No backups yet"', async () => {
    let attempts = 0
    installApi({
      '/api/ml/status': ML_NOT_LOADED,
      '/api/backups': () => {
        attempts++
        if (attempts === 1) throw Object.assign(new AxiosError('down'), {
          response: { status: 500, data: { detail: 'backups down' }, statusText: '', headers: {}, config },
        })
        return BACKUPS_NOT_CONFIGURED
      },
    })
    signInFirebase()
    await openSettings()

    await waitFor(() => expect(within(fraudCard()).getByText(/not loaded/i)).toBeInTheDocument())

    // Backups error shown; empty-state must not be shown when errored.
    const backupsHeading = screen.getByRole('heading', { name: /^Backups$/i })
    const backupsCard = backupsHeading.closest('section') as HTMLElement
    await within(backupsCard).findByRole('alert')
    expect(within(backupsCard).queryByText(/No backups yet/i)).not.toBeInTheDocument()

    // Retry in backups, then it loads normally.
    const retry = within(backupsCard).getByRole('button', { name: /try again/i })
    await userEvent.click(retry)
    await waitFor(() => expect(screen.getByText(/No provider configured/i)).toBeInTheDocument())
  })

  it('malformed ML response does not crash the page', async () => {
    installApi({ '/api/ml/status': {}, '/api/backups': BACKUPS_OK })
    signInFirebase()
    await openSettings()

    // Panel still renders (falls into the not-loaded branch) rather than throwing.
    await waitFor(() => expect(within(fraudCard()).getByText(/not loaded/i)).toBeInTheDocument())
    expect(screen.queryByText(/Something went wrong on this screen/i)).not.toBeInTheDocument()
  })

  it('malformed backups response does not crash the page', async () => {
    installApi({ '/api/ml/status': ML_NOT_LOADED, '/api/backups': { items: [] } })
    signInFirebase()
    await openSettings()

    await waitFor(() => expect(within(fraudCard()).getByText(/not loaded/i)).toBeInTheDocument())
    // No items and no error -> the empty state is the honest answer.
    expect(await screen.findByText(/No backups yet/i)).toBeInTheDocument()
    expect(screen.queryByText(/Something went wrong on this screen/i)).not.toBeInTheDocument()
  })
})

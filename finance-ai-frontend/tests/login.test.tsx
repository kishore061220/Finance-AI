/**
 * Login form behaviour.
 *
 * Covers the three things the login screen is responsible for beyond rendering:
 * turning Firebase failures into safe messages, offering a password reset
 * without revealing whether an address is registered, and falling back to the
 * redirect flow when the Google popup is blocked.
 *
 * The Firebase SDK is mocked behind the same module boundary the app imports
 * (`firebase/auth`), so the real sign-in handlers in `SessionContext` run.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AxiosError } from 'axios'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { SessionProvider } from '@/auth/SessionContext'
import { api } from '@/lib/api'
import LoginPage from '@/pages/LoginPage'
import type { AuthConfig, UserResponse } from '@/types'
import { fb } from './firebaseMock'

vi.mock('firebase/auth', async () => (await import('./firebaseMock')).authModule())
vi.mock('@/lib/firebase', async () => (await import('./firebaseMock')).firebaseLibModule())

const FIREBASE_CONFIG: AuthConfig = {
  provider: 'firebase',
  firebase_enabled: true,
  registration_enabled: true,
  project_id: 'finance-ai-test',
  app_env: 'development',
}

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

/** Answer the endpoints the session provider touches on boot. */
function mockApi(overrides: Record<string, unknown> = {}) {
  const table: Record<string, unknown> = {
    '/api/auth/config': FIREBASE_CONFIG,
    '/api/auth/me': TEST_USER,
    ...overrides,
  }
  vi.spyOn(api, 'request').mockImplementation((config) => {
    const url = String(config.url)
    if (url in table) {
      const body = table[url]
      // An Error in the table models a rejected request (401, offline, ...);
      // anything else is a successful body.
      if (body instanceof Error) return Promise.reject(body)
      return Promise.resolve({ data: body } as never)
    }
    return Promise.reject(
      Object.assign(new AxiosError(`unmocked ${url}`), {
        response: { status: 404, data: { detail: `unmocked ${url}` }, statusText: '', headers: {}, config: undefined },
      }),
    )
  })
}

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={['/login']}>
      <SessionProvider>
        <LoginPage />
      </SessionProvider>
    </MemoryRouter>,
  )
}

async function fillCredentials() {
  await userEvent.type(await screen.findByLabelText(/email/i), 'ada@example.com')
  await userEvent.type(screen.getByLabelText(/password/i), 'secret123')
}

beforeEach(() => {
  fb.reset()
  fb.setConfigured(true)
  fb.setProjectId('finance-ai-test')
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('email sign-in errors', () => {
  it('shows a safe, actionable message for invalid credentials', async () => {
    mockApi()
    fb.signInWithEmailAndPassword.mockRejectedValueOnce(
      Object.assign(new Error('Firebase: Error (auth/invalid-credential).'), {
        code: 'auth/invalid-credential',
      }),
    )

    renderLogin()
    await fillCredentials()
    await userEvent.click(screen.getByRole('button', { name: /^sign in$/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/email or password is incorrect/i)
    // The raw SDK string must never reach the user.
    expect(screen.queryByText(/auth\/invalid-credential/)).not.toBeInTheDocument()
  })

  it('explains an API rejection after Firebase accepted the sign-in', async () => {
    mockApi({
      '/api/auth/me': Object.assign(new AxiosError('unauthorized'), {
        response: { status: 401, data: { detail: 'Invalid token' }, statusText: '', headers: {}, config: undefined },
      }),
    })
    fb.signInWithEmailAndPassword.mockResolvedValueOnce({
      user: { getIdToken: async () => 'fresh-token' },
    } as never)

    renderLogin()
    await fillCredentials()
    await userEvent.click(screen.getByRole('button', { name: /^sign in$/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/API rejected the session/i)
  })
})

describe('forgot password', () => {
  it('asks for an email before sending', async () => {
    mockApi()
    renderLogin()

    await userEvent.click(await screen.findByRole('button', { name: /forgot password/i }))

    expect(screen.getByRole('alert')).toHaveTextContent(/enter your email/i)
    expect(fb.sendPasswordResetEmail).not.toHaveBeenCalled()
  })

  it('sends a reset link and confirms without revealing account existence', async () => {
    mockApi()
    renderLogin()

    await userEvent.type(await screen.findByLabelText(/email/i), 'ada@example.com')
    await userEvent.click(screen.getByRole('button', { name: /forgot password/i }))

    await waitFor(() => expect(fb.sendPasswordResetEmail).toHaveBeenCalledTimes(1))
    expect(fb.sendPasswordResetEmail.mock.calls[0][1]).toBe('ada@example.com')
    expect(await screen.findByRole('status')).toHaveTextContent(/if an account exists/i)
  })

  it('treats an unknown account the same as a known one', async () => {
    mockApi()
    fb.sendPasswordResetEmail.mockRejectedValueOnce(
      Object.assign(new Error('Firebase: Error (auth/user-not-found).'), {
        code: 'auth/user-not-found',
      }),
    )

    renderLogin()
    await userEvent.type(await screen.findByLabelText(/email/i), 'nobody@example.com')
    await userEvent.click(screen.getByRole('button', { name: /forgot password/i }))

    // The same confirmation appears, so the response cannot be used to probe.
    expect(await screen.findByRole('status')).toHaveTextContent(/if an account exists/i)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

describe('Google sign-in', () => {
  it('falls back to the redirect flow when the popup is blocked', async () => {
    mockApi()
    fb.signInWithPopup.mockRejectedValueOnce(
      Object.assign(new Error('Firebase: Error (auth/popup-blocked).'), {
        code: 'auth/popup-blocked',
      }),
    )

    renderLogin()
    await userEvent.click(await screen.findByRole('button', { name: /continue with google/i }))

    await waitFor(() => expect(fb.signInWithRedirect).toHaveBeenCalledTimes(1))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('reports a cancelled popup instead of silently returning to the form', async () => {
    mockApi()
    fb.signInWithPopup.mockRejectedValueOnce(
      Object.assign(new Error('Firebase: Error (auth/popup-closed-by-user).'), {
        code: 'auth/popup-closed-by-user',
      }),
    )

    renderLogin()
    await userEvent.click(await screen.findByRole('button', { name: /continue with google/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/closed before it finished/i)
  })
})

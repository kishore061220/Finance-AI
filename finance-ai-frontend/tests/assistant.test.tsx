/**
 * Assistant page - request lifecycle and honest fallback behaviour.
 *
 * Pins down:
 * - a typed question is sent and the remote answer is shown;
 * - a loading indicator appears and duplicate submissions are blocked;
 * - a retryable fallback is clearly labelled and can be retried;
 * - a hard request error surfaces to the user.
 */

import { render, screen, waitFor } from '@testing-library/react'
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

const FIREBASE_CONFIG = {
  provider: 'firebase',
  firebase_enabled: true,
  registration_enabled: true,
  project_id: 'finance-ai-test',
  app_env: 'development',
}

const ASSISTANT_CONFIG = {
  provider: 'gemini',
  model: 'gemini-3.8-flash',
  remote_configured: true,
  status: 'configured',
  message: 'Remote model configured.',
  suggestions: ['How much did I spend this period?', 'Which category is my biggest expense?'],
}

type AssistantReply = {
  reply: string
  provider: string
  model: string | null
  context_used: string[]
  suggestions: string[]
  fallback: boolean
  retryable?: boolean
}

type Handler = unknown | ((config: { data?: string }) => unknown | Promise<unknown>)

function installApi(table: Record<string, Handler>) {
  const calls: Array<{ url: string; method?: string; data?: AssistantReply }> = []
  const base: Record<string, Handler> = {
    '/api/auth/config': FIREBASE_CONFIG,
    '/api/auth/me': TEST_USER,
    ...table,
  }

  api.defaults.adapter = (async (config) => {
    const url = String(config.url)
    calls.push({
      url,
      method: config.method,
      data: typeof config.data === 'string' ? JSON.parse(config.data) : config.data,
    })
    const entry = base[url]
    const value = typeof entry === 'function' ? await (entry as Handler)(config as never) : entry
    return { data: value, status: 200, statusText: '', headers: {}, config }
  }) as never

  return calls
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((r) => {
    resolve = r
  })
  return { promise, resolve }
}

function signInFirebase() {
  fb.setConfigured(true)
  fb.setProjectId('finance-ai-test')
  fb.setUser({ uid: 'uid-9', email: TEST_USER.email, displayName: TEST_USER.name })
}

function renderAssistant() {
  return render(
    <MemoryRouter initialEntries={['/assistant']}>
      <SessionProvider>
        <Routes>
          <Route path="*" element={<App />} />
        </Routes>
      </SessionProvider>
    </MemoryRouter>,
  )
}

async function openAssistant() {
  await screen.findByRole('heading', { name: /assistant/i })
}

beforeEach(() => {
  signInFirebase()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('AssistantPage', () => {
  it('sends a typed question and shows the remote answer', async () => {
    const calls = installApi({
      '/api/assistant/config': ASSISTANT_CONFIG,
      '/api/assistant': {
        reply: 'You spent \u20b91,23,456.78.',
        provider: 'gemini',
        model: 'gemini-3.8-flash',
        context_used: [],
        suggestions: [],
        fallback: false,
        retryable: false,
      } satisfies AssistantReply,
    })
    renderAssistant()
    await openAssistant()

    await userEvent.type(screen.getByLabelText(/your question/i), 'How much did I spend?')
    await userEvent.click(screen.getByRole('button', { name: /send/i }))

    expect(await screen.findByText('You spent \u20b91,23,456.78.')).toBeInTheDocument()
    const ask = calls.find((c) => c.url === '/api/assistant')
    expect(ask?.data?.message).toBe('How much did I spend?')
  })

  it('shows a loading indicator and blocks duplicate submissions', async () => {
    const gate = deferred<AssistantReply>()
    let asks = 0
    installApi({
      '/api/assistant/config': ASSISTANT_CONFIG,
      '/api/assistant': () => {
        asks += 1
        return gate.promise
      },
    })
    renderAssistant()
    await openAssistant()

    await userEvent.type(screen.getByLabelText(/your question/i), 'Hello')
    const send = screen.getByRole('button', { name: /send/i })
    await userEvent.click(send)

    expect(await screen.findByText(/thinking/i)).toBeInTheDocument()
    expect(send).toBeDisabled()
    // A second click while pending must not fire another request.
    await userEvent.click(send)
    expect(asks).toBe(1)

    gate.resolve({
      reply: 'ok',
      provider: 'gemini',
      model: null,
      context_used: [],
      suggestions: [],
      fallback: false,
      retryable: false,
    })
    expect(await screen.findByText('ok')).toBeInTheDocument()
  })

  it('labels a retryable fallback and lets the user retry it', async () => {
    let asks = 0
    installApi({
      '/api/assistant/config': ASSISTANT_CONFIG,
      '/api/assistant': () => {
        asks += 1
        if (asks === 1) {
          return {
            reply: 'Built-in answer',
            provider: 'builtin',
            model: null,
            context_used: [],
            suggestions: [],
            fallback: true,
            retryable: true,
          } satisfies AssistantReply
        }
        return {
          reply: 'Real remote answer',
          provider: 'gemini',
          model: 'gemini-3.8-flash',
          context_used: [],
          suggestions: [],
          fallback: false,
          retryable: false,
        } satisfies AssistantReply
      },
    })
    renderAssistant()
    await openAssistant()

    await userEvent.type(screen.getByLabelText(/your question/i), 'Explain how EMIs work')
    await userEvent.click(screen.getByRole('button', { name: /send/i }))

    expect(await screen.findByText('Built-in answer')).toBeInTheDocument()
    expect(screen.getByText(/could not answer, so this is a built-in reply/i)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /retry/i }))
    expect(await screen.findByText('Real remote answer')).toBeInTheDocument()
    expect(asks).toBe(2)
  })

  it('surfaces a hard request error', async () => {
    installApi({
      '/api/assistant/config': ASSISTANT_CONFIG,
      '/api/assistant': () => {
        throw new AxiosError('boom', '500', undefined, undefined, {
          status: 500,
          statusText: 'Server Error',
          data: { detail: 'assistant exploded' },
          headers: {},
          config: undefined as never,
        })
      },
    })
    renderAssistant()
    await openAssistant()

    await userEvent.type(screen.getByLabelText(/your question/i), 'Hello')
    await userEvent.click(screen.getByRole('button', { name: /send/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/assistant exploded/i)
    // The request finished (no spinner) and a new question can be submitted.
    expect(screen.queryByText(/thinking/i)).not.toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/your question/i), 'Try again')
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /send/i })).not.toBeDisabled(),
    )
  })
})

/**
 * Financial assistant chat.
 *
 * The backend answers from the caller's own rows and, for general questions,
 * from the remote Gemini model. The config endpoint reports which engine is
 * active. When a remote call fails the backend falls back to the built-in
 * engine and flags the reply `retryable`, so the UI can be honest about it and
 * offer a retry instead of presenting a canned answer as if the model said it.
 */

import { useRef, useState, type FormEvent } from 'react'

import { Alert, Button, Card, Field, PageHeader, Spinner, TextInput } from '@/components/ui'
import { useAsync } from '@/hooks/useAsync'
import { assistantApi } from '@/lib/endpoints'

type Message = {
  id: number
  role: 'user' | 'assistant'
  content: string
  /** Set on assistant replies that are a retryable built-in fallback. */
  retryable?: boolean
}

export default function AssistantPage() {
  const config = useAsync(() => assistantApi.config(), [])
  const idRef = useRef(0)
  const [message, setMessage] = useState('')
  const [history, setHistory] = useState<Message[]>([])
  const [asking, setAsking] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const send = async (text: string, base?: Message[]) => {
    const trimmed = text.trim()
    // `asking` guards against duplicate submissions: a second Enter/click while
    // a request is in flight is ignored (and the Send button is disabled too).
    if (!trimmed || asking) return
    const prior = base ?? history
    const next: Message[] = [
      ...prior,
      { id: idRef.current++, role: 'user', content: trimmed },
    ]
    setError(null)
    setAsking(true)
    setHistory(next)
    setMessage('')
    try {
      // Only the last few turns are sent: the backend context is the caller's
      // own rows, so a long transcript adds tokens without changing the answer.
      const res = await assistantApi.ask({
        message: trimmed,
        history: prior.slice(-10).map(({ role, content }) => ({ role, content })),
      })
      setHistory([
        ...next,
        {
          id: idRef.current++,
          role: 'assistant',
          content: res.reply,
          retryable: res.retryable,
        },
      ])
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'The assistant could not answer.')
    } finally {
      setAsking(false)
    }
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    void send(message)
  }

  // Re-ask the question that produced a failed reply, dropping the failed pair.
  const retry = (assistantId: number) => {
    const idx = history.findIndex((entry) => entry.id === assistantId)
    if (idx < 1) return
    const question = history[idx - 1].content
    void send(question, history.slice(0, idx - 1))
  }

  const configUnavailable = config.data?.status === 'unavailable'

  return (
    <div className="space-y-6">
      <PageHeader
        title="Assistant"
        description={config.data?.message ?? 'Ask questions about your own finances.'}
      />

      {config.error && <Alert tone="error">{config.error}</Alert>}
      {configUnavailable && !config.error && (
        <Alert tone="warning">
          The remote model is unavailable right now. Answers may come from the
          built-in assistant until it recovers.
        </Alert>
      )}

      <Card>
        {history.length === 0 ? (
          <p className="text-sm text-muted">
            Ask something like “How much did I spend on food last month?”
          </p>
        ) : (
          <div className="mb-4 max-h-96 space-y-3 overflow-y-auto" aria-live="polite">
            {history.map((entry) => (
              <div
                key={entry.id}
                className={`rounded-lg px-3 py-2 text-sm ${
                  entry.role === 'user'
                    ? 'ml-8 bg-accent/10 text-text'
                    : 'mr-8 bg-surface-2 text-text-strong'
                }`}
              >
                <p className="whitespace-pre-wrap">{entry.content}</p>
                {entry.role === 'assistant' && entry.retryable && (
                  <div className="mt-2 space-y-2">
                    <p className="text-xs text-warning">
                      The remote model could not answer, so this is a built-in reply.
                    </p>
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      disabled={asking}
                      onClick={() => retry(entry.id)}
                    >
                      Retry
                    </Button>
                  </div>
                )}
              </div>
            ))}
            {asking && <Spinner label="Thinking" />}
          </div>
        )}

        <form onSubmit={submit} className="space-y-3">
          {error && <Alert tone="error">{error}</Alert>}
          <Field label="Your question" htmlFor="assistant-message">
            <TextInput
              id="assistant-message"
              placeholder="Ask about your finances…"
              value={message}
              onChange={(event) => setMessage(event.target.value)}
            />
          </Field>
          <Button type="submit" loading={asking} disabled={!message.trim() || asking}>
            Send
          </Button>
        </form>

        {(config.data?.suggestions.length ?? 0) > 0 && (
          <div className="mt-4 flex flex-wrap gap-2">
            {config.data?.suggestions.map((suggestion) => (
              <Button
                key={suggestion}
                type="button"
                variant="ghost"
                size="sm"
                disabled={asking}
                onClick={() => void send(suggestion)}
              >
                {suggestion}
              </Button>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}

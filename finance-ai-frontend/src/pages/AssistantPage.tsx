/**
 * Financial assistant chat.
 *
 * The backend answers from the caller's own rows; the config endpoint reports
 * which engine is active (built-in or a configured remote model). When a remote
 * model is configured but unavailable the backend falls back, and the reply still
 * carries the real text, so whatever comes back is shown as-is.
 */

import { useRef, useState, type FormEvent } from 'react'

import { Alert, Button, Card, Field, PageHeader, Spinner, TextInput } from '@/components/ui'
import { useAsync } from '@/hooks/useAsync'
import { assistantApi } from '@/lib/endpoints'

type Message = { id: number; role: 'user' | 'assistant'; content: string }

export default function AssistantPage() {
  const config = useAsync(() => assistantApi.config(), [])
  const idRef = useRef(0)
  const [message, setMessage] = useState('')
  const [history, setHistory] = useState<Message[]>([])
  const [asking, setAsking] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const send = async (text: string) => {
    const trimmed = text.trim()
    if (!trimmed || asking) return
    setError(null)
    setAsking(true)
    const next = [...history, { id: idRef.current++, role: 'user' as const, content: trimmed }]
    setHistory(next)
    setMessage('')
    try {
      // Only the last few turns are sent: the backend context is the caller's
      // own rows, so a long transcript adds tokens without changing the answer.
      const res = await assistantApi.ask({
        message: trimmed,
        history: history.slice(-10),
      })
      setHistory([...next, { id: idRef.current++, role: 'assistant', content: res.reply }])
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

  return (
    <div className="space-y-6">
      <PageHeader
        title="Assistant"
        description={config.data?.message ?? 'Ask questions about your own finances.'}
      />

      {config.error && <Alert tone="error">{config.error}</Alert>}

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
          <Button type="submit" loading={asking} disabled={!message.trim()}>
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

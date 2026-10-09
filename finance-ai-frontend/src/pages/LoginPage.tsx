/**
 * Sign-in screen.
 *
 * Which form is shown depends on what the server says it supports
 * (`GET /api/auth/config`), not on what the bundle happens to have configured.
 * When Firebase is not configured in the build but the backend reports dev auth,
 * the developer sign-in form appears; when the backend reports Firebase, the
 * email/Google forms appear regardless.
 */

import { useState, type FormEvent } from 'react'
import { Navigate } from 'react-router-dom'

import { useSession, isFirebaseConfigured } from '@/auth/SessionContext'
import { Alert, Button, Card, Field, TextInput } from '@/components/ui'

type Mode = 'signin' | 'signup' | 'developer'

export default function LoginPage() {
  const { status, config, signInWithEmail, signUp, signInWithGoogle, signInAsDeveloper } = useSession()

  const [mode, setMode] = useState<Mode>('signin')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  /**
   * The backend's own view of the provider wins over the build's.
   *
   * A build with Firebase variables pointing at a real project, talking to a
   * server that has Firebase disabled, would otherwise show forms that cannot
   * possibly work.
   */
  const serverSaysFirebase = config?.firebase_enabled ?? isFirebaseConfigured()
  const devOnly = config?.provider === 'dev' || (!serverSaysFirebase && config !== null)

  /**
   * The tab actually shown, derived rather than synchronised.
   *
   * An effect would need a second render pass to reach the same result, and in
   * between the email form would briefly render on a server that only accepts
   * the developer token - forms the user cannot submit.
   */
  const activeMode = devOnly && mode === 'signin' ? 'developer' : mode

  if (status === 'authenticated') {
    return <Navigate to="/" replace />
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (activeMode === 'signin') {
        await signInWithEmail(email, password)
      } else if (activeMode === 'signup') {
        await signUp(email, password, name)
      } else {
        await signInAsDeveloper(email)
      }
    } catch (cause: unknown) {
      setError(
        cause instanceof Error ? cause.message : 'Could not sign in. Please try again.',
      )
    } finally {
      setBusy(false)
    }
  }

  const googleSignIn = async () => {
    setBusy(true)
    setError(null)
    try {
      await signInWithGoogle()
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Google sign-in failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4 py-10">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <h1 className="text-3xl">Finance AI</h1>
          <p className="mt-2 text-sm text-muted">
            Track spending, budgets, loans, and fraud alerts in one place.
          </p>
        </div>

        <Card>
          {error && (
            <div className="mb-4">
              <Alert tone="error">{error}</Alert>
            </div>
          )}

          {devOnly ? (
            <form onSubmit={submit} className="space-y-4">
              <Alert tone="warning">
                This server is running with development authentication. Configure Firebase before
                deploying.
              </Alert>

              <Field label="Email" htmlFor="dev-email" hint="Any email works on a dev server.">
                <TextInput
                  id="dev-email"
                  type="email"
                  autoComplete="username"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  required
                />
              </Field>

              <Button type="submit" loading={busy} className="w-full">
                Continue as developer
              </Button>
            </form>
          ) : (
            <>
              <form onSubmit={submit} className="space-y-4">
                {activeMode === 'signup' && (
                  <Field label="Full name" htmlFor="name">
                    <TextInput
                      id="name"
                      autoComplete="name"
                      value={name}
                      onChange={(event) => setName(event.target.value)}
                      required
                    />
                  </Field>
                )}

                <Field label="Email" htmlFor="email">
                  <TextInput
                    id="email"
                    type="email"
                    autoComplete="username"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    required
                  />
                </Field>

                <Field label="Password" htmlFor="password">
                  <TextInput
                    id="password"
                    type="password"
                    // `current-password` on sign-in tells password managers which
                    // credential to offer, instead of generating a new one.
                    autoComplete={activeMode === 'signup' ? 'new-password' : 'current-password'}
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    minLength={activeMode === 'signup' ? 6 : undefined}
                    required
                  />
                </Field>

                <Button type="submit" loading={busy} className="w-full">
                  {activeMode === 'signup' ? 'Create account' : 'Sign in'}
                </Button>
              </form>

              <div className="my-4 flex items-center gap-3 text-xs text-muted">
                <span className="h-px flex-1 bg-border-subtle" />
                or
                <span className="h-px flex-1 bg-border-subtle" />
              </div>

              <Button
                type="button"
                variant="secondary"
                className="w-full"
                loading={busy}
                onClick={() => void googleSignIn()}
              >
                Continue with Google
              </Button>

              <p className="mt-5 text-center text-sm text-muted">
                {activeMode === 'signup' ? 'Already have an account?' : 'No account yet?'}{' '}
                <button
                  type="button"
                  className="text-accent hover:underline"
                  onClick={() => setMode(activeMode === 'signup' ? 'signin' : 'signup')}
                >
                  {activeMode === 'signup' ? 'Sign in' : 'Create one'}
                </button>
              </p>
            </>
          )}
        </Card>
      </div>
    </div>
  )
}

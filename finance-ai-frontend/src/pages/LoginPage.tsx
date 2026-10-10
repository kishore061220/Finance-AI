/**
 * Sign-in screen.
 *
 * Which form is shown depends on what the server says it supports
 * (`GET /api/auth/config`), not on what the bundle happens to have configured.
 * The only authentication path this client offers is Firebase:
 *
 *  - server on Firebase  -> email/Google forms, plus a warning when this build
 *    points at a different project or has no `VITE_FIREBASE_*` variables.
 *  - server unreachable  -> the forms can only appear when the build itself has
 *    Firebase configured; otherwise an explanatory notice is shown.
 *  - server on dev/unconfigured auth -> an explanatory notice. Nothing is
 *    offered that cannot succeed.
 */

import { useState, type FormEvent } from 'react'
import { Navigate } from 'react-router-dom'

import { useSession, isFirebaseConfigured } from '@/auth/SessionContext'
import { Alert, Button, Card, Field, TextInput } from '@/components/ui'

type Mode = 'signin' | 'signup'

export default function LoginPage() {
  const {
    status,
    config,
    firebaseProjectIssue,
    signInWithEmail,
    signUp,
    signInWithGoogle,
  } = useSession()

  const [mode, setMode] = useState<Mode>('signin')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  /**
   * Only offer forms that can actually succeed.
   *
   * The server's word is authoritative. When it answers, its provider decides;
   * when it is unreachable, forms are only shown if this build is Firebase-ready
   * (the connection may simply be down, and the attempt will say so).
   */
  const buildFirebase = isFirebaseConfigured()
  const serverSaysFirebase = config?.firebase_enabled ?? false
  const decisionKnown = config !== null
  const canOfferForms = serverSaysFirebase || (buildFirebase && !decisionKnown)

  if (status === 'authenticated') {
    return <Navigate to="/" replace />
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (mode === 'signin') {
        await signInWithEmail(email, password)
      } else {
        await signUp(email, password, name)
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

  const renderSetupNotice = () => (
    <Alert tone="warning">
      This server has no Firebase Authentication provider available to this
      client. No sign-in form can succeed against it. Configure the backend with
      Firebase credentials and build this app with <code>VITE_FIREBASE_*</code>{' '}
      variables pointing at the same Firebase project.
    </Alert>
  )

  const renderProjectIssue = () => {
    if (!firebaseProjectIssue) return null
    if (firebaseProjectIssue === 'unconfigured') {
      return (
        <Alert tone="error">
          This build has no <code>VITE_FIREBASE_*</code> configuration, so it
          cannot obtain an ID token for the Firebase server. Set the Firebase
          build variables and rebuild.
        </Alert>
      )
    }
    return (
      <Alert tone="error">
        This app is built to authenticate against one Firebase project, but the
        server verifies a different one. Sign-in would succeed and then be
        rejected. Rebuild the app with the project the server uses.
      </Alert>
    )
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

          {!canOfferForms ? (
            renderSetupNotice()
          ) : (
            <>
              {renderProjectIssue()}

              <form onSubmit={submit} className="space-y-4">
                {mode === 'signup' && (
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
                    autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    minLength={mode === 'signup' ? 6 : undefined}
                    required
                  />
                </Field>

                <Button type="submit" loading={busy} className="w-full">
                  {mode === 'signup' ? 'Create account' : 'Sign in'}
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
                {mode === 'signup' ? 'Already have an account?' : 'No account yet?'}{' '}
                <button
                  type="button"
                  className="text-accent hover:underline"
                  onClick={() => setMode(mode === 'signup' ? 'signin' : 'signup')}
                >
                  {mode === 'signup' ? 'Sign in' : 'Create one'}
                </button>
              </p>
            </>
          )}
        </Card>
      </div>
    </div>
  )
}
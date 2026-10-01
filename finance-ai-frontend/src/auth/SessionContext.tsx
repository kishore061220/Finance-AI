/**
 * Session state.
 *
 * The token lives in memory, not localStorage. A Firebase ID token in
 * localStorage is readable by any script that runs on the page, so an XSS bug
 * becomes a session theft. Persistence across reloads comes from Firebase's own
 * `onAuthStateChanged`, which re-derives a fresh token from IndexedDB - so the
 * trade is one extra round trip on load in exchange for not leaving a bearer
 * token on disk.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'

import { ApiError, configureAuth, request } from '@/lib/api'
import { firebaseAuth, isFirebaseConfigured } from '@/lib/firebase'
import type { AuthConfig, UserResponse } from '@/types'

export type SessionStatus = 'loading' | 'authenticated' | 'anonymous'

interface SessionState {
  status: SessionStatus
  user: UserResponse | null
  config: AuthConfig | null
  signInWithEmail: (email: string, password: string) => Promise<void>
  signUp: (email: string, password: string, name: string) => Promise<void>
  signInWithGoogle: () => Promise<void>
  /** Development-only sign-in. Calls the backend's dev-token endpoint. */
  signInAsDeveloper: (email: string) => Promise<void>
  signOut: () => Promise<void>
  getToken: () => string | null
}

const SessionContext = createContext<SessionState | null>(null)

/** Storage key for the dev-token session, which is a real backend credential. */
const DEV_TOKEN_KEY = 'finance_ai.dev_token'

export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<SessionStatus>('loading')
  const [user, setUser] = useState<UserResponse | null>(null)
  const [config, setConfig] = useState<AuthConfig | null>(null)
  const tokenRef = useRef<string | null>(null)

  // Exported so the axios interceptor can always reach the current token.
  const getToken = useCallback(() => tokenRef.current, [])
  const signOutLocal = useCallback(() => {
    tokenRef.current = null
    setUser(null)
    setStatus('anonymous')
  }, [])

  useEffect(() => {
    configureAuth(getToken, signOutLocal)
  }, [getToken, signOutLocal])

  /**
   * Load the user profile for a token.
   *
   * A failure here means the token is no longer usable, so the session is
   * dropped rather than left half-authenticated with no user.
   */
  const adoptToken = useCallback(
    async (token: string) => {
      tokenRef.current = token
      try {
        const profile = await request<UserResponse>({ method: 'GET', url: '/api/auth/me' })
        setUser(profile)
        setStatus('authenticated')
      } catch (error) {
        tokenRef.current = null
        setUser(null)
        setStatus('anonymous')
        if (!(error instanceof ApiError)) throw error
      }
    },
    [],
  )

  // Resolve which provider the server is using, then restore any session.
  useEffect(() => {
    let cancelled = false

    void (async () => {
      let resolved: AuthConfig | null = null
      try {
        resolved = await request<AuthConfig>(
          { method: 'GET', url: '/api/auth/config' },
          { skipAuth: true },
        )
      } catch {
        // The server being unreachable must not block the login screen; the
        // sign-in attempt will surface the connection problem with detail.
      }
      if (cancelled) return
      if (resolved) setConfig(resolved)

      // Awaited, not called synchronously: firebaseAuth() now performs a dynamic
      // import, so the provider is only available after the SDK chunk loads.
      const auth = await firebaseAuth()
      if (auth) {
        // Firebase persists the session itself; ask it who is signed in.
        const { onAuthStateChanged } = await import('firebase/auth')
        onAuthStateChanged(auth, async (firebaseUser) => {
          if (cancelled) return
          if (!firebaseUser) {
            signOutLocal()
            return
          }
          await adoptToken(await firebaseUser.getIdToken())
        })
        return
      }

      // No Firebase config: fall back to a stored development token if present.
      const stored = sessionStorage.getItem(DEV_TOKEN_KEY)
      if (stored) {
        await adoptToken(stored)
        return
      }

      setStatus('anonymous')
    })()

    return () => {
      cancelled = true
    }
  }, [adoptToken, signOutLocal])

  const signInWithEmail = useCallback(
    async (email: string, password: string) => {
      const auth = await firebaseAuth()
      if (!auth) {
        throw new Error(
          'Email sign-in requires Firebase configuration. Set VITE_FIREBASE_* variables.',
        )
      }
      const { signInWithEmailAndPassword } = await import('firebase/auth')
      const credential = await signInWithEmailAndPassword(auth, email, password)
      await adoptToken(await credential.user.getIdToken())
    },
    [adoptToken],
  )

  const signUp = useCallback(
    async (email: string, password: string, name: string) => {
      const auth = await firebaseAuth()
      if (!auth) {
        throw new Error(
          'Registration requires Firebase configuration. Set VITE_FIREBASE_* variables.',
        )
      }
      const { createUserWithEmailAndPassword, updateProfile } = await import('firebase/auth')
      const credential = await createUserWithEmailAndPassword(auth, email, password)
      await updateProfile(credential.user, { displayName: name })
      await adoptToken(await credential.user.getIdToken())
    },
    [adoptToken],
  )

  const signInWithGoogle = useCallback(async () => {
    const auth = await firebaseAuth()
    if (!auth) {
      throw new Error('Google sign-in requires Firebase configuration.')
    }
    const { GoogleAuthProvider, signInWithPopup } = await import('firebase/auth')
    const credential = await signInWithPopup(auth, new GoogleAuthProvider())
    await adoptToken(await credential.user.getIdToken())
  }, [adoptToken])

  const signInAsDeveloper = useCallback(
    async (email: string) => {
      const response = await request<{ access_token: string }>(
        {
          method: 'POST',
          url: '/api/auth/dev-token',
          data: { subject: `dev-${email}`, email, name: 'Developer', expires_minutes: 480 },
        },
        { skipAuth: true },
      )
      sessionStorage.setItem(DEV_TOKEN_KEY, response.access_token)
      await adoptToken(response.access_token)
    },
    [adoptToken],
  )

  /**
   * End the session.
   *
   * Order matters here. The server notification runs *before* anything clears
   * the local token, because the interceptor reads the token from memory: sign
   * Firebase out first and the onAuthStateChanged handler clears `tokenRef`, so
   * the logout request would go out unauthenticated and the server-side audit
   * record would never be written. The logout call is best effort and must not
   * prevent the local sign-out, but `signOutLocal` runs unconditionally at the
   * end either way.
   */
  const signOut = useCallback(async () => {
    try {
      await request({ method: 'POST', url: '/api/auth/logout' })
    } catch {
      // A failed acknowledgement must not block the local sign-out.
    }

    const auth = await firebaseAuth()
    if (auth) {
      const { signOut: firebaseSignOut } = await import('firebase/auth')
      await firebaseSignOut(auth).catch(() => {
        // Already signed out, or the SDK failed to load. Local state still clears.
      })
    }
    sessionStorage.removeItem(DEV_TOKEN_KEY)
    signOutLocal()
  }, [signOutLocal])

  const value = useMemo<SessionState>(
    () => ({
      status,
      user,
      config,
      signInWithEmail,
      signUp,
      signInWithGoogle,
      signInAsDeveloper,
      signOut,
      getToken,
    }),
    [
      status,
      user,
      config,
      signInWithEmail,
      signUp,
      signInWithGoogle,
      signInAsDeveloper,
      signOut,
      getToken,
    ],
  )

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useSession(): SessionState {
  const context = useContext(SessionContext)
  if (!context) {
    throw new Error('useSession must be used inside a SessionProvider.')
  }
  return context
}

export { isFirebaseConfigured }

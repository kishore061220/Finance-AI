/**
 * Session state.
 *
 * The token lives in memory, not localStorage. A Firebase ID token in
 * localStorage is readable by any script that runs on the page, so an XSS bug
 * becomes a session theft. Persistence across reloads comes from Firebase's own
 * `onIdTokenChanged`, which re-derives a fresh token from IndexedDB - so the
 * trade is one extra round trip on load in exchange for not leaving a bearer
 * token on disk.
 *
 * Token refresh is Firebase-driven: the SDK renews the ID token before it
 * expires and this provider watches `onIdTokenChanged` (which fires for both
 * sign-in/sign-out and token refresh), re-adopting the current token so every
 * request carries a live credential. There is no development-token fallback:
 * this client authenticates only against Firebase.
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

import { configureAuth, request } from '@/lib/api'
import { describeAuthFailure, firebaseErrorCode } from '@/lib/authErrors'
import {
  firebaseAuth,
  firebaseProjectId,
  isFirebaseConfigured,
} from '@/lib/firebase'
import type { AuthConfig, UserResponse } from '@/types'

export type SessionStatus = 'loading' | 'authenticated' | 'anonymous'

/**
 * Why a Firebase build cannot show working sign-in forms even though the server
 * says it is on Firebase.
 *
 * - `null`            – nothing wrong, or the server is not on Firebase.
 * - `'unconfigured'`  – the server verifies Firebase tokens but this build has
 *                       no `VITE_FIREBASE_*` variables, so it cannot mint one.
 * - `'mismatch'`      – this build points at a different Firebase project than
 *                       the backend verifies. Sign-in would succeed and then be
 *                       rejected on the first API call.
 */
export type FirebaseProjectIssue = 'unconfigured' | 'mismatch' | null

interface SessionState {
  status: SessionStatus
  user: UserResponse | null
  config: AuthConfig | null
  firebaseProjectIssue: FirebaseProjectIssue
  /**
   * A failure from an authentication step that runs outside a form submit -
   * currently a redirect-based Google sign-in completing on page load. Form
   * submissions surface their own errors, so this is separate.
   */
  authError: string | null
  signInWithEmail: (email: string, password: string) => Promise<void>
  signUp: (email: string, password: string, name: string) => Promise<void>
  signInWithGoogle: () => Promise<void>
  sendPasswordReset: (email: string) => Promise<void>
  signOut: () => Promise<void>
  getToken: () => string | null
}

const SessionContext = createContext<SessionState | null>(null)

export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<SessionStatus>('loading')
  const [user, setUser] = useState<UserResponse | null>(null)
  const [config, setConfig] = useState<AuthConfig | null>(null)
  const [authError, setAuthError] = useState<string | null>(null)
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
   * dropped rather than left half-authenticated with no user. The error is
   * re-thrown, not swallowed: an interactive sign-in needs to tell the user the
   * API refused the session (wrong project, missing service-account keys, the
   * API being down) instead of silently bouncing them back to the login form.
   * The background listener wraps its call in a try/catch so a refresh failure
   * cannot become an unhandled rejection.
   */
  const adoptToken = useCallback(
    async (token: string) => {
      tokenRef.current = token
      try {
        const profile = await request<UserResponse>({ method: 'GET', url: '/api/auth/me' })
        setUser(profile)
        setStatus('authenticated')
        setAuthError(null)
      } catch (error) {
        tokenRef.current = null
        setUser(null)
        setStatus('anonymous')
        throw error
      }
    },
    [],
  )

  /**
   * Resolve which provider the server is using, then restore any session.
   *
   * `onIdTokenChanged` rather than `onAuthStateChanged`: the former also fires
   * when Firebase silently refreshes the ID token, which is what keeps a session
   * alive past the one-hour lifetime without a 401 in between.
   */
  useEffect(() => {
    let cancelled = false
    let unsubscribeFirebase: (() => void) | null = null

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

      const auth = await firebaseAuth()
      if (auth) {
        // Firebase persists the session itself; ask it who is signed in. The
        // listener is held so unmounting never leaves a dead observer behind.
        const { getRedirectResult, onIdTokenChanged } = await import('firebase/auth')
        if (cancelled) return

        // Complete a redirect-based Google sign-in, if this page load is the
        // return leg of one. Google sign-in normally uses a popup, but falls
        // back to a redirect when popups are blocked; without this call the
        // credential from that fallback would be discarded and the user would
        // land back on the login page.
        try {
          const result = await getRedirectResult(auth)
          if (cancelled) return
          if (result?.user) {
            await adoptToken(await result.user.getIdToken())
          }
        } catch (error) {
          if (!cancelled) setAuthError(describeAuthFailure(error))
        }
        if (cancelled) return

        unsubscribeFirebase = onIdTokenChanged(auth, async (firebaseUser) => {
          if (cancelled) return
          if (!firebaseUser) {
            signOutLocal()
            return
          }
          try {
            await adoptToken(await firebaseUser.getIdToken())
          } catch {
            // adoptToken has already cleared the session; a background refresh
            // failure must not surface as an unhandled rejection.
          }
        })
        return
      }

      // No Firebase configuration in this build and no other provider: the
      // server decides what the login screen may offer.
      setStatus('anonymous')
    })()

    return () => {
      cancelled = true
      unsubscribeFirebase?.()
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
    const { GoogleAuthProvider, signInWithPopup, signInWithRedirect } = await import(
      'firebase/auth'
    )
    const provider = new GoogleAuthProvider()
    try {
      const credential = await signInWithPopup(auth, provider)
      await adoptToken(await credential.user.getIdToken())
    } catch (error) {
      /**
       * Popup blocked (or unsupported) is the one failure that is worth
       * retrying another way. The redirect flow takes over the page and its
       * result is picked up by `getRedirectResult` on the next load. Every
       * other error - including the user closing the popup - is re-thrown so
       * the login screen can explain it.
       */
      const code = firebaseErrorCode(error)
      if (code === 'auth/popup-blocked' || code === 'auth/operation-not-supported-in-this-environment') {
        await signInWithRedirect(auth, provider)
        return
      }
      throw error
    }
  }, [adoptToken])

  /**
   * Send a password-reset email.
   *
   * The server never tells us whether the address has an account, and neither
   * should this. When Firebase reports `auth/user-not-found` the call is treated
   * as a success so the response cannot be used to enumerate registered emails;
   * only genuine failures (a malformed address, the network) are re-thrown.
   */
  const sendPasswordReset = useCallback(async (email: string) => {
    const auth = await firebaseAuth()
    if (!auth) {
      throw new Error('Password reset requires Firebase configuration.')
    }
    const { sendPasswordResetEmail } = await import('firebase/auth')
    try {
      await sendPasswordResetEmail(auth, email)
    } catch (error) {
      if (firebaseErrorCode(error) === 'auth/user-not-found') return
      throw error
    }
  }, [])

  /**
   * End the session.
   *
   * Order matters here. The server notification runs *before* anything clears
   * the local token, because the interceptor reads the token from memory: sign
   * Firebase out first and the onIdTokenChanged handler clears `tokenRef`, so
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
    signOutLocal()
  }, [signOutLocal])

  /**
   * Detect a build that cannot authenticate against this server even though the
   * server believes it is on Firebase.
   */
  const firebaseProjectIssue = useMemo<FirebaseProjectIssue>(() => {
    if (!config?.firebase_enabled) return null
    const buildProjectId = firebaseProjectId()
    if (!buildProjectId) return 'unconfigured'
    if (config.project_id && buildProjectId !== config.project_id) return 'mismatch'
    return null
  }, [config])

  const value = useMemo<SessionState>(
    () => ({
      status,
      user,
      config,
      firebaseProjectIssue,
      authError,
      signInWithEmail,
      signUp,
      signInWithGoogle,
      sendPasswordReset,
      signOut,
      getToken,
    }),
    [
      status,
      user,
      config,
      firebaseProjectIssue,
      authError,
      signInWithEmail,
      signUp,
      signInWithGoogle,
      sendPasswordReset,
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
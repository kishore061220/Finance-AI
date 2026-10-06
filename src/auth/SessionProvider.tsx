/**
 * Session state for the app.
 *
 * Provider selection mirrors the backend, not the device. `/api/auth/config`
 * reports which provider the server is using, and the login screen offers only
 * forms that can actually succeed against it - a build with Firebase
 * configuration talking to a server without it would otherwise present email and
 * Google buttons that always fail.
 *
 * Token handling:
 *  - Firebase manages its own credential and persists it in the platform's secure
 *    storage. The ID token is held in memory and attached per request.
 *  - The development token is persisted in AsyncStorage. It is a real bearer
 *    credential, but it only ever exists against a backend with Firebase off and
 *    `ALLOW_DEV_AUTH=true`, which cannot be true in production.
 *
 * Neither path ever sends a user id: the backend derives ownership from the
 * token on every request.
 */

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';

import { ApiError, configureAuth, request, setToken } from '../services/api';
import { authApi } from '../services/endpoints';
import { firebaseAuth, isFirebaseAvailable } from '../services/firebase';
import { DEV_TOKEN_KEY } from '../config';
import type { AuthConfig, DevTokenResponse, UserResponse } from '../types';

export type SessionStatus = 'loading' | 'authenticated' | 'anonymous';

export interface SessionState {
  status: SessionStatus;
  user: UserResponse | null;
  config: AuthConfig | null;
  signInWithEmail: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string, name: string) => Promise<void>;
  signInAsDeveloper: (email: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const SessionContext = createContext<SessionState | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<SessionStatus>('loading');
  const [user, setUser] = useState<UserResponse | null>(null);
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const tokenRef = useRef<string | null>(null);

  /** Drop the local session. Registered with the API client so a 401 anywhere clears it. */
  const signOutLocal = useCallback(() => {
    tokenRef.current = null;
    setToken(null);
    setUser(null);
    setStatus('anonymous');
  }, []);

  useEffect(() => {
    configureAuth({ getToken: () => tokenRef.current, onUnauthorized: signOutLocal });
  }, [signOutLocal]);

  /**
   * Validate a token and adopt it.
   *
   * A failure means the token is unusable, so the session is dropped rather than
   * left half-authenticated with a null user and screens that 401 on mount. A
   * non-HTTP failure (a dropped connection) is surfaced instead, because the
   * token may well still be valid once the network returns.
   */
  const adoptToken = useCallback(async (token: string) => {
    tokenRef.current = token;
    setToken(token);
    try {
      const profile = await authApi.me();
      setUser(profile);
      setStatus('authenticated');
    } catch (error) {
      if (error instanceof ApiError && error.isUnauthorized) {
        signOutLocal();
        return;
      }
      // Anything else: drop the token too, because we cannot prove it works, but
      // do not pretend the server rejected it.
      signOutLocal();
      throw error;
    }
  }, [signOutLocal]);

  // Resolve the provider, then restore whatever session exists.
  useEffect(() => {
    let cancelled = false;
    // The Firebase auth listener outlives the async IIFE below, so its
    // unsubscribe function is held here and invoked on cleanup. Returning it
    // from inside the IIFE would be discarded with the IIFE's own promise and the
    // listener would keep firing after unmount.
    let unsubscribeFirebase: (() => void) | null = null;

    void (async () => {
      let resolved: AuthConfig | null = null;
      try {
        resolved = await authApi.config();
      } catch {
        // Unreachable config endpoint must not block the login screen; the
        // sign-in attempt will report the connection problem with detail.
      }
      if (cancelled) return;
      if (resolved) setConfig(resolved);

      const auth = await firebaseAuth();
      if (auth) {
        // `require` rather than `import()`: Metro only bundles a literal
        // specifier, and Jest cannot execute a dynamic import without an opt-in VM
        // flag. `firebaseAuth()` returning non-null already proves the module
        // loaded, so this cannot throw here.
        const { onAuthStateChanged } = require('@react-native-firebase/auth') as typeof import('@react-native-firebase/auth');
        if (cancelled) return;
        unsubscribeFirebase = onAuthStateChanged(auth, async (firebaseUser) => {
          if (cancelled) return;
          if (!firebaseUser) {
            signOutLocal();
            return;
          }
          try {
            await adoptToken(await firebaseUser.getIdToken());
          } catch {
            // adoptToken already cleared the session; a background refresh
            // failure should not surface as an unhandled rejection.
          }
        });
        return;
      }

      try {
        const stored = await AsyncStorage.getItem(DEV_TOKEN_KEY);
        if (cancelled) return;
        if (stored) {
          await adoptToken(stored);
          return;
        }
      } catch {
        // Unreadable storage is not fatal: the user just signs in again.
      }

      if (!cancelled) setStatus('anonymous');
    })();

    return () => {
      cancelled = true;
      unsubscribeFirebase?.();
    };
  }, [adoptToken, signOutLocal]);

  const signInWithEmail = useCallback(
    async (email: string, password: string) => {
      const auth = await firebaseAuth();
      if (!auth) {
        throw new Error(
          'Email sign-in needs Firebase. This build has no google-services.json; see the README.',
        );
      }
      const { signInWithEmailAndPassword } = require('@react-native-firebase/auth') as typeof import('@react-native-firebase/auth');
      const credential = await signInWithEmailAndPassword(auth, email, password);
      await adoptToken(await credential.user.getIdToken());
    },
    [adoptToken],
  );

  const signUp = useCallback(
    async (email: string, password: string, name: string) => {
      const auth = await firebaseAuth();
      if (!auth) {
        throw new Error(
          'Registration needs Firebase. This build has no google-services.json; see the README.',
        );
      }
      const { createUserWithEmailAndPassword, updateProfile } = require('@react-native-firebase/auth') as typeof import('@react-native-firebase/auth');
      const credential = await createUserWithEmailAndPassword(auth, email, password);
      await updateProfile(credential.user, { displayName: name });
      await adoptToken(await credential.user.getIdToken());
    },
    [adoptToken],
  );

  const signInAsDeveloper = useCallback(
    async (email: string) => {
      const response = await request<DevTokenResponse>(
        {
          method: 'POST',
          url: '/api/auth/dev-token',
          data: {
            subject: `dev-${email}`,
            email,
            name: 'Developer',
            expires_minutes: 480,
          },
        },
        { skipAuth: true },
      );
      await AsyncStorage.setItem(DEV_TOKEN_KEY, response.access_token);
      await adoptToken(response.access_token);
    },
    [adoptToken],
  );

  /**
   * End the session.
   *
   * The server notification runs first: the request interceptor reads the token
   * from memory, so signing out of Firebase first would clear `tokenRef` and send
   * the logout unauthenticated, losing the server-side audit record. The
   * acknowledgement is best effort and must not block the local sign-out, which
   * happens unconditionally at the end.
   */
  const signOut = useCallback(async () => {
    try {
      await authApi.logout();
    } catch {
      // A failed acknowledgement must not trap the user in a signed-in shell.
    }

    const auth = await firebaseAuth();
    if (auth) {
      const { signOut: firebaseSignOut } = require('@react-native-firebase/auth') as typeof import('@react-native-firebase/auth');
      await firebaseSignOut(auth).catch(() => {
        // Already signed out, or the SDK is unavailable. Local state still clears.
      });
    }

    await AsyncStorage.removeItem(DEV_TOKEN_KEY).catch(() => {
      // Non-fatal: the token is already unusable in memory, and a stale entry is
      // rejected on next launch.
    });
    signOutLocal();
  }, [signOutLocal]);

  const value = useMemo<SessionState>(
    () => ({
      status,
      user,
      config,
      signInWithEmail,
      signUp,
      signInAsDeveloper,
      signOut,
    }),
    [status, user, config, signInWithEmail, signUp, signInAsDeveloper, signOut],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionState {
  const context = useContext(SessionContext);
  if (!context) {
    throw new Error('useSession must be used inside a SessionProvider.');
  }
  return context;
}

/**
 * True when this build can actually use Firebase.
 *
 * A convenience for screens that need to hide a control rather than show one
 * that will fail - see `services/firebase.ts` for how this is detected.
 */
export { isFirebaseAvailable };

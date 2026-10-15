/**
 * Human-readable explanations for authentication failures.
 *
 * The Firebase SDK throws `FirebaseError` values whose `message` is a
 * developer-facing string such as `Firebase: Error (auth/invalid-credential).`.
 * Rendering that verbatim tells the user nothing they can act on, so the codes
 * are mapped here instead.
 *
 * Two rules shape the wording:
 *
 * 1. **No account enumeration.** `auth/invalid-credential` (and the legacy
 *    `auth/user-not-found` / `auth/wrong-password` it replaced) deliberately
 *    collapse "no such user" and "wrong password" into one response. The copy
 *    keeps that collapse so it cannot be used to probe which emails exist.
 *    The forgot-password path treats a missing account as success for the same
 *    reason - see `SessionContext.sendPasswordReset`.
 * 2. **Actionable, not alarming.** Each message names the likely cause and the
 *    next step (use Google, reset the password, allow popups, fix the console).
 */

import { ApiError } from '@/lib/api'

/** The `auth/...` code on a Firebase error, or null for anything else. */
export function firebaseErrorCode(error: unknown): string | null {
  if (error && typeof error === 'object' && 'code' in error) {
    const code = (error as { code?: unknown }).code
    if (typeof code === 'string' && code.startsWith('auth/')) {
      return code
    }
  }
  return null
}

const INVALID_CREDENTIALS =
  'The email or password is incorrect. If this account was created with Google, ' +
  'use "Continue with Google" instead. If you have forgotten the password, use ' +
  '"Forgot password?" to reset it.'

const MESSAGES: Record<string, string> = {
  'auth/invalid-credential': INVALID_CREDENTIALS,
  'auth/user-not-found': INVALID_CREDENTIALS,
  'auth/wrong-password': INVALID_CREDENTIALS,
  'auth/missing-password': 'Enter your password.',
  'auth/invalid-email': 'Enter a valid email address.',
  'auth/user-disabled': 'This account has been disabled. Contact support.',
  'auth/too-many-requests':
    'Too many attempts. Wait a few minutes and try again, or reset your password.',
  'auth/network-request-failed': 'Network error. Check your connection and try again.',
  'auth/email-already-in-use':
    'An account already exists for this email. Sign in instead, or reset your password.',
  'auth/weak-password': 'Choose a stronger password (at least 6 characters).',
  'auth/operation-not-allowed':
    'This sign-in method is not enabled for the Firebase project. Enable it under ' +
    'Authentication > Sign-in method in the Firebase console.',
  'auth/popup-closed-by-user': 'Google sign-in was closed before it finished. Please try again.',
  'auth/cancelled-popup-request': 'Google sign-in was cancelled. Please try again.',
  'auth/popup-blocked':
    'The sign-in popup was blocked by the browser. Allow popups for this site and try again.',
  'auth/account-exists-with-different-credential':
    'An account already exists for this email using a different sign-in method. ' +
    'Sign in with the method you originally used, or reset the password.',
  'auth/unauthorized-domain':
    'This domain is not authorised for Firebase sign-in. Add it under ' +
    'Authentication > Settings > Authorized domains in the Firebase console.',
  'auth/requires-recent-login': 'Please sign in again to continue.',
}

/**
 * Describe a Firebase error, or null when the value is not one.
 *
 * Returning null (rather than a generic string) lets callers fall through to
 * handling non-Firebase failures - most importantly an `ApiError` raised after
 * Firebase itself accepted the sign-in.
 */
export function describeFirebaseError(error: unknown): string | null {
  const code = firebaseErrorCode(error)
  if (!code) return null
  return MESSAGES[code] ?? 'Sign-in failed. Check your details and try again.'
}

/**
 * One message for any failure in an authentication action.
 *
 * Covers three sources in the order they occur: Firebase rejecting the
 * credentials, the API rejecting the resulting token, and the network being
 * absent. The API case matters because a Firebase sign-in can succeed and then
 * be refused by the backend (wrong project, missing service-account keys); the
 * user used to be dropped back on the login screen with no explanation.
 */
export function describeAuthFailure(error: unknown): string {
  const firebase = describeFirebaseError(error)
  if (firebase) return firebase

  if (error instanceof ApiError) {
    if (error.isNetworkError) return error.detail
    if (error.status === 401 || error.status === 403) {
      return (
        'Firebase accepted this sign-in, but the API rejected the session. Make ' +
        'sure the app and the server use the same Firebase project and that the ' +
        'backend has valid Firebase service-account credentials.'
      )
    }
    return error.detail
  }

  if (error instanceof Error && error.message) return error.message
  return 'Could not complete sign-in. Please try again.'
}

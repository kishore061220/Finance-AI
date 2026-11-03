/**
 * Native Google Sign-In, isolated.
 *
 * The native module is loaded lazily with `require` behind a try/catch for the
 * same reasons as `services/firebase.ts`: Metro only bundles a literal
 * specifier, Jest can intercept the module, and a build without the native
 * binding degrades to a clear error instead of crashing at import time.
 *
 * Only the Google `idToken` leaves this module. It is handed to Firebase to
 * build an auth credential and is never stored, logged, or attached to an API
 * request.
 */

// Type-only import, erased at compile time so the native module is not loaded
// eagerly.
import type { SignInResponse } from '@react-native-google-signin/google-signin';

import { GOOGLE_WEB_CLIENT_ID } from '../config';

type GoogleSigninModule = typeof import('@react-native-google-signin/google-signin');

/** Thrown when the user closes the Google account chooser. Callers stay quiet. */
export class GoogleSignInCancelled extends Error {
  constructor() {
    super('Google sign-in was cancelled.');
    this.name = 'GoogleSignInCancelled';
    // Restores the prototype chain after transpilation to ES5-era output.
    Object.setPrototypeOf(this, GoogleSignInCancelled.prototype);
  }
}

let configured = false;

function loadGoogleSignin(): GoogleSigninModule | null {
  try {
    return require('@react-native-google-signin/google-signin') as GoogleSigninModule;
  } catch {
    return null;
  }
}

/** Whether this build has the public Web client id Google Sign-In requires. */
export function isGoogleSignInConfigured(): boolean {
  return GOOGLE_WEB_CLIENT_ID !== null;
}

function configureOnce(module: GoogleSigninModule): void {
  if (configured) return;
  module.GoogleSignin.configure({
    webClientId: GOOGLE_WEB_CLIENT_ID ?? undefined,
    scopes: ['email', 'profile'],
    // Deliberately off: the app does not need a server refresh token, and
    // leaving it off means no authorization code is requested or stored.
    offlineAccess: false,
  });
  configured = true;
}

function codeOf(error: unknown): string | null {
  if (typeof error !== 'object' || error === null) return null;
  const code = (error as { code?: unknown }).code;
  return typeof code === 'string' ? code : null;
}

function mapGoogleError(error: unknown, module: GoogleSigninModule): Error {
  const code = codeOf(error);
  if (code !== null) {
    if (code === module.statusCodes.SIGN_IN_CANCELLED) {
      return new GoogleSignInCancelled();
    }
    if (code === module.statusCodes.IN_PROGRESS) {
      return new Error('Google sign-in is already in progress. Please wait.');
    }
    if (code === module.statusCodes.PLAY_SERVICES_NOT_AVAILABLE) {
      return new Error(
        'Google Play Services is unavailable or out of date on this device. Update it and try again.',
      );
    }
    // Android maps a misconfigured OAuth client (wrong package/SHA-1) to
    // DEVELOPER_ERROR, which arrives as the numeric string "10".
    if (code === '10' || code === 'DEVELOPER_ERROR') {
      return new Error(
        'Google sign-in is misconfigured for this build (check SHA fingerprints).',
      );
    }
  }

  return new Error(
    error instanceof Error && error.message
      ? error.message
      : 'Google sign-in failed. Please try again.',
  );
}

/**
 * Run the native Google flow and return its `idToken`.
 *
 * A cancelled flow is a normal outcome, not a failure: it is reported as a
 * typed `GoogleSignInCancelled` so the UI can clear its busy state silently.
 */
export async function getGoogleIdToken(): Promise<string> {
  if (GOOGLE_WEB_CLIENT_ID === null) {
    throw new Error('Google sign-in is not configured.');
  }

  const module = loadGoogleSignin();
  if (!module) {
    throw new Error('Google sign-in is not available in this build.');
  }

  configureOnce(module);

  let response: SignInResponse;
  try {
    await module.GoogleSignin.hasPlayServices({ showPlayServicesUpdateDialog: true });
    response = await module.GoogleSignin.signIn();
  } catch (error) {
    throw mapGoogleError(error, module);
  }

  if (response.type === 'cancelled') {
    throw new GoogleSignInCancelled();
  }

  const idToken = response.data.idToken;
  if (!idToken) {
    throw new Error(
      'Google sign-in did not return an ID token. Check that the Web client id belongs to Firebase project finance-fd3f3, then try again.',
    );
  }

  return idToken;
}

/** Forget the Google session. Best effort and never throws. */
export async function googleSignOut(): Promise<void> {
  const module = loadGoogleSignin();
  if (!module) return;
  try {
    await module.GoogleSignin.signOut();
  } catch {
    // Signing out locally must never be blocked by Google teardown.
  }
}

/**
 * Test hook: forget that `configure()` already ran after a module reset.
 *
 * Not used by application code; it exists so a test can exercise configuration
 * more than once in one Jest process.
 */
export function resetGoogleSignInForTests(): void {
  configured = false;
}

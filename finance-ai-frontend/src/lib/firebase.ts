/**
 * Firebase wiring, lazily loaded.
 *
 * Kept in its own module so the rest of the app never imports the SDK at module
 * scope. The functions here are async because `firebase/auth` is behind a dynamic
 * import: it is ~120kB gzipped, and on a development server using dev-token auth
 * it is never needed at all. A static import would put it in the entry chunk
 * that every visitor downloads before the login form appears.
 *
 * Configuration comes from `VITE_FIREBASE_*` build-time variables. If they are
 * missing, `isFirebaseConfigured()` is false and the app falls back to the
 * development token endpoint - which the backend itself only enables when
 * Firebase is off and `ALLOW_DEV_AUTH=true`, so the fallback cannot become a
 * production authentication path.
 */

export interface FirebaseSettings {
  apiKey: string
  authDomain: string
  projectId: string
  storageBucket: string
  messagingSenderId: string
  appId: string
}

function readSettings(): FirebaseSettings | null {
  const env = import.meta.env ?? {}
  const settings: FirebaseSettings = {
    apiKey: env.VITE_FIREBASE_API_KEY as string,
    authDomain: env.VITE_FIREBASE_AUTH_DOMAIN as string,
    projectId: env.VITE_FIREBASE_PROJECT_ID as string,
    storageBucket: env.VITE_FIREBASE_STORAGE_BUCKET as string,
    messagingSenderId: env.VITE_FIREBASE_MESSAGING_SENDER_ID as string,
    appId: env.VITE_FIREBASE_APP_ID as string,
  }

  const missing = Object.entries(settings)
    .filter(([, value]) => !value)
    .map(([key]) => key)

  return missing.length === 0 ? settings : null
}

/**
 * Synchronous check, safe to call during render.
 *
 * Exists so a screen can decide which forms to show without awaiting an import.
 */
export function isFirebaseConfigured(): boolean {
  return readSettings() !== null
}

/** Names of the variables still missing, for a clearer setup error. */
export function missingFirebaseVars(): string[] {
  const env = import.meta.env ?? {}
  const names = {
    VITE_FIREBASE_API_KEY: env.VITE_FIREBASE_API_KEY,
    VITE_FIREBASE_AUTH_DOMAIN: env.VITE_FIREBASE_AUTH_DOMAIN,
    VITE_FIREBASE_PROJECT_ID: env.VITE_FIREBASE_PROJECT_ID,
    VITE_FIREBASE_STORAGE_BUCKET: env.VITE_FIREBASE_STORAGE_BUCKET,
    VITE_FIREBASE_MESSAGING_SENDER_ID: env.VITE_FIREBASE_MESSAGING_SENDER_ID,
    VITE_FIREBASE_APP_ID: env.VITE_FIREBASE_APP_ID,
  }
  return Object.entries(names)
    .filter(([, value]) => !value)
    .map(([key]) => key)
}

/**
 * The `Auth` instance, or null when Firebase is not configured.
 *
 * Imported as a type-only dependency. A value import here would drag the whole
 * SDK into the entry chunk and defeat the lazy loading this module exists for.
 */
export type FirebaseAuth = import('firebase/auth').Auth

let cached: FirebaseAuth | null = null
let pending: Promise<FirebaseAuth | null> | null = null

/**
 * Resolve the Firebase `Auth` instance, loading the SDK on first use.
 *
 * The in-flight promise is cached alongside the result so concurrent callers
 * during start-up share one import rather than each triggering their own.
 */
export async function firebaseAuth(): Promise<FirebaseAuth | null> {
  if (!isFirebaseConfigured()) {
    return null
  }
  if (cached) return cached
  if (pending) return pending

  pending = (async () => {
    const settings = readSettings() as FirebaseSettings
    const [{ getApp, getApps, initializeApp }, { getAuth }] = await Promise.all([
      import('firebase/app'),
      import('firebase/auth'),
    ])
    const app = getApps().length > 0 ? getApp() : initializeApp(settings)
    cached = getAuth(app)
    return cached
  })()

  try {
    return await pending
  } catch (cause) {
    // A failed import must not leave a rejected promise cached forever.
    pending = null
    throw cause
  }
}

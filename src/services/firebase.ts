/**
 * Firebase access, isolated.
 *
 * Every native Firebase module throws when
 * `android/app/google-services.json` is absent. That file is per-project and
 * per-app credentials, so it is not committed, and a build without it is the
 * normal state of a fresh clone.
 *
 * So the modules are loaded lazily and behind a guard. Firebase is the only
 * authentication path: a build with no `google-services.json` cannot sign in,
 * and the login screen says so instead of offering a form that cannot succeed.
 * The backend independently refuses to mint development tokens whenever Firebase
 * is configured, so there is no second authentication path to fall back to.
 *
 * The loads use `require` rather than `import()`. Two reasons: Metro only bundles
 * a module when the specifier is a string literal, which a computed dynamic
 * import is not, and Jest runs `import()` through a VM hook that is off by
 * default - so a dynamic import would make these modules untestable.
 */

// Type-only imports, erased at compile time so they cost nothing at runtime.
import type { FirebaseAuthTypes } from '@react-native-firebase/auth';
import type { FirebaseApp } from '@react-native-firebase/app';

/** The Firebase app module, or null when it cannot be loaded. */
type FirebaseModule = typeof import('@react-native-firebase/app');
type AuthModule = typeof import('@react-native-firebase/auth');

let cachedAppModule: FirebaseModule | null = null;
let cachedAuth: FirebaseAuthTypes.Module | null = null;
let availability: boolean | null = null;

/**
 * Whether Firebase can be initialised on this device.
 *
 * Detected by attempting the native module load once. Synchronous enough to use
 * in a render, and cached so the probe runs only a single time.
 */
export function isFirebaseAvailable(): boolean {
  if (availability !== null) return availability;
  try {
    // A missing google-services.json makes loading the native module throw.
    require('@react-native-firebase/app');
    availability = true;
  } catch {
    availability = false;
  }
  return availability;
}

function loadAppModule(): FirebaseModule | null {
  if (cachedAppModule) return cachedAppModule;
  try {
    cachedAppModule = require('@react-native-firebase/app') as FirebaseModule;
    return cachedAppModule;
  } catch {
    availability = false;
    return null;
  }
}

/**
 * The Firebase `Auth` instance, or null when Firebase is unavailable.
 *
 * Resolves to null rather than throwing: every caller treats Firebase as
 * optional, and a rejected promise here would surface as a blank login screen
 * with no explanation.
 */
export async function firebaseAuth(): Promise<FirebaseAuthTypes.Module | null> {
  if (!isFirebaseAvailable()) return null;
  if (cachedAuth) return cachedAuth;

  const appModule = loadAppModule();
  if (!appModule) return null;

  try {
    const authModule = require('@react-native-firebase/auth') as AuthModule;
    // The first entry is this app's own `FirebaseApp`. There is no `defaultApp()`
    // fallback on purpose: without a configured project there is no app to
    // authenticate against, and guessing one would produce a module that loads and
    // then fails on its first call.
    const app: FirebaseApp | undefined = appModule.default.apps[0];
    if (!app) {
      availability = false;
      return null;
    }
    cachedAuth = authModule.default.auth(app);
    return cachedAuth;
  } catch {
    // A failed load leaves the app unable to sign in, which the login screen
    // reports; there is no fallback provider.
    availability = false;
    return null;
  }
}

/**
 * Resets the cached lookup.
 *
 * Only for tests, which need to exercise both the present and absent branches
 * within one Jest process.
 */
export function resetFirebaseCache(): void {
  cachedAppModule = null;
  cachedAuth = null;
  availability = null;
}

/**
 * The Firebase project id this build was configured with, or null.
 *
 * Read from the app's own options, which come from `google-services.json`. The
 * server reports the project it verifies tokens for, so the two can be compared
 * before a sign-in succeeds and then fails on the first API call.
 */
export function firebaseProjectId(): string | null {
  const appModule = loadAppModule();
  const app: FirebaseApp | undefined = appModule?.default.apps[0];
  return app?.options?.projectId ?? null;
}

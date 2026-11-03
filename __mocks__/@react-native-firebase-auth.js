/**
 * Firebase auth module mock.
 *
 * Holds an in-memory user so `onIdTokenChanged` (and the older
 * `onAuthStateChanged`) and `getIdToken` behave like a real session.
 * `signInWithEmailAndPassword` and `createUserWithEmailAndPassword` reject the
 * way Firebase does for a wrong password or an existing account, so a test can
 * assert the app surfaces the SDK's own message instead of a generic one.
 */

const state = {
  user: null,
  observers: [],
  credentialError: null,
  credentialUser: { email: 'google@example.com', emailVerified: true },
};

/**
 * The modular Google provider. `credential` only packages the Google idToken in
 * the shape Firebase's `signInWithCredential` expects; it does not verify it.
 */
const GoogleAuthProvider = {
  PROVIDER_ID: 'google.com',
  credential: jest.fn((token, secret) => ({ providerId: 'google.com', token, secret })),
};

function emit() {
  for (const observer of state.observers) observer(state.user);
}

function makeUser(overrides = {}) {
  return {
    uid: 'uid-1',
    email: 'dev@example.com',
    emailVerified: false,
    displayName: 'Developer',
    phoneNumber: null,
    getIdToken: jest.fn(async () => 'mock-id-token'),
    ...overrides,
  };
}

const auth = {
  get currentUser() {
    return state.user;
  },

  onAuthStateChanged(observer, error) {
    state.observers.push(observer);
    // Firebase fires immediately with the current user, and a test must observe
    // that without needing to trigger anything itself.
    Promise.resolve().then(() => (observer ? observer(state.user) : error?.(state.error)));
    return () => {
      state.observers = state.observers.filter((entry) => entry !== observer);
    };
  },

  onIdTokenChanged(observer) {
    state.observers.push(observer);
    Promise.resolve().then(() => observer(state.user));
    return () => {
      state.observers = state.observers.filter((entry) => entry !== observer);
    };
  },

  signOut: jest.fn(async () => {
    state.user = null;
    emit();
  }),

  signInWithEmailAndPassword: jest.fn(async (email) => {
    if (email === 'wrong@example.com') {
      const error = new Error('The password is invalid or the user does not exist.');
      error.code = 'auth/wrong-password';
      throw error;
    }
    state.user = makeUser({ email });
    emit();
    return { user: state.user };
  }),

  createUserWithEmailAndPassword: jest.fn(async (email) => {
    if (email === 'exists@example.com') {
      const error = new Error('The email address is already in use by another account.');
      error.code = 'auth/email-already-in-use';
      throw error;
    }
    state.user = makeUser({ email });
    emit();
    return { user: state.user };
  }),

  updateProfile: jest.fn(async (user, profile) => {
    state.user = { ...user, ...profile };
    return state.user;
  }),

  /**
   * The modular Google sign-in. It sets the same in-memory user and notifies
   * observers exactly like the email mocks, so the session provider's
   * `onIdTokenChanged` path runs unchanged.
   */
  signInWithCredential: jest.fn(async (_authInstance, _credential) => {
    if (state.credentialError) throw state.credentialError;
    state.user = makeUser(state.credentialUser);
    emit();
    return { user: state.user };
  }),

  getIdToken: jest.fn(async () => 'mock-id-token'),
};

/**
 * The modular `onAuthStateChanged(auth, observer, error)` form.
 *
 * Distinct from the namespaced `auth.onAuthStateChanged(observer)`, because the
 * argument positions differ - the instance comes first in the modular form.
 */
function onAuthStateChanged(_authInstance, observer, error) {
  return auth.onAuthStateChanged(observer, error);
}

/**
 * The modular `onIdTokenChanged(auth, observer)` form.
 *
 * The session provider subscribes to this rather than `onAuthStateChanged`,
 * because it also fires when Firebase silently renews the ID token.
 */
function onIdTokenChanged(_authInstance, observer) {
  return auth.onIdTokenChanged(observer);
}

/**
 * Put the module into a signed-in or signed-out state and notify observers,
 * which is what a `signInWithCredential` call does on a real device.
 */
function __setFirebaseUser(user) {
  state.user = user ? makeUser(user) : null;
  emit();
}

function __setGoogleSignInCredentialError(error) {
  state.credentialError = error;
}

function __setGoogleSignInUser(user) {
  state.credentialUser = user;
}

function __reset() {
  state.user = null;
  state.observers = [];
  state.credentialError = null;
  state.credentialUser = { email: 'google@example.com', emailVerified: true };
  jest.clearAllMocks();
}

module.exports = {
  __esModule: true,
  __setFirebaseUser,
  __setGoogleSignInCredentialError,
  __setGoogleSignInUser,
  __reset,
  default: { auth: () => auth, ...auth },
  GoogleAuthProvider,
  signInWithEmailAndPassword: auth.signInWithEmailAndPassword,
  signInWithCredential: auth.signInWithCredential,
  createUserWithEmailAndPassword: auth.createUserWithEmailAndPassword,
  updateProfile: auth.updateProfile,
  signOut: auth.signOut,
  onAuthStateChanged,
  onIdTokenChanged,
};

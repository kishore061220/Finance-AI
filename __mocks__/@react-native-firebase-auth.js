/**
 * Firebase auth module mock.
 *
 * Holds an in-memory user so `onAuthStateChanged` and `getIdToken` behave like a
 * real session. `signInWithEmailAndPassword` and `createUserWithEmailAndPassword`
 * reject the way Firebase does for a wrong password or an existing account, so a
 * test can assert the app surfaces the SDK's own message instead of a generic one.
 */

const state = {
  user: null,
  observers: [],
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
 * Put the module into a signed-in or signed-out state and notify observers,
 * which is what a `signInWithCredential` call does on a real device.
 */
function __setFirebaseUser(user) {
  state.user = user ? makeUser(user) : null;
  emit();
}

function __reset() {
  state.user = null;
  state.observers = [];
  jest.clearAllMocks();
}

module.exports = {
  __esModule: true,
  __setFirebaseUser,
  __reset,
  default: { auth: () => auth, ...auth },
  signInWithEmailAndPassword: auth.signInWithEmailAndPassword,
  createUserWithEmailAndPassword: auth.createUserWithEmailAndPassword,
  updateProfile: auth.updateProfile,
  signOut: auth.signOut,
  onAuthStateChanged,
};

/**
 * Shared Firebase mock for the web test suite.
 *
 * Tests drive the session provider through the real application code paths, so
 * the mocks live behind the same module boundaries the app imports:
 * `firebase/auth` supplies the SDK functions, `@/lib/firebase` supplies the
 * configured-state probe. State is held in closure variables rather than on an
 * object, because the app destructures the SDK functions (`const { x } = await
 * import(...)`), which would otherwise lose `this`.
 */

import { vi } from 'vitest'

export interface FakeFirebaseUser {
  uid: string
  email: string
  emailVerified: boolean
  displayName: string | null
  getIdToken(): Promise<string>
}

let configured = false
let projectId = 'finance-ai-test'
let token = 'signed-in-token'
let user: FakeFirebaseUser | null = null
let observers: Array<(current: FakeFirebaseUser | null) => void> = []

function makeUser(overrides: Partial<FakeFirebaseUser> = {}): FakeFirebaseUser {
  return {
    uid: 'uid-9',
    email: 'ada@example.com',
    emailVerified: true,
    displayName: null,
    getIdToken: async () => token,
    ...overrides,
  }
}

function notify() {
  for (const observer of observers) observer(user)
}

const signInWithEmailAndPassword = vi.fn(
  async (_auth: unknown, email: string): Promise<{ user: FakeFirebaseUser }> => {
    user = makeUser({ email })
    notify()
    return { user }
  },
)

const createUserWithEmailAndPassword = vi.fn(
  async (_auth: unknown, email: string): Promise<{ user: FakeFirebaseUser }> => {
    user = makeUser({ email })
    notify()
    return { user }
  },
)

const updateProfile = vi.fn(async (u: FakeFirebaseUser, profile: { displayName?: string }) => {
  user = { ...u, ...profile }
  return user
})

const signOut = vi.fn(async (_auth: unknown) => {
  user = null
  notify()
})

const signInWithPopup = vi.fn(
  async (_auth: unknown, _provider: unknown): Promise<{ user: FakeFirebaseUser }> => {
    user = makeUser()
    notify()
    return { user }
  },
)

const GoogleAuthProvider = vi.fn(() => ({}))

function onIdTokenChanged(
  _auth: unknown,
  observer: (current: FakeFirebaseUser | null) => void,
) {
  observers.push(observer)
  // Firebase fires immediately with the current user; tests must observe that
  // without needing to trigger anything themselves.
  queueMicrotask(() => observer(user))
  return () => {
    observers = observers.filter((entry) => entry !== observer)
  }
}

export const fb = {
  get user() {
    return user
  },
  get configured() {
    return configured
  },

  setConfigured(value: boolean) {
    configured = value
  },

  setProjectId(value: string) {
    projectId = value
  },

  setUser(next: Partial<FakeFirebaseUser> | null) {
    user = next ? makeUser(next) : null
    notify()
  },

  /** Simulate Firebase refreshing the ID token without a sign change. */
  setToken(value: string) {
    token = value
    notify()
  },

  reset() {
    configured = false
    projectId = 'finance-ai-test'
    token = 'signed-in-token'
    user = null
    observers = []
    signInWithEmailAndPassword.mockClear()
    createUserWithEmailAndPassword.mockClear()
    updateProfile.mockClear()
    signOut.mockClear()
    signInWithPopup.mockClear()
  },

  onIdTokenChanged,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  updateProfile,
  signOut,
  signInWithPopup,
  GoogleAuthProvider,
}

/** `firebase/auth` module shape, safe to reference from vi.mock factories. */
export function authModule() {
  return {
    onIdTokenChanged,
    signInWithEmailAndPassword,
    createUserWithEmailAndPassword,
    updateProfile,
    signOut,
    signInWithPopup,
    GoogleAuthProvider,
  }
}

/** `@/lib/firebase` module shape. */
export function firebaseLibModule() {
  return {
    isFirebaseConfigured: () => configured,
    firebaseProjectId: () => (configured ? projectId : null),
    firebaseAuth: async () => (configured ? { mockAuth: true } : null),
  }
}
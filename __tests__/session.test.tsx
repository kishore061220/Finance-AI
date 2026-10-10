/**
 * Session provider behaviour.
 *
 * The only authentication path is Firebase. The paths that matter are the ones a
 * user hits when something is misconfigured: a build with no Firebase
 * credentials, a token the server rejects, a provider that is neither, and a
 * build pointed at a different Firebase project than the server verifies.
 */

import React from 'react';
import ReactTestRenderer, { act } from 'react-test-renderer';

import { SessionProvider, useSession } from '../src/auth/SessionProvider';
import { resetFirebaseCache } from '../src/services/firebase';
import { authApi } from '../src/services/endpoints';

jest.mock('../src/services/endpoints', () => ({
  authApi: {
    config: jest.fn(),
    me: jest.fn(),
    logout: jest.fn(),
    profile: jest.fn(),
    updateProfile: jest.fn(),
  },
}));

/**
 * The native mocks.
 *
 * Loaded with `require`, not `jest.requireMock`. The latter returns an *automock* of
 * the module, which silently replaces every export with an empty stub - so a test
 * using it would call a no-op `__setFirebaseConfigured` and quietly exercise the
 * wrong branch.
 */
const firebaseApp =
  require('@react-native-firebase/app') as typeof import('@react-native-firebase/app') & {
    __setFirebaseConfigured: (configured: boolean) => void;
  };
const firebaseAuthModule =
  require('@react-native-firebase/auth') as typeof import('@react-native-firebase/auth') & {
    __setFirebaseUser: (user: { email: string } | null) => void;
    __reset: () => void;
  };

const USER = {
  id: 7,
  name: 'Developer',
  email: 'dev@example.com',
  role: 'user',
  is_active: true,
  email_verified: true,
  phone_number: null,
  created_at: '2026-01-01T00:00:00Z',
  last_login_at: null,
};

type Probe = { status: string; userEmail: string | null; projectIssue: string | null };

function Probe_({ onState }: { onState: (state: Probe) => void }) {
  const { status, user, firebaseProjectIssue } = useSession();
  onState({ status, userEmail: user?.email ?? null, projectIssue: firebaseProjectIssue });
  return null;
}

/** Renders the provider and resolves once the status leaves `loading`. */
async function mount(onState: (state: Probe) => void) {
  let tree: ReactTestRenderer.ReactTestRenderer | undefined;

  await act(async () => {
    tree = ReactTestRenderer.create(
      <SessionProvider>
        <Probe_ onState={onState} />
      </SessionProvider>,
    );
  });

  return tree;
}

beforeEach(async () => {
  resetFirebaseCache();
  firebaseApp.__setFirebaseConfigured(false);
  firebaseAuthModule.__reset();
  jest.clearAllMocks();
  (authApi.config as jest.Mock).mockResolvedValue({
    provider: 'dev',
    firebase_enabled: false,
    registration_enabled: false,
    app_env: 'local',
  });
  (authApi.me as jest.Mock).mockResolvedValue(USER);
  (authApi.logout as jest.Mock).mockResolvedValue({ signed_out: true });
});

describe('with no Firebase credentials in the build', () => {
  it('reports anonymous when there is no Firebase user', async () => {
    const states: Probe[] = [];

    await mount((state) => states.push(state));

    expect(states.at(-1)).toEqual({
      status: 'anonymous',
      userEmail: null,
      projectIssue: null,
    });
    expect(authApi.me).not.toHaveBeenCalled();
  });

  it('surfaces an unreachable API without claiming a valid session', async () => {
    (authApi.config as jest.Mock).mockRejectedValue(new Error('Network request failed'));
    const states: Probe[] = [];

    await mount((state) => states.push(state));

    // A dropped connection must not be reported as a rejected credential: the
    // login screen stays available so the user can retry.
    expect(states.at(-1)?.status).toBe('anonymous');
  });

  it('passes an unconfigured provider through to the UI', async () => {
    (authApi.config as jest.Mock).mockResolvedValue({
      provider: 'unconfigured',
      firebase_enabled: false,
      registration_enabled: false,
      app_env: 'production',
    });
    const states: Probe[] = [];

    await mount((state) => states.push(state));

    expect(states.at(-1)?.status).toBe('anonymous');
  });
});

describe('sign out', () => {
  it('tells the server before clearing the local session', async () => {
    firebaseApp.__setFirebaseConfigured(true);
    firebaseAuthModule.__setFirebaseUser({ email: 'firebase@example.com' });
    (authApi.me as jest.Mock).mockResolvedValue({ ...USER, email: 'firebase@example.com' });
    const states: Probe[] = [];
    let signOut: (() => Promise<void>) | null = null;

    await act(async () => {
      ReactTestRenderer.create(
        <SessionProvider>
          <Probe_ onState={(state) => states.push(state)} />
          <Capture onReady={(fn) => (signOut = fn)} />
        </SessionProvider>,
      );
    });

    await act(async () => {
      await signOut?.();
    });

    expect(authApi.logout).toHaveBeenCalledTimes(1);
    expect(states.at(-1)).toEqual({
      status: 'anonymous',
      userEmail: null,
      projectIssue: null,
    });
    expect(firebaseAuthModule.default.auth().signOut).toHaveBeenCalled();
  });

  it('still clears the session when the server acknowledgement fails', async () => {
    firebaseApp.__setFirebaseConfigured(true);
    firebaseAuthModule.__setFirebaseUser({ email: 'firebase@example.com' });
    (authApi.me as jest.Mock).mockResolvedValue({ ...USER, email: 'firebase@example.com' });
    (authApi.logout as jest.Mock).mockRejectedValue(new Error('offline'));
    const states: Probe[] = [];
    let signOut: (() => Promise<void>) | null = null;

    await act(async () => {
      ReactTestRenderer.create(
        <SessionProvider>
          <Probe_ onState={(state) => states.push(state)} />
          <Capture onReady={(fn) => (signOut = fn)} />
        </SessionProvider>,
      );
    });

    await act(async () => {
      await signOut?.();
    });

    expect(states.at(-1)?.status).toBe('anonymous');
  });
});

describe('with Firebase credentials in the build', () => {
  /**
   * Points the API at the Firebase account.
   *
   * `me` is resolved from the bearer token, so with a Firebase session it has to
   * return the Firebase user. Left on the default dev user it would overwrite the
   * email the observer reported and hide which path actually ran.
   */
  function mockApiAsFirebaseUser() {
    (authApi.me as jest.Mock).mockResolvedValue({ ...USER, email: 'firebase@example.com' });
  }

  it('adopts an existing Firebase session on launch', async () => {
    firebaseApp.__setFirebaseConfigured(true);
    firebaseAuthModule.__setFirebaseUser({ email: 'firebase@example.com' });
    mockApiAsFirebaseUser();
    const states: Probe[] = [];

    await mount((state) => states.push(state));

    expect(states.at(-1)).toEqual({
      status: 'authenticated',
      userEmail: 'firebase@example.com',
      projectIssue: null,
    });
  });

  it('drops the session when the server rejects the Firebase token', async () => {
    firebaseApp.__setFirebaseConfigured(true);
    firebaseAuthModule.__setFirebaseUser({ email: 'firebase@example.com' });
    (authApi.me as jest.Mock).mockRejectedValue(
      Object.assign(new Error('Invalid token.'), { status: 401 }),
    );
    const states: Probe[] = [];

    await mount((state) => states.push(state));

    expect(states.at(-1)).toEqual({
      status: 'anonymous',
      userEmail: null,
      projectIssue: null,
    });
  });

  it('flags a build pointed at a different Firebase project than the server', async () => {
    firebaseApp.__setFirebaseConfigured(true);
    (authApi.config as jest.Mock).mockResolvedValue({
      provider: 'firebase',
      firebase_enabled: true,
      registration_enabled: true,
      app_env: 'production',
      project_id: 'server-project',
    });
    const states: Probe[] = [];

    await mount((state) => states.push(state));

    // The app mock's project is 'finance-ai-test'; the server verifies
    // 'server-project', so sign-in would succeed and then be rejected.
    expect(states.at(-1)?.projectIssue).toBe('mismatch');
  });
});

/** Grabs the sign-out function once the provider has mounted. */
function Capture({ onReady }: { onReady: (fn: () => Promise<void>) => void }) {
  const { signOut } = useSession();
  onReady(signOut);
  return null;
}

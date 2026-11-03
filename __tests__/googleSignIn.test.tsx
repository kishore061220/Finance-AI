/**
 * Google sign-in, both layers.
 *
 * The service tests exercise the native flow and its error mapping. The session
 * tests prove the Google idToken becomes a Firebase credential and then the
 * normal `adoptToken` path - not a second authentication system.
 */

import React from 'react';
import ReactTestRenderer, { act } from 'react-test-renderer';

import { SessionProvider, useSession } from '../src/auth/SessionProvider';
import { authApi } from '../src/services/endpoints';
import { resetFirebaseCache } from '../src/services/firebase';
import {
  getGoogleIdToken,
  googleSignOut,
  GoogleSignInCancelled,
  resetGoogleSignInForTests,
} from '../src/services/googleSignIn';

jest.mock('../src/services/endpoints', () => ({
  authApi: {
    config: jest.fn(),
    me: jest.fn(),
    logout: jest.fn(),
    profile: jest.fn(),
    updateProfile: jest.fn(),
  },
}));

const firebaseApp =
  require('@react-native-firebase/app') as typeof import('@react-native-firebase/app') & {
    __setFirebaseConfigured: (configured: boolean) => void;
  };
const firebaseAuthModule =
  require('@react-native-firebase/auth') as typeof import('@react-native-firebase/auth') & {
    __setFirebaseUser: (user: { email: string } | null) => void;
    __setGoogleSignInCredentialError: (error: unknown) => void;
    __setGoogleSignInUser: (user: Record<string, unknown>) => void;
    __reset: () => void;
  };
const googleMock =
  require('@react-native-google-signin/google-signin') as typeof import('@react-native-google-signin/google-signin') & {
    __setGoogleSignInSuccess: (idToken?: string | null) => void;
    __setGoogleSignInCancelled: () => void;
    __setGoogleSignInError: (error: unknown) => void;
    __setPlayServicesError: (error: unknown) => void;
    __setGoogleSignOutError: (error: unknown) => void;
    __getConfiguredOptions: () => Record<string, unknown> | null;
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

type Snapshot = { status: string; email: string | null; projectIssue: string | null };
type Actions = {
  signInWithGoogle: () => Promise<void>;
  signInWithEmail: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string, name: string) => Promise<void>;
  signOut: () => Promise<void>;
};

function Probe({
  onState,
  onActions,
}: {
  onState: (state: Snapshot) => void;
  onActions: (actions: Actions) => void;
}) {
  const session = useSession();
  onState({
    status: session.status,
    email: session.user?.email ?? null,
    projectIssue: session.firebaseProjectIssue,
  });
  onActions(session);
  return null;
}

async function mountSession() {
  let snapshot: Snapshot = { status: 'loading', email: null, projectIssue: null };
  let actions: Actions | null = null;
  let tree: ReactTestRenderer.ReactTestRenderer | undefined;

  await act(async () => {
    tree = ReactTestRenderer.create(
      <SessionProvider>
        <Probe
          onState={(state) => {
            snapshot = state;
          }}
          onActions={(value) => {
            actions = value;
          }}
        />
      </SessionProvider>,
    );
  });

  return {
    tree,
    snapshot: () => snapshot,
    actions: () => {
      if (!actions) throw new Error('Session provider did not mount.');
      return actions;
    },
  };
}

async function captureError(action: () => Promise<void>): Promise<unknown> {
  let error: unknown;
  await act(async () => {
    try {
      await action();
    } catch (cause) {
      error = cause;
    }
  });
  return error;
}

beforeEach(() => {
  resetFirebaseCache();
  resetGoogleSignInForTests();
  googleMock.__reset();
  firebaseApp.__setFirebaseConfigured(false);
  firebaseAuthModule.__reset();
  jest.clearAllMocks();
  (authApi.config as jest.Mock).mockResolvedValue({
    provider: 'firebase',
    firebase_enabled: true,
    registration_enabled: true,
    app_env: 'test',
    project_id: 'finance-ai-test',
  });
  (authApi.me as jest.Mock).mockResolvedValue(USER);
  (authApi.logout as jest.Mock).mockResolvedValue({ signed_out: true });
});

describe('googleSignIn service', () => {
  it('configures once with the Web client id and no offline access', async () => {
    googleMock.__setGoogleSignInSuccess('google-id-token');

    expect(await getGoogleIdToken()).toBe('google-id-token');
    expect(await getGoogleIdToken()).toBe('google-id-token');

    expect(googleMock.GoogleSignin.configure).toHaveBeenCalledTimes(1);
    expect(googleMock.GoogleSignin.configure).toHaveBeenCalledWith({
      webClientId: expect.any(String),
      scopes: ['email', 'profile'],
      offlineAccess: false,
    });
  });

  it('turns a cancelled native response into a typed cancellation', async () => {
    googleMock.__setGoogleSignInCancelled();

    await expect(getGoogleIdToken()).rejects.toBeInstanceOf(GoogleSignInCancelled);
  });

  it('rejects a success response with no ID token', async () => {
    googleMock.__setGoogleSignInSuccess(null);

    await expect(getGoogleIdToken()).rejects.toThrow(/did not return an ID token/);
  });

  it('maps a Play Services failure to a user-facing message', async () => {
    googleMock.__setPlayServicesError(
      Object.assign(new Error('missing'), { code: googleMock.statusCodes.PLAY_SERVICES_NOT_AVAILABLE }),
    );

    await expect(getGoogleIdToken()).rejects.toThrow(/Play Services/);
  });

  it.each([
    ['10', /misconfigured for this build/],
    ['DEVELOPER_ERROR', /misconfigured for this build/],
    ['ASYNC_OP_IN_PROGRESS', /already in progress/],
  ])('maps native error %s', async (code, expected) => {
    googleMock.__setGoogleSignInError(Object.assign(new Error('native'), { code }));

    await expect(getGoogleIdToken()).rejects.toThrow(expected);
  });

  it('signs out of Google best-effort even when the native call fails', async () => {
    googleMock.__setGoogleSignOutError(new Error('offline'));

    await expect(googleSignOut()).resolves.toBeUndefined();
    expect(googleMock.GoogleSignin.signOut).toHaveBeenCalled();
  });
});

describe('session Google sign-in', () => {
  beforeEach(() => {
    firebaseApp.__setFirebaseConfigured(true);
  });

  it('adopts the Firebase session for a new Google user', async () => {
    googleMock.__setGoogleSignInSuccess('google-id-token-new');
    firebaseAuthModule.__setGoogleSignInUser({
      email: 'new-google@example.com',
      emailVerified: true,
    });
    (authApi.me as jest.Mock).mockResolvedValue({
      ...USER,
      id: 101,
      email: 'new-google@example.com',
    });
    const session = await mountSession();

    await act(async () => {
      await session.actions().signInWithGoogle();
    });

    expect(firebaseAuthModule.GoogleAuthProvider.credential).toHaveBeenCalledWith(
      'google-id-token-new',
    );
    expect(firebaseAuthModule.signInWithCredential).toHaveBeenCalledTimes(1);
    expect(authApi.me).toHaveBeenCalled();
    expect(session.snapshot()).toMatchObject({
      status: 'authenticated',
      email: 'new-google@example.com',
    });
  });

  it('adopts the same local user for an existing Google user', async () => {
    googleMock.__setGoogleSignInSuccess('google-id-token-existing');
    firebaseAuthModule.__setGoogleSignInUser({
      email: 'existing-google@example.com',
      emailVerified: true,
    });
    (authApi.me as jest.Mock).mockResolvedValue({
      ...USER,
      id: 7,
      email: 'existing-google@example.com',
    });
    const session = await mountSession();

    await act(async () => {
      await session.actions().signInWithGoogle();
    });

    expect(session.snapshot()).toMatchObject({
      status: 'authenticated',
      email: 'existing-google@example.com',
    });
  });

  it('leaves the session anonymous when the user cancels', async () => {
    googleMock.__setGoogleSignInCancelled();
    const session = await mountSession();

    const error = await captureError(() => session.actions().signInWithGoogle());

    expect(error).toBeInstanceOf(GoogleSignInCancelled);
    expect(session.snapshot().status).toBe('anonymous');
    expect(authApi.me).not.toHaveBeenCalled();
  });

  it('leaves the session anonymous when Firebase is unavailable', async () => {
    firebaseApp.__setFirebaseConfigured(false);
    const session = await mountSession();

    const error = await captureError(() => session.actions().signInWithGoogle());

    expect((error as Error).message).toMatch(/needs Firebase/);
    expect(googleMock.GoogleSignin.signIn).not.toHaveBeenCalled();
  });

  it('translates a Firebase network failure', async () => {
    googleMock.__setGoogleSignInSuccess('google-id-token');
    firebaseAuthModule.__setGoogleSignInCredentialError(
      Object.assign(new Error('network'), { code: 'auth/network-request-failed' }),
    );
    const session = await mountSession();

    const error = await captureError(() => session.actions().signInWithGoogle());

    expect((error as Error).message).toMatch(/Cannot reach Firebase/);
    expect(session.snapshot().status).toBe('anonymous');
  });

  it('signs out of Google as part of the session sign-out', async () => {
    firebaseAuthModule.__setGoogleSignInUser({
      email: 'google@example.com',
      emailVerified: true,
    });
    (authApi.me as jest.Mock).mockResolvedValue({ ...USER, email: 'google@example.com' });
    const session = await mountSession();

    await act(async () => {
      await session.actions().signOut();
    });

    expect(googleMock.GoogleSignin.signOut).toHaveBeenCalledTimes(1);
    expect(session.snapshot()).toEqual({
      status: 'anonymous',
      email: null,
      projectIssue: null,
    });
  });

  it('keeps email sign-in working', async () => {
    const session = await mountSession();

    await act(async () => {
      await session.actions().signInWithEmail('email@example.com', 'secret');
    });

    expect(firebaseAuthModule.signInWithEmailAndPassword).toHaveBeenCalledWith(
      expect.anything(),
      'email@example.com',
      'secret',
    );
    expect(session.snapshot().status).toBe('authenticated');
  });

  it('keeps registration working', async () => {
    const session = await mountSession();

    await act(async () => {
      await session.actions().signUp('register@example.com', 'secret', 'Register');
    });

    expect(firebaseAuthModule.createUserWithEmailAndPassword).toHaveBeenCalled();
    expect(firebaseAuthModule.updateProfile).toHaveBeenCalled();
    expect(session.snapshot().status).toBe('authenticated');
  });

  it('still restores an existing Firebase session on launch', async () => {
    firebaseAuthModule.__setFirebaseUser({ email: 'restored@example.com' });
    (authApi.me as jest.Mock).mockResolvedValue({
      ...USER,
      email: 'restored@example.com',
    });
    const session = await mountSession();

    expect(session.snapshot()).toMatchObject({
      status: 'authenticated',
      email: 'restored@example.com',
    });
  });
});

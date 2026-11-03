/**
 * The login screen's Google affordance.
 *
 * The session provider is mocked because these tests are about the screen's
 * own decisions: when to show the button, when to disable it, and whether a
 * cancelled chooser leaks a banner or a second submission.
 */

import React from 'react';
import { Text } from 'react-native';
import ReactTestRenderer, { act } from 'react-test-renderer';

import LoginScreen from '../src/screens/LoginScreen';

jest.mock('../src/auth/SessionProvider', () => ({
  useSession: jest.fn(),
  isFirebaseAvailable: jest.fn(),
}));

jest.mock('../src/services/googleSignIn', () => {
  class GoogleSignInCancelled extends Error {
    constructor() {
      super('Google sign-in was cancelled.');
      this.name = 'GoogleSignInCancelled';
    }
  }
  return {
    GoogleSignInCancelled,
    isGoogleSignInConfigured: jest.fn(),
  };
});

const sessionModule =
  require('../src/auth/SessionProvider') as {
    useSession: jest.Mock;
    isFirebaseAvailable: jest.Mock;
  };
const googleModule =
  require('../src/services/googleSignIn') as {
    GoogleSignInCancelled: new () => Error;
    isGoogleSignInConfigured: jest.Mock;
  };

const firebaseConfig = {
  provider: 'firebase',
  firebase_enabled: true,
  registration_enabled: true,
  app_env: 'test',
  project_id: 'finance-ai-test',
};

function setSession(overrides: Record<string, unknown> = {}) {
  sessionModule.useSession.mockReturnValue({
    status: 'anonymous',
    user: null,
    config: firebaseConfig,
    firebaseProjectIssue: null,
    signInWithEmail: jest.fn(),
    signUp: jest.fn(),
    signInWithGoogle: jest.fn(async () => {}),
    signOut: jest.fn(),
    ...overrides,
  });
}

async function renderScreen() {
  let tree: ReactTestRenderer.ReactTestRenderer | undefined;
  await act(async () => {
    tree = ReactTestRenderer.create(<LoginScreen />);
  });
  if (!tree) throw new Error('Login screen did not render.');
  return tree;
}

function googleButton(tree: ReactTestRenderer.ReactTestRenderer) {
  const matches = tree.root.findAll(
    (node) => node.props?.accessibilityLabel === 'Continue with Google',
  );
  return matches[0] ?? null;
}

function hasText(tree: ReactTestRenderer.ReactTestRenderer, value: string) {
  return (
    tree.root.findAll(
      (node) => node.type === Text && node.props.children === value,
    ).length > 0
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  sessionModule.isFirebaseAvailable.mockReturnValue(true);
  googleModule.isGoogleSignInConfigured.mockReturnValue(true);
  setSession();
});

it('shows the Google button when the server has Firebase enabled', async () => {
  const tree = await renderScreen();

  const button = googleButton(tree);
  expect(button).not.toBeNull();
  expect(button?.props.disabled).toBe(false);
});

it('hides every form when the server has no Firebase provider', async () => {
  setSession({
    config: {
      ...firebaseConfig,
      provider: 'dev',
      firebase_enabled: false,
      registration_enabled: false,
    },
  });
  const tree = await renderScreen();

  expect(googleButton(tree)).toBeNull();
});

it('disables the button and says why when Google is not configured', async () => {
  googleModule.isGoogleSignInConfigured.mockReturnValue(false);
  const tree = await renderScreen();

  expect(googleButton(tree)?.props.disabled).toBe(true);
  expect(hasText(tree, 'Google sign-in is not configured.')).toBe(true);
});

it('disables the button when the Firebase project does not match', async () => {
  setSession({ firebaseProjectIssue: 'mismatch' });
  const tree = await renderScreen();

  expect(googleButton(tree)?.props.disabled).toBe(true);
});

it('ignores a second tap while the first sign-in is pending', async () => {
  const signInWithGoogle = jest.fn(() => new Promise<void>(() => {}));
  setSession({ signInWithGoogle });
  const tree = await renderScreen();

  const tapIfEnabled = () => {
    const button = googleButton(tree);
    if (button && !button.props.disabled) button.props.onPress();
  };

  await act(async () => {
    tapIfEnabled();
  });
  await act(async () => {
    tapIfEnabled();
  });

  expect(signInWithGoogle).toHaveBeenCalledTimes(1);
});

it('clears busy state without a banner when the user cancels', async () => {
  const signInWithGoogle = jest.fn(async () => {
    throw new googleModule.GoogleSignInCancelled();
  });
  setSession({ signInWithGoogle });
  const tree = await renderScreen();

  await act(async () => {
    googleButton(tree)?.props.onPress();
  });

  expect(hasText(tree, 'Google sign-in was cancelled.')).toBe(false);
  expect(googleButton(tree)?.props.disabled).toBe(false);
});

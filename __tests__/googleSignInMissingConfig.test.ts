/**
 * A build with no Web client id must fail before touching the native module,
 * with the exact message the login screen shows.
 */

jest.mock('../src/config', () => ({
  GOOGLE_WEB_CLIENT_ID: null,
}));

import {
  getGoogleIdToken,
  isGoogleSignInConfigured,
} from '../src/services/googleSignIn';

const googleMock =
  require('@react-native-google-signin/google-signin') as typeof import('@react-native-google-signin/google-signin') & {
    __reset: () => void;
  };

beforeEach(() => {
  googleMock.__reset();
  jest.clearAllMocks();
});

it('reports that Google sign-in is not configured', () => {
  expect(isGoogleSignInConfigured()).toBe(false);
});

it('throws a clear error without calling the native module', async () => {
  await expect(getGoogleIdToken()).rejects.toThrow('Google sign-in is not configured.');
  expect(googleMock.GoogleSignin.signIn).not.toHaveBeenCalled();
  expect(googleMock.GoogleSignin.configure).not.toHaveBeenCalled();
});

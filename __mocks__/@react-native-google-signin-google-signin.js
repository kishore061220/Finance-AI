/**
 * Google Sign-In native module mock.
 *
 * The shipped mock in the package always succeeds, so it cannot exercise the
 * cancelled, missing-ID-token, Play Services and native-error branches. This
 * one keeps the same public shape but lets a test choose the outcome and then
 * resets it between cases.
 */

const statusCodes = Object.freeze({
  // Real Android values from GoogleSignInStatusCodes / PromiseWrapper.
  SIGN_IN_CANCELLED: '12501',
  IN_PROGRESS: 'ASYNC_OP_IN_PROGRESS',
  PLAY_SERVICES_NOT_AVAILABLE: 'PLAY_SERVICES_NOT_AVAILABLE',
  SIGN_IN_REQUIRED: '12502',
  NULL_PRESENTER: 'NULL_PRESENTER',
});

const state = {
  response: null,
  signInError: null,
  playServicesError: null,
  signOutError: null,
  configured: null,
};

function defaultSuccess(idToken) {
  return {
    type: 'success',
    data: {
      idToken,
      serverAuthCode: null,
      scopes: ['email', 'profile'],
      user: {
        id: 'google-user-1',
        name: 'Google User',
        email: 'google@example.com',
        photo: null,
        familyName: null,
        givenName: null,
      },
    },
  };
}

const GoogleSignin = {
  configure: jest.fn((options) => {
    state.configured = options;
  }),
  hasPlayServices: jest.fn(async () => {
    if (state.playServicesError) throw state.playServicesError;
    return true;
  }),
  signIn: jest.fn(async () => {
    if (state.signInError) throw state.signInError;
    return state.response;
  }),
  signOut: jest.fn(async () => {
    if (state.signOutError) throw state.signOutError;
    return null;
  }),
};

function __setGoogleSignInSuccess(idToken = 'mock-google-id-token') {
  state.response = defaultSuccess(idToken);
}

function __setGoogleSignInResponse(response) {
  state.response = response;
}

function __setGoogleSignInCancelled() {
  state.response = { type: 'cancelled', data: null };
}

function __setGoogleSignInError(error) {
  state.signInError = error;
}

function __setPlayServicesError(error) {
  state.playServicesError = error;
}

function __setGoogleSignOutError(error) {
  state.signOutError = error;
}

function __getConfiguredOptions() {
  return state.configured;
}

function __reset() {
  state.response = defaultSuccess('mock-google-id-token');
  state.signInError = null;
  state.playServicesError = null;
  state.signOutError = null;
  state.configured = null;
  jest.clearAllMocks();
}

__setGoogleSignInSuccess();

module.exports = {
  __esModule: true,
  GoogleSignin,
  statusCodes,
  __setGoogleSignInSuccess,
  __setGoogleSignInResponse,
  __setGoogleSignInCancelled,
  __setGoogleSignInError,
  __setPlayServicesError,
  __setGoogleSignOutError,
  __getConfiguredOptions,
  __reset,
};

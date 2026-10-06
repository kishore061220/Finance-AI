/**
 * Firebase messaging mock.
 *
 * `requestPermission` resolves to the bare status number the real namespaced API
 * returns - not an object - because the app compares it numerically and a mock
 * returning `{ authorizationStatus }` would let a wrong comparison pass.
 *
 * Defaults to NOT_DETERMINED so a test must opt in to each path.
 */

const state = {
  status: -1,
  token: 'mock-fcm-token',
  tokenError: null,
  listeners: [],
};

const messaging = () => ({
  requestPermission: jest.fn(async () => state.status),
  getToken: jest.fn(async () => {
    if (state.tokenError) throw state.tokenError;
    return state.token;
  }),
  hasPermission: jest.fn(async () => state.status),
  onMessage: jest.fn((listener) => {
    state.listeners.push(listener);
    return () => {
      state.listeners = state.listeners.filter((entry) => entry !== listener);
    };
  }),
  onNotificationOpenedApp: jest.fn(() => () => undefined),
});

function __setAuthorizationStatus(status) {
  state.status = status;
}

function __setTokenError(message) {
  state.tokenError = message ? new Error(message) : null;
}

function __reset() {
  state.status = -1;
  state.token = 'mock-fcm-token';
  state.tokenError = null;
  state.listeners = [];
  jest.clearAllMocks();
}

module.exports = {
  __esModule: true,
  __setAuthorizationStatus,
  __setTokenError,
  __reset,
  AuthorizationStatus: {
    NOT_DETERMINED: -1,
    DENIED: 0,
    AUTHORIZED: 1,
    PROVISIONAL: 2,
  },
  default: messaging,
  getMessaging: messaging,
};

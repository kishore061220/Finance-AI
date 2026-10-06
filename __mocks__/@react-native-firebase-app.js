/**
 * Firebase app module mock.
 *
 * Models the shape the real module has when `google-services.json` is absent: the
 * import succeeds (so `isFirebaseAvailable()` reports true) but `apps` is empty, so
 * there is no app to authenticate against. That is the state a fresh clone is in,
 * and the fallback to the development-token path depends on it.
 *
 * Set `__setFirebaseConfigured(true)` to model a build that has the credentials
 * file, which is how the Firebase branch is tested without a real project.
 */

const state = {
  configured: false,
};

const app = {
  name: '[DEFAULT]',
  options: { apiKey: 'test-api-key', projectId: 'finance-ai-test' },
  automaticDataCollectionEnabled: false,
};

const firebase = {
  apps: [],
  initializeApp: jest.fn(),
  app: jest.fn(() => app),
  getApps: jest.fn(() => firebase.apps),
  getApp: jest.fn(() => app),
};

function __setFirebaseConfigured(configured) {
  state.configured = configured;
  // A configured build has an initialised default app; an unconfigured one does
  // not. `firebase.apps` is what `services/firebase.ts` reads to find the app.
  firebase.apps = configured ? [app] : [];
  firebase.getApps.mockReturnValue(firebase.apps);
}

__setFirebaseConfigured(false);

module.exports = {
  __esModule: true,
  __setFirebaseConfigured,
  default: firebase,
  firebase,
};

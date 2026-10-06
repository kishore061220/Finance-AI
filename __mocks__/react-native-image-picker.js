/**
 * Image picker mock.
 *
 * `__setResult` chooses between a cancelled picker, a permission failure, and a
 * successful selection, because those are the three outcomes the capture screen
 * branches on and the default should not always be the happy one.
 */

const state = {
  response: {
    didCancel: false,
    errorCode: undefined,
    assets: [{ uri: 'file:///tmp/receipt.jpg', width: 100, height: 200 }],
  },
};

function __setResult(response) {
  state.response = response;
}

function __reset() {
  state.response = {
    didCancel: false,
    errorCode: undefined,
    assets: [{ uri: 'file:///tmp/receipt.jpg', width: 100, height: 200 }],
  };
  jest.clearAllMocks();
}

module.exports = {
  __esModule: true,
  __setResult,
  __reset,
  launchCamera: jest.fn(async () => state.response),
  launchImageLibrary: jest.fn(async () => state.response),
};

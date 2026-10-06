/**
 * ML Kit text-recognition mock.
 *
 * Returns a canned receipt so the parse-then-confirm flow can be tested without a
 * camera. `__setTextError` models the native failure that happens when
 * `google-services.json` is missing, which is the case worth handling.
 */

const state = {
  text: 'SWIGGY\n1 x Masala Dosa  249.00\n1 x Filter Coffee  59.00\nTOTAL 308.00',
  error: null,
};

function __setText(value) {
  state.text = value;
}

function __setTextError(message) {
  state.error = message ? new Error(message) : null;
}

function __reset() {
  state.error = null;
  jest.clearAllMocks();
}

module.exports = {
  __esModule: true,
  __setText,
  __setTextError,
  __reset,
  default: {
    recognize: jest.fn(async () => {
      if (state.error) throw state.error;
      const lines = state.text.split('\n');
      return {
        text: state.text,
        blocks: [{ lines: lines.map((line) => ({ text: line, left: 0, top: 0, width: 1, height: 1 })) }],
      };
    }),
  },
};

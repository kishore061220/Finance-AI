module.exports = {
  root: true,
  extends: '@react-native',
  /**
   * The React Native app lives at the repository ROOT. Without this, `eslint .`
   * walks into every sibling project and lints the web client, the backend and
   * the ML package against React Native rules - thousands of errors that have
   * nothing to do with this app. Each of those projects lints itself:
   * finance-ai-frontend uses oxlint, finance-ai-api and finance-ai-ml use pytest
   * and compileall.
   */
  ignorePatterns: [
    'node_modules/',
    'android/',
    'ios/',
    'finance-ai-api/',
    'finance-ai-frontend/',
    'finance-ai-ml/',
    'docs/',
    'database/',
    'coverage/',
  ],
  rules: {
    /**
     * `void somePromise()` is how this codebase marks an intentionally
     * un-awaited promise - a fire-and-forget reload, or an event handler whose
     * rejection is handled inside the promise itself. Without it the
     * no-floating-promises idiom is indistinguishable from a forgotten `await`.
     * `allowAsStatement` keeps the marker working for statement position while
     * still flagging `return void x`.
     */
    'no-void': ['warn', { allowAsStatement: true }],

    /**
     * Inline styles are allowed, but the theme is still the source of colour and
     * spacing tokens. The warnings that remain are for one-off geometry (a bar
     * height, a percentage width) where a named style would be reused exactly once
     * and would read as noise.
     */
    'react-native/no-inline-styles': 'warn',
  },
  overrides: [
    {
      // Jest globals are declared for the setup file and the manual mocks as well
      // as the specs - `__mocks__` files call `jest.fn()` directly.
      files: [
        '**/__tests__/**/*.{js,ts,tsx}',
        '**/*.test.{js,ts,tsx}',
        '**/__mocks__/**/*.js',
        'jest.setup.js',
      ],
      env: { jest: true, node: true },
      rules: {
        // Tests assert on rendered structure, so a long expect chain in one line
        // is clearer than one statement per assertion.
        'jest/expect-expect': 'off',
      },
    },
  ],
};

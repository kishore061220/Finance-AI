module.exports = {
  preset: '@react-native/jest-preset',
  /**
   * The React Native app lives at the repository ROOT. Without an explicit
   * roots/testMatch, Jest discovers every *.test.* in the tree and runs the web
   * client's Vitest suites under the React Native preset - jsdom is not there,
   * so they fail with "import a file after the Jest environment has been torn
   * down". The web client has its own runner (`npm test` in
   * finance-ai-frontend); this project owns only its own tests.
   */
  roots: ['<rootDir>/__tests__'],
  testMatch: ['**/__tests__/**/*.test.{js,ts,tsx}'],
  testPathIgnorePatterns: [
    '/node_modules/',
    '<rootDir>/finance-ai-api/',
    '<rootDir>/finance-ai-frontend/',
    '<rootDir>/finance-ai-ml/',
  ],
  /**
   * React Navigation, Firebase, AsyncStorage and the ML Kit bindings all ship
   * untranspiled ESM, so Jest's default "skip node_modules" rule leaves them
   * unparseable. They are listed explicitly rather than disabling the check for
   * everything in node_modules, which would hide real syntax problems in the
   * packages we depend on most.
   */
  transformIgnorePatterns: [
    'node_modules/(?!(?:@react-native|react-native|@react-navigation|@react-native-firebase|@react-native-async-storage|@react-native-ml-kit|react-native-image-picker|react-native-safe-area-context|react-native-screens|react-native-gesture-handler)/)',
  ],
  setupFiles: ['<rootDir>/jest.setup.js'],
  /**
   * Native modules have no implementation under Jest. Each is replaced by a mock
   * that reports the same shape the real module returns, so a test exercises the
   * app's own branching rather than a stub that always succeeds - which would let
   * a broken Firebase fallback pass unnoticed.
   */
  moduleNameMapper: {
    '^@react-native-async-storage/async-storage$':
      '<rootDir>/__mocks__/@react-native-async-storage.js',
    '^@react-native-firebase/app$': '<rootDir>/__mocks__/@react-native-firebase-app.js',
    '^@react-native-firebase/auth$': '<rootDir>/__mocks__/@react-native-firebase-auth.js',
    '^@react-native-firebase/messaging$':
      '<rootDir>/__mocks__/@react-native-firebase-messaging.js',
    '^@react-native-ml-kit/text-recognition$':
      '<rootDir>/__mocks__/@react-native-ml-kit-text-recognition.js',
    '^react-native-image-picker$': '<rootDir>/__mocks__/react-native-image-picker.js',
  },
  collectCoverageFrom: [
    'src/**/*.{ts,tsx}',
    '!src/**/*.d.ts',
    '!src/theme.ts',
  ],
};

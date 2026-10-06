/**
 * Jest setup.
 *
 * Native modules that need no behaviour of their own are silenced here rather
 * than mocked per test, so a test that does not exercise them stays quiet.
 */

// react-native-screens and safe-area-context register native components; the
// preset does not stub them.
jest.mock('react-native-safe-area-context', () => {
  const inset = { top: 0, right: 0, bottom: 0, left: 0 };
  const frame = { x: 0, y: 0, width: 390, height: 844 };
  const React = require('react');
  // Real contexts rather than missing ones. `@react-navigation`'s
  // `SafeAreaProviderCompat` calls `useContext` on both of these, and a test
  // render crashes outright if they are undefined. Seeding them with non-null
  // defaults also tells the compat wrapper the insets are already resolved, so
  // it skips the native measurement pass and stays synchronous.
  const SafeAreaInsetsContext = React.createContext(inset);
  const SafeAreaFrameContext = React.createContext(frame);
  return {
    SafeAreaInsetsContext,
    SafeAreaFrameContext,
    SafeAreaProvider: ({ children }) => children,
    SafeAreaView: ({ children }) => React.createElement('SafeAreaView', null, children),
    useSafeAreaInsets: () => inset,
    useSafeAreaFrame: () => frame,
    initialWindowMetrics: { insets: inset, frame },
  };
});

jest.mock('react-native-screens', () => {
  const actual = jest.requireActual('react-native-screens');
  return { ...actual, enableScreens: jest.fn() };
});

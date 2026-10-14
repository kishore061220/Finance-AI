/**
 * @format
 */

import React from 'react';
import ReactTestRenderer from 'react-test-renderer';
import App from '../App';

/**
 * The provider restores the session asynchronously (config -> Firebase ->
 * subscribe). A synchronous `act` flushes only the first render and leaves that
 * chain running; it then resolves after Jest has torn the environment down and
 * `require('@react-native-firebase/app')` throws from a dead realm. That always
 * exits the run with code 1 even though every test "passed".
 *
 * An async `act` lets the chain settle while the environment is alive, and the
 * unmount runs the provider's cleanup (which marks the restore cancelled) so no
 * late state update or module load can outlive the test either.
 */
test('renders correctly', async () => {
  let tree: ReactTestRenderer.ReactTestRenderer | undefined;
  await ReactTestRenderer.act(async () => {
    tree = ReactTestRenderer.create(<App />);
  });
  await ReactTestRenderer.act(async () => {
    tree?.unmount();
  });
});

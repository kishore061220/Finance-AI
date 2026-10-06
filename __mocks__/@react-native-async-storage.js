/**
 * AsyncStorage mock.
 *
 * Backed by a real Map so a test that writes a token and then reloads the session
 * exercises the same read-back path as the device. A stub that always returns null
 * would make the restore branch look untested while passing.
 */

const store = new Map();

module.exports = {
  __esModule: true,
  default: {
    getItem: jest.fn(async (key) => (store.has(key) ? store.get(key) : null)),
    setItem: jest.fn(async (key, value) => {
      store.set(key, value);
    }),
    removeItem: jest.fn(async (key) => {
      store.delete(key);
    }),
    clear: jest.fn(async () => {
      store.clear();
    }),
    getAllKeys: jest.fn(async () => Array.from(store.keys())),
    multiGet: jest.fn(async (keys) =>
      keys.map((key) => [key, store.has(key) ? store.get(key) : null]),
    ),
    multiSet: jest.fn(async (pairs) => {
      for (const [key, value] of pairs) store.set(key, value);
    }),
    multiRemove: jest.fn(async (keys) => {
      for (const key of keys) store.delete(key);
    }),
  },
};

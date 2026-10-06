import { fileURLToPath, URL } from 'node:url'

import { defineConfig, mergeConfig } from 'vitest/config'

import viteConfig from './vite.config'

/**
 * Test config, kept in its own file.
 *
 * `vite.config.ts` uses Vite's own `defineConfig`, whose `UserConfig` has no
 * `test` key. Importing from `vitest/config` there instead pulls vitest's
 * bundled Vite types into the file, and those clash with the installed Vite 8
 * (rolldown) types - producing a wall of `hotUpdate`/`PluginContextMeta` errors
 * that has nothing to do with this project's configuration. Merging keeps each
 * file typed by its own tool.
 */
export default mergeConfig(
  viteConfig,
  defineConfig({
    /**
     * The automatic JSX runtime, set explicitly.
     *
     * Without it Vitest transforms `.tsx` with the classic runtime, which
     * compiles JSX to bare `React.createElement` calls and fails every component
     * test with "React is not defined" - even though the application build works,
     * because the app is transformed by `@vitejs/plugin-react` instead of esbuild.
     */
    esbuild: { jsx: 'automatic' },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./tests/vitest.setup.ts'],
      css: false,
      restoreMocks: true,
      alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
      /**
       * Vitest defaults to a 5s per-test timeout. These tests render whole
       * screens with jsdom and Testing Library, and on a cold CI runner the
       * first file routinely spends its budget transforming and setting up the
       * environment rather than on the assertion. That produced a failure that
       * passed on every subsequent run - a flake, not a defect. The timeout is
       * raised rather than the assertion weakened: nothing here waits on a real
       * network, so a test that needs more than 20s is genuinely stuck.
       */
      testTimeout: 20000,
      hookTimeout: 20000,
    },
  }),
)

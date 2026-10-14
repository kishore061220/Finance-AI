import { fileURLToPath } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      // Absolute filesystem path to src. `new URL(...).pathname` yields a
      // leading-slash path, and stripping that slash makes the alias relative on
      // POSIX systems (CI), which resolves against the wrong directory. On Windows
      // it happened to work (`/C:/...` -> `C:/...`), so the bug only surfaced on
      // the Linux build. `fileURLToPath` is correct on both.
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // Keeps the browser on one origin in development, so no CORS preflight and
      // no hardcoded absolute API URL in the bundle.
      '/api': {
        target: process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/health': {
        target: process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})

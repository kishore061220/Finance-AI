# Finance AI — Web

React + TypeScript single-page app for the Finance AI backend.

## Requirements

- Node.js 20 or newer
- A running Finance AI API (see `finance-ai-api/`)

## Setup

```bash
npm install
npm run dev
```

The dev server proxies `/api` to `http://127.0.0.1:8000` (see `vite.config.ts`),
so no environment configuration is needed for local work against a local API.

To point at a different backend:

```bash
VITE_API_BASE_URL=https://api.example.com npm run dev
```

Leave it unset and the app uses relative `/api` paths, which is what you want
when the API and the app are served from the same origin.

## Firebase configuration

Optional. With none of these set, the app falls back to the backend's
development-token endpoint, which the API only enables when Firebase is off and
`ALLOW_DEV_AUTH=true`.

Copy `.env.example` to `.env.local` and fill it in to enable Firebase:

```
VITE_FIREBASE_API_KEY=
VITE_FIREBASE_AUTH_DOMAIN=
VITE_FIREBASE_PROJECT_ID=
VITE_FIREBASE_STORAGE_BUCKET=
VITE_FIREBASE_MESSAGING_SENDER_ID=
VITE_FIREBASE_APP_ID=
```

The Firebase web config is not a secret — the API key is meant to be public and
restricted by authorized domain — but it is not committed, so each deployment
needs its own.

Firebase is loaded with a dynamic import, so it is only downloaded by visitors
who actually reach the login screen on a Firebase-enabled server.

## Scripts

| Script | Purpose |
| --- | --- |
| `npm run dev` | Dev server with hot reload and the `/api` proxy |
| `npm run build` | Type-check, then build to `dist/` |
| `npm run preview` | Serve the production build locally |
| `npm run lint` | Oxlint over `src/` |
| `npm run typecheck` | `tsc` in no-emit mode |
| `npm test` | Vitest, single run |
| `npm run test:watch` | Vitest in watch mode |
| `npm run verify` | lint, typecheck, test, build — the gate for a change |

## Architecture

```
src/
  api/          no; see lib/endpoints.ts
  auth/         SessionContext — Firebase and development-token sessions
  components/   AppLayout (signed-in chrome), charts.tsx, ui.tsx
  hooks/        useAsync — fetch-on-mount with loading/error/reload
  lib/          api.ts (axios client), endpoints.ts (typed API surface),
                firebase.ts (lazy SDK loading), format.ts
  pages/        one file per route
  types.ts      response shapes mirroring the backend schemas
```

The API client in `lib/api.ts` attaches the bearer token from memory on every
request. The token is not stored in `localStorage`: an XSS bug would otherwise be
a session theft. Firebase restores its own session from IndexedDB, and the
development token lives in `sessionStorage`, which dies with the tab.

`lib/endpoints.ts` is the only place that knows API URLs. Pages call typed
wrappers, never raw paths.

## Tests

`npm test` covers:

- `tests/format.test.ts` — money, percentage, and date formatting
- `tests/api.test.ts` — token attachment, error mapping, `skipAuth`
- `tests/endpoints.test.ts` — request shapes and URL construction per wrapper
- `tests/ui.test.tsx` — accessibility of the shared primitives
- `tests/session.test.tsx` — route guards, sign-in, sign-out, session restore

## Notes for contributors

- Ownership is derived from the bearer token by the backend. Never send or trust
  a client-supplied `user_id`.
- Money arrives from the API as strings. Use the formatters in `lib/format.ts`
  instead of `parseFloat`, so rounding stays consistent.
- Screens are lazily imported in `App.tsx`. Recharts is large and only the
  dashboard needs it.

# Firebase Setup Guide

This document describes how to enable real Firebase Authentication so clients can sign in against a Firebase-backed server. It covers API configuration, web and mobile client configuration, verification steps, and how to detect common project mismatches.

## Prerequisites
- A Firebase project in the Firebase Console
- Firebase Authentication enabled (Email/Password and/or Google as needed)
- For web: the Firebase web app config (public)
- For mobile (Android): `google-services.json` in `android/app/`

## Backend (finance-ai-api)

The API verifies Firebase ID tokens using the Firebase Admin SDK. Set the following in `finance-ai-api/.env` (do not commit `.env`):

| Variable | Required | Notes |
| --- | --- | --- |
| `FIREBASE_PROJECT_ID` | Yes | The Firebase project the server verifies against. |
| `FIREBASE_CREDENTIALS_PATH` | One of these | Path to a service account JSON file. |
| `FIREBASE_CREDENTIALS_JSON` | One of these | Raw JSON of a service account. The path takes precedence. |
| `ALLOW_DEV_AUTH` | No | Must be `false` in production and is automatically ignored when Firebase is configured. |

When Firebase is configured, the server sets:
- `settings.firebase_enabled = true`
- `GET /api/auth/config` returns `provider = "firebase"`, `firebase_enabled = true`, and `project_id = FIREBASE_PROJECT_ID` (or `null` if not set)

When Firebase is not configured, dev auth may only be active if explicitly allowed; however, this client only offers Firebase sign-in.

## Web (finance-ai-frontend)

The web client is Firebase-only. Set the following in `finance-ai-frontend/.env.local` (not committed):

| Variable | Required |
| --- | --- |
| `VITE_FIREBASE_API_KEY` | Yes |
| `VITE_FIREBASE_AUTH_DOMAIN` | Yes |
| `VITE_FIREBASE_PROJECT_ID` | Yes |
| `VITE_FIREBASE_STORAGE_BUCKET` | Yes |
| `VITE_FIREBASE_MESSAGING_SENDER_ID` | Yes |
| `VITE_FIREBASE_APP_ID` | Yes |

Notes:
- These are public values. Restrict HTTP referrers in the Firebase Console.
- `firebaseProjectId()` reads the configured project and is compared against `config.project_id` from `/api/auth/config`. Mismatches produce a visible warning and prevent "working" sign-in from 401ing later.
- `onIdTokenChanged` drives session adoption and token refresh.

## Mobile (React Native)

Android requires `android/app/google-services.json`. iOS requires `GoogleService-Info.plist` per standard Firebase RN setup.

- If the file is missing, the app cannot initialize Firebase and will show a notice that sign-in is not available (no developer fallback).
- The session subscribes to `onIdTokenChanged` (Firebase Auth) so refreshed tokens are adopted without a sign-out/in.
- Project consistency: `firebaseProjectId()` reads the configured project; if `config.project_id` differs, the UI warns.

## Verification (no fabrication)

1. API: `cd finance-ai-api && .venv\Scripts\python.exe -m pytest -q` → 269 passed.
2. ML: `cd finance-ai-ml && ..\finance-ai-api\.venv\Scripts\python.exe -m pytest -q` → 81 passed.
3. Web: `cd finance-ai-frontend && npx vitest run` → 100 passed; `npm run typecheck`, `npm run lint` clean.
4. Mobile: `cd C:\Projects\Finance-AI && npx jest --no-coverage` → 39 passed; `npm run typecheck` clean, `npm run lint` produces only style warnings.

To test real Firebase end-to-end (BLOCKED if credentials missing):
- Ensure the API runs with Firebase configured and `ALLOW_DEV_AUTH=false`. Do not point at the live `finance_ai` database for ad-hoc destructive E2E writes; use the controlled P2 path with `finance_ai_e2e`.
- Web builds with matching `VITE_FIREBASE_*`. Sign in with Email/Password or Google. `GET /api/auth/me` returns 200 and provisions the user (by Firebase UID). Token refresh occurs without explicit re-login.
- Mobile with matching `google-services.json` behaves the same.
- A mismatch (different `project_id`) is detected and blocks successful operation as designed.

Do not invent tokens or mark Firebase as verified without running these steps against real credentials.

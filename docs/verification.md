# Verification record

What was actually executed on this machine, and what that does and does not
prove. Commands are reproducible from a clean checkout.

## Executed

| # | Component | Command | Result |
| --- | --- | --- | --- |
| 1 | API | `.venv\Scripts\python.exe -m pytest -q` | **255 passed** |
| 2 | API | `python -m compileall -q app main.py` | clean |
| 3 | ML | `pytest -q` (run with the API venv) | **65 passed** |
| 4 | Web | `npm run typecheck` | clean |
| 5 | Web | `npm run lint` (oxlint) | clean |
| 6 | Web | `npm test -- --run` | **98 passed** |
| 7 | Web | `npm run build` | built; app shell present in the main chunk |
| 8 | Mobile | `npx tsc --noEmit` | clean |
| 9 | Mobile | `npm run lint` | 0 errors, 24 inline-style warnings |
| 10 | Mobile | `npm test -- --runInBand` | **41 passed** |
| 11 | Mobile Android | `gradlew :app:assembleDebug` | **BUILD SUCCESSFUL**, `app-debug.apk` |
| 12 | Mobile bundle | `react-native bundle --platform android --dev false` | bundle written, native modules resolved |
| 13 | CI | YAML parse of both workflows | 4 jobs in `ci.yml`, 1 in `android-build.yml` |

Earlier in the engagement, Alembic was exercised for upgrade, downgrade, and
`alembic check` (no new operations detected), including a round trip back to
`0005` with data preserved.

## What each check covers

**API (255).** Authorization boundaries - an authenticated user cannot read or
mutate another user's rows. Ownership scoping on every list, filter, and update.
Backup checksum verification, restore preview, conflict handling, and rollback.
The prediction gate at the three-month boundary. Token expiry and refresh.
Registration and pending invites. The 5xx path must not leak a traceback.
Model-artifact integrity: a tampered `.pkl` is refused before unpickling and
scoring degrades to rules-only. The 31-feature set is asserted to match the
standalone package's `CANONICAL_FEATURES`.

**ML (65).** Feature-vector construction and ordering, refusal to train below the
row/positive thresholds, artifact round-trip, checksum verification, and scoring
against a known fixture.

**Web (98).** Axios client behaviour: the `Authorization` header, token clearing
on 401, error normalisation without leaking 5xx internals, and query/body
serialisation. Endpoint wrappers. Formatting edge cases. Session and routing: an
anonymous visitor cannot reach a protected screen, and an authenticated one is
not stranded on login. Each of the seven screens is asserted to actually render,
not merely to stop showing the login form.

**Mobile (41).** The same client and endpoint behaviour, plus session
restoration for both providers, Firebase sign-in/sign-out paths, the
`unconfigured` provider, and an app-shell render with the full navigator.

## Defects these runs found

Recorded because they are the argument for running the suites rather than
assuming:

1. **Web — shipping-blocking.** A 0-byte `src/App.jsx` shadowed `src/App.tsx`
   (`.jsx` resolves before `.tsx` in Vite). Every build and every test imported an
   empty module, so the production bundle contained no application. Found by the
   session/routing suite; fixed by deleting the stray file. A guard is worth
   considering in CI (see `ci.yml`, which type-checks and tests on every push).
2. **Mobile — test-visible.** Dynamic `import()` of native modules does not run
   under Jest without an opt-in VM flag, and Metro only bundles literal
   specifiers anyway. Replaced with guarded `require()`; the Android bundle and
   a debug APK both confirm the modules resolve.
3. **Mobile — would have shipped.** `messaging().requestPermission()` is a no-op
   on Android that resolves `AUTHORIZED` without prompting, so the app would have
   registered an FCM token that could never be delivered. The Android 13+ runtime
   request is now made explicitly via `PermissionsAndroid`.
4. **API — data leak.** The error handler built its response before the 5xx
   branch, so an unexpected server error could include a traceback in the JSON
   body. Fixed and covered by a test.
5. **Web — test quality.** The "renders each screen" test asserted only that the
   login button was gone, which is also true while a screen is still suspended
   behind the Suspense fallback. It now asserts each screen's heading.
6. **API — silent model degradation.** The artifact sidecar recorded the feature
   names but no format version and no checksum, so (a) the standalone package
   refused to read an API-trained artifact and (b) a modified `.pkl` was
   unpickled anyway. Both are fixed; a tampered artifact now degrades to
   rules-only scoring with a message instead of trusting the file.
7. **Cross-package contract, unasserted.** The API and the standalone trainer
   build the same 31 features in *different* orders. That is safe by design - the
   scorer projects the vector onto the order the artifact recorded - but nothing
   checked that the two still agreed on the *names*, so a rename on one side
   would have been silently dropped at scoring time. `test_feature_parity.py`
   now pins set equality and the artifact format version.

## Not verified

| Area | Why | What would close it |
| --- | --- | --- |
| iOS build and runtime | No macOS/Xcode in this environment | Run `npx react-native run-ios` on a Mac |
| Firebase sign-in end to end | Needs a Firebase project and `google-services.json` / plist | Add the files, sign in on a device |
| Push delivery | Same, plus a real FCM sender | Register a device, send from the Firebase console |
| Cloud backup to GCS / Drive | Needs bucket or OAuth credentials | Point `GCS_BUCKET` / Drive vars at a test bucket |
| Remote assistant | Needs a provider API key | Set `ASSISTANT_API_KEY` |
| Receipt OCR | Needs Google Services files and an Android device | Scan a receipt on device |
| Live database migration | `finance_ai` is read-only for this engagement | Rotate the credential, rehearse on a copy, then migrate under change control |
| Production model training | Live data has 9 transactions against a 50-row floor | Collect real history, or label a larger local set |
| Load / performance | No load-test environment | Run k6 or similar against a staging deploy |
| Browser/device matrix | Only the default jsdom and a debug APK here | Playwright/Cypress matrix, physical devices |

## Live data

`finance_ai` was never written to. It holds 5 users, 9 transactions, and 2
budgets; a pre-migration copy is kept at
`database/backup/finance_ai_backup_pre_migration.json` for reference. The exposed
`DB_PASSWORD` in the API `.env` was not read, copied, or used anywhere, and must
be rotated before any deployment.

## Dependency advisories

`npm audit` in the mobile project reports 5 transitive advisories after the
Axios upgrade to `1.20.0`. None are in application code, and no forced
downgrade was applied - Axios has shipped advisories at a higher version than
this one, so "downgrading to fix" is not a real mitigation. Re-check on the next
`npm audit` and review the advisory list rather than the count.

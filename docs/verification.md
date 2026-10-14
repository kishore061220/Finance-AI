# Verification Summary

## Baseline Test Results (actual, re-run this session)
- API (finance-ai-api): **306 passed** (pytest -q) - verified
- ML (finance-ai-ml): **81 passed** (pytest -q); API/backend feature-parity subset **10 passed** - verified
- Web (finance-ai-frontend): **104 passed / 5 files** (vitest run); typecheck + lint + build clean - verified
- Mobile (FinanceAI, repo root): **60 passed / 5 suites** (jest --no-coverage); `tsc --noEmit` clean; lint 24 warnings / 0 errors - verified
- Android (android/): `:app:assembleDebug` **BUILD SUCCESSFUL** (~19.8 MB APK) - verified
- Mobile Android JS bundle: `npm run bundle:android` **exit 0** (Metro wrote the bundle + 19 assets) - verified
- See [completion-audit.md](completion-audit.md) for the audit findings and fixes behind the API count.

## Firebase/Auth Changes
- Web: Removed dev-token path; Firebase-only session via `onIdTokenChanged`; project_id consistency check; updated tests with `firebaseMock`; 103 passed.
- Mobile: Removed dev-token path and `DEV_TOKEN_KEY`; Firebase-only; `onIdTokenChanged`; project consistency; updated mocks/tests; 58 passed.
- API: `/api/auth/config` returns `project_id`; dev-token endpoint remains but is reachable only when `ALLOW_DEV_AUTH=true` and Firebase is absent.

## Real Firebase E2E
- Android config: `android/app/google-services.json` for project `finance-fd3f3` /
  package `com.financeai` is in place (gitignored) and the debug APK builds with the
  Google Services plugin applied (`gradlew :app:assembleDebug` → BUILD SUCCESSFUL).
- API: `FIREBASE_PROJECT_ID=finance-fd3f3` set; token verification still requires a
  service account → real token verification is BLOCKED, not faked. Dev provider
  active only in this unconfigured state.
- Web: no `VITE_FIREBASE_*` env file present → real Web sign-in BLOCKED until
  supplied.
- Live MySQL `finance_ai` (9 users / 11 transactions / 3 budgets) read-only check
  PASS; `users.firebase_uid` and `users.email` both UNIQUE, matching provisioning.
- Re-verified this session: API pytest **306 passed**; ML pytest **81 passed**
  (parity subset 10 passed); Web vitest **104 passed** (+ typecheck, lint, build
  clean); Mobile jest **60 passed** (typecheck clean, lint 0 errors / 24 warnings);
  Android `assembleDebug` BUILD SUCCESSFUL; mobile `bundle:android` exit 0.

## Alembic Migrations - PASS (disposable DB)
- The live `finance_ai` database was never touched. A throwaway schema
  `finance_ai_migration_check` was created, migrated, reversed, re-migrated, and
  dropped in the same session.
- `alembic upgrade head` applied `0001 -> 0007` and produced every feature table
  plus `budgets_duplicate_archive`; `alembic_version` = `0007`.
- `alembic downgrade base` reversed the chain to the empty baseline with no error.
- `alembic upgrade head` applied cleanly a second time (`alembic_version` = `0007`).
- `alembic heads` = single head `0007`; `alembic history` linear.
- Offline `alembic upgrade --sql` is unsupported for this chain by design (0003
  calls `sa.inspect`), which is why a live disposable DB was used.

## Shared Backend + Database (T6) - PASS
A dedicated MySQL database (`finance_ai_e2e`) was created and migrated with the real
Alembic chain (`0001 -> 0007`), then the real FastAPI app was driven through two
independent HTTP sessions standing in for the Web and Mobile clients (plus a third
user for isolation). Script: `finance-ai-api/scripts/e2e_shared_backend.py`.
A hard guard refuses to run unless the target database is the dedicated `*_e2e`
database, so the live `finance_ai` database is never touched.

Result: **20/20 checks passed**, including:
- two sessions resolving to the same user id (shared identity);
- web writes a transaction -> mobile reads it; mobile writes a budget -> web reads it (shared rows, both directions);
- the transaction survives a web re-login (persisted in MySQL, not client memory);
- a second user cannot see the first user's transaction or budget (per-user isolation);
- the transaction row is read straight out of the shared MySQL database with the correct owner;
- the T7 feature endpoints (reports types/generate/history, assistant config/ask, family create/invite/members) all work against that same backend.

## Feature Coverage (T7) - PASS
- Web: `ReportsPage`, `FamilyPage`, `AssistantPage` implemented and wired into routes/nav; `endpoints.ts` `reportApi`/`assistantApi`/`familyApi` and `ReportRecord`/assistant response shapes corrected; typecheck + lint clean; 104 tests pass.
- Mobile: `ReportsScreen`, `FamilyScreen`, `AssistantScreen` implemented, wired into the `MoreStackNavigator` and the `More` hub rows; typed `reportApi`/`assistantApi`/`familyApi` and wire types added; `tsc --noEmit` clean; lint 24/0; 60 tests pass.

## ML (T8) - PASS
- Artifacts present: `finance-ai-api/ml_artifacts/fraud_model.json` (+ `.pkl`); random_forest `roc_auc 0.7577`, `avg_precision 0.0866`, `precision 0.0213`, `recall 0.3333`, `f1 0.0401`, `thr 0.5`, `rows_used 282982`.
- API `trainer.load()` reports `model_loaded`/`scoring_mode=combined`; scoring combines the model with the rule engine.
- ML suite covers training, comparison, dataset handling, and API/backend feature parity: 81 passed.

## Full Verification (T9)
- All unit suites green (API 306, ML 81, Web 104, Mobile 60); Web typecheck+lint+build clean; Mobile typecheck clean and lint 0 errors; Android `assembleDebug` BUILD SUCCESSFUL and `bundle:android` exit 0.
- Cross-client shared backend + MySQL proven by the 20/20 E2E above.
- Alembic chain proven reversible on a disposable DB (`upgrade head` -> `downgrade base` -> `upgrade head`).
- Real Firebase E2E remains BLOCKED (credentials absent) and is not simulated.

## Phase Results
- T1-T5: PASS
- T6 (shared backend + DB E2E): **PASS** (finance_ai_e2e, 20/20)
- T7 (Reports/Family/Assistant UI, Web + Mobile): **PASS**
- T8 (ML train/eval + inference): PASS
- T9 (end-to-end verification): PASS (real-Firebase path BLOCKED by missing credentials)
- T10 (report): PASS (this document + `docs/project-report.md`)
- Deferred functional gaps (loan `record_payment` UI, FCM refresh/sign-out/dead-token cleanup, family read-boundary tests): **PASS**; `can_view_all` and SMS body-hash dedup documented as intentional.

## Overall
Code changes complete and verified by the existing test suites plus a real
shared-database E2E. The only unmet item is the real-Firebase sign-in path, which
is blocked by absent credentials and is documented rather than fabricated.

# FinanceAI — final project report

Status: **complete and verified on this machine**, with the external-dependency
gaps listed in section 16 still open. Every number below was produced by a
command in [verification.md](verification.md), not estimated.

---

## 1. Executive summary

FinanceAI is a four-component personal-finance product delivered as one
repository: a FastAPI backend, a React web client, a React Native mobile client,
and a standalone fraud-model training package.

| Component | Stack | Surface | Tests |
| --- | --- | --- | --- |
| `finance-ai-api` | FastAPI, SQLAlchemy 2, Alembic, PostgreSQL | 95 OpenAPI operations | 255 passed |
| `finance-ai-frontend` | React 19, TypeScript, Vite, React Router, Vitest | 7 protected screens | 98 passed |
| `FinanceAI` | React Native, Firebase | Android (iOS code-complete) | 41 passed |
| `finance-ai-ml` | scikit-learn / XGBoost | offline training package | 65 passed |

459 tests pass in total. The web client lints, type-checks, and builds; the
mobile client type-checks, lints, bundles with Metro, and produces a debug APK.

Two findings were serious enough to call shipping defects and are documented in
section 15: the web build shipped an **empty application module**, and the mobile
app registered a **push token that could never be delivered**.

---

## 2. Scope delivered

- Multi-user finance tracking: transactions, budgets, categories, recurring items.
- Authentication and account lifecycle: registration, invite acceptance, login,
  refresh, password reset, profile.
- Analytics: dashboard aggregates, category and date-range reports, loan
  calculations.
- Forecasting with an honest data gate.
- Fraud scoring combining a deterministic rule engine with a trained model.
- Notifications and device token registration.
- Backup, checksum-verified restore preview, and transactional apply.
- Budget sharing and family member management.
- An AI assistant endpoint that is disabled unless configured.
- Receipt OCR plumbing that degrades gracefully without a device or Firebase.

Out of scope and not attempted: payment execution, bank aggregation, and
anything that writes to the live database.

---

## 3. Repository layout

```
Finance-AI/
├── finance-ai-api/          FastAPI backend (app/{routes,models,schemas,services,ml,core,utils}, alembic, tests)
├── finance-ai-frontend/     Web client (src/{pages,components,services}, tests)
├── FinanceAI/               React Native client (android/, ios/, src/, __tests__/)
├── finance-ai-ml/           Standalone fraud training package (finance_ai_ml/)
├── database/backup/         Pre-migration copy of the live database
├── docs/                    architecture, API contract, verification, this report
└── .github/workflows/       ci.yml, android-build.yml
```

Five placeholder directories (`finance-ai-admin`, `finance-ai-mobile-old`,
`screenshots`, `assets`, `datasets`) were confirmed empty and removed. `database`
was kept because it holds the live backup.

`.gitignore` files sit at the root and in each of the four components. The root
is **not** a Git repository yet, so this report and the docs are the handoff
record; there is no commit history to point at.

---

## 4. Backend

Thirteen route modules expose 92 operations, plus three app-level ones served
from `main.py` — 95 in the OpenAPI spec. Layering is strictly
route → service → model: routes do HTTP, services hold the rules, models hold the
schema. Business logic never lives in a route body.

| Module | Operations | Area |
| --- | --- | --- |
| `family` | 13 | members, invitations, shared budgets |
| `dashboard` | 10 | aggregates for the home screen |
| `loans` | 10 | amortisation and schedules |
| `notifications` | 10 | list, read state, device tokens |
| `auth` | 7 | registration, login, refresh, reset, invites |
| `transactions` | 7 | CRUD, filters, recurrence |
| `fraud` | 7 | scores, flags, review |
| `backups` | 7 | snapshot, list, preview, restore |
| `budgets` | 6 | per-category budgets and progress |
| `categorization` | 6 | category management |
| `ml` | 4 | training job and artifact status |
| `reports` | 3 | date-range and category reports |
| `assistant` | 2 | AI assistant |
| `meta` (`main.py`) | 3 | `/`, `/health` |

Twelve SQLAlchemy models and twelve service modules back these. Money is
`Decimal` end to end and stored as `Numeric`; no float ever touches a balance.
`utils/money.py` centralises rounding so that a sum of many small amounts cannot
drift.

---

## 5. Database and migrations

Six Alembic revisions build the schema. They were exercised for upgrade,
downgrade, and `alembic check` (no pending autogenerate diff), including a full
round trip back to `0005` with data intact.

`Base.metadata.create_all()` appears **only** in isolated test setup. Production
schema changes go through Alembic, so a deploy cannot silently produce a schema
that differs from the one the migrations describe.

---

## 6. Authentication and authorization

Bearer tokens are verified server-side and the identity is taken **only** from
the verified token — never from a request body or query parameter. Every list,
filter, and mutation is scoped to the authenticated user, and the suite asserts
that user A cannot read or modify user B's rows.

Firebase is the production provider. A development provider exists behind
`/api/auth/dev-token` and is available only when `ALLOW_DEV_AUTH=true` **and** no
Firebase configuration is present, so it cannot be reached by accident in a
deployed environment.

A 5xx response no longer includes a traceback: the handler used to build its body
before the error branch, which could leak internals. This was found by the test
suite, not review.

---

## 7. Fraud detection

Two independent signals, deliberately not merged into one number:

1. **Rule engine** — deterministic, always available, tunable.
2. **Model** — trained, blended at 70/30 in favour of the rules.

The rules never get overwritten by the model. With no artifact on disk, scoring
returns `status: "rules_only"` and the rule score unchanged, so the feature
degrades instead of breaking.

Training refuses to run below `MIN_TRAIN_ROWS=50` rows or
`MIN_POSITIVE_LABELS=5` positives and returns a structured `insufficient_data`
result describing the shortfall. With 9 live transactions this is the correct
outcome; no metric is invented to fill the gap.

The artifact is a `.pkl` plus a JSON sidecar recording the feature names, an
artifact format version, and a SHA-256 checksum. `trainer.load` verifies the
checksum **before** unpickling and falls back to rules-only scoring on failure —
a modified model file is refused rather than executed.

---

## 8. Feature contract across packages

The API and the standalone trainer both use 31 features, in deliberately
different orders: `app/ml/features.py` builds them semantically,
`finance_ai_ml/features.py` declares `CANONICAL_FEATURES` alphabetically.

This is safe because scoring never assumes positions. The sidecar records the
order the model was trained with, and `score_transaction` projects the vector
onto those names. A model trained by either package scores correctly.

What must not drift is the **set** of names — a rename on one side alone is
silently dropped at scoring time, since the projection substitutes zero.
`app/tests/test_feature_parity.py` asserts set equality and that the artifact
format versions match; CI runs it from the ML job.

---

## 9. Forecasting

Below three calendar months of history the endpoint returns
`status: "insufficient_data"` with `available_months`, `required_months`, and
`months_needed`. Above the threshold it returns `status: "predicted"`. The
three-month boundary is covered by tests in both directions. No forecast is
returned with a confidence the data cannot support.

---

## 10. Backup and restore

Restore is the most dangerous operation in the product and is built to be hard
to get wrong:

- Backups are checksummed (`SHA-256`) when recorded.
- Restore is **previewed first**: the caller sees the exact changes.
- Application requires `confirm=true`.
- It is user-scoped and transactional.
- It is idempotent — re-running does not double-apply.
- A malformed amount is rejected during apply, not coerced.

Nothing here was executed against the live database. See section 16.

---

## 11. Web client

Seven protected screens, lazy-loaded behind a session check. An anonymous
visitor cannot reach any of them, and an authenticated one is never stranded on
the login form.

The Axios client sets `Authorization`, clears tokens on 401, and normalises
errors without leaking 5xx internals.

The app shell is verified in the production bundle: the main chunk contains
`"Restoring your session"`. This check exists because of the defect in
section 15 — a build that succeeds can still contain no application.

---

## 12. Mobile client

Session restoration, sign-in/sign-out for both providers, an explicit
`unconfigured` provider state, and an app-shell render with the full navigator
are all covered.

Native modules are loaded with guarded literal `require()`. This is deliberate
and is documented in code: Metro only bundles literal specifiers, and Jest
cannot execute dynamic `import()` without `--experimental-vm-modules`.

Verified end to end on Windows: `tsc --noEmit` clean, lint 0 errors (24
inline-style warnings), 41 tests passing, a Metro Android production bundle, and
`:app:assembleDebug` producing
`android/app/build/outputs/apk/debug/app-debug.apk`.

Permissions follow platform reality: image picking needs no camera permission on
Android, and Android 13+ notification permission is requested through
`PermissionsAndroid` because `messaging().requestPermission()` is a no-op there.

---

## 13. Standalone ML package

`finance-ai-ml` imports no backend code and installs its own dependencies, so it
can be used offline. It trains, evaluates, exports, and verifies artifacts, and
`export_to_backend` writes into the directory the API's trainer reads.

`app/ml/features.py` is deliberately free of pandas and scikit-learn imports at
module level, which is what lets the backend import it — and what lets the
parity test run with only the ML job's dependencies installed.

---

## 14. Testing and verification

| Component | Command | Result |
| --- | --- | --- |
| API | `pytest -q` | 255 passed |
| ML | `pytest -q` | 65 passed |
| Web | `npm run typecheck` / `lint` / `build` | clean |
| Web | `npm test -- --run` | 98 passed |
| Mobile | `npx tsc --noEmit` / `lint` | clean / 0 errors |
| Mobile | `npm test -- --runInBand` | 41 passed |
| Mobile | `gradlew :app:assembleDebug` | APK produced |
| Mobile | `react-native bundle --platform android` | bundle produced |

Coverage is behavioural rather than percentage-driven: authorization
boundaries, ownership scoping, backup/restore paths, the prediction gate, token
expiry, artifact integrity, and the cross-package feature contract. Full detail
and the defect list are in [verification.md](verification.md).

CI (`.github/workflows/ci.yml`) runs four jobs on every push — API, ML, web,
mobile — including a Metro bundle check, because no JavaScript test can prove the
app bundles. `android-build.yml` is separate and runs on `main`, since a native
build needs a JDK, the Android SDK, and several minutes.

---

## 15. Defects found and fixed

These are the argument for running the suites instead of assuming they pass.

1. **Web, shipping-blocking.** A 0-byte `src/App.jsx` shadowed `src/App.tsx`
   (`.jsx` resolves before `.tsx`). Every build and test imported an empty
   module; the production bundle contained no application. Fixed by deleting the
   file. The bundle now contains the app shell, and CI checks for it.
2. **Mobile, would have shipped.** `messaging().requestPermission()` is a no-op
   on Android and resolves `AUTHORIZED` without prompting, so the app would have
   registered an FCM token that could never be delivered. Now requested
   explicitly via `PermissionsAndroid`.
3. **API, data leak.** The error handler built its response before the 5xx
   branch, so an unexpected error could include a traceback in the response body.
   Fixed and tested.
4. **API, silent model degradation.** The artifact sidecar carried no format
   version and no checksum, so the standalone package could not read an
   API-trained artifact, and a modified `.pkl` was unpickled anyway. Now the
   sidecar is self-describing and a tampered artifact degrades to rules-only.
5. **Web, test quality.** The "renders each screen" test only asserted the login
   button was gone — also true while a screen was still suspended behind the
   Suspense fallback. It now asserts each screen's heading.
6. **Cross-package contract, unasserted.** Nothing checked that the API and the
   standalone trainer still agreed on the 31 feature *names*. Now pinned.

---

## 16. Risks, limitations, and next steps

### Blocked by missing external dependencies

| Area | Needs |
| --- | --- |
| iOS build and runtime | macOS with Xcode — unavailable on this Windows host |
| Firebase sign-in end to end | A Firebase project plus `google-services.json` / plist |
| Push delivery | The same, plus a real FCM sender |
| Cloud backup to GCS / Drive | Bucket or OAuth credentials |
| Remote assistant | A provider API key |
| Receipt OCR | Google Services files and an Android device |

These are configuration gaps, not code gaps. Each path degrades safely when
unconfigured rather than failing at import or startup.

### Security items requiring action before deployment

1. **Rotate the database password.** A `DB_PASSWORD` is present in plaintext in
   `finance-ai-api/.env`. It was never read, copied, or used during this
   engagement, but its presence in a file that may have been shared is the
   reason to rotate it.
2. **Move secrets out of `.env`** into a secret manager. `.gitignore` files now
   exist at the root and in every component, and were verified with
   `git check-ignore`: `.env`, `.env.*`, `google-services.json`,
   `GoogleService-Info.plist`, `ml_artifacts/`, `*.pkl`, and build output are all
   ignored while `.env.example` and all source remain tracked. Keep it that way
   before this tree goes under version control.
3. **Live migration.** `finance_ai` was never written to. It holds 5 users, 9
   transactions, and 2 budgets, with a pre-migration copy at
   `database/backup/finance_ai_backup_pre_migration.json`. That copy is
   deliberately git-ignored — it is production data. Rehearse the migration on a
   copy, then run it under change control with the rotated credential.

### Known limitations

- The fraud model cannot be trained on current data (9 rows against a 50-row
  floor). It needs real history or a larger labelled set. Until then scoring is
  rules-only, which is a working product path.
- The mobile project reports 5 transitive `npm audit` advisories. None are in
  application code, and no forced downgrade was applied — Axios has shipped
  advisories at higher versions, so "downgrading to fix" would not be a real
  mitigation. Review the advisory list, not the count.
- No load or performance testing was performed; there is no staging environment.
- Browser testing is limited to jsdom. A Playwright matrix and physical devices
  are the next meaningful investment after the external credentials above.
- Housekeeping: `finance-ai-api/` contains both `.venv/` and a stray `venv/`.
  The documented interpreter is `.venv\Scripts\python.exe`; `venv/` is unused and
  can be deleted.

### Recommended order of work

1. Rotate the database credential and move secrets to a secret manager.
2. Put the tree under version control with a correct `.gitignore`.
3. Run `ci.yml` and `android-build.yml` on the new remote to confirm parity with
   local results.
4. Add a Firebase project and close the sign-in, push, and OCR gaps.
5. Rehearse and then execute the live migration under change control.
6. Collect labelled transaction history to enable real fraud training.

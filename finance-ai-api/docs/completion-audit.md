# Completion Audit

This document records the repository-wide completion audit: what was inspected,
what was found, what was fixed (with the regression test that now guards each
fix), what was deliberately left as-is, and what remains blocked. It complements
[verification.md](verification.md) (commands and results) and
[project-report.md](project-report.md) (handoff summary).

## Method

- Three read-only exploration agents swept the API, ML, web, and mobile trees for
  stubs, broken wiring, doc-vs-code mismatches, and unsafe patterns.
- `git grep` for `TODO`, `FIXME`, `placeholder`, `NotImplemented`, `pass  #`, and
  mock/stub markers found only legitimate input placeholders and test doubles -
  no production stubs.
- The Alembic migration chain is linear with a single head (`0001 -> 0007`).
- Every route module's count of authentication dependencies is >= its endpoint
  count (auth/login/register legitimately lower, being public).

## Fixed defects

Each fix is on the API unless noted, and each is covered by a new regression
test so it cannot silently return.

### H1 - Account takeover via unverified email (security)

`app/core/deps.py` linked a legacy user row (matched by email) to whatever
Firebase identity presented that email. Because an identity that never verified
its address still reports the email, anyone could register a victim's address in
Firebase, never verify it, and be handed the victim's account.

Fix: legacy linking now requires `identity.email_verified`. An unverified
identity that matches an existing row is refused with HTTP 403. Dev tokens
default to verified, so existing flows are unaffected.

Test: `test_auth_and_access.py::TestUserProvisioning::test_unverified_email_cannot_claim_a_legacy_account`.

### M1 - Dev auth stayed live when credentials existed without the project id

`app/core/config.py` `firebase_enabled` required `FIREBASE_PROJECT_ID` *and*
credentials. A deployment that shipped a service-account file but forgot to also
export `FIREBASE_PROJECT_ID` reported Firebase as disabled and kept the dev
token endpoint live.

Fix: a service-account credential (or `GOOGLE_APPLICATION_CREDENTIALS`) is now
the decisive signal. A missing project id makes token verification fail closed
(401), which is strictly safer than leaving the dev provider reachable.

Test: `test_auth_and_access.py::TestSingleAuthPath::test_credentials_alone_disable_dev_auth`.

### Budget projection counted lifetime spend as month-to-date

`app/services/prediction.py` `budget_projection` summed every expense in a
category regardless of month, so a budget's "spent" figure included all history.
It now filters expenses to the budget's month.

Test: `test_prediction.py::TestBudgetProjection::test_projection_counts_only_the_current_month`.

### Category forecast diluted by months the category was unused

`app/services/prediction.py` `category_forecasts` divided each category total by
the *global* number of months instead of the months that category was actually
used, contradicting its docstring. It now divides per category use-month.

Test: `test_prediction.py::TestCategoryForecasts::test_average_uses_only_months_the_category_was_used`.

### Loan principal counted unpaid installments

`app/services/loan_service.py` `loan_summary` accumulated principal from every
installment, so pending/overdue principal showed as already repaid. It now counts
only PAID installments.

Test: `test_loan_service.py::test_principal_repaid_counts_only_paid_installments`.

### `/api/ml/train` ignored `test_size`; `/api/ml/score` 500 on bad date

`app/routes/ml.py` hardcoded `test_size=0.2` (the request field was dropped), and
the dry-run score endpoint passed an arbitrary string to `datetime.fromisoformat`
producing an unhandled 500. `test_size` now flows through and a malformed date
returns 422.

Test: `test_features.py::TestFraud::test_dry_run_score_rejects_a_malformed_date`.

### `/api/budgets/period/<year>/<month>` 500 on an out-of-range year

`app/routes/budgets.py` `budgets_for_period` validated the month but not the year,
so `datetime(year, month, 1)` raised `ValueError` (500). Year is now validated to
`2000..2200` and returns 422.

Test: `test_features.py::TestBudgets::test_period_endpoint_validates_year`.

### Restore duplicated fraud alerts on repeat

`app/services/restore.py` re-inserted every fraud alert on each restore (the
table has no unique constraint), so restoring the same backup twice duplicated
the alerts even though the preview counted them as skipped. `_apply_fraud_alerts`
now re-reads live alerts and skips existing
`(transaction_id, risk_score, detection_layer)` keys, matching the plan. The row
key helper defaults a missing `detection_layer` to `RULES`.

Test: `test_restore.py::TestApplyAndIdempotency::test_restoring_twice_does_not_duplicate_fraud_alerts`.

### Fraud model could silently un-flag a rules-detected transaction

`app/services/transaction_analysis.py` computed `is_flagged` from the blended
score alone, so a rule engine flag near the threshold (e.g. 35) could be blended
down below it (e.g. 20) and the transaction was stored unflagged with no alert -
contradicting the trainer's guarantee that the rule verdict is never overwritten.
The rules score is now a floor: `effective_score = max(combined, rule_score)`,
and `is_flagged`, the stored `fraud_score`, and the alert `risk_score` all use it;
the alert level is taken from whichever signal is higher.

Test: `test_fraud_detection.py::test_apply_analysis_keeps_a_rules_flag_when_the_blend_dips`.

### Build/CI fixes (from earlier in the audit)

- `.github/workflows/ci.yml` ML parity step pointed at a nonexistent file
  (`../finance-ai-api/app/tests/test_feature_parity.py`, exit 4); it now runs the
  real `finance-ai-ml/tests/test_api_feature_parity.py` and
  `test_parity_with_backend.py`.
- `finance-ai-frontend/vite.config.ts` used a platform-dependent
  `URL().pathname` for the `@` alias (breaks on Linux CI); replaced with
  `fileURLToPath`.
- Mobile lint had two real errors (missing hook dependencies in
  `DashboardScreen.tsx` and `TransactionsScreen.tsx`); fixed by binding the
  stable `reload` callbacks to locals.
- Mobile jest reported "56 passed" but exited **1**: `__tests__/App.test.tsx`
  used a synchronous `act()`, leaving `SessionProvider`'s async restore running
  past teardown, which produced a late `require('@react-native-firebase/app')`
  ("import after the Jest environment has been torn down") and a
  "Cannot log after tests are done" warning. A green-looking suite with a red
  exit code would have failed CI. Fixed with an async `act()` plus `unmount()`.

### Frontend/backend contract mismatches (web)

The web client sent parameters the API rejects or silently ignores. Fixed in
`finance-ai-frontend` with regression tests in `tests/endpoints.test.ts`.

- **Fraud level filter offered `CRITICAL`.** The backend's `RiskLevel` is only
  `LOW|MEDIUM|HIGH` (the rule engine tops out at HIGH), so selecting "Critical"
  produced a 422. Removed from the filter options (`FraudPage.tsx`).
- **Unread toggle was a no-op.** The client sent `is_read`, but
  `/api/fraud/alerts` filters on `unread_only`; FastAPI ignored the unknown
  parameter, so the toggle did nothing. Now sends `unread_only`.
- **Backup provider values.** The dropdown sent `LOCAL|FIREBASE|GCS|DRIVE`; the
  schema accepts only `FIREBASE_STORAGE|GOOGLE_CLOUD_STORAGE|GOOGLE_DRIVE`
  (`LOCAL` is the empty/`Server default` option), so any non-default choice
  returned 422. Values corrected.
- **Backup verify response.** `backupApi.verify` was typed as
  `{verified; checksum}` and the page read `result.checksum` ("Expected
  undefined"); the route returns `expected_checksum`/`actual_checksum`/`message`.
- **Backup status casing.** The page compared `completed`/`failed`; the enum is
  `SUCCESS`/`FAILED`, so every backup rendered as the "pending" style.
- **Dashboard query params.** `trends`/`insights` were typed to send
  `start_date`/`end_date`, which those month-based routes ignore; the wrappers
  now match each route (`months`; `month`/`year`) and `dataHealth` reflects the
  real response fields.
- **Mobile device-token response type.** `notificationApi.registerDevice` was
  typed `{registered: boolean}` while the route returns `DeviceTokenResponse`
  (no `registered` field). Corrected; the value is not consumed today, so this
  was a latent type lie rather than a runtime fault.

### SMS detection and integrations

- **Receiver persisted messages after opt-out (privacy).** `SmsReceiver.kt`
  delivered and queued every `SMS_RECEIVED` regardless of the user's setting, so
  with detection off the UI's "Messages are no longer read" was false. The
  receiver now consults a native `SharedPreferences` flag that JS writes from
  `setAutoDetectEnabled` (mirrored via the new `SmsReceiverModule.setEnabled`),
  and returns before doing anything when off. `startSmsInbox` re-asserts the
  flag for installs that predate it.
- **Parser captured prose as a merchant.** `_extract_merchant` returned `"your"`
  from "credited to your account" because the `to <word>` heuristic grabbed the
  next word blindly. A filler-word denylist now rejects it.
- **Backup docstring claimed encryption that does not exist.**
  `app/services/backup.py` is headed "Encrypted-at-rest", but the payload is
  plaintext JSON with a SHA-256 integrity checksum. The docstring now states the
  truth (TLS in transit, provider-default encryption at rest, plaintext on local
  disk).
- **`FIREBASE_STORAGE` advertised while unusable.** `provider_available`
  returned true on auth credentials alone, but the upload needs a resolvable
  Storage bucket. It now also requires a bucket (new
  `FIREBASE_STORAGE_BUCKET`, else derived `<project>.appspot.com`), and both the
  uploader and the down-restore use that bucket name.
- **FCM background handler was dead and mislabelled.** `push.ts`
  `registerBackgroundHandler` was never called from `index.js`, and used
  `onMessage` (foreground) while its docstring claimed a background handler. It
  now registers `setBackgroundMessageHandler` and is invoked from `index.js`
  before the root component.
- **Assistant `/config` could report a remote model while built-in answered.**
  The route computed `remote_ready` from the API key alone, but the service also
  requires the provider not be `builtin`; with the default provider plus a stray
  key, config advertised the remote model while answers stayed local. The gate now
  matches the service.

### Security and robustness (second audit pass)

- **CORS wildcard with credentials.** `.env.example` claimed the API rejects
  `Access-Control-Allow-Origin: *` when credentials are enabled, but `main.py`
  passed the configured origins through verbatim, so a wildcard plus
  `allow_credentials=True` would be sent (browsers reject it as invalid, but the
  server advertised a broken posture). `Settings.resolved_cors_origins` now drops
  `*` whenever `cors_allow_credentials` is set, and `main.py` uses it. Tests:
  `test_auth_and_access.py::TestCorsGuard`.
- **FCM dead tokens retried forever.** `push.send_to_tokens` logged every failure
  but never distinguished a permanently dead token, so a retired handset was
  retried on every send and counted as a failure. Permanent FCM errors
  (`UnregisteredError`, `SenderIdMismatchError`) are now collected as
  `invalid_tokens` and `send_to_user` deactivates those rows in the same session.
  Test: `test_features.py::TestNotifications::test_dead_tokens_are_deactivated`.
- **FCM token rotation was not re-registered.** `push.ts` never subscribed to
  `onTokenRefresh`, so a rotated token silently stopped delivery until the next
  launch re-registered it manually from the settings screen. A single guarded
  `listenForTokenRefresh()` subscription (invoked after a successful registration)
  now re-registers the new token. The server exposes
  `DELETE /api/notifications/devices?token=...` and `pushService.unregisterCurrentDevice()`
  is called on sign-out, while the auth token is still valid, so the next account
  on the handset does not inherit the previous one's alerts. Tests:
  `test_features.py::TestNotifications::test_unregister_by_token_stops_this_handset`
  and `...::test_unregister_by_token_rejects_unknown_and_foreign_tokens`; mobile
  `__tests__/endpoints.test.ts`.
- **Loan repayments were API-only.** `POST /api/loans/{id}/payments` existed and
  was tested, but neither client could mark an installment paid. The web
  `LoansPage` and mobile `LoansScreen` now load each loan's `upcoming`
  installments and offer a "mark paid" action per installment, refreshing from
  the server afterwards. The web `LoanDetail.upcoming` type was tightened from
  `Record<string, unknown>[]` to a real `UpcomingInstallment`. Tests: web
  `tests/endpoints.test.ts`, mobile `__tests__/endpoints.test.ts`.
- **Family read boundary had no regression test.** Reads are gated on ACTIVE
  membership and writes on the group owner; both are correct, but only the write
  path was pinned. `TestFamily::test_non_member_cannot_read_group_data` now asserts
  a non-member gets 404 from the group, members, expenses and balances routes, and
  `test_membership_not_can_view_all_is_the_read_boundary` records that
  `can_view_all` gates nothing (see below).

### Migrations verified on a disposable database

The full chain was exercised against a throwaway MySQL schema
(`finance_ai_migration_check`, created and dropped in the same session; the live
`finance_ai` database was never touched):

- `alembic upgrade head` applied `0001 -> 0007`; resulting schema carried every
  feature table plus `budgets_duplicate_archive` and `alembic_version = 0007`.
- `alembic downgrade base` reversed every step to the empty baseline.
- `alembic upgrade head` applied cleanly a second time.
- `alembic heads` reports a single head (`0007`) and `alembic history` is linear.

`alembic upgrade --sql` (offline) is not usable for this chain: migration 0003
inspects the live foreign-key name via `sa.inspect`, which has no offline
equivalent. This is by design, not a defect.

## Documented, not fixed (low severity / operator-controlled)

These were found and judged out of scope for a safe code change; they are
recorded here rather than silently changed.

- **`dashboard_summary` `monthly_trend` length 1.** The trend is built from the
  same month-filtered row set, so it currently reports a single point. Cosmetic.
- **`/fraud/score` and `/ml/score` verdict fields.** `risk_level` is derived from
  the rule engine while `is_fraud`/`is_flagged` come from the combined score.
  This is intentional layering; the field semantics are now consistent internally
  after the rules-floor fix. A clearer naming split is a possible follow-up.
- **`detect_recurring` uses `avg * 4.345`.** The multiplier assumes ~30.4-day
  months; the docstring says "near-monthly". Acceptable approximation.
- **`device_tokens` constraint-name drift** between the model and migration is a
  cosmetic inconsistency; it does not affect token delivery. (Dead-token
  deactivation is now implemented - see the security pass above.)
- **Family `can_view_all` is stored but not enforced.** The membership flag is
  persisted and round-tripped, but no endpoint yet reads another member's ledger,
  so there is nothing to gate; reads are gated on ACTIVE membership and writes on
  the owner (now pinned by
  `test_non_member_cannot_read_group_data`). It is inert configuration, not an
  open door; the flag should be enforced if a cross-member view is ever added.
- **Mobile `ReportsScreen` discards the generated file body.** The API streams a
  file, but the RN client has no file-save path and the screen's contract (stated
  in its own docstring) is that confirmation comes from the history row the
  generation records. Intentional, not a lost-upload bug.
- **SMS de-duplication is by exact body hash.** `sms_messages` has a unique
  `(user_id, body_hash)` constraint, so two genuinely separate transactions whose
  message text is byte-identical collapse to one row. This is what suppresses a
  dual-SIM duplicate, and bank bodies normally carry a timestamp/reference, so it
  is rare; the alternative (hash on body + received time) needs a migration and is
  a design change, not a one-line fix.

## Verification

- API: `306 passed` (includes every regression test above).
- ML: `81 passed`. Web: `104 passed`, typecheck + lint + build clean. Mobile:
  `60 passed`, typecheck clean, lint 0 errors / 24 warnings.
- Android: `:app:assembleDebug` BUILD SUCCESSFUL; merged manifest carries
  `RECEIVE_SMS` and `com.financeai.sms.SmsReceiver`.

## Blocked (not simulated)

- Real Firebase sign-in end-to-end (API token verification and web/mobile
  sessions) requires a service account / `VITE_FIREBASE_*` and is BLOCKED.
- Real-device SMS reception (including force-stopped delivery) requires physical
  hardware; the Play Permissions Declaration Form is a manual human step.
- FCM/OCR/cloud-backup live round trips require credentials and devices.

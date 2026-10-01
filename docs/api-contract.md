# API contract

Source of truth: the running application's OpenAPI schema
(`app.openapi()["paths"]`). The inventory below is generated from it, not
hand-maintained, so it cannot drift from the code without a regeneration.

Base URL in development: `http://127.0.0.1:8000`. Every endpoint below except
`/`, `/health`, `/api/info`, and `GET /api/auth/config` requires
`Authorization: Bearer <token>`.

## Endpoint inventory (95 operations)

```
GET    /
GET    /api/info
GET    /health

GET    /api/auth/config
GET    /api/auth/me
GET    /api/auth/profile
PATCH  /api/auth/profile
POST   /api/auth/logout
POST   /api/auth/refresh
POST   /api/auth/dev-token

GET    /api/transactions
POST   /api/transactions
GET    /api/transactions/recent
GET    /api/transactions/{transaction_id}
PATCH  /api/transactions/{transaction_id}
DELETE /api/transactions/{transaction_id}
POST   /api/transactions/bulk

GET    /api/budgets
POST   /api/budgets
GET    /api/budgets/period/{year}/{month}
GET    /api/budgets/{budget_id}
PATCH  /api/budgets/{budget_id}
DELETE /api/budgets/{budget_id}

GET    /api/dashboard
GET    /api/dashboard/summary
GET    /api/dashboard/categories
GET    /api/dashboard/trends
GET    /api/dashboard/insights
GET    /api/dashboard/recurring
GET    /api/dashboard/merchants
GET    /api/dashboard/daily
GET    /api/dashboard/health
GET    /api/dashboard/prediction

GET    /api/categorization/categories
POST   /api/categorization/predict
POST   /api/categorization/sms/parse
POST   /api/categorization/sms/commit
POST   /api/categorization/ocr/parse
POST   /api/categorization/ocr/commit

GET    /api/fraud/alerts
GET    /api/fraud/alerts/{alert_id}
PATCH  /api/fraud/alerts/{alert_id}
POST   /api/fraud/alerts/{alert_id}/read
POST   /api/fraud/alerts/{alert_id}/dismiss
GET    /api/fraud/analyze/{transaction_id}
GET    /api/fraud/summary

GET    /api/loans
POST   /api/loans
GET    /api/loans/portfolio
GET    /api/loans/{loan_id}
PATCH  /api/loans/{loan_id}
DELETE /api/loans/{loan_id}
GET    /api/loans/{loan_id}/payments
POST   /api/loans/{loan_id}/payments
GET    /api/loans/{loan_id}/prepayment
POST   /api/loans/emi/calculate

GET    /api/family
POST   /api/family
GET    /api/family/{group_id}
PATCH  /api/family/{group_id}
DELETE /api/family/{group_id}
GET    /api/family/{group_id}/members
POST   /api/family/{group_id}/members
DELETE /api/family/{group_id}/members/{member_id}
GET    /api/family/{group_id}/expenses
POST   /api/family/{group_id}/expenses
GET    /api/family/{group_id}/expenses/{expense_id}/splits
GET    /api/family/{group_id}/balances
POST   /api/family/{group_id}/settle

GET    /api/notifications
POST   /api/notifications
POST   /api/notifications/read-all
POST   /api/notifications/{notification_id}/read
DELETE /api/notifications/{notification_id}
GET    /api/notifications/unread-count
GET    /api/notifications/devices
POST   /api/notifications/devices
DELETE /api/notifications/devices/{device_id}
POST   /api/notifications/devices/test

GET    /api/backups
POST   /api/backups
GET    /api/backups/providers
GET    /api/backups/{backup_id}
POST   /api/backups/{backup_id}/verify
GET    /api/backups/{backup_id}/restore/preview
POST   /api/backups/{backup_id}/restore

GET    /api/reports
GET    /api/reports/types
POST   /api/reports/generate

GET    /api/ml/status
GET    /api/ml/train/report
POST   /api/ml/train
POST   /api/ml/score

GET    /api/assistant/config
POST   /api/assistant
```

## Contracts the clients depend on

These are the places where a plausible-looking guess would have broken a client,
so they are pinned explicitly.

### `GET /api/auth/config`

```json
{
  "provider": "firebase | dev | unconfigured",
  "firebase_enabled": true,
  "registration_enabled": true,
  "app_env": "production"
}
```

Both clients call this before rendering sign-in. `provider: "unconfigured"` is a
real state, not an error: it means neither Firebase nor development auth is set
up, and the UI says so instead of offering a sign-in that cannot work.

### `POST /api/auth/dev-token`

Returns **404** unless `ALLOW_DEV_AUTH=true` *and* Firebase is not configured.
This is deliberate: a Firebase deployment must not be reachable through the
local token endpoint.

### `GET /api/dashboard`

One aggregated read: totals, category breakdown, top merchants, budget progress,
monthly trend, insights, fraud summary, and recurring items. Accepts `month` and
`year`. This is what the dashboard screen uses - it does not fan out to the
narrower reads below it.

The narrower reads exist as separate endpoints and are all part of the same
router: `/summary`, `/categories`, `/trends`, `/insights`, `/recurring`,
`/merchants`, `/daily`, `/health`, `/prediction`. Clients should prefer the
aggregated route unless they need one slice.

### `GET /api/fraud/alerts`

Filters are `risk_level` (`LOW` / `MEDIUM` / `HIGH`), `unread_only`,
`include_dismissed`, `start_date`, `end_date`, `sort`, and `limit` / `offset`.
Note this is offset pagination, not `page` / `page_size` - the two styles are
both in the API, so mixing them up is an easy mistake.

## Conventions

- **Money** is serialised as a decimal string, never a float.
- **Dates** are ISO-8601. Query bounds use `YYYY-MM-DD`.
- **Errors** carry `detail` with a human-readable sentence.
- **Pagination** is `page` / `page_size` with `total` and `pages` in the body on
  the transaction and budget lists; the fraud alert list uses `limit` / `offset`
  and returns `total` with `by_level` counts.
- **Ownership** is derived from the bearer token. No endpoint accepts a user id
  from the client.

### `GET /api/dashboard/prediction`

Requires three calendar months of expense history. Below the threshold, HTTP 200
with:

```json
{
  "status": "insufficient_data",
  "message": "...",
  "prediction": null,
  "required_months": 3,
  "available_months": 1,
  "months_needed": 2,
  "observed_average": "900.00",
  "history": [],
  "categories": [],
  "budget_projection": []
}
```

A produced forecast is `status: "predicted"` with a populated `prediction`.
Clients key off `status`, never off the presence of the object.

### `GET /api/loans/portfolio`

```json
{
  "loan_count": 2,
  "active_count": 1,
  "total_outstanding": "125000.00",
  "total_monthly_emi": "9400.00",
  "next_due_date": "2026-10-12",
  "loans": []
}
```

### Categorization

`POST /api/categorization/sms/parse` and `.../ocr/parse` return parsed fields for
review; the matching `/commit` endpoint persists them. The parse response has no
top-level category - the client shows an editable category field rather than
pretending one was decided. Category suggestions arrive with the prediction
payload, and the user confirms before anything is written.

### Fraud features

The 31 fraud features are shared with the standalone trainer in
`../finance-ai-ml`, and the two sides order them **differently on purpose**:

- `app/ml/features.py` builds a vector in semantic order (time → weekday →
  amount → flags).
- `finance_ai_ml/features.py` declares `CANONICAL_FEATURES` alphabetically.

That is safe because the artifact records its own order:
`trainer.save` writes `feature_names` into `fraud_model.json`, and
`trainer.score_transaction` projects the vector onto those names
(`row.get(name, 0.0) for name in feature_names`) rather than assuming a
position. A model trained by either package therefore scores correctly.

What must never drift is the **set** of names. A rename on one side only is
dropped silently at scoring time - `row.get(name, 0.0)` substitutes zero and the
model degrades with no error. `finance-ai-api/app/tests/test_feature_parity.py`
asserts set equality between the two implementations and runs in CI from the ML
job.

### `GET /api/ml/status` and training refusal

Training refuses to run below `MIN_TRAIN_ROWS = 50` or `MIN_POSITIVE_LABELS = 5`
and reports why, rather than fitting a model to noise.

### `GET /api/backups/{backup_id}/restore/preview` and `.../restore`

The preview returns the exact changes that would be applied - counts of inserts,
updates, and unchanged rows, plus any conflicts. `POST .../restore` requires
`confirm=true` and applies nothing without it.

## Conventions

- **Money** is serialised as a decimal string, never a float.
- **Dates** are ISO-8601. Query bounds use `YYYY-MM-DD`.
- **Errors** carry `detail` with a human-readable sentence.
- **Pagination** uses `page` / `page_size` with `total` and `pages` in the body.
- **Ownership** is derived from the bearer token. No endpoint accepts a user id
  from the client.

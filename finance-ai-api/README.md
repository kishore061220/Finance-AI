# FinanceAI API

FastAPI backend for the FinanceAI personal-finance suite: authentication,
transactions, budgets, fraud scoring, loans, backups, notifications, and the
spending forecast.

## Stack

| Concern | Choice |
| --- | --- |
| API framework | FastAPI `0.141.1`, ASGI via `uvicorn[standard]` |
| ORM | SQLAlchemy `2.0.52` (async engine) |
| Migrations | Alembic `1.20.0` |
| Database | MySQL / MariaDB (`PyMySQL`) |
| Auth | `python-jose` bearer tokens + `passlib[bcrypt]` hashes |
| Identity provider | Firebase Admin SDK, with a local development-token mode |
| ML | `scikit-learn` + `xgboost`, `numpy`, `pandas` |

## Layout

```
app/
  core/          configuration, security primitives, dependency wiring
  database/      engine, session factory
  models/        SQLAlchemy models (imported for their side effect in main.py)
  schemas/       Pydantic request/response models
  routes/        one router per resource group
  services/      business logic (restore, backup, prediction, fraud scoring)
  ml/            feature engineering - 31 features, semantic order
  utils/         shared helpers
  tests/         pytest suite
alembic/         migration history
```

## Running locally

```powershell
python -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements.txt
Copy-Item .env.example .env      # then fill in the values below
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000
```

Health check: `GET /health`. Interactive API docs: `http://localhost:8000/docs`.

### Migrations are explicit

`main.py` deliberately does **not** call `Base.metadata.create_all()` and does
not run migrations on startup. Creating tables behind the migration history's
back lets a deployment drift away from the reviewed schema, and auto-start
migrations mean a deploy can mutate the database as a side effect of booting a
process. Apply them as an operator action:

```powershell
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe check          # no new operations detected
.\.venv\Scripts\alembic.exe downgrade 0005
```

## Configuration

Everything is read once at import time from the process environment;
`.env` in this directory is loaded automatically. See `.env.example` for the
full list. The ones that matter first:

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | Signs issued bearer tokens. Required in production. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access-token lifetime. |
| `CORS_ORIGINS` | Comma-separated allowed origins. |
| `ALLOW_DEV_AUTH` | Enables the local development-token endpoint. Ignored when Firebase is configured. |
| `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_NAME` | Database connection. |
| `FIREBASE_PROJECT_ID` | Enables Firebase token verification. |
| `FIREBASE_CREDENTIALS_PATH` / `FIREBASE_CREDENTIALS_JSON` | Service-account credentials, inline or by path. |
| `GCS_BUCKET`, `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_DRIVE_FOLDER_ID`, `GOOGLE_DRIVE_CREDENTIALS_PATH` | Remote backup targets. Unset means local backups only. |
| `ASSISTANT_PROVIDER`, `ASSISTANT_API_KEY`, `ASSISTANT_MODEL`, `ASSISTANT_BASE_URL` | Remote assistant. Defaults to the built-in provider. |

## Authentication model

- Clients present `Authorization: Bearer <token>`; nothing else identifies a user.
- A `user_id` in a request body or query string is ignored by the auth layer.
- Every query is scoped to the authenticated user on the server side.
- When Firebase is configured, tokens are verified against Firebase.
- `ALLOW_DEV_AUTH` additionally enables `POST /api/auth/dev-token`, which mints a
  token for a local account. The backend refuses to enable it while Firebase is
  configured, so a Firebase deployment cannot be reached through this path.

## Backup and restore

- Backups record a SHA-256 checksum; restore verifies it before applying anything.
- `POST /api/backups/{id}/restore` returns a preview first and only applies with
  `confirm=true`.
- A restore is transactional and user-scoped, and upserts on natural keys so it is
  safe to run twice.

## Spending forecast

`GET /api/dashboard/prediction` requires three calendar months of expense
history. Below that it returns `status: "insufficient_data"` with the shortfall
described (`available_months`, `required_months`, `months_needed`) rather than a
made-up number. A produced forecast comes back as `status: "predicted"`.

## Fraud model

Scoring reads the model artifact together with the feature order it was trained
against, so the position of a column is never assumed. `app/ml/features.py`
builds the 31 features in semantic order and `finance_ai_ml` declares the same
31 names alphabetically; `app/tests/test_feature_parity.py` asserts the two sets
never drift, because a rename on one side only would be dropped silently at
scoring time.

The sidecar (`ml_artifacts/fraud_model.json`) records the feature names, the
artifact format version, and a SHA-256 checksum of the `.pkl`. `trainer.load`
verifies the checksum *before* unpickling and falls back to rules-only scoring if
it fails. Scoring refuses to run against an untrained model; the thresholds are
`MIN_TRAIN_ROWS=50` and `MIN_POSITIVE_LABELS=5`.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The suite covers authorization boundaries, ownership scoping, backup/restore
conflicts and rollback, the prediction gate, and migration behaviour. It runs
against an isolated database and never touches the live `finance_ai` database.

## Notes for operators

- `DB_PASSWORD` for the live database was exposed in a committed `.env` earlier
  in this project's history. Rotate it before any deployment.

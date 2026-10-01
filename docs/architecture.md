# Architecture

## Shape

```
                 ┌─────────────────────┐
   browser ────►│  finance-ai-frontend │──┐
                 │  React + Vite       │  │   Authorization: Bearer <token>
                 └─────────────────────┘  │
                                           ├──► ┌────────────────────────────┐
                 ┌─────────────────────┐  ├──► │  finance-ai-api (FastAPI)   │
   device  ────►│  FinanceAI           │──┘    │  routes → services → ORM    │
                 │  React Native        │       └───────────┬────────────────┘
                 └─────────────────────┘                   │
                                                            ▼
                                              ┌───────────────────────────┐
                                              │  MySQL  (finance_ai)     │
                                              └───────────────────────────┘

                 ┌─────────────────────┐
   operator ───►│  finance-ai-ml      │──►  fraud_model.pkl + .json
                 │  training / scoring  │     (shared with the API)
                 └─────────────────────┘
```

Four deployable pieces and one database. The clients hold no business logic and
no credentials: they present a token, call endpoints, and render what comes back.

## Layering inside the API

```
routes/      HTTP shape only: parse the request, call a service, shape a response.
services/    Business rules: restore safety, prediction gating, fraud scoring.
ml/          Feature engineering. 31 features in semantic order; the artifact
             records this order so scoring never assumes positions.
models/      SQLAlchemy tables. Numeric columns are Decimal, not float.
schemas/     Pydantic models, including the serialisation of money as strings.
core/        Settings, security primitives, and the request-scoped user dependency.
```

Two rules that the layering exists to enforce:

1. **Identity comes from the token.** `core/deps.py` resolves the bearer token to
   a user once per request. Routes never accept a user id from the client, and
   every query filters on the resolved identity.
2. **Schema changes go through migrations.** `main.py` neither creates tables nor
   migrates on startup. `alembic upgrade head` is an operator action.

## Authentication

```
client ──► GET /api/auth/config
             │
             ├─ provider "firebase"  ──► Firebase ID token ──► Bearer <id-token>
             ├─ provider "dev"       ──► POST /api/auth/dev-token ──► Bearer <jwt>
             └─ provider "unconfigured" ──► no sign-in offered; UI explains
```

The provider is decided by the server, so neither client has to guess. Firebase
verification is on the server; clients only relay tokens. The development path
exists so the suite is runnable without a Firebase project, and the backend
closes it whenever Firebase is configured.

## Fraud scoring pipeline

```
transaction ──► app/ml/features.py ──► 31 features ──► model ──► score + risk level
                (semantic order)        order projected onto
                                        the artifact's feature_names
```

Training lives in two places on purpose: `app/ml/trainer.py` for the API
(`POST /api/ml/train`) and `finance-ai-ml` as a standalone package for offline
work. The two order the same 31 features differently - the API semantically, the
standalone package alphabetically - and that is fine: the model artifact records
its `feature_names`, and scoring projects the vector onto those names rather than
assuming positions. The *set* of names is the hard contract, enforced by
`app/tests/test_feature_parity.py`.

Both training paths refuse to run below 50 labelled rows or 5 positives rather
than producing a model that looks trained and is not. Model artifacts are a
`.pkl` plus a `.json` sidecar carrying the feature names and a training report.

## Backups

`POST /api/backups` writes a checksummed snapshot, locally by default and to GCS
or Google Drive when configured. Restore is deliberately a two-step flow: verify
checksum, then preview the exact changes, then apply with `confirm=true`. The
apply is transactional, scoped to the authenticated user, and upserts on natural
keys so a repeated run converges instead of duplicating.

## Client structure

Both clients follow the same shape, deliberately, so behaviour does not drift:

| Concern | Web | Mobile |
| --- | --- | --- |
| HTTP | `src/lib/api.ts` (Axios) | `src/services/api.ts` (Axios) |
| Typed endpoints | `src/lib/endpoints.ts` | `src/services/endpoints.ts` |
| Session | `src/auth/SessionContext.tsx` | `src/auth/SessionProvider.tsx` |
| Routes | react-router, code-split pages | React Navigation, bottom tabs |
| Firebase | `src/lib/firebase.ts` | `src/services/firebase.ts` |
| Formatting | `src/lib/format.ts` | `src/lib/format.ts` |

The mobile client degrades more: with no Firebase files it falls back to
development tokens, and the receipt scanner is offered only on Android where
on-device ML Kit exists. Neither client invents a value the API did not return -
missing data renders as "not available", not as a zero.

## Data flow rules worth stating

- Money crosses the wire as a decimal string and is parsed with `Decimal` /
  `Numeric`. No float ever holds a currency amount.
- List endpoints are paginated and the client renders the server's `total`.
- Destructive actions (delete, restore, dismiss) go through an endpoint that
  re-checks ownership server-side, so a stale client cannot widen its own scope.

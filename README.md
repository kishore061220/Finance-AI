# FinanceAI

Personal-finance platform: a FastAPI backend, a React web client, a React Native
mobile client, and a standalone fraud-model training package.

## Components

| Directory | What it is | Entry point |
| --- | --- | --- |
| `finance-ai-api/` | FastAPI backend: auth, transactions, budgets, fraud, loans, backups, notifications, forecast | `main.py` → `app:app` |
| `finance-ai-frontend/` | React 19 + Vite + Tailwind web client | `src/main.tsx` → `src/App.tsx` |
| `FinanceAI/` | React Native (0.87) iOS/Android client | `index.js` → `App.tsx` |
| `finance-ai-ml/` | Standalone fraud-model training package | `finance_ai_ml/train.py` |
| `database/` | Schema reference, migration notes, pre-migration live backup | `schema/`, `backup/` |
| `docs/` | Architecture, API contract, verification record, project report | `README.md` in `docs/` |

Each component has its own README with the commands it needs. Start with the one
for the part you are changing.

## Running the stack

Backend first, since both clients talk to it:

```powershell
# 1. API - http://localhost:8000
cd finance-ai-api
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000

# 2a. Web - http://localhost:5173, proxies /api to the backend
cd finance-ai-frontend
npm run dev

# 2b. Mobile
cd FinanceAI
npm start           # Metro
npm run android     # or: npx react-native run-ios
```

The web client calls a relative `/api` path and relies on the dev-server proxy,
so there is no absolute API URL to configure. `VITE_API_BASE_URL` only matters
when the API is hosted on a different origin from the static assets.

## Authentication

Clients authenticate with `Authorization: Bearer <token>`. No endpoint trusts a
`user_id` from the client; every query is scoped to the token's identity on the
server.

- **Firebase** is the production path. Both clients call `GET /api/auth/config`
  first and branch on the reported provider, so a deployment without Firebase
  files renders a developer sign-in instead of failing on a native module.
- **Development tokens** are available only when the backend runs with
  `ALLOW_DEV_AUTH=true` *and* no Firebase project configured. The backend returns
  404 for `/api/auth/dev-token` otherwise, so the local path cannot be reached in
  a Firebase deployment.

## Verification record

Reproduced on this machine:

| Component | Command | Result |
| --- | --- | --- |
| API | `pytest -q` | 255 passed |
| ML | `pytest -q` | 65 passed |
| Web | `npm run typecheck` / `npm run lint` / `npm test -- --run` / `npm run build` | clean / clean / 98 passed / built |
| Mobile | `npx tsc --noEmit` / `npm run lint` / `npm test -- --runInBand` | clean / 0 errors / 41 passed |
| Mobile Android | `gradlew :app:assembleDebug` | `BUILD SUCCESSFUL` → `app-debug.apk` |
| Mobile bundle | `react-native bundle --platform android --dev false` | bundle written |

`docs/verification.md` records what each of these covers and what remains
unverified, including the checks that need real credentials or a device.

## Security notes

- The live database `finance_ai` was treated as read-only throughout. No migration
  or cutover was run against it.
- The live `DB_PASSWORD` was exposed in a committed `.env`. **Rotate it before
  deploying.** The credential was not read or copied anywhere.
- `finance-ai-api/.env` and any Firebase/Google credentials stay out of version
  control; `.env.example` documents the variable names.

## Known limitations

- iOS is unverified: no macOS/Xcode in this environment.
- Cloud backup targets (GCS / Google Drive) and the remote assistant need provider
  credentials; local backups and the built-in assistant work without them.
- Receipt OCR needs on-device ML Kit, which requires Google Services files and a
  physical Android device.
- Production fraud-model training is intentionally refused on live data: it holds
  9 transactions against a 50-row minimum.

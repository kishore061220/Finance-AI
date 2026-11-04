# Finance-AI

**Secure Financial Transaction Monitoring and Fraud Detection System** — a personal-finance prototype that captures transactions (manual entry, receipt OCR, bank SMS) and screens each one for suspicious activity using inspectable rules plus a secondary machine-learning score.

> **Status: prototype.** This is an integrated software prototype with a transparent evaluation. It is **not** a validated fraud detector. See [What is and is not validated](#what-is-and-is-not-validated).

Presented at NCIETCA-2026 (Paper ID NCIETCA082). Authors: Kishore V and Dr. K. Anuradha, Master of Computer Applications, Rathinam Technical Campus, Coimbatore.

## Features

- **Transaction capture:** manual entry, receipt OCR (ML Kit on Android), and bank SMS on Android.
- **SMS safety:** on-device filter, deduplication, and a confidence gate. Messages parsed below 0.85 confidence are held as `PENDING_REVIEW` for the owner to confirm.
- **Fraud screening:** a rule-and-history risk score (amount, unusual hour, suspicious merchant, spend spike, new merchant or category, bursts of activity) producing LOW, MEDIUM or HIGH alerts with reasons.
- **ML signal:** an offline-trained model contributes a secondary score. Combined score = `round(0.7 * rule + 0.3 * ML)`. If no verified model artifact is available, scoring falls back to rules only.
- **Personal finance:** budgets, reports, loans, notifications and a spending forecast.
- **Backup and restore:** checksum-verified backups with a preview and explicit confirmation; restored rows are stamped with the authenticated user.
- **Per-user isolation:** the user comes from a verified bearer token, never from a client-supplied identifier.

## Architecture

| Part | Folder | Stack |
| --- | --- | --- |
| Mobile client (Android) | repository root, `src/`, `android/` | React Native, TypeScript, Kotlin SMS receiver |
| Web client | [`finance-ai-frontend/`](finance-ai-frontend/README.md) | React, TypeScript, Vite |
| Backend API | [`finance-ai-api/`](finance-ai-api/README.md) | Python, FastAPI, SQLAlchemy, Alembic, MySQL / MariaDB |
| ML package (offline) | [`finance-ai-ml/`](finance-ai-ml/README.md) | pandas, scikit-learn, XGBoost |
| Identity | backend + clients | Firebase Authentication (with a local development-token mode) |

The ML package is separate from the API. It exports a checksum-verified model artifact that the backend loads at run time. See [`docs/architecture.md`](docs/architecture.md) for the component map and fraud pipeline.

## Quick start

Requirements: Python 3.11+ (or the version your environment uses), Node.js 20+, MySQL or MariaDB. Android Studio for the mobile app.

**1. Backend**

```bash
cd finance-ai-api
python -m venv .venv
# Windows: .venv\Scripts\activate    Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fill in the values
alembic upgrade head        # migrations are explicit, never run on startup
python -m uvicorn main:app --reload --port 8000
```

Health check: `GET /health`. Interactive docs: `http://localhost:8000/docs`.

**2. Web client**

```bash
cd finance-ai-frontend
npm install
npm run dev
```

The dev server proxies `/api` to `http://127.0.0.1:8000`.

**3. Mobile client (Android)**

```bash
npm install
npm start          # Metro
npm run android    # in a second terminal
```

**4. ML package (optional)**

```bash
pip install -e ./finance-ai-ml
python -m finance_ai_ml compare finance-ai-ml/sample_data/transactions.csv --split chronological
```

See each component's README for configuration, Firebase setup and training commands.

## Tests

```bash
# API
cd finance-ai-api && python -m pytest -q
# Web
cd finance-ai-frontend && npm run verify
# Mobile
npm test
# ML
cd finance-ai-ml && python -m pytest -q
```

Test results reported in [`docs/verification.md`](docs/verification.md): API 306, ML 81, web 104 and mobile 60 tests passing, an Android debug build, Alembic up/down/up, and a 20/20 shared-database end-to-end check. These are the repository's own reported results.

## Evaluation (ML component only)

Dataset: the public ULB/Worldline credit-card fraud benchmark (OpenML 1597), mapped to the application's fields (282,982 rows, 465 frauds, about 0.16 percent). Models are ranked by average precision (AP) because fraud is so rare.

| Model | Stratified AP | Chronological AP |
| --- | --- | --- |
| Logistic Regression | 0.0044 | 0.0023 |
| Random Forest | 0.0866 | 0.0021 |
| XGBoost | 0.0544 | 0.0022 |

Random Forest led on the random split, but on the chronological split every model fell close to the test-set fraud rate, and Random Forest flagged no frauds at the 0.5 threshold. Full metrics, the mapping and limitations are in [`finance-ai-ml/DATASET.md`](finance-ai-ml/DATASET.md).

## What is and is not validated

**Documented as tested:** unit and integration tests, migrations, an end-to-end check against a shared database, and an Android debug build.

**Not yet validated:**

- The combined rule + ML detector on labelled fraud data.
- Live Firebase token verification (credentials absent).
- SMS capture on physical Android devices.
- Response time and throughput.

**Known limitations:** the benchmark is credit-card data, not personal SMS or receipts; rule thresholds are untuned and the currency is unspecified; the server stores raw SMS text; results rest on a single run and small numbers of fraud cases.

## Documentation

- [`docs/architecture.md`](docs/architecture.md), [`docs/api-contract.md`](docs/api-contract.md)
- [`docs/verification.md`](docs/verification.md), [`docs/completion-audit.md`](docs/completion-audit.md)
- [`docs/firebase-setup.md`](docs/firebase-setup.md), [`docs/project-report.md`](docs/project-report.md)

## License

MIT. See [`LICENSE`](LICENSE).

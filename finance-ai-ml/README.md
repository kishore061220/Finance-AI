# Finance-AI ML

Offline training package that exports a fraud detection model compatible with the `finance-ai-api` backend's scoring contract.

- **Canonical feature set:** 31 features in an exact order enforced by `finance_ai_ml.features.CANONICAL_FEATURES`.
- **Data hygiene:** Strict CSV/Parquet parsing. Non-numeric or non-positive amounts, unparseable dates, and unreadable labels are dropped and reported in `frame.attrs["dropped"]`.
- **Conservative training:** Refuses to train below 50 rows or 5 positive labels. Uses XGBoost when installed, falling back to scikit-learn's `HistGradientBoostingClassifier`.
- **Backend compatibility:** Exports `fraud_model.pkl` and `fraud_model.json` with a SHA256 checksum and the feature order the backend loads.
- **No real data in the repo.** Tests generate synthetic data in memory and never write to `backups/`, `ml_artifacts/`, or the project root.

## Installation

Editable install from the repository root:

```bash
pip install -e ./finance-ai-ml
```

Or install just the dependencies:

```bash
pip install -r finance-ai-ml/requirements.txt
```

## Commands

The dataset path is positional. Four subcommands:

```bash
# Describe a dataset without training.
python -m finance_ai_ml inspect sample_data/transactions.csv

# Train and write fraud_model.{pkl,json} to --output.
python -m finance_ai_ml train sample_data/transactions.csv --output ./artifacts

# Train and write straight into the backend's artifact directory.
python -m finance_ai_ml publish sample_data/transactions.csv --backend ../finance-ai-api

# Fit and compare several models, then export the winner. `--split chronological`
# scores oldest->newest, the stricter estimate for time-ordered fraud.
python -m finance_ai_ml compare sample_data/transactions.csv --split stratified \
    --backend ../finance-ai-api

# Re-check an existing artifact's checksum and print its metadata.
python -m finance_ai_ml verify ../finance-ai-api/ml_artifacts
```

The dataset actually used, the mapping, the per-model metrics and the honest
limitations are recorded in [DATASET.md](DATASET.md). The acquisition script
lives at `scripts/prepare_ulb_creditcard.py`.

Thresholds are overridable with `--min-rows`, `--min-positives`, and `--test-size`. Lower them only when a smaller dataset is genuinely the right call, and only knowing the reported metrics become less trustworthy.

### Exit codes

| Code | Meaning |
| ---- | ------- |
| `0` | Success |
| `1` | Refused: `insufficient_data`. No artifact written. |
| `2` | Bad input: unreadable file, missing column, corrupt artifact. |

A scheduled job can therefore tell "not enough data today" apart from "the file was malformed".

## What a run reports

A successful run reports held-out `roc_auc`, `average_precision`, `precision`, `recall`, and `f1`, alongside caveats that name the sample sizes.

Those numbers are an indication, not evidence, until the model has been measured against real confirmed fraud. `tests/conftest.py` builds a synthetic dataset with a genuine distribution shift - fraud rows are large, round, nocturnal, and from unfamiliar merchants - so the suite can prove the pipeline learns something rather than merely asserting that a number is above a threshold. Synthetic performance still does not transfer to production.

A refusal reports which threshold was missed and how many rows were dropped, and writes nothing.

## Tests

```bash
cd finance-ai-ml
python -m pytest -q
```

Two suites carry most of the weight:

- `tests/test_parity_with_backend.py` imports the backend's `app.ml.features.build_feature_vector` directly and asserts the canonical feature names *and values* match. It imports rather than restating the expected list so it tracks the backend automatically instead of going stale when a feature is added there. A failure here is the dangerous kind: the backend would score against the wrong columns with no exception raised.
- `tests/test_train.py::TestBackendCompatibility` trains here, exports, then hands the artifact to the backend's own loader and scores a real transaction with it. That is the test that catches a packaging or format mismatch between the two projects.

Both skip if `finance-ai-api` is absent, so this package stays testable on its own.

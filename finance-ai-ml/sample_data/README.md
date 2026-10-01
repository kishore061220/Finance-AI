Put real labelled training data here, one CSV or Parquet file.

This directory is intentionally empty in the repository. Two reasons:

1. A committed synthetic dataset would make any reported metric meaningless. A
   model trained on a file that ships with the repo is scored on data it has
   already memorised, so the resulting `roc_auc` describes nothing real.
2. A committed real dataset would be a disclosure incident. Every row is a
   customer's transaction history.

The test suite generates its own synthetic data in memory (see
`tests/conftest.py`) and never reads from this directory, so leaving it empty
keeps the tests honest.

## Required columns

| Column              | Required | Notes                                              |
| ------------------- | -------- | -------------------------------------------------- |
| `transaction_date`  | yes      | Anything pandas can parse; parsed to datetime       |
| `amount`            | yes      | Numeric and greater than zero; others are dropped   |
| `is_flagged`        | yes      | 0/1, `true`/`false`, `yes`/`no`, `fraud`/`clean`    |

Also recognised, and filled with defaults when absent:

| Column              | Default        |
| ------------------- | -------------- |
| `user_id`           | `0`            |
| `transaction_type`  | `expense`      |
| `category`          | `Uncategorized`|
| `merchant`          | `None`         |
| `emi_type`          | `None`         |
| `source`            | `MANUAL`       |

Other label names (`label`, `is_fraud`, `fraud`) are accepted, or pass an
explicit one with `--label-column`.

## Inspect before training

```bash
python -m finance_ai_ml inspect sample_data/transactions.csv
```

Training refuses to run below 50 rows or 5 positive labels. When that happens
it exits `1` and writes no artifact, so a scheduled job can tell "not enough
data today" apart from "the file was malformed" (exit `2`).

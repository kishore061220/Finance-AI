# Fraud training dataset and evaluation record

This file records exactly what the fraud model was trained on, how it was
evaluated, what the numbers were, and why those numbers are modest. It is the
evidence behind the artifact at `finance-ai-api/ml_artifacts/fraud_model.pkl`.

---

## 1. Dataset

| Field | Value |
| --- | --- |
| Name | `creditcard` (Credit Card Fraud Detection) |
| Source | OpenML data id **1597** — <https://www.openml.org/d/1597> |
| Origin | Machine Learning Group, Université Libre de Bruxelles (ULB) & Worldline |
| File | ARFF, 284,807 rows, 31 columns (30 numeric + 1 nominal) |
| Download URL | <https://openml.org/data/v1/download/1673544/creditcard.arff> |
| Licence (as listed) | OpenML reports **Public**. The canonical Kaggle release is distributed under the **Open Database License (ODbL)** with contents under the **Database Contents License (DbCL)**. |
| Label | `Class`: `1` = a transaction confirmed fraudulent; `0` = legitimate. |
| Balance | 492 frauds / 284,807 rows = **0.172 %** positive. |

### Why this dataset

It is a **real, documented, anonymised** fraud label set — not synthetic, not a
committed sample of live user data. It is the de-facto benchmark for
transactional fraud and its class imbalance is representative of the problem.

### What it does not contain

`V1..V28` are the output of a PCA transform the publisher applied to protect
cardholder privacy. They are **not** reconstructable into merchant, category or
counterparty fields, and the production scoring contract
(`finance-ai-api/app/ml/features.py`) cannot produce them. A model that used
them would be unscorable against a live Finance-AI transaction. They are
therefore dropped — see the limitation in §5.

---

## 2. Mapping to the training schema

`scripts/prepare_ulb_creditcard.py` performs the mapping:

| ULB column | Finance-AI column | Note |
| --- | --- | --- |
| `Time` | `transaction_date` | `2013-09-01T00:00:00Z` + `Time` seconds |
| `Amount` | `amount` | unchanged |
| `Class` | `is_flagged` | the label |
| — | `user_id` | `0` (one synthetic user) |
| — | `transaction_type` | `expense` |
| — | `category` | `Uncategorized` |
| — | `merchant` | empty |
| — | `source` | `MANUAL` |

Rows with `amount <= 0` are dropped by the pipeline's documented rule. In the
source that removes **1,825** rows including **27** frauds whose `Amount` was
`0`, leaving **282,982 rows / 465 positives**. This bias is unavoidable without
fabricating amounts, and is stated rather than hidden.

---

## 3. Data inspection (before training)

Run: `python -m finance_ai_ml inspect <csv>`

| Check | Result |
| --- | --- |
| Rows | 282,982 |
| Positives | 465 (0.1643 %) |
| Missing values | 0 in modelled columns (blank `merchant`/`emi_type` are the documented defaults) |
| Exact duplicate rows | 4,822 (byte-identical after mapping) |
| Date span | 2013-09-01 → 2013-09-02 (two days) |
| Amount | min 0.01, mean 88.92, max 25,691.16 |

**Leakage controls**

* The train/test split is taken **before** any preprocessing is fitted.
* The linear model's `StandardScaler` lives inside a `Pipeline`, so it is fitted
  on the training fold only.
* Label-derived columns are never used as features; the feature builder
  (`finance_ai_ml.features`) consumes only amount/time/merchant/type/source.
* `amount_vs_mean` uses the user's overall mean, matching the backend, so no
  future window leaks into a training row.

---

## 4. Models compared

Run: `python -m finance_ai_ml compare <csv> --split <stratified|chronological>`

Candidates: `LogisticRegression` (scaled, `class_weight="balanced"`),
`RandomForestClassifier` (`class_weight="balanced_subsample"`), and
`XGBoost` (`scale_pos_weight`). Held-out threshold 0.5.

### Stratified 20 % hold-out (56,597 rows, 93 positives)

| Model | ROC-AUC | PR-AUC | Precision | Recall | F1 | False positives |
| --- | --- | --- | --- | --- | --- | --- |
| logistic_regression | 0.6844 | 0.0044 | 0.0031 | 0.6129 | 0.0061 | 18,472 |
| **random_forest** | **0.7577** | **0.0866** | 0.0213 | 0.3333 | 0.0401 | 1,424 |
| xgboost | 0.8278 | 0.0544 | 0.0065 | 0.6882 | 0.0129 | 9,759 |

**Selected: random_forest**, by average precision (PR-AUC = 0.0866). At a base
rate of 0.0016, that is roughly a **54× lift** over random ranking. XGBoost has
the higher ROC-AUC but a materially worse PR-AUC at the 0.5 threshold, which is
the metric that matters for a rare positive class.

### Chronological hold-out (oldest 80 % train, newest 20 % test — 70 positives)

| Model | ROC-AUC | PR-AUC | Recall | F1 | False positives |
| --- | --- | --- | --- | --- | --- |
| logistic_regression | 0.6538 | 0.0023 | 0.1571 | 0.0032 | 6,702 |
| random_forest | 0.6626 | 0.0021 | 0.0000 | 0.0000 | 0 |
| xgboost | 0.6827 | 0.0022 | 0.2429 | 0.0052 | 6,442 |

This is the honest headline: **when the model must predict future transactions
from past ones, PR-AUC collapses to ≈0.002 — barely above the 0.0016 base
rate.** The stratified figure is flattering partly because a random split lets
near-duplicate transactions land on both sides. The deployed model should be
treated as a weak secondary signal, which is exactly how the backend uses it
(30 % weight, rules keep 70 %).

---

## 5. Limitations

1. **Feature starvation.** Only `amount` and time-of-day reach the model. The
   ULB signal that makes fraud separable lives in `V1..V28`, which the scoring
   contract cannot supply. This is the single biggest cause of the modest
   numbers.
2. **Distribution shift.** All rows share `user_id = 0`, so `amount_vs_mean`,
   `merchant_tx_count` and `user_tx_count` are computed over one pseudo-user. A
   real user's per-transaction baseline differs.
3. **No merchant/category signal** in the source, so those one-hot features are
   constant here and carry no weight.
4. **Zero-amount frauds dropped** (27 of 492) by the `amount > 0` rule.
5. **Two-day window.** `month`/`day_of_month` take almost no range, and any
   weekly seasonality is unrepresented.

Conclusion: the pipeline is proven to train, evaluate, select, export and score
a real model on real labels, but a *production-grade* fraud model needs data
that exposes merchant, category and counterparty features at scoring time.

---

## 6. Reproduce

```bash
# 1. Fetch and map the dataset (downloads ~144 MiB to --work-dir).
python finance-ai-ml/scripts/prepare_ulb_creditcard.py --work-dir /tmp/ulb

# 2. Compare models and publish the winner to the backend.
cd finance-ai-ml
python -m finance_ai_ml compare /tmp/ulb/ulb_creditcard.csv --split stratified \
    --backend ../finance-ai-api

# 3. Confirm the artifact loads and scores.
cd ../finance-ai-api
python -c "from app.ml import trainer; print(trainer.load()[1])"

# 4. Verify artifact integrity.
cd ../finance-ai-ml
python -m finance_ai_ml verify ../finance-ai-api/ml_artifacts
```

The dataset is **not** committed (it is ~144 MiB and its licence is better
honoured by fetching from the source). The artifact is git-ignored; reproduce
it, do not commit the pickle.

"""Vectorised feature engineering with pandas.

This mirrors ``finance-ai-api/app/ml/features.py`` column for column. The two
implementations are written differently (vectorised here, row-at-a-time in the
backend) but must produce *identical* names and semantics, because the backend
scores live transactions with its own builder and feeds the result to an
estimator trained here. A silent divergence would not crash - it would just
quietly degrade every fraud score, which is the worst possible failure mode.

``tests/test_parity_with_backend.py`` asserts name-for-name agreement. Run it.
"""

from __future__ import annotations

import logging
import math
from typing import List

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# The 31 columns the backend's build_feature_vector produces, in canonical order.
# Order is fixed, not sorted, so the artifact and the scoring path agree.
CANONICAL_FEATURES: List[str] = [
    "amount",
    "amount_deviation",
    "amount_log",
    "amount_sqrt",
    "amount_vs_mean",
    "category_known",
    "day_of_month",
    "dow_0",
    "dow_1",
    "dow_2",
    "dow_3",
    "dow_4",
    "dow_5",
    "dow_6",
    "hour_cos",
    "hour_sin",
    "is_amount_outlier",
    "is_emi",
    "is_expense",
    "is_income",
    "is_night",
    "is_round_amount",
    "is_weekend",
    "merchant_known",
    "merchant_tx_count",
    "month",
    "source_manual",
    "source_ocr",
    "source_sms",
    "user_tx_count",
    "weekday",
]


class FeatureContractError(ValueError):
    """The produced columns do not match the contract the backend scores with."""


def _merchant_key(value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "unknown"
    return str(value).strip().lower() or "unknown"


def build_feature_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Return the canonical feature matrix for a cleaned transaction frame.

    Every feature uses only information available at scoring time. In particular
    ``amount_vs_mean`` uses the user's *overall* mean rather than a mean computed
    from the future, matching the backend.
    """
    if frame.empty:
        return pd.DataFrame(columns=CANONICAL_FEATURES)

    df = frame.copy()
    dates = pd.to_datetime(df["transaction_date"])
    amount = df["amount"].astype(float)

    out = pd.DataFrame(index=df.index)

    # --- Time, encoded cyclically so 23:00 and 00:00 are adjacent ---------
    hour = dates.dt.hour.astype(float)
    weekday = dates.dt.weekday.astype(float)
    out["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    out["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    out["weekday"] = weekday
    out["is_weekend"] = (weekday >= 5).astype(float)
    out["is_night"] = ((hour >= 22) | (hour < 6)).astype(float)
    out["day_of_month"] = dates.dt.day.astype(float)
    out["month"] = dates.dt.month.astype(float)
    for i in range(7):
        out[f"dow_{i}"] = (weekday == i).astype(float)

    # --- Amount -----------------------------------------------------------
    out["amount"] = amount
    out["amount_log"] = np.log1p(amount.clip(lower=0))
    out["amount_sqrt"] = np.sqrt(amount.clip(lower=0))
    out["is_round_amount"] = ((amount >= 100) & (amount % 100 == 0)).astype(float)

    # --- Amount relative to this user's own mean ---------------------------
    grouped_mean = amount.groupby(df["user_id"]).transform("mean")
    ratio = (amount / grouped_mean).fillna(0.0).replace([np.inf, -np.inf], 0.0)
    out["amount_vs_mean"] = ratio
    out["amount_deviation"] = ratio - 1.0
    out["is_amount_outlier"] = (ratio > 3).astype(float)

    # --- Categorical encodings --------------------------------------------
    ttype = df["transaction_type"].astype(str).str.lower()
    out["is_expense"] = (ttype == "expense").astype(float)
    out["is_income"] = (ttype == "income").astype(float)
    out["is_emi"] = df["emi_type"].notna().astype(float)

    # --- Merchant history within the user ---------------------------------
    merchant_keys = pd.Series(
        [_merchant_key(m) for m in df["merchant"]], index=df.index
    )
    merchant_counts = merchant_keys.groupby([df["user_id"], merchant_keys]).transform(
        "size"
    )
    out["merchant_known"] = (merchant_counts > 0).astype(float)
    out["merchant_tx_count"] = merchant_counts.astype(float)
    out["user_tx_count"] = (
        amount.groupby(df["user_id"]).transform("size").astype(float)
    )

    category = df["category"].astype(str).str.lower()
    out["category_known"] = ((category != "") & (category != "other")).astype(float)

    source = df["source"].astype(str).str.upper()
    out["source_sms"] = (source == "SMS").astype(float)
    out["source_ocr"] = (source == "OCR").astype(float)
    out["source_manual"] = (source == "MANUAL").astype(float)

    return assert_feature_contract(out)


def assert_feature_contract(matrix: pd.DataFrame) -> pd.DataFrame:
    """Fail loudly if the column set has drifted from the backend's contract.

    Returning the reordered frame means a correct-but-differently-ordered
    result is repaired silently, while a genuinely missing or extra column is an
    error rather than a silently wrong model.
    """
    produced = set(matrix.columns)
    expected = set(CANONICAL_FEATURES)

    missing = sorted(expected - produced)
    extra = sorted(produced - expected)
    if missing or extra:
        raise FeatureContractError(
            "Feature matrix does not match the scoring contract. "
            f"Missing: {missing}. Unexpected: {extra}. The backend scores live "
            "transactions with app.ml.features; this matrix must have exactly "
            "the same columns."
        )
    return matrix[CANONICAL_FEATURES]


def extract_labels(frame: pd.DataFrame) -> np.ndarray:
    """Labels as an int array; unlabelled rows become ``-1`` (never trained on)."""
    labels = frame["label"]
    return labels.map(lambda v: -1 if v is None or pd.isna(v) else int(v)).to_numpy(
        dtype=int
    )


__all__ = [
    "CANONICAL_FEATURES",
    "FeatureContractError",
    "assert_feature_contract",
    "build_feature_frame",
    "extract_labels",
]

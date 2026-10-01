"""Feature engineering for the fraud and spend models.

Kept free of pandas/sklearn imports at module level so the API can import it
in environments where the ML extras are not installed.
"""

from __future__ import annotations

import math
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Sequence

HOUR_CYCLES = ["morning", "afternoon", "evening", "night"]


def _amount(value) -> float:
    if isinstance(value, Decimal):
        return float(value)
    return float(value or 0)


def _merchant_key(merchant: Optional[str]) -> str:
    return (merchant or "unknown").strip().lower()


def time_features(dt: datetime) -> Dict[str, float]:
    """Cyclical time features - hour and weekday encoded without ordering bias."""
    hour = dt.hour
    weekday = dt.weekday()
    return {
        "hour_sin": math.sin(2 * math.pi * hour / 24),
        "hour_cos": math.cos(2 * math.pi * hour / 24),
        "weekday": float(weekday),
        "is_weekend": 1.0 if weekday >= 5 else 0.0,
        "is_night": 1.0 if hour >= 22 or hour < 6 else 0.0,
        "day_of_month": float(dt.day),
        "month": float(dt.month),
    }


def day_of_week_onehot(weekday: int) -> Dict[str, float]:
    return {f"dow_{i}": 1.0 if weekday == i else 0.0 for i in range(7)}


def amount_features(amount, user_mean: Optional[float] = None) -> Dict[str, float]:
    a = _amount(amount)
    feats = {
        "amount": a,
        "amount_log": math.log1p(max(a, 0.0)),
        "amount_sqrt": math.sqrt(max(a, 0.0)),
        "is_round_amount": 1.0 if a >= 100 and a % 100 == 0 else 0.0,
    }
    if user_mean and user_mean > 0:
        ratio = a / user_mean
        feats["amount_vs_mean"] = ratio
        feats["amount_deviation"] = ratio - 1.0
        feats["is_amount_outlier"] = 1.0 if ratio > 3 else 0.0
    else:
        feats["amount_vs_mean"] = 0.0
        feats["amount_deviation"] = 0.0
        feats["is_amount_outlier"] = 0.0
    return feats


def build_feature_vector(
    transaction,
    *,
    user_mean_amount: Optional[float] = None,
    merchant_seen_count: int = 0,
    user_tx_count: int = 0,
) -> Dict[str, float]:
    """One feature dict for a single transaction.

    Uses only values available at scoring time - no future information.
    """
    dt = transaction.transaction_date
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)

    feats: Dict[str, float] = {}
    feats.update(time_features(dt))
    feats.update(day_of_week_onehot(dt.weekday()))
    feats.update(
        amount_features(getattr(transaction, "amount", 0), user_mean_amount)
    )

    amount = _amount(getattr(transaction, "amount", 0))
    ttype = getattr(transaction, "transaction_type", None)
    ttype = getattr(ttype, "value", ttype)
    feats["is_expense"] = 1.0 if ttype == "expense" else 0.0
    feats["is_income"] = 1.0 if ttype == "income" else 0.0
    feats["is_emi"] = 1.0 if getattr(transaction, "emi_type", None) else 0.0
    feats["merchant_known"] = 1.0 if merchant_seen_count > 0 else 0.0
    feats["merchant_tx_count"] = float(merchant_seen_count)
    feats["user_tx_count"] = float(user_tx_count)

    category = (getattr(transaction, "category", "") or "").lower()
    feats["category_known"] = 1.0 if category and category != "other" else 0.0

    source = getattr(transaction, "source", None)
    source = getattr(source, "value", source)
    feats["source_sms"] = 1.0 if source == "SMS" else 0.0
    feats["source_ocr"] = 1.0 if source == "OCR" else 0.0
    feats["source_manual"] = 1.0 if source == "MANUAL" else 0.0

    return feats


def build_dataset(
    transactions: Sequence,
    labels: Optional[Sequence[int]] = None,
) -> tuple:
    """Return ``(feature_matrix, feature_names, labels)``.

    When ``labels`` is None an unsupervised flag is produced instead: the
    amount deviation and round-amount heuristics. This is explicitly *not* a
    supervised label and is only used for bootstrapping the pipeline.
    """
    means: Dict[int, float] = {}
    totals: Dict[int, List[float]] = {}
    merchants: Dict[tuple, int] = {}
    counts: Dict[int, int] = {}

    for tx in transactions:
        uid = getattr(tx, "user_id", 0)
        amount = _amount(getattr(tx, "amount", 0))
        totals.setdefault(uid, []).append(amount)
        counts[uid] = counts.get(uid, 0) + 1
        key = (uid, _merchant_key(getattr(tx, "merchant", None)))
        merchants[key] = merchants.get(key, 0) + 1

    for uid, amounts in totals.items():
        means[uid] = sum(amounts) / len(amounts) if amounts else 0.0

    rows: List[Dict[str, float]] = []
    feature_names: List[str] = []
    for tx in transactions:
        uid = getattr(tx, "user_id", 0)
        row = build_feature_vector(
            tx,
            user_mean_amount=means.get(uid),
            merchant_seen_count=merchants.get(
                (uid, _merchant_key(getattr(tx, "merchant", None))), 0
            ),
            user_tx_count=counts.get(uid, 0),
        )
        if not feature_names:
            feature_names = sorted(row.keys())
        rows.append({name: row.get(name, 0.0) for name in feature_names})

    if labels is not None:
        y = list(labels)
    else:
        y = [
            1
            if (
                row.get("is_amount_outlier", 0) == 1
                or row.get("is_night", 0) == 1 and row.get("is_amount_outlier", 0) == 1
            )
            else 0
            for row in rows
        ]

    return rows, feature_names, y

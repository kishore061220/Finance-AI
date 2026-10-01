"""Rule-based fraud detection.

Two layers:

* ``analyze_transaction`` - the original, stateless rule engine. Its signature
  and return shape are preserved exactly so existing callers keep working.
* ``analyze_with_baseline`` - an extended engine that also compares a
  transaction against that user's own historical behaviour (amount deviation,
  new merchant, unusual category, burst activity).

This module is deterministic rule logic. It is deliberately separate from the
``app.ml`` supervised models so the two detection layers can be reported
independently (see ``DetectionLayer``).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Sequence

SUSPICIOUS_MERCHANTS = ("unknown", "test merchant", "suspicious merchant")

# Thresholds kept identical to the original implementation for compatibility.
HIGH_AMOUNT = 50000
ELEVATED_AMOUNT = 25000
UNUSUAL_HOURS = (0, 1, 2, 3, 4, 23)

HIGH_RISK_AT = 60
MEDIUM_RISK_AT = 30


def _level_for(score: int) -> str:
    if score >= HIGH_RISK_AT:
        return "HIGH"
    if score >= MEDIUM_RISK_AT:
        return "MEDIUM"
    return "LOW"


def analyze_transaction(
    amount: float,
    merchant: str | None,
    transaction_date: datetime,
) -> Dict:
    """Original stateless fraud engine. Behaviour preserved verbatim."""
    risk_score = 0
    reasons: List[str] = []

    # 1. High amount check
    if amount >= HIGH_AMOUNT:
        risk_score += 40
        reasons.append("Unusually high transaction amount")
    elif amount >= ELEVATED_AMOUNT:
        risk_score += 20
        reasons.append("High transaction amount")

    # 2. Transaction time check
    hour = transaction_date.hour
    if hour in UNUSUAL_HOURS:
        risk_score += 25
        reasons.append("Transaction occurred at an unusual time")

    # 3. Merchant check
    if merchant and merchant.lower() in SUSPICIOUS_MERCHANTS:
        risk_score += 30
        reasons.append("Suspicious merchant")

    risk_level = _level_for(risk_score)
    return {
        "is_fraud": risk_level == "HIGH",
        "risk_score": risk_score,
        "risk_level": risk_level,
        "reasons": reasons,
    }


def analyze_with_baseline(
    amount: float,
    merchant: str | None,
    transaction_date: datetime,
    *,
    category: Optional[str] = None,
    history_amounts: Optional[Sequence[float]] = None,
    history_merchants: Optional[Sequence[str]] = None,
    history_categories: Optional[Sequence[str]] = None,
    transactions_last_24h: int = 0,
) -> Dict:
    """Extended engine combining static rules with per-user behavioural checks.

    ``history_*`` are the user's prior (already-saved) transactions. All
    baseline rules degrade gracefully when history is empty: with no history
    the result is identical to :func:`analyze_transaction`.
    """
    result = analyze_transaction(amount, merchant, transaction_date)
    risk_score = int(result["risk_score"])
    reasons: List[str] = list(result["reasons"])
    signals: List[str] = []

    hist_amounts = [float(a) for a in (history_amounts or [])]
    hist_merchants = {m.strip().lower() for m in (history_merchants or []) if m}
    hist_categories = {c.strip().lower() for c in (history_categories or []) if c}

    # --- 5. Amount deviation vs the user's own mean -----------------------
    if hist_amounts:
        mean = sum(hist_amounts) / len(hist_amounts)
        if mean > 0:
            deviation = (float(amount) - mean) / mean
            if deviation > 3:
                risk_score += 25
                reasons.append(
                    f"Amount is {deviation:.1f}x the user's average transaction ({mean:.0f})"
                )
                signals.append("amount_spike")
            elif deviation > 1.5:
                risk_score += 10
                reasons.append("Transaction is notably above the user's average")
                signals.append("amount_above_average")

    # --- 6. Never-seen merchant ------------------------------------------
    if merchant and hist_merchants and merchant.strip().lower() not in hist_merchants:
        risk_score += 15
        reasons.append("First transaction with this merchant")
        signals.append("new_merchant")

    # --- 7. New / atypical category ---------------------------------------
    if category and hist_categories and category.strip().lower() not in hist_categories:
        risk_score += 5
        reasons.append("Unusual spending category for this user")
        signals.append("new_category")

    # --- 8. Burst activity -------------------------------------------------
    if transactions_last_24h >= 5:
        risk_score += 15
        reasons.append(f"{transactions_last_24h} transactions in the last 24 hours")
        signals.append("velocity_burst")

    # Cap at 100 so the score stays interpretable.
    risk_score = min(risk_score, 100)
    risk_level = _level_for(risk_score)

    return {
        "is_fraud": risk_level == "HIGH",
        "risk_score": risk_score,
        "risk_level": risk_level,
        "reasons": reasons,
        "signals": signals,
        "detection_layer": "RULES",
        "baseline_size": len(hist_amounts),
    }


def count_recent_transactions(
    all_transactions: Sequence, reference: datetime, window_hours: int = 24
) -> int:
    """Count transactions with a ``transaction_date`` inside the window."""
    cutoff = reference - timedelta(hours=window_hours)
    total = 0
    for tx in all_transactions:
        tx_date = getattr(tx, "transaction_date", None)
        if tx_date is not None and cutoff <= tx_date <= reference:
            total += 1
    return total


def summarize_alerts(alerts: Sequence) -> Dict:
    """Aggregate fraud alerts for the dashboard."""
    by_level = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    unread = 0
    for alert in alerts:
        level = getattr(alert.risk_level, "value", str(alert.risk_level))
        by_level[level] = by_level.get(level, 0) + 1
        if not alert.is_read:
            unread += 1
    return {
        "total": len(alerts),
        "by_level": by_level,
        "unread": unread,
    }


__all__ = [
    "analyze_transaction",
    "analyze_with_baseline",
    "count_recent_transactions",
    "summarize_alerts",
    "Decimal",
]

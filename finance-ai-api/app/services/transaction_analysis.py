"""Transactional fraud analysis shared by every transaction-writing path.

This is the single implementation of the behavioural scoring used when a
transaction is created or updated. It lives here so that manual entries,
the SMS ingestion pipeline and OCR/import all run *exactly* the same detection
logic instead of three copies that can drift apart.

Ownership is deliberately NOT enforced here. The caller has already resolved
the authenticated user and passes ``user_id`` explicitly; every query is
scoped to that id.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ml import trainer
from app.models.fraud_alert import DetectionLayer, FraudAlert, RiskLevel
from app.models.transaction import Transaction
from app.services.fraud_detection import analyze_with_baseline


def user_history(
    db: Session, user_id: int, exclude_id: Optional[int] = None
) -> list[Transaction]:
    """Prior transactions used as the behavioural baseline for scoring."""
    stmt = select(Transaction).where(Transaction.user_id == user_id)
    if exclude_id is not None:
        stmt = stmt.where(Transaction.id != exclude_id)
    return list(db.execute(stmt.order_by(Transaction.transaction_date.desc()).limit(500)).scalars())


def score_transaction(
    transaction: Transaction, history: list[Transaction], db: Session
) -> dict:
    """Blend the rule engine with the ML model for one transaction."""
    amounts = [float(t.amount) for t in history]
    merchants = [t.merchant for t in history if t.merchant]
    categories = [t.category for t in history if t.category]
    recent_24h = sum(
        1
        for t in history
        if (transaction.transaction_date - t.transaction_date).total_seconds() <= 86400
        and t.transaction_date <= transaction.transaction_date
    )

    rule = analyze_with_baseline(
        float(transaction.amount),
        transaction.merchant,
        transaction.transaction_date,
        category=transaction.category,
        history_amounts=amounts,
        history_merchants=merchants,
        history_categories=categories,
        transactions_last_24h=recent_24h,
    )
    ml_result = trainer.score_transaction(
        transaction,
        user_mean_amount=(sum(amounts) / len(amounts)) if amounts else None,
        merchant_seen_count=sum(1 for m in merchants if m and m == transaction.merchant),
        user_tx_count=len(history),
        rule_score=rule["risk_score"],
    )
    return {"rule": rule, "ml": ml_result}


def apply_analysis(transaction: Transaction, history: list[Transaction], db: Session) -> dict:
    """Score a transaction, persist the flags on the row and return an alert draft.

    The returned ``alert`` (when not ``None``) is a constructed
    :class:`FraudAlert` that the caller must ``db.add`` and commit alongside the
    transaction. The transaction's ``fraud_score`` and ``is_flagged`` are set on
    the object immediately.

    An alert is generated only when the combined confidence crosses the flag
    threshold; an ordinary unusual transaction is scored and flagged but is not
    labelled as confirmed fraud.
    """
    result = score_transaction(transaction, history, db)
    rule = result["rule"]
    ml = result["ml"]
    combined = ml.get("combined_score", rule["risk_score"])

    transaction.fraud_score = combined
    transaction.is_flagged = combined >= 30

    alert_payload = None
    if transaction.is_flagged:
        level = ml.get("risk_level", rule["risk_level"])
        alert_payload = FraudAlert(
            user_id=transaction.user_id,
            transaction_id=None,
            risk_score=combined,
            risk_level=RiskLevel(level),
            is_fraud=level == "HIGH",
            detection_layer=(
                DetectionLayer.COMBINED if ml.get("status") == "combined" else DetectionLayer.RULES
            ),
            reasons=rule["reasons"],
            amount_snapshot=Decimal(str(transaction.amount)),
            merchant_snapshot=transaction.merchant,
            category_snapshot=transaction.category,
        )
    return {"combined_score": combined, "alert": alert_payload, "ml": ml}


__all__ = [
    "apply_analysis",
    "score_transaction",
    "user_history",
]
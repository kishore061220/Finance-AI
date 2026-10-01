"""Fraud model training and scoring routes.

Training is a POST because it is expensive and state-changing, and it is
restricted to admins. The endpoints report ``insufficient_data`` or
``sklearn_unavailable`` rather than returning fabricated metrics.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_owner
from app.database.connection import get_db
from app.ml import trainer
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.common import FraudAnalysisResponse
from app.services.fraud_detection import analyze_with_baseline

router = APIRouter(prefix="/api/ml", tags=["ml"])


@router.get("/status", summary="Model availability and training state")
def model_status(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    estimator, feature_names, load_error = trainer.load()
    available, reason = trainer.check_sklearn()

    transaction_count = db.execute(
        select(Transaction.id).where(Transaction.user_id == current_user.id)
    ).all()

    return {
        "sklearn_available": available,
        "sklearn_reason": reason,
        "model_loaded": estimator is not None,
        "model_name": type(estimator).__name__ if estimator is not None else None,
        "feature_count": len(feature_names),
        "load_error": load_error,
        "user_transaction_count": len(transaction_count),
        "scoring_mode": "combined" if estimator is not None else "rules_only",
        "message": (
            "The trained model is loaded; scores combine it with the rule engine."
            if estimator is not None
            else (
                load_error
                or "No trained model is available, so scoring uses the rule engine only."
            )
        ),
    }


@router.post(
    "/train",
    summary="Train the fraud model (admin only)",
    responses={422: {"description": "Not enough data or sklearn unavailable"}},
)
def train_model(
    min_samples: int = Query(default=50, ge=10, le=10000),
    test_size: float = Query(default=0.2, gt=0.0, lt=0.5),
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    """Train from the whole user base.

    A failed or skipped training returns a report describing exactly why, with
    HTTP 422, so a caller can never mistake "not trained" for "trained".
    """
    available, reason = trainer.check_sklearn()
    if not available:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "sklearn_unavailable",
                "message": f"scikit-learn is not importable: {reason}",
            },
        )

    transactions = list(db.execute(select(Transaction)).scalars())
    labels = [1 if t.is_flagged else 0 for t in transactions]

    # The trainer enforces its own floor (MIN_TRAIN_ROWS / MIN_POSITIVE_LABELS).
    # A caller may raise the bar via min_samples but must not be able to lower
    # it below what the trainer considers safe for a split.
    required = max(min_samples, trainer.MIN_TRAIN_ROWS)

    if len(transactions) < required:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "status": "insufficient_data",
                "message": (
                    f"Training needs at least {required} labelled transactions; "
                    f"the database has {len(transactions)}."
                ),
                "available": len(transactions),
                "required": required,
            },
        )

    report = trainer.train(transactions, labels, test_size=0.2)
    if report.status != "trained":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=report.as_dict(),
        )

    result = report.as_dict()
    return result


@router.get(
    "/train/report",
    summary="Last training report",
)
def training_report(
    current_user: User = Depends(get_current_user),
) -> dict:
    """Report on the artifact already on disk - never invents metrics."""
    estimator, feature_names, load_error = trainer.load()
    if estimator is None:
        return {
            "status": "not_trained",
            "model": None,
            "feature_names": feature_names,
            "message": load_error or "No fraud model has been trained yet.",
            "metrics": None,
        }
    return {
        "status": "trained",
        "model": type(estimator).__name__,
        "feature_count": len(feature_names),
        "message": (
            "A trained model is present. Metrics are only available from the "
            "training run that produced this artifact; they are not persisted."
        ),
        "metrics": None,
    }


@router.post(
    "/score",
    response_model=FraudAnalysisResponse,
    summary="Score an unsaved transaction",
)
def score(
    amount: float = Query(..., gt=0),
    merchant: Optional[str] = Query(default=None, max_length=150),
    category: Optional[str] = Query(default=None, max_length=100),
    transaction_date: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FraudAnalysisResponse:
    """Dry-run the detector without saving anything.

    Useful for a client-side confirmation sheet: the user sees the verdict
    before the transaction is written.
    """
    from datetime import datetime

    when = datetime.fromisoformat(transaction_date) if transaction_date else datetime.utcnow()

    history = list(
        db.execute(
            select(Transaction).where(Transaction.user_id == current_user.id)
        ).scalars()
    )
    amounts = [float(t.amount) for t in history]
    merchants = [t.merchant for t in history if t.merchant]
    categories = [t.category for t in history if t.category]
    recent_24h = sum(
        1
        for t in history
        if (when - t.transaction_date).total_seconds() <= 86400
        and t.transaction_date <= when
    )

    # ``analyze_with_baseline`` degrades to the plain rule set when there is no
    # history, so a single call covers both cases and always returns ``signals``.
    rule = analyze_with_baseline(
        amount,
        merchant,
        when,
        category=category,
        history_amounts=amounts,
        history_merchants=merchants,
        history_categories=categories,
        transactions_last_24h=recent_24h,
    )

    # A plain namespace supplies the attributes the feature builder reads
    # without inventing a throwaway ORM row.
    candidate = SimpleNamespace(
        amount=amount,
        transaction_type="expense",
        emi_type=None,
        category=category or "other",
        merchant=merchant,
        transaction_date=when,
        source="MANUAL",
    )

    ml = trainer.score_transaction(
        candidate,
        user_mean_amount=(sum(amounts) / len(amounts)) if amounts else None,
        merchant_seen_count=sum(1 for m in merchants if m and m == merchant),
        user_tx_count=len(history),
        rule_score=rule["risk_score"],
    )

    return FraudAnalysisResponse(
        is_fraud=ml["risk_level"] == "HIGH",
        risk_score=rule["risk_score"],
        risk_level=rule["risk_level"],
        reasons=rule["reasons"],
        signals=rule["signals"],
        detection_layer="COMBINED" if ml["status"] == "combined" else "RULES",
        ml_score=ml.get("ml_score"),
        combined_score=ml["combined_score"],
        model=ml.get("model"),
        message=ml.get("message", ""),
    )

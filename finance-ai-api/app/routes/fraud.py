"""Fraud alert and analysis routes. Every query is scoped to the caller."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database.connection import get_db
from app.ml import trainer
from app.models.fraud_alert import DetectionLayer, FraudAlert, RiskLevel
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.common import (
    FraudAlertListResponse,
    FraudAlertResponse,
    FraudAlertUpdate,
    FraudAnalysisResponse,
)
from app.services.fraud_detection import analyze_with_baseline, summarize_alerts

router = APIRouter(prefix="/api/fraud", tags=["fraud"])

ALERT_SORTS = {
    "created_at_desc": FraudAlert.created_at.desc(),
    "created_at_asc": FraudAlert.created_at.asc(),
    "risk_score_desc": FraudAlert.risk_score.desc(),
    "risk_score_asc": FraudAlert.risk_score.asc(),
}


def _find_alert(db: Session, alert_id: int, user_id: int) -> FraudAlert:
    alert = db.get(FraudAlert, alert_id)
    if alert is None or alert.user_id != user_id:
        raise HTTPException(status_code=404, detail="Fraud alert not found")
    return alert


@router.get("/alerts", response_model=FraudAlertListResponse, summary="List alerts")
def list_alerts(
    risk_level: Optional[str] = Query(default=None, pattern="^(LOW|MEDIUM|HIGH)$"),
    unread_only: bool = Query(default=False),
    include_dismissed: bool = Query(default=False),
    start_date: Optional[datetime] = Query(default=None),
    end_date: Optional[datetime] = Query(default=None),
    sort: str = Query(default="created_at_desc"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FraudAlertListResponse:
    stmt = select(FraudAlert).where(FraudAlert.user_id == current_user.id)
    if risk_level:
        stmt = stmt.where(FraudAlert.risk_level == RiskLevel(risk_level))
    if unread_only:
        stmt = stmt.where(FraudAlert.is_read.is_(False))
    if not include_dismissed:
        stmt = stmt.where(FraudAlert.is_dismissed.is_(False))
    if start_date:
        stmt = stmt.where(FraudAlert.created_at >= start_date)
    if end_date:
        stmt = stmt.where(FraudAlert.created_at <= end_date)

    total = db.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar_one()
    unread = db.execute(
        select(func.count())
        .select_from(FraudAlert)
        .where(FraudAlert.user_id == current_user.id, FraudAlert.is_read.is_(False))
    ).scalar_one()

    by_level: dict = {}
    for level in db.execute(
        select(FraudAlert.risk_level, func.count())
        .where(FraudAlert.user_id == current_user.id)
        .group_by(FraudAlert.risk_level)
    ):
        key = level[0].value if hasattr(level[0], "value") else str(level[0])
        by_level[key] = level[1]

    order = ALERT_SORTS.get(sort)
    if order is None:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid sort '{sort}'. Allowed: {', '.join(sorted(ALERT_SORTS))}",
        )
    items = list(
        db.execute(stmt.order_by(order).limit(limit).offset(offset)).scalars()
    )
    return FraudAlertListResponse(
        items=[FraudAlertResponse.model_validate(i) for i in items],
        total=total,
        unread=unread,
        by_level=by_level,
    )


@router.get("/alerts/{alert_id}", response_model=FraudAlertResponse, summary="Get alert")
def get_alert(
    alert_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FraudAlert:
    return _find_alert(db, alert_id, current_user.id)


@router.patch(
    "/alerts/{alert_id}", response_model=FraudAlertResponse, summary="Update alert"
)
def update_alert(
    alert_id: int,
    payload: FraudAlertUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FraudAlert:
    alert = _find_alert(db, alert_id, current_user.id)
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(alert, field, value)
    db.commit()
    db.refresh(alert)
    return alert


@router.post("/alerts/{alert_id}/read", response_model=FraudAlertResponse, summary="Mark read")
def mark_read(
    alert_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FraudAlert:
    alert = _find_alert(db, alert_id, current_user.id)
    alert.is_read = True
    db.commit()
    db.refresh(alert)
    return alert


@router.post(
    "/alerts/{alert_id}/dismiss", response_model=FraudAlertResponse, summary="Dismiss"
)
def dismiss(
    alert_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FraudAlert:
    alert = _find_alert(db, alert_id, current_user.id)
    alert.is_dismissed = True
    alert.is_read = True
    db.commit()
    db.refresh(alert)
    return alert


@router.get("/summary", summary="Alert counts for the caller")
def summary(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    rows = list(
        db.execute(
            select(FraudAlert).where(FraudAlert.user_id == current_user.id)
        ).scalars()
    )
    return summarize_alerts(rows)


@router.get(
    "/analyze/{transaction_id}",
    response_model=FraudAnalysisResponse,
    summary="Re-score a saved transaction",
)
def analyze(
    transaction_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FraudAnalysisResponse:
    """Re-run detection for one of the caller's transactions.

    Useful after the ML model is trained, or to see the effect of the user's
    now-larger baseline.
    """
    transaction = db.get(Transaction, transaction_id)
    if transaction is None or transaction.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Transaction not found")

    history = list(
        db.execute(
            select(Transaction).where(
                Transaction.user_id == current_user.id,
                Transaction.id != transaction.id,
            )
        ).scalars()
    )
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
    ml = trainer.score_transaction(
        transaction,
        user_mean_amount=(sum(amounts) / len(amounts)) if amounts else None,
        merchant_seen_count=sum(
            1 for m in merchants if m and m == transaction.merchant
        ),
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

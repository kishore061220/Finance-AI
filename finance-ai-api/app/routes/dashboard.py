"""Dashboard and analytics routes.

All figures are computed from the authenticated user's own rows. The previous
implementation returned global aggregates, so every user saw every other
user's finances.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database.connection import get_db
from app.models.budget import Budget
from app.models.fraud_alert import FraudAlert
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.common import (
    CategoryBreakdownResponse,
    DailySeriesResponse,
    DashboardResponse,
    FraudSummaryResponse,
    InsightResponse,
    MerchantBreakdownResponse,
    MonthlyTrendResponse,
    PredictionResponse,
    RecurringResponse,
    TotalsResponse,
)
from app.services.analytics import (
    budget_progress,
    category_breakdown,
    daily_series,
    detect_recurring,
    filter_period,
    generate_insights,
    merchant_breakdown,
    month_bounds,
    monthly_series,
    totals,
)
from app.services.prediction import build_prediction_report

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _load(db: Session, user_id: int, start: Optional[datetime], end: Optional[datetime]):
    stmt = select(Transaction).where(Transaction.user_id == user_id)
    if start or end:
        stmt = stmt.where(Transaction.transaction_date >= (start or datetime.min))
        if end:
            stmt = stmt.where(Transaction.transaction_date <= end)
    return list(db.execute(stmt.order_by(Transaction.transaction_date.desc())).scalars())


@router.get("", response_model=DashboardResponse, summary="Full dashboard")
def dashboard(
    month: Optional[int] = Query(default=None, ge=1, le=12),
    year: Optional[int] = Query(default=None, ge=2000, le=2200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DashboardResponse:
    now = datetime.utcnow()
    month = month or now.month
    year = year or now.year
    start, end = month_bounds(year, month)

    transactions = _load(db, current_user.id, start, end)
    budgets = list(
        db.execute(
            select(Budget).where(
                Budget.user_id == current_user.id,
                Budget.month == month,
                Budget.year == year,
            )
        ).scalars()
    )

    alert_filter = FraudAlert.user_id == current_user.id
    if start and end:
        alert_filter = alert_filter & (FraudAlert.created_at >= start)
    if end:
        alert_filter = alert_filter & (FraudAlert.created_at <= end)
    alert_rows = list(db.execute(select(FraudAlert).where(alert_filter)).scalars())

    by_level: dict = {}
    for a in alert_rows:
        key = a.risk_level.value
        by_level[key] = by_level.get(key, 0) + 1

    return DashboardResponse(
        totals=TotalsResponse(**totals(transactions)),
        category_breakdown=[
            CategoryBreakdownResponse(**r) for r in category_breakdown(transactions)
        ],
        top_merchants=[
            MerchantBreakdownResponse(**r) for r in merchant_breakdown(transactions, 10)
        ],
        budget_progress=budget_progress(budgets, transactions),
        monthly_trend=[MonthlyTrendResponse(**m) for m in monthly_series(transactions)],
        insights=[InsightResponse(**i) for i in generate_insights(transactions, budgets)],
        fraud_summary=FraudSummaryResponse(
            total=len(alert_rows), unread=sum(1 for a in alert_rows if not a.is_read)
        ),
        recurring=[RecurringResponse(**r) for r in detect_recurring(transactions)],
        generated_at=datetime.utcnow().isoformat() + "Z",
    )


@router.get("/summary", response_model=TotalsResponse, summary="Totals only")
def summary(
    start_date: Optional[datetime] = Query(default=None),
    end_date: Optional[datetime] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TotalsResponse:
    transactions = _load(db, current_user.id, start_date, end_date)
    return TotalsResponse(**totals(transactions))


@router.get(
    "/categories",
    response_model=list[CategoryBreakdownResponse],
    summary="Spending by category",
)
def categories(
    start_date: Optional[datetime] = Query(default=None),
    end_date: Optional[datetime] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list:
    transactions = _load(db, current_user.id, start_date, end_date)
    return [CategoryBreakdownResponse(**r) for r in category_breakdown(transactions)]


@router.get(
    "/merchants",
    response_model=list[MerchantBreakdownResponse],
    summary="Top merchants",
)
def merchants(
    limit: int = Query(default=10, ge=1, le=50),
    start_date: Optional[datetime] = Query(default=None),
    end_date: Optional[datetime] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list:
    transactions = _load(db, current_user.id, start_date, end_date)
    return [
        MerchantBreakdownResponse(**r)
        for r in merchant_breakdown(transactions, limit)
    ]


@router.get(
    "/trends", response_model=list[MonthlyTrendResponse], summary="Monthly income/expense"
)
def trends(
    months: int = Query(default=12, ge=1, le=60),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list:
    # The trend must span several months, so it reads the full history and
    # then keeps the most recent ``months`` buckets.
    transactions = _load(db, current_user.id, None, None)
    series = monthly_series(transactions)
    return [MonthlyTrendResponse(**m) for m in series[-months:]]


@router.get(
    "/daily", response_model=list[DailySeriesResponse], summary="Daily expense series"
)
def daily(
    days: int = Query(default=30, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list:
    transactions = _load(db, current_user.id, None, None)
    return [DailySeriesResponse(**d) for d in daily_series(transactions, days)]


@router.get(
    "/insights", response_model=list[InsightResponse], summary="Explainable insights"
)
def insights(
    month: Optional[int] = Query(default=None, ge=1, le=12),
    year: Optional[int] = Query(default=None, ge=2000, le=2200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list:
    now = datetime.utcnow()
    month = month or now.month
    year = year or now.year
    start, end = month_bounds(year, month)

    transactions = _load(db, current_user.id, start, end)
    budgets = list(
        db.execute(
            select(Budget).where(
                Budget.user_id == current_user.id,
                Budget.month == month,
                Budget.year == year,
            )
        ).scalars()
    )
    return [InsightResponse(**i) for i in generate_insights(transactions, budgets)]


@router.get(
    "/recurring", response_model=list[RecurringResponse], summary="Recurring payments"
)
def recurring(
    min_occurrences: int = Query(default=3, ge=2, le=24),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list:
    transactions = _load(db, current_user.id, None, None)
    return [
        RecurringResponse(**r)
        for r in detect_recurring(transactions, min_occurrences)
    ]


@router.get(
    "/prediction",
    response_model=PredictionResponse,
    summary="Spending forecast for the next month",
)
def prediction(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> PredictionResponse:
    """Project next month's expenses from the caller's own history.

    Returns ``status="insufficient_data"`` with a null prediction when there is
    not enough history to justify a figure. That is a deliberate 200, not an
    error: "keep recording expenses and this will appear" is the correct answer,
    and a 404 or a fabricated number would both be worse.
    """
    transactions = _load(db, current_user.id, None, None)
    now = datetime.utcnow()
    budgets = list(
        db.execute(
            select(Budget).where(
                Budget.user_id == current_user.id,
                Budget.month == now.month,
                Budget.year == now.year,
            )
        ).scalars()
    )
    return PredictionResponse(**build_prediction_report(transactions, budgets))


@router.get("/health", summary="Data volume for the caller")
def data_health(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    transaction_count = db.execute(
        select(func.count())
        .select_from(Transaction)
        .where(Transaction.user_id == current_user.id)
    ).scalar_one()
    budget_count = db.execute(
        select(func.count())
        .select_from(Budget)
        .where(Budget.user_id == current_user.id)
    ).scalar_one()

    transactions = _load(db, current_user.id, None, None)
    now = datetime.utcnow()
    this_month = filter_period(transactions, *month_bounds(now.year, now.month))
    return {
        "transaction_count": transaction_count,
        "budget_count": budget_count,
        "transactions_this_month": len(this_month),
        "spending_insights_available": transaction_count >= 3,
    }

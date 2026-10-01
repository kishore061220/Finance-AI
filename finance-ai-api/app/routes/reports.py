"""Report generation routes.

Reports are rendered on demand and returned as a file download. A
``Report`` row records what was produced so the app can show a history. The
generated file itself is not retained - only its size, row count and checksum.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database.connection import get_db
from app.models.budget import Budget
from app.models.fraud_alert import FraudAlert
from app.models.loan import Loan
from app.models.report import Report, ReportFormat, ReportType
from app.models.transaction import Transaction, TransactionType
from app.models.user import User
from app.schemas.common import ReportRequest, ReportResponse
from app.services import report_generator as generator
from app.services.analytics import category_breakdown, monthly_series, totals

router = APIRouter(prefix="/api/reports", tags=["reports"])

EXTENSIONS = {"CSV": "csv", "EXCEL": "xlsx", "PDF": "pdf"}


def _transactions_in_period(
    db: Session, user_id: int, start: Optional[datetime], end: Optional[datetime]
) -> List[Transaction]:
    stmt = select(Transaction).where(Transaction.user_id == user_id)
    if start:
        stmt = stmt.where(Transaction.transaction_date >= start)
    if end:
        stmt = stmt.where(Transaction.transaction_date <= end)
    return list(
        db.execute(stmt.order_by(Transaction.transaction_date.desc())).scalars()
    )


def _build_rows(
    db: Session, user_id: int, payload: ReportRequest
) -> Tuple[str, Tuple[str, ...], List[Dict], str]:
    """Return ``(report_type, columns, rows, title)`` for the request."""
    report_type = payload.report_type
    txs = _transactions_in_period(db, user_id, payload.period_start, payload.period_end)

    if report_type in ("TRANSACTIONS", "INCOME", "EXPENSES"):
        rows = txs
        if report_type == "INCOME":
            rows = [t for t in rows if t.transaction_type == TransactionType.INCOME]
        elif report_type == "EXPENSES":
            rows = [t for t in rows if t.transaction_type == TransactionType.EXPENSE]
        if payload.category:
            rows = [t for t in rows if t.category == payload.category]
        return (
            report_type,
            generator.TRANSACTION_COLUMNS,
            [generator.transaction_row(t) for t in rows],
            f"{report_type.title()} Transactions",
        )

    if report_type == "CATEGORIES":
        t = totals(txs)
        return (
            report_type,
            generator.CATEGORY_COLUMNS,
            generator.category_rows(txs, t),
            "Spending by Category",
        )

    if report_type == "SPENDING_TRENDS":
        return (
            report_type,
            generator.TREND_COLUMNS,
            generator.spending_trend_rows(txs),
            "Spending Trend",
        )

    if report_type == "BUDGETS":
        stmt = select(Budget).where(Budget.user_id == user_id)
        if payload.period_start:
            stmt = stmt.where(
                (Budget.year * 100 + Budget.month)
                >= (payload.period_start.year * 100 + payload.period_start.month)
            )
        if payload.period_end:
            stmt = stmt.where(
                (Budget.year * 100 + Budget.month)
                <= (payload.period_end.year * 100 + payload.period_end.month)
            )
        budgets = list(db.execute(stmt.order_by(Budget.year, Budget.month)).scalars())
        return (
            report_type,
            generator.BUDGET_COLUMNS,
            [generator.budget_row(b) for b in budgets],
            "Budgets",
        )

    if report_type == "FRAUD":
        stmt = select(FraudAlert).where(FraudAlert.user_id == user_id)
        if payload.period_start:
            stmt = stmt.where(FraudAlert.created_at >= payload.period_start)
        if payload.period_end:
            stmt = stmt.where(FraudAlert.created_at <= payload.period_end)
        alerts = list(
            db.execute(stmt.order_by(FraudAlert.created_at.desc())).scalars()
        )
        return (
            report_type,
            generator.FRAUD_COLUMNS,
            [generator.fraud_row(a) for a in alerts],
            "Fraud Alerts",
        )

    if report_type == "LOANS":
        loans = list(
            db.execute(select(Loan).where(Loan.user_id == user_id)).scalars()
        )
        return (
            report_type,
            generator.LOAN_COLUMNS,
            [generator.loan_row(l) for l in loans],
            "Loans",
        )

    raise HTTPException(
        status_code=422, detail=f"Unsupported report type: {report_type}"
    )


@router.get("/types", summary="Available report types")
def report_types(current_user: User = Depends(get_current_user)) -> dict:
    return {
        "report_types": [t.value for t in ReportType],
        "report_formats": [f.value for f in ReportFormat],
    }


@router.post("/generate", summary="Generate and download a report")
def generate_report(
    payload: ReportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    report_type, columns, rows, title = _build_rows(db, current_user.id, payload)

    try:
        blob, row_count, media_type = generator.generate(
            payload.report_format, columns, rows, title
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    from app.services.backup import checksum

    record = Report(
        user_id=current_user.id,
        report_type=ReportType(report_type),
        report_format=ReportFormat(payload.report_format),
        period_start=payload.period_start,
        period_end=payload.period_end,
        category=payload.category,
        row_count=row_count,
        file_size_bytes=len(blob),
        checksum=checksum(blob),
        parameters={"columns": list(columns)},
    )
    db.add(record)
    db.commit()

    extension = EXTENSIONS[payload.report_format]
    filename = (
        f"finance-ai-{report_type.lower()}-{datetime.utcnow():%Y%m%d-%H%M%S}.{extension}"
    )
    return StreamingResponse(
        io.BytesIO(blob),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Report-Id": str(record.id),
            "X-Row-Count": str(row_count),
        },
    )


@router.get("", response_model=List[ReportResponse], summary="Report history")
def list_reports(
    report_type: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[Report]:
    stmt = select(Report).where(Report.user_id == current_user.id)
    if report_type:
        stmt = stmt.where(Report.report_type == ReportType(report_type))
    return list(
        db.execute(stmt.order_by(Report.created_at.desc()).limit(limit)).scalars()
    )

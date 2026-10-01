"""Budget routes.

All access is scoped to ``current_user.id``. The legacy implementation read
``user_id`` from a query string, which let any caller see or edit another
user's budgets.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database.connection import get_db
from app.models.budget import Budget
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.budget import (
    BudgetCreate,
    BudgetListResponse,
    BudgetResponse,
    BudgetUpdate,
)
from app.services.analytics import budget_progress, month_bounds

router = APIRouter(prefix="/api/budgets", tags=["budgets"])


def _period_expenses(
    db: Session, user_id: int, year: int, month: int
):
    start, end = month_bounds(year, month)
    return list(
        db.execute(
            select(Transaction).where(
                Transaction.user_id == user_id,
                Transaction.transaction_date >= start,
                Transaction.transaction_date <= end,
            )
        ).scalars()
    )


def _find(db: Session, budget_id: int, user_id: int) -> Budget:
    budget = db.get(Budget, budget_id)
    if budget is None or budget.user_id != user_id:
        # 404 rather than 403 so we never confirm another user's records exist.
        raise HTTPException(status_code=404, detail="Budget not found")
    return budget


@router.post(
    "",
    response_model=BudgetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a budget",
)
def create_budget(
    payload: BudgetCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Budget:
    existing = db.execute(
        select(Budget).where(
            Budget.user_id == current_user.id,
            Budget.category == payload.category,
            Budget.month == payload.month,
            Budget.year == payload.year,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A budget for '{payload.category}' already exists for "
                f"{payload.year}-{payload.month:02d}."
            ),
        )

    budget = Budget(user_id=current_user.id, **payload.model_dump())
    db.add(budget)
    db.commit()
    db.refresh(budget)
    return budget


@router.get("", response_model=BudgetListResponse, summary="Budgets with progress")
def list_budgets(
    month: Optional[int] = Query(default=None, ge=1, le=12),
    year: Optional[int] = Query(default=None, ge=2000, le=2200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BudgetListResponse:
    now = datetime.utcnow()
    month = month or now.month
    year = year or now.year

    budgets = list(
        db.execute(
            select(Budget)
            .where(
                Budget.user_id == current_user.id,
                Budget.month == month,
                Budget.year == year,
            )
            .order_by(Budget.category)
        ).scalars()
    )
    transactions = _period_expenses(db, current_user.id, year, month)
    progress = budget_progress(budgets, transactions)
    return BudgetListResponse(
        items=progress, total=len(progress), month=month, year=year
    )


@router.get(
    "/period/{year}/{month}", response_model=BudgetListResponse, summary="By period"
)
def budgets_for_period(
    year: int,
    month: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BudgetListResponse:
    if not 1 <= month <= 12:
        raise HTTPException(status_code=422, detail="month must be between 1 and 12")
    budgets = list(
        db.execute(
            select(Budget)
            .where(
                Budget.user_id == current_user.id,
                Budget.month == month,
                Budget.year == year,
            )
            .order_by(Budget.category)
        ).scalars()
    )
    progress = budget_progress(
        budgets, _period_expenses(db, current_user.id, year, month)
    )
    return BudgetListResponse(
        items=progress, total=len(progress), month=month, year=year
    )


@router.get("/{budget_id}", response_model=BudgetResponse, summary="Get one")
def get_budget(
    budget_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Budget:
    return _find(db, budget_id, current_user.id)


@router.patch("/{budget_id}", response_model=BudgetResponse, summary="Update")
def update_budget(
    budget_id: int,
    payload: BudgetUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Budget:
    budget = _find(db, budget_id, current_user.id)
    data = payload.model_dump(exclude_unset=True)

    # Changing category or period can collide with an existing budget.
    candidate_category = data.get("category", budget.category)
    candidate_month = data.get("month", budget.month)
    candidate_year = data.get("year", budget.year)
    clash = db.execute(
        select(Budget).where(
            Budget.user_id == current_user.id,
            Budget.category == candidate_category,
            Budget.month == candidate_month,
            Budget.year == candidate_year,
            Budget.id != budget.id,
        )
    ).scalar_one_or_none()
    if clash is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Another budget already exists for that category and period.",
        )

    for field, value in data.items():
        setattr(budget, field, value)
    db.commit()
    db.refresh(budget)
    return budget


@router.delete(
    "/{budget_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete"
)
def delete_budget(
    budget_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    budget = _find(db, budget_id, current_user.id)
    db.delete(budget)
    db.commit()

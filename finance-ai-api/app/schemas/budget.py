"""Budget schemas."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.user import ORMModel


def _validate_period(month: int, year: int) -> None:
    if not 1 <= month <= 12:
        raise ValueError("month must be between 1 and 12")
    if not 2000 <= year <= 2200:
        raise ValueError("year must be between 2000 and 2200")


class BudgetCreate(BaseModel):
    """``user_id`` removed: budgets are always created for the caller."""

    category: str = Field(..., min_length=1, max_length=100)
    amount: Decimal = Field(..., gt=0, max_digits=12, decimal_places=2)
    month: int = Field(..., ge=1, le=12)
    year: int = Field(..., ge=2000, le=2200)

    @field_validator("category")
    @classmethod
    def _strip_category(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("category cannot be blank")
        return v


class BudgetUpdate(BaseModel):
    category: Optional[str] = Field(default=None, min_length=1, max_length=100)
    amount: Optional[Decimal] = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    month: Optional[int] = Field(default=None, ge=1, le=12)
    year: Optional[int] = Field(default=None, ge=2000, le=2200)

    @model_validator(mode="after")
    def _check_period(self):
        if self.month is not None and self.year is not None:
            _validate_period(self.month, self.year)
        return self


class BudgetResponse(ORMModel):
    id: int
    user_id: int
    category: str
    amount: Decimal
    month: int
    year: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class BudgetProgressResponse(BaseModel):
    budget_id: int
    category: str
    month: int
    year: int
    limit: Decimal
    spent: Decimal
    remaining: Decimal
    used_percent: float
    status: str


class BudgetListResponse(BaseModel):
    items: List[BudgetProgressResponse]
    total: int
    month: int
    year: int


__all__ = [
    "BudgetCreate",
    "BudgetListResponse",
    "BudgetProgressResponse",
    "BudgetResponse",
    "BudgetUpdate",
]

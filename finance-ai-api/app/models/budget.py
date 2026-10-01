"""Budget model."""

from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base
from app.models.base import TimestampMixin


class Budget(Base, TimestampMixin):
    __tablename__ = "budgets"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_budgets_amount_positive"),
        CheckConstraint("month >= 1 AND month <= 12", name="ck_budgets_month_range"),
        CheckConstraint("year >= 2000 AND year <= 2200", name="ck_budgets_year_range"),
        UniqueConstraint(
            "user_id", "category", "month", "year", name="uq_budgets_user_category_period"
        ),
        Index("ix_budgets_user_period", "user_id", "year", "month"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)

    user: Mapped["User"] = relationship(back_populates="budgets")  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Budget id={self.id} user={self.user_id} {self.category} {self.amount}>"
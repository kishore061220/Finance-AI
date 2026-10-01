"""Audit archive tables.

These tables exist so a data-hygiene migration can move rows aside instead of
deleting them. They are intentionally **not** mapped as live business entities:
there are no foreign keys (the row they referenced may no longer exist) and no
cascades, so archived data can never be mutated or removed by ordinary
application code.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base


class BudgetArchive(Base):
    """Superseded budget rows moved aside by the 0004 migration.

    The database enforces one budget per (user, category, month, year). Rows
    that violated that rule predate the constraint, so rather than deleting
    them the migration copied them here first. This table is the audit trail.
    """

    __tablename__ = "budgets_duplicate_archive"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<BudgetArchive id={self.id} user={self.user_id} "
            f"{self.category} {self.year}-{self.month}>"
        )

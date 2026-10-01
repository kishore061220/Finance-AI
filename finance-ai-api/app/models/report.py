"""Generated report audit trail."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base
from app.models.base import StrEnum, TimestampMixin


class ReportFormat(StrEnum):
    CSV = "CSV"
    EXCEL = "EXCEL"
    PDF = "PDF"


class ReportType(StrEnum):
    TRANSACTIONS = "TRANSACTIONS"
    INCOME = "INCOME"
    EXPENSES = "EXPENSES"
    CATEGORIES = "CATEGORIES"
    FRAUD = "FRAUD"
    BUDGETS = "BUDGETS"
    SPENDING_TRENDS = "SPENDING_TRENDS"
    LOANS = "LOANS"


def _enum(enum_cls):
    return Enum(enum_cls, values_callable=lambda e: [m.value for m in e])


class Report(Base, TimestampMixin):
    __tablename__ = "reports"
    __table_args__ = (Index("ix_reports_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    report_type: Mapped[ReportType] = mapped_column(_enum(ReportType), nullable=False)
    report_format: Mapped[ReportFormat] = mapped_column(
        _enum(ReportFormat), nullable=False
    )
    period_start: Mapped[Optional[datetime]] = mapped_column(DateTime)
    period_end: Mapped[Optional[datetime]] = mapped_column(DateTime)
    category: Mapped[Optional[str]] = mapped_column(String(100))
    row_count: Mapped[Optional[int]] = mapped_column(Integer)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(Integer)
    checksum: Mapped[Optional[str]] = mapped_column(String(64))
    parameters: Mapped[Optional[dict]] = mapped_column(JSON)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Report id={self.id} user={self.user_id} {self.report_type}/{self.report_format}>"
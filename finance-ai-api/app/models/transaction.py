"""Transaction model with income/expense/EMI support and source tracking."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    text,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base
from app.models.base import StrEnum, TimestampMixin


class TransactionType(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"


class TransactionSource(StrEnum):
    MANUAL = "MANUAL"
    SMS = "SMS"
    OCR = "OCR"
    IMPORT = "IMPORT"


class EmiType(StrEnum):
    HOME_LOAN = "Home Loan"
    CAR_LOAN = "Car Loan"
    PERSONAL_LOAN = "Personal Loan"
    EDUCATION_LOAN = "Education Loan"
    CREDIT_CARD = "Credit Card"
    OTHER = "Other"


def _enum(enum_cls):
    """Build an Enum column that persists the enum *values*."""
    return Enum(
        enum_cls,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


class Transaction(Base, TimestampMixin):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
        CheckConstraint(
            "transaction_type IN ('income','expense')",
            name="ck_transactions_type_valid",
        ),
        Index("ix_transactions_user_date", "user_id", "transaction_date"),
        Index("ix_transactions_user_type_date", "user_id", "transaction_type", "transaction_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    transaction_type: Mapped[TransactionType] = mapped_column(
        _enum(TransactionType), nullable=False, default=TransactionType.EXPENSE
    )
    # Changed from FLOAT to NUMERIC to remove binary floating point drift on money.
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    emi_type: Mapped[Optional[str]] = mapped_column(String(100))

    merchant: Mapped[Optional[str]] = mapped_column(String(150))
    description: Mapped[Optional[str]] = mapped_column(Text)
    transaction_date: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, index=True
    )

    source: Mapped[TransactionSource] = mapped_column(
        _enum(TransactionSource),
        nullable=False,
        default=TransactionSource.MANUAL,
        server_default=TransactionSource.MANUAL.value,
    )
    bank_reference: Mapped[Optional[str]] = mapped_column(String(120), index=True)
    # Populated by SMS/OCR so the user can review the original evidence.
    raw_source_text: Mapped[Optional[str]] = mapped_column(Text)
    categorization_source: Mapped[Optional[str]] = mapped_column(String(32))

    fraud_score: Mapped[Optional[int]] = mapped_column(Integer)
    is_flagged: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )

    user: Mapped["User"] = relationship(back_populates="transactions")  # noqa: F821
    fraud_alerts: Mapped[List["FraudAlert"]] = relationship(  # noqa: F821
        back_populates="transaction", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<Transaction id={self.id} user={self.user_id} "
            f"{self.transaction_type} {self.amount} {self.category}>"
        )
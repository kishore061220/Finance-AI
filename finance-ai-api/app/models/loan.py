"""Loan and loan payment models."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base
from app.models.base import StrEnum, TimestampMixin


class LoanType(StrEnum):
    HOME = "Home Loan"
    CAR = "Car Loan"
    PERSONAL = "Personal Loan"
    EDUCATION = "Education Loan"
    BUSINESS = "Business Loan"
    OTHER = "Other"


class LoanStatus(StrEnum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    FORECLOSED = "FORECLOSED"


class PaymentStatus(StrEnum):
    PENDING = "PENDING"
    PAID = "PAID"
    OVERDUE = "OVERDUE"


def _enum(enum_cls):
    return Enum(enum_cls, values_callable=lambda e: [m.value for m in e])


class Loan(Base, TimestampMixin):
    __tablename__ = "loans"
    __table_args__ = (
        CheckConstraint("principal > 0", name="ck_loans_principal_positive"),
        CheckConstraint("interest_rate >= 0", name="ck_loans_rate_non_negative"),
        CheckConstraint("tenure_months > 0", name="ck_loans_tenure_positive"),
        Index("ix_loans_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    lender: Mapped[Optional[str]] = mapped_column(String(150))
    loan_type: Mapped[LoanType] = mapped_column(
        _enum(LoanType), nullable=False, default=LoanType.OTHER
    )
    principal: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    interest_rate: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    tenure_months: Mapped[int] = mapped_column(Integer, nullable=False)
    # Monthly EMI - computed by the service layer, stored for stability.
    monthly_emi: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total_payable: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[LoanStatus] = mapped_column(
        _enum(LoanStatus), nullable=False, default=LoanStatus.ACTIVE
    )
    notes: Mapped[Optional[str]] = mapped_column(String(255))

    user: Mapped["User"] = relationship(back_populates="loans")  # noqa: F821
    payments: Mapped[List["LoanPayment"]] = relationship(
        back_populates="loan", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Loan id={self.id} user={self.user_id} {self.name} emi={self.monthly_emi}>"


class LoanPayment(Base, TimestampMixin):
    __tablename__ = "loan_payments"
    __table_args__ = (
        Index("ix_loan_payments_loan_due", "loan_id", "due_date"),
        UniqueConstraint(
            "loan_id", "installment_number", name="uq_loan_payments_installment"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    loan_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("loans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    installment_number: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    principal_component: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    interest_component: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    paid_date: Mapped[Optional[date]] = mapped_column(Date)
    status: Mapped[PaymentStatus] = mapped_column(
        _enum(PaymentStatus), nullable=False, default=PaymentStatus.PENDING
    )
    transaction_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("transactions.id", ondelete="SET NULL")
    )

    loan: Mapped["Loan"] = relationship(back_populates="payments")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<LoanPayment id={self.id} loan={self.loan_id} #{self.installment_number} {self.status}>"
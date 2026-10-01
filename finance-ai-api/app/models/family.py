"""Family expense sharing models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base
from app.models.base import StrEnum, TimestampMixin


class FamilyRole(StrEnum):
    OWNER = "OWNER"
    MEMBER = "MEMBER"


class MemberStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


def _enum(enum_cls):
    return Enum(enum_cls, values_callable=lambda e: [m.value for m in e])


class FamilyGroup(Base, TimestampMixin):
    __tablename__ = "family_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    owner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    description: Mapped[Optional[str]] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("1"))

    owner: Mapped["User"] = relationship(foreign_keys=[owner_id])
    members: Mapped[List["FamilyMember"]] = relationship(
        back_populates="family", cascade="all, delete-orphan"
    )
    shared_expenses: Mapped[List["SharedExpense"]] = relationship(
        back_populates="family", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<FamilyGroup id={self.id} name={self.name!r} owner={self.owner_id}>"


class FamilyMember(Base, TimestampMixin):
    __tablename__ = "family_members"
    __table_args__ = (
        UniqueConstraint("family_id", "user_id", name="uq_family_members_family_user"),
        Index("ix_family_members_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    family_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("family_groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # NULL until the invite is accepted by that user, so an email-only invite
    # can exist before the recipient has ever signed in.
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # Which account the invitation was addressed to.
    invited_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    invited_email: Mapped[Optional[str]] = mapped_column(String(150))
    role: Mapped[FamilyRole] = mapped_column(
        _enum(FamilyRole), nullable=False, default=FamilyRole.MEMBER
    )
    status: Mapped[MemberStatus] = mapped_column(
        _enum(MemberStatus), nullable=False, default=MemberStatus.PENDING
    )
    can_view_all: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    joined_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    family: Mapped["FamilyGroup"] = relationship(back_populates="members")
    user: Mapped[Optional["User"]] = relationship(foreign_keys=[user_id])
    invited_user: Mapped[Optional["User"]] = relationship(foreign_keys=[invited_user_id])

    def __repr__(self) -> str:  # pragma: no cover
        return f"<FamilyMember id={self.id} family={self.family_id} user={self.user_id} {self.status}>"


class SharedExpense(Base, TimestampMixin):
    __tablename__ = "shared_expenses"
    __table_args__ = (Index("ix_shared_expenses_family_date", "family_id", "expense_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    family_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("family_groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    transaction_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("transactions.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255))
    category: Mapped[Optional[str]] = mapped_column(String(100))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    expense_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_settled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("0"))

    family: Mapped["FamilyGroup"] = relationship(back_populates="shared_expenses")
    created_by: Mapped["User"] = relationship()
    splits: Mapped[List["ExpenseSplit"]] = relationship(
        back_populates="shared_expense", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SharedExpense id={self.id} family={self.family_id} {self.total_amount}>"


class ExpenseSplit(Base, TimestampMixin):
    __tablename__ = "expense_splits"
    __table_args__ = (
        UniqueConstraint("shared_expense_id", "user_id", name="uq_expense_splits_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    shared_expense_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("shared_expenses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owed_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # MySQL normalises a DECIMAL default of 0 to 0.00, so declare it that way
    # to keep `alembic check` clean.
    settled_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00"), server_default=text("0.00")
    )
    is_settled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("0"))

    shared_expense: Mapped["SharedExpense"] = relationship(back_populates="splits")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ExpenseSplit id={self.id} expense={self.shared_expense_id} user={self.user_id}>"
"""User model.

Existing production rows are preserved: ``firebase_uid`` and ``email_verified``
are nullable so the legacy ``id``/``email``/``password_hash`` identity keeps
working while Firebase Authentication is rolled out.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, Enum, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base
from app.models.base import StrEnum, TimestampMixin


class UserRole(StrEnum):
    OWNER = "OWNER"
    MEMBER = "MEMBER"


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # Email stays the business-unique contact identity and remains NOT NULL,
    # matching the legacy schema. Firebase UID is the authentication identity.
    email: Mapped[str] = mapped_column(
        String(150), unique=True, index=True, nullable=False
    )
    # Firebase subject (the Firebase UID). Nullable for pre-migration rows.
    firebase_uid: Mapped[Optional[str]] = mapped_column(
        String(128), unique=True, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Renamed from ``password``; nullable because Firebase users have no password.
    password_hash: Mapped[Optional[str]] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=UserRole.MEMBER,
        server_default=text("'MEMBER'"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    email_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    phone_number: Mapped[Optional[str]] = mapped_column(String(32))
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Relationships
    transactions: Mapped[List["Transaction"]] = relationship(  # noqa: F821
        back_populates="user", cascade="all, delete-orphan"
    )
    budgets: Mapped[List["Budget"]] = relationship(  # noqa: F821
        back_populates="user", cascade="all, delete-orphan"
    )
    fraud_alerts: Mapped[List["FraudAlert"]] = relationship(  # noqa: F821
        back_populates="user", cascade="all, delete-orphan"
    )
    loans: Mapped[List["Loan"]] = relationship(  # noqa: F821
        back_populates="user", cascade="all, delete-orphan"
    )
    notifications: Mapped[List["Notification"]] = relationship(  # noqa: F821
        back_populates="user", cascade="all, delete-orphan"
    )
    device_tokens: Mapped[List["DeviceToken"]] = relationship(  # noqa: F821
        back_populates="user", cascade="all, delete-orphan"
    )
    backup_records: Mapped[List["BackupRecord"]] = relationship(  # noqa: F821
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def is_anonymous_placeholder(self) -> bool:  # pragma: no cover - helper
        return self.firebase_uid is None and self.email is None

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<User id={self.id} email={self.email} uid={self.firebase_uid}>"
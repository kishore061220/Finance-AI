"""In-app notification model."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base
from app.models.base import StrEnum, TimestampMixin


class NotificationType(StrEnum):
    FRAUD_ALERT = "FRAUD_ALERT"
    BUDGET_WARNING = "BUDGET_WARNING"
    LOAN_DUE = "LOAN_DUE"
    FAMILY = "FAMILY"
    SYSTEM = "SYSTEM"
    ASSISTANT = "ASSISTANT"


def _enum(enum_cls):
    return Enum(enum_cls, values_callable=lambda e: [m.value for m in e])


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_read", "user_id", "is_read"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    notification_type: Mapped[NotificationType] = mapped_column(
        _enum(NotificationType), nullable=False, default=NotificationType.SYSTEM
    )
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    # Deliberately short: push previews must not leak full financial detail.
    body: Mapped[str] = mapped_column(String(255), nullable=False)
    data: Mapped[Optional[dict]] = mapped_column(JSON)
    is_read: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    # Link target, e.g. "fraud_alert:42"
    deep_link: Mapped[Optional[str]] = mapped_column(String(120))

    user: Mapped["User"] = relationship(back_populates="notifications")  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Notification id={self.id} user={self.user_id} {self.notification_type}>"
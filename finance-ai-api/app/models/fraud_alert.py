"""Fraud alert model - one row per detection."""

from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    text,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base
from app.models.base import StrEnum, TimestampMixin


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class DetectionLayer(StrEnum):
    RULES = "RULES"
    ML = "ML"
    COMBINED = "COMBINED"


def _enum(enum_cls):
    return Enum(enum_cls, values_callable=lambda e: [m.value for m in e])


class FraudAlert(Base, TimestampMixin):
    __tablename__ = "fraud_alerts"
    __table_args__ = (
        Index("ix_fraud_alerts_user_created", "user_id", "created_at"),
        Index("ix_fraud_alerts_user_read", "user_id", "is_read"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    transaction_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("transactions.id", ondelete="CASCADE"), index=True
    )

    risk_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    risk_level: Mapped[RiskLevel] = mapped_column(
        _enum(RiskLevel), nullable=False, default=RiskLevel.LOW
    )
    is_fraud: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )

    detection_layer: Mapped[DetectionLayer] = mapped_column(
        _enum(DetectionLayer),
        nullable=False,
        default=DetectionLayer.RULES,
        server_default=text("'RULES'"),
    )
    reasons: Mapped[Optional[list]] = mapped_column(JSON)

    amount_snapshot: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    merchant_snapshot: Mapped[Optional[str]] = mapped_column(String(150))
    category_snapshot: Mapped[Optional[str]] = mapped_column(String(100))

    is_read: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    is_dismissed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    notified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )

    transaction: Mapped[Optional["Transaction"]] = relationship(  # noqa: F821
        back_populates="fraud_alerts"
    )
    user: Mapped["User"] = relationship(back_populates="fraud_alerts")  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<FraudAlert id={self.id} user={self.user_id} {self.risk_level} score={self.risk_score}>"
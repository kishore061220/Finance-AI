"""Firebase Cloud Messaging device registration token."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base
from app.models.base import StrEnum, TimestampMixin


class DevicePlatform(StrEnum):
    ANDROID = "ANDROID"
    IOS = "IOS"
    WEB = "WEB"


class DeviceToken(Base, TimestampMixin):
    __tablename__ = "device_tokens"
    __table_args__ = (Index("ix_device_tokens_user_active", "user_id", "is_active"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # FCM registration tokens are long strings.
    token: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    platform: Mapped[DevicePlatform] = mapped_column(
        Enum(DevicePlatform, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=DevicePlatform.ANDROID,
    )
    device_name: Mapped[Optional[str]] = mapped_column(String(120))
    app_version: Mapped[Optional[str]] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    user: Mapped["User"] = relationship(back_populates="device_tokens")  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DeviceToken id={self.id} user={self.user_id} {self.platform}>"
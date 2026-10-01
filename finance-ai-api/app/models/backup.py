"""Cloud backup history model."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base
from app.models.base import StrEnum, TimestampMixin


class BackupProvider(StrEnum):
    LOCAL = "LOCAL"
    FIREBASE_STORAGE = "FIREBASE_STORAGE"
    GOOGLE_CLOUD_STORAGE = "GOOGLE_CLOUD_STORAGE"
    GOOGLE_DRIVE = "GOOGLE_DRIVE"


class BackupStatus(StrEnum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


def _enum(enum_cls):
    return Enum(enum_cls, values_callable=lambda e: [m.value for m in e])


class BackupRecord(Base, TimestampMixin):
    __tablename__ = "backup_records"
    __table_args__ = (Index("ix_backup_records_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[BackupProvider] = mapped_column(_enum(BackupProvider), nullable=False)
    status: Mapped[BackupStatus] = mapped_column(
        _enum(BackupStatus), nullable=False, default=BackupStatus.PENDING
    )
    # Object key / Drive file id returned by the provider.
    remote_path: Mapped[Optional[str]] = mapped_column(String(512))
    remote_url: Mapped[Optional[str]] = mapped_column(String(512))
    record_count: Mapped[Optional[int]] = mapped_column(Integer)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer)
    checksum: Mapped[Optional[str]] = mapped_column(String(64))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    user: Mapped["User"] = relationship(back_populates="backup_records")  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover
        return f"<BackupRecord id={self.id} user={self.user_id} {self.provider} {self.status}>"
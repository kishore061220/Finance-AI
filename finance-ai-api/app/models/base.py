"""Shared model mixins."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, func, text
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    """Adds server-managed ``created_at`` / ``updated_at`` columns.

    The server default is declared as the literal SQL keyword
    ``CURRENT_TIMESTAMP`` rather than ``func.now()`` or ``now()``. MySQL
    normalises both of those to ``CURRENT_TIMESTAMP`` when the column is
    altered, so using the keyword directly keeps the model and the migrated
    schema identical under ``alembic check``.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=func.now(),
    )


class StrEnum(str, enum.Enum):
    """String-valued enum that serialises to plain strings."""

    def __str__(self) -> str:  # pragma: no cover - trivial
        return str(self.value)
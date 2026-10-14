"""SMS ingestion ledger.

One row per received bank SMS. Rows exist so the ingest is idempotent (an
app retry cannot create a second copy), deduplicated (identical messages map to
one row) and reviewable (low-confidence parses wait in ``PENDING_REVIEW`` until
the owner confirms or rejects them).

The body is the user's own banking SMS and is used only to let the owner review
the evidence. It is scoped to ``user_id`` and reachable exclusively through the
authenticated API - never echoed in logs or error messages.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base
from app.models.base import StrEnum, TimestampMixin


class SmsIngestStatus(StrEnum):
    # Inserted at receive time; resolved in the same request unless an error
    # needs to be retried later (then it stays ERROR and can be re-sent).
    PROCESSING = "PROCESSING"
    # Parsed confidently and stored as a transaction (SMS source).
    SAVED = "SAVED"
    # Identical to a message already seen for this user.
    DUPLICATE = "DUPLICATE"
    # Parsable but low confidence, awaiting the owner's confirm/reject decision.
    PENDING_REVIEW = "PENDING_REVIEW"
    # Not a usable bank transaction (OTP, promo, balance-only, unparsable).
    INVALID = "INVALID"
    # The owner explicitly rejected the pending message.
    REJECTED = "REJECTED"
    # Receive succeeded but processing failed; safe to retry the same payload.
    ERROR = "ERROR"


def _enum(enum_cls):
    return Enum(enum_cls, values_callable=lambda e: [m.value for m in e])


class SmsMessage(Base, TimestampMixin):
    __tablename__ = "sms_messages"
    __table_args__ = (
        # The key next to one another produce identical rows for retries.
        UniqueConstraint("user_id", "client_msg_id", name="uq_sms_messages_user_client"),
        # Repeated identical bodies for the same user are treated as the same SMS.
        # This is a deliberate anti-double-ingest backstop for the case where the
        # same message is redelivered under a different client_msg_id (e.g. the
        # OS message id changed on reboot). It cannot distinguish that from two
        # genuinely identical bank SMS (same sender, same amount, no reference
        # number) sent at different times, and merges them. A compound key that
        # adds received_at would separate those two cases only when the client
        # always supplies the SMS timestamp, which it is not required to do, and
        # would let a redelivery without a timestamp create a second transaction.
        # The safe default is therefore to keep the body-only key: a merged
        # duplicate is recoverable, an auto-created duplicate transaction is not.
        UniqueConstraint("user_id", "body_hash", name="uq_sms_messages_user_body_hash"),
        Index("ix_sms_messages_user_status", "user_id", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Device/provider message id so a retry after an app restart maps to the
    # same row instead of creating a second one.
    client_msg_id: Mapped[str] = mapped_column(String(64), nullable=False)
    sender: Mapped[Optional[str]] = mapped_column(String(32))
    # SHA-256 of the normalised body, used for cross-session deduplication.
    body_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_body: Mapped[str] = mapped_column(Text, nullable=False)
    # Wall-clock copy of the device timestamp (normalise to UTC before sending).
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    status: Mapped[SmsIngestStatus] = mapped_column(
        _enum(SmsIngestStatus), nullable=False, default=SmsIngestStatus.PROCESSING
    )
    # Snapshot of app.services.sms_parser.parse_sms at ingest time.
    parsed: Mapped[Optional[dict]] = mapped_column(JSON)
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    rejection_reason: Mapped[Optional[str]] = mapped_column(String(255))
    error_message: Mapped[Optional[str]] = mapped_column(String(255))

    # Populated when a SAVED (or confirmed) message becomes a transaction.
    transaction_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("transactions.id", ondelete="SET NULL"), index=True
    )

    transaction: Mapped[Optional["Transaction"]] = relationship()  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<SmsMessage id={self.id} user={self.user_id} {self.status}>"
"""SMS ingestion schemas.

Auth note: none of these payloads carries a ``user_id``. The owner is always
the authenticated principal, resolved from the verified Firebase token.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.models.sms_message import SmsIngestStatus
from app.schemas.transaction import TransactionResponse
from app.schemas.user import ORMModel


class SmsMessageReceiveRequest(BaseModel):
    """One bank SMS reported by a device.

    ``client_msg_id`` is the device/provider message id. The server treats it
    as the idempotency key: re-sending the same id never creates a second row.
    """

    client_msg_id: str = Field(..., min_length=1, max_length=64)
    sender: Optional[str] = Field(default=None, max_length=32)
    body: str = Field(..., min_length=1, max_length=4000)
    # Naive UTC is preferred; timezone-aware values are normalised to UTC.
    received_at: Optional[datetime] = None

    @staticmethod
    def normalise_received_at(value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value


class SmsMessageResponse(ORMModel):
    id: int
    user_id: int
    client_msg_id: str
    sender: Optional[str] = None
    body: str
    received_at: Optional[datetime] = None
    status: SmsIngestStatus
    parsed: Dict[str, Any] = Field(default_factory=dict)
    confidence: Optional[float] = None
    rejection_reason: Optional[str] = None
    error_message: Optional[str] = None
    transaction_id: Optional[int] = None
    transaction: Optional[TransactionResponse] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SmsMessageListResponse(BaseModel):
    items: List[SmsMessageResponse]
    total: int
    page: int
    page_size: int
    pages: int


class SmsRejectRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=255)


def hash_body(body: str) -> str:
    """Normalised SHA-256 used to detect an identical message being re-sent."""
    normalised = " ".join((body or "").split()).lower()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


__all__ = [
    "SmsMessageListResponse",
    "SmsMessageReceiveRequest",
    "SmsMessageResponse",
    "SmsRejectRequest",
    "hash_body",
]
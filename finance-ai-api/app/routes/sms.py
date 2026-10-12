"""SMS ingestion pipeline.

Design goals, in order of importance:

1. **Idempotent** - ``client_msg_id`` is the replay key. An app retry (after a
   lost request or an app restart) returns the same row instead of creating a
   second transaction.
2. **Deduplicated** - an identical body for the same user maps to the existing
   outcome.
3. **Conservative by default** - a message without both an amount and a
   direction is never imported; a low-confidence parse waits as
   ``PENDING_REVIEW`` until the owner confirms or rejects it.
4. **Same fraud pipeline as manual entries** - saved messages are scored with
   the shared ``transaction_analysis`` helpers, so an SMS-imported debit is
   flagged exactly like a manually entered one.

Privacy: the body is stored per-user so the owner can review the evidence and
decide. It is never echoed in logs or error payloads.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database.connection import get_db
from app.models.sms_message import SmsIngestStatus, SmsMessage
from app.models.transaction import Transaction, TransactionSource, TransactionType
from app.models.user import User
from app.schemas.sms import (
    SmsMessageListResponse,
    SmsMessageReceiveRequest,
    SmsMessageResponse,
    SmsRejectRequest,
    hash_body,
)
from app.schemas.transaction import TransactionResponse
from app.services import sms_parser
from app.services.transaction_analysis import apply_analysis, user_history

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sms", tags=["sms"])

# Parses with an amount + direction but a confidence below this are held for
# the owner's review instead of being written into the ledger automatically.
REVIEW_CONFIDENCE_THRESHOLD = 0.85
MAX_BODY_LENGTH = 4000


def _json_safe(parsed: dict) -> dict:
    """Make the parser output storable in a JSON column.

    ``parse_sms`` returns ``Decimal`` amounts and ``datetime`` objects which
    sqlalchemy's JSON type cannot serialise; they are converted here. The body
    is dropped because it is already stored in ``raw_body``.
    """
    safe: dict = {}
    for key, value in parsed.items():
        if isinstance(value, Decimal):
            safe[key] = str(value)
        elif isinstance(value, datetime):
            safe[key] = value.isoformat()
        elif value is None or isinstance(value, (str, int, float, bool, list, dict)):
            safe[key] = value
        else:
            safe[key] = str(value)
    safe.pop("raw_text", None)
    return safe


def _create_transaction(db: Session, user_id: int, parsed: dict, body: str) -> int:
    """Persist a parsed SMS as a transaction and run the shared fraud pipeline.

    Returns the new transaction id. The caller is responsible for committing.
    """
    history = user_history(db, user_id)
    transaction = Transaction(
        user_id=user_id,
        transaction_type=TransactionType(parsed["transaction_type"]),
        amount=parsed["amount"],
        category=parsed.get("category") or "Uncategorized",
        merchant=parsed.get("merchant"),
        transaction_date=parsed.get("transaction_date"),
        source=TransactionSource.SMS,
        bank_reference=parsed.get("bank_reference"),
        raw_source_text=body,
        categorization_source="sms-rules",
    )
    db.add(transaction)
    db.flush()

    analysis = apply_analysis(transaction, history, db)
    alert = analysis["alert"]
    if alert is not None:
        alert.transaction_id = transaction.id
        db.add(alert)
    db.flush()
    return transaction.id


def _transaction_response(db: Session, transaction_id: Optional[int]):
    if transaction_id is None:
        return None
    transaction = db.get(Transaction, transaction_id)
    return TransactionResponse.model_validate(transaction) if transaction else None


def _to_response(db: Session, message: SmsMessage) -> SmsMessageResponse:
    return SmsMessageResponse(
        id=message.id,
        user_id=message.user_id,
        client_msg_id=message.client_msg_id,
        sender=message.sender,
        body=message.raw_body,
        received_at=message.received_at,
        status=message.status,
        parsed=message.parsed or {},
        confidence=message.confidence,
        rejection_reason=message.rejection_reason,
        error_message=message.error_message,
        transaction_id=message.transaction_id,
        transaction=_transaction_response(db, message.transaction_id),
        created_at=message.created_at,
        updated_at=message.updated_at,
    )


def _get_owned_message(db: Session, message_id: int, user_id: int) -> SmsMessage:
    message = db.execute(
        select(SmsMessage).where(
            SmsMessage.id == message_id, SmsMessage.user_id == user_id
        )
    ).scalar_one_or_none()
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return message


def _process(db: Session, message: SmsMessage) -> None:
    """Parse ``message.raw_body`` and move the message to its terminal state.

    Mutates the message and may create a transaction + fraud alert, but does
    not commit. Invoked once per receive; ERROR rows may be re-processed on a
    replay so the device retry queue can make progress.
    """
    parsed = sms_parser.parse_sms(message.raw_body)
    message.parsed = _json_safe(parsed)
    message.confidence = parsed["confidence"]

    has_amount = parsed.get("amount") is not None
    has_direction = parsed.get("transaction_type") is not None

    if not has_amount or not has_direction:
        message.status = SmsIngestStatus.INVALID
        message.rejection_reason = (
            "Not a usable bank transaction: no amount or direction could be extracted."
        )
        return

    if parsed["confidence"] >= REVIEW_CONFIDENCE_THRESHOLD:
        message.status = SmsIngestStatus.SAVED
        message.transaction_id = _create_transaction(
            db, message.user_id, parsed, message.raw_body
        )
        return

    message.status = SmsIngestStatus.PENDING_REVIEW


@router.post(
    "/messages",
    response_model=SmsMessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest one bank SMS",
)
def receive_sms(
    payload: SmsMessageReceiveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SmsMessageResponse:
    """Report a received bank SMS and get its processing outcome.

    Safe to call multiple times with the same ``client_msg_id``; the first
    outcome wins and later calls return the stored row.
    """
    received_at = SmsMessageReceiveRequest.normalise_received_at(payload.received_at)
    if received_at is None:
        received_at = datetime.now(timezone.utc).replace(tzinfo=None)
    body_hash = hash_body(payload.body)

    existing = db.execute(
        select(SmsMessage).where(
            SmsMessage.user_id == current_user.id,
            SmsMessage.client_msg_id == payload.client_msg_id,
        )
    ).scalar_one_or_none()

    if existing is not None:
        if existing.status == SmsIngestStatus.ERROR:
            try:
                db.rollback()
                existing = _get_owned_message(db, existing.id, current_user.id)
                _process(db, existing)
                db.commit()
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                existing = _get_owned_message(db, existing.id, current_user.id)
                existing.status = SmsIngestStatus.ERROR
                existing.error_message = type(exc).__name__
                db.commit()
        return _to_response(db, existing)

    duplicate = db.execute(
        select(SmsMessage).where(
            SmsMessage.user_id == current_user.id,
            SmsMessage.body_hash == body_hash,
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        return _to_response(db, duplicate)

    message = SmsMessage(
        user_id=current_user.id,
        client_msg_id=payload.client_msg_id,
        sender=payload.sender,
        raw_body=payload.body[:MAX_BODY_LENGTH],
        body_hash=body_hash,
        received_at=received_at,
        status=SmsIngestStatus.PROCESSING,
    )
    db.add(message)
    db.flush()
    try:
        _process(db, message)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("SMS ingest failed for user=%s: %s", current_user.id, type(exc).__name__)
        db.rollback()
        # The failed transaction may have inserted the row and then failed
        # while parsing or scoring. Rollback removes that uncommitted row, so
        # recreate the durable ERROR record for a safe client retry.
        message = SmsMessage(
            user_id=current_user.id,
            client_msg_id=payload.client_msg_id,
            sender=payload.sender,
            raw_body=payload.body[:MAX_BODY_LENGTH],
            body_hash=body_hash,
            received_at=received_at,
            status=SmsIngestStatus.ERROR,
            error_message=type(exc).__name__,
        )
        db.add(message)
        db.commit()

    return _to_response(db, message)


@router.get(
    "/messages",
    response_model=SmsMessageListResponse,
    summary="List ingested SMS messages",
)
def list_messages(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    status_filter: Optional[SmsIngestStatus] = Query(
        default=None, alias="status", description="Filter by processing status"
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> SmsMessageListResponse:
    stmt = select(SmsMessage).where(SmsMessage.user_id == current_user.id)
    if status_filter is not None:
        stmt = stmt.where(SmsMessage.status == status_filter)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = list(
        db.execute(
            stmt.order_by(SmsMessage.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).scalars()
    )
    return SmsMessageListResponse(
        items=[_to_response(db, row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=((total + page_size - 1) // page_size) if total else 0,
    )


@router.post(
    "/messages/{message_id}/confirm",
    response_model=SmsMessageResponse,
    summary="Confirm a pending SMS and write the transaction",
)
def confirm_message(
    message_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SmsMessageResponse:
    message = _get_owned_message(db, message_id, current_user.id)
    if message.status == SmsIngestStatus.SAVED:
        return _to_response(db, message)
    if message.status != SmsIngestStatus.PENDING_REVIEW:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Cannot confirm a message in state {message.status.value}.",
        )

    parsed = sms_parser.parse_sms(message.raw_body)
    message.parsed = _json_safe(parsed)
    message.confidence = parsed["confidence"]
    if not parsed.get("amount") or not parsed.get("transaction_type"):
        message.status = SmsIngestStatus.INVALID
        message.rejection_reason = (
            "Not a usable bank transaction: no amount or direction could be extracted."
        )
        db.commit()
        return _to_response(db, message)

    message.status = SmsIngestStatus.SAVED
    message.transaction_id = _create_transaction(
        db, current_user.id, parsed, message.raw_body
    )
    db.commit()
    return _to_response(db, message)


@router.post(
    "/messages/{message_id}/reject",
    response_model=SmsMessageResponse,
    summary="Reject a pending SMS",
)
def reject_message(
    message_id: int,
    payload: Optional[SmsRejectRequest] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SmsMessageResponse:
    message = _get_owned_message(db, message_id, current_user.id)
    if message.status == SmsIngestStatus.REJECTED:
        return _to_response(db, message)
    if message.status != SmsIngestStatus.PENDING_REVIEW:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Cannot reject a message in state {message.status.value}.",
        )

    message.status = SmsIngestStatus.REJECTED
    message.rejection_reason = (payload.reason if payload else None) or "Rejected by owner"
    db.commit()
    return _to_response(db, message)
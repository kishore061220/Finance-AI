"""Categorization, SMS parsing and OCR parsing routes.

Parsing and categorisation run on the server so the rules stay in one place and
are testable. The *decisions* are never stored here: the endpoints return
proposals, and the caller confirms. The one exception is an explicit
``apply_category`` with a ``transaction_id`` the caller owns.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database.connection import get_db
from app.models.transaction import Transaction, TransactionSource, TransactionType
from app.models.user import User
from app.schemas.transaction import (
    CategorizeRequest,
    CategorizeResponse,
    OcrLineItem,
    OcrParseRequest,
    OcrParseResponse,
    SmsParseRequest,
    SmsParseResponse,
)
from app.services import ocr_parser, sms_parser
from app.services.categorization import (
    all_categories,
    predict_category_detailed,
)

router = APIRouter(prefix="/api/categorization", tags=["categorization"])


@router.get("/categories", summary="Known categories and their keywords")
def categories() -> dict:
    from app.services.categorization import CATEGORY_RULES

    return {
        "categories": all_categories(),
        "keywords": {
            rule.category: list(rule.keywords) for rule in CATEGORY_RULES
        },
        "engine": "keyword-rules",
    }


@router.post("/predict", response_model=CategorizeResponse, summary="Categorize text")
def predict(
    payload: CategorizeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CategorizeResponse:
    result = predict_category_detailed(
        payload.merchant, payload.description, payload.amount
    )

    # Only write back when the caller explicitly asks, and only for a
    # transaction they own.
    if payload.apply_category and payload.transaction_id is not None:
        transaction = db.get(Transaction, payload.transaction_id)
        if transaction is None or transaction.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Transaction not found")
        transaction.category = result["category"]
        transaction.categorization_source = "rules"
        db.commit()
        db.refresh(transaction)

    return CategorizeResponse(**result)


@router.post("/sms/parse", response_model=SmsParseResponse, summary="Parse bank SMS")
def parse_sms(
    payload: SmsParseRequest, current_user: User = Depends(get_current_user)
) -> SmsParseResponse:
    result = sms_parser.parse_sms(payload.raw_text)
    return SmsParseResponse(**result)


@router.post("/sms/commit", response_model=dict, summary="Store a parsed SMS")
def commit_sms(
    payload: SmsParseRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Parse a bank SMS and, if it is usable, save it as a transaction."""
    parsed = sms_parser.parse_sms(payload.raw_text)
    if not parsed.get("amount") or not parsed.get("transaction_type"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "Could not extract a usable transaction from this SMS.",
                "parsed": parsed,
            },
        )

    category = parsed.get("category") or predict_category_detailed(
        parsed.get("merchant"), parsed.get("raw_text"), parsed.get("amount")
    )["category"]

    transaction = Transaction(
        user_id=current_user.id,
        transaction_type=TransactionType(parsed["transaction_type"]),
        amount=parsed["amount"],
        category=category,
        merchant=parsed.get("merchant"),
        transaction_date=parsed.get("transaction_date"),
        source=TransactionSource.SMS,
        bank_reference=parsed.get("bank_reference"),
        raw_source_text=payload.raw_text,
        categorization_source="sms-rules",
    )
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    return {
        "created": True,
        "transaction_id": transaction.id,
        "transaction": {
            "id": transaction.id,
            "transaction_type": transaction.transaction_type.value,
            "amount": str(transaction.amount),
            "category": transaction.category,
            "merchant": transaction.merchant,
            "transaction_date": transaction.transaction_date.isoformat(),
            "source": transaction.source.value,
            "confidence": parsed.get("confidence"),
        },
    }


@router.post("/ocr/parse", response_model=OcrParseResponse, summary="Parse OCR text")
def parse_ocr(
    payload: OcrParseRequest, current_user: User = Depends(get_current_user)
) -> OcrParseResponse:
    if not payload.text or not payload.text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "No text supplied. Run on-device OCR (ML Kit) and send the "
                "recognised text here."
            ),
        )
    result = ocr_parser.parse_statement(payload.text, payload.currency)
    return OcrParseResponse(**result)


@router.post("/ocr/commit", response_model=dict, summary="Store an OCR statement")
def commit_ocr(
    payload: OcrParseRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Parse OCR text and save the line items as transactions.

    Either the caller sends ``text`` directly, or an already-split list of
    ``line_items`` from the device parser.
    """
    if payload.text and payload.text.strip():
        parsed = ocr_parser.parse_statement(payload.text, payload.currency)
        items = [OcrLineItem(**li) for li in parsed["line_items"]]
        merchant = parsed.get("merchant")
    else:
        items = []
        merchant = None

    if not items:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No line items could be extracted from the supplied text.",
        )

    created = []
    for item in items:
        if not item.transaction_type:
            continue
        category = predict_category_detailed(
            item.description, item.description, item.amount
        )["category"]
        transaction = Transaction(
            user_id=current_user.id,
            transaction_type=TransactionType(item.transaction_type),
            amount=item.amount,
            category=category,
            merchant=merchant or item.description[:150],
            transaction_date=item.date,
            source=TransactionSource.OCR,
            raw_source_text=item.raw_line[:2000],
            categorization_source="ocr-rules",
        )
        db.add(transaction)
        db.flush()
        created.append(transaction.id)

    db.commit()
    return {
        "created": len(created),
        "merchant": merchant,
        "transaction_ids": created,
    }

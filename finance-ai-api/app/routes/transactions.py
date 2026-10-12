"""Transaction routes.

Every route scopes its query to ``current_user.id``. The client cannot supply a
``user_id``; the previous implementation trusted a ``user_id`` path/query
parameter, which allowed any caller to read or modify any other user's
financial records.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database.connection import get_db
from app.models.transaction import Transaction, TransactionSource, TransactionType
from app.models.user import User
from app.schemas.transaction import (
    BulkImportRequest,
    BulkImportResponse,
    TransactionCreate,
    TransactionListResponse,
    TransactionResponse,
    TransactionUpdate,
)
from app.services.transaction_analysis import apply_analysis, user_history

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/transactions", tags=["transactions"])

SORT_COLUMNS = {
    "transaction_date_desc": Transaction.transaction_date.desc(),
    "transaction_date_asc": Transaction.transaction_date.asc(),
    "amount_desc": Transaction.amount.desc(),
    "amount_asc": Transaction.amount.asc(),
    "created_at_desc": Transaction.created_at.desc(),
}


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Transaction not found")


@router.post(
    "",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a transaction",
)
def create_transaction(
    payload: TransactionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Transaction:
    history = user_history(db, current_user.id)

    transaction = Transaction(
        user_id=current_user.id,
        transaction_type=TransactionType(payload.transaction_type),
        amount=payload.amount,
        category=payload.category,
        emi_type=payload.emi_type,
        merchant=payload.merchant,
        description=payload.description,
        transaction_date=payload.transaction_date,
        source=payload.source,
        bank_reference=payload.bank_reference,
        raw_source_text=payload.raw_source_text,
        categorization_source="client",
    )
    db.add(transaction)
    db.flush()  # assign the id without committing yet

    analysis = apply_analysis(transaction, history, db)
    if analysis["alert"] is not None:
        analysis["alert"].transaction_id = transaction.id
        db.add(analysis["alert"])

    db.commit()
    db.refresh(transaction)
    return transaction


@router.get("", response_model=TransactionListResponse, summary="List transactions")
def list_transactions(
    transaction_type: Optional[str] = Query(default=None, pattern="^(income|expense)$"),
    category: Optional[str] = Query(default=None, max_length=100),
    emi_type: Optional[str] = Query(default=None, max_length=100),
    merchant: Optional[str] = Query(default=None, max_length=150),
    start_date: Optional[datetime] = Query(default=None),
    end_date: Optional[datetime] = Query(default=None),
    min_amount: Optional[Decimal] = Query(default=None, ge=0),
    max_amount: Optional[Decimal] = Query(default=None, ge=0),
    flagged_only: bool = Query(default=False),
    search: Optional[str] = Query(default=None, max_length=150),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    sort: str = Query(default="transaction_date_desc"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TransactionListResponse:
    stmt = select(Transaction).where(Transaction.user_id == current_user.id)

    if transaction_type:
        stmt = stmt.where(Transaction.transaction_type == TransactionType(transaction_type))
    if category:
        stmt = stmt.where(Transaction.category == category)
    if emi_type:
        stmt = stmt.where(Transaction.emi_type == emi_type)
    if merchant:
        stmt = stmt.where(Transaction.merchant.ilike(f"%{merchant}%"))
    if start_date:
        stmt = stmt.where(Transaction.transaction_date >= start_date)
    if end_date:
        stmt = stmt.where(Transaction.transaction_date <= end_date)
    if min_amount is not None:
        stmt = stmt.where(Transaction.amount >= min_amount)
    if max_amount is not None:
        stmt = stmt.where(Transaction.amount <= max_amount)
    if flagged_only:
        stmt = stmt.where(Transaction.is_flagged.is_(True))
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            or_(
                Transaction.merchant.ilike(pattern),
                Transaction.description.ilike(pattern),
                Transaction.category.ilike(pattern),
            )
        )

    total = db.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar_one()

    order = SORT_COLUMNS.get(sort)
    if order is None:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid sort '{sort}'. Allowed: {', '.join(sorted(SORT_COLUMNS))}",
        )
    stmt = stmt.order_by(order).offset((page - 1) * page_size).limit(page_size)

    items = list(db.execute(stmt).scalars())
    return TransactionListResponse(
        items=[TransactionResponse.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@router.get("/recent", summary="Most recent transactions")
def recent_transactions(
    limit: int = Query(default=10, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    items = list(
        db.execute(
            select(Transaction)
            .where(Transaction.user_id == current_user.id)
            .order_by(Transaction.transaction_date.desc(), Transaction.id.desc())
            .limit(limit)
        ).scalars()
    )
    return {"items": [TransactionResponse.model_validate(i).model_dump() for i in items]}


@router.get("/{transaction_id}", response_model=TransactionResponse, summary="Get one")
def get_transaction(
    transaction_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Transaction:
    transaction = db.get(Transaction, transaction_id)
    # Ownership is enforced here; a non-owner gets 404, not 403, so the
    # endpoint does not confirm that someone else's record exists.
    if transaction is None or transaction.user_id != current_user.id:
        raise _not_found()
    return transaction


@router.patch("/{transaction_id}", response_model=TransactionResponse, summary="Update")
def update_transaction(
    transaction_id: int,
    payload: TransactionUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Transaction:
    transaction = db.get(Transaction, transaction_id)
    if transaction is None or transaction.user_id != current_user.id:
        raise _not_found()

    data = payload.model_dump(exclude_unset=True)
    if "transaction_type" in data and data["transaction_type"] is not None:
        data["transaction_type"] = TransactionType(data["transaction_type"])
    for field, value in data.items():
        setattr(transaction, field, value)

    # Re-score because the amount, merchant or date may have changed.
    history = user_history(db, current_user.id, exclude_id=transaction.id)
    apply_analysis(transaction, history, db)

    db.commit()
    db.refresh(transaction)
    return transaction


@router.delete(
    "/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete"
)
def delete_transaction(
    transaction_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    transaction = db.get(Transaction, transaction_id)
    if transaction is None or transaction.user_id != current_user.id:
        raise _not_found()
    db.delete(transaction)
    db.commit()


@router.post("/bulk", response_model=BulkImportResponse, summary="Bulk import")
def bulk_import(
    payload: BulkImportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BulkImportResponse:
    """Import many transactions, skipping duplicates by bank reference."""
    created = 0
    skipped = 0
    errors: List[dict] = []
    ids: List[int] = []
    seen_references = set()

    for index, item in enumerate(payload.transactions):
        try:
            if payload.dry_run:
                ids.append(0)
                created += 1
                continue

            if item.bank_reference:
                if item.bank_reference in seen_references:
                    skipped += 1
                    continue
                exists = db.execute(
                    select(Transaction.id).where(
                        Transaction.user_id == current_user.id,
                        Transaction.bank_reference == item.bank_reference,
                    )
                ).scalar_one_or_none()
                if exists:
                    skipped += 1
                    continue
                seen_references.add(item.bank_reference)

            transaction = Transaction(
                user_id=current_user.id,
                transaction_type=TransactionType(item.transaction_type),
                amount=item.amount,
                category=item.category,
                emi_type=item.emi_type,
                merchant=item.merchant,
                description=item.description,
                transaction_date=item.transaction_date,
                source=TransactionSource.IMPORT,
                bank_reference=item.bank_reference,
                categorization_source="bulk-import",
            )
            db.add(transaction)
            db.flush()
            ids.append(transaction.id)
            created += 1
        except Exception as exc:  # keep importing the rest
            db.rollback()
            skipped += 1
            errors.append({"index": index, "error": str(exc)[:200]})

    if not payload.dry_run:
        db.commit()

    return BulkImportResponse(
        created=created, skipped=skipped, errors=errors, transaction_ids=ids
    )

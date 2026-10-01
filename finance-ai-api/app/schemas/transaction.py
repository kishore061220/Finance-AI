"""Transaction schemas."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from app.models.transaction import EmiType, TransactionSource, TransactionType
from app.schemas.user import ORMModel

# Original public field: lower-case values.
VALID_TYPES = {"income", "expense"}


def _coerce_type(value: str) -> str:
    v = (value or "").strip().lower()
    if v not in VALID_TYPES:
        raise ValueError("transaction_type must be 'income' or 'expense'")
    return v


class TransactionCreate(BaseModel):
    """Create payload.

    ``user_id`` is intentionally absent: the owner is always the authenticated
    principal. A client-supplied user id can no longer target another account.
    """

    transaction_type: str = Field(..., description="income or expense")
    amount: Decimal = Field(..., gt=0, max_digits=14, decimal_places=2)
    category: str = Field(..., min_length=1, max_length=100)
    emi_type: Optional[str] = Field(default=None, max_length=100)
    merchant: Optional[str] = Field(default=None, max_length=150)
    description: Optional[str] = None
    transaction_date: datetime
    source: TransactionSource = TransactionSource.MANUAL
    bank_reference: Optional[str] = Field(default=None, max_length=120)
    raw_source_text: Optional[str] = None

    @field_validator("transaction_type")
    @classmethod
    def _validate_type(cls, v: str) -> str:
        return _coerce_type(v)

    @field_validator("emi_type")
    @classmethod
    def _validate_emi(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        valid = {e.value for e in EmiType}
        if v not in valid:
            raise ValueError(
                f"emi_type must be one of: {', '.join(sorted(valid))}"
            )
        return v


class TransactionUpdate(BaseModel):
    transaction_type: Optional[str] = None
    amount: Optional[Decimal] = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    category: Optional[str] = Field(default=None, min_length=1, max_length=100)
    emi_type: Optional[str] = Field(default=None, max_length=100)
    merchant: Optional[str] = Field(default=None, max_length=150)
    description: Optional[str] = None
    transaction_date: Optional[datetime] = None
    bank_reference: Optional[str] = Field(default=None, max_length=120)

    @field_validator("transaction_type")
    @classmethod
    def _validate_type(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else _coerce_type(v)

    @field_validator("emi_type")
    @classmethod
    def _validate_emi(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        valid = {e.value for e in EmiType}
        if v not in valid:
            raise ValueError(f"emi_type must be one of: {', '.join(sorted(valid))}")
        return v


class TransactionResponse(ORMModel):
    id: int
    user_id: int
    transaction_type: TransactionType
    amount: Decimal
    category: str
    emi_type: Optional[str] = None
    merchant: Optional[str] = None
    description: Optional[str] = None
    transaction_date: datetime
    source: TransactionSource
    bank_reference: Optional[str] = None
    raw_source_text: Optional[str] = None
    categorization_source: Optional[str] = None
    fraud_score: Optional[int] = None
    is_flagged: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TransactionListResponse(BaseModel):
    items: List[TransactionResponse]
    total: int
    page: int
    page_size: int
    pages: int


class TransactionFilter(BaseModel):
    transaction_type: Optional[str] = None
    category: Optional[str] = None
    emi_type: Optional[str] = None
    merchant: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    min_amount: Optional[Decimal] = None
    max_amount: Optional[Decimal] = None
    flagged_only: bool = False
    search: Optional[str] = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)
    sort: str = "transaction_date_desc"

    @field_validator("transaction_type")
    @classmethod
    def _validate_type(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else _coerce_type(v)


class CategorizeRequest(BaseModel):
    merchant: Optional[str] = Field(default=None, max_length=150)
    description: Optional[str] = None
    amount: Optional[Decimal] = None
    apply_category: bool = Field(
        default=False,
        description="When true and transaction_id is set, write the category back.",
    )
    transaction_id: Optional[int] = None


class CategorizeResponse(BaseModel):
    category: str
    confidence: float
    scores: Dict[str, float]
    matched_keywords: List[str]
    notes: List[str]
    engine: str


class SmsParseRequest(BaseModel):
    raw_text: str = Field(..., min_length=4)


class SmsParseResponse(BaseModel):
    amount: Optional[Decimal] = None
    transaction_type: Optional[str] = None
    merchant: Optional[str] = None
    category: Optional[str] = None
    transaction_date: Optional[datetime] = None
    bank_reference: Optional[str] = None
    confidence: float
    parser: str
    raw_text: str
    notes: List[str] = []


class OcrParseRequest(BaseModel):
    text: Optional[str] = None
    currency: Optional[str] = Field(default=None, max_length=8)
    default_source: TransactionSource = TransactionSource.OCR


class OcrLineItem(BaseModel):
    description: str
    amount: Decimal
    transaction_type: Optional[str] = None
    date: Optional[datetime] = None
    confidence: float
    raw_line: str


class OcrParseResponse(BaseModel):
    merchant: Optional[str] = None
    total: Optional[Decimal] = None
    currency: Optional[str] = None
    transaction_date: Optional[datetime] = None
    line_items: List[OcrLineItem] = []
    confidence: float
    parser: str
    notes: List[str] = []


class BulkImportRequest(BaseModel):
    transactions: List[TransactionCreate] = Field(..., min_length=1, max_length=1000)
    dry_run: bool = False


class BulkImportResponse(BaseModel):
    created: int
    skipped: int
    errors: List[Dict[str, Any]] = []
    transaction_ids: List[int] = []


__all__ = [
    "BulkImportRequest",
    "BulkImportResponse",
    "CategorizeRequest",
    "CategorizeResponse",
    "OcrLineItem",
    "OcrParseRequest",
    "OcrParseResponse",
    "SmsParseRequest",
    "SmsParseResponse",
    "TransactionCreate",
    "TransactionFilter",
    "TransactionListResponse",
    "TransactionResponse",
    "TransactionUpdate",
]

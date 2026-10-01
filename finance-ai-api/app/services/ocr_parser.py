"""OCR text parser for bank statements and receipt photos.

ML Kit performs the *image* recognition on the mobile client and sends the
recognised text here. This module parses that text. The division of labour is
deliberate: it keeps the heavy vision dependency out of the backend and means
the parser is fully unit-testable without any image fixture.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional

from app.services.categorization import predict_category
from app.services.sms_parser import _extract_date

PARSER_NAME = "statement-ocr-heuristics"

CURRENCY_SYMBOLS = {
    "₹": "INR",
    "rs": "INR",
    "inr": "INR",
    "$": "USD",
    "usd": "USD",
    "€": "EUR",
    "eur": "EUR",
    "£": "GBP",
    "gbp": "GBP",
}

TOTAL_PATTERNS = (
    re.compile(r"(?:grand\s*total|total\s*amount|amount\s*due|total)\s*[:\-]?\s*[₹$€£]?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", re.IGNORECASE),
    re.compile(r"[₹$€£]\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)"),
)

LINE_ITEM = re.compile(
    r"^(?P<desc>.*?[A-Za-z0-9])\s{1,}|[₹$€£]?\s*(?P<amount>[0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*(?P<trailing>(?:CR|DR)?)\s*$"
)

AMOUNT_AT_END = re.compile(r"([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*(CR|DR)?\s*$")
AMOUNT_ANYWHERE = re.compile(r"[₹$€£]?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)")

SKIP_LINE = re.compile(
    r"^\s*(page|statement|account|a/c|acct|account no|branch|ifsc|date|dated|"
    r"statement date|transaction date|period|opening|closing|"
    r"balance|total|grand total|subtotal|amount due|thank you|customer|address|"
    r"generated|www\.|http|page no)",
    re.IGNORECASE,
)


def _to_decimal(raw: str) -> Optional[Decimal]:
    try:
        return Decimal(raw.replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def detect_currency(text: str) -> Optional[str]:
    lowered = text.lower()
    for token, code in CURRENCY_SYMBOLS.items():
        if token in lowered:
            return code
    return None


def _extract_total(text: str) -> Optional[Decimal]:
    for pattern in TOTAL_PATTERNS:
        for m in pattern.finditer(text):
            value = _to_decimal(m.group(1))
            if value is not None and value > 0:
                return value
    return None


def _parse_line(line: str) -> Optional[Dict]:
    """Turn a single statement row into a line item, or ``None`` to skip it."""
    stripped = line.strip()
    if not stripped or len(stripped) < 3 or SKIP_LINE.match(stripped):
        return None

    m = AMOUNT_AT_END.search(stripped)
    if not m:
        return None
    amount = _to_decimal(m.group(1))
    if amount is None or amount <= 0:
        return None

    description = stripped[: m.start()].strip(" .:-–—\t₹$€£")
    description = re.sub(r"\s+", " ", description)
    if not description or description.isdigit():
        return None

    # A trailing CR/DR is how bank statements mark credit vs debit.
    direction_marker = (m.group(2) or "").upper()
    if direction_marker == "CR":
        ttype = "income"
    elif direction_marker == "DR":
        ttype = "expense"
    else:
        ttype = None

    return {
        "description": description[:120],
        "amount": amount,
        "transaction_type": ttype,
        "raw_line": stripped[:200],
    }


def parse_statement(text: str, currency: Optional[str] = None) -> Dict:
    """Parse recognised OCR text into a merchant, total and line items.

    Returns a dict matching :class:`app.schemas.transaction.OcrParseResponse`.
    Confidence reflects how much could be extracted, and every gap is listed in
    ``notes`` rather than silently guessed.
    """
    raw = text or ""
    notes: List[str] = []
    lines = [ln for ln in raw.splitlines()]

    detected_currency = currency or detect_currency(raw)
    if not currency and not detected_currency:
        notes.append("No currency symbol detected; amounts are unlabelled.")

    line_items: List[Dict] = []
    for line in lines:
        item = _parse_line(line)
        if item is not None:
            line_items.append(item)

    total = _extract_total(raw)
    merchant = _guess_merchant(lines)
    statement_date = _extract_date(raw)

    # Confidence weights: items, total, merchant, date.
    confidence = 0.0
    if line_items:
        confidence += 0.4
    else:
        notes.append(
            "No line items could be parsed. The user should enter the "
            "transaction manually rather than trusting this result."
        )
    if total is not None:
        confidence += 0.3
    if merchant is not None:
        confidence += 0.15
    else:
        notes.append("Merchant name not detected.")
    if statement_date is not None:
        confidence += 0.15
    else:
        notes.append("No statement date detected; the transaction will default to now.")

    if line_items and total is not None:
        summed = sum(i["amount"] for i in line_items)
        if abs(summed - total) > Decimal("1.00"):
            notes.append(
                f"Line items total {summed} but the statement total is {total}; "
                "the document may be a partial page."
            )

    for item in line_items:
        item["category"] = predict_category(item["description"], "", float(item["amount"]))
        item["date"] = statement_date
        # Per-item confidence is the statement confidence discounted slightly.
        item["confidence"] = round(confidence * 0.95, 4)

    if statement_date is None:
        statement_date = datetime.now()

    return {
        "merchant": merchant,
        "total": total,
        "currency": detected_currency,
        "transaction_date": statement_date,
        "line_items": line_items,
        "confidence": round(min(confidence, 0.99), 4),
        "parser": PARSER_NAME,
        "notes": notes,
    }


def _guess_merchant(lines: List[str]) -> Optional[str]:
    """The merchant is usually the first substantial non-boilerplate line."""
    for line in lines[:8]:
        stripped = line.strip()
        if not stripped or SKIP_LINE.match(stripped):
            continue
        if AMOUNT_AT_END.search(stripped) and not AMOUNT_ANYWHERE.search(stripped[:20]):
            continue
        if len(stripped) < 3 or len(stripped) > 60:
            continue
        if stripped.isdigit():
            continue
        return re.sub(r"\s+", " ", stripped)[:60]
    return None


def parse_receipt_lines(text: str) -> List[Dict]:
    """Convenience wrapper returning only the line items."""
    return parse_statement(text)["line_items"]

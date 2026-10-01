"""Bank SMS / notification text parser.

Pure-Python heuristics - no external service, no ML. It extracts the fields the
app needs to pre-fill a transaction, and every field it is unsure about comes
back as ``None`` with a note explaining why, rather than as a guess.

Supported shapes (Indian bank SMS, the dominant format for this app):
* ``Your A/c XX1234 is debited by Rs.1,234.56 on 05-Mar-2026 for SWIGGY via UPI``
* ``Rs 5000.00 credited to your account ... on 2026-03-05 ref No 9876543210``
* ``EMI of Rs 25000.00 has been debited ... towards Home Loan ... Avl Bal: x``
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional

from app.services.categorization import predict_category

PARSER_NAME = "bank-sms-heuristics"

AMOUNT_PATTERNS = (
    re.compile(r"(?:rs\.?|inr|₹)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", re.IGNORECASE),
    re.compile(r"\b([0-9][0-9,]*\.[0-9]{2})\b"),
)

DEBIT_WORDS = (
    "debited", "debit", "spent", "paid to", "withdrawn", "withdrawal", "charged",
    "purchase", "payment to", "transferred to", "sent to", "atm wdl", "atm cash",
    "wdl",
)
CREDIT_WORDS = (
    "credited", "credit", "received", "received from", "salary", "refund",
    "transferred from", "cashback",
)

REF_PATTERNS = (
    re.compile(r"(?:ref(?:erence)?\s*(?:no\.?|number|#)?)\s*[:#]?\s*([A-Za-z0-9]{6,20})", re.IGNORECASE),
    re.compile(r"\b(upi|ref)\s*[:#]\s*([0-9]{6,})\b", re.IGNORECASE),
    re.compile(r"\b([0-9]{12})\b"),  # UTR / 12-digit reference
)

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

DATE_PATTERNS = (
    re.compile(r"(\d{4})-(\d{2})-(\d{2})"),
    re.compile(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})"),
    re.compile(r"(\d{1,2})[-\s]([A-Za-z]{3})[-\s](\d{4})"),
    re.compile(r"(\d{1,2})\s*([A-Za-z]{3})[-\s]*(\d{2,4})"),
)

EMI_MARKERS = ("emi", "instalment", "installment", "equated monthly", "loan emi")


def _extract_amount(text: str) -> Optional[Decimal]:
    for pattern in AMOUNT_PATTERNS:
        for m in pattern.finditer(text):
            raw = m.group(1).replace(",", "")
            try:
                value = Decimal(raw)
            except (InvalidOperation, ValueError):
                continue
            # Ignore implausible values that are almost certainly not the
            # transaction amount (e.g. a year or an account number).
            if 0 < value < Decimal("1000000000"):
                return value
    return None


def _extract_direction(text: str) -> Optional[str]:
    lowered = text.lower()
    debit_hit = any(w in lowered for w in DEBIT_WORDS)
    credit_hit = any(w in lowered for w in CREDIT_WORDS)
    if debit_hit and not credit_hit:
        return "expense"
    if credit_hit and not debit_hit:
        return "income"
    if debit_hit and credit_hit:
        # "debited ... credited to" is ambiguous; prefer the first mention.
        positions = [lowered.find(w) for w in DEBIT_WORDS if w in lowered]
        credits = [lowered.find(w) for w in CREDIT_WORDS if w in lowered]
        if positions and credits:
            return "expense" if min(positions) < min(credits) else "income"
    return None


def _extract_date(text: str) -> Optional[datetime]:
    for i, pattern in enumerate(DATE_PATTERNS):
        m = pattern.search(text)
        if not m:
            continue
        try:
            if i == 0:  # YYYY-MM-DD
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if i == 1:  # DD/MM/YYYY or MM/DD/YYYY - prefer DD/MM for India
                d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if d > 12:
                    return datetime(y, mo, d)
                return datetime(y, mo, min(d, 12)) if mo <= 12 else None
            if i == 2:  # DD-MMM-YYYY
                return datetime(int(m.group(3)), MONTHS[m.group(2).lower()[:3]], int(m.group(1)))
            # DD MMM YY
            year = int(m.group(3))
            year = year + 2000 if year < 70 else year + 1900
            return datetime(year, MONTHS[m.group(2).lower()[:3]], int(m.group(1)))
        except (ValueError, KeyError):
            continue
    return None


def _extract_reference(text: str) -> Optional[str]:
    for pattern in REF_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(m.lastindex or 1)
    return None


def _extract_merchant(text: str) -> Optional[str]:
    """Best-effort merchant name from the 'for <MERCHANT>' / 'to <MERCHANT>' tail.

    The capture stops at the first trailing banking keyword (``via``, ``ref``,
    ``avl bal``, ...) rather than at the end of the message, because real SMS
    bodies continue with the account/tail data.
    """
    stop = (
        r"(?:via|through|upi|neft|imps|ref|avl|avail|bal|balance|trxn|txn|"
        r"a/c|acct|account|on|dated|for\s+\d)"
    )
    patterns = (
        re.compile(rf"\bfor\s+([A-Za-z0-9][A-Za-z0-9&.\-]{{1,40}}(?:\s+[A-Za-z0-9&.\-]{{1,20}})*?)\s+(?={stop}|$)", re.IGNORECASE),
        re.compile(rf"\bto\s+([A-Za-z0-9][A-Za-z0-9&.\-]{{1,40}}(?:\s+[A-Za-z0-9&.\-]{{1,20}})*?)\s+(?={stop}|$)", re.IGNORECASE),
        re.compile(rf"\bfrom\s+([A-Za-z0-9][A-Za-z0-9&.\-]{{1,40}}(?:\s+[A-Za-z0-9&.\-]{{1,20}})*?)\s+(?={stop}|$)", re.IGNORECASE),
    )
    for pattern in patterns:
        m = pattern.search(text)
        if m:
            candidate = re.sub(r"\s+", " ", m.group(1)).strip(" .-")
            # Reject pure noise such as a masked account number.
            if candidate and len(candidate) > 1 and not candidate.replace("X", "").replace("x", "").isdigit():
                return candidate
    return None


def parse_sms(raw_text: str) -> Dict:
    """Extract transaction fields from a bank SMS.

    Returns a dict matching :class:`app.schemas.transaction.SmsParseResponse`.
    Every uncertain field is ``None`` and explained in ``notes``.
    """
    text = (raw_text or "").strip()
    notes: List[str] = []

    if not text:
        return {
            "amount": None,
            "transaction_type": None,
            "merchant": None,
            "category": None,
            "transaction_date": None,
            "bank_reference": None,
            "confidence": 0.0,
            "parser": PARSER_NAME,
            "raw_text": raw_text or "",
            "notes": ["Empty input."],
        }

    amount = _extract_amount(text)
    direction = _extract_direction(text)
    date_value = _extract_date(text)
    reference = _extract_reference(text)
    merchant = _extract_merchant(text)

    # Certainty: an amount plus a direction is the minimum for a usable record.
    confidence = 0.0
    if amount is not None:
        confidence += 0.4
    else:
        notes.append("No amount found. The message may not be a payment notification.")
    if direction is not None:
        confidence += 0.25
    else:
        notes.append(
            "Could not tell whether money was debited or credited; set the type manually."
        )
    if date_value is not None:
        confidence += 0.15
    else:
        notes.append("No transaction date found; it will default to now.")
    if merchant is not None:
        confidence += 0.1
    if reference is not None:
        confidence += 0.1

    category = None
    if merchant or text:
        category = predict_category(merchant or "", text, float(amount) if amount else None)

    if date_value is None:
        date_value = datetime.now()

    is_emi = any(marker in text.lower() for marker in EMI_MARKERS)
    if is_emi:
        category = "EMI"
        notes.append("Detected an EMI debit; category set to EMI.")

    return {
        "amount": amount,
        "transaction_type": direction,
        "merchant": merchant,
        "category": category,
        "transaction_date": date_value,
        "bank_reference": reference,
        "confidence": round(min(confidence, 0.99), 4),
        "parser": PARSER_NAME,
        "raw_text": raw_text,
        "notes": notes,
    }

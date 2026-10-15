"""Pure financial maths helpers shared across services."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import List

TWO = Decimal("2")
ONE_HUNDRED = Decimal("100")
MONEY = Decimal("0.01")


def to_decimal(value) -> Decimal:
    """Coerce to ``Decimal`` via string to avoid float artefacts."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def money(value) -> Decimal:
    """Round to 2 decimal places using banker-safe half-up rounding."""
    return to_decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def calculate_emi(
    principal: Decimal, annual_rate_percent: Decimal, tenure_months: int
) -> Decimal:
    """Standard reducing-balance EMI.

    ``EMI = P * r * (1+r)^n / ((1+r)^n - 1)`` where ``r`` is the monthly rate.
    A zero-interest loan reduces to ``P / n``.
    """
    p = to_decimal(principal)
    months = int(tenure_months)
    if months <= 0:
        raise ValueError("tenure_months must be positive")
    if p <= 0:
        raise ValueError("principal must be positive")

    monthly_rate = to_decimal(annual_rate_percent) / ONE_HUNDRED / Decimal("12")
    if monthly_rate == 0:
        return money(p / Decimal(months))

    growth = (Decimal(1) + monthly_rate) ** months
    emi = p * monthly_rate * growth / (growth - Decimal(1))
    return money(emi)


def amortisation_schedule(
    principal: Decimal, annual_rate_percent: Decimal, tenure_months: int
) -> List[dict]:
    """Return a per-installment principal/interest split.

    The final installment absorbs the rounding remainder so the sum of
    principal components equals the original principal exactly.
    """
    p = to_decimal(principal)
    monthly_rate = to_decimal(annual_rate_percent) / ONE_HUNDRED / Decimal("12")
    emi = calculate_emi(p, annual_rate_percent, tenure_months)

    balance = p
    rows: List[dict] = []
    for n in range(1, int(tenure_months) + 1):
        if monthly_rate == 0:
            interest = Decimal("0")
        else:
            interest = money(balance * monthly_rate)
        principal_part = emi - interest if n < tenure_months else balance
        if principal_part < 0:
            principal_part = Decimal("0")
        principal_part = money(min(principal_part, balance))
        balance = money(balance - principal_part)
        rows.append(
            {
                "installment_number": n,
                "emi": emi,
                "principal": principal_part,
                "interest": interest,
                "balance_after": balance,
            }
        )
    return rows


def total_interest(principal: Decimal, annual_rate_percent: Decimal, tenure_months: int) -> Decimal:
    emi = calculate_emi(principal, annual_rate_percent, tenure_months)
    return money(emi * Decimal(int(tenure_months)) - to_decimal(principal))


def safe_div(numerator: Decimal, denominator: Decimal, default: Decimal = Decimal("0")) -> Decimal:
    """Division that never raises on a zero denominator."""
    if denominator == 0:
        return default
    return numerator / denominator


def clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    return max(low, min(high, value))


def _group_indian(integer_digits: str) -> str:
    """Group an integer digit string the Indian way: last 3, then pairs.

    ``"1234567"`` -> ``"12,34,567"``. Western grouping (``"1,234,567"``) is
    deliberately not used: the whole app formats money in the ``en-IN`` style.
    """
    if len(integer_digits) <= 3:
        return integer_digits
    head, tail = integer_digits[:-3], integer_digits[-3:]
    groups: List[str] = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    groups.append(tail)
    return ",".join(groups)


def format_inr(value) -> str:
    """Render a numeric value as Indian-rupee display text.

    Display only - it never mutates or rounds the value that is *stored*; the
    input is only quantised to two decimals for presentation. Output looks like
    ``₹1,23,456.78`` and matches the ``en-IN`` formatting the mobile and web
    clients use. Anything that is not a finite number is returned unchanged as a
    string, so an unexpected type degrades to "show the raw value" instead of
    raising inside a response builder.
    """
    if value is None:
        return ""
    try:
        amount = money(value)
    except (InvalidOperation, TypeError, ValueError):
        return str(value)
    sign = "-" if amount < 0 else ""
    integer, _, fraction = f"{abs(amount):.2f}".partition(".")
    return f"₹{sign}{_group_indian(integer)}.{fraction}"
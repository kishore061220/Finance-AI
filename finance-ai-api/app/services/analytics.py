"""Spending analytics, budget tracking and insight generation.

All aggregation is done in Python over already-sorted rows rather than in SQL
so the same code path serves the API, the reports and the tests.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from app.utils.money import money, safe_div, to_decimal

# Budget utilisation thresholds that generate a warning.
BUDGET_WARN_AT = Decimal("0.80")
BUDGET_CRITICAL_AT = Decimal("1.00")

# Recurring-payment amounts must vary by no more than this coefficient of
# variation to be considered a fixed subscription charge.
MAX_RECURRING_CV = 0.25


def _is_expense(tx) -> bool:
    return getattr(tx.transaction_type, "value", str(tx.transaction_type)) == "expense"


def _is_income(tx) -> bool:
    return getattr(tx.transaction_type, "value", str(tx.transaction_type)) == "income"


def _month_key(d: datetime) -> Tuple[int, int]:
    return d.year, d.month


def filter_period(
    transactions: Iterable, start: Optional[datetime] = None, end: Optional[datetime] = None
) -> List:
    rows = list(transactions)
    if start:
        rows = [t for t in rows if t.transaction_date >= start]
    if end:
        rows = [t for t in rows if t.transaction_date <= end]
    return sorted(rows, key=lambda t: t.transaction_date, reverse=True)


def month_bounds(year: int, month: int) -> Tuple[datetime, datetime]:
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1) - timedelta(seconds=1)
    else:
        end = datetime(year, month + 1, 1) - timedelta(seconds=1)
    return start, end


def totals(transactions: Iterable) -> Dict[str, Decimal]:
    income = Decimal("0")
    expense = Decimal("0")
    for tx in transactions:
        amount = to_decimal(tx.amount)
        if _is_income(tx):
            income += amount
        elif _is_expense(tx):
            expense += amount
    net = money(income - expense)
    return {
        "income": money(income),
        "expense": money(expense),
        "net": net,
        "savings_rate_percent": round(
            float(safe_div(net, income, Decimal("0")) * 100), 2
        ),
    }


def category_breakdown(transactions: Iterable) -> List[Dict]:
    """Expense totals per category, highest first."""
    buckets: Dict[str, Decimal] = defaultdict(Decimal)
    for tx in transactions:
        if _is_expense(tx):
            buckets[tx.category] += to_decimal(tx.amount)
    grand = sum(buckets.values(), Decimal("0"))
    rows = [
        {
            "category": cat,
            "amount": money(amount),
            "percent": round(float(safe_div(amount, grand, Decimal("0")) * 100), 2),
        }
        for cat, amount in buckets.items()
    ]
    rows.sort(key=lambda r: r["amount"], reverse=True)
    return rows


def merchant_breakdown(transactions: Iterable, limit: int = 10) -> List[Dict]:
    buckets: Dict[str, Decimal] = defaultdict(Decimal)
    for tx in transactions:
        if _is_expense(tx) and tx.merchant:
            buckets[tx.merchant] += to_decimal(tx.amount)
    rows = [
        {"merchant": m, "amount": money(a)} for m, a in buckets.items()
    ]
    rows.sort(key=lambda r: r["amount"], reverse=True)
    return rows[:limit]


def daily_series(transactions: Iterable, days: int = 30) -> List[Dict]:
    """Daily expense total for the last ``days`` days, zero-filled."""
    rows = list(transactions)
    if not rows:
        return []
    anchor = max(t.transaction_date for t in rows).date()
    start = anchor - timedelta(days=days - 1)
    buckets: Dict[date, Decimal] = defaultdict(Decimal)
    for tx in rows:
        if _is_expense(tx) and tx.transaction_date.date() >= start:
            buckets[tx.transaction_date.date()] += to_decimal(tx.amount)
    return [
        {"date": (start + timedelta(days=i)).isoformat(), "amount": money(buckets.get(start + timedelta(days=i), Decimal("0")))}
        for i in range(days)
    ]


def monthly_series(transactions: Iterable) -> List[Dict]:
    """Income/expense per calendar month across the supplied rows."""
    income: Dict[Tuple[int, int], Decimal] = defaultdict(Decimal)
    expense: Dict[Tuple[int, int], Decimal] = defaultdict(Decimal)
    for tx in transactions:
        key = _month_key(tx.transaction_date)
        if _is_income(tx):
            income[key] += to_decimal(tx.amount)
        elif _is_expense(tx):
            expense[key] += to_decimal(tx.amount)
    keys = sorted(set(income) | set(expense))
    return [
        {
            "year": y,
            "month": m,
            "label": f"{y:04d}-{m:02d}",
            "income": money(income.get((y, m), Decimal("0"))),
            "expense": money(expense.get((y, m), Decimal("0"))),
            "net": money(income.get((y, m), Decimal("0")) - expense.get((y, m), Decimal("0"))),
        }
        for y, m in keys
    ]


def budget_progress(budgets: Sequence, transactions: Sequence) -> List[Dict]:
    """Compare each budget against actual spend for the same period.

    ``budgets`` and ``transactions`` must already be filtered to the same
    user and the same (year, month) period - the route layer does that.
    """
    actual: Dict[str, Decimal] = defaultdict(Decimal)
    for tx in transactions:
        if _is_expense(tx):
            actual[tx.category] += to_decimal(tx.amount)

    out: List[Dict] = []
    for b in budgets:
        spent = money(actual.get(b.category, Decimal("0")))
        limit = to_decimal(b.amount)
        ratio = safe_div(spent, limit, Decimal("0"))
        remaining = money(limit - spent)
        if ratio >= BUDGET_CRITICAL_AT:
            state = "OVER"
        elif ratio >= BUDGET_WARN_AT:
            state = "WARNING"
        else:
            state = "OK"
        out.append(
            {
                "budget_id": b.id,
                "category": b.category,
                "month": b.month,
                "year": b.year,
                "limit": money(limit),
                "spent": spent,
                "remaining": remaining,
                "used_percent": round(float(ratio * 100), 2),
                "status": state,
            }
        )
    out.sort(key=lambda r: r["used_percent"], reverse=True)
    return out


def generate_insights(
    transactions: Sequence, budgets: Sequence = ()
) -> List[Dict]:
    """Rule-based, explainable financial insights for the dashboard.

    Every insight carries the numbers it was derived from so the UI can show
    the reasoning rather than an opaque claim.
    """
    insights: List[Dict] = []
    if not transactions:
        return [
            {
                "type": "NO_DATA",
                "severity": "INFO",
                "title": "No transactions yet",
                "message": "Add or import transactions to unlock spending insights.",
            }
        ]

    t = totals(transactions)
    breakdown = category_breakdown(transactions)

    if t["income"] > 0 and t["savings_rate_percent"] < 0:
        insights.append(
            {
                "type": "NEGATIVE_SAVINGS",
                "severity": "HIGH",
                "title": "Spending exceeds income",
                "message": (
                    f"Expenses are {money(abs(t['net']))} above income "
                    f"({t['savings_rate_percent']}% savings rate)."
                ),
                "data": {"net": str(t["net"])},
            }
        )
    elif t["income"] > 0 and t["savings_rate_percent"] < 10:
        insights.append(
            {
                "type": "LOW_SAVINGS",
                "severity": "MEDIUM",
                "title": "Low savings rate",
                "message": f"Only {t['savings_rate_percent']}% of income is being saved.",
                "data": {"savings_rate_percent": t["savings_rate_percent"]},
            }
        )

    if breakdown:
        top = breakdown[0]
        if top["percent"] >= 40 and len(breakdown) > 1:
            insights.append(
                {
                    "type": "CONCENTRATED_SPENDING",
                    "severity": "MEDIUM",
                    "title": f"{top['category']} dominates spending",
                    "message": (
                        f"{top['percent']}% of expenses went to {top['category']} "
                        f"({top['amount']})."
                    ),
                    "data": top,
                }
            )

    for b in budget_progress(budgets, transactions) if budgets else []:
        if b["status"] == "OVER":
            insights.append(
                {
                    "type": "BUDGET_EXCEEDED",
                    "severity": "HIGH",
                    "title": f"{b['category']} budget exceeded",
                    "message": (
                        f"Spent {b['spent']} against a {b['limit']} budget "
                        f"({b['used_percent']}%)."
                    ),
                    "data": b,
                }
            )
        elif b["status"] == "WARNING":
            insights.append(
                {
                    "type": "BUDGET_WARNING",
                    "severity": "MEDIUM",
                    "title": f"{b['category']} budget nearly used",
                    "message": f"{b['used_percent']}% of the {b['limit']} budget is spent.",
                    "data": b,
                }
            )

    # Month-over-month expense change.
    months = monthly_series(transactions)
    if len(months) >= 2:
        prev, curr = months[-2], months[-1]
        if prev["expense"] > 0:
            change = safe_div(curr["expense"] - prev["expense"], prev["expense"], Decimal("0"))
            change_pct = round(float(change * 100), 2)
            if abs(change_pct) >= 15:
                direction = "up" if change_pct > 0 else "down"
                insights.append(
                    {
                        "type": "MONTH_OVER_MONTH",
                        "severity": "INFO" if direction == "down" else "MEDIUM",
                        "title": f"Expenses {direction} {abs(change_pct)}%",
                        "message": (
                            f"{curr['label']} expenses were {curr['expense']} vs "
                            f"{prev['expense']} in {prev['label']}."
                        ),
                        "data": {"change_percent": change_pct, "current": curr, "previous": prev},
                    }
                )

    # Recurring subscription detection.
    subs = detect_recurring(transactions)
    for s in subs:
        insights.append(
            {
                "type": "RECURRING_PAYMENT",
                "severity": "INFO",
                "title": f"Recurring: {s['merchant']}",
                "message": (
                    f"{s['occurrences']} payments of about {s['average_amount']} "
                    f"- roughly {s['monthly_cost']} per month."
                ),
                "data": s,
            }
        )

    return insights


def detect_recurring(transactions: Sequence, min_occurrences: int = 3) -> List[Dict]:
    """Detect near-monthly recurring merchants with stable amounts.

    Stability is measured with the coefficient of variation (stdev / mean).
    A subscription is charged the same amount each month, so a high spread
    means the merchant is simply a frequently-used shop, not a subscription.
    """
    buckets: Dict[str, List[Decimal]] = defaultdict(list)
    for tx in transactions:
        if _is_expense(tx) and tx.merchant:
            buckets[tx.merchant.strip().lower()].append(to_decimal(tx.amount))

    out: List[Dict] = []
    for merchant, amounts in buckets.items():
        if len(amounts) < min_occurrences:
            continue
        avg = sum(amounts, Decimal("0")) / Decimal(len(amounts))
        if avg <= 0:
            continue
        variance = sum((a - avg) ** 2 for a in amounts) / Decimal(len(amounts))
        coefficient_of_variation = float(variance.sqrt() / avg)
        if coefficient_of_variation > MAX_RECURRING_CV:
            continue
        monthly = money(avg * Decimal("4.345"))
        out.append(
            {
                "merchant": merchant,
                "occurrences": len(amounts),
                "average_amount": money(avg),
                "coefficient_of_variation": round(coefficient_of_variation, 4),
                "monthly_cost": monthly,
                "annual_cost": money(monthly * Decimal("12")),
            }
        )
    out.sort(key=lambda r: r["monthly_cost"], reverse=True)
    return out


def dashboard_summary(
    transactions: Sequence, budgets: Sequence, alerts: Sequence
) -> Dict:
    """Single payload backing the web and mobile dashboards."""
    t = totals(transactions)
    return {
        "totals": {k: str(v) for k, v in t.items()},
        "category_breakdown": category_breakdown(transactions),
        "top_merchants": merchant_breakdown(transactions),
        "budget_progress": budget_progress(budgets, transactions),
        "monthly_trend": monthly_series(transactions),
        "insights": generate_insights(transactions, budgets),
        "fraud_summary": {
            "total": len(alerts),
            "unread": sum(1 for a in alerts if not a.is_read),
        },
        "recurring": detect_recurring(transactions),
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }

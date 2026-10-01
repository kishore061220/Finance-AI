"""Loan / EMI calculation service."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional

from app.utils.money import (
    amortisation_schedule,
    calculate_emi,
    money,
    to_decimal,
    total_interest,
)

LOAN_TYPES = (
    "Home Loan",
    "Car Loan",
    "Personal Loan",
    "Education Loan",
    "Business Loan",
    "Other",
)


def build_loan_terms(
    principal, annual_rate_percent, tenure_months
) -> Dict[str, Decimal]:
    """Compute EMI, total payable and total interest for a loan offer."""
    p = to_decimal(principal)
    months = int(tenure_months)
    emi = calculate_emi(p, annual_rate_percent, months)
    total_payable = money(emi * Decimal(months))
    return {
        "monthly_emi": emi,
        "total_payable": total_payable,
        "total_interest": total_interest(p, annual_rate_percent, months),
    }


def emi_calculator(principal, annual_rate_percent, tenure_months) -> Dict:
    """Public calculator payload used by the mobile/web EMI screens."""
    terms = build_loan_terms(principal, annual_rate_percent, tenure_months)
    schedule = amortisation_schedule(
        to_decimal(principal), annual_rate_percent, int(tenure_months)
    )
    return {
        "principal": money(to_decimal(principal)),
        "annual_rate": money(to_decimal(annual_rate_percent)),
        "tenure_months": int(tenure_months),
        "monthly_emi": terms["monthly_emi"],
        "total_payable": terms["total_payable"],
        "total_interest": terms["total_interest"],
        "schedule": schedule,
    }


def loan_summary(payments) -> Dict:
    """Aggregate a loan's payment schedule into progress figures.

    ``payments`` are ``LoanPayment``-like objects exposing ``amount``,
    ``status`` and ``principal_component``.
    """
    total_due = Decimal("0")
    total_paid = Decimal("0")
    total_principal = Decimal("0")
    paid_count = 0
    overdue_count = 0
    next_due = None

    for p in payments:
        total_due += to_decimal(p.amount)
        total_principal += to_decimal(getattr(p, "principal_component", 0) or 0)
        status = getattr(p.status, "value", str(p.status))
        if status == "PAID":
            total_paid += to_decimal(p.amount)
            paid_count += 1
        elif status == "OVERDUE":
            overdue_count += 1
        if next_due is None and status != "PAID":
            next_due = p.due_date

    outstanding = money(total_due - total_paid)
    progress = 0.0
    if total_due > 0:
        progress = round(float((total_paid / total_due) * 100), 2)

    return {
        "total_due": money(total_due),
        "total_paid": money(total_paid),
        "outstanding": outstanding,
        "installments_paid": paid_count,
        "installments_total": len(payments),
        "overdue_count": overdue_count,
        "principal_repaid": money(total_principal),
        "completion_percent": progress,
        "next_due_date": next_due,
    }


def upcoming_installments(payments, limit: int = 3) -> List[Dict]:
    """The next ``limit`` unpaid installments, soonest first."""
    pending = [
        p for p in payments if getattr(p.status, "value", str(p.status)) != "PAID"
    ]
    pending.sort(key=lambda p: p.due_date)
    return [
        {
            "installment_number": p.installment_number,
            "due_date": p.due_date,
            "amount": money(to_decimal(p.amount)),
            "status": getattr(p.status, "value", str(p.status)),
        }
        for p in pending[:limit]
    ]


def prepayment_impact(
    principal, annual_rate_percent, tenure_months, prepay
) -> Dict:
    """Effect of paying ``prepay`` extra in the first month."""
    base = emi_calculator(principal, annual_rate_percent, tenure_months)
    p = to_decimal(principal)
    extra = to_decimal(prepay)
    if extra <= 0 or extra >= p:
        return {
            "valid": False,
            "reason": "Prepayment must be greater than 0 and less than the principal.",
        }

    revised_principal = p - extra
    terms = build_loan_terms(revised_principal, annual_rate_percent, tenure_months)
    return {
        "valid": True,
        "prepayment": money(extra),
        "original_emi": base["monthly_emi"],
        "revised_emi": terms["monthly_emi"],
        "original_interest": base["total_interest"],
        "revised_interest": terms["total_interest"],
        "interest_saved": money(base["total_interest"] - terms["total_interest"]),
    }

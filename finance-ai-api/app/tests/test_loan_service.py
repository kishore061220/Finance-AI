"""Tests for loan / EMI service calculations."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.services.loan_service import (
    build_loan_terms,
    emi_calculator,
    loan_summary,
    prepayment_impact,
    upcoming_installments,
)


def _payment(n, amount, status, due, principal_component="0"):
    return SimpleNamespace(
        installment_number=n,
        amount=Decimal(amount),
        status=status,
        due_date=date(2026, 1, due),
        principal_component=Decimal(principal_component),
    )


def test_build_loan_terms_consistency():
    t = build_loan_terms(Decimal("1000000"), Decimal("12"), 12)
    assert t["monthly_emi"] * 12 == t["total_payable"]
    assert t["total_interest"] == t["total_payable"] - Decimal("1000000")


def test_emi_calculator_payload_shape():
    out = emi_calculator(Decimal("250000"), Decimal("10.5"), 24)
    assert out["tenure_months"] == 24
    assert len(out["schedule"]) == 24
    assert out["total_interest"] > 0


def test_loan_summary_partial_payments():
    payments = [
        _payment(1, "10000", "PAID", 5, "9500"),
        _payment(2, "10000", "PAID", 5, "9580"),
        _payment(3, "10000", "PENDING", 5),
        _payment(4, "10000", "OVERDUE", 5),
    ]
    s = loan_summary(payments)
    assert s["total_due"] == Decimal("40000")
    assert s["total_paid"] == Decimal("20000")
    assert s["outstanding"] == Decimal("20000")
    assert s["installments_paid"] == 2
    assert s["installments_total"] == 4
    assert s["overdue_count"] == 1
    assert s["completion_percent"] == 50.0
    assert s["next_due_date"] == date(2026, 1, 5)


def test_loan_summary_zero_values():
    s = loan_summary([])
    assert s["total_due"] == Decimal("0")
    assert s["completion_percent"] == 0.0
    assert s["next_due_date"] is None


def test_upcoming_installments_sorted_and_limited():
    payments = [
        _payment(3, "1000", "PENDING", 20),
        _payment(1, "1000", "PAID", 5),
        _payment(2, "1000", "PENDING", 10),
        _payment(4, "1000", "PENDING", 30),
    ]
    rows = upcoming_installments(payments, limit=2)
    assert [r["installment_number"] for r in rows] == [2, 3]


def test_prepayment_reduces_interest():
    out = prepayment_impact(Decimal("1000000"), Decimal("12"), 12, Decimal("200000"))
    assert out["valid"] is True
    assert out["revised_interest"] < out["original_interest"]
    assert out["interest_saved"] > 0


def test_prepayment_rejects_overshoot():
    out = prepayment_impact(Decimal("100000"), Decimal("12"), 12, Decimal("100000"))
    assert out["valid"] is False
    assert "reason" in out
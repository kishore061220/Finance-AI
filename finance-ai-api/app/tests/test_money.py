"""Tests for the money / EMI maths."""

from decimal import Decimal

import pytest

from app.utils.money import (
    amortisation_schedule,
    calculate_emi,
    money,
    safe_div,
    total_interest,
)


def test_money_rounds_half_up():
    assert money(Decimal("10.005")) == Decimal("10.01")
    assert money(Decimal("10.004")) == Decimal("10.00")


def test_zero_interest_emi_is_principal_over_term():
    assert calculate_emi(Decimal("120000"), Decimal("0"), 12) == Decimal("10000.00")


def test_known_emi_value():
    # 1,000,000 at 12% p.a. (1% monthly) over 12 months.
    # r = 0.01, (1.01)^12 = 1.12682503
    # EMI = 1e6 * 0.01 * 1.12682503 / (1.12682503 - 1) = 88,848.79
    emi = calculate_emi(Decimal("1000000"), Decimal("12"), 12)
    assert emi == Decimal("88848.79")


def test_emi_rejects_bad_inputs():
    with pytest.raises(ValueError):
        calculate_emi(Decimal("1000"), Decimal("10"), 0)
    with pytest.raises(ValueError):
        calculate_emi(Decimal("0"), Decimal("10"), 12)


def test_schedule_principal_sums_to_original():
    principal = Decimal("500000")
    rows = amortisation_schedule(principal, Decimal("9.5"), 24)
    assert len(rows) == 24
    total_principal = sum(r["principal"] for r in rows)
    assert total_principal == principal
    assert rows[-1]["balance_after"] == Decimal("0.00")


def test_schedule_interest_decreases_monotonically():
    rows = amortisation_schedule(Decimal("1000000"), Decimal("12"), 24)
    interests = [r["interest"] for r in rows]
    assert all(interests[i] >= interests[i + 1] for i in range(len(interests) - 1))


def test_total_interest_positive_for_interest_bearing_loan():
    interest = total_interest(Decimal("1000000"), Decimal("12"), 12)
    assert interest > 0


def test_total_interest_zero_for_zero_rate():
    assert total_interest(Decimal("120000"), Decimal("0"), 12) == Decimal("0")


def test_safe_div_handles_zero_denominator():
    assert safe_div(Decimal("10"), Decimal("0"), Decimal("5")) == Decimal("5")
    assert safe_div(Decimal("10"), Decimal("2")) == Decimal("5")
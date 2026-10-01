"""Tests for the SMS parser."""

from datetime import datetime
from decimal import Decimal

from app.services.sms_parser import parse_sms


def test_debit_upi_sms():
    text = (
        "Your A/c XX1234 is debited by Rs.1,234.56 on 05-Mar-2026 for "
        "SWIGGY BANGALORE via UPI Ref No 987654321012"
    )
    out = parse_sms(text)
    assert out["amount"] == Decimal("1234.56")
    assert out["transaction_type"] == "expense"
    assert out["transaction_date"] == datetime(2026, 3, 5)
    assert out["bank_reference"] == "987654321012"
    assert out["merchant"]
    assert "SWIGGY" in out["merchant"].upper()
    assert out["category"] == "Food"
    assert out["confidence"] > 0.8


def test_credit_sms_is_income():
    text = (
        "Rs 85000.00 has been credited to your account on 2026-03-01 "
        "towards salary ref No ABC12345678"
    )
    out = parse_sms(text)
    assert out["amount"] == Decimal("85000.00")
    assert out["transaction_type"] == "income"
    assert out["transaction_date"] == datetime(2026, 3, 1)
    assert out["bank_reference"] == "ABC12345678"
    assert out["category"] == "Salary"


def test_emi_sms_sets_emi_category():
    text = (
        "EMI of Rs 25000.00 has been debited from your A/c towards Home Loan "
        "on 2026-03-05 Avl Bal: 500000.00"
    )
    out = parse_sms(text)
    assert out["amount"] == Decimal("25000.00")
    assert out["transaction_type"] == "expense"
    assert out["category"] == "EMI"
    assert any("EMI" in n for n in out["notes"])


def test_atm_withdrawal_sms():
    text = "ATM WDL Rs.5000.00 on 10/03/2026 at ATM ID 12345"
    out = parse_sms(text)
    assert out["amount"] == Decimal("5000.00")
    assert out["transaction_type"] == "expense"
    assert out["category"] == "Withdrawal"


def test_iso_date_format():
    out = parse_sms("INR 250 debited on 2026-03-07 for Netflix")
    assert out["transaction_date"] == datetime(2026, 3, 7)


def test_empty_input_is_safe():
    out = parse_sms("")
    assert out["amount"] is None
    assert out["confidence"] == 0.0
    assert out["notes"]


def test_unparseable_text_reports_low_confidence():
    out = parse_sms("Your OTP for login is 445122. Do not share it.")
    assert out["confidence"] < 0.5
    # 445122 must not be mistaken for a transaction amount.
    assert out["amount"] != Decimal("445122")


def test_missing_direction_is_reported():
    out = parse_sms("Rs 500.00 at 12:00 somewhere")
    assert out["transaction_type"] is None
    assert any("debited or credited" in n for n in out["notes"])


def test_missing_date_defaults_to_now_with_note():
    out = parse_sms("Rs 500.00 debited for coffee")
    assert isinstance(out["transaction_date"], datetime)
    assert any("No transaction date" in n for n in out["notes"])


def test_thousand_separator_grouping():
    out = parse_sms("Rs 1,50,000.00 debited on 2026-03-09 for rent")
    assert out["amount"] == Decimal("150000.00")
    assert out["category"] == "Rent"


def test_amount_without_currency_prefix():
    out = parse_sms("Charged 1999.99 to your card on 2026-03-11 at Amazon")
    assert out["amount"] == Decimal("1999.99")
    assert out["transaction_type"] == "expense"
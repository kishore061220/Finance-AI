"""Tests for the categorization engine."""

from app.services.categorization import (
    DEFAULT_CATEGORY,
    all_categories,
    predict_category,
    predict_category_detailed,
)


def test_swiggy_is_food():
    assert predict_category("SWIGGY", "Order delivered") == "Food"


def test_amazon_is_shopping():
    assert predict_category("Amazon", "Order #123") == "Shopping"


def test_uber_is_travel():
    assert predict_category("Uber", "Trip fare") == "Travel"


def test_salary_is_salary_income():
    assert predict_category("SALARY CREDIT", "ACME Corp payroll") == "Salary"


def test_atm_withdrawal_beats_generic_transfer():
    # "ATM WDL" must not be classified as a plain transfer.
    assert predict_category("ATM WDL", "Cash withdrawal") == "Withdrawal"


def test_unknown_merchant_falls_back_to_other():
    assert predict_category("ZZZZ Unknown Vendor", "") == DEFAULT_CATEGORY


def test_empty_input_falls_back():
    assert predict_category("", "") == DEFAULT_CATEGORY


def test_detail_reports_confidence_and_keywords():
    out = predict_category_detailed("Swiggy", "Food order", 450)
    assert out["category"] == "Food"
    assert 0 < out["confidence"] <= 0.99
    assert "swiggy" in out["matched_keywords"]
    assert out["engine"] == "keyword-rules"


def test_detail_never_reports_fake_confidence():
    out = predict_category_detailed("Blah Blah Corp", "n/a", 10)
    assert out["confidence"] == 0.0
    assert out["notes"]


def test_all_categories_includes_default():
    cats = all_categories()
    assert DEFAULT_CATEGORY in cats
    assert "Food" in cats
    assert len(cats) == len(set(cats))
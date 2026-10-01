"""Tests for the OCR statement parser."""

from decimal import Decimal

from app.services.ocr_parser import detect_currency, parse_statement


def test_detect_currency_inr():
    assert detect_currency("Total ₹1,250.00") == "INR"
    assert detect_currency("Amount Due: Rs 400") == "INR"
    assert detect_currency("Total") is None


def test_parse_statement_line_items():
    text = """
    ACME MART
    Date: 2026-03-10
    Swiggy Order                     ₹450.00
    Amazon Shopping                  ₹1200.00
    Salary Credit                  ₹85000.00 CR
    Grand Total                    ₹86650.00
    """
    out = parse_statement(text)
    assert out["currency"] == "INR"
    items = out["line_items"]
    assert len(items) == 3
    assert items[0]["description"] == "Swiggy Order"
    assert items[0]["amount"] == Decimal("450.00")
    assert items[2]["transaction_type"] == "income"  # marked CR
    assert items[0]["category"] == "Food"
    assert out["total"] == Decimal("86650.00")


def test_total_beats_generic_number():
    text = "Item A 100.00\nItem B 200.00\nGrand Total: 300.00"
    out = parse_statement(text)
    assert out["total"] == Decimal("300.00")


def test_boilerplate_lines_are_skipped():
    text = (
        "HDFC Bank\n"
        "Account No: 50100234567890\n"
        "IFSC: HDFC0000123\n"
        "Statement Period: 01/03/2026 - 31/03/2026\n"
        "Pizza Delivery 599.00\n"
    )
    out = parse_statement(text)
    assert len(out["line_items"]) == 1
    assert out["line_items"][0]["amount"] == Decimal("599.00")


def test_merchant_detection():
    text = "WHOLE FOODS MARKET\nMilk 120.00\nBread 80.00\nTotal 200.00"
    out = parse_statement(text)
    assert out["merchant"] == "WHOLE FOODS MARKET"


def test_no_line_items_reports_honest_note():
    out = parse_statement("Just some random text with no numbers")
    assert out["line_items"] == []
    assert out["confidence"] < 0.5
    assert any("manually" in n for n in out["notes"])


def test_partial_page_mismatch_is_flagged():
    text = "Item A 100.00\nItem B 200.00\nTotal 9999.00"
    out = parse_statement(text)
    assert any("partial page" in n for n in out["notes"])


def test_date_detection_from_statement_period():
    text = "Statement Date 2026-03-10\nCoffee 90.00\nTotal 90.00"
    out = parse_statement(text)
    assert out["transaction_date"].year == 2026
    assert out["transaction_date"].month == 3


def test_boilerplate_only_text_yields_nothing():
    out = parse_statement("Thank you for banking with us\nwww.example.com")
    assert out["line_items"] == []
    assert out["merchant"] is None

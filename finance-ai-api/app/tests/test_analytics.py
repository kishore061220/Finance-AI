"""Tests for the analytics / insights layer."""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from app.services.analytics import (
    budget_progress,
    category_breakdown,
    daily_series,
    detect_recurring,
    generate_insights,
    merchant_breakdown,
    monthly_series,
    totals,
)


def tx(amount, ttype="expense", category="Food", merchant="M", d=datetime(2026, 3, 15, 12)):
    return SimpleNamespace(
        amount=Decimal(str(amount)),
        transaction_type=ttype,
        category=category,
        merchant=merchant,
        transaction_date=d,
    )


def test_totals_and_savings_rate():
    rows = [tx(100, "income", "Salary"), tx(40, "expense"), tx(10, "expense")]
    t = totals(rows)
    assert t["income"] == Decimal("100.00")
    assert t["expense"] == Decimal("50.00")
    assert t["net"] == Decimal("50.00")
    assert t["savings_rate_percent"] == 50.0


def test_totals_savings_rate_zero_when_no_income():
    t = totals([tx(100), tx(20)])
    assert t["savings_rate_percent"] == 0.0
    assert t["net"] == Decimal("-120.00")


def test_category_breakdown_sorted_with_percent():
    rows = [
        tx(30, category="Food", merchant="A"),
        tx(60, category="Travel", merchant="B"),
        tx(10, category="Food", merchant="C"),
    ]
    out = category_breakdown(rows)
    assert out[0]["category"] == "Travel"
    assert out[0]["percent"] == 60.0
    assert out[1]["amount"] == Decimal("40.00")
    assert round(sum(r["percent"] for r in out)) == 100


def test_merchant_breakdown_limits():
    rows = [tx(10, merchant=f"M{i}") for i in range(15)]
    assert len(merchant_breakdown(rows, limit=5)) == 5


def test_monthly_series_groups_by_month():
    rows = [
        tx(100, "income", d=datetime(2026, 1, 5)),
        tx(20, d=datetime(2026, 1, 20)),
        tx(50, d=datetime(2026, 2, 3)),
    ]
    out = monthly_series(rows)
    assert len(out) == 2
    assert out[0]["label"] == "2026-01"
    assert out[0]["expense"] == Decimal("20.00")
    assert out[1]["expense"] == Decimal("50.00")


def test_daily_series_is_zero_filled():
    rows = [tx(100, d=datetime(2026, 3, 10))]
    series = daily_series(rows, days=5)
    assert len(series) == 5
    assert series[-1]["amount"] == Decimal("100.00")
    assert series[0]["amount"] == Decimal("0.00")


def test_budget_progress_states():
    budget = SimpleNamespace(
        id=1, category="Food", month=3, year=2026, amount=Decimal("100")
    )
    rows = [tx(85, category="Food")]
    out = budget_progress([budget], rows)[0]
    assert out["used_percent"] == 85.0
    assert out["status"] == "WARNING"
    assert out["remaining"] == Decimal("15.00")

    rows2 = [tx(120, category="Food")]
    over = budget_progress([budget], rows2)[0]
    assert over["status"] == "OVER"
    assert over["remaining"] == Decimal("-20.00")


def test_detect_recurring_requires_stability():
    stable = [tx(9.99, merchant="Netflix", d=datetime(2026, 1, i)) for i in (2, 12, 22)]
    out = detect_recurring(stable)
    assert out and out[0]["merchant"] == "netflix"
    assert out[0]["occurrences"] == 3

    unstable = [tx(10, merchant="Shop", d=datetime(2026, 1, 1)),
                tx(500, merchant="Shop", d=datetime(2026, 1, 2)),
                tx(900, merchant="Shop", d=datetime(2026, 1, 3))]
    assert not detect_recurring(unstable)


def test_detect_recurring_needs_min_occurrences():
    rows = [tx(9.99, merchant="Netflix", d=datetime(2026, 1, 2))]
    assert detect_recurring(rows) == []


def test_insights_detect_negative_savings():
    rows = [tx(100, "income", "Salary"), tx(500)]
    kinds = {i["type"] for i in generate_insights(rows)}
    assert "NEGATIVE_SAVINGS" in kinds


def test_insights_detect_budget_exceeded():
    budget = SimpleNamespace(id=1, category="Food", month=3, year=2026, amount=Decimal("50"))
    rows = [tx(90, category="Food")]
    out = generate_insights(rows, [budget])
    assert any(i["type"] == "BUDGET_EXCEEDED" for i in out)


def test_insights_no_data_message():
    out = generate_insights([])
    assert out[0]["type"] == "NO_DATA"


def test_insights_concentrated_spending():
    rows = [tx(100, category="Travel", merchant="Uber")] + [
        tx(20, category="Food", merchant=f"M{i}") for i in range(5)
    ]
    out = generate_insights(rows)
    assert any(i["type"] == "CONCENTRATED_SPENDING" for i in out)
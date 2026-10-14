"""Tests for the fraud rule engine (original and extended)."""

from datetime import datetime

from app.services.fraud_detection import (
    analyze_transaction,
    analyze_with_baseline,
    count_recent_transactions,
    summarize_alerts,
)


def test_low_risk_normal_transaction():
    r = analyze_transaction(500, "Swiggy", datetime(2026, 3, 10, 13))
    assert r["risk_level"] == "LOW"
    assert r["is_fraud"] is False
    assert r["reasons"] == []


def test_original_thresholds_preserved():
    elevated = analyze_transaction(30000, "Shop", datetime(2026, 3, 10, 13))
    assert elevated["risk_score"] == 20
    assert elevated["risk_level"] == "LOW"

    high = analyze_transaction(60000, "Shop", datetime(2026, 3, 10, 13))
    assert high["risk_score"] == 40
    assert high["risk_level"] == "MEDIUM"


def test_unusual_hour_adds_25():
    r = analyze_transaction(100, "Shop", datetime(2026, 3, 10, 3))
    assert any("unusual time" in x for x in r["reasons"])


def test_suspicious_merchant_reaches_high():
    r = analyze_transaction(60000, "test merchant", datetime(2026, 3, 10, 2))
    assert r["risk_score"] >= 95
    assert r["risk_level"] == "HIGH"
    assert r["is_fraud"] is True


def test_baseline_matches_rules_without_history():
    plain = analyze_transaction(100, "Shop", datetime(2026, 3, 10, 13))
    ext = analyze_with_baseline(100, "Shop", datetime(2026, 3, 10, 13))
    assert ext["risk_score"] == plain["risk_score"]
    assert ext["risk_level"] == plain["risk_level"]


def test_baseline_flags_amount_spike():
    out = analyze_with_baseline(
        9000, "Shop", datetime(2026, 3, 10, 13), history_amounts=[100, 120, 90, 110]
    )
    assert "amount_spike" in out["signals"]
    assert out["risk_score"] > 0


def test_baseline_flags_new_merchant():
    out = analyze_with_baseline(
        100, "Brand New Shop", datetime(2026, 3, 10, 13), history_merchants=["swiggy", "amazon"]
    )
    assert "new_merchant" in out["signals"]


def test_baseline_flags_velocity_burst():
    out = analyze_with_baseline(100, "Shop", datetime(2026, 3, 10, 13), transactions_last_24h=7)
    assert "velocity_burst" in out["signals"]


def test_score_is_capped_at_100():
    out = analyze_with_baseline(
        999999,
        "test merchant",
        datetime(2026, 3, 10, 2),
        history_amounts=[10] * 10,
        history_merchants=[],
        transactions_last_24h=20,
    )
    assert out["risk_score"] == 100


def test_count_recent_transactions_window():
    txs = [
        type("T", (), {"transaction_date": datetime(2026, 3, 10, 10)})(),
        type("T", (), {"transaction_date": datetime(2026, 3, 9, 22)})(),
        type("T", (), {"transaction_date": datetime(2026, 3, 1, 10)})(),
    ]
    n = count_recent_transactions(txs, datetime(2026, 3, 10, 12), window_hours=24)
    assert n == 2


def test_summarize_alerts_counts_levels():
    class A:
        def __init__(self, lvl, read):
            self.risk_level = lvl
            self.is_read = read

    out = summarize_alerts([A("HIGH", False), A("LOW", True), A("LOW", False)])
    assert out["total"] == 3
    assert out["by_level"]["HIGH"] == 1
    assert out["by_level"]["LOW"] == 2
    assert out["unread"] == 2


def test_apply_analysis_keeps_a_rules_flag_when_the_blend_dips(monkeypatch):
    """The model must not silently un-flag a transaction the rules flagged.

    Reproduces the case where the rule engine scores just over the threshold
    (e.g. 35) but the weighted blend lands below it (e.g. 20). Previously the
    transaction became ``is_flagged = False`` and no alert was raised at all.
    """
    from decimal import Decimal
    from types import SimpleNamespace

    from app.services import transaction_analysis

    monkeypatch.setattr(
        transaction_analysis,
        "score_transaction",
        lambda transaction, history, db: {
            "rule": {
                "risk_score": 35,
                "risk_level": "MEDIUM",
                "reasons": ["amount_spike"],
                "signals": ["amount_spike"],
            },
            "ml": {
                "status": "combined",
                "combined_score": 20,
                "risk_level": "LOW",
            },
        },
    )

    transaction = SimpleNamespace(
        user_id=1,
        amount=Decimal("100.00"),
        merchant="Shop",
        category="Shopping",
        transaction_date=datetime(2026, 3, 10, 13),
    )

    result = transaction_analysis.apply_analysis(transaction, [], None)

    assert transaction.is_flagged is True
    assert transaction.fraud_score == 35
    assert result["alert"] is not None
    assert result["alert"].risk_level.value == "MEDIUM"
"""The contract between offline training and live scoring.

If these tests fail, a model exported by this package will be scored against the
wrong columns by the backend. That failure is silent - no exception, just worse
fraud scores - so the check is kept explicit and separate from the feature
engineering's own tests.

The backend lives in ``finance-ai-api`` in the same repository, so its feature
builder is imported directly rather than duplicating the expected list. That way
this test tracks the backend automatically instead of going stale when somebody
adds a feature there.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from finance_ai_ml.features import CANONICAL_FEATURES, build_feature_frame

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "finance-ai-api"


def _backend_features():
    """Import the backend's feature builder, skipping if it is not present."""
    if not (BACKEND_ROOT / "main.py").exists():
        pytest.skip(f"backend not found at {BACKEND_ROOT}")
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    from app.ml.features import build_feature_vector

    return build_feature_vector


def test_canonical_list_matches_the_backend_exactly():
    """Same names, same order, same count - no drift allowed."""
    build_feature_vector = _backend_features()

    class Tx:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    sample = Tx(
        transaction_date=__import__("datetime").datetime(2026, 1, 15, 2, 30),
        amount=1000,
        transaction_type="expense",
        category="Shopping",
        merchant="Store",
        emi_type=None,
        source="SMS",
    )
    backend_names = sorted(build_feature_vector(sample))

    assert len(CANONICAL_FEATURES) == len(backend_names), (
        "This module and the backend disagree on the number of features. "
        "One of them was edited without the other."
    )
    assert sorted(CANONICAL_FEATURES) == backend_names


def test_feature_values_agree_on_a_real_row(dataset):
    """Not just the names - the numbers have to mean the same thing."""
    build_feature_vector = _backend_features()
    frame = build_feature_frame(dataset)

    row = dataset.iloc[0]
    merchant_count = int(
        ((dataset["merchant"].fillna("unknown").str.lower()) == str(row["merchant"]).lower()).sum()
    )
    user_count = int((dataset["user_id"] == row["user_id"]).sum())
    user_mean = float(dataset[dataset["user_id"] == row["user_id"]]["amount"].mean())

    class Tx:
        transaction_date = row["transaction_date"]
        amount = float(row["amount"])
        transaction_type = row["transaction_type"]
        category = row["category"]
        merchant = row["merchant"]
        emi_type = row["emi_type"]
        source = row["source"]

    expected = build_feature_vector(
        Tx(),
        user_mean_amount=user_mean,
        merchant_seen_count=merchant_count,
        user_tx_count=user_count,
    )

    for name, value in expected.items():
        produced = float(frame.iloc[0][name])
        assert produced == pytest.approx(value, abs=1e-9), (
            f"Feature {name!r} differs between offline training and live "
            f"scoring: offline={produced}, backend={value}."
        )


def test_contract_error_is_raised_on_drift(monkeypatch, dataset):
    """A missing column must fail loudly, not train on a shifted matrix."""
    import finance_ai_ml.features as features_module

    real = features_module.build_feature_frame(dataset)
    truncated = real.drop(columns=["amount_log"])

    with pytest.raises(features_module.FeatureContractError) as excinfo:
        features_module.assert_feature_contract(truncated)
    assert "amount_log" in str(excinfo.value)


def test_reordered_columns_are_repaired_not_rejected(dataset):
    """Correct columns in a different order are fine - the order is restated."""
    import finance_ai_ml.features as features_module

    shuffled = build_feature_frame(dataset)[list(reversed(CANONICAL_FEATURES))]
    repaired = features_module.assert_feature_contract(shuffled)
    assert list(repaired.columns) == CANONICAL_FEATURES

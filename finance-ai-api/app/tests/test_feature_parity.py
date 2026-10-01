"""The API and the standalone trainer must agree on the feature set.

``finance-ai-ml`` declares its feature list alphabetically as
``CANONICAL_FEATURES``; ``app.ml.features`` builds a vector in semantic order.
The orders differ deliberately, and ``trainer.score_transaction`` projects the
vector onto whatever order the loaded artifact recorded, so a model trained by
either package scores correctly.

The *set* of names is still a hard contract: if one side renames or adds a
feature and the other does not, the extra column is silently dropped at scoring
time (``row.get(name, 0.0)``) and the model degrades without any error. That is
the failure this test exists to catch.

``app.ml.features`` imports stdlib only, so this runs without the ML package's
pandas/sklearn stack installed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.ml import features as api_features

ML_ROOT = Path(__file__).resolve().parents[3] / "finance-ai-ml"


def _api_vector_keys() -> list[str]:
    class _Transaction:
        transaction_date = "2026-10-01T12:00:00"
        amount = 100.0
        transaction_type = "expense"
        category = "Food"
        merchant = "Cafe"
        description = None
        emi_type = None
        source = "MANUAL"

    return list(
        api_features.build_feature_vector(
            _Transaction(),
            user_mean_amount=50.0,
            merchant_seen_count=2,
            user_tx_count=7,
        ).keys()
    )


def _ml_canonical_features() -> list[str]:
    if not ML_ROOT.is_dir():
        pytest.skip("finance-ai-ml is not present next to the API")
    sys.path.insert(0, str(ML_ROOT))
    try:
        from finance_ai_ml.features import CANONICAL_FEATURES

        return list(CANONICAL_FEATURES)
    except ImportError as exc:  # pragma: no cover - dependency not installed
        pytest.skip(f"finance_ai_ml is not importable: {exc}")
    finally:
        sys.path.remove(str(ML_ROOT))


def _ml_artifact_format_version() -> int:
    """The sidecar layout version the standalone package writes and requires."""
    if not ML_ROOT.is_dir():
        pytest.skip("finance-ai-ml is not present next to the API")
    sys.path.insert(0, str(ML_ROOT))
    try:
        from finance_ai_ml.export import ARTIFACT_FORMAT_VERSION

        return ARTIFACT_FORMAT_VERSION
    except ImportError as exc:  # pragma: no cover - dependency not installed
        pytest.skip(f"finance_ai_ml is not importable: {exc}")
    finally:
        sys.path.remove(str(ML_ROOT))


class TestSharedFeatureContract:
    def test_api_vector_has_31_features(self):
        assert len(_api_vector_keys()) == 31

    def test_ml_declares_31_features(self):
        assert len(_ml_canonical_features()) == 31

    def test_both_sides_declare_the_same_names(self):
        assert set(_ml_canonical_features()) == set(_api_vector_keys())

    def test_the_orders_differ_so_the_artifact_order_is_load_bearing(self):
        # If these ever become equal the assertion above still holds, but the
        # projection in score_transaction stops being load-bearing. Worth knowing
        # when it happens, because it means the contract has quietly changed.
        assert _ml_canonical_features() != _api_vector_keys()

    def test_no_duplicate_names_on_either_side(self):
        api_keys = _api_vector_keys()
        ml_names = _ml_canonical_features()
        assert len(set(api_keys)) == len(api_keys)
        assert len(set(ml_names)) == len(ml_names)

    def test_artifact_format_version_matches_the_standalone_package(self):
        from app.ml.trainer import ARTIFACT_FORMAT_VERSION

        assert ARTIFACT_FORMAT_VERSION == _ml_artifact_format_version()

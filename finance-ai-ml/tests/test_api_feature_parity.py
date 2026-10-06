"""The API and this package must agree on the fraud feature set.

``finance_ai_ml.features.CANONICAL_FEATURES`` declares the 31 feature names
alphabetically; ``app.ml.features.build_feature_vector`` builds the same 31
features in semantic order. The orders differ deliberately, and
``app.ml.trainer.score_transaction`` projects the vector onto whatever order the
loaded artifact recorded, so a model trained by either side scores correctly.

The *set* of names is still a hard contract. If one side renames or adds a
feature and the other does not, the extra column is silently dropped at scoring
time (``row.get(name, 0.0)``) and the model degrades with no error at all. That
is the failure this test exists to catch.

This test lives here rather than in the API's test suite for a concrete reason:
it must be runnable from the ML job, whose dependency set deliberately excludes
the API's (fastapi, sqlalchemy, alembic). Both modules imported here are stdlib
only, so this test needs nothing beyond what the ML job already installs.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "finance-ai-api"
ML_ROOT = REPO_ROOT / "finance-ai-ml"


def _load_api_feature_module():
    """Import ``app.ml.features`` from the sibling backend checkout.

    Importing it costs nothing: ``app/ml/features.py`` is free of pandas and
    sklearn imports at module level precisely so the backend can import it
    cheaply.
    """
    if not (API_ROOT / "app" / "ml" / "features.py").is_file():
        pytest.skip(
            "finance-ai-api is not present next to finance-ai-ml. This package is "
            "usable standalone; the cross-check only runs in a full checkout."
        )
    if str(API_ROOT) not in sys.path:
        sys.path.insert(0, str(API_ROOT))
    from app.ml import features as api_features

    return api_features


def _api_vector_keys() -> list[str]:
    api_features = _load_api_feature_module()

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
    from finance_ai_ml.features import CANONICAL_FEATURES

    return list(CANONICAL_FEATURES)


def _api_artifact_format_version() -> int:
    _load_api_feature_module()
    from app.ml.trainer import ARTIFACT_FORMAT_VERSION

    return ARTIFACT_FORMAT_VERSION


class TestSharedFeatureContract:
    def test_this_package_declares_31_features(self):
        assert len(_ml_canonical_features()) == 31

    def test_the_api_vector_has_31_features(self):
        assert len(_api_vector_keys()) == 31

    def test_both_sides_declare_the_same_names(self):
        assert set(_ml_canonical_features()) == set(_api_vector_keys())

    def test_no_duplicate_names_on_either_side(self):
        api_keys = _api_vector_keys()
        ml_names = _ml_canonical_features()
        assert len(set(api_keys)) == len(api_keys)
        assert len(set(ml_names)) == len(ml_names)

    def test_the_orders_differ_so_the_artifact_order_stays_load_bearing(self):
        # Scoring is safe precisely because the two orders differ and the
        # artifact's recorded order is honoured. If these ever become equal the
        # assertion above still holds, but it means the contract has quietly
        # changed and is worth a look.
        assert _ml_canonical_features() != _api_vector_keys()

    def test_artifact_format_versions_agree(self):
        from finance_ai_ml.export import ARTIFACT_FORMAT_VERSION

        assert _api_artifact_format_version() == ARTIFACT_FORMAT_VERSION

"""Offline training for the Finance-AI fraud model.

This package exists so the model can be trained outside the API - from a CSV
extract, a warehouse export, or a scheduled job - and the resulting artifact
loaded by the backend for scoring.

Two rules govern everything here:

* **The feature contract is fixed.** The backend builds features at scoring time
  with ``app.ml.features``. If this package emitted a different column set, the
  estimator would be fed values it was never trained on and every score would be
  silently wrong. :data:`CANONICAL_FEATURES` mirrors that contract exactly, and
  ``tests/test_parity_with_backend.py`` fails the build if the two drift apart.
* **No number is invented.** Too little labelled data, or a validation set with
  only one class, produces an explicit refusal instead of a metric that looks
  meaningful and is not.
"""

from __future__ import annotations

from finance_ai_ml.config import TrainingConfig
from finance_ai_ml.dataset import DatasetError, load_transactions
from finance_ai_ml.export import export_artifact, read_artifact_metadata
from finance_ai_ml.features import CANONICAL_FEATURES, build_feature_frame
from finance_ai_ml.train import TrainingResult, train

__version__ = "1.0.0"

__all__ = [
    "CANONICAL_FEATURES",
    "DatasetError",
    "TrainingConfig",
    "TrainingResult",
    "build_feature_frame",
    "export_artifact",
    "load_transactions",
    "read_artifact_metadata",
    "train",
]

"""Training configuration.

Every threshold that decides "this data is enough to train" lives here, so the
policy is one readable object rather than a scatter of module constants.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass(frozen=True)
class TrainingConfig:
    """Knobs for :func:`finance_ai_ml.train.train`.

    The defaults are deliberately conservative and match the backend's
    ``app.ml.trainer`` thresholds, so a model trained offline and one trained
    through the API refuse on the same data for the same reason.
    """

    # A stratified hold-out below this many rows is not a validation set.
    min_rows: int = 50
    # A classifier trained on fewer positive examples than this learns the
    # majority class, not fraud.
    min_positives: int = 5
    # Fraction of rows held out for evaluation.
    test_size: float = 0.2
    # Fixed so a rerun on the same data reproduces the same numbers.
    random_state: int = 42
    # Probability at or above which a row is predicted fraudulent.
    threshold: float = 0.5

    # XGBoost hyper-parameters. Deliberately small and heavily regularised:
    # fraud datasets are tiny and imbalanced, and a large model on 200 rows is
    # memorisation wearing a lab coat.
    n_estimators: int = 200
    max_depth: int = 4
    learning_rate: float = 0.05
    subsample: float = 0.9
    colsample_bytree: float = 0.9
    reg_lambda: float = 1.0
    min_child_weight: int = 1

    # Fallback estimator, used when xgboost is not installed.
    fallback_max_iter: int = 200
    fallback_learning_rate: float = 0.05
    fallback_l2: float = 1.0

    def validate(self) -> None:
        if not 0.05 <= self.test_size <= 0.5:
            raise ValueError(
                f"test_size must be between 0.05 and 0.5 (a larger hold-out "
                f"leaves too little to train on); got {self.test_size}."
            )
        if not 0.0 < self.threshold < 1.0:
            raise ValueError(
                f"threshold must be strictly between 0 and 1; got {self.threshold}."
            )
        if self.min_rows < 2:
            raise ValueError("min_rows must be at least 2 to allow a split.")
        if self.min_positives < 1:
            raise ValueError("min_positives must be at least 1.")


__all__ = ["TrainingConfig"]

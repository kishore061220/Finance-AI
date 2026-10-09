"""Train, evaluate and report.

The report is the deliverable. It states what was trained on, what the
held-out numbers were, and - importantly - what those numbers are worth given
how little data there was. A roc_auc of 0.99 on 60 rows with 6 positives means
almost nothing, and saying so is part of the output rather than a footnote.
"""

from __future__ import annotations

import logging
import platform
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from finance_ai_ml.config import TrainingConfig
from finance_ai_ml.features import (
    CANONICAL_FEATURES,
    build_feature_frame,
    extract_labels,
)

logger = logging.getLogger(__name__)

# Below this many positives even a held-out estimate is noise, so the report
# carries a prominent caveat rather than a confident headline metric.
THIN_EVIDENCE_POSITIVES = 20


@dataclass
class TrainingResult:
    status: str
    model: Optional[str] = None
    rows_used: int = 0
    train_rows: int = 0
    test_rows: int = 0
    positives: int = 0
    test_positives: int = 0
    metrics: Dict[str, float] = field(default_factory=dict)
    feature_names: List[str] = field(default_factory=list)
    message: str = ""
    caveats: List[str] = field(default_factory=list)
    trained_at: Optional[str] = None
    library_versions: Dict[str, str] = field(default_factory=dict)
    # Per-candidate metrics when the model was chosen by compare_models().
    comparison: Dict[str, Dict[str, float]] = field(default_factory=dict)
    estimator: object = None

    @property
    def ok(self) -> bool:
        return self.status == "trained"

    def as_dict(self) -> Dict:
        """Serialisable view. The estimator is deliberately excluded."""
        body = asdict(self)
        body.pop("estimator", None)
        return body


def _versions() -> Dict[str, str]:
    import sklearn

    versions = {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scikit-learn": sklearn.__version__,
    }
    try:
        import xgboost

        versions["xgboost"] = xgboost.__version__
    except ImportError:
        pass
    return versions


def make_estimator(positive_rate: float, config: TrainingConfig):
    """XGBoost when installed, otherwise sklearn's HistGradientBoosting."""
    try:
        from xgboost import XGBClassifier

        return (
            XGBClassifier(
                n_estimators=config.n_estimators,
                max_depth=config.max_depth,
                learning_rate=config.learning_rate,
                subsample=config.subsample,
                colsample_bytree=config.colsample_bytree,
                reg_lambda=config.reg_lambda,
                min_child_weight=config.min_child_weight,
                # Counter the imbalance explicitly; without this a model on
                # 5% positives converges on predicting "clean" every time.
                scale_pos_weight=(1 - positive_rate) / positive_rate
                if positive_rate > 0
                else 1.0,
                eval_metric="logloss",
                tree_method="hist",
                random_state=config.random_state,
            ),
            "xgboost",
        )
    except ImportError:
        from sklearn.ensemble import HistGradientBoostingClassifier

        return (
            HistGradientBoostingClassifier(
                max_iter=config.fallback_max_iter,
                max_depth=config.max_depth,
                learning_rate=config.fallback_learning_rate,
                l2_regularization=config.fallback_l2,
                random_state=config.random_state,
            ),
            "sklearn-hist-gradient-boosting",
        )


def _caveats(config: TrainingConfig, positives: int, test_positives: int) -> List[str]:
    notes: List[str] = []
    if positives < THIN_EVIDENCE_POSITIVES:
        notes.append(
            f"Only {positives} positive examples. The held-out metrics below are "
            "an indication, not evidence - a single misclassified fraud case "
            "moves roc_auc by several points. Treat this model as a starting "
            "point and re-train once substantially more labelled data exists."
        )
    if test_positives <= 2:
        notes.append(
            f"The validation split contains {test_positives} positive "
            f"example(s). Precision and recall on that split are not "
            "statistically meaningful; roc_auc is the only figure worth reading."
        )
    notes.append(
        f"These numbers come from a {int(config.test_size * 100)}% stratified "
        "hold-out. They describe performance on unseen rows from this dataset "
        "only, and say nothing about a different user base or a future period."
    )
    return notes


def train(
    frame: pd.DataFrame,
    config: Optional[TrainingConfig] = None,
) -> TrainingResult:
    """Train the fraud classifier over a cleaned transaction frame.

    Returns a :class:`TrainingResult` with ``status`` set to one of:

    ``trained``
        A real estimator was fitted and evaluated. ``estimator`` holds it.
    ``insufficient_data``
        Not enough rows or positives. No metrics are reported, because any that
        were would be meaningless.
    ``failed``
        Training was attempted and did not complete; ``message`` says why.
    """
    config = config or TrainingConfig()
    config.validate()

    labels = extract_labels(frame)
    usable = labels >= 0
    if not usable.any():
        return TrainingResult(
            status="insufficient_data",
            rows_used=0,
            message=(
                "No labelled rows found. A supervised classifier needs an "
                "is_flagged (or equivalent) column; unlabelled data can only "
                "support the rule engine."
            ),
        )

    frame = frame[usable].reset_index(drop=True)
    labels = labels[usable]

    features = build_feature_frame(frame)
    X = features.to_numpy(dtype=float)
    y = labels.astype(int)

    positives = int(y.sum())
    total = int(len(y))

    if total < config.min_rows:
        return TrainingResult(
            status="insufficient_data",
            rows_used=total,
            positives=positives,
            feature_names=list(CANONICAL_FEATURES),
            message=(
                f"{total} labelled row(s) available; at least {config.min_rows} "
                "are required before a train/validation split means anything."
            ),
            library_versions=_versions(),
        )
    if positives < config.min_positives:
        return TrainingResult(
            status="insufficient_data",
            rows_used=total,
            positives=positives,
            feature_names=list(CANONICAL_FEATURES),
            message=(
                f"Only {positives} positive label(s); at least "
                f"{config.min_positives} confirmed fraud examples are required. "
                "Fewer than that and a classifier simply learns to predict "
                "'clean' every time."
            ),
            library_versions=_versions(),
        )

    from sklearn.metrics import (
        average_precision_score,
        f1_score,
        precision_score,
        recall_score,
        roc_auc_score,
    )
    from sklearn.model_selection import train_test_split

    try:
        X_train, X_test, y_train, y_test = train_test_split(
            X,
            y,
            test_size=config.test_size,
            random_state=config.random_state,
            stratify=y,
        )
    except ValueError as exc:
        return TrainingResult(
            status="failed",
            rows_used=total,
            positives=positives,
            message=f"Could not build a stratified split: {exc}",
            library_versions=_versions(),
        )

    estimator, model_name = make_estimator(float(y_train.mean()), config)
    try:
        estimator.fit(X_train, y_train)
        probabilities = estimator.predict_proba(X_test)[:, 1]
    except Exception as exc:  # noqa: BLE001
        logger.exception("Model fitting failed")
        return TrainingResult(
            status="failed",
            rows_used=total,
            positives=positives,
            message=f"Training the {model_name} estimator failed: {exc}",
            library_versions=_versions(),
        )

    predicted = (probabilities >= config.threshold).astype(int)
    test_positives = int(y_test.sum())

    metrics = {
        "roc_auc": round(float(roc_auc_score(y_test, probabilities)), 4),
        "average_precision": round(
            float(average_precision_score(y_test, probabilities)), 4
        ),
        "precision": round(
            float(precision_score(y_test, predicted, zero_division=0)), 4
        ),
        "recall": round(float(recall_score(y_test, predicted, zero_division=0)), 4),
        "f1": round(float(f1_score(y_test, predicted, zero_division=0)), 4),
    }

    return TrainingResult(
        status="trained",
        model=model_name,
        rows_used=total,
        train_rows=int(len(y_train)),
        test_rows=int(len(y_test)),
        positives=positives,
        test_positives=test_positives,
        metrics=metrics,
        feature_names=list(CANONICAL_FEATURES),
        message=(
            f"Trained on {len(y_train)} rows and evaluated on "
            f"{len(y_test)} held-out rows."
        ),
        caveats=_caveats(config, positives, test_positives),
        trained_at=datetime.now(timezone.utc).isoformat(),
        library_versions=_versions(),
        estimator=estimator,
    )


__all__ = ["THIN_EVIDENCE_POSITIVES", "TrainingResult", "make_estimator", "train"]

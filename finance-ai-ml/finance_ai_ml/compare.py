"""Compare candidate fraud models and select one on documented evidence.

The single-estimator path in :mod:`finance_ai_ml.train` picks XGBoost (or the
sklearn fallback) and reports its held-out metrics. This module exists for the
"train and compare suitable models" requirement: it fits several candidates
against the *same* stratified hold-out, reports precision, recall, F1, PR-AUC,
ROC-AUC, the confusion matrix and false-positive behaviour for each, and
selects the winner by average precision (PR-AUC) rather than accuracy - the
correct choice on a fraud problem where the positive class is under 1%.

Correctness guarantees:

* The train/test split happens **before** any preprocessing is fitted.
* Preprocessing (``StandardScaler`` for the linear model) lives inside a
  scikit-learn ``Pipeline`` and is therefore fitted on the training fold only.
* Class imbalance is handled at the estimator (``class_weight`` /
  ``scale_pos_weight``), never by resampling the test set.
* The exported estimator accepts the raw 31-column feature vector, so the
  backend's ``score_transaction`` can call ``predict_proba`` directly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from finance_ai_ml.config import TrainingConfig
from finance_ai_ml.features import (
    CANONICAL_FEATURES,
    build_feature_frame,
    extract_labels,
)

logger = logging.getLogger(__name__)

THRESHOLD = 0.5


@dataclass
class CandidateResult:
    name: str
    metrics: Dict[str, float]
    estimator: object = field(repr=False, default=None)
    error: Optional[str] = None

    def as_dict(self) -> Dict:
        return {"name": self.name, "metrics": self.metrics, "error": self.error}


@dataclass
class ComparisonResult:
    status: str
    train_rows: int
    test_rows: int
    positives: int
    test_positives: int
    candidates: List[CandidateResult]
    best: Optional[str] = None
    selection_metric: str = "average_precision"
    split: str = "stratified"
    feature_names: List[str] = field(default_factory=list)
    message: str = ""
    caveats: List[str] = field(default_factory=list)

    @property
    def best_candidate(self) -> Optional[CandidateResult]:
        for candidate in self.candidates:
            if candidate.name == self.best:
                return candidate
        return None

    def as_dict(self) -> Dict:
        return {
            "status": self.status,
            "train_rows": self.train_rows,
            "test_rows": self.test_rows,
            "positives": self.positives,
            "test_positives": self.test_positives,
            "best": self.best,
            "selection_metric": self.selection_metric,
            "split": self.split,
            "feature_names": self.feature_names,
            "message": self.message,
            "caveats": self.caveats,
            "candidates": [c.as_dict() for c in self.candidates],
        }


def _logistic(config: TrainingConfig):
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    return Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            (
                "model",
                LogisticRegression(
                    max_iter=2000,
                    class_weight="balanced",
                    random_state=config.random_state,
                ),
            ),
        ]
    )


def _random_forest(config: TrainingConfig):
    from sklearn.ensemble import RandomForestClassifier

    return RandomForestClassifier(
        n_estimators=400,
        max_depth=None,
        min_samples_leaf=2,
        class_weight="balanced_subsample",
        n_jobs=-1,
        random_state=config.random_state,
    )


def _xgboost(config: TrainingConfig, positive_rate: float):
    from xgboost import XGBClassifier

    return XGBClassifier(
        n_estimators=config.n_estimators,
        max_depth=config.max_depth,
        learning_rate=config.learning_rate,
        subsample=config.subsample,
        colsample_bytree=config.colsample_bytree,
        reg_lambda=config.reg_lambda,
        min_child_weight=config.min_child_weight,
        scale_pos_weight=(1 - positive_rate) / positive_rate if positive_rate > 0 else 1.0,
        eval_metric="logloss",
        tree_method="hist",
        random_state=config.random_state,
    )


def _gradient_boosting(config: TrainingConfig):
    from sklearn.ensemble import HistGradientBoostingClassifier

    return HistGradientBoostingClassifier(
        max_iter=config.fallback_max_iter,
        max_depth=config.max_depth,
        learning_rate=config.fallback_learning_rate,
        l2_regularization=config.fallback_l2,
        random_state=config.random_state,
    )


def available_candidates(config: TrainingConfig, positive_rate: float) -> List[tuple]:
    """Return ``(name, factory)`` pairs for every estimator that imports."""
    candidates = [
        ("logistic_regression", lambda: _logistic(config)),
        ("random_forest", lambda: _random_forest(config)),
    ]
    try:
        import xgboost  # noqa: F401

        candidates.append(("xgboost", lambda: _xgboost(config, positive_rate)))
    except ImportError:  # pragma: no cover - exercised when xgboost is absent
        candidates.append(
            ("sklearn-hist-gradient-boosting", lambda: _gradient_boosting(config))
        )
    return candidates


def _metrics(y_true: np.ndarray, probabilities: np.ndarray, threshold: float) -> Dict[str, float]:
    from sklearn.metrics import (
        average_precision_score,
        confusion_matrix,
        f1_score,
        precision_score,
        recall_score,
        roc_auc_score,
    )

    predicted = (probabilities >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, predicted, labels=[0, 1]).ravel()
    negatives = int(tn + fp)
    return {
        "roc_auc": round(float(roc_auc_score(y_true, probabilities)), 4),
        "average_precision": round(float(average_precision_score(y_true, probabilities)), 4),
        "precision": round(float(precision_score(y_true, predicted, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, predicted, zero_division=0)), 4),
        "f1": round(float(f1_score(y_true, predicted, zero_division=0)), 4),
        "threshold": float(threshold),
        "true_negatives": float(tn),
        "false_positives": float(fp),
        "false_negatives": float(fn),
        "true_positives": float(tp),
        "false_positive_rate": round(float(fp / negatives), 6) if negatives else 0.0,
    }


def _caveats(
    config: TrainingConfig, positives: int, test_positives: int, split: str
) -> List[str]:
    notes = []
    if positives < 20:
        notes.append(
            f"Only {positives} positive examples; held-out metrics are an "
            "indication, not evidence."
        )
    if test_positives < 10:
        notes.append(
            f"The test split holds only {test_positives} positives, so precision, "
            "recall and PR-AUC are noisy; treat model ranking with caution."
        )
    if split == "chronological":
        notes.append(
            f"Metrics come from a {int(config.test_size * 100)}% chronological "
            "hold-out: the model trains on older rows and is scored on newer "
            "ones. This is the stricter, deception-resistant estimate."
        )
    else:
        notes.append(
            f"Metrics come from a {int(config.test_size * 100)}% stratified "
            "random hold-out. A random split can overstate performance on "
            "time-ordered fraud; run --split chronological for the stricter test."
        )
    return notes


def _chronological_split(X, y, frame, test_size):
    """Split by time: oldest rows train, newest rows test. No shuffling.

    This is the stricter evaluation for fraud: a random split lets the model
    learn from transactions that occur after the ones it is tested on, which
    overstates real-world performance. Returns the four arrays.
    """
    order = np.argsort(frame["transaction_date"].to_numpy(), kind="mergesort")
    X = X[order]
    y = y[order]
    cut = int(len(y) * (1 - test_size))
    return X[:cut], X[cut:], y[:cut], y[cut:]


def compare_models(
    frame: pd.DataFrame,
    config: Optional[TrainingConfig] = None,
    *,
    split: str = "stratified",
) -> ComparisonResult:
    """Fit and evaluate every available candidate on one shared hold-out.

    ``split`` is ``"stratified"`` (random, class-balanced) or
    ``"chronological"`` (oldest rows train, newest rows test).
    """
    if split not in {"stratified", "chronological"}:
        raise ValueError("split must be 'stratified' or 'chronological'")
    config = config or TrainingConfig()
    config.validate()

    labels = extract_labels(frame)
    usable = labels >= 0
    if not usable.any():
        return ComparisonResult(
            status="insufficient_data",
            train_rows=0,
            test_rows=0,
            positives=0,
            test_positives=0,
            candidates=[],
            message="No labelled rows found.",
        )

    frame = frame[usable].reset_index(drop=True)
    labels = labels[usable]
    features = build_feature_frame(frame)
    X = features.to_numpy(dtype=float)
    y = labels.astype(int)
    positives = int(y.sum())
    total = int(len(y))

    if total < config.min_rows or positives < config.min_positives:
        return ComparisonResult(
            status="insufficient_data",
            train_rows=0,
            test_rows=0,
            positives=positives,
            test_positives=0,
            candidates=[],
            feature_names=list(CANONICAL_FEATURES),
            message=(
                f"{total} labelled rows with {positives} positives; need at least "
                f"{config.min_rows} rows and {config.min_positives} positives."
            ),
        )

    from sklearn.model_selection import train_test_split

    if split == "chronological":
        X_train, X_test, y_train, y_test = _chronological_split(
            X, y, frame, config.test_size
        )
        if len(np.unique(y_train)) < 2 or len(np.unique(y_test)) < 2:
            return ComparisonResult(
                status="failed",
                train_rows=int(len(y_train)),
                test_rows=int(len(y_test)),
                positives=positives,
                test_positives=int(y_test.sum()),
                candidates=[],
                split=split,
                feature_names=list(CANONICAL_FEATURES),
                message=(
                    "The chronological split put all labelled rows of one class "
                    "on a single side; a time-ordered hold-out cannot be built "
                    "from this ordering."
                ),
            )
    else:
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=config.test_size, random_state=config.random_state, stratify=y
        )
    positive_rate = float(y_train.mean())

    results: List[CandidateResult] = []
    for name, factory in available_candidates(config, positive_rate):
        try:
            estimator = factory()
            estimator.fit(X_train, y_train)
            probabilities = estimator.predict_proba(X_test)[:, 1]
            results.append(
                CandidateResult(
                    name=name,
                    metrics=_metrics(y_test, probabilities, THRESHOLD),
                    estimator=estimator,
                )
            )
            logger.info("Trained candidate %s", name)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Candidate %s failed", name)
            results.append(CandidateResult(name=name, metrics={}, error=str(exc)))

    scored = [c for c in results if c.metrics]
    if not scored:
        return ComparisonResult(
            status="failed",
            train_rows=int(len(y_train)),
            test_rows=int(len(y_test)),
            positives=positives,
            test_positives=int(y_test.sum()),
            candidates=results,
            feature_names=list(CANONICAL_FEATURES),
            message="Every candidate failed to train; see per-candidate errors.",
        )

    best = max(scored, key=lambda c: (c.metrics["average_precision"], c.metrics["roc_auc"]))

    return ComparisonResult(
        status="compared",
        train_rows=int(len(y_train)),
        test_rows=int(len(y_test)),
        positives=positives,
        test_positives=int(y_test.sum()),
        candidates=results,
        best=best.name,
        split=split,
        feature_names=list(CANONICAL_FEATURES),
        message=(
            f"Compared {len(scored)} candidate(s) on {len(y_test)} held-out rows "
            f"({int(y_test.sum())} positives) using a {split} split. Selected "
            f"{best.name} by average_precision={best.metrics['average_precision']}."
        ),
        caveats=_caveats(config, positives, int(y_test.sum()), split),
    )


def export_best(result: ComparisonResult, directory) -> "tuple":
    """Export the selected candidate as a backend-compatible artifact.

    Returns ``(model_path, meta_path)``. Raises ``ComparisonError`` when there
    is no trained winner.
    """
    from pathlib import Path

    from finance_ai_ml import export as export_module

    best = result.best_candidate
    if best is None or best.estimator is None:
        raise ComparisonError("No trained candidate to export.")

    # export_artifact expects an object with status/model/estimator/feature_names
    # and an as_dict() method. A tiny adapter keeps the write path identical to
    # the single-estimator flow so both artifacts are byte-for-byte compatible.
    from finance_ai_ml.train import TrainingResult

    payload = {c.name: c.metrics for c in result.candidates}
    training_result = TrainingResult(
        status="trained",
        model=best.name,
        rows_used=result.train_rows + result.test_rows,
        train_rows=result.train_rows,
        test_rows=result.test_rows,
        positives=result.positives,
        test_positives=result.test_positives,
        metrics=best.metrics,
        feature_names=list(result.feature_names),
        message=result.message,
        caveats=result.caveats,
        comparison=payload,
        estimator=best.estimator,
    )
    return export_module.export_artifact(training_result, Path(directory))


class ComparisonError(RuntimeError):
    """The comparison produced no exportable winner."""


__all__ = [
    "CandidateResult",
    "ComparisonError",
    "ComparisonResult",
    "available_candidates",
    "compare_models",
    "export_best",
]

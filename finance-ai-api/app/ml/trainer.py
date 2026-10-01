"""Supervised fraud / anomaly model training and scoring.

Design constraints honoured here:

* The ML layer is a *separate* signal from the deterministic rule engine. The
  rule verdict is never overwritten by the model, and the combined score is a
  weighted blend of the two.
* No metric is ever invented. If there is not enough labelled data to train
  and validate, :func:`train` returns a structured ``insufficient_data``
  result and :func:`score` falls back to the rule score only.
* ``xgboost`` is used when available; otherwise ``sklearn``'s gradient
  boosting is used. Both paths are real, trained models.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from app.ml.features import build_dataset, build_feature_vector

logger = logging.getLogger(__name__)

# Below this many labelled rows a train/validation split is not meaningful.
MIN_TRAIN_ROWS = 50
MIN_POSITIVE_LABELS = 5
ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "ml_artifacts"

# Mirrors finance_ai_ml.export.ARTIFACT_FORMAT_VERSION. Kept in sync by
# app/tests/test_feature_parity.py, which fails if the two drift. Bump this when
# the sidecar layout changes so an older reader refuses the artifact rather than
# silently mis-reading it.
ARTIFACT_FORMAT_VERSION = 1


@dataclass
class Metric:
    name: str
    value: Optional[float]

    def as_dict(self) -> Dict:
        return asdict(self)


@dataclass
class TrainingReport:
    status: str
    model: Optional[str] = None
    rows_used: int = 0
    positives: int = 0
    metrics: List[Metric] = field(default_factory=list)
    feature_names: List[str] = field(default_factory=list)
    message: str = ""
    trained_at: Optional[str] = None
    artifact_path: Optional[str] = None

    def as_dict(self) -> Dict:
        return {
            "status": self.status,
            "model": self.model,
            "rows_used": self.rows_used,
            "positives": self.positives,
            "metrics": [m.as_dict() for m in self.metrics],
            "feature_names": self.feature_names,
            "message": self.message,
            "trained_at": self.trained_at,
            "artifact_path": self.artifact_path,
        }


def check_sklearn() -> Tuple[bool, str]:
    try:
        import sklearn  # noqa: F401
    except ImportError:
        return False, "scikit-learn is not installed"
    return True, ""


def _make_estimator(positive_rate: float):
    """Prefer XGBoost; fall back to sklearn's HistGradientBoosting."""
    try:
        from xgboost import XGBClassifier

        return (
            XGBClassifier(
                n_estimators=200,
                max_depth=4,
                learning_rate=0.05,
                subsample=0.9,
                colsample_bytree=0.9,
                reg_lambda=1.0,
                min_child_weight=1,
                scale_pos_weight=(1 - positive_rate) / positive_rate
                if positive_rate > 0
                else 1.0,
                eval_metric="logloss",
                tree_method="hist",
                random_state=42,
            ),
            "xgboost",
        )
    except ImportError:
        from sklearn.ensemble import HistGradientBoostingClassifier

        return (
            HistGradientBoostingClassifier(
                max_iter=200,
                max_depth=4,
                learning_rate=0.05,
                l2_regularization=1.0,
                random_state=42,
            ),
            "sklearn-hist-gradient-boosting",
        )


def train(
    transactions: Sequence,
    labels: Optional[Sequence[int]] = None,
    *,
    test_size: float = 0.2,
) -> TrainingReport:
    """Train the fraud classifier and return an honest evaluation report."""
    ok, err = check_sklearn()
    if not ok:
        return TrainingReport(status="unavailable", message=err)

    rows, feature_names, y = build_dataset(transactions, labels)
    positives = sum(1 for v in y if v == 1)
    total = len(y)

    if total < MIN_TRAIN_ROWS:
        return TrainingReport(
            status="insufficient_data",
            rows_used=total,
            positives=positives,
            feature_names=feature_names,
            message=(
                f"{total} labelled rows available; at least {MIN_TRAIN_ROWS} are "
                "required for a meaningful train/validation split."
            ),
        )
    if positives < MIN_POSITIVE_LABELS:
        return TrainingReport(
            status="insufficient_data",
            rows_used=total,
            positives=positives,
            feature_names=feature_names,
            message=(
                f"Only {positives} positive label(s); at least {MIN_POSITIVE_LABELS} "
                "fraud examples are required to train a classifier."
            ),
        )

    import numpy as np
    from sklearn.metrics import (
        average_precision_score,
        f1_score,
        precision_score,
        recall_score,
        roc_auc_score,
    )
    from sklearn.model_selection import train_test_split

    X = np.array([[r[name] for name in feature_names] for r in rows], dtype=float)
    Y = np.array(y, dtype=int)

    try:
        X_tr, X_te, y_tr, y_te = train_test_split(
            X, Y, test_size=test_size, random_state=42, stratify=Y
        )
    except ValueError as exc:
        return TrainingReport(
            status="failed",
            rows_used=total,
            positives=positives,
            message=f"Could not create a stratified split: {exc}",
        )

    estimator, model_name = _make_estimator(float(y_tr.mean()))
    estimator.fit(X_tr, y_tr)
    y_prob = estimator.predict_proba(X_te)[:, 1]
    y_pred = (y_prob >= 0.5).astype(int)

    metrics = [
        Metric("roc_auc", round(float(roc_auc_score(y_te, y_prob)), 4)),
        Metric("average_precision", round(float(average_precision_score(y_te, y_prob)), 4)),
        Metric("precision", round(float(precision_score(y_te, y_pred, zero_division=0)), 4)),
        Metric("recall", round(float(recall_score(y_te, y_pred, zero_division=0)), 4)),
        Metric("f1", round(float(f1_score(y_te, y_pred, zero_division=0)), 4)),
    ]

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    path = save(estimator, feature_names, model_name, TrainingReport(
        status="trained",
        model=model_name,
        rows_used=total,
        positives=positives,
        metrics=metrics,
        feature_names=feature_names,
    ))

    return TrainingReport(
        status="trained",
        model=model_name,
        rows_used=total,
        positives=positives,
        metrics=metrics,
        feature_names=feature_names,
        message="Model trained and evaluated on a held-out stratified split.",
        trained_at=_utcnow(),
        artifact_path=str(path),
    )


def save(estimator, feature_names: Sequence[str], model_name: str, report: TrainingReport) -> Path:
    """Persist the estimator plus its feature contract."""
    import pickle

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    model_path = ARTIFACT_DIR / "fraud_model.pkl"
    meta_path = ARTIFACT_DIR / "fraud_model.json"

    with model_path.open("wb") as fh:
        pickle.dump(estimator, fh)
    meta_path.write_text(
        json.dumps(
            {
                "artifact_format_version": ARTIFACT_FORMAT_VERSION,
                "model": model_name,
                "feature_names": list(feature_names),
                "report": report.as_dict(),
                # Integrity check, not a signature: it catches a truncated or
                # partially-overwritten artifact before load() unpickles it.
                "checksum": hashlib.sha256(model_path.read_bytes()).hexdigest(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return model_path


def load() -> Tuple[Optional[object], List[str], str]:
    """Load the persisted model. Returns ``(None, [], message)`` when absent."""
    import pickle

    model_path = ARTIFACT_DIR / "fraud_model.pkl"
    meta_path = ARTIFACT_DIR / "fraud_model.json"
    if not model_path.exists() or not meta_path.exists():
        return None, [], "No trained model artifact found. Run the training job first."
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))

        # Checked before unpickling: pickle.load executes the payload it is given,
        # so an artifact whose bytes changed must not reach it.
        expected = meta.get("checksum")
        if expected:
            actual = hashlib.sha256(model_path.read_bytes()).hexdigest()
            if actual != expected:
                return (
                    None,
                    [],
                    "Fraud model artifact failed its integrity check and was not "
                    "loaded. Retrain the model.",
                )

        with model_path.open("rb") as fh:
            estimator = pickle.load(fh)
        return estimator, meta.get("feature_names", []), ""
    except Exception as exc:  # pragma: no cover - corrupt artifact path
        logger.warning("Failed to load fraud model artifact: %s", exc)
        return None, [], f"Model artifact could not be loaded: {exc}"


def score_transaction(
    transaction,
    *,
    user_mean_amount: Optional[float] = None,
    merchant_seen_count: int = 0,
    user_tx_count: int = 0,
    rule_score: int = 0,
) -> Dict:
    """Score a transaction with the ML model, blended with the rule score.

    The rule score is always available, so this returns a usable verdict even
    when no model has been trained.
    """
    estimator, feature_names, load_error = load()
    if estimator is None or not feature_names:
        return {
            "status": "rules_only",
            "ml_score": None,
            "combined_score": rule_score,
            "risk_level": _level(rule_score),
            "model": None,
            "message": load_error
            or "ML model unavailable; rule engine result returned unchanged.",
        }

    import numpy as np

    row = build_feature_vector(
        transaction,
        user_mean_amount=user_mean_amount,
        merchant_seen_count=merchant_seen_count,
        user_tx_count=user_tx_count,
    )
    X = np.array([[row.get(name, 0.0) for name in feature_names]], dtype=float)
    ml_prob = float(estimator.predict_proba(X)[0][1])
    ml_score = int(round(ml_prob * 100))

    # The rule engine is deterministic and already tuned, so it keeps the
    # larger weight; the model adjusts the score rather than replacing it.
    combined = int(round(rule_score * 0.7 + ml_score * 0.3))
    combined = max(0, min(100, combined))

    return {
        "status": "combined",
        "ml_score": ml_score,
        "ml_probability": round(ml_prob, 4),
        "rule_score": rule_score,
        "combined_score": combined,
        "risk_level": _level(combined),
        "model": type(estimator).__name__,
        "message": "",
    }


def _level(score: int) -> str:
    if score >= 60:
        return "HIGH"
    if score >= 30:
        return "MEDIUM"
    return "LOW"


def _utcnow() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "ARTIFACT_DIR",
    "Metric",
    "TrainingReport",
    "check_sklearn",
    "load",
    "save",
    "score_transaction",
    "train",
]

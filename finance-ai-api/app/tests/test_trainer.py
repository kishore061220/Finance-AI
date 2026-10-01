"""Trainer unit tests.

The HTTP tests can only assert that training is *refused* when there is not
enough data, which means the success path - actually fitting an estimator,
computing metrics, and writing an artifact - is never executed. These tests
exercise that path directly against a synthetic labelled dataset.

Nothing here claims a model is good; the assertions are about behaviour: the
right estimator is chosen, the artifact round-trips, and the guards refuse
rather than fabricating a result.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.ml import features, trainer


def make_transactions(n: int = 80, positives: int = 12):
    """Build a synthetic transaction set with a learnable amount pattern.

    Positive rows get a large amount at an unusual hour; negative rows get a
    small amount during normal hours. That is enough signal for the pipeline to
    produce a model, and it is clearly synthetic rather than real user data.
    """
    rows = []
    base = datetime(2026, 1, 1, 10, 0, 0)
    for i in range(n):
        is_positive = i < positives
        when = base + timedelta(days=i)
        if is_positive:
            rows.append(
                SimpleNamespace(
                    id=i + 1,
                    user_id=1,
                    amount=Decimal("25000.00"),
                    transaction_type="expense",
                    category="Shopping",
                    merchant=f"SUSPICIOUS MERCHANT {i}",
                    transaction_date=when.replace(hour=2),
                    source="MANUAL",
                    is_flagged=True,
                )
            )
        else:
            rows.append(
                SimpleNamespace(
                    id=i + 1,
                    user_id=1,
                    amount=Decimal("120.00"),
                    transaction_type="expense",
                    category="Food",
                    merchant=f"Corner Cafe {i}",
                    transaction_date=when.replace(hour=13),
                    source="MANUAL",
                    is_flagged=False,
                )
            )
    labels = [1 if t.is_flagged else 0 for t in rows]
    return rows, labels


class TestGates:
    def test_undersized_dataset_reports_insufficient_data(self):
        rows, labels = make_transactions(n=20, positives=4)
        report = trainer.train(rows, labels)
        assert report.status == "insufficient_data"
        assert report.rows_used == 20
        assert "at least" in report.message
        assert report.artifact_path is None

    def test_too_few_positives_reports_insufficient_data(self):
        rows, labels = make_transactions(n=80, positives=3)
        report = trainer.train(rows, labels)
        assert report.status == "insufficient_data"
        assert report.positives == 3
        assert "positive" in report.message.lower()

    def test_no_fabricated_metrics_on_refusal(self):
        rows, labels = make_transactions(n=20, positives=4)
        report = trainer.train(rows, labels)
        assert report.metrics == []
        assert report.model is None
        assert report.trained_at is None

    def test_degenerate_single_class_reports_failure(self):
        rows, labels = make_transactions(n=80, positives=0)
        report = trainer.train(rows, labels)
        assert report.status == "insufficient_data"


class TestEstimatorSelection:
    def test_prefers_xgboost_when_importable(self):
        estimator, name = trainer._make_estimator(0.15)
        assert name == "xgboost"
        assert type(estimator).__name__ == "XGBClassifier"

    def test_falls_back_to_sklearn_when_xgboost_missing(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "xgboost":
                raise ImportError("xgboost deliberately hidden for this test")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        estimator, name = trainer._make_estimator(0.15)
        assert name == "sklearn-hist-gradient-boosting"
        assert type(estimator).__name__ == "HistGradientBoostingClassifier"

    def test_check_sklearn_reports_available(self):
        ok, reason = trainer.check_sklearn()
        assert ok is True
        assert reason == ""


class TestTrainingSucceeds:
    @pytest.fixture
    def trained(self, tmp_path, monkeypatch):
        """Train for real, with the artifact directory redirected to tmp."""
        monkeypatch.setattr(trainer, "ARTIFACT_DIR", tmp_path / "ml_artifacts")
        rows, labels = make_transactions()
        return trainer.train(rows, labels), rows, labels

    def test_reports_trained(self, trained):
        report, _, _ = trained
        assert report.status == "trained"
        assert report.rows_used == 80
        assert report.positives == 12
        assert report.model in ("xgboost", "sklearn-hist-gradient-boosting")
        assert report.trained_at is not None

    def test_metrics_are_computed_and_in_range(self, trained):
        report, _, _ = trained
        by_name = {m.name: m.value for m in report.metrics}
        assert set(by_name) == {
            "roc_auc",
            "average_precision",
            "precision",
            "recall",
            "f1",
        }
        for value in by_name.values():
            assert value is not None
            assert 0.0 <= value <= 1.0

    def test_recalls_the_synthetic_pattern(self, trained):
        """The synthetic signal is learnable, so the model should find it.

        This guards against a pipeline that silently returns a degenerate
        constant predictor while still reporting metrics.
        """
        report, _, _ = trained
        by_name = {m.name: m.value for m in report.metrics}
        assert by_name["roc_auc"] >= 0.9

    def test_artifact_written(self, trained, tmp_path):
        report, _, _ = trained
        artifact = tmp_path / "ml_artifacts"
        assert (artifact / "fraud_model.pkl").exists()
        assert (artifact / "fraud_model.json").exists()
        assert report.artifact_path == str(artifact / "fraud_model.pkl")

    def test_artifact_metadata_matches_model(self, trained, tmp_path):
        report, _, _ = trained
        meta = json.loads((tmp_path / "ml_artifacts" / "fraud_model.json").read_text())
        assert meta["model"] == report.model
        assert meta["feature_names"] == report.feature_names
        assert meta["report"]["status"] == "trained"

    def test_artifact_metadata_is_self_describing(self, trained, tmp_path):
        """The sidecar must carry its layout version and an integrity checksum.

        finance-ai-ml reads these artifacts, and an artifact without them cannot
        be validated before unpickling.
        """
        report, _, _ = trained
        artifact = tmp_path / "ml_artifacts"
        meta = json.loads((artifact / "fraud_model.json").read_text())
        assert meta["artifact_format_version"] == trainer.ARTIFACT_FORMAT_VERSION
        expected = hashlib.sha256((artifact / "fraud_model.pkl").read_bytes()).hexdigest()
        assert meta["checksum"] == expected

    def test_load_rejects_a_tampered_artifact(self, trained, tmp_path):
        """A modified model file must not be unpickled.

        pickle.load executes its payload, so an artifact that changed on disk
        after export is refused instead of trusted.
        """
        trained  # noqa: B018 - the fixture writes the artifact being tampered with
        model_path = tmp_path / "ml_artifacts" / "fraud_model.pkl"
        model_path.write_bytes(model_path.read_bytes() + b"tampered")

        estimator, feature_names, load_error = trainer.load()
        assert estimator is None
        assert feature_names == []
        assert "integrity" in load_error.lower()

    def test_scoring_falls_back_to_rules_when_the_artifact_is_tampered(self, trained, tmp_path):
        rows, _ = make_transactions(n=1, positives=1)
        model_path = tmp_path / "ml_artifacts" / "fraud_model.pkl"
        model_path.write_bytes(model_path.read_bytes() + b"tampered")

        result = trainer.score_transaction(rows[0], rule_score=40)
        assert result["status"] == "rules_only"
        assert result["combined_score"] == 40

    def test_load_round_trips(self, trained, tmp_path):
        report, _, _ = trained
        estimator, feature_names, load_error = trainer.load()
        assert estimator is not None
        assert load_error == ""
        assert feature_names == report.feature_names

    def test_scoring_uses_loaded_model(self, trained):
        """score_transaction must blend the model instead of rules-only."""
        rows, _ = make_transactions(n=1, positives=1)
        result = trainer.score_transaction(rows[0], rule_score=40)
        assert result["status"] == "combined"
        assert result["ml_score"] is not None
        assert 0.0 <= result["combined_score"] <= 100.0


class TestScoreFallback:
    def test_rules_only_when_no_artifact(self, tmp_path, monkeypatch):
        monkeypatch.setattr(trainer, "ARTIFACT_DIR", tmp_path / "empty")
        result = trainer.score_transaction(
            SimpleNamespace(
                id=1,
                user_id=1,
                amount=Decimal("500.00"),
                transaction_type="expense",
                category="Shopping",
                merchant="Some Merchant",
                transaction_date=datetime(2026, 1, 1, 12),
                source="MANUAL",
                is_flagged=False,
            ),
            rule_score=45,
        )
        assert result["status"] == "rules_only"
        assert result["ml_score"] is None
        # The rule score is passed through unchanged, so the caller still gets
        # a usable verdict instead of a null.
        assert result["combined_score"] == 45
        assert result["risk_level"]
        assert result["message"]

    def test_load_reports_missing_artifact_honestly(self, tmp_path, monkeypatch):
        monkeypatch.setattr(trainer, "ARTIFACT_DIR", tmp_path / "empty")
        estimator, feature_names, load_error = trainer.load()
        assert estimator is None
        assert feature_names == []
        assert load_error


class TestFeatures:
    def test_build_dataset_shapes_match(self):
        rows, labels = make_transactions(n=30, positives=6)
        matrix, feature_names, y = features.build_dataset(rows, labels)
        assert len(matrix) == 30
        assert len(y) == 30
        assert y.count(1) == 6
        for row in matrix:
            assert set(row) == set(feature_names)

    def test_all_feature_values_are_numeric(self):
        rows, labels = make_transactions(n=30, positives=6)
        matrix, feature_names, _ = features.build_dataset(rows, labels)
        for row in matrix:
            for name in feature_names:
                assert isinstance(row[name], (int, float))
                assert row[name] == row[name]  # not NaN

    def test_labels_override_the_unsupervised_heuristic(self):
        rows, _ = make_transactions(n=30, positives=6)
        _, _, derived = features.build_dataset(rows, None)
        _, _, explicit = features.build_dataset(rows, [0] * 30)
        assert explicit == [0] * 30
        assert derived != explicit

    def test_single_vector_matches_dataset_row(self):
        rows, labels = make_transactions(n=5, positives=1)
        matrix, feature_names, _ = features.build_dataset(rows, labels)
        vector = features.build_feature_vector(rows[0])
        for name in feature_names:
            assert name in vector
        # Every value the dataset computed must also be reachable per-row.
        assert set(vector) >= set(feature_names)

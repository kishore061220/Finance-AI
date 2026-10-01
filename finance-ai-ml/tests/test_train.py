"""Training, refusal and artifact export."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from finance_ai_ml.config import TrainingConfig
from finance_ai_ml.dataset import load_transactions
from finance_ai_ml.export import (
    ArtifactError,
    META_FILENAME,
    MODEL_FILENAME,
    export_artifact,
    export_to_backend,
    load_artifact,
    read_artifact_metadata,
)
from finance_ai_ml.features import CANONICAL_FEATURES, build_feature_frame
from finance_ai_ml.train import train


class TestRefusals:
    def test_too_few_rows_is_refused(self, tiny_dataset):
        """A number is not produced when the data cannot support one."""
        result = train(tiny_dataset)
        assert result.status == "insufficient_data"
        assert result.metrics == {}
        assert result.estimator is None
        assert str(TrainingConfig().min_rows) in result.message

    def test_too_few_positives_is_refused(self, raw_dataset):
        """Enough rows but almost no fraud: a classifier would predict 'clean'."""
        data = raw_dataset.copy()
        data["is_flagged"] = 0
        data.loc[0:1, "is_flagged"] = 1
        result = train(load_transactions(data))
        assert result.status == "insufficient_data"
        assert "positive label" in result.message
        assert result.metrics == {}

    def test_no_labels_at_all_is_refused(self, raw_dataset):
        data = raw_dataset.copy()
        data["is_flagged"] = None
        result = train(load_transactions(data))
        assert result.status == "insufficient_data"
        assert "No labelled rows" in result.message

    def test_refusal_reports_library_versions(self, tiny_dataset):
        """A refused run is still a data point about the environment."""
        result = train(tiny_dataset)
        assert "pandas" in result.library_versions
        assert "scikit-learn" in result.library_versions

    def test_invalid_config_is_rejected(self, dataset):
        for bad in (
            TrainingConfig(test_size=0.9),
            TrainingConfig(threshold=0.0),
            TrainingConfig(min_rows=1),
        ):
            with pytest.raises(ValueError):
                train(dataset, bad)


class TestTraining:
    def test_sufficient_data_trains(self, dataset):
        result = train(dataset)
        assert result.status == "trained"
        assert result.model in ("xgboost", "sklearn-hist-gradient-boosting")
        assert result.estimator is not None
        assert result.rows_used == len(dataset)
        assert result.positives == int(dataset["label"].sum())

    def test_split_sizes_are_reported_and_correct(self, dataset):
        result = train(dataset)
        assert result.train_rows + result.test_rows == result.rows_used
        assert result.test_positives > 0
        assert result.test_positives < result.positives

    def test_all_metrics_are_present_and_bounded(self, dataset):
        result = train(dataset)
        assert set(result.metrics) == {
            "roc_auc", "average_precision", "precision", "recall", "f1"
        }
        for name, value in result.metrics.items():
            assert 0.0 <= value <= 1.0, f"{name} out of range: {value}"

    def test_model_finds_the_synthetic_signal(self, dataset):
        """The generator has a real distribution shift, so a real model finds it.

        If this fails the metrics are meaningless - it would mean either the
        features or the labels are broken, not that XGBoost is bad.
        """
        result = train(dataset)
        assert result.metrics["roc_auc"] > 0.8
    def test_caveats_are_attached_to_thin_data(self, dataset):
        """A high score on 12 positives is not evidence, and must say so."""
        result = train(dataset)
        assert result.caveats
        joined = " ".join(result.caveats).lower()
        assert "indication, not evidence" in joined
        assert "hold-out" in joined

    def test_training_is_reproducible(self, dataset):
        first = train(dataset)
        second = train(dataset)
        assert first.metrics == second.metrics

    def test_result_serialises_without_the_estimator(self, dataset):
        result = train(dataset)
        payload = result.as_dict()
        assert "estimator" not in payload
        # It must be JSON-serialisable for the CLI and the report.
        json.dumps(payload, default=str)
        assert payload["status"] == "trained"
        assert payload["trained_at"]


class TestFeatures:
    def test_frame_has_the_canonical_columns_in_order(self, dataset):
        frame = build_feature_frame(dataset)
        assert list(frame.columns) == CANONICAL_FEATURES
        assert len(frame) == len(dataset)

    def test_empty_frame_returns_empty_canonical_frame(self):
        frame = build_feature_frame(pd.DataFrame(columns=["amount", "transaction_date"]))
        assert list(frame.columns) == CANONICAL_FEATURES
        assert len(frame) == 0

    def test_no_nans_or_infinities(self, dataset):
        """A NaN in the matrix silently becomes a prediction on some backends."""
        frame = build_feature_frame(dataset)
        values = frame.to_numpy(dtype=float)
        assert not np.isnan(values).any()
        assert not np.isinf(values).any()

    def test_amount_vs_mean_is_relative_to_the_user(self, dataset):
        frame = build_feature_frame(dataset)
        means = dataset.groupby("user_id")["amount"].transform("mean")
        expected = (dataset["amount"] / means).fillna(0.0)
        np.testing.assert_allclose(
            frame["amount_vs_mean"].to_numpy(), expected.to_numpy(), rtol=1e-9
        )

    def test_income_is_not_treated_as_expense(self, dataset):
        data = dataset.copy()
        data.loc[0:4, "transaction_type"] = "income"
        frame = build_feature_frame(data)
        assert frame["is_income"].iloc[0] == 1.0
        assert frame["is_expense"].iloc[0] == 0.0


class TestArtifactExport:
    def test_export_writes_the_pair_the_backend_expects(self, dataset, tmp_path):
        result = train(dataset)
        model_path, meta_path = export_artifact(result, tmp_path)

        assert model_path.name == MODEL_FILENAME
        assert meta_path.name == META_FILENAME
        assert model_path.exists() and meta_path.exists()

    def test_metadata_carries_the_feature_contract(self, dataset, tmp_path):
        """This list is what the backend maps columns with, not documentation."""
        result = train(dataset)
        _, meta_path = export_artifact(result, tmp_path)
        metadata = json.loads(meta_path.read_text())
        assert metadata["feature_names"] == CANONICAL_FEATURES
        assert metadata["report"]["status"] == "trained"

    def test_artifact_round_trips(self, dataset, tmp_path):
        result = train(dataset)
        export_artifact(result, tmp_path)
        estimator, metadata = load_artifact(tmp_path)
        assert estimator is not None
        assert metadata["feature_names"] == CANONICAL_FEATURES

        # And the reloaded estimator still predicts.
        probabilities = estimator.predict_proba(
            build_feature_frame(dataset).to_numpy(dtype=float)
        )[:, 1]
        assert len(probabilities) == len(dataset)
        assert ((probabilities >= 0) & (probabilities <= 1)).all()

    def test_refused_result_cannot_be_exported(self, tiny_dataset, tmp_path):
        result = train(tiny_dataset)
        with pytest.raises(ArtifactError, match="Refusing to export"):
            export_artifact(result, tmp_path)
        assert not (tmp_path / MODEL_FILENAME).exists()

    def test_feature_mismatch_is_refused(self, dataset, tmp_path):
        """A model whose column order drifted must never reach production."""
        result = train(dataset)
        result.feature_names = list(reversed(CANONICAL_FEATURES))
        with pytest.raises(ArtifactError, match="scoring contract"):
            export_artifact(result, tmp_path)
        assert not (tmp_path / MODEL_FILENAME).exists()

    def test_tampered_model_is_detected(self, dataset, tmp_path):
        result = train(dataset)
        model_path, _ = export_artifact(result, tmp_path)
        model_path.write_bytes(b"not a pickle")
        with pytest.raises(ArtifactError, match="integrity"):
            read_artifact_metadata(tmp_path)

    def test_missing_metadata_is_reported(self, tmp_path):
        with pytest.raises(ArtifactError, match="No artifact metadata"):
            read_artifact_metadata(tmp_path)

    def test_corrupt_metadata_is_reported(self, tmp_path):
        (tmp_path / META_FILENAME).write_text("{ not json")
        with pytest.raises(ArtifactError, match="not valid JSON"):
            read_artifact_metadata(tmp_path)

    def test_metadata_without_model_file_is_reported(self, dataset, tmp_path):
        result = train(dataset)
        model_path, _ = export_artifact(result, tmp_path)
        model_path.unlink()
        with pytest.raises(ArtifactError, match="missing"):
            read_artifact_metadata(tmp_path)

    def test_publish_targets_the_backend_artifact_dir(self, dataset, tmp_path):
        result = train(dataset)
        path = export_to_backend(result, backend_root=tmp_path)
        assert path == tmp_path / "ml_artifacts" / MODEL_FILENAME
        assert path.exists()


class TestBackendCompatibility:
    def test_the_backend_can_load_what_this_module_exports(self, dataset, tmp_path):
        """The end-to-end contract, exercised for real.

        Train here, export, then hand the artifact to the backend's own loader
        and check it can read the metadata and score a row. This is the test
        that would catch a packaging or format mismatch between the two
        projects, which no unit test on either side would notice.
        """
        import sys

        backend_root = Path(__file__).resolve().parents[2] / "finance-ai-api"
        if not (backend_root / "main.py").exists():
            pytest.skip(f"backend not present at {backend_root}")
        if str(backend_root) not in sys.path:
            sys.path.insert(0, str(backend_root))

        from app.ml import trainer as backend_trainer

        result = train(dataset)
        export_artifact(result, tmp_path)

        # Point the backend at our artifact and let its own loader read it.
        backend_trainer.ARTIFACT_DIR = tmp_path
        estimator, feature_names, error = backend_trainer.load()

        assert error == ""
        assert estimator is not None
        assert feature_names == CANONICAL_FEATURES

        # And the backend can score a real transaction with what it loaded.
        row = dataset.iloc[0]

        class Tx:
            transaction_date = row["transaction_date"]
            amount = float(row["amount"])
            transaction_type = row["transaction_type"]
            category = row["category"]
            merchant = row["merchant"]
            emi_type = None
            source = row["source"]

        verdict = backend_trainer.score_transaction(Tx(), rule_score=20)
        assert verdict["status"] == "combined"
        assert 0 <= verdict["combined_score"] <= 100
        assert verdict["ml_score"] is not None

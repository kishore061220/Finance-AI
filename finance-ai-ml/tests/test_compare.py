"""Model comparison, selection and export of the winner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from finance_ai_ml.compare import (
    ComparisonError,
    available_candidates,
    compare_models,
    export_best,
)
from finance_ai_ml.config import TrainingConfig
from finance_ai_ml.export import META_FILENAME, MODEL_FILENAME, read_artifact_metadata
from finance_ai_ml.features import CANONICAL_FEATURES


class TestComparison:
    def test_compares_several_candidates(self, dataset):
        result = compare_models(dataset)
        assert result.status == "compared"
        names = {c.name for c in result.candidates}
        assert {"logistic_regression", "random_forest"} <= names
        assert result.best in names

    def test_every_scored_candidate_reports_pr_auc_and_confusion(self, dataset):
        result = compare_models(dataset)
        scored = [c for c in result.candidates if c.metrics]
        assert scored
        for candidate in scored:
            for metric in (
                "roc_auc",
                "average_precision",
                "precision",
                "recall",
                "f1",
                "true_positives",
                "false_positives",
                "false_negatives",
                "true_negatives",
            ):
                assert metric in candidate.metrics

    def test_selection_is_by_average_precision(self, dataset):
        result = compare_models(dataset)
        scored = [c for c in result.candidates if c.metrics]
        best_pr = max(c.metrics["average_precision"] for c in scored)
        assert result.best_candidate.metrics["average_precision"] == best_pr

    def test_linear_candidate_is_a_scaled_pipeline(self, dataset):
        """Preprocessing must travel with the estimator so predict_proba accepts
        the raw feature vector the backend sends."""
        result = compare_models(dataset)
        linear = next(c for c in result.candidates if c.name == "logistic_regression")
        steps = dict(linear.estimator.named_steps)
        assert "scaler" in steps and "model" in steps

    def test_too_little_data_is_refused(self, tiny_dataset):
        result = compare_models(tiny_dataset)
        assert result.status == "insufficient_data"
        assert result.candidates == []

    def test_chronological_split_reports_the_strategy(self, dataset):
        result = compare_models(dataset, split="chronological")
        assert result.split == "chronological"
        # Either it compared, or it honestly refused when one class fell on a
        # single side of the time boundary.
        assert result.status in {"compared", "failed"}

    def test_bad_split_name_is_rejected(self, dataset):
        with pytest.raises(ValueError):
            compare_models(dataset, split="random")


class TestExport:
    def test_export_writes_a_loadable_winner(self, dataset, tmp_path: Path):
        result = compare_models(dataset)
        model_path, meta_path = export_best(result, tmp_path)
        assert model_path == tmp_path / MODEL_FILENAME
        assert meta_path == tmp_path / META_FILENAME

        metadata = read_artifact_metadata(tmp_path)
        assert metadata["model"] == result.best
        assert metadata["feature_names"] == list(CANONICAL_FEATURES)
        # The comparison is recorded so the deployed choice is auditable.
        assert result.best in metadata["report"]["comparison"]

    def test_export_refuses_without_a_winner(self):
        from finance_ai_ml.compare import ComparisonResult

        empty = ComparisonResult(
            status="insufficient_data",
            train_rows=0,
            test_rows=0,
            positives=0,
            test_positives=0,
            candidates=[],
        )
        with pytest.raises(ComparisonError):
            export_best(empty, Path("unused"))


def test_available_candidates_are_labelled():
    candidates = available_candidates(TrainingConfig(), 0.1)
    names = [name for name, _ in candidates]
    assert "logistic_regression" in names
    assert "random_forest" in names
    assert any(name in {"xgboost", "sklearn-hist-gradient-boosting"} for name in names)

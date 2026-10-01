"""Dataset loading and validation."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from finance_ai_ml.dataset import (
    DatasetError,
    load_transactions,
    read_table,
    summarise,
)


def write_csv(tmp_path, rows, name="data.csv"):
    path = tmp_path / name
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


class TestLabelDetection:
    def test_is_flagged_is_detected(self, tmp_path, raw_dataset):
        path = write_csv(tmp_path, raw_dataset)
        frame = load_transactions(path)
        assert frame["label"].notna().all()

    def test_alternative_label_names_work(self, tmp_path, raw_dataset):
        renamed = raw_dataset.rename(columns={"is_flagged": "is_fraud"})
        path = write_csv(tmp_path, renamed)
        assert load_transactions(path)["label"].notna().all()

    def test_explicit_label_column_wins(self, tmp_path, raw_dataset):
        data = raw_dataset.rename(columns={"is_flagged": "confusing"})
        data["real_label"] = data["confusing"]
        path = write_csv(tmp_path, data)
        frame = load_transactions(path, "real_label")
        assert frame["label"].notna().all()

    def test_missing_label_is_an_error(self, tmp_path, raw_dataset):
        """Training on unlabelled data silently would produce a useless model."""
        path = write_csv(tmp_path, raw_dataset.drop(columns=["is_flagged"]))
        with pytest.raises(DatasetError, match="no label column"):
            load_transactions(path)

    def test_requested_missing_label_column_is_an_error(self, tmp_path, raw_dataset):
        path = write_csv(tmp_path, raw_dataset)
        with pytest.raises(DatasetError, match="not in"):
            load_transactions(path, "does_not_exist")

    def test_label_column_may_be_disabled(self, tmp_path, raw_dataset):
        path = write_csv(tmp_path, raw_dataset.drop(columns=["is_flagged"]))
        frame = load_transactions(path, require_label=False)
        assert frame["label"].isna().all()
        assert len(frame) == len(raw_dataset)


class TestLabelParsing:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            (1, 1), (0, 0), (True, 1), (False, 0),
            ("true", 1), ("FALSE", 0), ("Yes", 1), ("no", 0),
            ("fraud", 1), ("clean", 0), ("1", 1), ("0", 0),
        ],
    )
    def test_truthy_values(self, tmp_path, raw_dataset, raw, expected):
        data = raw_dataset.copy()
        data["is_flagged"] = raw
        frame = load_transactions(write_csv(tmp_path, data))
        assert set(frame["label"].unique()) == {expected}

    def test_unreadable_labels_are_dropped_and_counted(self, tmp_path, raw_dataset):
        data = raw_dataset.copy()
        # Widen first: pandas 3 refuses to store a string in an int64 column,
        # and we want the *loader* to be the thing under test here.
        data["is_flagged"] = data["is_flagged"].astype(object)
        data.loc[0:4, "is_flagged"] = "maybe"
        frame = load_transactions(write_csv(tmp_path, data))
        assert frame.attrs["dropped"]["label"] == 5
        assert len(frame) == len(raw_dataset) - 5


class TestAmountValidation:
    def test_non_numeric_amounts_are_dropped(self, tmp_path, raw_dataset):
        data = raw_dataset.copy()
        # Widen first: pandas 3 refuses to store a string in a float64 column,
        # and we want the *loader* to be the thing under test here.
        data["amount"] = data["amount"].astype(object)
        data.loc[0:2, "amount"] = "not-a-number"
        frame = load_transactions(write_csv(tmp_path, data))
        assert frame.attrs["dropped"]["amount"] == 3

    def test_non_positive_amounts_are_dropped(self, tmp_path, raw_dataset):
        """A zero or negative expense is a data error, not a training example."""
        data = raw_dataset.copy()
        data.loc[0, "amount"] = 0
        data.loc[1, "amount"] = -50
        frame = load_transactions(write_csv(tmp_path, data))
        assert frame.attrs["dropped"]["amount"] == 2
        assert (frame["amount"] > 0).all()

    def test_amount_is_float(self, tmp_path, raw_dataset):
        frame = load_transactions(write_csv(tmp_path, raw_dataset))
        assert frame["amount"].dtype.kind == "f"


class TestDateValidation:
    def test_unparseable_dates_are_dropped(self, tmp_path, raw_dataset):
        data = raw_dataset.copy()
        data.loc[0:1, "transaction_date"] = "not-a-date"
        frame = load_transactions(write_csv(tmp_path, data))
        assert frame.attrs["dropped"]["date"] == 2
        assert isinstance(frame["transaction_date"].iloc[0], pd.Timestamp)

    def test_missing_required_columns_are_reported(self, tmp_path, raw_dataset):
        path = write_csv(tmp_path, raw_dataset.drop(columns=["amount"]))
        with pytest.raises(DatasetError, match="missing required column"):
            load_transactions(path)


class TestFileHandling:
    def test_missing_file_is_reported_clearly(self, tmp_path):
        with pytest.raises(DatasetError, match="No such dataset file"):
            read_table(tmp_path / "nope.csv")

    def test_parquet_is_supported(self, tmp_path, raw_dataset):
        path = tmp_path / "data.parquet"
        raw_dataset.to_parquet(path, index=False)
        frame = load_transactions(path)
        assert len(frame) == len(raw_dataset)

    def test_column_names_are_case_insensitive(self, tmp_path, raw_dataset):
        renamed = raw_dataset.rename(
            columns={"is_flagged": "IS_FLAGGED", "amount": "Amount"}
        )
        path = write_csv(tmp_path, renamed)
        assert load_transactions(path)["label"].notna().all()

    def test_dataframe_can_be_passed_directly(self, raw_dataset):
        frame = load_transactions(raw_dataset)
        assert len(frame) == len(raw_dataset)


class TestNormalisation:
    def test_transaction_type_defaults_to_expense(self, tmp_path, raw_dataset):
        data = raw_dataset.copy()
        data["transaction_type"] = "weird-value"
        frame = load_transactions(write_csv(tmp_path, data))
        assert set(frame["transaction_type"]) == {"expense"}

    def test_source_defaults_to_manual(self, tmp_path, raw_dataset):
        data = raw_dataset.copy()
        data["source"] = None
        frame = load_transactions(write_csv(tmp_path, data))
        assert set(frame["source"]) == {"MANUAL"}

    def test_missing_user_id_becomes_zero(self, tmp_path, raw_dataset):
        data = raw_dataset.drop(columns=["user_id"])
        frame = load_transactions(write_csv(tmp_path, data))
        assert set(frame["user_id"]) == {0}


class TestSummary:
    def test_summary_counts_labels(self, raw_dataset):
        frame = load_transactions(raw_dataset)
        info = summarise(frame)
        assert info["rows"] == len(frame)
        assert info["positives"] == int(raw_dataset["is_flagged"].sum())
        assert info["labelled"] == len(frame)
        assert info["unlabelled"] == 0

    def test_summary_of_empty_frame(self):
        frame = load_transactions(pd.DataFrame(
            {"user_id": [], "transaction_date": [], "amount": [],
             "transaction_type": [], "category": [], "merchant": [],
             "emi_type": [], "source": [], "is_flagged": []}
        ))
        info = summarise(frame)
        assert info["rows"] == 0
        assert info["date_range"] is None

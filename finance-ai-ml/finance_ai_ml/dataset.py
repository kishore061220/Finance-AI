"""Load and validate training data.

The input is a CSV (or Parquet) of transactions with an ``is_flagged`` label.
Loading is strict on purpose: a silently mis-parsed amount column or a label
column full of blanks produces a model that trains happily on nonsense. Every
rejection says which rows are at fault and why.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

import pandas as pd

logger = logging.getLogger(__name__)

# Column names accepted as the supervised label, in order of preference. These
# mirror the backend's transaction fields.
LABEL_COLUMNS = ("is_flagged", "label", "is_fraud", "fraud")

# Columns the feature builder can consume. Anything else in the CSV is ignored.
KNOWN_COLUMNS = {
    "user_id",
    "transaction_date",
    "amount",
    "transaction_type",
    "category",
    "merchant",
    "emi_type",
    "source",
    "bank_reference",
    "description",
}


class DatasetError(ValueError):
    """The dataset cannot be used for training, and the reason is known."""


def _truthy(value) -> Optional[bool]:
    """Interpret a label cell. Blank/unknown values return ``None``."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value == 1:
            return True
        if value == 0:
            return False
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "t", "yes", "y", "fraud", "flagged"}:
        return True
    if text in {"0", "false", "f", "no", "n", "clean"}:
        return False
    return None


def _normalise_type(value) -> str:
    text = str(value or "").strip().lower()
    return text if text in {"income", "expense", "transfer"} else "expense"


def _normalise_source(value) -> str:
    text = str(value or "").strip().upper()
    return text if text in {"SMS", "OCR", "MANUAL", "IMPORT"} else "MANUAL"


def read_table(
    path: Path,
    label_column: Optional[str] = None,
    *,
    require_label: bool = True,
) -> pd.DataFrame:
    """Read a CSV or Parquet file into a raw DataFrame.

    Raises :class:`DatasetError` with an actionable message rather than letting
    a pandas parsing error surface as a stack trace.
    """
    path = Path(path)
    if not path.exists():
        raise DatasetError(f"No such dataset file: {path}")

    try:
        if path.suffix.lower() in {".parquet", ".pq"}:
            frame = pd.read_parquet(path)
        else:
            frame = pd.read_csv(path)
    except Exception as exc:  # noqa: BLE001
        raise DatasetError(f"Could not read {path.name}: {exc}") from exc

    frame.columns = [str(c).strip().lower() for c in frame.columns]

    if label_column:
        if label_column.lower() not in frame.columns:
            raise DatasetError(
                f"Requested label column {label_column!r} is not in {path.name}. "
                f"Available columns: {sorted(frame.columns)}"
            )
    elif require_label and not any(c in frame.columns for c in LABEL_COLUMNS):
        raise DatasetError(
            f"{path.name} has no label column. Expected one of "
            f"{list(LABEL_COLUMNS)}. A supervised classifier cannot be trained "
            "on unlabelled data."
        )
    return frame


def load_transactions(
    source: "Path | str | pd.DataFrame",
    label_column: Optional[str] = None,
    *,
    require_label: bool = True,
) -> pd.DataFrame:
    """Return a clean, typed DataFrame ready for feature engineering.

    Columns produced: ``user_id``, ``transaction_date`` (datetime),
    ``amount`` (float), ``transaction_type``, ``category``, ``merchant``,
    ``emi_type``, ``source``, and ``label`` (nullable int).

    Rows with an unusable amount, an unparseable date, or (when a label is
    required) an unreadable label are dropped and counted, and the counts are
    returned on ``frame.attrs['dropped']`` so the caller can report them.
    """
    if isinstance(source, pd.DataFrame):
        frame = source.copy()
        frame.columns = [str(c).strip().lower() for c in frame.columns]
    else:
        frame = read_table(Path(source), label_column, require_label=require_label)

    if label_column:
        resolved_label = label_column.lower()
    else:
        resolved_label = next(
            (c for c in LABEL_COLUMNS if c in frame.columns), None
        )

    required = ["transaction_date", "amount"]
    missing = [c for c in required if c not in frame.columns]
    if missing:
        raise DatasetError(
            f"Dataset is missing required column(s): {missing}. "
            f"Available columns: {sorted(frame.columns)}"
        )

    dropped = {"amount": 0, "date": 0, "label": 0}

    # Amount: anything that is not a finite positive number cannot be modelled.
    amount = pd.to_numeric(frame["amount"], errors="coerce")
    bad_amount = amount.isna() | (amount <= 0) | amount.isin([float("inf"), float("-inf")])
    dropped["amount"] = int(bad_amount.sum())
    frame = frame[~bad_amount].copy()
    amount = amount[~bad_amount]

    # Date: features are time-based, so an unparseable row is unusable.
    dates = pd.to_datetime(frame["transaction_date"], errors="coerce", utc=False)
    bad_date = dates.isna()
    dropped["date"] = int(bad_date.sum())
    frame = frame[~bad_date].copy()
    dates = dates[~bad_date]

    if resolved_label:
        labels = frame[resolved_label].map(_truthy)
        if require_label:
            bad_label = labels.isna()
            dropped["label"] = int(bad_label.sum())
            frame = frame[~bad_label].copy()
            labels = labels[~bad_label]
        frame["label"] = labels.astype("object").where(labels.notna(), None).map(
            lambda v: None if v is None else int(v)
        )
    else:
        frame["label"] = None

    frame["amount"] = amount[~bad_date].astype(float)
    frame["transaction_date"] = dates
    frame["user_id"] = (
        pd.to_numeric(frame.get("user_id"), errors="coerce").fillna(0).astype(int)
        if "user_id" in frame.columns
        else 0
    )
    for column, default in (
        ("transaction_type", "expense"),
        ("category", "Uncategorized"),
        ("merchant", None),
        ("emi_type", None),
        ("source", "MANUAL"),
    ):
        if column not in frame.columns:
            frame[column] = default

    frame["transaction_type"] = frame["transaction_type"].map(_normalise_type)
    frame["source"] = frame["source"].map(_normalise_source)
    frame["category"] = frame["category"].fillna("Uncategorized").astype(str)
    frame["merchant"] = frame["merchant"].astype("object").where(
        frame["merchant"].notna(), None
    )

    frame = frame[
        ["user_id", "transaction_date", "amount", "transaction_type", "category",
         "merchant", "emi_type", "source", "label"]
    ].reset_index(drop=True)

    frame.attrs["dropped"] = dropped
    return frame


def summarise(frame: pd.DataFrame) -> dict:
    """A short, honest description of what was loaded."""
    labels = frame["label"]
    labelled = labels.notna().sum()
    return {
        "rows": int(len(frame)),
        "labelled": int(labelled),
        "unlabelled": int(len(frame) - labelled),
        "positives": int(labels.fillna(0).sum()),
        "negatives": int(labelled - labels.fillna(0).sum()),
        "users": int(frame["user_id"].nunique()),
        "amount_sum": float(frame["amount"].sum()),
        "date_range": (
            [frame["transaction_date"].min(), frame["transaction_date"].max()]
            if len(frame)
            else None
        ),
        "dropped": dict(frame.attrs.get("dropped", {})),
    }


__all__ = [
    "DatasetError",
    "KNOWN_COLUMNS",
    "LABEL_COLUMNS",
    "load_transactions",
    "read_table",
    "summarise",
]

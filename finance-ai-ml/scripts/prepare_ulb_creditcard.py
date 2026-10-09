"""Acquire the ULB credit-card fraud dataset and map it to the training schema.

Source
------
``creditcard`` (OpenML data id 1597), the anonymised European cardholder
dataset released by the Machine Learning Group of Université Libre de
Bruxelles (ULB) and Worldline. OpenML reports the dataset licence as
``Public``; the canonical Kaggle release is distributed under the Open
Database License (ODbL) with contents under the Database Contents License
(DbCL). See ``finance-ai-ml/DATASET.md`` for the full provenance and the
limitations of the mapping performed here.

What this script does
---------------------
1. Downloads the ARFF (gzip-encoded on the wire) if it is not already present.
2. Reads the ``@data`` block and maps three real columns onto the schema the
   training pipeline expects:

   ================  =========================================================
   ULB column        Finance-AI column
   ================  =========================================================
   ``Time``          ``transaction_date`` (2013-09-01 UTC + Time seconds)
   ``Amount``        ``amount``
   ``Class``         ``is_flagged`` (1 = confirmed fraud)
   ================  =========================================================

   Every other training column is filled with its documented default. The
   PCA components ``V1..V28`` are deliberately dropped: the production
   scoring contract (``app.ml.features``) cannot supply them, so a model that
   depended on them could not score a live transaction.

The output is a CSV with exactly the columns ``finance_ai_ml.dataset`` reads.
Nothing is downloaded into the repository; pass an external path.
"""

from __future__ import annotations

import argparse
import gzip
import io
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

# OpenML file id for the creditcard ARFF. The URL redirects and the payload is
# served with gzip content-encoding.
ARFF_URL = "https://openml.org/data/v1/download/1673544/creditcard.arff"

# The dataset spans two days starting 2013-09-01. ``Time`` is the number of
# seconds elapsed since the first transaction.
BASE_TIME = datetime(2013, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

ATTRIBUTES = ["Time"] + [f"V{i}" for i in range(1, 29)] + ["Amount", "Class"]

OUTPUT_COLUMNS = [
    "user_id",
    "transaction_date",
    "amount",
    "transaction_type",
    "category",
    "merchant",
    "emi_type",
    "source",
    "is_flagged",
]


def download(url: str, destination: Path) -> Path:
    """Download ``url`` to ``destination``, transparently decoding gzip."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {url} ...")
    request = urllib.request.Request(
        url,
        headers={
            "Accept-Encoding": "gzip",
            "User-Agent": "finance-ai-ml/prepare-ulb-creditcard",
        },
    )
    with urllib.request.urlopen(request, timeout=600) as response:
        raw = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    destination.write_bytes(raw)
    print(f"Wrote {destination} ({len(raw) / 1_048_576:.1f} MiB decompressed)")
    return destination


def _data_offset(path: Path) -> int:
    """Return the line index of the ``@data`` marker."""
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for index, line in enumerate(handle):
            if line.strip().lower().startswith("@data"):
                return index
    raise ValueError(f"{path} has no @data marker; is it really an ARFF file?")


def convert(arff_path: Path, csv_path: Path) -> pd.DataFrame:
    """Parse the ARFF data block and write the mapped CSV."""
    header = _data_offset(arff_path)
    frame = pd.read_csv(
        arff_path,
        skiprows=header + 1,
        header=None,
        names=ATTRIBUTES,
        quotechar="'",
        engine="c",
    )
    frame["amount"] = pd.to_numeric(frame["Amount"], errors="coerce")
    frame["is_flagged"] = pd.to_numeric(frame["Class"], errors="coerce").fillna(0).astype(int)
    frame["Time"] = pd.to_numeric(frame["Time"], errors="coerce")

    invalid = frame["amount"].isna() | (frame["amount"] <= 0) | frame["Time"].isna()
    dropped = int(invalid.sum())
    frame = frame[~invalid].copy()

    frame["transaction_date"] = frame["Time"].map(
        lambda seconds: (BASE_TIME + timedelta(seconds=float(seconds))).replace(
            tzinfo=None
        ).isoformat(sep=" ")
    )
    frame["user_id"] = 0
    frame["transaction_type"] = "expense"
    frame["category"] = "Uncategorized"
    frame["merchant"] = ""
    frame["emi_type"] = ""
    frame["source"] = "MANUAL"

    output = frame[OUTPUT_COLUMNS].reset_index(drop=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(csv_path, index=False)

    positives = int(output["is_flagged"].sum())
    print(f"Rows: {len(output)}  positives: {positives}  dropped: {dropped}")
    print(f"Fraud rate: {positives / len(output):.4%}")
    print(f"Wrote {csv_path}")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--arff",
        default=None,
        help="Existing ARFF file. Downloaded to --work-dir if omitted.",
    )
    parser.add_argument(
        "--work-dir",
        default=None,
        help="Directory for the downloaded ARFF and the output CSV.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output CSV path (default: <work-dir>/ulb_creditcard.csv).",
    )
    args = parser.parse_args(argv)

    if not args.arff and not args.work_dir:
        parser.error("provide --arff or --work-dir")

    work_dir = Path(args.work_dir) if args.work_dir else Path(args.arff).parent
    work_dir.mkdir(parents=True, exist_ok=True)

    arff_path = Path(args.arff) if args.arff else work_dir / "creditcard.arff"
    if not arff_path.exists():
        download(ARFF_URL, arff_path)

    csv_path = Path(args.output) if args.output else work_dir / "ulb_creditcard.csv"
    convert(arff_path, csv_path)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

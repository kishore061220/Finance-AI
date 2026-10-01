"""Command-line entry point.

    python -m finance_ai_ml inspect  data.csv
    python -m finance_ai_ml train    data.csv --output ./ml_artifacts
    python -m finance_ai_ml publish  data.csv --backend C:/Projects/Finance-AI/finance-ai-api

Exit codes are meaningful: 0 success, 1 a refusal (``insufficient_data``),
2 bad input. That lets a scheduled job distinguish "no model today" from
"the data was malformed".
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from finance_ai_ml.config import TrainingConfig
from finance_ai_ml.dataset import DatasetError, load_transactions, summarise
from finance_ai_ml.export import (
    ArtifactError,
    export_artifact,
    export_to_backend,
    read_artifact_metadata,
)
from finance_ai_ml.train import train

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_BAD_INPUT = 2


def _config(args: argparse.Namespace) -> TrainingConfig:
    config = TrainingConfig()
    overrides = {}
    if getattr(args, "test_size", None) is not None:
        overrides["test_size"] = args.test_size
    if getattr(args, "min_rows", None) is not None:
        overrides["min_rows"] = args.min_rows
    if getattr(args, "min_positives", None) is not None:
        overrides["min_positives"] = args.min_positives
    return TrainingConfig(**{**config.__dict__, **overrides})


def cmd_inspect(args: argparse.Namespace) -> int:
    frame = load_transactions(args.dataset, args.label_column, require_label=False)
    print(json.dumps(summarise(frame), indent=2, default=str))
    return EXIT_OK


def cmd_train(args: argparse.Namespace) -> int:
    try:
        frame = load_transactions(args.dataset, args.label_column)
    except DatasetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT

    print("Dataset:")
    print(json.dumps(summarise(frame), indent=2, default=str))

    result = train(frame, _config(args))
    payload = result.as_dict()

    if result.status != "trained":
        print("\n" + payload["message"], file=sys.stderr)
        print(json.dumps(payload, indent=2), file=sys.stderr)
        return EXIT_REFUSED

    print(f"\nTrained {result.model} on {result.rows_used} rows.")
    print("Held-out metrics:")
    for name, value in result.metrics.items():
        print(f"  {name:20s} {value}")
    for note in result.caveats:
        print(f"\n  ! {note}")

    output = Path(args.output)
    model_path, meta_path = export_artifact(result, output)
    print(f"\nWrote {model_path}")
    print(f"Wrote {meta_path}")
    return EXIT_OK


def cmd_publish(args: argparse.Namespace) -> int:
    try:
        frame = load_transactions(args.dataset, args.label_column)
    except DatasetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT

    result = train(frame, _config(args))
    if result.status != "trained":
        print(result.message, file=sys.stderr)
        return EXIT_REFUSED

    try:
        path = export_to_backend(result, Path(args.backend) if args.backend else None)
    except ArtifactError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT

    print(f"Published {path}")
    print("The API will use this model on its next scoring call. Restart the "
          "server if it caches the artifact at startup.")
    return EXIT_OK


def cmd_verify(args: argparse.Namespace) -> int:
    try:
        metadata = read_artifact_metadata(Path(args.directory))
    except ArtifactError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT
    print(json.dumps(metadata, indent=2, default=str))
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="finance_ai_ml",
        description="Offline training for the Finance-AI fraud model.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("dataset", help="CSV or Parquet file of labelled transactions")
        sub.add_argument(
            "--label-column",
            default=None,
            help="Label column name (default: auto-detect is_flagged/label/is_fraud)",
        )
        sub.add_argument("--test-size", type=float, default=None, dest="test_size")
        sub.add_argument("--min-rows", type=int, default=None, dest="min_rows")
        sub.add_argument(
            "--min-positives", type=int, default=None, dest="min_positives"
        )

    inspect_parser = subparsers.add_parser(
        "inspect", help="Describe a dataset without training"
    )
    add_common(inspect_parser)
    inspect_parser.set_defaults(func=cmd_inspect)

    train_parser = subparsers.add_parser("train", help="Train and write an artifact")
    add_common(train_parser)
    train_parser.add_argument(
        "--output", default="./ml_artifacts", help="Directory for the artifact"
    )
    train_parser.set_defaults(func=cmd_train)

    publish_parser = subparsers.add_parser(
        "publish", help="Train and write straight into the backend's artifact dir"
    )
    add_common(publish_parser)
    publish_parser.add_argument(
        "--backend", default=None, help="Path to the finance-ai-api directory"
    )
    publish_parser.set_defaults(func=cmd_publish)

    verify_parser = subparsers.add_parser(
        "verify", help="Validate an existing artifact's integrity"
    )
    verify_parser.add_argument("directory")
    verify_parser.set_defaults(func=cmd_verify)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except DatasetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT
    except ArtifactError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

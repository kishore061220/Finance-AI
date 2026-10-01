"""Artifact export and integrity verification.

The backend loads an artifact as a pair of files:

``fraud_model.pkl``
    The pickled estimator.
``fraud_model.json``
    Metadata: model name, the exact feature order the estimator expects, and the
    training report.

:func:`export_artifact` writes exactly that layout, and :func:`export_to_backend`
points it at ``finance-ai-api/ml_artifacts/`` so the API picks the model up on
its next scoring call.

The metadata's ``feature_names`` is not documentation - it is the contract the
backend reads to decide which key of its feature dict maps to which column.
Export therefore refuses to write a model whose feature order does not match
:data:`CANONICAL_FEATURES`, which stops a mismatched model reaching production.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from finance_ai_ml.features import CANONICAL_FEATURES

logger = logging.getLogger(__name__)

MODEL_FILENAME = "fraud_model.pkl"
META_FILENAME = "fraud_model.json"

# Bumped whenever the feature contract or artifact layout changes. The backend
# can then refuse a model built against a different contract.
ARTIFACT_FORMAT_VERSION = 1


class ArtifactError(RuntimeError):
    """The artifact cannot be written or trusted."""


def checksum(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def export_artifact(result, directory: Path) -> Tuple[Path, Path]:
    """Write ``result``'s estimator and metadata into ``directory``.

    Returns ``(model_path, meta_path)``.
    """
    if getattr(result, "status", None) != "trained":
        raise ArtifactError(
            f"Refusing to export a result with status {getattr(result, 'status', None)!r}. "
            "Only a trained result carries an estimator."
        )
    estimator = getattr(result, "estimator", None)
    if estimator is None:
        raise ArtifactError(
            "Result claims to be trained but carries no estimator. Nothing was "
            "written."
        )

    feature_names = list(getattr(result, "feature_names", []) or [])
    if feature_names != list(CANONICAL_FEATURES):
        raise ArtifactError(
            "The estimator's feature order does not match the scoring contract "
            "the backend uses. Refusing to write an artifact that would be "
            "scored against the wrong columns. "
            f"Expected {list(CANONICAL_FEATURES)}, got {feature_names}."
        )

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    model_path = directory / MODEL_FILENAME
    meta_path = directory / META_FILENAME

    import pickle

    with model_path.open("wb") as handle:
        pickle.dump(estimator, handle, protocol=pickle.HIGHEST_PROTOCOL)

    metadata = {
        "artifact_format_version": ARTIFACT_FORMAT_VERSION,
        "model": result.model,
        "feature_names": feature_names,
        "report": result.as_dict(),
        "checksum": checksum(model_path.read_bytes()),
    }
    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return model_path, meta_path


def export_to_backend(result, backend_root: Optional[Path] = None) -> Path:
    """Write the artifact where the backend's trainer looks for it.

    The backend reads ``finance-ai-api/ml_artifacts/fraud_model.pkl``.
    """
    root = Path(backend_root) if backend_root else _default_backend_root()
    model_path, _ = export_artifact(result, root / "ml_artifacts")
    logger.info("Exported fraud model to %s", model_path)
    return model_path


def _default_backend_root() -> Path:
    """Locate ``finance-ai-api`` relative to this package.

    Resolved from the filesystem rather than hard-coded so the module works from
    a checkout without configuration.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "finance-ai-api"
        if (candidate / "main.py").exists():
            return candidate
    raise ArtifactError(
        "Could not locate the finance-ai-api directory. Pass backend_root "
        "explicitly if the project layout differs."
    )


def read_artifact_metadata(directory: Path) -> Dict:
    """Read and validate an artifact's metadata.

    Raises :class:`ArtifactError` if the metadata is missing, unreadable, from a
    newer format, or its recorded checksum no longer matches the model file.
    """
    directory = Path(directory)
    meta_path = directory / META_FILENAME
    model_path = directory / MODEL_FILENAME

    if not meta_path.exists():
        raise ArtifactError(f"No artifact metadata at {meta_path}.")
    try:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ArtifactError(f"{meta_path} is not valid JSON: {exc}") from exc

    version = metadata.get("artifact_format_version")
    if version != ARTIFACT_FORMAT_VERSION:
        raise ArtifactError(
            f"Artifact format version {version!r} is not supported by this "
            f"module (expected {ARTIFACT_FORMAT_VERSION})."
        )

    if metadata.get("feature_names") != list(CANONICAL_FEATURES):
        raise ArtifactError(
            "Artifact feature order does not match the current contract. The "
            "model would be scored against the wrong columns; retrain it."
        )

    expected = metadata.get("checksum")
    if expected and model_path.exists():
        actual = checksum(model_path.read_bytes())
        if actual != expected:
            raise ArtifactError(
                "Artifact integrity check failed: fraud_model.pkl has changed "
                "since it was exported. Delete and re-export."
            )
    elif expected and not model_path.exists():
        raise ArtifactError(
            f"Metadata references a model file that is missing: {model_path}."
        )

    return metadata


def load_artifact(directory: Path):
    """Load ``(estimator, metadata)`` after validating the artifact."""
    import pickle

    metadata = read_artifact_metadata(directory)
    model_path = Path(directory) / MODEL_FILENAME
    with model_path.open("rb") as handle:
        estimator = pickle.load(handle)
    return estimator, metadata


def list_artifacts(directory: Path) -> List[Path]:
    directory = Path(directory)
    if not directory.exists():
        return []
    return sorted(directory.glob("fraud_model.*"))


__all__ = [
    "ARTIFACT_FORMAT_VERSION",
    "ArtifactError",
    "META_FILENAME",
    "MODEL_FILENAME",
    "checksum",
    "export_artifact",
    "export_to_backend",
    "list_artifacts",
    "load_artifact",
    "read_artifact_metadata",
]

"""Strict validation for portable, checksummed ONNX model bundles."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


SUPPORTED_SCHEMA = 1
_MANIFEST_FIELDS = frozenset({
    "model_id",
    "architecture",
    "classes",
    "preprocessing_version",
    "confidence_floor",
    "artifact_sha256",
    "schema_version",
    "metrics",
})


class ModelBundleError(ValueError):
    """A model bundle is missing, malformed, incompatible, or untrusted."""


@dataclass(frozen=True)
class ModelManifest:
    model_id: str
    architecture: str
    classes: tuple[str, ...]
    preprocessing_version: str
    confidence_floor: float
    artifact_sha256: str
    schema_version: int
    metrics: Mapping[str, Any]

    @classmethod
    def from_mapping(cls, raw: object) -> "ModelManifest":
        if not isinstance(raw, dict):
            raise ModelBundleError("model manifest must be a JSON object")

        fields = set(raw)
        missing = _MANIFEST_FIELDS - fields
        if missing:
            raise ModelBundleError(f"model manifest is missing required fields: {sorted(missing)}")
        unknown = fields - _MANIFEST_FIELDS
        if unknown:
            raise ModelBundleError(f"model manifest has unknown fields: {sorted(unknown)}")

        string_fields = ("model_id", "architecture", "preprocessing_version", "artifact_sha256")
        for name in string_fields:
            if not isinstance(raw[name], str) or not raw[name]:
                raise ModelBundleError(f"model manifest field {name!r} must be a non-empty string")

        classes = raw["classes"]
        if not isinstance(classes, list) or not classes:
            raise ModelBundleError("model manifest classes must be a non-empty list")
        if any(not isinstance(class_name, str) or not class_name for class_name in classes):
            raise ModelBundleError("model manifest classes must contain non-empty strings")
        if len(set(classes)) != len(classes):
            raise ModelBundleError("model manifest classes must not contain duplicates")

        confidence_floor = raw["confidence_floor"]
        if (
            isinstance(confidence_floor, bool)
            or not isinstance(confidence_floor, (int, float))
            or not isfinite(confidence_floor)
            or not 0 <= confidence_floor <= 1
        ):
            raise ModelBundleError("model manifest confidence_floor must be within [0, 1]")

        artifact_sha256 = raw["artifact_sha256"]
        if len(artifact_sha256) != 64 or any(char not in "0123456789abcdef" for char in artifact_sha256):
            raise ModelBundleError("model manifest artifact_sha256 must be a lowercase SHA-256 hex digest")

        schema_version = raw["schema_version"]
        if isinstance(schema_version, bool) or not isinstance(schema_version, int):
            raise ModelBundleError("model manifest field 'schema_version' must be an integer")

        metrics = raw["metrics"]
        if not isinstance(metrics, dict):
            raise ModelBundleError("model manifest metrics must be an object")

        return cls(
            model_id=raw["model_id"],
            architecture=raw["architecture"],
            classes=tuple(classes),
            preprocessing_version=raw["preprocessing_version"],
            confidence_floor=float(confidence_floor),
            artifact_sha256=artifact_sha256,
            schema_version=schema_version,
            metrics=MappingProxyType(dict(metrics)),
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_model_bundle(bundle_dir: Path) -> tuple[ModelManifest, Path]:
    """Load a fixed-name ONNX artifact only after manifest and hash validation."""
    bundle_dir = Path(bundle_dir)
    manifest_path = bundle_dir / "manifest.json"
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ModelBundleError("model manifest is missing") from error
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ModelBundleError("model manifest is malformed") from error

    manifest = ModelManifest.from_mapping(raw)
    if manifest.schema_version != SUPPORTED_SCHEMA:
        raise ModelBundleError("unsupported model manifest schema")

    try:
        resolved_bundle = bundle_dir.resolve(strict=True)
        artifact = bundle_dir / "model.onnx"
        resolved_artifact = artifact.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ModelBundleError("model artifact is missing") from error

    if resolved_artifact.parent != resolved_bundle:
        raise ModelBundleError("model artifact escapes bundle")
    if not resolved_artifact.is_file():
        raise ModelBundleError("model artifact is missing")
    if sha256_file(resolved_artifact) != manifest.artifact_sha256:
        raise ModelBundleError("model artifact checksum mismatch")
    return manifest, resolved_artifact

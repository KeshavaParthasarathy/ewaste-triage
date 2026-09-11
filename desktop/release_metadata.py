"""Validated, immutable release identity for the packaged desktop product."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re


_BUILD_FIELDS = frozenset({
    "schema_version", "app_version", "source_revision", "release_manifest_sha256"
})
_RELEASE_FIELDS = frozenset({
    "schema_version", "app_version", "model", "components", "target", "created_at", "parity"
})
_MODEL_FIELDS = frozenset({
    "model_id", "artifact_sha256", "manifest_sha256", "labels_sha256", "schema_version"
})
_COMPONENT_FIELDS = frozenset({"sha256", "content_sha256", "schema_version", "version"})
_LEGACY_TARGET_FIELDS = frozenset({"architecture", "minimum_macos"})
_TARGET_FIELDS = frozenset({"platform", "architecture", "minimum_version"})
_SUPPORTED_TARGETS = frozenset({
    ("macos", "arm64", "14.0"),
    ("windows", "x86_64", "11"),
})
_PARITY_FIELDS = frozenset({"schema_version", "status", "model_id", "model_sha256", "labels", "metrics", "holdout"})
_PARITY_METRICS_FIELDS = frozenset({"reference_images", "top1_matches", "max_probability_delta"})
_PARITY_HOLDOUT_FIELDS = frozenset({"status", "split", "valid", "overlaps_training", "samples"})
_CANONICAL_LABELS = (
    "0301_computer_mouse", "0301_keyboard", "0303_laptop", "0306_mobile_phone", "0401_headphones"
)
_SHA256 = re.compile(r"[0-9a-f]{64}")
_REVISION = re.compile(r"[0-9a-f]{40}")


class ReleaseMetadataError(ValueError):
    """The immutable packaged release identity is unavailable or incompatible."""


@dataclass(frozen=True)
class RuntimeModelIntegrity:
    """Internal release anchors required to bind a frozen classifier safely."""

    model_id: str
    model_schema_version: int
    model_artifact_sha256: str
    model_manifest_sha256: str
    model_labels_sha256: str
    labels: tuple[str, ...]


@dataclass(frozen=True)
class ReleaseMetadata:
    """The sole public, display-safe release identity contract."""

    app_version: str
    source_revision: str
    model_sha256: str
    component_database_sha256: str
    component_database_version: str

    def public_payload(self) -> dict[str, str]:
        return {
            "app_version": self.app_version,
            "source_revision": self.source_revision,
            "model_sha256": self.model_sha256,
            "component_database_sha256": self.component_database_sha256,
            "component_database_version": self.component_database_version,
        }


def _read_json(path: Path) -> object:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise ReleaseMetadataError("unavailable or incompatible") from exc


def _object(value: object, fields: frozenset[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ReleaseMetadataError("unavailable or incompatible")
    return value


def _string(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ReleaseMetadataError("unavailable or incompatible")
    return value


def _hash(value: object) -> str:
    value = _string(value)
    if _SHA256.fullmatch(value) is None:
        raise ReleaseMetadataError("unavailable or incompatible")
    return value


def _integer(value: object, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ReleaseMetadataError("unavailable or incompatible")
    return value


def _validate_target(value: object) -> None:
    if not isinstance(value, dict):
        raise ReleaseMetadataError("unavailable or incompatible")
    if set(value) == _LEGACY_TARGET_FIELDS:
        if value == {"architecture": "arm64", "minimum_macos": "14.0"}:
            return
        raise ReleaseMetadataError("unavailable or incompatible")
    target = _object(value, _TARGET_FIELDS)
    fields = (
        _string(target["platform"]),
        _string(target["architecture"]),
        _string(target["minimum_version"]),
    )
    if fields not in _SUPPORTED_TARGETS:
        raise ReleaseMetadataError("unavailable or incompatible")


def _validate_release_manifest(manifest: object) -> tuple[dict[str, object], dict[str, object]]:
    release = _object(manifest, _RELEASE_FIELDS)
    if type(release["schema_version"]) is not int or release["schema_version"] != 1:
        raise ReleaseMetadataError("unavailable or incompatible")
    _string(release["app_version"])

    model = _object(release["model"], _MODEL_FIELDS)
    _string(model["model_id"])
    for field in ("artifact_sha256", "manifest_sha256", "labels_sha256"):
        _hash(model[field])
    if type(model["schema_version"]) is not int or model["schema_version"] != 1:
        raise ReleaseMetadataError("unavailable or incompatible")

    components = _object(release["components"], _COMPONENT_FIELDS)
    _hash(components["sha256"])
    _hash(components["content_sha256"])
    if (
        type(components["schema_version"]) is not int
        or components["schema_version"] != 2
        or components["version"] != "2.0.0"
    ):
        raise ReleaseMetadataError("unavailable or incompatible")

    _validate_target(release["target"])
    created_at = _string(release["created_at"])
    try:
        if datetime.fromisoformat(created_at.replace("Z", "+00:00")).tzinfo is None:
            raise ValueError("timezone missing")
    except ValueError as exc:
        raise ReleaseMetadataError("unavailable or incompatible") from exc

    parity = _object(release["parity"], _PARITY_FIELDS)
    if (
        type(parity["schema_version"]) is not int
        or parity["schema_version"] != 1
        or parity["status"] != "passed"
    ):
        raise ReleaseMetadataError("unavailable or incompatible")
    if _string(parity["model_id"]) != model["model_id"] or _hash(parity["model_sha256"]) != model["artifact_sha256"]:
        raise ReleaseMetadataError("unavailable or incompatible")
    if not isinstance(parity["labels"], list) or tuple(parity["labels"]) != _CANONICAL_LABELS:
        raise ReleaseMetadataError("unavailable or incompatible")
    metrics = _object(parity["metrics"], _PARITY_METRICS_FIELDS)
    images = _integer(metrics["reference_images"], minimum=1)
    matches = _integer(metrics["top1_matches"])
    delta = metrics["max_probability_delta"]
    if isinstance(delta, bool) or not isinstance(delta, (int, float)) or not math.isfinite(delta) or not 0 <= delta <= 0.0001 or matches > images:
        raise ReleaseMetadataError("unavailable or incompatible")
    holdout = _object(parity["holdout"], _PARITY_HOLDOUT_FIELDS)
    if holdout["status"] != "passed" or holdout["split"] != "holdout" or holdout["valid"] is not True or holdout["overlaps_training"] is not False:
        raise ReleaseMetadataError("unavailable or incompatible")
    _integer(holdout["samples"], minimum=1)
    return release, components


def _sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ReleaseMetadataError("unavailable or incompatible") from exc


def validate_runtime_model_identity(paths, classifier, integrity: RuntimeModelIntegrity) -> None:
    """Bind the loaded classifier to every anchored staged-model identity input."""
    if _sha256_file(paths.model_bundle_dir / "manifest.json") != integrity.model_manifest_sha256:
        raise ReleaseMetadataError("unavailable or incompatible")
    labels_path = paths.resources_dir / "release" / "labels.json"
    if _sha256_file(labels_path) != integrity.model_labels_sha256:
        raise ReleaseMetadataError("unavailable or incompatible")
    labels = _read_json(labels_path)
    if not isinstance(labels, list) or tuple(labels) != integrity.labels:
        raise ReleaseMetadataError("unavailable or incompatible")
    manifest = getattr(classifier, "manifest", None)
    if (
        getattr(manifest, "model_id", None) != integrity.model_id
        or getattr(manifest, "schema_version", None) != integrity.model_schema_version
        or getattr(manifest, "artifact_sha256", None) != integrity.model_artifact_sha256
        or tuple(getattr(classifier, "classes", ())) != integrity.labels
    ):
        raise ReleaseMetadataError("unavailable or incompatible")


def load_release_metadata(paths) -> tuple[ReleaseMetadata, dict[str, object], RuntimeModelIntegrity]:
    """Read one closed, byte-anchored release record for runtime and About."""
    metadata = _object(_read_json(paths.build_metadata_path), _BUILD_FIELDS)
    if type(metadata["schema_version"]) is not int or metadata["schema_version"] != 1:
        raise ReleaseMetadataError("unavailable or incompatible")
    app_version = _string(metadata["app_version"])
    source_revision = _string(metadata["source_revision"])
    if _REVISION.fullmatch(source_revision) is None:
        raise ReleaseMetadataError("unavailable or incompatible")
    expected_manifest_sha = _hash(metadata["release_manifest_sha256"])
    try:
        manifest_bytes = paths.release_manifest_path.read_bytes()
    except OSError as exc:
        raise ReleaseMetadataError("unavailable or incompatible") from exc
    if hashlib.sha256(manifest_bytes).hexdigest() != expected_manifest_sha:
        raise ReleaseMetadataError("unavailable or incompatible")
    try:
        manifest = json.loads(
            manifest_bytes.decode("utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (UnicodeError, ValueError) as exc:
        raise ReleaseMetadataError("unavailable or incompatible") from exc
    release, components = _validate_release_manifest(manifest)
    if release["app_version"] != app_version:
        raise ReleaseMetadataError("unavailable or incompatible")
    value = ReleaseMetadata(
        app_version=app_version,
        source_revision=source_revision,
        model_sha256=release["model"]["artifact_sha256"],
        component_database_sha256=components["sha256"],
        component_database_version=components["version"],
    )
    expectations = {
        "expected_sha256": components["sha256"],
        "expected_content_sha256": components["content_sha256"],
        "expected_schema_version": components["schema_version"],
        "expected_version": components["version"],
    }
    integrity = RuntimeModelIntegrity(
        model_id=release["model"]["model_id"],
        model_schema_version=release["model"]["schema_version"],
        model_artifact_sha256=release["model"]["artifact_sha256"],
        model_manifest_sha256=release["model"]["manifest_sha256"],
        model_labels_sha256=release["model"]["labels_sha256"],
        labels=tuple(release["parity"]["labels"]),
    )
    return value, expectations, integrity

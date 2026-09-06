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
_TARGET_FIELDS = frozenset({"architecture", "minimum_macos"})
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

    target = _object(release["target"], _TARGET_FIELDS)
    if target["architecture"] != "arm64" or target["minimum_macos"] != "14.0":
        raise ReleaseMetadataError("unavailable or incompatible")
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


def load_release_metadata(paths) -> tuple[ReleaseMetadata, dict[str, object]]:
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
    return value, {
        "expected_sha256": components["sha256"],
        "expected_content_sha256": components["content_sha256"],
        "expected_schema_version": components["schema_version"],
        "expected_version": components["version"],
    }

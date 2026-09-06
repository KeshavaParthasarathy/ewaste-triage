#!/usr/bin/env python3
"""Validate and atomically stage immutable assets for a macOS app release."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
from typing import Any, Mapping
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.photo_classes import PHOTO_CLASS_SPECS
from server.model_bundle import ModelBundleError, SUPPORTED_SCHEMA, load_model_bundle, sha256_file
from server.reference_db import ReferenceStore, SCHEMA_VERSION as REFERENCE_SCHEMA_VERSION


RELEASE_SCHEMA_VERSION = 1
TARGET_ARCHITECTURE = "arm64"
MINIMUM_MACOS_VERSION = "14.0"
MAX_PARITY_DELTA = 1e-4
CANONICAL_LABELS = tuple(PHOTO_CLASS_SPECS)
_PARITY_FIELDS = frozenset({"schema_version", "status", "model_id", "model_sha256", "labels", "metrics", "holdout"})
_METRIC_FIELDS = frozenset({"reference_images", "top1_matches", "max_probability_delta"})
_HOLDOUT_FIELDS = frozenset({"status", "split", "valid", "overlaps_training", "samples"})


class ReleasePreparationError(ValueError):
    """The candidate assets cannot safely become a packaged release."""


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReleasePreparationError(f"{label} is unreadable or malformed") from error
    if not isinstance(value, dict):
        raise ReleasePreparationError(f"{label} must be an object")
    return value


def _require_exact_fields(value: Mapping[str, Any], fields: frozenset[str], label: str) -> None:
    if set(value) != fields:
        raise ReleasePreparationError(f"{label} has an invalid closed schema")


def _require_int(value: object, label: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or (positive and value <= 0):
        raise ReleasePreparationError(f"{label} must be {'a positive ' if positive else 'an '}integer")
    return value


def _require_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not float("-inf") < value < float("inf"):
        raise ReleasePreparationError(f"{label} must be finite")
    return float(value)


def _validate_parity_report(
    parity_report: Path,
    *,
    model_id: str,
    model_sha256: str,
    labels: tuple[str, ...],
    model_parity: Mapping[str, Any],
) -> dict[str, Any]:
    report = _read_json(parity_report, "parity report")
    _require_exact_fields(report, _PARITY_FIELDS, "parity report")
    if report["schema_version"] != RELEASE_SCHEMA_VERSION:
        raise ReleasePreparationError("parity report schema_version is unsupported")
    if report["status"] != "passed":
        raise ReleasePreparationError("parity status must be passed")
    if report["model_id"] != model_id or report["model_sha256"] != model_sha256:
        raise ReleasePreparationError("parity report does not match the model checksum or version")
    if report["labels"] != list(labels):
        raise ReleasePreparationError("parity report labels are not the approved canonical order")

    metrics = report["metrics"]
    if not isinstance(metrics, dict):
        raise ReleasePreparationError("parity report metrics must be an object")
    _require_exact_fields(metrics, _METRIC_FIELDS, "parity report metrics")
    image_count = _require_int(metrics["reference_images"], "parity reference_images", positive=True)
    top1_matches = _require_int(metrics["top1_matches"], "parity top1_matches")
    delta = _require_number(metrics["max_probability_delta"], "parity max_probability_delta")
    if top1_matches != image_count or delta < 0 or delta > MAX_PARITY_DELTA:
        raise ReleasePreparationError("parity report metrics do not meet the release gate")
    if dict(model_parity) != metrics:
        raise ReleasePreparationError("parity report metrics do not match the model manifest")

    holdout = report["holdout"]
    if not isinstance(holdout, dict):
        raise ReleasePreparationError("holdout report must be an object")
    _require_exact_fields(holdout, _HOLDOUT_FIELDS, "holdout report")
    if (
        holdout["status"] != "passed"
        or holdout["split"] != "holdout"
        or holdout["valid"] is not True
        or holdout["overlaps_training"] is not False
        or _require_int(holdout["samples"], "holdout samples", positive=True) <= 0
    ):
        raise ReleasePreparationError("holdout report is invalid or overlaps training data")
    return report


def _fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _write_release_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    _write_json(path, manifest)


def _copy_asset(source: Path, destination: Path) -> None:
    shutil.copy2(source, destination)
    _fsync_file(destination)


def _promote(stage: Path, output: Path) -> None:
    backup: Path | None = None
    if output.exists():
        if not output.is_dir():
            raise ReleasePreparationError("release output must be a directory")
        backup = output.parent / f".{output.name}-{uuid4().hex}.previous"
        os.replace(output, backup)
    try:
        os.replace(stage, output)
    except BaseException:
        if backup is not None:
            os.replace(backup, output)
        raise
    else:
        if backup is not None:
            shutil.rmtree(backup)
    _fsync_directory(output.parent)


def prepare_release(
    model_bundle: Path,
    component_db: Path,
    parity_report: Path,
    output_dir: Path,
    app_version: str,
) -> Path:
    """Validate candidates and atomically replace *output_dir* with staged release assets."""
    model_bundle = Path(model_bundle)
    component_db = Path(component_db)
    parity_report = Path(parity_report)
    output_dir = Path(output_dir)
    if not isinstance(app_version, str) or not app_version.strip():
        raise ReleasePreparationError("app_version must be a non-empty string")
    try:
        model_manifest, artifact = load_model_bundle(model_bundle)
    except ModelBundleError as error:
        raise ReleasePreparationError(f"model bundle validation failed: {error}") from error
    if model_manifest.schema_version != SUPPORTED_SCHEMA:
        raise ReleasePreparationError("model schema_version is unsupported")
    if model_manifest.classes != CANONICAL_LABELS:
        raise ReleasePreparationError("model labels are not the approved canonical order")

    try:
        with ReferenceStore(component_db) as references:
            component_manifest = references.manifest
    except (OSError, ValueError, sqlite3.Error) as error:  # type: ignore[name-defined]
        raise ReleasePreparationError("component database validation failed") from error
    if component_manifest.schema_version != REFERENCE_SCHEMA_VERSION:
        raise ReleasePreparationError("component database schema_version is unsupported")

    model_sha256 = sha256_file(artifact)
    model_parity = model_manifest.metrics.get("parity")
    if not isinstance(model_parity, Mapping):
        raise ReleasePreparationError("model manifest has no valid parity metrics")
    report = _validate_parity_report(
        parity_report,
        model_id=model_manifest.model_id,
        model_sha256=model_sha256,
        labels=model_manifest.classes,
        model_parity=model_parity,
    )

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}-", suffix=".tmp", dir=output_dir.parent))
    try:
        model_stage = stage / "model"
        model_stage.mkdir()
        _copy_asset(artifact, model_stage / "model.onnx")
        _copy_asset(model_bundle / "manifest.json", model_stage / "manifest.json")
        labels_path = stage / "labels.json"
        # Keep the labels asset a plain JSON array for the runtime, with deterministic bytes.
        labels_path.write_text(
            json.dumps(list(model_manifest.classes), separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        _fsync_file(labels_path)
        _copy_asset(component_db, stage / "components.sqlite")
        _write_json(stage / "parity-report.json", report)

        manifest = {
            "schema_version": RELEASE_SCHEMA_VERSION,
            "app_version": app_version,
            "model": {
                "model_id": model_manifest.model_id,
                "artifact_sha256": sha256_file(model_stage / "model.onnx"),
                "labels_sha256": sha256_file(labels_path),
                "schema_version": model_manifest.schema_version,
            },
            "components": {
                "sha256": sha256_file(stage / "components.sqlite"),
                "schema_version": component_manifest.schema_version,
                "version": component_manifest.version,
            },
            "target": {"architecture": TARGET_ARCHITECTURE, "minimum_macos": MINIMUM_MACOS_VERSION},
            "created_at": datetime.now(timezone.utc).isoformat(),
            "parity": report,
        }
        _write_release_manifest(stage / "release-manifest.json", manifest)
        _fsync_directory(model_stage)
        _fsync_directory(stage)
        _promote(stage, output_dir)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return output_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-bundle", required=True, type=Path)
    parser.add_argument("--component-db", required=True, type=Path)
    parser.add_argument("--parity-report", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--app-version", required=True)
    arguments = parser.parse_args()
    print(prepare_release(**vars(arguments)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

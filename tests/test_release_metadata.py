"""Closed packaged-release identity contracts."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

import pytest

from desktop.release_metadata import ReleaseMetadataError, load_release_metadata


LABELS = [
    "0301_computer_mouse",
    "0301_keyboard",
    "0303_laptop",
    "0306_mobile_phone",
    "0401_headphones",
]


def _write_release(tmp_path, *, build_change=None, manifest_change=None):
    resources = tmp_path / "resources"
    release_dir = resources / "release"
    release_dir.mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "app_version": "1.2.3",
        "model": {
            "model_id": "release-model-1",
            "artifact_sha256": "a" * 64,
            "manifest_sha256": "b" * 64,
            "labels_sha256": "c" * 64,
            "schema_version": 1,
        },
        "components": {
            "sha256": "d" * 64,
            "content_sha256": "e" * 64,
            "schema_version": 2,
            "version": "2.0.0",
        },
        "target": {"architecture": "arm64", "minimum_macos": "14.0"},
        "created_at": "2026-09-06T12:00:00+00:00",
        "parity": {
            "schema_version": 1,
            "status": "passed",
            "model_id": "release-model-1",
            "model_sha256": "a" * 64,
            "labels": LABELS,
            "metrics": {"reference_images": 5, "top1_matches": 5, "max_probability_delta": 0.0},
            "holdout": {"status": "passed", "split": "holdout", "valid": True, "overlaps_training": False, "samples": 25},
        },
    }
    if manifest_change:
        manifest_change(manifest)
    manifest_path = release_dir / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    build = {
        "schema_version": 1,
        "app_version": "1.2.3",
        "source_revision": "f" * 40,
        "release_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    }
    if build_change:
        build_change(build)
    build_path = resources / "build-metadata.json"
    build_path.write_text(json.dumps(build, sort_keys=True), encoding="utf-8")
    return SimpleNamespace(build_metadata_path=build_path, release_manifest_path=manifest_path)


def test_load_release_metadata_returns_display_and_reference_values_from_one_record(tmp_path):
    metadata, expectations = load_release_metadata(_write_release(tmp_path))

    assert metadata.public_payload() == {
        "app_version": "1.2.3",
        "source_revision": "f" * 40,
        "model_sha256": "a" * 64,
        "component_database_sha256": "d" * 64,
        "component_database_version": "2.0.0",
    }
    assert expectations == {
        "expected_sha256": "d" * 64,
        "expected_content_sha256": "e" * 64,
        "expected_schema_version": 2,
        "expected_version": "2.0.0",
    }


@pytest.mark.parametrize(
    ("build_change", "manifest_change"),
    [
        (lambda build: build.update({"extra": "no"}), None),
        (lambda build: build.pop("source_revision"), None),
        (lambda build: build.update({"schema_version": True}), None),
        (lambda build: build.update({"source_revision": "F" * 40}), None),
        (None, lambda manifest: manifest.update({"extra": "no"})),
        (None, lambda manifest: manifest.pop("model")),
        (None, lambda manifest: manifest["model"].update({"artifact_sha256": "A" * 64})),
        (None, lambda manifest: manifest.update({"app_version": "9.9.9"})),
        (None, lambda manifest: manifest["components"].update({"schema_version": 3})),
        (None, lambda manifest: manifest["components"].update({"version": "2.1.0"})),
    ],
)
def test_load_release_metadata_fails_closed_for_schema_or_identity_drift(
    tmp_path, build_change, manifest_change
):
    paths = _write_release(
        tmp_path, build_change=build_change, manifest_change=manifest_change
    )

    with pytest.raises(ReleaseMetadataError, match="unavailable or incompatible"):
        load_release_metadata(paths)


def test_load_release_metadata_rejects_a_build_anchor_for_other_manifest_bytes(tmp_path):
    paths = _write_release(tmp_path)
    manifest = json.loads(paths.release_manifest_path.read_text(encoding="utf-8"))
    manifest["created_at"] = "2026-09-07T12:00:00+00:00"
    paths.release_manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")

    with pytest.raises(ReleaseMetadataError, match="unavailable or incompatible"):
        load_release_metadata(paths)

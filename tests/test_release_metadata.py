"""Closed packaged-release identity contracts."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from desktop.main import ModelStartupError, build_desktop_app
from desktop.paths import AppPaths
import desktop.release_metadata as release_metadata
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
    model_dir = resources / "models" / "production"
    model_dir.mkdir(parents=True)
    runtime_manifest = {
        "model_id": "release-model-1",
        "architecture": "test-onnx",
        "classes": LABELS,
        "preprocessing_version": "rgb-224-v1",
        "confidence_floor": 0.6,
        "artifact_sha256": "a" * 64,
        "schema_version": 1,
        "metrics": {"parity": {"reference_images": 5}},
    }
    runtime_manifest_path = model_dir / "manifest.json"
    runtime_manifest_path.write_text(
        json.dumps(runtime_manifest, sort_keys=True), encoding="utf-8"
    )
    labels_path = release_dir / "labels.json"
    labels_path.write_text(json.dumps(LABELS, separators=(",", ":")), encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "app_version": "1.2.3",
        "model": {
            "model_id": "release-model-1",
            "artifact_sha256": "a" * 64,
            "manifest_sha256": hashlib.sha256(runtime_manifest_path.read_bytes()).hexdigest(),
            "labels_sha256": hashlib.sha256(labels_path.read_bytes()).hexdigest(),
            "schema_version": 1,
        },
        "components": {
            "sha256": "d" * 64,
            "content_sha256": "e" * 64,
            "schema_version": 2,
            "version": "2.0.0",
        },
        "target": {
            "platform": "macos",
            "architecture": "arm64",
            "minimum_version": "14.0",
        },
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
    return SimpleNamespace(
        resources_dir=resources,
        model_bundle_dir=model_dir,
        build_metadata_path=build_path,
        release_manifest_path=manifest_path,
    )


def test_load_release_metadata_returns_display_and_reference_values_from_one_record(tmp_path):
    metadata, expectations, integrity = load_release_metadata(_write_release(tmp_path))

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
    assert integrity.model_manifest_sha256 != integrity.model_labels_sha256


def test_load_release_metadata_accepts_windows_x64_target(tmp_path):
    paths = _write_release(
        tmp_path,
        manifest_change=lambda manifest: manifest.update(
            target={
                "platform": "windows",
                "architecture": "x86_64",
                "minimum_version": "11",
            }
        ),
    )

    metadata, _expectations, _integrity = load_release_metadata(paths)

    assert metadata.app_version == "1.2.3"


def test_load_release_metadata_keeps_legacy_macos_target_compatible(tmp_path):
    paths = _write_release(
        tmp_path,
        manifest_change=lambda manifest: manifest.update(
            target={"architecture": "arm64", "minimum_macos": "14.0"}
        ),
    )

    metadata, _expectations, _integrity = load_release_metadata(paths)

    assert metadata.app_version == "1.2.3"


@pytest.mark.parametrize(
    "target",
    [
        {"platform": "windows", "architecture": "arm64", "minimum_version": "11"},
        {"platform": "linux", "architecture": "x86_64", "minimum_version": "11"},
        {"platform": "macos", "architecture": "arm64", "minimum_version": "11"},
    ],
)
def test_load_release_metadata_rejects_unsupported_target_combinations(tmp_path, target):
    paths = _write_release(
        tmp_path,
        manifest_change=lambda manifest: manifest.update(target=target),
    )

    with pytest.raises(ReleaseMetadataError, match="unavailable or incompatible"):
        load_release_metadata(paths)


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
        (None, lambda manifest: manifest["model"].update({"schema_version": True})),
        (None, lambda manifest: manifest["components"].update({"sha256": 7})),
        (None, lambda manifest: manifest.update({"app_version": "9.9.9"})),
        (None, lambda manifest: manifest["components"].update({"schema_version": 3})),
        (None, lambda manifest: manifest["components"].update({"version": "2.1.0"})),
        (None, lambda manifest: manifest["target"].update({"architecture": True})),
        (None, lambda manifest: manifest["parity"].update({"labels": "not-a-list"})),
        (None, lambda manifest: manifest["parity"]["metrics"].update({"reference_images": True})),
        (None, lambda manifest: manifest["parity"]["holdout"].update({"valid": 1})),
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


def test_runtime_model_identity_rejects_same_artifact_with_different_manifest_or_labels(tmp_path):
    """An unchanged ONNX file cannot authorize a different runtime model identity."""
    paths = _write_release(tmp_path)
    validator = getattr(release_metadata, "validate_runtime_model_identity", None)

    assert callable(validator)
    _metadata, _expectations, integrity = load_release_metadata(paths)
    classifier = SimpleNamespace(
        manifest=SimpleNamespace(
            model_id="release-model-1", schema_version=1, artifact_sha256="a" * 64
        ),
        classes=tuple(LABELS),
    )
    validator(paths, classifier, integrity)

    runtime_manifest = json.loads((paths.model_bundle_dir / "manifest.json").read_text())
    runtime_manifest["confidence_floor"] = 0.7
    (paths.model_bundle_dir / "manifest.json").write_text(json.dumps(runtime_manifest, sort_keys=True))
    with pytest.raises(ReleaseMetadataError, match="unavailable or incompatible"):
        validator(paths, classifier, integrity)

    (paths.model_bundle_dir / "manifest.json").write_text(json.dumps({
        **runtime_manifest, "confidence_floor": 0.6
    }, sort_keys=True))
    (paths.resources_dir / "release" / "labels.json").write_text(json.dumps(list(reversed(LABELS))))
    with pytest.raises(ReleaseMetadataError, match="unavailable or incompatible"):
        validator(paths, classifier, integrity)


def test_frozen_assembly_recovers_when_same_artifact_has_a_rewritten_manifest(
    monkeypatch, tmp_path
):
    paths = _write_release(tmp_path)
    runtime_manifest = json.loads((paths.model_bundle_dir / "manifest.json").read_text())
    runtime_manifest["confidence_floor"] = 0.7
    (paths.model_bundle_dir / "manifest.json").write_text(json.dumps(runtime_manifest, sort_keys=True))
    classifier = SimpleNamespace(
        manifest=SimpleNamespace(
            model_id="release-model-1", schema_version=1, artifact_sha256="a" * 64
        ),
        classes=tuple(LABELS),
    )
    monkeypatch.setattr("desktop.main.OnnxClassifier", lambda _path: classifier)
    app_paths = AppPaths(
        resources_dir=paths.resources_dir,
        static_dir=paths.resources_dir / "server" / "static",
        model_bundle_dir=paths.model_bundle_dir,
        reference_dir=paths.resources_dir / "reference",
        data_dir=tmp_path / "support",
        history_database_path=tmp_path / "support" / "history.sqlite",
        history_media_dir=tmp_path / "support" / "media",
    )

    with pytest.raises(ModelStartupError, match="unavailable or incompatible"):
        build_desktop_app(app_paths, require_release_integrity=True)

"""Contracts for immutable, parity-gated app-release staging."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.build_component_db import compile_reference
from scripts.prepare_release import ReleasePreparationError, prepare_release


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_LABELS = [
    "0301_computer_mouse",
    "0301_keyboard",
    "0303_laptop",
    "0306_mobile_phone",
    "0401_headphones",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_model_bundle(root: Path, *, schema_version: int = 1) -> Path:
    bundle = root / "model-bundle"
    bundle.mkdir()
    artifact = bundle / "model.onnx"
    artifact.write_bytes(b"approved test model")
    (bundle / "manifest.json").write_text(json.dumps({
        "model_id": "approved-model-2026-09",
        "architecture": "test-architecture",
        "classes": CANONICAL_LABELS,
        "preprocessing_version": "rgb-224-v1",
        "confidence_floor": 0.6,
        "artifact_sha256": sha256(artifact),
        "schema_version": schema_version,
        "metrics": {"parity": {"reference_images": 5, "top1_matches": 5, "max_probability_delta": 0.0}},
    }))
    return bundle


def write_parity_report(root: Path, bundle: Path, **changes) -> Path:
    report = {
        "schema_version": 1,
        "status": "passed",
        "model_id": "approved-model-2026-09",
        "model_sha256": sha256(bundle / "model.onnx"),
        "labels": CANONICAL_LABELS,
        "metrics": {"reference_images": 5, "top1_matches": 5, "max_probability_delta": 0.0},
        "holdout": {
            "status": "passed",
            "split": "holdout",
            "valid": True,
            "overlaps_training": False,
            "samples": 25,
        },
    }
    report.update(changes)
    path = root / "parity-report.json"
    path.write_text(json.dumps(report))
    return path


@pytest.fixture
def release_inputs(tmp_path):
    bundle = write_model_bundle(tmp_path)
    components = tmp_path / "components.sqlite"
    compile_reference(ROOT / "reference", components)
    report = write_parity_report(tmp_path, bundle)
    return bundle, components, report, tmp_path / "release"


def test_prepare_release_requires_passing_parity_report(release_inputs):
    bundle, components, report, output = release_inputs
    write_parity_report(report.parent, bundle, status="failed")

    with pytest.raises(ReleasePreparationError, match="parity status"):
        prepare_release(bundle, components, report, output, "1.2.3")

    assert not output.exists()


def test_prepare_release_rejects_checksum_mismatch(release_inputs):
    bundle, components, report, output = release_inputs
    (bundle / "model.onnx").write_bytes(b"tampered after manifest")

    with pytest.raises(ReleasePreparationError, match="checksum"):
        prepare_release(bundle, components, report, output, "1.2.3")

    assert not output.exists()


def test_prepare_release_rejects_unknown_schema_version(release_inputs):
    bundle, components, report, output = release_inputs
    write_parity_report(report.parent, bundle, schema_version=99)

    with pytest.raises(ReleasePreparationError, match="schema_version"):
        prepare_release(bundle, components, report, output, "1.2.3")


def test_prepare_release_reports_an_invalid_component_database(release_inputs):
    bundle, components, report, output = release_inputs
    components.write_bytes(b"not sqlite")

    with pytest.raises(ReleasePreparationError, match="component database"):
        prepare_release(bundle, components, report, output, "1.2.3")


def test_prepare_release_rejects_invalid_or_overlapping_holdout(release_inputs):
    bundle, components, report, output = release_inputs
    write_parity_report(
        report.parent,
        bundle,
        holdout={"status": "passed", "split": "holdout", "valid": True, "overlaps_training": True, "samples": 25},
    )

    with pytest.raises(ReleasePreparationError, match="holdout"):
        prepare_release(bundle, components, report, output, "1.2.3")


def test_prepare_release_stages_model_labels_components_and_manifest_atomically(release_inputs):
    bundle, components, report, output = release_inputs

    result = prepare_release(bundle, components, report, output, "1.2.3")

    assert result == output
    assert (output / "model" / "model.onnx").read_bytes() == (bundle / "model.onnx").read_bytes()
    assert json.loads((output / "labels.json").read_text()) == CANONICAL_LABELS
    assert (output / "components.sqlite").read_bytes() == components.read_bytes()
    manifest = json.loads((output / "release-manifest.json").read_text())
    assert set(manifest) == {"schema_version", "app_version", "model", "components", "target", "created_at", "parity"}
    assert manifest["model"] == {
        "model_id": "approved-model-2026-09",
        "artifact_sha256": sha256(output / "model" / "model.onnx"),
        "labels_sha256": sha256(output / "labels.json"),
        "schema_version": 1,
    }
    assert manifest["components"] == {"sha256": sha256(output / "components.sqlite"), "schema_version": 1, "version": "1.0.0"}
    assert manifest["target"] == {"architecture": "arm64", "minimum_macos": "14.0"}
    assert manifest["parity"]["holdout"]["overlaps_training"] is False
    assert not list(output.parent.glob(f".{output.name}-*.tmp"))


def test_failed_staging_preserves_previous_release(release_inputs, monkeypatch):
    bundle, components, report, output = release_inputs
    output.mkdir()
    (output / "previous-release.txt").write_text("keep me")

    monkeypatch.setattr(
        "scripts.prepare_release._write_release_manifest",
        lambda *_: (_ for _ in ()).throw(OSError("disk full")),
    )

    with pytest.raises(OSError, match="disk full"):
        prepare_release(bundle, components, report, output, "1.2.3")

    assert (output / "previous-release.txt").read_text() == "keep me"
    assert not list(output.parent.glob(f".{output.name}-*.tmp"))

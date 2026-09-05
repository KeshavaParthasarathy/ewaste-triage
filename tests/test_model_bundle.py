import hashlib
import json

import pytest

from server.model_bundle import ModelBundleError, load_model_bundle


def write_manifest(bundle_dir, **overrides):
    manifest = {
        "model_id": "ewaste-resnet18-2026-09-05",
        "architecture": "resnet18",
        "classes": ["0301_computer_mouse", "0306_mobile_phone"],
        "preprocessing_version": "rgb-224-v1",
        "confidence_floor": 0.6,
        "artifact_sha256": hashlib.sha256(b"known model").hexdigest(),
        "schema_version": 1,
        "metrics": {"top1_accuracy": 0.91},
    }
    manifest.update(overrides)
    (bundle_dir / "manifest.json").write_text(json.dumps(manifest))


def write_valid_bundle(bundle_dir):
    (bundle_dir / "model.onnx").write_bytes(b"known model")
    write_manifest(bundle_dir)


def test_load_model_bundle_verifies_sha256(tmp_path):
    model = tmp_path / "model.onnx"
    model.write_bytes(b"known model")
    write_manifest(tmp_path, artifact_sha256=hashlib.sha256(model.read_bytes()).hexdigest())

    manifest, path = load_model_bundle(tmp_path)

    assert manifest.classes == ("0301_computer_mouse", "0306_mobile_phone")
    assert path == model


def test_load_model_bundle_rejects_tampered_artifact(tmp_path):
    write_valid_bundle(tmp_path)
    (tmp_path / "model.onnx").write_bytes(b"tampered")

    with pytest.raises(ModelBundleError, match="checksum"):
        load_model_bundle(tmp_path)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"classes": ["0301_computer_mouse", "0301_computer_mouse"]}, "duplicate"),
        ({"classes": []}, "classes"),
        ({"confidence_floor": -0.01}, "confidence"),
        ({"confidence_floor": 1.01}, "confidence"),
        ({"metrics": []}, "metrics"),
        ({"schema_version": 2}, "unsupported"),
        ({"unexpected": "field"}, "unknown"),
    ],
)
def test_load_model_bundle_rejects_invalid_manifest_values(tmp_path, overrides, message):
    write_valid_bundle(tmp_path)
    write_manifest(tmp_path, **overrides)

    with pytest.raises(ModelBundleError, match=message):
        load_model_bundle(tmp_path)


@pytest.mark.parametrize(
    "overrides",
    [
        {"model_id": 42},
        {"architecture": None},
        {"classes": "0301_computer_mouse"},
        {"preprocessing_version": False},
        {"confidence_floor": "0.6"},
        {"artifact_sha256": "not-a-sha256"},
        {"schema_version": True},
    ],
)
def test_load_model_bundle_rejects_wrong_field_types(tmp_path, overrides):
    write_valid_bundle(tmp_path)
    write_manifest(tmp_path, **overrides)

    with pytest.raises(ModelBundleError, match="manifest"):
        load_model_bundle(tmp_path)


@pytest.mark.parametrize("missing_field", [
    "model_id", "architecture", "classes", "preprocessing_version",
    "confidence_floor", "artifact_sha256", "schema_version", "metrics",
])
def test_load_model_bundle_rejects_missing_required_field(tmp_path, missing_field):
    write_valid_bundle(tmp_path)
    raw = json.loads((tmp_path / "manifest.json").read_text())
    raw.pop(missing_field)
    (tmp_path / "manifest.json").write_text(json.dumps(raw))

    with pytest.raises(ModelBundleError, match="missing"):
        load_model_bundle(tmp_path)


def test_load_model_bundle_rejects_malformed_json(tmp_path):
    write_valid_bundle(tmp_path)
    (tmp_path / "manifest.json").write_text("{")

    with pytest.raises(ModelBundleError, match="malformed"):
        load_model_bundle(tmp_path)


def test_load_model_bundle_rejects_symlinked_artifact_outside_bundle(tmp_path):
    outside = tmp_path.parent / "outside-model.onnx"
    outside.write_bytes(b"known model")
    (tmp_path / "model.onnx").symlink_to(outside)
    write_manifest(tmp_path)

    with pytest.raises(ModelBundleError, match="escapes"):
        load_model_bundle(tmp_path)

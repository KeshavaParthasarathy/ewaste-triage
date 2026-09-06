"""Contracts for immutable, parity-gated app-release staging."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pytest
import yaml

import scripts.prepare_release as release_module
from scripts.build_component_db import compile_reference
from scripts.prepare_release import ReleasePreparationError, prepare_release
from server.reference_db import ReferenceStore


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


def test_prepare_release_rejects_unsupported_model_preprocessing(release_inputs):
    bundle, components, report, output = release_inputs
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["preprocessing_version"] = "rgb-999-v9"
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(ReleasePreparationError, match="preprocessing"):
        prepare_release(bundle, components, report, output, "1.2.3")

    assert not output.exists()


def test_prepare_release_rejects_invalid_model_confidence_floor(release_inputs):
    bundle, components, report, output = release_inputs
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["confidence_floor"] = 1.1
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(ReleasePreparationError, match="confidence_floor"):
        prepare_release(bundle, components, report, output, "1.2.3")

    assert not output.exists()


def test_prepare_release_rejects_model_manifest_change_during_staging(
    release_inputs, monkeypatch
):
    bundle, components, report, output = release_inputs
    real_copy = release_module._copy_asset

    def copy_then_tamper(source, destination):
        real_copy(source, destination)
        if Path(source) == bundle / "manifest.json":
            staged_manifest = json.loads(Path(destination).read_text())
            staged_manifest["confidence_floor"] = 0.75
            Path(destination).write_text(json.dumps(staged_manifest))

    monkeypatch.setattr(release_module, "_copy_asset", copy_then_tamper)

    with pytest.raises(ReleasePreparationError, match="changed while staging"):
        prepare_release(bundle, components, report, output, "1.2.3")

    assert not output.exists()
    assert not list(output.parent.glob(f".{output.name}-*.tmp"))


def test_prepare_release_rejects_source_manifest_change_after_validation(
    release_inputs, monkeypatch
):
    bundle, components, report, output = release_inputs
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["metrics"]["parity"] = {
        "reference_images": 1,
        "top1_matches": 1,
        "max_probability_delta": 0.0,
    }
    manifest_path.write_text(json.dumps(manifest))
    parity = json.loads(report.read_text())
    parity["metrics"] = {
        "reference_images": 1,
        "top1_matches": 1,
        "max_probability_delta": 0.0,
    }
    report.write_text(json.dumps(parity))
    real_sha256_file = release_module.sha256_file
    mutated = False

    def mutate_after_first_source_manifest_hash(path):
        nonlocal mutated
        digest = real_sha256_file(Path(path))
        if Path(path) == manifest_path and not mutated:
            mutated = True
            manifest = json.loads(manifest_path.read_text())
            manifest["metrics"]["parity"] = {
                "reference_images": True,
                "top1_matches": True,
                "max_probability_delta": False,
            }
            manifest_path.write_text(json.dumps(manifest))
        return digest

    monkeypatch.setattr(
        release_module,
        "sha256_file",
        mutate_after_first_source_manifest_hash,
    )

    with pytest.raises(ReleasePreparationError, match="changed while validating"):
        prepare_release(bundle, components, report, output, "1.2.3")

    assert not output.exists()
    assert not list(output.parent.glob(f".{output.name}-*.tmp"))


def test_prepare_release_preserves_output_when_source_changes_before_hash_capture(
    release_inputs, monkeypatch
):
    bundle, components, report, output = release_inputs
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["metrics"]["parity"] = {
        "reference_images": 1,
        "top1_matches": 1,
        "max_probability_delta": 0.0,
    }
    manifest_path.write_text(json.dumps(manifest))
    parity = json.loads(report.read_text())
    parity["metrics"] = {
        "reference_images": 1,
        "top1_matches": 1,
        "max_probability_delta": 0.0,
    }
    report.write_text(json.dumps(parity))
    output.mkdir()
    sentinel = output / "previous-release.txt"
    sentinel.write_text("keep the approved release")
    real_sha256_file = release_module.sha256_file
    mutated = False

    def mutate_before_first_source_manifest_hash(path):
        nonlocal mutated
        if Path(path) == manifest_path and not mutated:
            mutated = True
            changed = json.loads(manifest_path.read_text())
            changed["metrics"]["parity"] = {
                "reference_images": True,
                "top1_matches": True,
                "max_probability_delta": False,
            }
            manifest_path.write_text(json.dumps(changed))
        return real_sha256_file(Path(path))

    monkeypatch.setattr(
        release_module,
        "sha256_file",
        mutate_before_first_source_manifest_hash,
    )

    with pytest.raises(ReleasePreparationError, match="metrics do not match"):
        prepare_release(bundle, components, report, output, "1.2.3")

    assert sentinel.read_text() == "keep the approved release"
    assert not list(output.parent.glob(f".{output.name}-*.tmp"))
    assert not list(output.parent.glob(f".{output.name}-*.backup-*"))


def test_prepare_release_rejects_coordinated_model_bundle_change_during_staging(
    release_inputs, monkeypatch
):
    bundle, components, report, output = release_inputs
    real_copy = release_module._copy_asset

    def copy_then_tamper(source, destination):
        real_copy(source, destination)
        if Path(source) == bundle / "model.onnx":
            Path(destination).write_bytes(b"different but internally consistent model")
        elif Path(source) == bundle / "manifest.json":
            staged_manifest = json.loads(Path(destination).read_text())
            staged_manifest["artifact_sha256"] = sha256(Path(destination).parent / "model.onnx")
            Path(destination).write_text(json.dumps(staged_manifest))

    monkeypatch.setattr(release_module, "_copy_asset", copy_then_tamper)

    with pytest.raises(ReleasePreparationError, match="changed while staging"):
        prepare_release(bundle, components, report, output, "1.2.3")

    assert not output.exists()
    assert not list(output.parent.glob(f".{output.name}-*.tmp"))


def test_prepare_release_rejects_boolean_model_parity_metric_aliases(release_inputs):
    bundle, components, report, output = release_inputs
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["metrics"]["parity"] = {
        "reference_images": True,
        "top1_matches": True,
        "max_probability_delta": False,
    }
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(ReleasePreparationError, match="metrics do not match"):
        prepare_release(bundle, components, report, output, "1.2.3")

    assert not output.exists()


def test_prepare_release_rejects_unknown_schema_version(release_inputs):
    bundle, components, report, output = release_inputs
    write_parity_report(report.parent, bundle, schema_version=99)

    with pytest.raises(ReleasePreparationError, match="schema_version"):
        prepare_release(bundle, components, report, output, "1.2.3")


def test_prepare_release_rejects_boolean_parity_schema_version(release_inputs):
    bundle, components, report, output = release_inputs
    write_parity_report(report.parent, bundle, schema_version=True)

    with pytest.raises(ReleasePreparationError, match="schema_version"):
        prepare_release(bundle, components, report, output, "1.2.3")

    assert not output.exists()


def test_prepare_release_reports_an_invalid_component_database(release_inputs):
    bundle, components, report, output = release_inputs
    components.write_bytes(b"not sqlite")

    with pytest.raises(ReleasePreparationError, match="component database"):
        prepare_release(bundle, components, report, output, "1.2.3")


def test_prepare_release_reopens_staged_component_copy_and_rejects_swap(
    release_inputs, tmp_path, monkeypatch
):
    bundle, components, report, output = release_inputs
    changed_source = tmp_path / "changed-reference"
    shutil.copytree(ROOT / "reference", changed_source)
    component_yaml = changed_source / "device_components.yaml"
    document = yaml.safe_load(component_yaml.read_text())
    document["categories"][0]["display_name"] = "Changed mouse"
    component_yaml.write_text(yaml.safe_dump(document, sort_keys=False))
    swapped = tmp_path / "swapped.sqlite"
    compile_reference(changed_source, swapped)
    real_copy = release_module._copy_asset

    def swap_component_copy(source, destination):
        return real_copy(swapped if Path(source) == components else source, destination)

    monkeypatch.setattr(release_module, "_copy_asset", swap_component_copy)

    with pytest.raises(ReleasePreparationError, match="component database.*staging"):
        prepare_release(bundle, components, report, output, "1.2.3")

    assert not output.exists()


@pytest.mark.parametrize(
    "output_selector",
    ("bundle", "inside_bundle", "model_asset", "manifest_asset", "components", "report"),
)
def test_prepare_release_rejects_output_paths_overlapping_input_assets(
    release_inputs, output_selector
):
    bundle, components, report, _ = release_inputs
    output = {
        "bundle": bundle,
        "inside_bundle": bundle / "release",
        "model_asset": bundle / "model.onnx",
        "manifest_asset": bundle / "manifest.json",
        "components": components,
        "report": report,
    }[output_selector]
    original_bundle = {
        child.name: child.read_bytes()
        for child in bundle.iterdir()
    }

    with pytest.raises(ReleasePreparationError, match="overlap"):
        prepare_release(bundle, components, report, output, "1.2.3")

    assert {
        child.name: child.read_bytes()
        for child in bundle.iterdir()
    } == original_bundle
    assert not list(bundle.parent.glob(f".{output.name}-*.tmp"))
    assert not list(bundle.parent.glob(f".{output.name}-*.previous"))


def test_prepare_release_rejects_output_overlapping_resolved_manifest_asset(
    release_inputs
):
    bundle, components, report, _ = release_inputs
    manifest_link = bundle / "manifest.json"
    manifest_bytes = manifest_link.read_bytes()
    manifest_source = bundle.parent / "manifest-source"
    manifest_source.mkdir()
    resolved_manifest = manifest_source / "manifest.json"
    resolved_manifest.write_bytes(manifest_bytes)
    manifest_link.unlink()
    manifest_link.symlink_to(resolved_manifest)

    with pytest.raises(ReleasePreparationError, match="overlap"):
        prepare_release(bundle, components, report, manifest_source, "1.2.3")

    assert resolved_manifest.read_bytes() == manifest_bytes
    assert manifest_link.resolve(strict=True) == resolved_manifest
    assert not list(bundle.parent.glob(f".{manifest_source.name}-*.tmp"))
    assert not list(bundle.parent.glob(f".{manifest_source.name}-*.previous"))


@pytest.mark.parametrize(
    "repository_output",
    (ROOT / "models" / "production", ROOT / "server", ROOT / "packaging"),
)
def test_prepare_release_rejects_repository_source_output(tmp_path, repository_output):
    bundle = write_model_bundle(tmp_path)
    components = tmp_path / "components.sqlite"
    compile_reference(ROOT / "reference", components)
    report = write_parity_report(tmp_path, bundle)

    with pytest.raises(ReleasePreparationError, match="overlap|release-staging"):
        prepare_release(bundle, components, report, repository_output, "1.2.3")


@pytest.mark.parametrize(
    "source_name",
    ("data", "desktop", "docs", "models", "packaging", "reference", "refs", "scripts", "server", "tests"),
)
def test_prepare_release_rejects_output_overlapping_resolved_source_directory(
    release_inputs, tmp_path, monkeypatch, source_name
):
    bundle, components, report, _ = release_inputs
    repository = tmp_path / "checkout"
    repository.mkdir()
    source_directory = tmp_path / f"external-{source_name}"
    source_directory.mkdir()
    sentinel = source_directory / "source.py"
    sentinel.write_text("preserve me")
    (repository / source_name).symlink_to(source_directory, target_is_directory=True)
    monkeypatch.setattr(release_module, "ROOT", repository)

    with pytest.raises(ReleasePreparationError, match="overlap"):
        prepare_release(bundle, components, report, source_directory, "1.2.3")

    assert sentinel.read_text() == "preserve me"
    assert not list(source_directory.parent.glob(f".{source_directory.name}-*.tmp"))
    assert not list(source_directory.parent.glob(f".{source_directory.name}-*.previous"))


def test_prepare_release_allows_a_child_of_repository_staging_root(
    release_inputs, tmp_path, monkeypatch
):
    bundle, components, report, _ = release_inputs
    repository = tmp_path / "checkout"
    output = repository / ".release-staging" / "release"
    monkeypatch.setattr(release_module, "ROOT", repository)

    assert prepare_release(bundle, components, report, output, "1.2.3") == output
    assert (output / "release-manifest.json").is_file()


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
        "manifest_sha256": sha256(output / "model" / "manifest.json"),
        "labels_sha256": sha256(output / "labels.json"),
        "schema_version": 1,
    }
    with ReferenceStore(output / "components.sqlite") as references:
        logical_sha256 = references.manifest.content_sha256
    assert manifest["components"] == {
        "sha256": sha256(output / "components.sqlite"),
        "content_sha256": logical_sha256,
        "schema_version": 2,
        "version": "2.0.0",
    }
    assert manifest["target"] == {"architecture": "arm64", "minimum_macos": "14.0"}
    assert manifest["parity"]["holdout"]["overlaps_training"] is False
    assert not list(output.parent.glob(f".{output.name}-*.tmp"))


def test_release_manifest_schema_recursively_closes_the_actual_parity_contract():
    schema = json.loads((ROOT / "packaging" / "release-manifest.schema.json").read_text())
    model = schema["properties"]["model"]
    parity = schema["properties"]["parity"]
    metrics = parity["properties"]["metrics"]
    holdout = parity["properties"]["holdout"]
    components = schema["properties"]["components"]

    assert components["additionalProperties"] is False
    assert set(components["required"]) == {
        "sha256",
        "content_sha256",
        "schema_version",
        "version",
    }
    assert components["properties"]["content_sha256"] == {
        "type": "string",
        "pattern": "^[0-9a-f]{64}$",
    }

    assert model["additionalProperties"] is False
    assert set(model["required"]) == {
        "model_id",
        "artifact_sha256",
        "manifest_sha256",
        "labels_sha256",
        "schema_version",
    }
    assert set(model["properties"]) == set(model["required"])
    assert model["properties"]["manifest_sha256"] == {
        "type": "string",
        "pattern": "^[0-9a-f]{64}$",
    }
    assert parity["additionalProperties"] is False
    assert set(parity["required"]) == {
        "schema_version", "status", "model_id", "model_sha256", "labels", "metrics", "holdout"
    }
    assert set(parity["properties"]) == set(parity["required"])
    assert parity["properties"]["labels"] == {"const": CANONICAL_LABELS}
    assert metrics["additionalProperties"] is False
    assert set(metrics["required"]) == {"reference_images", "top1_matches", "max_probability_delta"}
    assert set(metrics["properties"]) == set(metrics["required"])
    assert metrics["properties"]["reference_images"] == {"type": "integer", "minimum": 1}
    assert metrics["properties"]["top1_matches"] == {"type": "integer", "minimum": 0}
    assert metrics["properties"]["max_probability_delta"] == {
        "type": "number", "minimum": 0, "maximum": 0.0001
    }
    assert holdout["additionalProperties"] is False
    assert set(holdout["required"]) == {"status", "split", "valid", "overlaps_training", "samples"}
    assert set(holdout["properties"]) == set(holdout["required"])
    assert holdout["properties"] == {
        "status": {"const": "passed"},
        "split": {"const": "holdout"},
        "valid": {"const": True},
        "overlaps_training": {"const": False},
        "samples": {"type": "integer", "minimum": 1},
    }


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


def test_failed_stage_to_output_replace_restores_old_release_and_cleans_backup(
    release_inputs, monkeypatch
):
    bundle, components, report, output = release_inputs
    output.mkdir()
    (output / "previous-release.txt").write_text("keep me")
    real_replace = release_module.os.replace

    def fail_once_after_backup(source, destination):
        source = Path(source)
        destination = Path(destination)
        if source.name.endswith(".tmp") and destination == output:
            raise OSError("stage promotion failed")
        return real_replace(source, destination)

    monkeypatch.setattr(release_module.os, "replace", fail_once_after_backup)

    with pytest.raises(OSError, match="stage promotion failed"):
        prepare_release(bundle, components, report, output, "1.2.3")

    assert (output / "previous-release.txt").read_text() == "keep me"
    assert not list(output.parent.glob(f".{output.name}-*.previous"))
    assert not list(output.parent.glob(f".{output.name}-*.tmp"))


def test_failed_restore_reports_both_failures_and_preserved_backup_path(
    release_inputs, monkeypatch
):
    bundle, components, report, output = release_inputs
    output.mkdir()
    (output / "previous-release.txt").write_text("keep me")
    real_replace = release_module.os.replace

    def fail_promotion_and_restore(source, destination):
        source = Path(source)
        destination = Path(destination)
        if source.name.endswith(".tmp") and destination == output:
            raise OSError("stage promotion failed")
        if source.name.endswith(".previous") and destination == output:
            raise OSError("previous release restore failed")
        return real_replace(source, destination)

    monkeypatch.setattr(release_module.os, "replace", fail_promotion_and_restore)

    with pytest.raises(ReleasePreparationError) as error:
        prepare_release(bundle, components, report, output, "1.2.3")

    assert "stage promotion failed" in str(error.value)
    assert "previous release restore failed" in str(error.value)
    assert "previous release is preserved" in str(error.value)
    backup = Path(str(error.value).rsplit(" at ", 1)[1])
    assert (backup / "previous-release.txt").read_text() == "keep me"
    assert not output.exists()
    assert not list(output.parent.glob(f".{output.name}-*.tmp"))
    assert list(output.parent.glob(f".{output.name}-*.previous")) == [backup]

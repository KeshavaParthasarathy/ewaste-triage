"""Contracts for the product-only Apple Silicon macOS package."""

from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import sqlite3
import subprocess
import sys
import xml.etree.ElementTree as ElementTree

import pytest

from server.reference_db import ReferenceStore, compile_reference


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "packaging" / "EWasteTriage.spec"
BUILD_SCRIPT = ROOT / "scripts" / "build_macos_app.sh"
CANONICAL_LABELS = [
    "0301_computer_mouse",
    "0301_keyboard",
    "0303_laptop",
    "0306_mobile_phone",
    "0401_headphones",
]
PRODUCT_STATIC_ASSETS = (
    "app.css",
    "app.js",
    "index.html",
    "phone.css",
    "phone.html",
    "phone.js",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assignment(path: Path, name: str):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                return ast.literal_eval(node.value)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} is not a literal assignment in {path}")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _write_release_stage(root: Path, *, version: str = "1.2.3") -> Path:
    release = root / "release"
    model_dir = release / "model"
    model_dir.mkdir(parents=True)
    model = model_dir / "model.onnx"
    model.write_bytes(b"approved onnx model")
    model_sha = _sha256(model)
    parity_metrics = {
        "reference_images": 5,
        "top1_matches": 5,
        "max_probability_delta": 0.0,
    }
    model_manifest_path = model_dir / "manifest.json"
    _write_json(
        model_manifest_path,
        {
            "model_id": "release-model-1",
            "architecture": "test-onnx",
            "classes": CANONICAL_LABELS,
            "preprocessing_version": "rgb-224-v1",
            "confidence_floor": 0.6,
            "schema_version": 1,
            "artifact_sha256": model_sha,
            "metrics": {"parity": parity_metrics},
        },
    )
    labels = release / "labels.json"
    labels.write_text(json.dumps(CANONICAL_LABELS, separators=(",", ":")) + "\n")
    components = release / "components.sqlite"
    component_manifest = compile_reference(ROOT / "reference", components)
    parity = {
        "schema_version": 1,
        "status": "passed",
        "model_id": "release-model-1",
        "model_sha256": model_sha,
        "labels": CANONICAL_LABELS,
        "metrics": parity_metrics,
        "holdout": {
            "status": "passed",
            "split": "holdout",
            "valid": True,
            "overlaps_training": False,
            "samples": 25,
        },
    }
    _write_json(release / "parity-report.json", parity)
    _write_json(
        release / "release-manifest.json",
        {
            "schema_version": 1,
            "app_version": version,
            "model": {
                "model_id": "release-model-1",
                "artifact_sha256": model_sha,
                "manifest_sha256": _sha256(model_manifest_path),
                "labels_sha256": _sha256(labels),
                "schema_version": 1,
            },
            "components": {
                "sha256": _sha256(components),
                "content_sha256": component_manifest.content_sha256,
                "schema_version": component_manifest.schema_version,
                "version": component_manifest.version,
            },
            "target": {"architecture": "arm64", "minimum_macos": "14.0"},
            "created_at": "2026-09-06T12:00:00+00:00",
            "parity": parity,
        },
    )
    return release


def _write_app_bundle(root: Path, release: Path) -> Path:
    app = root / "E-Waste Triage.app"
    contents = app / "Contents"
    resources = contents / "Resources"
    executable = contents / "MacOS" / "E-Waste Triage"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"synthetic mach-o")
    executable.chmod(0o755)
    with (contents / "Info.plist").open("wb") as handle:
        plistlib.dump(
            {
                "CFBundleDisplayName": "E-Waste Triage",
                "CFBundleName": "E-Waste Triage",
                "CFBundleIdentifier": "com.ewastetriage.desktop",
                "CFBundleExecutable": "E-Waste Triage",
                "CFBundleShortVersionString": "1.2.3",
                "LSMinimumSystemVersion": "14.0",
                "LSApplicationCategoryType": "public.app-category.utilities",
                "NSCameraUsageDescription": (
                    "E-Waste Triage uses the camera only when you choose to capture a device photo."
                ),
                "NSLocalNetworkUsageDescription": (
                    "E-Waste Triage connects to your phone on the local network only during a capture session."
                ),
            },
            handle,
        )

    mappings = {
        "model/model.onnx": "models/production/model.onnx",
        "model/manifest.json": "models/production/manifest.json",
        "components.sqlite": "reference/components.sqlite",
        "labels.json": "release/labels.json",
        "parity-report.json": "release/parity-report.json",
        "release-manifest.json": "release/release-manifest.json",
    }
    for source_name, destination_name in mappings.items():
        destination = resources / destination_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(release / source_name, destination)
    for filename in PRODUCT_STATIC_ASSETS:
        path = resources / "server" / "static" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"product asset: {filename}\n")
    _write_json(
        resources / "build-metadata.json",
        {
            "schema_version": 1,
            "app_version": "1.2.3",
            "source_revision": "a" * 40,
            "release_manifest_sha256": _sha256(release / "release-manifest.json"),
        },
    )
    return app


def _arm64_lipo(command, **kwargs):
    assert command[:2] == ["/usr/bin/lipo", "-info"]
    assert kwargs == {"capture_output": True, "text": True}
    return subprocess.CompletedProcess(command, 0, "Non-fat file is architecture: arm64\n", "")


def test_spec_has_stable_product_identity_and_arm64_macos_contract():
    text = SPEC.read_text(encoding="utf-8")

    assert _assignment(SPEC, "PRODUCT_NAME") == "E-Waste Triage"
    assert _assignment(SPEC, "BUNDLE_IDENTIFIER") == "com.ewastetriage.desktop"
    assert _assignment(SPEC, "TARGET_ARCHITECTURE") == "arm64"
    assert _assignment(SPEC, "MINIMUM_MACOS_VERSION") == "14.0"
    assert _assignment(SPEC, "BUNDLE_VERSION_PATTERN") == r"[0-9]+\.[0-9]+\.[0-9]+"
    assert "desktop/main.py" in text
    assert "console=False" in text
    assert "codesign_identity=None" in text


def test_spec_uses_explicit_product_static_and_release_asset_allowlists():
    static_assets = _assignment(SPEC, "PRODUCT_STATIC_ASSETS")
    release_assets = _assignment(SPEC, "RELEASE_DATA_FILES")

    assert static_assets == PRODUCT_STATIC_ASSETS
    assert release_assets == (
        ("model/model.onnx", "models/production"),
        ("model/manifest.json", "models/production"),
        ("components.sqlite", "reference"),
        ("labels.json", "release"),
        ("parity-report.json", "release"),
        ("release-manifest.json", "release"),
    )
    assert "collect.html" not in SPEC.read_text(encoding="utf-8")


def test_spec_collects_the_release_metadata_runtime_without_copying_metadata():
    hidden_imports = _assignment(SPEC, "HIDDEN_IMPORTS")
    release_assets = _assignment(SPEC, "RELEASE_DATA_FILES")

    assert "desktop.release_metadata" in hidden_imports
    assert [source for source, _destination in release_assets if "metadata" in source] == []


def test_spec_excludes_admin_training_and_test_modules():
    from scripts.verify_macos_bundle import FORBIDDEN_PYTHON_MODULE_PREFIXES

    excluded = set(_assignment(SPEC, "EXCLUDED_MODULES"))

    assert {
        "scripts",
        "server.app",
        "server.classifier",
        "tests",
        "torch",
        "torchvision",
    } <= excluded
    assert set(FORBIDDEN_PYTHON_MODULE_PREFIXES) == excluded


def test_onnx_runtime_import_graph_does_not_load_training_frameworks():
    script = """
import builtins
import sys

original_import = builtins.__import__

def reject_training_frameworks(name, *args, **kwargs):
    if name.partition('.')[0] in {'torch', 'torchvision'}:
        raise AssertionError(f'packaged runtime imported {name}')
    return original_import(name, *args, **kwargs)

builtins.__import__ = reject_training_frameworks
import server.inference
assert not ({'torch', 'torchvision'} & set(sys.modules))
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr


def test_spec_declares_required_macos_plist_purpose_strings():
    info = _assignment(SPEC, "INFO_PLIST")

    assert info["LSMinimumSystemVersion"] == "14.0"
    assert info["LSApplicationCategoryType"] == "public.app-category.utilities"
    assert "camera" in info["NSCameraUsageDescription"].lower()
    assert "local network" in info["NSLocalNetworkUsageDescription"].lower()


def test_icon_source_is_self_contained_product_vector():
    icon = ROOT / "desktop" / "assets" / "app-icon.svg"
    root = ElementTree.parse(icon).getroot()
    text = icon.read_text(encoding="utf-8")

    assert root.attrib["viewBox"] == "0 0 1024 1024"
    assert "#171C1B" in text
    assert "#24C985" in text
    assert "#FFFFFF" in text
    assert "<image" not in text
    assert "href=" not in text


def test_entitlements_are_minimal_and_do_not_enable_app_sandbox():
    with (ROOT / "packaging" / "entitlements.plist").open("rb") as handle:
        entitlements = plistlib.load(handle)

    assert entitlements == {
        "com.apple.security.device.camera": True,
        "com.apple.security.network.client": True,
        "com.apple.security.network.server": True,
    }


def test_icon_renderer_emits_complete_iconset_and_uses_system_iconutil(tmp_path):
    from scripts.render_app_icon import ICONSET_FILES, render_icon

    svg = tmp_path / "icon.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    output = tmp_path / "E-WasteTriage.icns"
    calls = []

    def fake_run(command, *, check):
        calls.append(command)
        if command[0] == "/usr/bin/sips":
            Path(command[-1]).write_bytes(b"png")
        elif command[0] == "/usr/bin/iconutil":
            Path(command[-1]).write_bytes(b"icns")
        return subprocess.CompletedProcess(command, 0)

    assert render_icon(svg, output, runner=fake_run) == output
    assert output.read_bytes() == b"icns"
    assert len([call for call in calls if call[0] == "/usr/bin/sips"]) == 10
    assert {Path(call[-1]).name for call in calls[:-1]} == set(ICONSET_FILES)
    assert calls[-1][0:3] == ["/usr/bin/iconutil", "-c", "icns"]


def test_release_stage_verifier_accepts_closed_checksummed_manifest(tmp_path):
    from scripts.verify_macos_bundle import validate_release_stage

    release = _write_release_stage(tmp_path)

    manifest = validate_release_stage(release, expected_version="1.2.3")

    assert manifest["target"] == {"architecture": "arm64", "minimum_macos": "14.0"}


def test_release_stage_verifier_rejects_non_numeric_macos_bundle_version(tmp_path):
    from scripts.verify_macos_bundle import BundleVerificationError, validate_release_stage

    release = _write_release_stage(tmp_path, version="1.2.3-beta.1")

    with pytest.raises(BundleVerificationError, match="three period-separated integers"):
        validate_release_stage(release)


def test_release_stage_verifier_rejects_missing_manifest(tmp_path):
    from scripts.verify_macos_bundle import BundleVerificationError, validate_release_stage

    release = tmp_path / "release"
    release.mkdir()

    with pytest.raises(BundleVerificationError, match="release-manifest.json"):
        validate_release_stage(release)


def test_release_stage_verifier_rejects_unknown_manifest_fields(tmp_path):
    from scripts.verify_macos_bundle import BundleVerificationError, validate_release_stage

    release = _write_release_stage(tmp_path)
    manifest_path = release / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["admin_checkpoint"] = "models/best.pt"
    _write_json(manifest_path, manifest)

    with pytest.raises(BundleVerificationError, match="additional propert|unknown field"):
        validate_release_stage(release)


@pytest.mark.parametrize("invalid_const", ("schema_boolean", "overlap_integer"))
def test_release_schema_const_rejects_boolean_integer_aliases(tmp_path, invalid_const):
    from scripts.verify_macos_bundle import BundleVerificationError, validate_release_stage

    release = _write_release_stage(tmp_path)
    manifest_path = release / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if invalid_const == "schema_boolean":
        manifest["schema_version"] = True
    else:
        manifest["parity"]["holdout"]["overlaps_training"] = 0
        parity_path = release / "parity-report.json"
        parity = json.loads(parity_path.read_text())
        parity["holdout"]["overlaps_training"] = 0
        _write_json(parity_path, parity)
    _write_json(manifest_path, manifest)

    with pytest.raises(BundleVerificationError, match="must equal"):
        validate_release_stage(release)


def test_release_stage_verifier_rejects_asset_checksum_mismatch(tmp_path):
    from scripts.verify_macos_bundle import BundleVerificationError, validate_release_stage

    release = _write_release_stage(tmp_path)
    (release / "model" / "model.onnx").write_bytes(b"tampered")

    with pytest.raises(BundleVerificationError, match="model.*checksum"):
        validate_release_stage(release)


def test_release_stage_verifier_rejects_logically_tampered_component_database(
    tmp_path,
):
    from scripts.verify_macos_bundle import BundleVerificationError, validate_release_stage

    release = _write_release_stage(tmp_path)
    database = release / "components.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE rules SET text = text || ' tampered' WHERE rule_id = 'li_ion_no_household_trash'"
        )
    manifest_path = release / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["components"]["sha256"] = _sha256(database)
    _write_json(manifest_path, manifest)

    with pytest.raises(BundleVerificationError, match="component database"):
        validate_release_stage(release)


def test_release_stage_verifier_rejects_tampered_model_manifest_bytes(tmp_path):
    from scripts.verify_macos_bundle import BundleVerificationError, validate_release_stage

    release = _write_release_stage(tmp_path)
    manifest_path = release / "model" / "manifest.json"
    model_manifest = json.loads(manifest_path.read_text())
    model_manifest["confidence_floor"] = 0.75
    _write_json(manifest_path, model_manifest)

    with pytest.raises(BundleVerificationError, match="model manifest.*checksum"):
        validate_release_stage(release)


@pytest.mark.parametrize(
    ("change", "message"),
    (
        ({"confidence_floor": 1.1}, "confidence_floor"),
        ({"preprocessing_version": "rgb-999-v9"}, "preprocessing"),
        (
            {
                "metrics": {
                    "parity": {
                        "reference_images": 5,
                        "top1_matches": 4,
                        "max_probability_delta": 0.0,
                    }
                }
            },
            "parity metrics",
        ),
    ),
)
def test_release_stage_verifier_revalidates_runtime_model_manifest(
    tmp_path, change, message
):
    from scripts.verify_macos_bundle import BundleVerificationError, validate_release_stage

    release = _write_release_stage(tmp_path)
    model_manifest_path = release / "model" / "manifest.json"
    model_manifest = json.loads(model_manifest_path.read_text())
    model_manifest.update(change)
    _write_json(model_manifest_path, model_manifest)
    release_manifest_path = release / "release-manifest.json"
    release_manifest = json.loads(release_manifest_path.read_text())
    release_manifest["model"]["manifest_sha256"] = _sha256(model_manifest_path)
    _write_json(release_manifest_path, release_manifest)

    with pytest.raises(BundleVerificationError, match=message):
        validate_release_stage(release)


def test_release_stage_verifier_rejects_boolean_model_parity_metric_aliases(tmp_path):
    from scripts.verify_macos_bundle import BundleVerificationError, validate_release_stage

    release = _write_release_stage(tmp_path)
    model_manifest_path = release / "model" / "manifest.json"
    model_manifest = json.loads(model_manifest_path.read_text())
    model_manifest["metrics"]["parity"] = {
        "reference_images": True,
        "top1_matches": True,
        "max_probability_delta": False,
    }
    _write_json(model_manifest_path, model_manifest)
    release_manifest_path = release / "release-manifest.json"
    release_manifest = json.loads(release_manifest_path.read_text())
    release_manifest["model"]["manifest_sha256"] = _sha256(model_manifest_path)
    _write_json(release_manifest_path, release_manifest)

    with pytest.raises(BundleVerificationError, match="parity metrics"):
        validate_release_stage(release)


def test_bundle_verifier_checks_plist_architecture_assets_and_checksums(tmp_path):
    from scripts.verify_macos_bundle import verify_macos_bundle

    release = _write_release_stage(tmp_path / "stage")
    app = _write_app_bundle(tmp_path, release)

    manifest = verify_macos_bundle(
        app,
        release,
        expected_version="1.2.3",
        runner=_arm64_lipo,
        archive_reader=lambda _path: ["desktop.main", "server.desktop_app"],
    )

    assert manifest["model"]["model_id"] == "release-model-1"


@pytest.mark.parametrize(
    "forbidden_path",
    (
        "Contents/Resources/data/photos/train/device.jpg",
        "Contents/Resources/models/best.pt",
        "Contents/Resources/scripts/train_classifier.py",
        "Contents/Resources/tests/test_server.py",
        "Contents/Resources/server/static/collect.html",
        "Contents/Resources/docs/training-reports/result.md",
    ),
)
def test_bundle_verifier_rejects_forbidden_product_content(tmp_path, forbidden_path):
    from scripts.verify_macos_bundle import BundleVerificationError, verify_macos_bundle

    release = _write_release_stage(tmp_path / "stage")
    app = _write_app_bundle(tmp_path, release)
    forbidden = app / forbidden_path
    forbidden.parent.mkdir(parents=True, exist_ok=True)
    forbidden.write_bytes(b"must not ship")

    with pytest.raises(BundleVerificationError, match="forbidden"):
        verify_macos_bundle(app, release, runner=_arm64_lipo)


def test_bundle_verifier_rejects_non_arm64_executable(tmp_path):
    from scripts.verify_macos_bundle import BundleVerificationError, verify_macos_bundle

    release = _write_release_stage(tmp_path / "stage")
    app = _write_app_bundle(tmp_path, release)

    def intel_lipo(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, "architecture: x86_64\n", "")

    with pytest.raises(BundleVerificationError, match="arm64"):
        verify_macos_bundle(app, release, runner=intel_lipo)


@pytest.mark.parametrize(
    "module_name",
    (
        "scripts.train_classifier",
        "server.app",
        "server.app.admin",
        "server.classifier",
        "tests.test_server",
        "torch",
        "torch.nn",
        "torchvision.models",
    ),
)
def test_bundle_verifier_rejects_forbidden_embedded_python_modules(tmp_path, module_name):
    from scripts.verify_macos_bundle import BundleVerificationError, _verify_python_archive

    executable = tmp_path / "E-Waste Triage"
    executable.write_bytes(b"synthetic executable")

    with pytest.raises(BundleVerificationError, match="forbidden Python module"):
        _verify_python_archive(executable, archive_reader=lambda _path: [module_name])


@pytest.mark.parametrize("manifest_text", (None, "{not-json"))
def test_build_script_refuses_missing_or_invalid_release_before_creating_outputs(
    tmp_path, manifest_text
):
    release = tmp_path / "release"
    release.mkdir()
    if manifest_text is not None:
        (release / "release-manifest.json").write_text(manifest_text)
    build_base = tmp_path / "build"
    dist_dir = tmp_path / "dist"
    env = {
        **os.environ,
        "PYTHON_BIN": sys.executable,
        "EWASTE_BUILD_BASE": str(build_base),
        "EWASTE_DIST_DIR": str(dist_dir),
    }

    result = subprocess.run(
        [str(BUILD_SCRIPT), "--version", "1.2.3", "--release-dir", str(release)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "release-manifest.json" in result.stderr
    assert not build_base.exists()
    assert not dist_dir.exists()


def test_build_script_refuses_suffix_bundle_version_before_creating_outputs(tmp_path):
    build_base = tmp_path / "build"
    dist_dir = tmp_path / "dist"
    env = {
        **os.environ,
        "PYTHON_BIN": sys.executable,
        "EWASTE_BUILD_BASE": str(build_base),
        "EWASTE_DIST_DIR": str(dist_dir),
    }

    result = subprocess.run(
        [str(BUILD_SCRIPT), "--version", "1.2.3-beta.1", "--release-dir", str(tmp_path)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "three period-separated integers" in result.stderr
    assert not build_base.exists()
    assert not dist_dir.exists()


@pytest.mark.parametrize("dirty_kind", ("tracked", "untracked", "staged"))
def test_build_script_refuses_dirty_source_before_creating_outputs(tmp_path, dirty_kind):
    project = tmp_path / "project"
    (project / "scripts").mkdir(parents=True)
    (project / "packaging").mkdir()
    shutil.copy2(BUILD_SCRIPT, project / "scripts" / BUILD_SCRIPT.name)
    shutil.copy2(
        ROOT / "scripts" / "verify_macos_bundle.py",
        project / "scripts" / "verify_macos_bundle.py",
    )
    shutil.copy2(
        ROOT / "packaging" / "release-manifest.schema.json",
        project / "packaging" / "release-manifest.schema.json",
    )
    (project / "server").mkdir()
    for filename in ("__init__.py", "imaging.py", "model_bundle.py", "reference_db.py"):
        shutil.copy2(ROOT / "server" / filename, project / "server" / filename)
    subprocess.run(["/usr/bin/git", "init", "-q", str(project)], check=True)
    subprocess.run(["/usr/bin/git", "-C", str(project), "add", "."], check=True)
    subprocess.run(
        [
            "/usr/bin/git",
            "-C",
            str(project),
            "-c",
            "user.name=Packaging Contract",
            "-c",
            "user.email=packaging@example.invalid",
            "commit",
            "-qm",
            "test fixture",
        ],
        check=True,
    )
    if dirty_kind == "tracked":
        with (project / "scripts" / "verify_macos_bundle.py").open("a", encoding="utf-8") as handle:
            handle.write("\n# uncommitted source change\n")
    else:
        dirty_source = project / "server" / "uncommitted.py"
        dirty_source.write_text("SHOULD_NOT_SHIP = True\n", encoding="utf-8")
        if dirty_kind == "staged":
            subprocess.run(
                ["/usr/bin/git", "-C", str(project), "add", str(dirty_source)],
                check=True,
            )

    release = _write_release_stage(tmp_path / "stage")
    build_base = tmp_path / "build"
    dist_dir = tmp_path / "dist"
    env = {
        **os.environ,
        "PYTHON_BIN": sys.executable,
        "EWASTE_BUILD_BASE": str(build_base),
        "EWASTE_DIST_DIR": str(dist_dir),
    }
    result = subprocess.run(
        [
            str(project / "scripts" / BUILD_SCRIPT.name),
            "--version",
            "1.2.3",
            "--release-dir",
            str(release),
        ],
        cwd=project,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "source tree must be clean" in result.stderr
    assert not build_base.exists()
    assert not dist_dir.exists()


def test_build_script_uses_clean_tools_and_emits_versioned_unsigned_distribution():
    text = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert "set -euo pipefail" in text
    assert text.index("--stage-only") < text.index("render_app_icon.py")
    assert "-m PyInstaller" in text
    assert "--clean" in text
    assert "--workpath" in text
    assert "/usr/bin/hdiutil" in text
    assert "E-Waste Triage-${VERSION}-arm64.dmg" in text
    assert "E-Waste Triage-${VERSION}-release-notes.md" in text
    assert "render_release_notes.py" in text
    assert "/usr/bin/shasum" in text
    assert "release_manifest_sha256" in text
    assert text.index("status --porcelain") < text.index("/bin/rm -rf")
    assert "codesign " not in text
    assert "notarytool" not in text


def test_release_notes_renderer_emits_the_human_release_identity(tmp_path):
    release = _write_release_stage(tmp_path)
    output = tmp_path / "E-Waste Triage-1.2.3-release-notes.md"

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "render_release_notes.py"),
            "--release-dir",
            str(release),
            "--version",
            "1.2.3",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    notes = output.read_text(encoding="utf-8")
    assert "# E-Waste Triage 1.2.3" in notes
    assert "- App version: `1.2.3`" in notes
    assert "- Model: `release-model-1` (`test-onnx`, schema `1`)" in notes
    assert "- Preprocessing: `rgb-224-v1`" in notes
    assert "- Component references: `2.0.0` (schema `2`)" in notes
    assert "- Target: Apple Silicon (`arm64`), macOS `14.0` or later" in notes
    assert "- ONNX parity: 5/5 top-1 matches" in notes
    assert "same-network HTTP and is not TLS-encrypted" in notes
    assert "Administrator training tools and training photos are not included" in notes


def test_release_notes_renderer_rejects_a_version_mismatch_without_output(tmp_path):
    release = _write_release_stage(tmp_path, version="1.2.3")
    output = tmp_path / "notes.md"

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "render_release_notes.py"),
            "--release-dir",
            str(release),
            "--version",
            "1.2.4",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    assert completed.returncode != 0
    assert "version" in completed.stderr.lower()
    assert not output.exists()


def test_app_and_build_dependencies_are_pinned_without_onnx_runtime_downgrade():
    requirements = set((ROOT / "requirements.txt").read_text().splitlines())
    app_requirements = set((ROOT / "requirements-app.txt").read_text().splitlines())

    assert {
        "pillow-heif==1.6.0",
        "psutil==7.0.0",
        "pywebview==6.2.1",
        "qrcode==8.2",
        "pyinstaller==6.22.2",
        "onnxruntime==1.29.0",
    } <= requirements
    assert {"psutil==7.0.0", "qrcode==8.2", "pywebview==6.2.1"} <= app_requirements
    assert not {"torch==2.13.0", "torchvision==0.28.0"} & app_requirements


def test_packaged_runtime_requirements_install_a_yaml_reader(tmp_path):
    runtime_site = tmp_path / "runtime-site"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-deps",
            "--target",
            str(runtime_site),
            "-r",
            str(ROOT / "requirements-app.txt"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = subprocess.run(
        [sys.executable, "-S", "-c", "import yaml; print(yaml.__version__)"],
        env=os.environ | {"PYTHONPATH": str(runtime_site)},
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "6.0.3"

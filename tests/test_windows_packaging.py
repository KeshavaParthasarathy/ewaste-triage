"""Behavioral checks for the portable Windows release verifier."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "scripts" / "verify_windows_bundle.py"
WORKFLOW = ROOT / ".github" / "workflows" / "windows-release.yml"
GIT_ATTRIBUTES = ROOT / ".gitattributes"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _windows_fixture(tmp_path: Path) -> tuple[Path, Path]:
    release = tmp_path / "release"
    model = release / "model" / "model.onnx"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"portable onnx fixture")
    model_manifest = release / "model" / "manifest.json"
    _write_json(model_manifest, {"model_id": "fixture", "schema_version": 1})
    labels = release / "labels.json"
    _write_json(labels, ["mouse", "keyboard"])
    components = release / "components.sqlite"
    components.write_bytes(b"sqlite fixture")
    parity = release / "parity-report.json"
    _write_json(parity, {"status": "passed"})
    manifest = {
        "schema_version": 1,
        "app_version": "0.1.0",
        "model": {
            "artifact_sha256": _sha256(model),
            "manifest_sha256": _sha256(model_manifest),
            "labels_sha256": _sha256(labels),
        },
        "components": {"sha256": _sha256(components)},
        "target": {
            "platform": "windows",
            "architecture": "x86_64",
            "minimum_version": "11",
        },
    }
    release_manifest = release / "release-manifest.json"
    _write_json(release_manifest, manifest)

    app = tmp_path / "E-Waste Triage"
    (app / "E-Waste Triage.exe").parent.mkdir(parents=True)
    (app / "E-Waste Triage.exe").write_bytes(b"MZ synthetic executable")
    resources = app / "_internal"
    mappings = {
        model: resources / "models/production/model.onnx",
        model_manifest: resources / "models/production/manifest.json",
        labels: resources / "release/labels.json",
        components: resources / "reference/components.sqlite",
        parity: resources / "release/parity-report.json",
        release_manifest: resources / "release/release-manifest.json",
    }
    for source, destination in mappings.items():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    _write_json(
        resources / "build-metadata.json",
        {
            "schema_version": 1,
            "app_version": "0.1.0",
            "source_revision": "a" * 40,
            "release_manifest_sha256": _sha256(release_manifest),
        },
    )
    for filename in ("index.html", "app.css", "app.js", "phone.html", "phone.css", "phone.js"):
        asset = resources / "server/static" / filename
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_text(filename, encoding="utf-8")
    return release, app


def _verify(release: Path, app: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(VERIFY),
            "--release-dir",
            str(release),
            "--app-dir",
            str(app),
            "--expected-version",
            "0.1.0",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def test_windows_verifier_accepts_complete_matching_onedir(tmp_path):
    release, app = _windows_fixture(tmp_path)

    result = _verify(release, app)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "Windows application bundle verified"


def test_windows_verifier_rejects_tampered_packaged_model(tmp_path):
    release, app = _windows_fixture(tmp_path)
    (app / "_internal/models/production/model.onnx").write_bytes(b"changed")

    result = _verify(release, app)

    assert result.returncode == 1
    assert "model artifact does not match" in result.stderr


def test_windows_verifier_rejects_wrong_release_target(tmp_path):
    release, app = _windows_fixture(tmp_path)
    for manifest_path in (
        release / "release-manifest.json",
        app / "_internal/release/release-manifest.json",
    ):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["target"]["architecture"] = "arm64"
        _write_json(manifest_path, manifest)
    build_path = app / "_internal/build-metadata.json"
    build = json.loads(build_path.read_text(encoding="utf-8"))
    build["release_manifest_sha256"] = _sha256(release / "release-manifest.json")
    _write_json(build_path, build)

    result = _verify(release, app)

    assert result.returncode == 1
    assert "Windows 11 x64" in result.stderr


def test_windows_workflow_runs_product_tests_without_training_dependencies():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "tests/test_assessment_api.py" in workflow
    assert "tests/test_desktop_api.py" not in workflow


def test_release_artifact_bytes_are_stable_on_windows_checkout():
    attributes = GIT_ATTRIBUTES.read_text(encoding="utf-8")

    assert "*.json text eol=lf" in attributes
    assert "*.onnx binary" in attributes
    assert "*.sqlite binary" in attributes

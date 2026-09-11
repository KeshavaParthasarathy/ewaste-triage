#!/usr/bin/env python3
"""Verify the small set of files required by the Windows desktop package."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Sequence


STATIC_FILES = ("app.css", "app.js", "index.html", "phone.css", "phone.html", "phone.js")
WINDOWS_TARGET = {
    "platform": "windows",
    "architecture": "x86_64",
    "minimum_version": "11",
}
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


class WindowsBundleError(ValueError):
    """The Windows one-directory package is incomplete or inconsistent."""


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise WindowsBundleError(f"unreadable JSON: {path.name}") from error
    if not isinstance(value, dict):
        raise WindowsBundleError(f"JSON object required: {path.name}")
    return value


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise WindowsBundleError(f"required file is missing: {path.name}") from error


def _expect_hash(actual_path: Path, expected: object, label: str) -> None:
    if not isinstance(expected, str) or _sha256(actual_path) != expected:
        raise WindowsBundleError(f"{label} does not match the release manifest")


def verify_windows_bundle(
    release_dir: Path, app_dir: Path, expected_version: str
) -> None:
    """Validate a built Windows one-directory application against its release data."""
    release_dir = Path(release_dir)
    app_dir = Path(app_dir)
    if VERSION.fullmatch(expected_version) is None:
        raise WindowsBundleError("expected version must use X.Y.Z")
    if not (app_dir / "E-Waste Triage.exe").is_file():
        raise WindowsBundleError("Windows executable is missing")

    source_manifest_path = release_dir / "release-manifest.json"
    packaged_manifest_path = app_dir / "release/release-manifest.json"
    if _sha256(source_manifest_path) != _sha256(packaged_manifest_path):
        raise WindowsBundleError("packaged release manifest does not match")
    manifest = _read_json(packaged_manifest_path)
    if manifest.get("app_version") != expected_version:
        raise WindowsBundleError("release version does not match")
    if manifest.get("target") != WINDOWS_TARGET:
        raise WindowsBundleError("release target must be Windows 11 x64")

    model = manifest.get("model")
    components = manifest.get("components")
    if not isinstance(model, dict) or not isinstance(components, dict):
        raise WindowsBundleError("release manifest is incomplete")
    _expect_hash(
        app_dir / "models/production/model.onnx",
        model.get("artifact_sha256"),
        "model artifact",
    )
    _expect_hash(
        app_dir / "models/production/manifest.json",
        model.get("manifest_sha256"),
        "model manifest",
    )
    _expect_hash(
        app_dir / "release/labels.json", model.get("labels_sha256"), "labels"
    )
    _expect_hash(
        app_dir / "reference/components.sqlite",
        components.get("sha256"),
        "component database",
    )

    build = _read_json(app_dir / "build-metadata.json")
    if build.get("app_version") != expected_version:
        raise WindowsBundleError("build version does not match")
    if build.get("release_manifest_sha256") != _sha256(packaged_manifest_path):
        raise WindowsBundleError("build metadata does not anchor the release manifest")
    for filename in STATIC_FILES:
        if not (app_dir / "server/static" / filename).is_file():
            raise WindowsBundleError(f"product UI asset is missing: {filename}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-dir", required=True, type=Path)
    parser.add_argument("--app-dir", required=True, type=Path)
    parser.add_argument("--expected-version", required=True)
    arguments = parser.parse_args(argv)
    try:
        verify_windows_bundle(
            arguments.release_dir, arguments.app_dir, arguments.expected_version
        )
    except WindowsBundleError as error:
        parser.exit(1, f"error: {error}\n")
    print("Windows application bundle verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

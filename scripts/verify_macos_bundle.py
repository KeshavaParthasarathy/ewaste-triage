#!/usr/bin/env python3
"""Fail closed when a staged release or macOS application bundle drifts."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import plistlib
import re
import subprocess
import sys
from typing import Any, Callable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.imaging import SUPPORTED_PREPROCESSING_VERSION
from server.model_bundle import ModelBundleError, load_model_bundle


RELEASE_SCHEMA = ROOT / "packaging" / "release-manifest.schema.json"
PRODUCT_NAME = "E-Waste Triage"
BUNDLE_IDENTIFIER = "com.ewastetriage.desktop"
TARGET_ARCHITECTURE = "arm64"
MINIMUM_MACOS_VERSION = "14.0"
PRODUCT_STATIC_ASSETS = frozenset(
    {"app.css", "app.js", "index.html", "phone.css", "phone.html", "phone.js"}
)
RELEASE_RESOURCE_FILES = {
    "model/model.onnx": "models/production/model.onnx",
    "model/manifest.json": "models/production/manifest.json",
    "components.sqlite": "reference/components.sqlite",
    "labels.json": "release/labels.json",
    "parity-report.json": "release/parity-report.json",
    "release-manifest.json": "release/release-manifest.json",
}
BUILD_METADATA_FIELDS = frozenset(
    {"schema_version", "app_version", "source_revision", "release_manifest_sha256"}
)
FORBIDDEN_PYTHON_MODULE_PREFIXES = (
    "scripts",
    "server.app",
    "server.classifier",
    "tests",
    "torch",
    "torchvision",
)
_BUNDLE_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
_SOURCE_REVISION = re.compile(r"[0-9a-f]{40}")


class BundleVerificationError(ValueError):
    """A staged release or packaged application violates its release contract."""


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON value {token}")
            ),
        )
    except (OSError, UnicodeError, ValueError) as error:
        raise BundleVerificationError(f"{label} is missing or malformed: {path}") from error
    if not isinstance(value, dict):
        raise BundleVerificationError(f"{label} must be a JSON object: {path}")
    return value


def _schema_type_matches(value: object, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    raise BundleVerificationError(f"release schema uses unsupported type {expected!r}")


def _json_equal(value: object, expected: object) -> bool:
    """Compare values using JSON Schema equality rather than Python coercion."""
    if isinstance(value, bool) or isinstance(expected, bool):
        return isinstance(value, bool) and isinstance(expected, bool) and value is expected
    if isinstance(value, (int, float)) or isinstance(expected, (int, float)):
        return (
            isinstance(value, (int, float))
            and isinstance(expected, (int, float))
            and value == expected
        )
    if isinstance(value, (list, tuple)) or isinstance(expected, (list, tuple)):
        return (
            isinstance(value, (list, tuple))
            and isinstance(expected, (list, tuple))
            and len(value) == len(expected)
            and all(_json_equal(left, right) for left, right in zip(value, expected))
        )
    if isinstance(value, Mapping) or isinstance(expected, Mapping):
        return (
            isinstance(value, Mapping)
            and isinstance(expected, Mapping)
            and set(value) == set(expected)
            and all(_json_equal(value[key], expected[key]) for key in value)
        )
    return type(value) is type(expected) and value == expected


def _validate_schema(value: object, schema: Mapping[str, Any], path: str = "$") -> None:
    if "const" in schema and not _json_equal(value, schema["const"]):
        raise BundleVerificationError(f"{path} must equal {schema['const']!r}")

    expected_type = schema.get("type")
    if expected_type is not None and not _schema_type_matches(value, expected_type):
        raise BundleVerificationError(f"{path} must have JSON type {expected_type}")

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        missing = sorted(set(required) - set(value))
        if missing:
            raise BundleVerificationError(f"{path} is missing required fields: {missing}")
        if schema.get("additionalProperties") is False:
            unknown = sorted(set(value) - set(properties))
            if unknown:
                raise BundleVerificationError(f"{path} has unknown fields/additional properties: {unknown}")
        for name, child in value.items():
            if name in properties:
                _validate_schema(child, properties[name], f"{path}.{name}")

    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            raise BundleVerificationError(f"{path} is shorter than its minimum length")
        pattern = schema.get("pattern")
        if pattern is not None and re.fullmatch(pattern, value) is None:
            raise BundleVerificationError(f"{path} does not match {pattern!r}")
        if schema.get("format") == "date-time":
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as error:
                raise BundleVerificationError(f"{path} is not an ISO-8601 date-time") from error
            if parsed.tzinfo is None:
                raise BundleVerificationError(f"{path} date-time must include a timezone")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            raise BundleVerificationError(f"{path} must be finite")
        if "minimum" in schema and value < schema["minimum"]:
            raise BundleVerificationError(f"{path} is below its minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise BundleVerificationError(f"{path} exceeds its maximum")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as error:
        raise BundleVerificationError(f"required file is missing or unreadable: {path}") from error
    return digest.hexdigest()


def _resolve_release_directory(release_dir: Path) -> Path:
    try:
        resolved = Path(release_dir).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise BundleVerificationError(f"release directory is missing: {release_dir}") from error
    if not resolved.is_dir():
        raise BundleVerificationError(f"release directory is not a directory: {resolved}")
    return resolved


def _validate_runtime_model_bundle(
    bundle_dir: Path,
    release_manifest: Mapping[str, Any],
    *,
    label: str,
) -> None:
    model_release = release_manifest["model"]
    manifest_path = bundle_dir / "manifest.json"
    actual_manifest_sha = _sha256_file(manifest_path)
    if actual_manifest_sha != model_release["manifest_sha256"]:
        raise BundleVerificationError(
            f"{label} model manifest checksum mismatch: expected "
            f"{model_release['manifest_sha256']}, got {actual_manifest_sha}"
        )
    try:
        model_manifest, _ = load_model_bundle(bundle_dir)
    except ModelBundleError as error:
        raise BundleVerificationError(
            f"{label} model bundle validation failed: {error}"
        ) from error

    if model_manifest.preprocessing_version != SUPPORTED_PREPROCESSING_VERSION:
        raise BundleVerificationError(
            f"{label} model preprocessing_version is unsupported"
        )
    if model_manifest.model_id != model_release["model_id"]:
        raise BundleVerificationError(f"{label} model_id does not match release manifest")
    if model_manifest.schema_version != model_release["schema_version"]:
        raise BundleVerificationError(
            f"{label} model schema_version does not match release manifest"
        )
    if model_manifest.artifact_sha256 != model_release["artifact_sha256"]:
        raise BundleVerificationError(
            f"{label} model artifact checksum does not match release manifest"
        )
    if model_manifest.classes != tuple(release_manifest["parity"]["labels"]):
        raise BundleVerificationError(f"{label} model classes do not match release labels")
    model_parity = model_manifest.metrics.get("parity")
    if not isinstance(model_parity, Mapping) or not _json_equal(
        model_parity, release_manifest["parity"]["metrics"]
    ):
        raise BundleVerificationError(
            f"{label} model parity metrics do not match release manifest"
        )


def _assert_closed_release_files(release_dir: Path) -> None:
    expected = set(RELEASE_RESOURCE_FILES)
    actual: set[str] = set()
    for entry in release_dir.rglob("*"):
        if entry.is_symlink():
            try:
                entry.resolve(strict=True).relative_to(release_dir)
            except (OSError, RuntimeError, ValueError) as error:
                raise BundleVerificationError(f"release asset escapes its stage: {entry}") from error
        if entry.is_file():
            actual.add(entry.relative_to(release_dir).as_posix())
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing:
        raise BundleVerificationError(f"release stage is missing required files: {missing}")
    if unknown:
        raise BundleVerificationError(f"release stage has forbidden extra files: {unknown}")


def validate_release_stage(
    release_dir: Path,
    *,
    expected_version: str | None = None,
) -> dict[str, Any]:
    """Validate the closed staged layout and return its release manifest."""
    release_dir = _resolve_release_directory(release_dir)
    manifest_path = release_dir / "release-manifest.json"
    manifest = _read_json(manifest_path, "release-manifest.json")
    schema = _read_json(RELEASE_SCHEMA, "release manifest schema")
    _validate_schema(manifest, schema)
    if _BUNDLE_VERSION.fullmatch(manifest["app_version"]) is None:
        raise BundleVerificationError(
            "release app_version must contain three period-separated integers"
        )
    _assert_closed_release_files(release_dir)

    if expected_version is not None and manifest["app_version"] != expected_version:
        raise BundleVerificationError(
            f"release app version {manifest['app_version']!r} does not match {expected_version!r}"
        )

    checksums = {
        "model artifact": (
            release_dir / "model" / "model.onnx",
            manifest["model"]["artifact_sha256"],
        ),
        "model manifest": (
            release_dir / "model" / "manifest.json",
            manifest["model"]["manifest_sha256"],
        ),
        "labels": (release_dir / "labels.json", manifest["model"]["labels_sha256"]),
        "component database": (
            release_dir / "components.sqlite",
            manifest["components"]["sha256"],
        ),
    }
    for label, (path, expected) in checksums.items():
        actual = _sha256_file(path)
        if actual != expected:
            raise BundleVerificationError(
                f"{label} checksum mismatch: expected {expected}, got {actual}"
            )

    parity = _read_json(release_dir / "parity-report.json", "parity-report.json")
    if not _json_equal(parity, manifest["parity"]):
        raise BundleVerificationError("parity-report.json does not match release manifest parity")
    metrics = parity["metrics"]
    if metrics["top1_matches"] != metrics["reference_images"]:
        raise BundleVerificationError("parity top-1 results do not cover every reference image")
    if (
        parity["model_id"] != manifest["model"]["model_id"]
        or parity["model_sha256"] != manifest["model"]["artifact_sha256"]
    ):
        raise BundleVerificationError("parity report does not identify the released model")

    try:
        labels = json.loads((release_dir / "labels.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise BundleVerificationError("labels.json is missing or malformed") from error
    if labels != parity["labels"]:
        raise BundleVerificationError("labels.json does not match the approved parity labels")

    _validate_runtime_model_bundle(
        release_dir / "model",
        manifest,
        label="staged",
    )
    return manifest


def _read_plist(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            value = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException) as error:
        raise BundleVerificationError(f"Info.plist is missing or malformed: {path}") from error
    if not isinstance(value, dict):
        raise BundleVerificationError("Info.plist must contain a dictionary")
    return value


def _verify_plist(info: Mapping[str, Any], version: str) -> None:
    expected = {
        "CFBundleDisplayName": PRODUCT_NAME,
        "CFBundleName": PRODUCT_NAME,
        "CFBundleIdentifier": BUNDLE_IDENTIFIER,
        "CFBundleExecutable": PRODUCT_NAME,
        "CFBundleShortVersionString": version,
        "LSMinimumSystemVersion": MINIMUM_MACOS_VERSION,
        "LSApplicationCategoryType": "public.app-category.utilities",
    }
    for name, wanted in expected.items():
        if info.get(name) != wanted:
            raise BundleVerificationError(f"Info.plist {name} must equal {wanted!r}")
    for name, phrase in (
        ("NSCameraUsageDescription", "camera"),
        ("NSLocalNetworkUsageDescription", "local network"),
    ):
        value = info.get(name)
        if not isinstance(value, str) or phrase not in value.lower():
            raise BundleVerificationError(f"Info.plist {name} must explain {phrase} access")


def _verify_architecture(
    executable: Path,
    runner: Callable[..., subprocess.CompletedProcess],
) -> None:
    try:
        result = runner(
            ["/usr/bin/lipo", "-info", str(executable)],
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise BundleVerificationError("lipo could not inspect the packaged executable") from error
    output = f"{result.stdout or ''}\n{result.stderr or ''}"
    if result.returncode != 0:
        raise BundleVerificationError(f"lipo failed to inspect the packaged executable: {output.strip()}")
    if re.search(r"(?<![A-Za-z0-9_])arm64(?![A-Za-z0-9_])", output) is None:
        raise BundleVerificationError("packaged executable is not arm64")
    if re.search(r"(?<![A-Za-z0-9_])x86_64(?![A-Za-z0-9_])", output):
        raise BundleVerificationError("packaged executable contains forbidden x86_64 code")


def _verify_forbidden_content(app_bundle: Path) -> None:
    forbidden_patterns = (
        re.compile(r"(?:^|/)data/photos(?:/|$)"),
        re.compile(r"(?:^|/)models/best\.pt$"),
        re.compile(r"(?:^|/)scripts(?:/|$)"),
        re.compile(r"(?:^|/)tests(?:/|$)"),
        re.compile(r"(?:^|/)training-reports(?:/|$)"),
        re.compile(r"(?:^|/)collect\.html$"),
    )
    for entry in app_bundle.rglob("*"):
        relative = entry.relative_to(app_bundle).as_posix()
        if any(pattern.search(relative) for pattern in forbidden_patterns):
            raise BundleVerificationError(f"bundle contains forbidden product content: {relative}")


def _read_pyinstaller_archive(executable: Path) -> Sequence[str]:
    try:
        from PyInstaller.archive.readers import pkg_archive_contents
    except ImportError as error:
        raise BundleVerificationError(
            "the pinned PyInstaller build dependency is required to inspect the archive"
        ) from error
    try:
        return pkg_archive_contents(str(executable), recursive=True)
    except Exception as error:
        raise BundleVerificationError(
            f"could not inspect the PyInstaller archive: {executable}"
        ) from error


def _verify_python_archive(
    executable: Path,
    *,
    archive_reader: Callable[[Path], Sequence[str]] | None = None,
) -> None:
    reader = archive_reader or _read_pyinstaller_archive
    try:
        entries = reader(executable)
    except BundleVerificationError:
        raise
    except Exception as error:
        raise BundleVerificationError(
            f"could not inspect the PyInstaller archive: {executable}"
        ) from error
    if isinstance(entries, (str, bytes)):
        raise BundleVerificationError("PyInstaller archive contents must be a sequence of names")

    for raw_name in entries:
        if not isinstance(raw_name, str):
            raise BundleVerificationError("PyInstaller archive contains an invalid entry name")
        module_name = raw_name.replace("\\", ".").replace("/", ".").strip(".")
        for suffix in (".pyc", ".pyo", ".py"):
            if module_name.endswith(suffix):
                module_name = module_name[: -len(suffix)]
                break
        if any(
            module_name == prefix or module_name.startswith(f"{prefix}.")
            for prefix in FORBIDDEN_PYTHON_MODULE_PREFIXES
        ):
            raise BundleVerificationError(
                f"bundle contains forbidden Python module: {module_name}"
            )


def _verify_bundled_resources(resources: Path, release_dir: Path, manifest: Mapping[str, Any]) -> None:
    for source_name, destination_name in RELEASE_RESOURCE_FILES.items():
        source = release_dir / source_name
        destination = resources / destination_name
        if _sha256_file(destination) != _sha256_file(source):
            raise BundleVerificationError(f"bundled checksum mismatch for {destination_name}")

    static_dir = resources / "server" / "static"
    try:
        actual_static = {
            path.relative_to(static_dir).as_posix()
            for path in static_dir.rglob("*")
            if path.is_file()
        }
    except OSError as error:
        raise BundleVerificationError("bundled product static directory is unreadable") from error
    if actual_static != PRODUCT_STATIC_ASSETS:
        raise BundleVerificationError(
            f"bundled product static allowlist mismatch: {sorted(actual_static)}"
        )

    embedded_manifest = _read_json(
        resources / "release" / "release-manifest.json",
        "bundled release manifest",
    )
    if embedded_manifest != manifest:
        raise BundleVerificationError("bundled release manifest differs from staged manifest")

    _validate_runtime_model_bundle(
        resources / "models" / "production",
        manifest,
        label="bundled",
    )

    metadata = _read_json(resources / "build-metadata.json", "build metadata")
    if set(metadata) != BUILD_METADATA_FIELDS:
        raise BundleVerificationError("build metadata has unknown or missing fields")
    if metadata["schema_version"] != 1 or metadata["app_version"] != manifest["app_version"]:
        raise BundleVerificationError("build metadata version does not match release manifest")
    if not isinstance(metadata["source_revision"], str) or not _SOURCE_REVISION.fullmatch(
        metadata["source_revision"]
    ):
        raise BundleVerificationError("build metadata source_revision must be a full Git SHA")
    expected_manifest_sha = _sha256_file(release_dir / "release-manifest.json")
    if metadata["release_manifest_sha256"] != expected_manifest_sha:
        raise BundleVerificationError("build metadata release manifest checksum mismatch")


def verify_macos_bundle(
    app_bundle: Path,
    release_dir: Path,
    *,
    expected_version: str | None = None,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    archive_reader: Callable[[Path], Sequence[str]] | None = None,
) -> dict[str, Any]:
    """Verify identity, architecture, product contents, and staged checksums."""
    manifest = validate_release_stage(release_dir, expected_version=expected_version)
    try:
        app_bundle = Path(app_bundle).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise BundleVerificationError(f"application bundle is missing: {app_bundle}") from error
    if not app_bundle.is_dir() or app_bundle.suffix != ".app":
        raise BundleVerificationError(f"application bundle must be an existing .app: {app_bundle}")

    contents = app_bundle / "Contents"
    resources = contents / "Resources"
    executable = contents / "MacOS" / PRODUCT_NAME
    info = _read_plist(contents / "Info.plist")
    _verify_plist(info, manifest["app_version"])
    if not executable.is_file() or not executable.stat().st_mode & 0o111:
        raise BundleVerificationError(f"application executable is missing or not executable: {executable}")
    _verify_architecture(executable, runner)
    _verify_forbidden_content(app_bundle)
    _verify_python_archive(executable, archive_reader=archive_reader)
    _verify_bundled_resources(resources, _resolve_release_directory(release_dir), manifest)
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-dir", required=True, type=Path)
    parser.add_argument("--app", type=Path, help="application bundle to verify")
    parser.add_argument("--expected-version")
    parser.add_argument(
        "--stage-only",
        action="store_true",
        help="validate only the staged release before starting a package build",
    )
    arguments = parser.parse_args(argv)
    if arguments.stage_only and arguments.app is not None:
        parser.error("--stage-only cannot be combined with --app")
    if not arguments.stage_only and arguments.app is None:
        parser.error("--app is required unless --stage-only is used")
    try:
        if arguments.stage_only:
            validate_release_stage(
                arguments.release_dir,
                expected_version=arguments.expected_version,
            )
            print("Release stage verified")
        else:
            verify_macos_bundle(
                arguments.app,
                arguments.release_dir,
                expected_version=arguments.expected_version,
            )
            print("macOS application bundle verified")
    except BundleVerificationError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

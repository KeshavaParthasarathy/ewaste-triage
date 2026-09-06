"""Launch E-Waste Triage in a native pywebview window."""

from __future__ import annotations

import sys
import os
import json
import re
import hashlib

try:
    import webview
except ImportError:  # Keep module imports usable for service-only tests and tooling.
    webview = None

from desktop.paths import AppPaths
from desktop.server_thread import ServerThread
from server.history import HistoryStore
from server.inference import OnnxClassifier
from server.model_bundle import ModelBundleError
from server.reference_db import ReferenceStartupError, ReferenceStore
from flask import Flask
from onnxruntime.capi import onnxruntime_pybind11_state as ort_state


APP_VERSION = os.environ.get("EWASTE_TRIAGE_VERSION", "development")


class ModelStartupError(RuntimeError):
    """An expected failure while loading the packaged inference asset."""


class ReferenceDataStartupError(RuntimeError):
    """An expected failure while loading the packaged component reference data."""


_SAFE_DIAGNOSTIC = re.compile(r"[^A-Za-z0-9._ -]+")
_ONNX_STARTUP_ERRORS = (
    ort_state.EngineError,
    ort_state.Fail,
    ort_state.InvalidProtobuf,
)
_EXPECTED_MODEL_STARTUP_ERRORS = (ModelBundleError, *_ONNX_STARTUP_ERRORS)
_BUILD_METADATA_FIELDS = {
    "schema_version",
    "app_version",
    "source_revision",
    "release_manifest_sha256",
}
_RELEASE_MANIFEST_FIELDS = {
    "schema_version",
    "app_version",
    "model",
    "components",
    "target",
    "created_at",
    "parity",
}
_COMPONENT_RELEASE_FIELDS = {
    "sha256",
    "content_sha256",
    "schema_version",
    "version",
}


def _safe_diagnostic(value: object, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    value = _SAFE_DIAGNOSTIC.sub("-", value).strip(" .-")
    return value[:80] or fallback


def _read_build_version(resources_dir) -> str:
    try:
        metadata = json.loads((resources_dir / "build-metadata.json").read_text())
    except (FileNotFoundError, OSError, json.JSONDecodeError, UnicodeError):
        return APP_VERSION
    return _safe_diagnostic(metadata.get("app_version") if isinstance(metadata, dict) else None, APP_VERSION)


def _read_model_diagnostic(bundle_dir) -> str:
    try:
        manifest = json.loads((bundle_dir / "manifest.json").read_text())
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "unreadable"
    except (json.JSONDecodeError, UnicodeError):
        return "corrupt"
    if not isinstance(manifest, dict):
        return "corrupt"
    model_id = _safe_diagnostic(manifest.get("model_id"), "corrupt")
    schema = manifest.get("schema_version")
    if model_id == "corrupt" or not isinstance(schema, int):
        return "corrupt"
    return f"{model_id} (schema {schema})"


def _capture_cleanup_failure(action, previous_error):
    """Run teardown fully while preserving the exception that triggered it."""
    try:
        action()
    except BaseException as exc:
        return previous_error if previous_error is not None else exc
    return previous_error


def _packaged_component_expectations(paths: AppPaths) -> dict[str, object]:
    """Read the component contract only when it is anchored by build metadata."""
    try:
        metadata = json.loads(paths.build_metadata_path.read_text(encoding="utf-8"))
        manifest_bytes = paths.release_manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        if not isinstance(metadata, dict) or set(metadata) != _BUILD_METADATA_FIELDS:
            raise ValueError("invalid build metadata")
        if metadata["schema_version"] != 1:
            raise ValueError("unsupported build metadata")
        expected_manifest_sha = metadata["release_manifest_sha256"]
        if (
            not isinstance(expected_manifest_sha, str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected_manifest_sha)
            or hashlib.sha256(manifest_bytes).hexdigest() != expected_manifest_sha
        ):
            raise ValueError("release manifest is not anchored by build metadata")
        if not isinstance(manifest, dict) or set(manifest) != _RELEASE_MANIFEST_FIELDS:
            raise ValueError("invalid release manifest")
        if (
            manifest.get("schema_version") != 1
            or manifest.get("app_version") != metadata.get("app_version")
        ):
            raise ValueError("release manifest version mismatch")
        components = manifest.get("components")
        if not isinstance(components, dict) or set(components) != _COMPONENT_RELEASE_FIELDS:
            raise ValueError("invalid component release contract")
        for field in ("sha256", "content_sha256"):
            if not isinstance(components[field], str) or not re.fullmatch(
                r"[0-9a-f]{64}", components[field]
            ):
                raise ValueError("invalid component release hash")
        if (
            isinstance(components["schema_version"], bool)
            or not isinstance(components["schema_version"], int)
            or not isinstance(components["version"], str)
            or not components["version"].strip()
        ):
            raise ValueError("invalid component release version")
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ReferenceDataStartupError("unavailable or incompatible") from exc
    return {
        "expected_sha256": components["sha256"],
        "expected_content_sha256": components["content_sha256"],
        "expected_schema_version": components["schema_version"],
        "expected_version": components["version"],
    }


def build_desktop_app(
    paths: AppPaths, *, require_release_integrity: bool = False
):
    """Assemble the local Flask service from immutable resources and local data."""
    from server.desktop_app import create_desktop_app

    try:
        classifier = OnnxClassifier(paths.model_bundle_dir)
    except _EXPECTED_MODEL_STARTUP_ERRORS as exc:
        raise ModelStartupError(_read_model_diagnostic(paths.model_bundle_dir)) from exc
    try:
        expectations = (
            _packaged_component_expectations(paths)
            if require_release_integrity
            else {}
        )
        references = ReferenceStore(paths.reference_database_path, **expectations)
    except ReferenceStartupError as exc:
        raise ReferenceDataStartupError("unavailable or incompatible") from exc

    assembled = False
    try:
        app = create_desktop_app(
            classifier=classifier,
            history_store=HistoryStore(paths.history_database_path, paths.history_media_dir),
            static_dir=paths.static_dir,
            reference_store=references,
        )
        app.extensions["close_reference_store"] = references.close
        assembled = True
    finally:
        if not assembled:
            active_error = sys.exc_info()[1]
            cleanup_error = _capture_cleanup_failure(references.close, None)
            if active_error is None and cleanup_error is not None:
                raise cleanup_error
    return app


def build_recovery_app(*, app_version: str, model_diagnostic: str):
    app = Flask(__name__)

    @app.get("/")
    def recovery():
        return (
            "<!doctype html><title>E-Waste Triage recovery</title>"
            "<main><h1>Unable to start E-Waste Triage</h1>"
            "<p>The included model could not be loaded. Reinstall the app or contact support.</p>"
            f"<p>App version: {app_version} · Model bundle: {model_diagnostic}</p></main>"
        )

    return app


def build_reference_recovery_app(*, app_version: str, reference_diagnostic: str):
    app = Flask(__name__)

    @app.get("/")
    def recovery():
        return (
            "<!doctype html><title>E-Waste Triage recovery</title>"
            "<main><h1>Unable to start E-Waste Triage</h1>"
            "<p>The included component reference data could not be loaded. "
            "Reinstall the app or contact support.</p>"
            f"<p>App version: {app_version} · Reference database: "
            f"{reference_diagnostic}</p></main>"
        )

    return app


def run(*, webview_module=webview, paths: AppPaths | None = None) -> int:
    """Start the private service, then host it in one native app window."""
    if webview_module is None:
        raise RuntimeError("pywebview is required to launch the desktop application")

    frozen = bool(getattr(sys, "frozen", False))
    paths = paths or AppPaths.for_runtime(frozen)
    try:
        app = (
            build_desktop_app(paths, require_release_integrity=True)
            if frozen
            else build_desktop_app(paths)
        )
    except ModelStartupError as exc:
        app = build_recovery_app(
            app_version=_read_build_version(paths.resources_dir),
            model_diagnostic=str(exc),
        )
    except ReferenceDataStartupError as exc:
        app = build_reference_recovery_app(
            app_version=_read_build_version(paths.resources_dir),
            reference_diagnostic=str(exc),
        )
    server = None
    completed = False
    try:
        server = ServerThread(app)
        url = server.start_and_wait()
        webview_module.create_window("E-Waste Triage", url, min_size=(760, 620))
        webview_module.start(debug=False)
        completed = True
        return 0
    finally:
        cleanup_error = None
        if server is not None:
            cleanup_error = _capture_cleanup_failure(
                server.shutdown, cleanup_error
            )
        phone_closer = app.extensions.get("close_phone_capture")
        if phone_closer is not None:
            cleanup_error = _capture_cleanup_failure(
                phone_closer, cleanup_error
            )
        closer = app.extensions.get("close_reference_store")
        if closer is not None:
            cleanup_error = _capture_cleanup_failure(closer, cleanup_error)
        if completed and cleanup_error is not None:
            raise cleanup_error


if __name__ == "__main__":
    raise SystemExit(run())

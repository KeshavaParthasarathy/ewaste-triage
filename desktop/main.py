"""Launch E-Waste Triage in a native pywebview window."""

from __future__ import annotations

import sys
import os
import json
import re

try:
    import webview
except ImportError:  # Keep module imports usable for service-only tests and tooling.
    webview = None

from desktop.paths import AppPaths
from desktop.server_thread import ServerThread
from server.history import HistoryStore
from server.inference import OnnxClassifier
from server.model_bundle import ModelBundleError
from flask import Flask
from onnxruntime.capi import onnxruntime_pybind11_state as ort_state


APP_VERSION = os.environ.get("EWASTE_TRIAGE_VERSION", "development")


class ModelStartupError(RuntimeError):
    """An expected failure while loading the packaged inference asset."""


_SAFE_DIAGNOSTIC = re.compile(r"[^A-Za-z0-9._ -]+")
_ONNX_STARTUP_ERRORS = (
    ort_state.EngineError,
    ort_state.Fail,
    ort_state.InvalidProtobuf,
)


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


def build_desktop_app(paths: AppPaths):
    """Assemble the local Flask service from immutable resources and local data."""
    from server.desktop_app import create_desktop_app

    try:
        classifier = OnnxClassifier(paths.model_bundle_dir)
    except (ModelBundleError, OSError, RuntimeError, *_ONNX_STARTUP_ERRORS) as exc:
        raise ModelStartupError(_read_model_diagnostic(paths.model_bundle_dir)) from exc
    return create_desktop_app(
        classifier=classifier,
        history_store=HistoryStore(
            paths.history_database_path,
            paths.history_media_dir,
        ),
        static_dir=paths.static_dir,
    )


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


def run(*, webview_module=webview, paths: AppPaths | None = None) -> int:
    """Start the private service, then host it in one native app window."""
    if webview_module is None:
        raise RuntimeError("pywebview is required to launch the desktop application")

    paths = paths or AppPaths.for_runtime(getattr(sys, "frozen", False))
    try:
        app = build_desktop_app(paths)
    except ModelStartupError as exc:
        app = build_recovery_app(
            app_version=_read_build_version(paths.resources_dir),
            model_diagnostic=str(exc),
        )
    server = ServerThread(app)
    url = server.start_and_wait()
    try:
        webview_module.create_window("E-Waste Triage", url, min_size=(760, 620))
        webview_module.start(debug=False)
        return 0
    finally:
        server.shutdown()


if __name__ == "__main__":
    raise SystemExit(run())

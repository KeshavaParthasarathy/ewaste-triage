"""Launch E-Waste Triage in a native pywebview window."""

from __future__ import annotations

import sys
import os

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


APP_VERSION = os.environ.get("EWASTE_TRIAGE_VERSION", "development")


class ModelStartupError(RuntimeError):
    """An expected failure while loading the packaged inference asset."""


def build_desktop_app(paths: AppPaths):
    """Assemble the local Flask service from immutable resources and local data."""
    from server.desktop_app import create_desktop_app

    try:
        classifier = OnnxClassifier(paths.model_bundle_dir)
    except (ModelBundleError, OSError, RuntimeError) as exc:
        raise ModelStartupError("unavailable") from exc
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
            app_version=APP_VERSION,
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

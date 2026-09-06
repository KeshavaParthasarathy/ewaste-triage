"""Launch E-Waste Triage in a native pywebview window."""

from __future__ import annotations

import sys

try:
    import webview
except ImportError:  # Keep module imports usable for service-only tests and tooling.
    webview = None

from desktop.paths import AppPaths
from desktop.server_thread import ServerThread
from server.history import HistoryStore
from server.inference import OnnxClassifier


def build_desktop_app(paths: AppPaths):
    """Assemble the local Flask service from immutable resources and local data."""
    from server.app import create_app

    app = create_app(
        classifier=OnnxClassifier(paths.model_bundle_dir),
        history_store=HistoryStore(
            paths.history_database_path,
            paths.history_media_dir,
        ),
    )
    app.static_folder = str(paths.static_dir)
    return app


def run(*, webview_module=webview, paths: AppPaths | None = None) -> int:
    """Start the private service, then host it in one native app window."""
    if webview_module is None:
        raise RuntimeError("pywebview is required to launch the desktop application")

    paths = paths or AppPaths.for_runtime(getattr(sys, "frozen", False))
    app = build_desktop_app(paths)
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

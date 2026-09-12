from pathlib import Path
from types import SimpleNamespace
from urllib.request import urlopen

from flask import Flask
import pytest

import desktop.main as desktop_main
from desktop.main import run
from desktop.paths import AppPaths
import desktop.paths as paths_module
from desktop.server_thread import ServerThread


def create_health_app():
    app = Flask(__name__)

    @app.get("/health")
    def health():
        return {"ok": True}

    return app


class FakeWebview:
    def __init__(self):
        self.created = []
        self.started = []

    def create_window(self, title, url, **kwargs):
        self.created.append({"title": title, "url": url, **kwargs})

    def start(self, **kwargs):
        self.started.append(kwargs)


def test_server_thread_uses_an_ephemeral_127_loopback_port():
    server = ServerThread(create_health_app(), port=0)
    try:
        url = server.start_and_wait()
        assert url.startswith("http://127.0.0.1:")
        with urlopen(url + "/health", timeout=2) as response:
            assert response.status == 200
    finally:
        server.shutdown()


@pytest.mark.parametrize("host", ("0.0.0.0", "192.168.1.20", "::", "localhost"))
def test_server_thread_rejects_any_non_loopback_bind_host(host):
    with pytest.raises(ValueError, match="127.0.0.1"):
        ServerThread(create_health_app(), host=host)


def test_runtime_paths_keep_bundled_resources_separate_from_writable_data(
    monkeypatch, tmp_path
):
    bundled = tmp_path / "bundle"
    monkeypatch.setattr("sys._MEIPASS", str(bundled), raising=False)

    paths = AppPaths.for_runtime(frozen=True)

    assert paths.static_dir == bundled / "server" / "static"
    assert paths.model_bundle_dir == bundled / "models" / "production"
    assert paths.reference_dir == bundled / "reference"
    assert paths.data_dir == paths_module.platform_data_dir()
    assert paths.data_dir != paths.resources_dir
    assert paths.history_database_path.parent == paths.data_dir
    assert paths.history_media_dir.parent == paths.data_dir


def test_platform_data_dir_uses_windows_local_app_data(tmp_path):
    local_app_data = tmp_path / "LocalAppData"

    assert paths_module.platform_data_dir(
        "Windows", {"LOCALAPPDATA": str(local_app_data)}
    ) == local_app_data / "E-Waste Triage"


def test_platform_data_dir_keeps_macos_application_support():
    assert paths_module.platform_data_dir("Darwin", {}) == (
        Path.home() / "Library/Application Support/E-Waste Triage"
    )


def test_shutdown_signals_include_windows_ctrl_break_when_available():
    fake_signals = SimpleNamespace(SIGTERM=15, SIGINT=2, SIGBREAK=21)

    assert desktop_main.shutdown_signals(fake_signals) == (15, 2, 21)


def test_main_routes_gui_runtime_check_without_starting_the_app(monkeypatch):
    calls = []
    monkeypatch.setattr(
        desktop_main,
        "check_windows_gui_runtime",
        lambda: calls.append("checked") or 0,
        raising=False,
    )
    monkeypatch.setattr(
        desktop_main,
        "run",
        lambda: pytest.fail("runtime check must not start the application"),
    )

    assert desktop_main.main(["--gui-runtime-check"]) == 0
    assert calls == ["checked"]


def test_desktop_run_opens_one_native_window(monkeypatch, tmp_path):
    fake_webview = FakeWebview()
    paths = AppPaths(
        resources_dir=tmp_path / "resources",
        static_dir=tmp_path / "resources" / "server" / "static",
        model_bundle_dir=tmp_path / "resources" / "models" / "production",
        reference_dir=tmp_path / "resources" / "reference",
        data_dir=tmp_path / "support",
        history_database_path=tmp_path / "support" / "history.sqlite",
        history_media_dir=tmp_path / "support" / "media",
    )
    monkeypatch.setattr("desktop.main.build_desktop_app", lambda paths: create_health_app())

    assert run(webview_module=fake_webview, paths=paths) == 0

    assert len(fake_webview.created) == 1
    window = fake_webview.created[0]
    assert window["title"] == "E-Waste Triage"
    assert window["url"].startswith("http://127.0.0.1:")
    assert window["min_size"] == (760, 620)
    assert fake_webview.started == [{"debug": False}]


def test_desktop_run_closes_reference_store_when_shutdown_fails(
    monkeypatch, tmp_path
):
    fake_webview = FakeWebview()
    paths = AppPaths(
        resources_dir=tmp_path / "resources",
        static_dir=tmp_path / "resources" / "server" / "static",
        model_bundle_dir=tmp_path / "resources" / "models" / "production",
        reference_dir=tmp_path / "resources" / "reference",
        data_dir=tmp_path / "support",
        history_database_path=tmp_path / "support" / "history.sqlite",
        history_media_dir=tmp_path / "support" / "media",
    )
    app = create_health_app()
    closed = []
    app.extensions["close_reference_store"] = lambda: closed.append(True)

    class ShutdownFailure:
        def __init__(self, _app):
            pass

        def start_and_wait(self):
            return "http://127.0.0.1:12345"

        def shutdown(self):
            raise ValueError("shutdown failed")

    monkeypatch.setattr("desktop.main.build_desktop_app", lambda _paths: app)
    monkeypatch.setattr("desktop.main.ServerThread", ShutdownFailure)

    try:
        raise LookupError("outer handled error")
    except LookupError:
        with pytest.raises(ValueError, match="shutdown failed"):
            run(webview_module=fake_webview, paths=paths)

    assert closed == [True]


def test_desktop_run_preserves_startup_error_while_cleaning_up(monkeypatch, tmp_path):
    fake_webview = FakeWebview()
    paths = AppPaths(
        resources_dir=tmp_path / "resources",
        static_dir=tmp_path / "resources" / "server" / "static",
        model_bundle_dir=tmp_path / "resources" / "models" / "production",
        reference_dir=tmp_path / "resources" / "reference",
        data_dir=tmp_path / "support",
        history_database_path=tmp_path / "support" / "history.sqlite",
        history_media_dir=tmp_path / "support" / "media",
    )
    app = create_health_app()
    closed = []
    app.extensions["close_reference_store"] = lambda: closed.append(True)

    class StartupAndShutdownFailure:
        def __init__(self, _app):
            pass

        def start_and_wait(self):
            raise ValueError("startup failed")

        def shutdown(self):
            raise RuntimeError("shutdown failed")

    monkeypatch.setattr("desktop.main.build_desktop_app", lambda _paths: app)
    monkeypatch.setattr("desktop.main.ServerThread", StartupAndShutdownFailure)

    with pytest.raises(ValueError, match="startup failed"):
        run(webview_module=fake_webview, paths=paths)

    assert closed == [True]

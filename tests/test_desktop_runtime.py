from pathlib import Path
from urllib.request import urlopen

from flask import Flask

from desktop.main import run
from desktop.paths import AppPaths
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


def test_server_thread_uses_an_ephemeral_loopback_port():
    server = ServerThread(create_health_app(), port=0)
    try:
        url = server.start_and_wait()
        assert url.startswith("http://127.0.0.1:")
        with urlopen(url + "/health", timeout=2) as response:
            assert response.status == 200
    finally:
        server.shutdown()


def test_runtime_paths_keep_bundled_resources_separate_from_writable_data(
    monkeypatch, tmp_path
):
    bundled = tmp_path / "bundle"
    monkeypatch.setattr("sys._MEIPASS", str(bundled), raising=False)

    paths = AppPaths.for_runtime(frozen=True)

    assert paths.static_dir == bundled / "server" / "static"
    assert paths.model_bundle_dir == bundled / "models" / "production"
    assert paths.reference_dir == bundled / "reference"
    assert paths.data_dir == Path.home() / "Library/Application Support/E-Waste Triage"
    assert paths.data_dir != paths.resources_dir
    assert paths.history_database_path.parent == paths.data_dir
    assert paths.history_media_dir.parent == paths.data_dir


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

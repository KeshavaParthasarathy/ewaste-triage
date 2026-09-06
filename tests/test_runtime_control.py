"""Release-only control-plane contracts for the packaged desktop process."""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from threading import Event, Thread
import time
from urllib.parse import urlparse
from urllib.request import urlopen

from flask import Flask
import pytest

from desktop.main import build_desktop_app, run
from desktop.paths import APP_NAME, AppPaths
from server.phone_sessions import PhoneSessionManager


ROOT = Path(__file__).resolve().parents[1]


def _paths(tmp_path: Path) -> AppPaths:
    resources = tmp_path / "resources"
    support = tmp_path / "support"
    return AppPaths(
        resources_dir=resources,
        static_dir=resources / "server" / "static",
        model_bundle_dir=resources / "models" / "production",
        reference_dir=resources / "reference",
        data_dir=support,
        history_database_path=support / "history.sqlite",
        history_media_dir=support / "media",
    )


def _health_app() -> Flask:
    app = Flask(__name__)

    @app.get("/health")
    def health():
        return {"ok": True}

    return app


def _wait_for_readiness(path: Path, process: subprocess.Popen[str] | None = None):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
        if process is not None and process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(
                f"desktop process exited before readiness: {process.returncode}\n"
                f"stdout={stdout}\nstderr={stderr}"
            )
        time.sleep(0.02)
    raise AssertionError("desktop process did not publish readiness")


def test_production_runtime_ignores_test_app_support_override(monkeypatch, tmp_path):
    monkeypatch.delenv("EWASTE_TEST_MODE", raising=False)
    monkeypatch.setenv("EWASTE_TEST_APP_SUPPORT_DIR", str(tmp_path / "override"))

    paths = AppPaths.for_runtime(frozen=False)

    assert paths.data_dir == Path.home() / "Library" / "Application Support" / APP_NAME


@pytest.mark.parametrize("value", (None, "", "relative/support"))
def test_test_mode_requires_an_absolute_app_support_override(monkeypatch, value):
    monkeypatch.setenv("EWASTE_TEST_MODE", "1")
    if value is None:
        monkeypatch.delenv("EWASTE_TEST_APP_SUPPORT_DIR", raising=False)
    else:
        monkeypatch.setenv("EWASTE_TEST_APP_SUPPORT_DIR", value)

    with pytest.raises(ValueError, match="EWASTE_TEST_APP_SUPPORT_DIR"):
        AppPaths.for_runtime(frozen=False)


def test_test_mode_uses_an_absolute_app_support_override(monkeypatch, tmp_path):
    support = tmp_path / "app support"
    monkeypatch.setenv("EWASTE_TEST_MODE", "1")
    monkeypatch.setenv("EWASTE_TEST_APP_SUPPORT_DIR", str(support))

    paths = AppPaths.for_runtime(frozen=False)

    assert paths.data_dir == support
    assert paths.history_database_path == support / "history.sqlite"
    assert paths.history_media_dir == support / "media"


def test_test_mode_publishes_ready_loopback_url_without_opening_webview(
    monkeypatch, tmp_path
):
    ready_path = tmp_path / "ready.json"
    shutdown_event = Event()
    calls = []

    class WebviewThatMustNotRun:
        def create_window(self, *_args, **_kwargs):
            calls.append("create_window")
            raise AssertionError("test mode must not open pywebview")

        def start(self, **_kwargs):
            calls.append("start")
            raise AssertionError("test mode must not start pywebview")

    monkeypatch.setenv("EWASTE_TEST_MODE", "1")
    monkeypatch.setenv("EWASTE_TEST_READY_FILE", str(ready_path))
    monkeypatch.setenv("EWASTE_TEST_APP_SUPPORT_DIR", str(tmp_path / "support"))
    monkeypatch.setattr("desktop.main.build_desktop_app", lambda _paths: _health_app())
    result = []
    thread = Thread(
        target=lambda: result.append(
            run(
                webview_module=WebviewThatMustNotRun(),
                paths=_paths(tmp_path),
                shutdown_event=shutdown_event,
            )
        )
    )
    thread.start()
    payload = _wait_for_readiness(ready_path)

    assert payload.keys() == {"url"}
    assert payload["url"].startswith("http://127.0.0.1:")
    with urlopen(payload["url"] + "/health", timeout=2) as response:
        assert response.status == 200

    shutdown_event.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert result == [0]
    assert calls == []
    assert not ready_path.exists()


@pytest.mark.parametrize("termination_signal", (signal.SIGTERM, signal.SIGINT))
def test_test_mode_signals_stop_a_real_desktop_process_cleanly(
    tmp_path, termination_signal
):
    ready_path = tmp_path / "ready.json"
    support = tmp_path / "support"
    script = """
from flask import Flask
import desktop.main as main

app = Flask(__name__)

@app.get('/health')
def health():
    return {'ok': True}

main.build_desktop_app = lambda _paths: app
raise SystemExit(main.run())
"""
    env = os.environ | {
        "EWASTE_TEST_MODE": "1",
        "EWASTE_TEST_READY_FILE": str(ready_path),
        "EWASTE_TEST_APP_SUPPORT_DIR": str(support),
    }
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    payload = _wait_for_readiness(ready_path, process)
    assert payload.keys() == {"url"}
    with urlopen(payload["url"] + "/health", timeout=2) as response:
        assert response.status == 200

    process.send_signal(termination_signal)
    stdout, stderr = process.communicate(timeout=5)

    assert process.returncode == 0, (stdout, stderr)
    assert not ready_path.exists()


def test_test_mode_phone_capture_injects_only_loopback(monkeypatch, tmp_path):
    class Classifier:
        arch = "test"
        classes = ("0301_computer_mouse",)

    class ReferenceStore:
        def __init__(self, _path):
            pass

        def close(self):
            pass

    monkeypatch.setenv("EWASTE_TEST_MODE", "1")
    monkeypatch.setattr("desktop.main.OnnxClassifier", lambda _path: Classifier())
    monkeypatch.setattr("desktop.main.ReferenceStore", ReferenceStore)
    app = build_desktop_app(_paths(tmp_path))
    app.config["TESTING"] = True
    try:
        response = app.test_client().post("/api/phone-session")
        assert response.status_code == 201
        assert urlparse(response.json["upload_url"]).hostname == "127.0.0.1"
        assert response.json["pairing_code"].isdigit()
        assert "token=" in response.json["upload_url"]
    finally:
        app.extensions["close_phone_capture"]()
        app.extensions["close_reference_store"]()


@pytest.mark.parametrize(
    "host",
    ("localhost", "::1", "127.0.0.1%lo0", "https://127.0.0.1", "127.0.0.2"),
)
def test_loopback_test_seam_does_not_accept_noncanonical_or_authority_hosts(host):
    sessions = PhoneSessionManager(allow_loopback=True)

    with pytest.raises(ValueError, match="safe LAN IP literal"):
        sessions.start(host, port=9012)


def test_loopback_test_seam_accepts_only_the_packaged_smoke_address():
    session = PhoneSessionManager(allow_loopback=True).start("127.0.0.1", port=9012)

    assert session.host == "127.0.0.1"
    assert urlparse(session.upload_url).hostname == "127.0.0.1"

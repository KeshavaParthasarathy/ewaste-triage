import base64
import io
import json
from pathlib import Path
import subprocess
import threading
import time
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

from flask import Flask
from PIL import Image
import pytest

from desktop.main import run
from desktop.paths import AppPaths
import desktop.server_thread as server_thread
from server.desktop_app import create_desktop_app
from server.history import HistoryStore
from server.phone_sessions import PhoneSessionManager


BoundPhoneServer = getattr(server_thread, "BoundPhoneServer", None)
PhoneServerController = getattr(server_thread, "PhoneServerController", None)


PREDICTION = {
    "class_name": "0301_computer_mouse",
    "unu_key": "0301",
    "confidence": 0.93,
    "low_confidence": False,
    "topk": [
        {"class_name": "0301_computer_mouse", "confidence": 0.93},
        {"class_name": "0301_keyboard", "confidence": 0.05},
    ],
}


class FakeClock:
    def __init__(self, value=100.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class FakeClassifier:
    arch = "fake-onnx"
    classes = ["0301_computer_mouse", "0301_keyboard"]

    def classify(self, image):
        image.load()
        return dict(PREDICTION)

    def probabilities_preprocessed(self, _image):
        return [0.93, 0.05]


class RecordingPhoneController:
    def __init__(self, app, *, bound_port=49152):
        self.app = app
        self.bound_port = bound_port
        self.start_calls = []
        self.stop_calls = 0
        self._running = False

    def start(self, host, port=0):
        self.start_calls.append((host, port))
        self._running = True
        return BoundPhoneServer(host=host, port=self.bound_port)

    def stop(self):
        self.stop_calls += 1
        self._running = False

    @property
    def is_running(self):
        return self._running


def jpeg_bytes():
    output = io.BytesIO()
    Image.new("RGB", (48, 32), (57, 101, 77)).save(output, format="JPEG")
    return output.getvalue()


@pytest.fixture
def phone_desktop(tmp_path):
    clock = FakeClock()
    sessions = PhoneSessionManager(now=clock, ttl_seconds=600)
    created = []

    def controller_factory(phone_app):
        controller = RecordingPhoneController(phone_app)
        created.append(controller)
        return controller

    history = HistoryStore(tmp_path / "history.sqlite", tmp_path / "media")
    app = create_desktop_app(
        classifier=FakeClassifier(),
        history_store=history,
        phone_sessions=sessions,
        phone_server_factory=controller_factory,
        lan_address_provider=lambda: "192.168.1.42",
        phone_clock=clock,
        phone_monitor_interval=0.01,
    )
    app.config["TESTING"] = True
    try:
        yield app, app.test_client(), sessions, created[0], history, clock
    finally:
        app.extensions["close_phone_capture"]()


def wait_until(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_phone_server_controller_binds_only_when_started_and_publishes_actual_port():
    assert PhoneServerController is not None
    assert BoundPhoneServer is not None
    app = Flask(__name__)

    @app.get("/health")
    def health():
        return {"ok": True}

    controller = PhoneServerController(app)
    assert controller.is_running is False

    try:
        bound = controller.start("127.0.0.1", port=0)
        assert bound.host == "127.0.0.1"
        assert 1 <= bound.port <= 65535
        assert controller.is_running is True
        with urlopen(f"http://127.0.0.1:{bound.port}/health", timeout=2) as response:
            assert response.status == 200
    finally:
        controller.stop()

    assert controller.is_running is False


def test_phone_server_controller_closes_socket_when_worker_cannot_start(
    monkeypatch,
):
    servers = []

    class FakeServer:
        server_port = 49152

        def __init__(self):
            self.close_calls = 0

        def serve_forever(self):
            pass

        def server_close(self):
            self.close_calls += 1

    class FailingThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            raise RuntimeError("thread start failed")

        def is_alive(self):
            return False

    def fake_make_server(*_args, **_kwargs):
        server = FakeServer()
        servers.append(server)
        return server

    monkeypatch.setattr(server_thread, "make_server", fake_make_server)
    monkeypatch.setattr(server_thread, "Thread", FailingThread)
    controller = PhoneServerController(Flask(__name__))

    with pytest.raises(RuntimeError, match="thread start failed"):
        controller.start("127.0.0.1", port=0)
    with pytest.raises(RuntimeError, match="thread start failed"):
        controller.start("127.0.0.1", port=0)

    assert [server.close_calls for server in servers] == [1, 1]
    assert controller.is_running is False


@pytest.mark.parametrize("host", ["localhost", "0.0.0.0", "::", "[::1]", "127.0.0.1%lo0"])
def test_phone_server_controller_rejects_non_literal_or_wildcard_hosts(host):
    assert PhoneServerController is not None
    controller = PhoneServerController(Flask(__name__))

    with pytest.raises(ValueError, match="IP literal"):
        controller.start(host, port=0)

    assert controller.is_running is False


def test_no_lan_listener_exists_before_explicit_start(phone_desktop):
    _app, client, sessions, controller, _history, _clock = phone_desktop

    assert controller.is_running is False
    assert controller.start_calls == []
    assert sessions.active() is None
    assert client.get("/health").status_code == 200
    assert controller.start_calls == []


def test_start_phone_session_binds_lan_listener_and_returns_memory_qr(phone_desktop):
    app, client, sessions, controller, _history, _clock = phone_desktop

    response = client.post("/api/phone-session")
    body = response.get_json()

    assert response.status_code == 201
    assert body["active"] is True
    assert body["upload_url"].startswith("http://192.168.1.42:")
    assert body["upload_url"].endswith(parse_qs(urlparse(body["upload_url"]).query)["token"][0])
    assert f":{controller.bound_port}/phone?" in body["upload_url"]
    assert body["pairing_code"].isdigit() and len(body["pairing_code"]) == 6
    assert body["expires_in_seconds"] == pytest.approx(600)
    assert body["qr_png"].startswith("data:image/png;base64,")
    qr_bytes = base64.b64decode(body["qr_png"].partition(",")[2], validate=True)
    with Image.open(io.BytesIO(qr_bytes)) as qr:
        assert qr.format == "PNG"
        assert qr.width == qr.height and qr.width >= 100

    token = parse_qs(urlparse(body["upload_url"]).query)["token"][0]
    assert sessions.authorize(token, body["pairing_code"])
    assert controller.start_calls == [("192.168.1.42", 0)]
    assert controller.is_running is True
    assert app.extensions["phone_app"].config["PHONE_REQUIRE_PAIRING_CODE"] is True
    assert response.headers["Cache-Control"] == "no-store"


def test_stop_phone_session_closes_listener_and_revokes_url(phone_desktop):
    _app, client, sessions, controller, _history, _clock = phone_desktop
    started = client.post("/api/phone-session").get_json()
    token = parse_qs(urlparse(started["upload_url"]).query)["token"][0]

    response = client.delete("/api/phone-session")

    assert response.status_code == 200
    assert response.get_json() == {"active": False, "result": None}
    assert controller.is_running is False
    assert controller.stop_calls >= 1
    assert sessions.authorize(token) is False
    assert client.get("/api/phone-session").get_json() == {
        "active": False,
        "result": None,
    }


@pytest.mark.parametrize("revocation", ["stop", "replace", "expire"])
def test_revoked_session_discards_inflight_phone_upload_side_effects(
    tmp_path,
    revocation,
):
    entered_classifier = threading.Event()
    release_classifier = threading.Event()

    class BlockingClassifier(FakeClassifier):
        def classify(self, image):
            image.load()
            entered_classifier.set()
            assert release_classifier.wait(timeout=2)
            return dict(PREDICTION)

    class RecordingSourceImages:
        def __init__(self):
            self.puts = []

        def put(self, *args, **kwargs):
            self.puts.append((args, kwargs))

    clock = FakeClock()
    sessions = PhoneSessionManager(now=clock, ttl_seconds=600)
    controllers = []

    def controller_factory(phone_app):
        controller = RecordingPhoneController(phone_app)
        controllers.append(controller)
        return controller

    history = HistoryStore(
        tmp_path / "history.sqlite",
        tmp_path / "media",
    )
    source_images = RecordingSourceImages()
    app = create_desktop_app(
        classifier=BlockingClassifier(),
        history_store=history,
        source_image_store=source_images,
        phone_sessions=sessions,
        phone_server_factory=controller_factory,
        lan_address_provider=lambda: "192.168.1.42",
        phone_clock=clock,
        phone_monitor_interval=60,
    )
    app.config["TESTING"] = True
    client = app.test_client()
    started = client.post("/api/phone-session").get_json()
    token = parse_qs(urlparse(started["upload_url"]).query)["token"][0]
    upload_status = []

    def upload():
        with controllers[0].app.test_client() as phone_client:
            response = phone_client.post(
                "/phone/upload",
                data={
                    "token": token,
                    "code": started["pairing_code"],
                    "image": (
                        io.BytesIO(jpeg_bytes()),
                        "capture.jpg",
                    ),
                },
                content_type="multipart/form-data",
            )
            upload_status.append(response.status_code)

    upload_thread = threading.Thread(target=upload)
    upload_thread.start()
    try:
        assert entered_classifier.wait(timeout=2)
        if revocation == "stop":
            assert client.delete("/api/phone-session").status_code == 200
        elif revocation == "replace":
            replacement = client.post("/api/phone-session")
            assert replacement.status_code == 201
        else:
            clock.advance(601)
        release_classifier.set()
        upload_thread.join(timeout=2)

        assert upload_thread.is_alive() is False
        assert upload_status == [200]
        status = client.get("/api/phone-session").get_json()
        assert status["active"] is (revocation == "replace")
        assert status["result"] is None
        assert history.list_scans() == []
        assert source_images.puts == []
    finally:
        release_classifier.set()
        upload_thread.join(timeout=2)
        app.extensions["close_phone_capture"]()


def test_phone_result_enters_desktop_inbox_once_and_is_saved(phone_desktop):
    app, client, sessions, controller, history, clock = phone_desktop
    started = client.post("/api/phone-session").get_json()
    token = parse_qs(urlparse(started["upload_url"]).query)["token"][0]
    original_expiry = sessions.active().expires_at
    clock.advance(500)

    rejected = controller.app.test_client().post(
        "/phone/upload",
        data={
            "token": token,
            "image": (io.BytesIO(jpeg_bytes()), "capture.jpg"),
        },
        content_type="multipart/form-data",
    )
    assert sessions.active().expires_at == original_expiry
    accepted = controller.app.test_client().post(
        "/phone/upload",
        data={
            "token": token,
            "code": started["pairing_code"],
            "image": (io.BytesIO(jpeg_bytes()), "capture.jpg"),
        },
        content_type="multipart/form-data",
    )

    first = client.get("/api/phone-session").get_json()
    second = client.get("/api/phone-session").get_json()

    assert rejected.status_code == 404
    assert accepted.status_code == 200
    assert first["active"] is True
    assert first["result"]["class_name"] == "0301_computer_mouse"
    assert first["result"]["scan_id"]
    assert second["result"] is None
    assert sessions.active().expires_at == pytest.approx(clock.value + 600)
    assert history.get_scan(first["result"]["scan_id"])["prediction"] == PREDICTION
    assert app.config["SOURCE_IMAGE_STORE"].get(first["result"]["scan_id"]) is not None


def test_expired_session_closes_listener_without_desktop_polling(phone_desktop):
    _app, client, sessions, controller, _history, clock = phone_desktop
    client.post("/api/phone-session")
    assert controller.is_running is True

    clock.advance(601)

    assert wait_until(lambda: not controller.is_running)
    assert sessions.active() is None


def test_status_discards_queued_result_when_session_expired_before_monitor(
    tmp_path,
):
    clock = FakeClock()
    sessions = PhoneSessionManager(now=clock, ttl_seconds=600)
    controllers = []

    def controller_factory(phone_app):
        controller = RecordingPhoneController(phone_app)
        controllers.append(controller)
        return controller

    app = create_desktop_app(
        classifier=FakeClassifier(),
        history_store=HistoryStore(
            tmp_path / "history.sqlite",
            tmp_path / "media",
        ),
        phone_sessions=sessions,
        phone_server_factory=controller_factory,
        lan_address_provider=lambda: "192.168.1.42",
        phone_clock=clock,
        phone_monitor_interval=60,
    )
    app.config["TESTING"] = True
    client = app.test_client()
    try:
        started = client.post("/api/phone-session").get_json()
        token = parse_qs(urlparse(started["upload_url"]).query)["token"][0]
        accepted = controllers[0].app.test_client().post(
            "/phone/upload",
            data={
                "token": token,
                "code": started["pairing_code"],
                "image": (io.BytesIO(jpeg_bytes()), "capture.jpg"),
            },
            content_type="multipart/form-data",
        )
        assert accepted.status_code == 200
        clock.advance(601)

        response = client.get("/api/phone-session")

        assert response.get_json() == {"active": False, "result": None}
        assert controllers[0].is_running is False
    finally:
        app.extensions["close_phone_capture"]()


def test_missing_lan_address_keeps_phone_listener_closed(tmp_path):
    controllers = []

    def factory(phone_app):
        controller = RecordingPhoneController(phone_app)
        controllers.append(controller)
        return controller

    app = create_desktop_app(
        classifier=FakeClassifier(),
        history_store=HistoryStore(tmp_path / "history.sqlite", tmp_path / "media"),
        phone_server_factory=factory,
        lan_address_provider=lambda: None,
    )
    app.config["TESTING"] = True

    response = app.test_client().post("/api/phone-session")

    assert response.status_code == 503
    assert "local network" in response.get_json()["error"].lower()
    assert controllers[0].start_calls == []
    assert controllers[0].is_running is False


def test_desktop_shutdown_stops_phone_listener_and_revokes_session(phone_desktop):
    app, client, sessions, controller, _history, _clock = phone_desktop
    started = client.post("/api/phone-session").get_json()
    token = parse_qs(urlparse(started["upload_url"]).query)["token"][0]

    app.extensions["close_phone_capture"]()

    assert controller.is_running is False
    assert sessions.authorize(token) is False


def test_native_runtime_invokes_phone_cleanup_even_when_loopback_shutdown_fails(
    monkeypatch, tmp_path
):
    paths = AppPaths(
        resources_dir=tmp_path / "resources",
        static_dir=tmp_path / "resources/server/static",
        model_bundle_dir=tmp_path / "resources/models/production",
        reference_dir=tmp_path / "resources/reference",
        data_dir=tmp_path / "support",
        history_database_path=tmp_path / "support/history.sqlite",
        history_media_dir=tmp_path / "support/media",
    )
    app = Flask(__name__)
    cleanup = []
    app.extensions["close_phone_capture"] = lambda: cleanup.append("phone")
    app.extensions["close_reference_store"] = lambda: cleanup.append("reference")

    class FakeWebview:
        def create_window(self, *_args, **_kwargs):
            pass

        def start(self, **_kwargs):
            pass

    class FailingLoopbackServer:
        def __init__(self, _app):
            pass

        def start_and_wait(self):
            return "http://127.0.0.1:12345"

        def shutdown(self):
            raise ValueError("loopback shutdown failed")

    monkeypatch.setattr("desktop.main.build_desktop_app", lambda _paths: app)
    monkeypatch.setattr("desktop.main.ServerThread", FailingLoopbackServer)

    with pytest.raises(ValueError, match="loopback shutdown failed"):
        run(webview_module=FakeWebview(), paths=paths)

    assert cleanup == ["phone", "reference"]


def test_real_javascript_controller_drives_live_desktop_and_phone_http_apis(
    monkeypatch, tmp_path
):
    # Loopback is deterministic for the integration harness; production still obtains
    # and validates a LAN address through preferred_lan_address/PhoneSessionManager.
    monkeypatch.setattr(
        "server.phone_sessions._canonical_lan_host",
        lambda host: host,
    )
    history = HistoryStore(tmp_path / "history.sqlite", tmp_path / "media")
    app = create_desktop_app(
        classifier=FakeClassifier(),
        history_store=history,
        lan_address_provider=lambda: "127.0.0.1",
    )
    desktop_server = server_thread.ServerThread(app)
    base_url = desktop_server.start_and_wait()
    script = r"""
const UI = require(process.argv[1]);
const baseUrl = process.argv[2];
const imageBytes = Buffer.from(process.argv[3], "base64");
const states = [];
let pairing = null;
let incoming = null;
const view = {
  transition() {}, setBusy() {}, renderInfluence() {}, renderHistory() {},
  markHistoryDeleting() {}, clearPreview() {}, showSection() {},
  setPhoneState(state, payload) {
    states.push(state);
    if (state === "ready") pairing = payload;
  },
  updatePhoneSession() {},
  renderPhoneIncomingResult(result) { incoming = result; }
};
const controller = UI.createController({
  view,
  fetchImpl: (path, options) => fetch(baseUrl + path, options),
  formDataFactory: () => new FormData(),
  nextFrame: async () => {},
  objectUrl: () => "",
  schedule: () => 1,
  cancelSchedule() {}
});
(async () => {
  const started = await controller.startPhoneSession();
  const phoneUrl = new URL(pairing.upload_url);
  const upload = new FormData();
  upload.append("token", phoneUrl.searchParams.get("token"));
  upload.append("code", pairing.pairing_code);
  upload.append("image", new Blob([imageBytes], {type: "image/jpeg"}), "capture.jpg");
  const uploaded = await fetch(`${phoneUrl.origin}/phone/upload`, {
    method: "POST", body: upload
  });
  const polled = await controller.pollPhoneSession();
  const context = controller.getAssessmentContext();
  const stopped = await controller.stopPhoneSession();
  process.stdout.write(JSON.stringify({
    started, uploadStatus: uploaded.status, polled, stopped, states,
    incoming: incoming && incoming.class_name, scanId: context && context.scan_id
  }));
})();
"""

    try:
        completed = subprocess.run(
            [
                "node",
                "-e",
                script,
                str(Path(__file__).parents[1] / "server/static/app.js"),
                base_url,
                base64.b64encode(jpeg_bytes()).decode("ascii"),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        result = json.loads(completed.stdout)
    finally:
        app.extensions["close_phone_capture"]()
        desktop_server.shutdown()

    assert result["started"] is True
    assert result["uploadStatus"] == 200
    assert result["polled"] is True
    assert result["stopped"] is True
    assert result["states"] == ["starting", "ready", "received", "idle"]
    assert result["incoming"] == "0301_computer_mouse"
    assert result["scanId"]
    assert history.get_scan(result["scanId"])["prediction"] == PREDICTION
    assert app.extensions["phone_server_controller"].is_running is False

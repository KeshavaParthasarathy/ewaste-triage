"""Independent end-to-end smoke coverage for a frozen E-Waste Triage app."""

from __future__ import annotations

import errno
from io import BytesIO
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request as WerkzeugRequest


requires_packaged_app = pytest.mark.skipif(
    "EWASTE_PACKAGED_APP" not in os.environ,
    reason="set EWASTE_PACKAGED_APP to a frozen E-Waste Triage app directory",
)


EXPECTED_CLASSES = [
    "0301_computer_mouse",
    "0301_keyboard",
    "0303_laptop",
    "0306_mobile_phone",
    "0401_headphones",
]
FIXTURE = Path(__file__).parent / "fixtures" / "packaged-smoke.jpg"
HEX_40 = re.compile(r"[0-9a-f]{40}\Z")
HEX_64 = re.compile(r"[0-9a-f]{64}\Z")


def _app_executable() -> Path:
    app = Path(os.environ["EWASTE_PACKAGED_APP"]).expanduser()
    candidates = (
        app / "Contents" / "MacOS" / "E-Waste Triage",
        app / "E-Waste Triage.exe",
    )
    for executable in candidates:
        if app.is_dir() and executable.is_file():
            return executable
    pytest.fail(
        "EWASTE_PACKAGED_APP must point to a macOS .app or Windows one-directory package"
    )


def test_packaged_executable_accepts_windows_onedir(monkeypatch, tmp_path: Path) -> None:
    app = tmp_path / "E-Waste Triage"
    app.mkdir()
    executable = app / "E-Waste Triage.exe"
    executable.write_bytes(b"MZ")
    monkeypatch.setenv("EWASTE_PACKAGED_APP", str(app))

    assert _app_executable() == executable


def _output(process: subprocess.Popen[str]) -> str:
    if process.poll() is None:
        return "process is still running; stdout/stderr will be captured at shutdown"
    stdout, stderr = process.communicate(timeout=1)
    return f"stdout:\n{stdout}\nstderr:\n{stderr}"


def _loopback_url(value: object) -> tuple[str, int]:
    if not isinstance(value, str):
        raise AssertionError("readiness URL must be text")
    parsed = urlparse(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise AssertionError(f"readiness URL is not a plain loopback URL: {value!r}")
    try:
        port = parsed.port
    except ValueError as error:
        raise AssertionError(f"readiness URL has an invalid port: {value!r}") from error
    if port is None or not 1 <= port <= 65535:
        raise AssertionError(f"readiness URL has an invalid port: {value!r}")
    return value.rstrip("/"), port


def _wait_for_readiness(process: subprocess.Popen[str], ready_file: Path) -> tuple[str, int]:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            pytest.fail(
                f"packaged app exited before readiness ({process.returncode})\n{_output(process)}"
            )
        if ready_file.exists():
            try:
                payload = json.loads(ready_file.read_text(encoding="utf-8"))
                if set(payload) != {"url"}:
                    raise AssertionError("readiness JSON must contain only url")
                return _loopback_url(payload["url"])
            except (OSError, ValueError, AssertionError) as error:
                pytest.fail(f"packaged app published malformed readiness: {error}")
        time.sleep(0.05)
    pytest.fail(
        "packaged app did not publish readiness within 20 seconds\n"
        f"{_output(process)}"
    )


def _json_request(
    url: str,
    endpoint: str,
    *,
    method: str = "GET",
    payload: object | None = None,
    data: bytes | None = None,
    content_type: str | None = None,
    timeout: float = 1.0,
) -> object:
    headers = {"Accept": "application/json"}
    if payload is not None:
        assert data is None
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif content_type is not None:
        headers["Content-Type"] = content_type
    request = Request(f"{url}{endpoint}", data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            assert response.status == 200 or response.status == 201
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise AssertionError(f"{method} {endpoint} returned {error.code}: {body}") from error


def _eventually(action, *, timeout: float = 5.0, interval: float = 0.05):
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return action()
        except (AssertionError, OSError, URLError, ValueError) as error:
            last_error = error
            time.sleep(interval)
    if last_error is not None:
        raise last_error
    raise AssertionError("bounded retry expired")


def _multipart_image(*, token: str, code: str, image: Path) -> tuple[bytes, str]:
    boundary = f"----ewaste-smoke-{uuid4().hex}"
    fields = (("token", token), ("code", code))
    body = bytearray()
    for name, value in fields:
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(value.encode())
        body.extend(b"\r\n")
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        b'Content-Disposition: form-data; name="image"; filename="packaged-smoke.jpg"\r\n'
    )
    body.extend(b"Content-Type: image/jpeg\r\n\r\n")
    body.extend(image.read_bytes())
    body.extend(f"\r\n--{boundary}--\r\n".encode())
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def _port_refused(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return False
    except ConnectionRefusedError:
        return True
    except OSError:
        return False


def _wait_for_refusal(port: int, *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_refused(port):
            return
        time.sleep(0.05)
    raise AssertionError(f"loopback port {port} remained reachable after shutdown")


def _cleanup_child(
    process: subprocess.Popen[str],
    *,
    ready_file: Path,
    ports: tuple[int | None, ...],
    shutdown_url: str | None = None,
    shutdown_timeout: float = 10.0,
    refusal_timeout: float = 5.0,
) -> None:
    failures = []
    force_stopped = False
    shutdown_requested = False
    if process.poll() is None and shutdown_url is not None:
        try:
            _json_request(shutdown_url, "/__test__/shutdown", method="POST")
            shutdown_requested = True
        except (AssertionError, OSError, URLError):
            pass
    if process.poll() is None and not shutdown_requested:
        if os.name == "nt":
            # A windowed PyInstaller executable has no console to receive
            # CTRL_BREAK_EVENT. Stop the bootloader and its child as one tree.
            force_stopped = True
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
                text=True,
            )
        else:
            process.send_signal(signal.SIGTERM)
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=shutdown_timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        stdout, stderr = process.communicate(timeout=10)
    diagnostics = f"stdout:\n{stdout}\nstderr:\n{stderr}"
    if timed_out:
        failures.append(f"packaged app did not exit after SIGTERM\n{diagnostics}")
    elif process.returncode != 0 and not force_stopped:
        failures.append(f"packaged app exited with status {process.returncode}\n{diagnostics}")

    if ready_file.exists():
        if force_stopped:
            ready_file.unlink()
        else:
            failures.append("readiness file remained after graceful shutdown")
    for port in dict.fromkeys(ports):
        if port is None:
            continue
        try:
            _wait_for_refusal(port, timeout=refusal_timeout)
        except AssertionError as error:
            failures.append(str(error))
    if failures:
        pytest.fail("\n".join(failures))


def test_release_digest_matchers_accept_only_exact_lowercase_hex() -> None:
    assert HEX_40.fullmatch("a" * 40)
    assert HEX_64.fullmatch("b" * 64)
    assert HEX_40.fullmatch(("a" * 40) + "suffix") is None
    assert HEX_64.fullmatch(("b" * 64) + "suffix") is None


def test_multipart_helper_produces_a_real_image_form() -> None:
    body, content_type = _multipart_image(
        token="capability",
        code="123456",
        image=FIXTURE,
    )
    environ = EnvironBuilder(
        method="POST",
        input_stream=BytesIO(body),
        content_length=len(body),
        content_type=content_type,
    ).get_environ()
    request = WerkzeugRequest(environ)

    assert request.form.to_dict() == {"token": "capability", "code": "123456"}
    assert request.files["image"].filename == "packaged-smoke.jpg"
    assert request.files["image"].read() == FIXTURE.read_bytes()


@requires_packaged_app
def test_frozen_app_exercises_desktop_and_phone_paths(tmp_path: Path) -> None:
    executable = _app_executable()
    assert FIXTURE.is_file(), f"missing checked-in smoke fixture: {FIXTURE}"
    support_dir = tmp_path / "support"
    ready_file = tmp_path / "ready.json"
    environment = os.environ | {
        "EWASTE_TEST_MODE": "1",
        "EWASTE_TEST_APP_SUPPORT_DIR": str(support_dir),
        "EWASTE_TEST_READY_FILE": str(ready_file),
    }
    process = subprocess.Popen(
        [str(executable)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
        creationflags=(
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            if os.name == "nt"
            else 0
        ),
    )
    desktop_port: int | None = None
    phone_port: int | None = None
    url: str | None = None
    try:
        url, desktop_port = _wait_for_readiness(process, ready_file)

        health = _eventually(lambda: _json_request(url, "/health"))
        assert health["model_loaded"] is True
        assert health["classes"] == EXPECTED_CLASSES

        inactive = _json_request(url, "/api/phone-session")
        assert inactive == {"active": False, "result": None}

        metadata = _json_request(url, "/api/v1/release-metadata")
        assert set(metadata) == {
            "app_version",
            "source_revision",
            "model_sha256",
            "component_database_sha256",
            "component_database_version",
        }
        assert isinstance(metadata["app_version"], str) and metadata["app_version"].strip()
        assert isinstance(metadata["component_database_version"], str) and metadata["component_database_version"].strip()
        assert isinstance(metadata["source_revision"], str) and HEX_40.fullmatch(metadata["source_revision"])
        assert isinstance(metadata["model_sha256"], str) and HEX_64.fullmatch(metadata["model_sha256"])
        assert isinstance(metadata["component_database_sha256"], str) and HEX_64.fullmatch(metadata["component_database_sha256"])

        body, content_type = _multipart_image(token="unused", code="000000", image=FIXTURE)
        classified = _json_request(
            url,
            "/api/v1/classify",
            method="POST",
            data=body,
            content_type=content_type,
        )
        scan_id = classified["scan_id"]
        class_name = classified["class_name"]
        assert isinstance(scan_id, str) and scan_id
        assert class_name in EXPECTED_CLASSES

        history = _json_request(url, "/api/v1/history")
        assert any(row.get("scan_id") == scan_id and row["prediction"]["class_name"] == class_name for row in history)

        confirmed = _json_request(
            url,
            f"/api/v1/history/{scan_id}/confirmation",
            method="PUT",
            payload={"accepted_class_name": class_name},
        )
        assert confirmed["confirmation"] == {"accepted_class_name": class_name, "source": "user"}

        assessment = _json_request(url, f"/api/v1/scans/{scan_id}/assessment")
        assert assessment["category_id"] == class_name
        assert assessment["template"]["components"]
        edited = _json_request(
            url,
            f"/api/v1/scans/{scan_id}/assessment",
            method="PUT",
            payload={
                "condition": "visible_wear",
                "known_issues": {"notes": "packaged smoke test"},
            },
        )
        assert edited["inputs"]["condition"] == "visible_wear"
        assert edited["inputs"]["known_issues"]["notes"] == "packaged smoke test"
        reread = _json_request(url, f"/api/v1/scans/{scan_id}/assessment")
        assert reread["template"] == assessment["template"]
        assert reread["components"]

        pairing = _json_request(url, "/api/phone-session", method="POST")
        phone = urlparse(pairing["upload_url"])
        assert phone.scheme == "http" and phone.hostname == "127.0.0.1" and phone.path == "/phone"
        assert phone.port is not None
        phone_port = phone.port
        token = parse_qs(phone.query).get("token", [None])[0]
        code = pairing["pairing_code"]
        assert isinstance(token, str) and token
        assert isinstance(code, str) and re.fullmatch(r"[0-9]{6}", code)

        phone_body, phone_content_type = _multipart_image(token=token, code=code, image=FIXTURE)
        uploaded = _json_request(
            f"http://127.0.0.1:{phone_port}",
            "/phone/upload",
            method="POST",
            data=phone_body,
            content_type=phone_content_type,
        )
        assert uploaded["prediction"]["class_name"] in EXPECTED_CLASSES

        phone_result = _eventually(
            lambda: _phone_result(url), timeout=5
        )
        assert phone_result["class_name"] in EXPECTED_CLASSES
        assert _json_request(url, "/api/phone-session")["result"] is None
        stopped = _json_request(url, "/api/phone-session", method="DELETE")
        assert stopped == {"active": False, "result": None}
        _wait_for_refusal(phone_port)
    finally:
        _cleanup_child(
            process,
            ready_file=ready_file,
            ports=(desktop_port, phone_port),
            shutdown_url=url,
        )


def _phone_result(url: str) -> object:
    status = _json_request(url, "/api/phone-session")
    result = status["result"]
    if result is None:
        raise AssertionError("phone result has not arrived")
    return result


def _start_stubborn_child(tmp_path: Path) -> subprocess.Popen[str]:
    child_ready = tmp_path / "child-ready"
    script = (
        "import signal, sys, time\n"
        "from pathlib import Path\n"
        "signal.signal(signal.SIGTERM, lambda *_args: None)\n"
        "if hasattr(signal, 'SIGBREAK'): signal.signal(signal.SIGBREAK, lambda *_args: None)\n"
        "Path(sys.argv[1]).write_text('ready', encoding='utf-8')\n"
        "print('captured child stdout', flush=True)\n"
        "print('captured child stderr', file=sys.stderr, flush=True)\n"
        "while True: time.sleep(1)\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(child_ready)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=(
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            if os.name == "nt"
            else 0
        ),
    )
    deadline = time.monotonic() + 2
    while not child_ready.exists() and time.monotonic() < deadline:
        assert process.poll() is None, "stubborn test child exited during setup"
        time.sleep(0.01)
    assert child_ready.exists(), "stubborn test child did not finish setup"
    return process


def test_cleanup_timeout_reaps_child_and_reports_captured_output(tmp_path: Path) -> None:
    process = _start_stubborn_child(tmp_path)
    try:
        with pytest.raises(pytest.fail.Exception) as failure:
            _cleanup_child(
                process,
                ready_file=tmp_path / "missing-ready.json",
                ports=(),
                shutdown_timeout=0.05,
                refusal_timeout=0.05,
            )
        message = str(failure.value)
        assert "did not exit after SIGTERM" in message
        assert "captured child stdout" in message
        assert "captured child stderr" in message
        assert process.poll() is not None
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=2)


def test_cleanup_timeout_still_checks_readiness_and_ports(tmp_path: Path) -> None:
    process = _start_stubborn_child(tmp_path)
    ready_file = tmp_path / "ready.json"
    ready_file.write_text("{}", encoding="utf-8")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        try:
            with pytest.raises(pytest.fail.Exception) as failure:
                _cleanup_child(
                    process,
                    ready_file=ready_file,
                    ports=(port,),
                    shutdown_timeout=0.05,
                    refusal_timeout=0.01,
                )
            message = str(failure.value)
            assert "readiness file remained after graceful shutdown" in message
            assert f"loopback port {port} remained reachable after shutdown" in message
            assert process.poll() is not None
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=2)


def test_wait_for_refusal_retries_until_connection_is_refused(monkeypatch) -> None:
    attempts = []
    errors = iter(
        (
            socket.timeout("timed out"),
            OSError(errno.EHOSTUNREACH, "No route to host"),
            ConnectionRefusedError(errno.ECONNREFUSED, "Connection refused"),
        )
    )

    def fail_in_sequence(_address, *, timeout):
        assert timeout == 0.25
        attempts.append(timeout)
        raise next(errors)

    monkeypatch.setattr(socket, "create_connection", fail_in_sequence)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    _wait_for_refusal(49152, timeout=1)

    assert attempts == [0.25, 0.25, 0.25]


def test_wait_for_refusal_fails_when_non_refusal_errors_reach_deadline(
    monkeypatch,
) -> None:
    clock = iter((0.0, 0.0, 0.1, 1.0))
    errors = iter(
        (
            socket.timeout("timed out"),
            OSError(errno.EHOSTUNREACH, "No route to host"),
        )
    )
    attempts = []

    def fail_in_sequence(_address, *, timeout):
        attempts.append(timeout)
        raise next(errors)

    monkeypatch.setattr(socket, "create_connection", fail_in_sequence)
    monkeypatch.setattr(time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    with pytest.raises(AssertionError, match="remained reachable"):
        _wait_for_refusal(49152, timeout=0.5)

    assert attempts == [0.25, 0.25]

"""Independent end-to-end smoke coverage for a frozen E-Waste Triage app."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest


pytestmark = pytest.mark.skipif(
    "EWASTE_PACKAGED_APP" not in os.environ,
    reason="set EWASTE_PACKAGED_APP to a frozen E-Waste Triage.app to run packaged smoke coverage",
)


EXPECTED_CLASSES = [
    "0301_computer_mouse",
    "0301_keyboard",
    "0303_laptop",
    "0306_mobile_phone",
    "0401_headphones",
]
FIXTURE = Path(__file__).parent / "fixtures" / "packaged-smoke.jpg"
HEX_40 = re.compile(r"[0-9a-f]{40}\\Z")
HEX_64 = re.compile(r"[0-9a-f]{64}\\Z")


def _app_executable() -> Path:
    app = Path(os.environ["EWASTE_PACKAGED_APP"]).expanduser()
    executable = app / "Contents" / "MacOS" / "E-Waste Triage"
    if app.suffix != ".app" or not app.is_dir() or not executable.is_file():
        pytest.fail(
            "EWASTE_PACKAGED_APP must point to an existing .app with "
            "Contents/MacOS/E-Waste Triage"
        )
    return executable


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
        body.extend(f"--{boundary}\\r\\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\\r\\n\\r\\n'.encode())
        body.extend(value.encode())
        body.extend(b"\\r\\n")
    body.extend(f"--{boundary}\\r\\n".encode())
    body.extend(
        b'Content-Disposition: form-data; name="image"; filename="packaged-smoke.jpg"\\r\\n'
    )
    body.extend(b"Content-Type: image/jpeg\\r\\n\\r\\n")
    body.extend(image.read_bytes())
    body.extend(f"\\r\\n--{boundary}--\\r\\n".encode())
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def _port_refused(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return False
    except ConnectionRefusedError:
        return True
    except OSError:
        return True


def _wait_for_refusal(port: int, *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_refused(port):
            return
        time.sleep(0.05)
    raise AssertionError(f"loopback port {port} remained reachable after shutdown")


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
    )
    desktop_port: int | None = None
    phone_port: int | None = None
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
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            pytest.fail(f"packaged app did not exit after SIGTERM\n{_output(process)}")
        assert process.returncode == 0, _output(process)
        assert not ready_file.exists(), "readiness file remained after graceful shutdown"
        if desktop_port is not None:
            _wait_for_refusal(desktop_port)
        if phone_port is not None:
            _wait_for_refusal(phone_port)


def _phone_result(url: str) -> object:
    status = _json_request(url, "/api/phone-session")
    result = status["result"]
    if result is None:
        raise AssertionError("phone result has not arrived")
    return result

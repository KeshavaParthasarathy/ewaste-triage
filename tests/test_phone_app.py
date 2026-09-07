import io
import json
from pathlib import Path
import struct
import subprocess
import zlib

import pytest
from PIL import Image

from server.phone_app import MAX_UPLOAD_BYTES, create_phone_app
from server.phone_sessions import PhoneSessionManager


PHONE_JAVASCRIPT = Path(__file__).parents[1] / "server" / "static" / "phone.js"


def _run_phone_ui_contract(script):
    completed = subprocess.run(
        ["node", "-e", script, str(PHONE_JAVASCRIPT)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


class FakeClock:
    def __init__(self, value=100.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def jpeg_bytes():
    output = io.BytesIO()
    Image.new("RGB", (48, 32), (72, 124, 86)).save(output, format="JPEG")
    return output.getvalue()


def png_header_without_pixels(width, height):
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IEND", b"")


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def sessions(clock):
    return PhoneSessionManager(now=clock, ttl_seconds=600)


@pytest.fixture
def active_session(sessions):
    return sessions.start(host="192.168.1.23", port=9012)


@pytest.fixture
def phone_services(sessions):
    classified_images = []
    received_results = []

    def classify_image(image):
        image.load()
        classified_images.append(image)
        return {
            "class_name": "0301_computer_mouse",
            "unu_key": "0301",
            "confidence": 0.93,
            "low_confidence": False,
            "topk": [
                {"class_name": "0301_computer_mouse", "confidence": 0.93},
                {"class_name": "0301_keyboard", "confidence": 0.05},
            ],
        }

    app = create_phone_app(sessions, classify_image, received_results.append)
    app.config["TESTING"] = True
    return app, classified_images, received_results


@pytest.fixture
def client(phone_services):
    return phone_services[0].test_client()


def test_inactive_service_rejects_phone_page(client):
    assert client.get("/phone?token=anything").status_code == 404


def test_active_token_can_open_page_and_upload_normalized_jpeg(
    client, active_session, phone_services
):
    page = client.get(f"/phone?token={active_session.token}")
    assert page.status_code == 200
    assert active_session.token.encode() in page.data

    result = client.post(
        "/phone/upload",
        data={
            "token": active_session.token,
            "image": (io.BytesIO(jpeg_bytes()), "capture.jpg"),
        },
        content_type="multipart/form-data",
    )

    assert result.status_code == 200
    assert result.get_json()["prediction"]["class_name"] == "0301_computer_mouse"
    _, classified_images, received_results = phone_services
    assert received_results == [result.get_json()["prediction"]]
    assert classified_images[0].mode == "RGB"
    assert classified_images[0].size == (48, 32)
    with pytest.raises(ValueError, match="closed"):
        classified_images[0].getpixel((0, 0))


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("get", "/phone", {}),
        ("get", "/phone/status", {}),
        ("get", "/static/phone.css", {}),
        ("get", "/static/phone.js", {}),
        (
            "post",
            "/phone/upload",
            {
                "data": {"image": (io.BytesIO(jpeg_bytes()), "capture.jpg")},
                "content_type": "multipart/form-data",
            },
        ),
    ],
)
def test_wrong_token_is_rejected_on_every_phone_route(
    client, active_session, method, path, kwargs
):
    if method == "get":
        response = client.get(f"{path}?token=wrong", **kwargs)
    else:
        kwargs["data"]["token"] = "wrong"
        response = client.post(path, **kwargs)

    assert response.status_code == 404


def test_oversized_body_is_rejected_without_classification(
    client, active_session, phone_services
):
    response = client.post(
        "/phone/upload",
        data={
            "token": active_session.token,
            "image": (io.BytesIO(b"x" * MAX_UPLOAD_BYTES), "capture.jpg"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 413
    assert phone_services[1:] == ([], [])


@pytest.mark.parametrize(
    ("contents", "expected_status"),
    [
        (b"not an image", 400),
        (png_header_without_pixels(40_000_001, 1), 413),
    ],
)
def test_non_image_and_over_pixel_limit_image_are_rejected(
    client, active_session, phone_services, contents, expected_status
):
    response = client.post(
        "/phone/upload",
        data={
            "token": active_session.token,
            "image": (io.BytesIO(contents), "capture.bin"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == expected_status
    assert phone_services[1:] == ([], [])


def test_only_explicit_phone_routes_exist_on_lan_app(phone_services, active_session):
    app = phone_services[0]
    rules = {
        (rule.rule, tuple(sorted(rule.methods - {"HEAD", "OPTIONS"})))
        for rule in app.url_map.iter_rules()
    }

    assert rules == {
        ("/phone", ("GET",)),
        ("/phone/upload", ("POST",)),
        ("/phone/status", ("GET",)),
        ("/static/phone.css", ("GET",)),
        ("/static/phone.js", ("GET",)),
    }
    client = app.test_client()
    for path in (
        "/",
        "/history",
        "/api/v1/history",
        "/train",
        "/admin",
        "/files",
        "/static/app.js",
        "/static/../phone_app.py",
    ):
        assert client.get(f"{path}?token={active_session.token}").status_code == 404


def test_expired_session_rejects_upload(client, active_session, clock, phone_services):
    clock.advance(601)

    response = client.post(
        "/phone/upload",
        data={
            "token": active_session.token,
            "image": (io.BytesIO(jpeg_bytes()), "capture.jpg"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 404
    assert phone_services[1:] == ([], [])


def test_invalid_upload_does_not_refresh_session(client, active_session, clock, sessions):
    clock.advance(500)
    response = client.post(
        "/phone/upload",
        data={
            "token": active_session.token,
            "image": (io.BytesIO(b"not an image"), "capture.jpg"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 400

    clock.advance(101)
    assert sessions.active() is None


def test_valid_status_refreshes_session(client, active_session, clock, sessions):
    clock.advance(500)
    response = client.get(f"/phone/status?token={active_session.token}")

    assert response.status_code == 200
    assert response.get_json()["active"] is True
    clock.advance(599)
    assert sessions.active() is not None


def test_pairing_code_can_be_required_for_status_and_upload(
    phone_services, active_session
):
    app = phone_services[0]
    app.config["PHONE_REQUIRE_PAIRING_CODE"] = True
    client = app.test_client()

    assert client.get(f"/phone?token={active_session.token}").status_code == 200
    assert client.get(f"/phone/status?token={active_session.token}").status_code == 404
    assert client.get(
        f"/phone/status?token={active_session.token}&code={active_session.pairing_code}"
    ).status_code == 200
    response = client.post(
        "/phone/upload",
        data={
            "token": active_session.token,
            "code": active_session.pairing_code,
            "image": (io.BytesIO(jpeg_bytes()), "capture.jpg"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200


@pytest.mark.parametrize(
    "path",
    ["/phone", "/phone/status", "/static/phone.css", "/static/phone.js"],
)
def test_phone_responses_apply_restrictive_browser_headers(
    client, active_session, path
):
    response = client.get(f"{path}?token={active_session.token}")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'none'" in response.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert "Access-Control-Allow-Origin" not in response.headers


def test_phone_page_has_local_accessible_capture_states(client, active_session):
    page = client.get(f"/phone?token={active_session.token}")
    html = page.get_data(as_text=True)
    css = client.get(f"/static/phone.css?token={active_session.token}").get_data(as_text=True)
    javascript = client.get(f"/static/phone.js?token={active_session.token}").get_data(as_text=True)

    assert 'accept="image/jpeg,image/png,image/webp,image/heic,image/heif"' in html
    assert 'capture="environment"' in html
    for state in (
        "capture-state",
        "preview-state",
        "analyzing-state",
        "result-state",
        "expired-state",
    ):
        assert f'id="{state}"' in html
    assert 'id="retry-button"' in html
    assert 'aria-live="polite"' in html
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "URL.createObjectURL" in javascript
    assert "fetch(" in javascript
    assert "https://" not in html + css + javascript
    assert "http://" not in html + css + javascript
    assert "Temporary local HTTP session" in html
    assert "Local analysis on your paired Mac" in html
    assert "secure" not in html.lower()
    assert "private local session" not in html.lower()


def test_phone_result_presenter_consumes_production_classifier_schema():
    result = _run_phone_ui_contract(r"""
const PhoneUI = require(process.argv[1]);
const presented = PhoneUI.presentPrediction({
  class_name: "0301_computer_mouse",
  confidence: 0.934,
  topk: [
    {class_name: "0301_computer_mouse", confidence: 0.934},
    {class_name: "0301_keyboard", confidence: 0.041},
    {class_name: "0303_laptop", confidence: 0.025}
  ]
});
process.stdout.write(JSON.stringify({
  presented,
  reducedScroll: PhoneUI.scrollBehavior(true),
  standardScroll: PhoneUI.scrollBehavior(false)
}));
""")

    assert result == {
        "presented": {
            "label": "Computer mouse",
            "confidence": "93%",
            "confidence_width": "93%",
            "alternatives": ["Keyboard", "Laptop"],
        },
        "reducedScroll": "auto",
        "standardScroll": "smooth",
    }

import io
import sqlite3
import struct
import zlib
from unittest.mock import Mock

import pytest
from PIL import Image

from server.app import create_app
from server.explanations import ActiveSourceImageStore
from server.history import HistoryStore


PREDICTION = {
    "class_name": "0306_mobile_phone",
    "unu_key": "0306",
    "confidence": 0.91,
    "low_confidence": False,
    "topk": [
        {"class_name": "0306_mobile_phone", "confidence": 0.91},
        {"class_name": "0303_laptop", "confidence": 0.09},
    ],
}


class FakeClassifier:
    arch = "test-engine"
    classes = ["0306_mobile_phone", "0303_laptop"]

    def __init__(self):
        self.calls = 0

    def classify(self, image):
        self.calls += 1
        image.load()
        return dict(PREDICTION)

    def probabilities(self, image):
        brightness = sum(image.convert("RGB").resize((1, 1)).getpixel((0, 0))) / (3 * 255)
        return [brightness, 1.0 - brightness]

    probabilities_preprocessed = probabilities


class ProtocolOnlyEngine:
    def __init__(self):
        self.probability_calls = 0

    def classify(self, image):
        return dict(PREDICTION)

    def probabilities(self, image):
        self.probability_calls += 1
        return [0.9, 0.1]

    probabilities_preprocessed = probabilities


def _jpeg_bytes(color=(100, 140, 90)):
    buf = io.BytesIO()
    Image.new("RGB", (300, 300), color).save(buf, format="JPEG")
    buf.seek(0)
    return buf


def _maximum_size_jpeg_bytes():
    buf = io.BytesIO()
    Image.new("L", (8_000, 5_000), 100).save(buf, format="JPEG", quality=20)
    buf.seek(0)
    return buf


def _png_header_without_pixels(width, height):
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return io.BytesIO(
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IEND", b"")
    )


@pytest.fixture
def desktop_services(tmp_path):
    return (
        FakeClassifier(),
        HistoryStore(tmp_path / "history.sqlite", tmp_path / "media"),
    )


@pytest.fixture
def desktop_client(desktop_services):
    classifier, history_store = desktop_services
    app = create_app(classifier=classifier, history_store=history_store)
    app.config["TESTING"] = True
    return app.test_client()


def test_desktop_classify_returns_scan_id_and_persists_prediction(
    desktop_client, desktop_services
):
    classifier, history_store = desktop_services

    response = desktop_client.post(
        "/api/v1/classify",
        data={"image": (_jpeg_bytes(), "x.jpg")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.json["scan_id"]
    assert response.json["class_name"] == PREDICTION["class_name"]
    assert response.json["topk"] == PREDICTION["topk"]
    assert classifier.calls == 1
    assert history_store.get_scan(response.json["scan_id"])["prediction"]["class_name"] == PREDICTION["class_name"]


def test_desktop_classify_does_not_retain_original_by_default(
    desktop_client, desktop_services
):
    _, history_store = desktop_services

    response = desktop_client.post(
        "/api/v1/classify",
        data={"image": (_jpeg_bytes(), "x.jpg")},
        content_type="multipart/form-data",
    )

    record = history_store.get_scan(response.json["scan_id"])
    assert record["original_path"] is None


def test_failed_image_validation_creates_no_history_row(
    desktop_client, desktop_services
):
    _, history_store = desktop_services

    response = desktop_client.post(
        "/api/v1/classify",
        data={"image": (io.BytesIO(b"not an image"), "x.jpg")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert history_store.list_scans() == []


@pytest.mark.parametrize("width", [40_000_001, 200_000_000])
def test_pixel_limit_is_checked_before_decoding_the_full_image(
    desktop_client, desktop_services, width
):
    classifier, history_store = desktop_services

    response = desktop_client.post(
        "/api/v1/classify",
        data={
            "image": (
                _png_header_without_pixels(width, 1),
                "oversized.png",
            )
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 413
    assert response.json == {"error": "image exceeds 40,000,000 pixels"}
    assert classifier.calls == 0
    assert history_store.list_scans() == []


def test_history_write_failure_preserves_desktop_prediction(tmp_path):
    classifier = FakeClassifier()
    database = tmp_path / "history.sqlite"
    history_store = HistoryStore(database, tmp_path / "media")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TRIGGER reject_scan BEFORE INSERT ON scans "
            "BEGIN SELECT RAISE(ABORT, 'history unavailable'); END"
        )
    app = create_app(classifier=classifier, history_store=history_store)
    app.config["TESTING"] = True

    response = app.test_client().post(
        "/api/v1/classify",
        data={"image": (_jpeg_bytes(), "x.jpg")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.json["class_name"] == PREDICTION["class_name"]
    assert response.json["scan_id"] is None
    assert response.json["history_error"] == (
        "Classification complete, but this scan was not saved to history."
    )
    assert classifier.calls == 1
    assert history_store.list_scans() == []
    assert list((tmp_path / "media").iterdir()) == []


def test_desktop_classification_works_when_history_is_disabled(tmp_path):
    classifier = FakeClassifier()
    app = create_app(classifier=classifier, history_store=None)
    app.config["TESTING"] = True

    response = app.test_client().post(
        "/api/v1/classify",
        data={"image": (_jpeg_bytes(), "x.jpg")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.json["scan_id"] is None
    assert response.json["class_name"] == PREDICTION["class_name"]
    assert classifier.calls == 1


def test_history_api_lists_gets_deletes_and_clears_scans(
    desktop_client, desktop_services
):
    _, history_store = desktop_services
    first = desktop_client.post(
        "/api/v1/classify",
        data={"image": (_jpeg_bytes("blue"), "first.jpg")},
        content_type="multipart/form-data",
    ).json["scan_id"]
    second = desktop_client.post(
        "/api/v1/classify",
        data={"image": (_jpeg_bytes("red"), "second.jpg")},
        content_type="multipart/form-data",
    ).json["scan_id"]

    listed = desktop_client.get("/api/v1/history")
    fetched = desktop_client.get(f"/api/v1/history/{first}")
    deleted = desktop_client.delete(f"/api/v1/history/{first}")
    missing = desktop_client.get(f"/api/v1/history/{first}")
    cleared = desktop_client.delete("/api/v1/history")

    assert listed.status_code == 200
    assert [item["scan_id"] for item in listed.json] == [second, first]
    assert fetched.status_code == 200
    assert fetched.json["scan_id"] == first
    assert deleted.status_code == 200
    assert deleted.json == {"deleted": True}
    assert missing.status_code == 404
    assert cleared.status_code == 200
    assert cleared.json == {"deleted_count": 1}
    assert history_store.list_scans() == []


def test_history_api_is_empty_when_history_is_disabled():
    app = create_app(classifier=FakeClassifier(), history_store=None)
    app.config["TESTING"] = True
    client = app.test_client()

    assert client.get("/api/v1/history").json == []
    assert client.get("/api/v1/history/missing").status_code == 404
    assert client.delete("/api/v1/history/missing").status_code == 404
    assert client.delete("/api/v1/history").json == {"deleted_count": 0}


def test_history_api_returns_only_the_twenty_newest_scans(desktop_client, desktop_services):
    _, history_store = desktop_services
    scan_ids = [
        history_store.add_scan(
            PREDICTION,
            Image.new("RGB", (10, 10), (index, 0, 0)),
            retain_original=False,
            original=None,
        )
        for index in range(25)
    ]

    response = desktop_client.get("/api/v1/history")

    assert response.status_code == 200
    assert [row["scan_id"] for row in response.json] == list(reversed(scan_ids[-20:]))


def _desktop_scan(client):
    response = client.post(
        "/api/v1/classify",
        data={"image": (_jpeg_bytes(), "x.jpg")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    return response.json["scan_id"]


def test_explain_returns_normalized_grid_and_model_influence_copy(desktop_client):
    scan_id = _desktop_scan(desktop_client)

    response = desktop_client.post(f"/api/v1/explain/{scan_id}")

    assert response.status_code == 200
    assert response.json["scan_id"] == scan_id
    assert response.json["grid_size"] == 7
    assert len(response.json["values"]) == 7
    assert all(len(row) == 7 for row in response.json["values"])
    assert all(0.0 <= value <= 1.0 for row in response.json["values"] for value in row)
    assert "influenced this result" in response.json["copy"]
    assert "not a physical diagnosis" in response.json["copy"].lower()


def test_explain_uses_the_inference_protocol_without_a_classes_attribute(tmp_path):
    engine = ProtocolOnlyEngine()
    app = create_app(
        classifier=engine,
        history_store=HistoryStore(tmp_path / "history.sqlite", tmp_path / "media"),
    )
    app.config["TESTING"] = True
    client = app.test_client()
    scan_id = _desktop_scan(client)
    assert engine.probability_calls == 0

    response = client.post(f"/api/v1/explain/{scan_id}")

    assert response.status_code == 200


def test_explanation_failure_does_not_remove_prediction(desktop_client, desktop_services, monkeypatch):
    scan_id = _desktop_scan(desktop_client)
    monkeypatch.setattr("server.app.occlusion_map", Mock(side_effect=RuntimeError("boom")))

    response = desktop_client.post(f"/api/v1/explain/{scan_id}")

    assert response.status_code == 503
    assert response.json["prediction_available"] is True
    assert desktop_services[1].get_scan(scan_id)["prediction"]["class_name"] == PREDICTION["class_name"]


def test_explain_rejects_unknown_scan(desktop_client):
    response = desktop_client.post("/api/v1/explain/not-a-scan")

    assert response.status_code == 404


def test_explain_rejects_expired_source_image(tmp_path):
    now = [0.0]
    source_images = ActiveSourceImageStore(clock=lambda: now[0])
    app = create_app(
        classifier=FakeClassifier(),
        history_store=HistoryStore(tmp_path / "history.sqlite", tmp_path / "media"),
        source_image_store=source_images,
    )
    app.config["TESTING"] = True
    client = app.test_client()
    scan_id = _desktop_scan(client)
    now[0] = 300.0

    response = client.post(f"/api/v1/explain/{scan_id}")

    assert response.status_code == 404


def test_explain_allows_only_one_concurrent_job(desktop_client):
    scan_id = _desktop_scan(desktop_client)
    source_images = desktop_client.application.config["SOURCE_IMAGE_STORE"]
    assert source_images.try_acquire() is True
    try:
        response = desktop_client.post(f"/api/v1/explain/{scan_id}")
    finally:
        source_images.release()

    assert response.status_code == 429


def test_desktop_history_does_not_store_explanation_source_image(desktop_client, desktop_services):
    scan_id = _desktop_scan(desktop_client)
    record = desktop_services[1].get_scan(scan_id)

    assert record["original_path"] is None
    assert "source_image" not in record


def test_desktop_classify_caches_only_a_detached_inference_crop_for_max_size_upload(
    desktop_client,
):
    response = desktop_client.post(
        "/api/v1/classify",
        data={"image": (_maximum_size_jpeg_bytes(), "maximum.jpg")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    source_images = desktop_client.application.config["SOURCE_IMAGE_STORE"]
    cached = source_images.get(response.json["scan_id"])
    assert cached.mode == "RGB"
    assert cached.size == (224, 224)
    original_pixel = cached.getpixel((0, 0))
    cached.putpixel((0, 0), (0, 0, 0))
    assert source_images.get(response.json["scan_id"]).getpixel((0, 0)) == original_pixel

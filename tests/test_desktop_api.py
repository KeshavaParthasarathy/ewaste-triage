import io

import pytest
from PIL import Image

from server.app import create_app
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


def _jpeg_bytes(color=(100, 140, 90)):
    buf = io.BytesIO()
    Image.new("RGB", (300, 300), color).save(buf, format="JPEG")
    buf.seek(0)
    return buf


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

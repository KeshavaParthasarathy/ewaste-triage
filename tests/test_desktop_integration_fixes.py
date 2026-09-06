import io
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen

from PIL import Image

from desktop.main import run
from desktop.paths import AppPaths
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
    arch = "fake-onnx"
    classes = ["0306_mobile_phone", "0303_laptop"]

    def classify(self, image):
        image.load()
        return dict(PREDICTION)

    def probabilities_preprocessed(self, image):
        return [0.91, 0.09]


class FakeWebview:
    def __init__(self):
        self.created = []
        self.page = ""

    def create_window(self, title, url, **kwargs):
        self.created.append({"title": title, "url": url, **kwargs})

    def start(self, **kwargs):
        with urlopen(self.created[0]["url"], timeout=2) as response:
            self.page = response.read().decode()


def _jpeg_bytes():
    data = io.BytesIO()
    Image.new("RGB", (32, 32), "green").save(data, format="JPEG")
    data.seek(0)
    return data


def _desktop_app(tmp_path):
    from server.desktop_app import create_desktop_app

    app = create_desktop_app(
        classifier=FakeClassifier(),
        history_store=HistoryStore(tmp_path / "history.sqlite", tmp_path / "media"),
    )
    app.config["TESTING"] = True
    return app


def test_product_factory_import_does_not_require_admin_modules():
    code = """
import builtins
real_import = builtins.__import__
def guarded(name, *args, **kwargs):
    if name in {'scripts.valuation', 'scripts.photo_classes'}:
        raise ImportError(name)
    return real_import(name, *args, **kwargs)
builtins.__import__ = guarded
import server.desktop_app
print('ok')
"""
    completed = subprocess.run(
        [sys.executable, "-c", code], check=True, text=True, capture_output=True
    )
    assert completed.stdout.strip() == "ok"


def test_product_factory_excludes_collection_and_ingest_routes(tmp_path):
    client = _desktop_app(tmp_path).test_client()

    assert client.get("/collect").status_code == 404
    assert client.post("/ingest").status_code == 404
    assert client.get("/collection-classes").status_code == 404
    assert client.get("/health").json["model_loaded"] is True


def test_product_factory_persists_validated_user_correction_without_mutating_model_evidence(tmp_path):
    client = _desktop_app(tmp_path).test_client()
    scan_id = client.post(
        "/api/v1/classify",
        data={"image": (_jpeg_bytes(), "device.jpg")},
        content_type="multipart/form-data",
    ).json["scan_id"]

    corrected = client.put(
        f"/api/v1/history/{scan_id}/confirmation",
        json={"accepted_class_name": "0303_laptop"},
    )
    reopened = client.get(f"/api/v1/history/{scan_id}")
    invalid = client.put(
        f"/api/v1/history/{scan_id}/confirmation",
        json={"accepted_class_name": "9999_unknown"},
    )

    assert corrected.status_code == 200
    assert corrected.json["prediction"] == PREDICTION
    assert corrected.json["confirmation"] == {
        "accepted_class_name": "0303_laptop",
        "source": "user",
    }
    assert reopened.json == corrected.json
    assert invalid.status_code == 400
    assert invalid.json["error"] == "accepted category was not offered by the model"


def test_product_factory_rejects_oversized_request_with_plain_json_error(tmp_path):
    client = _desktop_app(tmp_path).test_client()
    oversized = io.BytesIO(b"x" * (8 * 1024 * 1024 + 1))

    response = client.post(
        "/api/v1/classify",
        data={"image": (oversized, "too-large.jpg")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 413
    assert response.json == {
        "error": "Photo is too large. Choose an image smaller than 8 MB and try again."
    }


def test_invalid_model_bundle_opens_a_safe_recovery_window(tmp_path):
    paths = AppPaths(
        resources_dir=tmp_path / "resources",
        static_dir=tmp_path / "resources" / "server" / "static",
        model_bundle_dir=tmp_path / "resources" / "models" / "production",
        reference_dir=tmp_path / "resources" / "reference",
        data_dir=tmp_path / "support",
        history_database_path=tmp_path / "support" / "history.sqlite",
        history_media_dir=tmp_path / "support" / "media",
    )
    webview = FakeWebview()

    assert run(webview_module=webview, paths=paths) == 0

    assert webview.created[0]["title"] == "E-Waste Triage"
    assert "Unable to start E-Waste Triage" in webview.page
    assert "Model bundle: unavailable" in webview.page
    assert "Traceback" not in webview.page

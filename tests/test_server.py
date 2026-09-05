import io

import pytest
import torch
import torch.nn as nn
from PIL import Image
from torchvision import models

import server.app as app_module
from server.app import create_app
from server.imaging import ImageTooLarge


@pytest.fixture
def ckpt(tmp_path):
    m = models.resnet18()
    m.fc = nn.Linear(m.fc.in_features, 2)
    p = tmp_path / "best.pt"
    torch.save({"arch": "resnet18",
                "classes": ["0301_small_it", "0306_mobile_phones"],
                "state_dict": m.state_dict()}, p)
    return p


@pytest.fixture
def client(ckpt, tmp_path):
    app = create_app(ckpt_path=ckpt, ingest_root=tmp_path / "photos")
    app.config["TESTING"] = True
    return app.test_client()


def _jpeg_bytes(color=(100, 140, 90)):
    buf = io.BytesIO()
    Image.new("RGB", (300, 300), color).save(buf, format="JPEG")
    buf.seek(0)
    return buf


def _oriented_jpeg_bytes():
    image = Image.new("RGB", (40, 20), "red")
    exif = image.getexif()
    exif[274] = 6
    buf = io.BytesIO()
    image.save(buf, format="JPEG", exif=exif)
    buf.seek(0)
    return buf


def test_health_reports_model_state(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json["model_loaded"] is True
    assert r.json["n_classes"] == 2


def test_capture_page_has_no_external_assets(client):
    html = client.get("/").get_data(as_text=True)
    assert "<form" in html or "<input" in html
    for scheme in ("http://", "https://", "//cdn"):
        assert scheme not in html, f"page references an external asset ({scheme}); it must be self-contained"


def test_collection_mode_starts_without_checkpoint_and_serves_collection_page(tmp_path):
    """Collection must work before the first model checkpoint exists."""
    app = create_app(ckpt_path=tmp_path / "missing.pt",
                     ingest_root=tmp_path / "photos",
                     collection_only=True)
    app.config["TESTING"] = True

    r = app.test_client().get("/")

    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Training Photo Collection" in html
    assert 'name="class_name"' in html
    assert 'name="device_id"' in html
    assert 'capture="environment"' in html


def test_collection_page_is_available_alongside_classifier(client):
    r = client.get("/collect")

    assert r.status_code == 200
    assert "Training Photo Collection" in r.get_data(as_text=True)


def test_collection_classes_match_the_approved_training_taxonomy(client):
    r = client.get("/collection-classes")

    assert r.status_code == 200
    assert r.json == {"classes": [
        {"value": "0301_computer_mouse", "label": "Computer mouse"},
        {"value": "0301_keyboard", "label": "Computer keyboard"},
        {"value": "0303_laptop", "label": "Laptop"},
        {"value": "0306_mobile_phone", "label": "Mobile phone"},
        {"value": "0401_headphones", "label": "Headphones"},
    ]}


def test_collection_mode_reports_no_model_and_rejects_classification(tmp_path):
    app = create_app(ckpt_path=tmp_path / "missing.pt",
                     ingest_root=tmp_path / "photos",
                     collection_only=True)
    app.config["TESTING"] = True
    client = app.test_client()

    health = client.get("/health")
    classify = client.post("/classify",
                           data={"image": (_jpeg_bytes(), "x.jpg")},
                           content_type="multipart/form-data")

    assert health.status_code == 200
    assert health.json == {"model_loaded": False, "classes": [], "collection_only": True}
    assert classify.status_code == 503
    assert classify.json["error"] == "classification unavailable in collection mode"


def test_collect_flag_starts_collection_only_app(monkeypatch):
    calls = {}

    class NonBlockingApp:
        def run(self, **kwargs):
            calls["run"] = kwargs

    def fake_create_app(*, ckpt_path=None, ingest_root=None, collection_only=False):
        calls["ckpt_path"] = ckpt_path
        calls["ingest_root"] = ingest_root
        calls["collection_only"] = collection_only
        return NonBlockingApp()

    monkeypatch.setattr(app_module, "create_app", fake_create_app)
    monkeypatch.setattr(app_module, "print_access_urls", lambda port: calls.setdefault("port", port))

    app_module.main(["--collect", "--port", "9123"])

    assert calls == {
        "ckpt_path": None,
        "ingest_root": None,
        "collection_only": True,
        "port": 9123,
        "run": {"host": "::", "port": 9123, "threaded": False},
    }


def test_collect_flag_can_target_the_holdout_folder(monkeypatch, tmp_path):
    calls = {}

    class NonBlockingApp:
        def run(self, **kwargs):
            calls["run"] = kwargs

    def fake_create_app(*, ckpt_path=None, ingest_root=None, collection_only=False):
        calls["ingest_root"] = ingest_root
        calls["collection_only"] = collection_only
        return NonBlockingApp()

    monkeypatch.setattr(app_module, "create_app", fake_create_app)
    monkeypatch.setattr(app_module, "print_access_urls", lambda port: None)

    app_module.main(["--collect", "--ingest-root", str(tmp_path / "holdout")])

    assert calls["ingest_root"] == str(tmp_path / "holdout")
    assert calls["collection_only"] is True


def test_classify_returns_a_class(client):
    r = client.post("/classify", data={"image": (_jpeg_bytes(), "x.jpg")},
                    content_type="multipart/form-data")
    assert r.status_code == 200
    assert r.json["class_name"] in ("0301_small_it", "0306_mobile_phones")
    assert "confidence" in r.json


def test_legacy_classify_accepts_an_injected_classifier_without_history(tmp_path):
    class InjectedClassifier:
        arch = "injected"
        classes = ["custom_class"]

        def classify(self, image):
            return {
                "class_name": "custom_class",
                "unu_key": None,
                "confidence": 0.75,
                "low_confidence": False,
                "topk": [{"class_name": "custom_class", "confidence": 0.75}],
            }

    app = create_app(
        ckpt_path=tmp_path / "missing.pt",
        classifier=InjectedClassifier(),
        history_store=None,
    )
    app.config["TESTING"] = True

    response = app.test_client().post(
        "/classify",
        data={"image": (_jpeg_bytes(), "x.jpg")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.json == {
        "advice": "Class name has no 4-digit UNU-KEY prefix; cannot estimate value.",
        "class_name": "custom_class",
        "confidence": 0.75,
        "low_confidence": False,
        "topk": [{"class_name": "custom_class", "confidence": 0.75}],
        "unu_key": None,
    }


def test_classify_rejects_a_non_image(client):
    r = client.post("/classify", data={"image": (io.BytesIO(b"not an image"), "x.jpg")},
                    content_type="multipart/form-data")
    assert r.status_code == 400
    assert "error" in r.json


def test_classify_without_a_file_is_a_400(client):
    r = client.post("/classify", data={}, content_type="multipart/form-data")
    assert r.status_code == 400


def test_classify_rejects_images_over_the_shared_pixel_limit(client, monkeypatch):
    def reject_large_image(_image):
        raise ImageTooLarge("image exceeds 40,000,000 pixels")

    monkeypatch.setattr(client.application.config["CLASSIFIER"], "classify", reject_large_image)

    r = client.post("/classify", data={"image": (_jpeg_bytes(), "x.jpg")},
                    content_type="multipart/form-data")

    assert r.status_code == 413
    assert r.json == {"error": "image exceeds 40,000,000 pixels"}


def test_ingest_writes_into_the_class_folder(client, tmp_path):
    r = client.post("/ingest",
                    data={"image": (_jpeg_bytes(), "x.jpg"),
                          "class_name": "0306_mobile_phone",
                          "device_id": "dev01"},
                    content_type="multipart/form-data")
    assert r.status_code == 200
    written = list((tmp_path / "photos" / "0306_mobile_phone").glob("dev01_*.jpg"))
    assert len(written) == 1


def test_ingest_physically_applies_exif_orientation(client, tmp_path):
    r = client.post("/ingest",
                    data={"image": (_oriented_jpeg_bytes(), "x.jpg"),
                          "class_name": "0306_mobile_phone",
                          "device_id": "dev01"},
                    content_type="multipart/form-data")

    assert r.status_code == 200
    written = next((tmp_path / "photos" / "0306_mobile_phone").glob("dev01_*.jpg"))
    with Image.open(written) as saved:
        assert saved.size == (20, 40)


def test_ingest_uses_the_next_numeric_suffix_without_overwriting_a_gap(client, tmp_path):
    """Deleting a middle shot must not make the next upload overwrite a later shot."""
    folder = tmp_path / "photos" / "0306_mobile_phone"
    folder.mkdir(parents=True)
    (folder / "dev01_000.jpg").write_bytes(b"zero")
    existing_later = folder / "dev01_002.jpg"
    existing_later.write_bytes(b"preserve me")

    r = client.post("/ingest",
                    data={"image": (_jpeg_bytes(), "x.jpg"),
                          "class_name": "0306_mobile_phone",
                          "device_id": "dev01"},
                    content_type="multipart/form-data")

    assert r.status_code == 200
    assert r.json["saved"] == "0306_mobile_phone/dev01_003.jpg"
    assert existing_later.read_bytes() == b"preserve me"
    assert (folder / "dev01_003.jpg").exists()


def test_ingest_rejects_a_path_traversing_class_name(client):
    r = client.post("/ingest",
                    data={"image": (_jpeg_bytes(), "x.jpg"),
                          "class_name": "../../etc",
                          "device_id": "dev01"},
                    content_type="multipart/form-data")
    assert r.status_code == 400


def test_ingest_rejects_a_regex_safe_but_unapproved_class(client):
    r = client.post("/ingest",
                    data={"image": (_jpeg_bytes(), "x.jpg"),
                          "class_name": "9999_typo_class",
                          "device_id": "dev01"},
                    content_type="multipart/form-data")

    assert r.status_code == 400
    assert "approved" in r.json["error"]


@pytest.mark.parametrize("bad", ["..", ".", "...", ".hidden"])
def test_ingest_rejects_dot_only_names(client, bad):
    """A bare '..' matched the original regex and escaped one directory level."""
    r = client.post("/ingest",
                    data={"image": (_jpeg_bytes(), "x.jpg"),
                          "class_name": bad, "device_id": "dev01"},
                    content_type="multipart/form-data")
    assert r.status_code == 400


def test_ingest_rejects_dot_only_device_id(client):
    r = client.post("/ingest",
                    data={"image": (_jpeg_bytes(), "x.jpg"),
                          "class_name": "0306_mobile_phone", "device_id": ".."},
                    content_type="multipart/form-data")
    assert r.status_code == 400


def test_ingest_rejects_device_id_with_underscore(client):
    """The splitter uses the first underscore as the device/photo boundary."""
    r = client.post("/ingest",
                    data={"image": (_jpeg_bytes(), "x.jpg"),
                          "class_name": "0306_mobile_phone", "device_id": "phone_01"},
                    content_type="multipart/form-data")

    assert r.status_code == 400
    assert "underscore" in r.json["error"]


def test_ingest_writes_nothing_outside_the_root(client, tmp_path):
    """Regression: a rejected name must not create anything above the ingest root."""
    before = set(tmp_path.rglob("*"))
    client.post("/ingest",
                data={"image": (_jpeg_bytes(), "x.jpg"),
                      "class_name": "..", "device_id": "dev01"},
                content_type="multipart/form-data")
    created = set(tmp_path.rglob("*")) - before
    assert created == set(), f"rejected request still created: {sorted(created)}"


def test_web_and_cli_agree_on_the_same_image(client, ckpt, tmp_path, monkeypatch):
    """The /classify endpoint and the Classifier used by the CLI must agree exactly."""
    from server.classifier import Classifier

    img_path = tmp_path / "sample.jpg"
    Image.new("RGB", (300, 300), (100, 140, 90)).save(img_path, format="JPEG")

    with open(img_path, "rb") as fh:
        web = client.post("/classify", data={"image": (fh, "sample.jpg")},
                          content_type="multipart/form-data").json

    cli = Classifier(ckpt).classify(Image.open(img_path))

    assert web["class_name"] == cli["class_name"]
    assert web["confidence"] == pytest.approx(cli["confidence"], abs=1e-6)


def test_demo_lists_the_pre_shot_photos(ckpt, tmp_path):
    shots = tmp_path / "demo"
    shots.mkdir()
    for name in ("02.jpg", "01.jpg"):
        Image.new("RGB", (10, 10)).save(shots / name, format="JPEG")

    app = create_app(ckpt_path=ckpt, ingest_root=tmp_path / "photos", demo_dir=shots)
    r = app.test_client().get("/demo")
    assert r.status_code == 200
    assert r.json["demo_photos"] == ["01.jpg", "02.jpg"]
    assert r.json["count"] == 2


def test_demo_works_without_an_explicit_dir(client):
    """demo_dir defaults to data/demo_photos, which may hold nothing yet."""
    r = client.get("/demo")
    assert r.status_code == 200
    assert r.json["count"] == len(r.json["demo_photos"])

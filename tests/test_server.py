import io

import pytest
import torch
import torch.nn as nn
from PIL import Image
from torchvision import models

from server.app import create_app


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


def test_classify_returns_a_class(client):
    r = client.post("/classify", data={"image": (_jpeg_bytes(), "x.jpg")},
                    content_type="multipart/form-data")
    assert r.status_code == 200
    assert r.json["class_name"] in ("0301_small_it", "0306_mobile_phones")
    assert "confidence" in r.json


def test_classify_rejects_a_non_image(client):
    r = client.post("/classify", data={"image": (io.BytesIO(b"not an image"), "x.jpg")},
                    content_type="multipart/form-data")
    assert r.status_code == 400
    assert "error" in r.json


def test_classify_without_a_file_is_a_400(client):
    r = client.post("/classify", data={}, content_type="multipart/form-data")
    assert r.status_code == 400


def test_ingest_writes_into_the_class_folder(client, tmp_path):
    r = client.post("/ingest",
                    data={"image": (_jpeg_bytes(), "x.jpg"),
                          "class_name": "0306_mobile_phones",
                          "device_id": "dev01"},
                    content_type="multipart/form-data")
    assert r.status_code == 200
    written = list((tmp_path / "photos" / "0306_mobile_phones").glob("dev01_*.jpg"))
    assert len(written) == 1


def test_ingest_rejects_a_path_traversing_class_name(client):
    r = client.post("/ingest",
                    data={"image": (_jpeg_bytes(), "x.jpg"),
                          "class_name": "../../etc",
                          "device_id": "dev01"},
                    content_type="multipart/form-data")
    assert r.status_code == 400


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
                          "class_name": "0306_mobile_phones", "device_id": ".."},
                    content_type="multipart/form-data")
    assert r.status_code == 400


def test_ingest_writes_nothing_outside_the_root(client, tmp_path):
    """Regression: a rejected name must not create anything above the ingest root."""
    before = set(tmp_path.rglob("*"))
    client.post("/ingest",
                data={"image": (_jpeg_bytes(), "x.jpg"),
                      "class_name": "..", "device_id": "dev01"},
                content_type="multipart/form-data")
    created = set(tmp_path.rglob("*")) - before
    assert created == set(), f"rejected request still created: {sorted(created)}"

import io
import json
import hashlib
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path
from urllib.request import urlopen

from PIL import Image

import pytest

from desktop.main import (
    ModelStartupError,
    ReferenceDataStartupError,
    build_desktop_app,
    build_recovery_app,
    run,
)
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
    manifest = SimpleNamespace(artifact_sha256="a" * 64)

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
    assert client.get("/static/collect.html").status_code == 404
    assert client.get("/static/app.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/").status_code == 200
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
    assert "Model bundle: missing" in webview.page
    assert "Traceback" not in webview.page


def test_unexpected_desktop_initialization_error_is_not_mislabeled_as_recovery(
    monkeypatch, tmp_path
):
    paths = AppPaths(
        resources_dir=tmp_path / "resources", static_dir=tmp_path / "static",
        model_bundle_dir=tmp_path / "model", reference_dir=tmp_path / "reference",
        data_dir=tmp_path / "support", history_database_path=tmp_path / "support/history.sqlite",
        history_media_dir=tmp_path / "support/media",
    )
    monkeypatch.setattr("desktop.main.build_desktop_app", lambda paths: (_ for _ in ()).throw(PermissionError("denied")))

    with pytest.raises(PermissionError, match="denied"):
        run(webview_module=FakeWebview(), paths=paths)


def test_unrelated_onnx_constructor_runtime_error_propagates(monkeypatch, tmp_path):
    paths = AppPaths(
        resources_dir=tmp_path / "resources", static_dir=tmp_path / "static",
        model_bundle_dir=tmp_path / "model", reference_dir=tmp_path / "reference",
        data_dir=tmp_path / "support", history_database_path=tmp_path / "support/history.sqlite",
        history_media_dir=tmp_path / "support/media",
    )

    def unrelated_bug(_bundle_dir):
        raise RuntimeError("unexpected constructor bug")

    monkeypatch.setattr("desktop.main.OnnxClassifier", unrelated_bug)

    with pytest.raises(RuntimeError, match="unexpected constructor bug"):
        run(webview_module=FakeWebview(), paths=paths)


def test_invalid_reference_database_opens_reference_specific_recovery(
    monkeypatch, tmp_path
):
    paths = AppPaths(
        resources_dir=tmp_path / "resources", static_dir=tmp_path / "static",
        model_bundle_dir=tmp_path / "model", reference_dir=tmp_path / "reference",
        data_dir=tmp_path / "support", history_database_path=tmp_path / "support/history.sqlite",
        history_media_dir=tmp_path / "support/media",
    )
    webview = FakeWebview()
    monkeypatch.setattr("desktop.main.OnnxClassifier", lambda _path: FakeClassifier())

    assert run(webview_module=webview, paths=paths) == 0

    assert "component reference data could not be loaded" in webview.page.lower()
    assert "Reference database: unavailable or incompatible" in webview.page
    assert "included model could not be loaded" not in webview.page
    assert str(paths.reference_database_path) not in webview.page
    assert "Traceback" not in webview.page


def test_reference_store_closes_when_later_app_assembly_fails(monkeypatch, tmp_path):
    paths = AppPaths(
        resources_dir=tmp_path / "resources", static_dir=tmp_path / "static",
        model_bundle_dir=tmp_path / "model", reference_dir=tmp_path / "reference",
        data_dir=tmp_path / "support", history_database_path=tmp_path / "support/history.sqlite",
        history_media_dir=tmp_path / "support/media",
    )
    closed = []

    class OwnedReference:
        def close(self):
            closed.append(True)

    monkeypatch.setattr("desktop.main.OnnxClassifier", lambda _path: FakeClassifier())
    monkeypatch.setattr("desktop.main.ReferenceStore", lambda _path: OwnedReference())
    monkeypatch.setattr(
        "server.desktop_app.create_desktop_app",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("assembly bug")),
    )

    with pytest.raises(RuntimeError, match="assembly bug"):
        build_desktop_app(paths)

    assert closed == [True]


def test_strict_packaged_assembly_anchors_reference_to_release_manifest(
    monkeypatch, tmp_path
):
    resources = tmp_path / "resources"
    reference_dir = resources / "reference"
    release_dir = resources / "release"
    reference_dir.mkdir(parents=True)
    release_dir.mkdir(parents=True)
    database = reference_dir / "components.sqlite"
    database.write_bytes(b"component bytes")
    database_sha = hashlib.sha256(database.read_bytes()).hexdigest()
    release_manifest = {
        "schema_version": 1,
        "app_version": "1.2.3",
        "model": {
            "model_id": "release-model-1",
            "artifact_sha256": "a" * 64,
            "manifest_sha256": "c" * 64,
            "labels_sha256": "d" * 64,
            "schema_version": 1,
        },
        "components": {
            "sha256": database_sha,
            "content_sha256": "b" * 64,
            "schema_version": 2,
            "version": "2.0.0",
        },
        "target": {"architecture": "arm64", "minimum_macos": "14.0"},
        "created_at": "2026-09-06T12:00:00+00:00",
        "parity": {
            "schema_version": 1, "status": "passed", "model_id": "release-model-1",
            "model_sha256": "a" * 64,
            "labels": ["0301_computer_mouse", "0301_keyboard", "0303_laptop", "0306_mobile_phone", "0401_headphones"],
            "metrics": {"reference_images": 5, "top1_matches": 5, "max_probability_delta": 0.0},
            "holdout": {"status": "passed", "split": "holdout", "valid": True, "overlaps_training": False, "samples": 25},
        },
    }
    manifest_path = release_dir / "release-manifest.json"
    manifest_path.write_text(json.dumps(release_manifest, sort_keys=True))
    (resources / "build-metadata.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "app_version": "1.2.3",
                "source_revision": "a" * 40,
                "release_manifest_sha256": hashlib.sha256(
                    manifest_path.read_bytes()
                ).hexdigest(),
            }
        )
    )
    paths = AppPaths(
        resources_dir=resources,
        static_dir=resources / "server/static",
        model_bundle_dir=resources / "models/production",
        reference_dir=reference_dir,
        data_dir=tmp_path / "support",
        history_database_path=tmp_path / "support/history.sqlite",
        history_media_dir=tmp_path / "support/media",
    )
    calls = []

    class OwnedReference:
        def close(self):
            pass

    def open_reference(path, **expectations):
        calls.append((path, expectations))
        return OwnedReference()

    monkeypatch.setattr("desktop.main.OnnxClassifier", lambda _path: FakeClassifier())
    monkeypatch.setattr("desktop.main.ReferenceStore", open_reference)

    app = build_desktop_app(paths, require_release_integrity=True)

    assert calls == [
        (
            database,
            {
                "expected_sha256": database_sha,
                "expected_content_sha256": "b" * 64,
                "expected_schema_version": 2,
                "expected_version": "2.0.0",
            },
        )
    ]
    app.extensions["close_reference_store"]()


def test_strict_packaged_assembly_rejects_manifest_not_anchored_by_build_metadata(
    monkeypatch, tmp_path
):
    resources = tmp_path / "resources"
    (resources / "release").mkdir(parents=True)
    (resources / "release/release-manifest.json").write_text("{}")
    (resources / "build-metadata.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "app_version": "1.2.3",
                "source_revision": "a" * 40,
                "release_manifest_sha256": "0" * 64,
            }
        )
    )
    paths = AppPaths(
        resources_dir=resources,
        static_dir=resources / "server/static",
        model_bundle_dir=resources / "models/production",
        reference_dir=resources / "reference",
        data_dir=tmp_path / "support",
        history_database_path=tmp_path / "support/history.sqlite",
        history_media_dir=tmp_path / "support/media",
    )
    monkeypatch.setattr("desktop.main.OnnxClassifier", lambda _path: FakeClassifier())
    monkeypatch.setattr("desktop.main.ReferenceStore", lambda _path, **_expectations: SimpleNamespace(close=lambda: None))

    with pytest.raises(ReferenceDataStartupError, match="unavailable or incompatible"):
        build_desktop_app(paths, require_release_integrity=True)


def test_strict_packaged_assembly_rejects_invalid_build_source_revision(
    monkeypatch, tmp_path
):
    """A displayable release must have an immutable Git-shaped source identity."""
    resources = tmp_path / "resources"
    reference_dir = resources / "reference"
    release_dir = resources / "release"
    reference_dir.mkdir(parents=True)
    release_dir.mkdir(parents=True)
    database = reference_dir / "components.sqlite"
    database.write_bytes(b"component bytes")
    manifest = {
        "schema_version": 1,
        "app_version": "1.2.3",
        "model": {
            "model_id": "release-model-1",
            "artifact_sha256": "a" * 64,
            "manifest_sha256": "b" * 64,
            "labels_sha256": "c" * 64,
            "schema_version": 1,
        },
        "components": {
            "sha256": hashlib.sha256(database.read_bytes()).hexdigest(),
            "content_sha256": "d" * 64,
            "schema_version": 2,
            "version": "2.0.0",
        },
        "target": {},
        "created_at": "2026-09-06T12:00:00+00:00",
        "parity": {},
    }
    manifest_path = release_dir / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True))
    (resources / "build-metadata.json").write_text(json.dumps({
        "schema_version": 1,
        "app_version": "1.2.3",
        "source_revision": "A" * 40,
        "release_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    }))
    paths = AppPaths(
        resources_dir=resources, static_dir=resources / "server/static",
        model_bundle_dir=resources / "models/production", reference_dir=reference_dir,
        data_dir=tmp_path / "support", history_database_path=tmp_path / "support/history.sqlite",
        history_media_dir=tmp_path / "support/media",
    )
    monkeypatch.setattr("desktop.main.OnnxClassifier", lambda _path: FakeClassifier())
    monkeypatch.setattr("desktop.main.ReferenceStore", lambda _path, **_expectations: SimpleNamespace(close=lambda: None))

    with pytest.raises(ReferenceDataStartupError, match="unavailable or incompatible"):
        build_desktop_app(paths, require_release_integrity=True)


def test_strict_packaged_assembly_rejects_classifier_from_another_valid_release(
    monkeypatch, tmp_path
):
    """Changing a valid model artifact must not leave About claiming this release."""
    resources = tmp_path / "resources"
    reference_dir = resources / "reference"
    release_dir = resources / "release"
    reference_dir.mkdir(parents=True)
    release_dir.mkdir(parents=True)
    database = reference_dir / "components.sqlite"
    database.write_bytes(b"component bytes")
    manifest = {
        "schema_version": 1,
        "app_version": "1.2.3",
        "model": {
            "model_id": "release-model-1",
            "artifact_sha256": "a" * 64,
            "manifest_sha256": "b" * 64,
            "labels_sha256": "c" * 64,
            "schema_version": 1,
        },
        "components": {
            "sha256": hashlib.sha256(database.read_bytes()).hexdigest(),
            "content_sha256": "d" * 64,
            "schema_version": 2,
            "version": "2.0.0",
        },
        "target": {"architecture": "arm64", "minimum_macos": "14.0"},
        "created_at": "2026-09-06T12:00:00+00:00",
        "parity": {
            "schema_version": 1, "status": "passed", "model_id": "release-model-1",
            "model_sha256": "a" * 64,
            "labels": ["0301_computer_mouse", "0301_keyboard", "0303_laptop", "0306_mobile_phone", "0401_headphones"],
            "metrics": {"reference_images": 5, "top1_matches": 5, "max_probability_delta": 0.0},
            "holdout": {"status": "passed", "split": "holdout", "valid": True, "overlaps_training": False, "samples": 25},
        },
    }
    manifest_path = release_dir / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True))
    (resources / "build-metadata.json").write_text(json.dumps({
        "schema_version": 1,
        "app_version": "1.2.3",
        "source_revision": "a" * 40,
        "release_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    }))
    paths = AppPaths(
        resources_dir=resources, static_dir=resources / "server/static",
        model_bundle_dir=resources / "models/production", reference_dir=reference_dir,
        data_dir=tmp_path / "support", history_database_path=tmp_path / "support/history.sqlite",
        history_media_dir=tmp_path / "support/media",
    )
    classifier = FakeClassifier()
    classifier.manifest = SimpleNamespace(artifact_sha256="e" * 64)
    monkeypatch.setattr("desktop.main.OnnxClassifier", lambda _path: classifier)
    monkeypatch.setattr("desktop.main.ReferenceStore", lambda _path, **_expectations: SimpleNamespace(close=lambda: None))

    with pytest.raises(ModelStartupError, match="unavailable or incompatible"):
        build_desktop_app(paths, require_release_integrity=True)


def test_release_metadata_api_returns_only_the_validated_display_contract(tmp_path):
    """The About surface exposes no bundle paths or implementation metadata."""
    app = _desktop_app(tmp_path)
    expected = {
        "app_version": "1.2.3",
        "source_revision": "a" * 40,
        "model_sha256": "b" * 64,
        "component_database_sha256": "c" * 64,
        "component_database_version": "2.0.0",
    }
    app.config["RELEASE_METADATA"] = SimpleNamespace(
        public_payload=lambda: expected
    )

    response = app.test_client().get("/api/v1/release-metadata")

    assert response.status_code == 200
    assert response.get_json() == expected


def test_development_release_metadata_api_fails_closed_without_invented_values(tmp_path):
    response = _desktop_app(tmp_path).test_client().get("/api/v1/release-metadata")

    assert response.status_code == 503
    assert response.get_json() == {"error": "release metadata is unavailable"}


def test_recovery_diagnostics_are_supplied_from_runtime_metadata():
    page = build_recovery_app(app_version="2026.9.6", model_diagnostic="bundle r17").test_client().get("/").get_data(as_text=True)

    assert "App version: 2026.9.6" in page
    assert "Model bundle: bundle r17" in page


def test_recovery_uses_packaged_build_and_readable_model_metadata(tmp_path):
    resources = tmp_path / "resources"
    bundle = resources / "models" / "production"
    bundle.mkdir(parents=True)
    model = bundle / "model.onnx"
    model.write_bytes(b"not a valid ONNX graph")
    (bundle / "manifest.json").write_text(json.dumps({
        "model_id": "release-2026.09",
        "architecture": "resnet18",
        "classes": ["0306_mobile_phone"],
        "preprocessing_version": "rgb-224-v1",
        "confidence_floor": 0.6,
        "artifact_sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
        "schema_version": 1,
        "metrics": {},
    }))
    (resources / "build-metadata.json").write_text(json.dumps({"app_version": "1.4.2"}))
    paths = AppPaths(
        resources_dir=resources, static_dir=resources / "server/static",
        model_bundle_dir=bundle, reference_dir=resources / "reference",
        data_dir=tmp_path / "support", history_database_path=tmp_path / "support/history.sqlite",
        history_media_dir=tmp_path / "support/media",
    )
    webview = FakeWebview()

    assert run(webview_module=webview, paths=paths) == 0

    assert "App version: 1.4.2" in webview.page
    assert "Model bundle: release-2026.09 (schema 1)" in webview.page


def test_recovery_uses_sanitized_missing_manifest_state(tmp_path):
    resources = tmp_path / "resources"
    paths = AppPaths(
        resources_dir=resources, static_dir=resources / "server/static",
        model_bundle_dir=resources / "models/production", reference_dir=resources / "reference",
        data_dir=tmp_path / "support", history_database_path=tmp_path / "support/history.sqlite",
        history_media_dir=tmp_path / "support/media",
    )
    webview = FakeWebview()

    assert run(webview_module=webview, paths=paths) == 0

    assert "Model bundle: missing" in webview.page
    assert str(paths.model_bundle_dir) not in webview.page

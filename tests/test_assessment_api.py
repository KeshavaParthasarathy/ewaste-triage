import copy
import json
import urllib.request

from PIL import Image

from server.desktop_app import create_desktop_app
from server.history import HistoryStore
from server.reference_db import ReferenceStore, compile_reference
from desktop.server_thread import ServerThread
from pathlib import Path


PREDICTION = {
    "class_name": "0306_mobile_phone",
    "confidence": 0.91,
    "low_confidence": False,
    "topk": [{"class_name": "0306_mobile_phone", "confidence": 0.91}, {"class_name": "0303_laptop", "confidence": 0.09}],
}


class FakeClassifier:
    arch = "test"
    classes = ["0306_mobile_phone"]


class MutableReference:
    def __init__(self):
        self.version = "1.0.0"

    def list_categories(self):
        return [{"category_id": "0306_mobile_phone", "display_name": "Mobile phone"}]

    def get_category(self, category_id):
        return self.list_categories()[0] if category_id == "0306_mobile_phone" else None

    def snapshot(self, category_id):
        if category_id != "0306_mobile_phone":
            raise KeyError(category_id)
        return {
            "category_id": category_id,
            "display_name": "Mobile phone",
            "template_version": self.version,
            "components": [{
                "component_id": "battery",
                "display_name": "Battery",
                "presence_label": "standard",
                "lifecycle": {"metric": "years", "minimum": 4, "maximum": 6, "source_ids": ["source"]},
                "source_ids": ["source"],
                "evidence_grade": "regulatory",
                "reviewed_on": "2026-09-05",
                "safety_sensitive": True,
                "notes": [],
            }],
            "rules": [],
            "handling_note": "Potential context, not a claim.",
            "source_ids": ["source"],
        }


def make_client(tmp_path):
    store = HistoryStore(tmp_path / "history.sqlite", tmp_path / "media")
    reference = MutableReference()
    app = create_desktop_app(classifier=FakeClassifier(), history_store=store, reference_store=reference)
    app.config["TESTING"] = True
    scan_id = store.add_scan(PREDICTION, Image.new("RGB", (10, 10)), retain_original=False, original=None)
    return app.test_client(), store, reference, scan_id


def test_reference_category_endpoints_are_desktop_product_endpoints(tmp_path):
    client, _, _, _ = make_client(tmp_path)

    listed = client.get("/api/v1/reference/categories")
    detail = client.get("/api/v1/reference/categories/0306_mobile_phone")

    assert listed.status_code == 200
    assert listed.json[0]["category_id"] == "0306_mobile_phone"
    assert detail.status_code == 200
    assert detail.json["components"][0]["component_id"] == "battery"
    assert client.get("/api/v1/reference/categories/missing").status_code == 404


def test_assessment_is_gated_by_category_acceptance_then_immutable(tmp_path):
    client, _, reference, scan_id = make_client(tmp_path)

    assert client.get(f"/api/v1/scans/{scan_id}/assessment").status_code == 409
    confirmed = client.put(
        f"/api/v1/history/{scan_id}/confirmation",
        json={"accepted_class_name": "0306_mobile_phone"},
    )
    assert confirmed.status_code == 200
    first = client.get(f"/api/v1/scans/{scan_id}/assessment")
    reference.version = "2.0.0"
    reference.snapshot = lambda _category_id: {**MutableReference().snapshot("0306_mobile_phone"), "template_version": "2.0.0", "components": []}
    second = client.get(f"/api/v1/scans/{scan_id}/assessment")

    assert first.status_code == second.status_code == 200
    assert first.json["template_version"] == second.json["template_version"] == "1.0.0"
    assert first.json["components"] == second.json["components"]
    assert first.json["template"]["components"][0]["component_id"] == "battery"
    assert "component_overrides" not in first.json["inputs"]
    assert client.put(f"/api/v1/history/{scan_id}/confirmation", json={"accepted_class_name": "0303_laptop"}).status_code == 409


def test_assessment_payload_and_scan_errors_are_strict(tmp_path):
    client, _, _, scan_id = make_client(tmp_path)
    client.put(f"/api/v1/history/{scan_id}/confirmation", json={"accepted_class_name": "0306_mobile_phone"})

    invalid_enum = client.put(f"/api/v1/scans/{scan_id}/assessment", json={"usage": "extreme"})
    invalid_range = client.put(f"/api/v1/scans/{scan_id}/assessment", json={"age_months": {"minimum": 5, "maximum": 4}})
    unknown_component = client.put(f"/api/v1/scans/{scan_id}/assessment", json={"component_overrides": {"missing": {}}})
    invalid_lifecycle = client.put(f"/api/v1/scans/{scan_id}/assessment", json={"component_overrides": {"battery": {"lifecycle": {"metric": "years", "minimum": 0, "maximum": 2, "source_ids": ["manual"], "evidence_grade": "documented", "reviewed_on": "2026-09-06"}}}})
    forbidden_safety = client.put(f"/api/v1/scans/{scan_id}/assessment", json={"component_overrides": {"battery": {"safety_sensitive": False}}})
    unknown = client.put("/api/v1/scans/missing/assessment", json={})
    valid = client.put(f"/api/v1/scans/{scan_id}/assessment", json={"age_months": {"minimum": 24, "maximum": 36}, "usage": "heavy", "condition": "no_visible_damage", "component_overrides": {"battery": {"presence_label": "standard"}}})

    assert invalid_enum.status_code == 400
    assert invalid_range.status_code == 422
    assert unknown_component.status_code == 400
    assert invalid_lifecycle.status_code == 422
    assert forbidden_safety.status_code == 400
    assert unknown.status_code == 404
    assert valid.status_code == 200
    assert valid.json["inputs"]["usage"] == "heavy"
    assert valid.json["components"][0]["result"]["percent_used"] == {"minimum": 33, "maximum": 75}
    assert valid.json["component_overrides"] == {"battery": {"presence_label": "standard"}}


def test_real_compiled_reference_works_over_threaded_http(tmp_path):
    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "components.sqlite"
    compile_reference(root / "reference", database)
    references = ReferenceStore(database)
    history = HistoryStore(tmp_path / "history.sqlite", tmp_path / "media")
    scan_id = history.add_scan(PREDICTION, Image.new("RGB", (10, 10)), retain_original=False, original=None)
    history.set_confirmation(scan_id, "0306_mobile_phone")
    app = create_desktop_app(classifier=FakeClassifier(), history_store=history, reference_store=references)
    server = ServerThread(app)
    url = server.start_and_wait()
    try:
        with urllib.request.urlopen(f"{url}/api/v1/reference/categories") as response:
            assert response.status == 200
        request = urllib.request.Request(
            f"{url}/api/v1/scans/{scan_id}/assessment",
            data=json.dumps({"cycle_count": {"minimum": 200, "maximum": 400}, "condition": "no_visible_damage"}).encode(),
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        with urllib.request.urlopen(request) as response:
            assessment = json.load(response)
        battery = next(item for item in assessment["components"] if item["component_id"] == "lithium_ion_battery")
        assert battery["result"]["percent_used"] == {"minimum": 25, "maximum": 50}
        assert battery["result"]["recommendation"] != "specialist_handling"
    finally:
        server.shutdown()
        references.close()

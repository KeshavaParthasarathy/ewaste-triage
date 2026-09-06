import copy
import json
import math
import sqlite3
import urllib.request

from PIL import Image
import pytest

from server.desktop_app import create_desktop_app
from server.history import HistoryStore
from server.lifecycle import assess_component
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


def test_initial_assessment_computation_failure_leaves_no_empty_record(tmp_path):
    client, store, _, scan_id = make_client(tmp_path)
    client.put(
        f"/api/v1/history/{scan_id}/confirmation",
        json={"accepted_class_name": "0306_mobile_phone"},
    )
    client.application.config["LIFECYCLE_ASSESSOR"] = lambda *_: (_ for _ in ()).throw(
        RuntimeError("calculation failed")
    )

    with pytest.raises(RuntimeError, match="calculation failed"):
        client.get(f"/api/v1/scans/{scan_id}/assessment")

    assert store.get_assessment(scan_id) is None


def test_first_assessment_update_computes_once_and_returns_the_atomic_creation(tmp_path):
    client, store, _, scan_id = make_client(tmp_path)
    client.put(
        f"/api/v1/history/{scan_id}/confirmation",
        json={"accepted_class_name": "0306_mobile_phone"},
    )
    calls = 0

    def assessor(component, inputs):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise RuntimeError("assessment was recomputed after creation")
        return assess_component(component, inputs)

    client.application.config["LIFECYCLE_ASSESSOR"] = assessor

    response = client.put(
        f"/api/v1/scans/{scan_id}/assessment",
        json={"usage": "heavy"},
    )

    assert response.status_code == 200
    assert calls == 1
    assert response.json == store.get_assessment(scan_id)
    assert response.json["inputs"]["usage"] == "heavy"


def test_first_assessment_update_computation_failure_leaves_no_record(tmp_path):
    client, store, _, scan_id = make_client(tmp_path)
    client.put(
        f"/api/v1/history/{scan_id}/confirmation",
        json={"accepted_class_name": "0306_mobile_phone"},
    )
    client.application.config["LIFECYCLE_ASSESSOR"] = lambda *_: (
        _ for _ in ()
    ).throw(RuntimeError("calculation failed"))

    with pytest.raises(RuntimeError, match="calculation failed"):
        client.put(
            f"/api/v1/scans/{scan_id}/assessment",
            json={"usage": "heavy"},
        )

    assert store.get_assessment(scan_id) is None


@pytest.mark.parametrize(
    ("payload", "expected_status"),
    [
        ({"usage": "not-a-supported-value"}, 400),
        ({"known_issues": {"notes": "x" * 501}}, 422),
        ({"known_issues": {"overheating": 1}}, 400),
        ({"component_overrides": {"not-in-template": {}}}, 400),
    ],
)
def test_invalid_first_assessment_update_does_not_create_a_default_snapshot(
    tmp_path, payload, expected_status
):
    client, store, _, scan_id = make_client(tmp_path)
    client.put(
        f"/api/v1/history/{scan_id}/confirmation",
        json={"accepted_class_name": "0306_mobile_phone"},
    )

    response = client.put(
        f"/api/v1/scans/{scan_id}/assessment",
        json=payload,
    )

    assert response.status_code == expected_status
    assert store.get_assessment(scan_id) is None


def test_repairable_legacy_empty_assessment_is_never_exposed(tmp_path):
    client, store, _, scan_id = make_client(tmp_path)
    client.put(
        f"/api/v1/history/{scan_id}/confirmation",
        json={"accepted_class_name": "0306_mobile_phone"},
    )
    template = MutableReference().snapshot("0306_mobile_phone")
    legacy = {
        "scan_id": scan_id,
        "category_id": "0306_mobile_phone",
        "template_version": "1.0.0",
        "template": template,
        "inputs": {},
        "component_overrides": {},
        "components": [],
    }
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            "INSERT INTO assessments VALUES (?, ?, ?, ?, ?)",
            (scan_id, "0306_mobile_phone", "1.0.0", json.dumps(legacy), "legacy"),
        )

    response = client.get(f"/api/v1/scans/{scan_id}/assessment")

    assert response.status_code == 200
    assert response.json["components"]
    assert store.get_assessment(scan_id)["components"]


def test_canonical_reference_category_outside_model_topk_can_be_confirmed(tmp_path):
    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "components.sqlite"
    compile_reference(root / "reference", database)
    references = ReferenceStore(database)
    history = HistoryStore(tmp_path / "history.sqlite", tmp_path / "media")
    scan_id = history.add_scan(
        PREDICTION,
        Image.new("RGB", (10, 10)),
        retain_original=False,
        original=None,
    )
    app = create_desktop_app(
        classifier=FakeClassifier(),
        history_store=history,
        reference_store=references,
    )
    app.config["TESTING"] = True
    client = app.test_client()

    invalid = client.put(
        f"/api/v1/history/{scan_id}/confirmation",
        json={"accepted_class_name": "9999_not_a_reference"},
    )
    response = client.put(
        f"/api/v1/history/{scan_id}/confirmation",
        json={"accepted_class_name": "0301_keyboard"},
    )

    assert invalid.status_code == 400
    assert invalid.json == {
        "error": "accepted category is not available in component references"
    }
    assert response.status_code == 200
    assert response.json["confirmation"] == {
        "accepted_class_name": "0301_keyboard",
        "source": "user",
    }
    assert response.json["prediction"] == PREDICTION
    assessment = client.get(f"/api/v1/scans/{scan_id}/assessment")
    assert assessment.status_code == 200
    assert assessment.json["category_id"] == "0301_keyboard"
    references.close()


def test_assessment_payload_and_scan_errors_are_strict(tmp_path):
    client, _, _, scan_id = make_client(tmp_path)
    client.put(f"/api/v1/history/{scan_id}/confirmation", json={"accepted_class_name": "0306_mobile_phone"})

    invalid_enum = client.put(f"/api/v1/scans/{scan_id}/assessment", json={"usage": "extreme"})
    invalid_range = client.put(f"/api/v1/scans/{scan_id}/assessment", json={"age_months": {"minimum": 5, "maximum": 4}})
    unknown_component = client.put(f"/api/v1/scans/{scan_id}/assessment", json={"component_overrides": {"missing": {}}})
    invalid_lifecycle = client.put(f"/api/v1/scans/{scan_id}/assessment", json={"component_overrides": {"battery": {"lifecycle": {"metric": "years", "minimum": 0, "maximum": 2}}}})
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


def test_known_issues_are_closed_bounded_persisted_and_drive_safety(tmp_path):
    client, _, _, scan_id = make_client(tmp_path)
    client.put(
        f"/api/v1/history/{scan_id}/confirmation",
        json={"accepted_class_name": "0306_mobile_phone"},
    )
    known_issues = {
        "overheating": True,
        "odor": False,
        "swelling_or_battery_damage": False,
        "recall": False,
        "notes": " Gets hot while charging. ",
    }

    saved = client.put(
        f"/api/v1/scans/{scan_id}/assessment",
        json={"known_issues": known_issues},
    )
    reopened = client.get(f"/api/v1/scans/{scan_id}/assessment")
    extra = client.put(
        f"/api/v1/scans/{scan_id}/assessment",
        json={"known_issues": {**known_issues, "other": True}},
    )
    too_long = client.put(
        f"/api/v1/scans/{scan_id}/assessment",
        json={"known_issues": {**known_issues, "notes": "x" * 501}},
    )

    assert saved.status_code == 200
    assert saved.json["inputs"]["known_issues"] == {
        **known_issues,
        "notes": "Gets hot while charging.",
    }
    assert reopened.json == saved.json
    result = saved.json["components"][0]["result"]
    assert result["recommendation"] == "specialist_handling"
    assert result["policy_revision"] == "1.0.0"
    assert any(item["kind"] == "user_known_issue" for item in result["evidence"])
    assert extra.status_code == 400
    assert too_long.status_code == 422


@pytest.mark.parametrize(
    "known_issues",
    (
        [],
        {"overheating": 1},
        {"odor": "yes"},
        {"swelling_or_battery_damage": None},
        {"recall": []},
        {"notes": 7},
    ),
)
def test_known_issue_types_are_strict_json_values(tmp_path, known_issues):
    client, _, _, scan_id = make_client(tmp_path)
    client.put(
        f"/api/v1/history/{scan_id}/confirmation",
        json={"accepted_class_name": "0306_mobile_phone"},
    )

    response = client.put(
        f"/api/v1/scans/{scan_id}/assessment",
        json={"known_issues": known_issues},
    )

    assert response.status_code == 400
    assert response.is_json


def test_known_issue_note_bound_counts_unicode_code_points(tmp_path):
    client, _, _, scan_id = make_client(tmp_path)
    client.put(
        f"/api/v1/history/{scan_id}/confirmation",
        json={"accepted_class_name": "0306_mobile_phone"},
    )

    accepted = client.put(
        f"/api/v1/scans/{scan_id}/assessment",
        json={"known_issues": {"notes": "😀" * 500}},
    )
    rejected = client.put(
        f"/api/v1/scans/{scan_id}/assessment",
        json={"known_issues": {"notes": "😀" * 501}},
    )

    assert accepted.status_code == 200
    assert accepted.json["inputs"]["known_issues"]["notes"] == "😀" * 500
    assert rejected.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"usage": []},
        {"condition": {}},
        {"component_overrides": {"battery": {"presence_label": []}}},
        {
            "component_overrides": {
                "battery": {
                    "lifecycle": {"metric": [], "minimum": 1, "maximum": 2}
                }
            }
        },
        {
            "component_overrides": {
                "battery": {
                    "lifecycle": {
                        "metric": "years",
                        "minimum": 1,
                        "maximum": 2,
                        "unexpected": {},
                    }
                }
            }
        },
    ],
)
def test_malformed_scalar_and_nested_lifecycle_values_return_json_400(tmp_path, payload):
    client, _, _, scan_id = make_client(tmp_path)
    client.put(
        f"/api/v1/history/{scan_id}/confirmation",
        json={"accepted_class_name": "0306_mobile_phone"},
    )

    response = client.put(f"/api/v1/scans/{scan_id}/assessment", json=payload)

    assert response.status_code == 400
    assert response.is_json
    assert set(response.json) == {"error"}


@pytest.mark.parametrize(
    "provenance",
    [
        {
            "source_ids": ["fabricated-source"],
            "evidence_grade": "regulatory",
            "reviewed_on": "2026-09-05",
        },
        {
            "source_ids": ["source"],
            "evidence_grade": "fabricated-grade",
            "reviewed_on": "2026-09-05",
        },
        {
            "source_ids": ["source"],
            "evidence_grade": "regulatory",
            "reviewed_on": "not-a-date",
        },
    ],
)
def test_user_lifecycle_override_cannot_fabricate_reference_provenance(
    tmp_path, provenance
):
    client, _, _, scan_id = make_client(tmp_path)
    client.put(
        f"/api/v1/history/{scan_id}/confirmation",
        json={"accepted_class_name": "0306_mobile_phone"},
    )
    lifecycle = {"metric": "years", "minimum": 2, "maximum": 3, **provenance}

    response = client.put(
        f"/api/v1/scans/{scan_id}/assessment",
        json={"component_overrides": {"battery": {"lifecycle": lifecycle}}},
    )

    assert response.status_code == 400
    assert response.is_json


def test_user_lifecycle_override_is_persisted_as_unverified_not_sourced(tmp_path):
    client, _, _, scan_id = make_client(tmp_path)
    client.put(
        f"/api/v1/history/{scan_id}/confirmation",
        json={"accepted_class_name": "0306_mobile_phone"},
    )

    override_lifecycle = {"metric": "years", "minimum": 2, "maximum": 3}
    response = client.put(
        f"/api/v1/scans/{scan_id}/assessment",
        json={
            "age_months": {"minimum": 12, "maximum": 12},
            "component_overrides": {
                "battery": {"lifecycle": override_lifecycle}
            },
        },
    )

    assert response.status_code == 200
    assert (
        response.json["component_overrides"]["battery"]["lifecycle"]
        == override_lifecycle
    )
    lifecycle = response.json["components"][0]["lifecycle"]
    assert lifecycle["source_ids"] == []
    assert lifecycle["evidence_grade"] == "user_provided_unverified"
    assert lifecycle["reviewed_on"] is None
    battery = response.json["components"][0]
    assert battery["result"]["percent_used"] is None
    assert battery["result"]["confidence"] == "unavailable"


def test_server_tagged_unverified_lifecycle_override_can_be_saved_unchanged(tmp_path):
    client, _, _, scan_id = make_client(tmp_path)
    client.put(
        f"/api/v1/history/{scan_id}/confirmation",
        json={"accepted_class_name": "0306_mobile_phone"},
    )
    first = client.put(
        f"/api/v1/scans/{scan_id}/assessment",
        json={
            "age_months": {"minimum": 12, "maximum": 12},
            "component_overrides": {
                "battery": {
                    "lifecycle": {"metric": "years", "minimum": 2, "maximum": 3}
                }
            },
        },
    )

    second = client.put(
        f"/api/v1/scans/{scan_id}/assessment",
        json={
            **first.json["inputs"],
            "component_overrides": first.json["component_overrides"],
        },
    )

    assert second.status_code == 200
    assert second.json["component_overrides"] == first.json["component_overrides"]
    assert second.json["components"] == first.json["components"]


def test_cycles_to_capacity_override_round_trips_and_can_be_cleared(tmp_path):
    client, _, _, scan_id = make_client(tmp_path)
    client.put(
        f"/api/v1/history/{scan_id}/confirmation",
        json={"accepted_class_name": "0306_mobile_phone"},
    )
    override = {
        "metric": "cycles_to_capacity",
        "minimum": 700,
        "maximum": 900,
        "capacity_percent": 80,
    }

    first = client.put(
        f"/api/v1/scans/{scan_id}/assessment",
        json={"component_overrides": {"battery": {"lifecycle": override}}},
    )
    reopened = client.get(f"/api/v1/scans/{scan_id}/assessment")
    cleared = client.put(
        f"/api/v1/scans/{scan_id}/assessment",
        json={**first.json["inputs"], "component_overrides": {}},
    )

    assert first.status_code == 200
    assert first.json["component_overrides"] == {
        "battery": {"lifecycle": override}
    }
    assert reopened.json == first.json
    assert cleared.status_code == 200
    assert cleared.json["component_overrides"] == {}
    assert cleared.json["components"][0]["lifecycle"]["metric"] == "years"


@pytest.mark.parametrize(
    ("lifecycle", "status"),
    [
        ({"metric": "cycles_to_capacity", "minimum": 1, "maximum": 2}, 400),
        (
            {
                "metric": "years",
                "minimum": 1,
                "maximum": 2,
                "capacity_percent": 80,
            },
            400,
        ),
        ({"metric": "years", "minimum": math.nan, "maximum": 2}, 422),
        ({"metric": "cycles", "minimum": 1, "maximum": math.inf}, 422),
        ({"metric": "years", "minimum": 1, "maximum": 101}, 422),
        ({"metric": "cycles", "minimum": 1, "maximum": 1_000_001}, 422),
    ],
)
def test_lifecycle_override_rejects_invalid_metric_combinations_and_bounds(
    tmp_path, lifecycle, status
):
    client, _, _, scan_id = make_client(tmp_path)
    client.put(
        f"/api/v1/history/{scan_id}/confirmation",
        json={"accepted_class_name": "0306_mobile_phone"},
    )

    response = client.put(
        f"/api/v1/scans/{scan_id}/assessment",
        json={"component_overrides": {"battery": {"lifecycle": lifecycle}}},
    )

    assert response.status_code == status
    assert response.is_json


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
        assert battery["result"]["percent_used"] is None
        assert "total lifecycle" in " ".join(battery["result"]["reasons"]).lower()
        assert battery["result"]["recommendation"] != "specialist_handling"
    finally:
        server.shutdown()
        references.close()

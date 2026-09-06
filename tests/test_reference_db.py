"""Contracts for the compiled, read-only component reference release."""

from __future__ import annotations

import copy
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from server.reference_db import (
    ReferenceStore,
    ReferenceValidationError,
    compile_reference,
)


ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "0301_computer_mouse",
    "0301_keyboard",
    "0303_laptop",
    "0306_mobile_phone",
    "0401_headphones",
}


def copy_reference_fixture(destination: Path) -> dict:
    """Copy release YAML and return the editable component document."""
    destination.mkdir(parents=True, exist_ok=True)
    sources = yaml.safe_load((ROOT / "reference" / "sources.yaml").read_text())
    components = yaml.safe_load((ROOT / "reference" / "device_components.yaml").read_text())
    (destination / "sources.yaml").write_text(yaml.safe_dump(sources, sort_keys=False))
    (destination / "device_components.yaml").write_text(
        yaml.safe_dump(components, sort_keys=False)
    )
    return components


def write_component_fixture(destination: Path, document: dict) -> None:
    (destination / "device_components.yaml").write_text(
        yaml.safe_dump(document, sort_keys=False)
    )


def test_release_reference_contains_exactly_five_categories(tmp_path):
    manifest = compile_reference(ROOT / "reference", tmp_path / "components.sqlite")

    store = ReferenceStore(tmp_path / "components.sqlite")

    assert {row["category_id"] for row in store.list_categories()} == EXPECTED
    assert manifest.schema_version == 1
    assert manifest.version == "1.0.0"
    assert len(manifest.content_sha256) == 64


def test_non_null_lifecycle_requires_a_source(tmp_path):
    fixture = copy_reference_fixture(tmp_path)
    fixture["categories"][0]["components"][0]["lifecycle"] = {
        "metric": "cycles",
        "minimum": 800,
        "maximum": 800,
    }
    write_component_fixture(tmp_path, fixture)

    with pytest.raises(ReferenceValidationError, match=r"device_components\.yaml.*source_ids"):
        compile_reference(tmp_path, tmp_path / "bad.sqlite")


def test_release_only_has_the_documented_mobile_battery_lifecycle(tmp_path):
    compile_reference(ROOT / "reference", tmp_path / "components.sqlite")
    store = ReferenceStore(tmp_path / "components.sqlite")

    lifecycle_components = [
        component
        for category in store.list_categories()
        for component in store.snapshot(category["category_id"])["components"]
        if component["lifecycle"] is not None
    ]

    assert lifecycle_components == [
        {
            "component_id": "lithium_ion_battery",
            "display_name": "Lithium-ion battery",
            "presence_label": "standard",
            "lifecycle": {
                "metric": "cycles_to_capacity",
                "minimum": 800,
                "maximum": 800,
                "capacity_percent": 80,
            },
            "source_ids": ["eu_phone_ecodesign_2023_1670"],
            "evidence_grade": "regulatory_minimum",
            "reviewed_on": "2026-09-05",
            "safety_sensitive": True,
            "notes": [],
        }
    ]


def test_wired_device_batteries_are_optional(tmp_path):
    compile_reference(ROOT / "reference", tmp_path / "components.sqlite")
    store = ReferenceStore(tmp_path / "components.sqlite")

    for category_id, component_id in (
        ("0301_computer_mouse", "removable_or_rechargeable_battery"),
        ("0301_keyboard", "removable_or_rechargeable_battery"),
        ("0401_headphones", "lithium_ion_battery"),
    ):
        components = store.snapshot(category_id)["components"]
        component = next(item for item in components if item["component_id"] == component_id)
        assert component["presence_label"] == "optional"


def test_snapshot_keeps_category_context_and_battery_disposal_rule(tmp_path):
    compile_reference(ROOT / "reference", tmp_path / "components.sqlite")
    store = ReferenceStore(tmp_path / "components.sqlite")

    snapshot = store.snapshot("0306_mobile_phone")

    assert snapshot["category_id"] == "0306_mobile_phone"
    assert "potential" in snapshot["handling_note"].lower()
    assert "not a claim" in snapshot["handling_note"].lower()
    battery_rule = next(rule for rule in snapshot["rules"] if rule["rule_id"] == "li_ion_no_household_trash")
    assert "household trash" in battery_rule["text"].lower()
    assert "municipal recycling" in battery_rule["text"].lower()
    assert battery_rule["source_ids"] == ["epa_used_li_ion_2026"]


def test_store_is_read_only_and_unknown_category_is_none(tmp_path):
    destination = tmp_path / "components.sqlite"
    compile_reference(ROOT / "reference", destination)
    store = ReferenceStore(destination)

    assert store.get_category("not-a-category") is None
    with pytest.raises(Exception):
        store._connection.execute("DELETE FROM categories")


def test_invalid_referenced_source_identifies_record_path(tmp_path):
    fixture = copy_reference_fixture(tmp_path)
    component = fixture["categories"][3]["components"][-1]
    component["source_ids"] = ["not_in_registry"]
    write_component_fixture(tmp_path, fixture)

    with pytest.raises(
        ReferenceValidationError,
        match=r"device_components\.yaml.*categories\[3\]\.components\[7\].*not_in_registry",
    ):
        compile_reference(tmp_path, tmp_path / "bad.sqlite")


def test_safety_sensitive_component_requires_auditable_provenance(tmp_path):
    fixture = copy_reference_fixture(tmp_path)
    component = fixture["categories"][0]["components"][-1]
    component.pop("source_ids", None)
    component.pop("evidence_grade", None)
    component.pop("reviewed_on", None)
    write_component_fixture(tmp_path, fixture)

    with pytest.raises(
        ReferenceValidationError,
        match=r"device_components\.yaml.*categories\[0\]\.components\[6\].*source_ids",
    ):
        compile_reference(tmp_path, tmp_path / "bad.sqlite")


@pytest.mark.parametrize(("field", "value"), (("minimum", float("nan")), ("maximum", float("inf"))))
def test_lifecycle_rejects_nonfinite_numbers_with_record_path(tmp_path, field, value):
    fixture = copy_reference_fixture(tmp_path)
    component = fixture["categories"][3]["components"][-1]
    component["lifecycle"][field] = value
    write_component_fixture(tmp_path, fixture)

    with pytest.raises(
        ReferenceValidationError,
        match=rf"device_components\.yaml.*categories\[3\]\.components\[7\]\.lifecycle\.{field}.*finite",
    ):
        compile_reference(tmp_path, tmp_path / "bad.sqlite")


def test_failed_validation_does_not_replace_existing_database(tmp_path):
    destination = tmp_path / "components.sqlite"
    original = compile_reference(ROOT / "reference", destination)
    fixture = copy_reference_fixture(tmp_path / "fixture")
    fixture["categories"][0]["components"][0]["lifecycle"] = {
        "metric": "cycles",
        "minimum": 1,
        "maximum": 2,
    }
    write_component_fixture(tmp_path / "fixture", fixture)

    with pytest.raises(ReferenceValidationError):
        compile_reference(tmp_path / "fixture", destination)

    store = ReferenceStore(destination)
    assert store.snapshot("0306_mobile_phone")["template_version"] == original.version


def test_build_script_runs_from_the_repository_root(tmp_path):
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/build_component_db.py",
            "--source",
            "reference",
            "--out",
            str(tmp_path / "components.sqlite"),
            "--print-summary",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "categories: 5" in completed.stdout
    assert "sourced non-null lifecycles: 1" in completed.stdout

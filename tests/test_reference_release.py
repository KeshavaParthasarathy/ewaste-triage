"""Whole-reference checks for publishing a component database release."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys

import yaml

from server.lifecycle import (
    AssessmentInputs,
    Condition,
    Confidence,
    Range,
    assess_component,
)
from server.reference_db import ReferenceStore, compile_reference


ROOT = Path(__file__).resolve().parents[1]
APPROVED_VERSION = "2.0.0"
APPROVED_SCHEMA_VERSION = 2
APPROVED_CONTENT_SHA256 = (
    "5729aefdd8573bdd10ae472b3231ddb6ff1db4c24b197bad4a37785a83efaa31"
)
APPROVED_PRESENCE_LABELS = {"standard", "common", "optional", "unknown"}
HANDLING_NOTE = (
    "Potential substance context only: electronics may require appropriate end-of-life "
    "handling under EPA and RoHS guidance. This category-level note is not a claim that "
    "a photographed item contains a specific substance."
)
CATEGORY_SOURCES = ("epa_electronics_management_2026", "eu_rohs_current")
BATTERY_SOURCE = ("epa_used_li_ion_2026",)
REVIEW_DATE = "2026-09-05"
CONDITIONAL_BATTERY_RULE = (
    "li_ion_no_household_trash",
    "If a lithium-ion battery is present, do not place it in household trash or "
    "municipal recycling; use an appropriate battery collection option.",
    BATTERY_SOURCE,
    "primary_guidance",
    REVIEW_DATE,
    "1.0.0",
)
STANDARD_BATTERY_RULE = (
    "li_ion_no_household_trash",
    "Do not place the lithium-ion battery in household trash or municipal recycling; "
    "use an appropriate battery collection option.",
    BATTERY_SOURCE,
    "primary_guidance",
    REVIEW_DATE,
    "1.0.0",
)

# Component tuples pin, in order: ID, display name, presence, lifecycle, source IDs,
# evidence grade, review date, safety flag, and notes.
APPROVED_TEMPLATES = {
    "0301_computer_mouse": {
        "display_name": "Computer mouse",
        "components": (
            ("enclosure", "Enclosure", "standard", None, (), None, None, False, ()),
            ("pcb_controller", "PCB controller", "standard", None, (), None, None, False, ()),
            ("optical_sensor", "Optical sensor", "standard", None, (), None, None, False, ()),
            ("switches", "Switches", "standard", None, (), None, None, False, ()),
            ("scroll_wheel", "Scroll wheel", "standard", None, (), None, None, False, ()),
            ("cable_or_wireless_module", "Cable or wireless module", "standard", None, (), None, None, False, ()),
            ("removable_or_rechargeable_battery", "Removable or rechargeable battery", "optional", None, BATTERY_SOURCE, "primary_guidance", REVIEW_DATE, True, ()),
        ),
        "rules": (CONDITIONAL_BATTERY_RULE,),
    },
    "0301_keyboard": {
        "display_name": "Keyboard",
        "components": (
            ("enclosure", "Enclosure", "standard", None, (), None, None, False, ()),
            ("keycaps", "Keycaps", "standard", None, (), None, None, False, ()),
            ("key_switches", "Key switches", "standard", None, (), None, None, False, ()),
            ("pcb_controller", "PCB controller", "standard", None, (), None, None, False, ()),
            ("cable_or_wireless_module", "Cable or wireless module", "standard", None, (), None, None, False, ()),
            ("removable_or_rechargeable_battery", "Removable or rechargeable battery", "optional", None, BATTERY_SOURCE, "primary_guidance", REVIEW_DATE, True, ()),
        ),
        "rules": (CONDITIONAL_BATTERY_RULE,),
    },
    "0303_laptop": {
        "display_name": "Laptop",
        "components": (
            ("enclosure", "Enclosure", "standard", None, (), None, None, False, ()),
            ("display_assembly", "Display assembly", "standard", None, (), None, None, False, ()),
            ("keyboard_trackpad", "Keyboard and trackpad", "standard", None, (), None, None, False, ()),
            ("logic_board", "Logic board", "standard", None, (), None, None, False, ()),
            ("memory", "Memory", "standard", None, (), None, None, False, ()),
            ("storage", "Storage", "standard", None, (), None, None, False, ()),
            ("cooling_assembly", "Cooling assembly", "standard", None, (), None, None, False, ()),
            ("speakers", "Speakers", "standard", None, (), None, None, False, ()),
            ("power_adapter", "Power adapter", "standard", None, (), None, None, False, ()),
            ("lithium_ion_battery", "Lithium-ion battery", "standard", None, BATTERY_SOURCE, "primary_guidance", REVIEW_DATE, True, ()),
        ),
        "rules": (STANDARD_BATTERY_RULE,),
    },
    "0306_mobile_phone": {
        "display_name": "Mobile phone",
        "components": (
            ("enclosure", "Enclosure", "standard", None, (), None, None, False, ()),
            ("display_assembly", "Display assembly", "standard", None, (), None, None, False, ()),
            ("logic_board", "Logic board", "standard", None, (), None, None, False, ()),
            ("storage", "Storage", "standard", None, (), None, None, False, ()),
            ("camera_modules", "Camera modules", "standard", None, (), None, None, False, ()),
            ("speakers_microphones", "Speakers and microphones", "standard", None, (), None, None, False, ()),
            ("vibration_motor", "Vibration motor", "standard", None, (), None, None, False, ()),
            (
                "lithium_ion_battery",
                "Lithium-ion battery",
                "standard",
                {
                    "metric": "cycles_to_capacity",
                    "minimum": 800,
                    "maximum": 800,
                    "capacity_percent": 80,
                },
                ("eu_phone_ecodesign_2023_1670",),
                "regulatory_minimum",
                REVIEW_DATE,
                True,
                (),
            ),
        ),
        "rules": (STANDARD_BATTERY_RULE,),
    },
    "0401_headphones": {
        "display_name": "Headphones",
        "components": (
            ("enclosure_headband", "Enclosure and headband", "standard", None, (), None, None, False, ()),
            ("ear_cushions", "Ear cushions", "standard", None, (), None, None, False, ()),
            ("audio_drivers", "Audio drivers", "standard", None, (), None, None, False, ()),
            ("pcb_controls", "PCB controls", "standard", None, (), None, None, False, ()),
            ("cable_or_wireless_module", "Cable or wireless module", "standard", None, (), None, None, False, ()),
            ("charging_case", "Charging case", "common", None, (), None, None, False, ()),
            ("lithium_ion_battery", "Lithium-ion battery", "optional", None, BATTERY_SOURCE, "primary_guidance", REVIEW_DATE, True, ()),
        ),
        "rules": (CONDITIONAL_BATTERY_RULE,),
    },
}


def _component_contract(component: dict) -> tuple:
    return (
        component["component_id"],
        component["display_name"],
        component["presence_label"],
        component["lifecycle"],
        tuple(component["source_ids"]),
        component["evidence_grade"],
        component["reviewed_on"],
        component["safety_sensitive"],
        tuple(component["notes"]),
    )


def _rule_contract(rule: dict) -> tuple:
    return (
        rule["rule_id"],
        rule["text"],
        tuple(rule["source_ids"]),
        rule["evidence_grade"],
        rule["reviewed_on"],
        rule["revision"],
    )


def _snapshot_contract(snapshot: dict) -> dict:
    return {
        "display_name": snapshot["display_name"],
        "template_version": snapshot["template_version"],
        "schema_version": snapshot["schema_version"],
        "handling_note": snapshot["handling_note"],
        "source_ids": tuple(snapshot["source_ids"]),
        "components": tuple(
            _component_contract(component) for component in snapshot["components"]
        ),
        "rules": tuple(_rule_contract(rule) for rule in snapshot["rules"]),
    }


def _assert_provenance(record: dict) -> None:
    assert record["source_ids"]
    assert record["evidence_grade"]
    assert record["reviewed_on"]


def test_compiled_release_matches_every_approved_template_field(tmp_path):
    manifest = compile_reference(ROOT / "reference", tmp_path / "components.sqlite")

    with ReferenceStore(tmp_path / "components.sqlite") as store:
        actual = {
            category["category_id"]: _snapshot_contract(
                store.snapshot(category["category_id"])
            )
            for category in store.list_categories()
        }

    expected = {
        category_id: {
            "display_name": template["display_name"],
            "template_version": APPROVED_VERSION,
            "schema_version": APPROVED_SCHEMA_VERSION,
            "handling_note": HANDLING_NOTE,
            "source_ids": CATEGORY_SOURCES,
            "components": template["components"],
            "rules": template["rules"],
        }
        for category_id, template in APPROVED_TEMPLATES.items()
    }
    assert manifest.version == APPROVED_VERSION
    assert manifest.schema_version == APPROVED_SCHEMA_VERSION
    assert actual == expected


def test_every_released_claim_is_traceable_and_honest(tmp_path):
    manifest = compile_reference(ROOT / "reference", tmp_path / "components.sqlite")
    lifecycle_claims = []

    with ReferenceStore(tmp_path / "components.sqlite") as store:
        for category in store.list_categories():
            snapshot = store.snapshot(category["category_id"])
            assert snapshot["template_version"] == manifest.version
            assert snapshot["source_ids"]

            for component in snapshot["components"]:
                assert component["presence_label"] in APPROVED_PRESENCE_LABELS
                if component["lifecycle"] is not None:
                    _assert_provenance(component)
                    lifecycle_claims.append((snapshot["category_id"], component))
                if component["safety_sensitive"]:
                    _assert_provenance(component)

            for rule in snapshot["rules"]:
                _assert_provenance(rule)

    assert len(lifecycle_claims) == 1
    category_id, phone_battery = lifecycle_claims[0]
    assert category_id == "0306_mobile_phone"
    assert phone_battery["component_id"] == "lithium_ion_battery"

    assessable_battery = {
        **phone_battery,
        "lifecycle": {
            **phone_battery["lifecycle"],
            "source_ids": phone_battery["source_ids"],
        },
    }
    unknown = assess_component(assessable_battery, AssessmentInputs())
    supported = assess_component(
        assessable_battery,
        AssessmentInputs(
            cycle_count=Range(200, 400),
            condition=Condition.NO_VISIBLE_DAMAGE,
        ),
    )
    assert unknown.percent_used is None
    assert unknown.confidence is Confidence.UNAVAILABLE
    assert supported.percent_used is None


def test_approved_digest_is_pinned_and_changes_when_reference_content_changes(tmp_path):
    baseline = compile_reference(ROOT / "reference", tmp_path / "baseline.sqlite")
    mutated_source = tmp_path / "mutated-reference"
    shutil.copytree(ROOT / "reference", mutated_source)
    component_path = mutated_source / "device_components.yaml"
    document = yaml.safe_load(component_path.read_text(encoding="utf-8"))
    document["categories"][0]["display_name"] = "Computer mouse revised"
    component_path.write_text(
        yaml.safe_dump(document, sort_keys=False), encoding="utf-8"
    )

    mutated = compile_reference(mutated_source, tmp_path / "mutated.sqlite")

    assert baseline.content_sha256 == APPROVED_CONTENT_SHA256
    assert mutated.content_sha256 != APPROVED_CONTENT_SHA256
    assert mutated.content_sha256 != baseline.content_sha256


def test_release_summary_and_content_checksum_are_exact_and_deterministic(tmp_path):
    outputs = []
    manifests = []
    for build_number in (1, 2):
        destination = tmp_path / f"components-{build_number}.sqlite"
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/build_component_db.py",
                "--source",
                "reference",
                "--out",
                str(destination),
                "--print-summary",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        outputs.append(completed.stdout)
        with ReferenceStore(destination) as store:
            manifests.append(store.manifest)

    expected_lines = [
        "component reference release summary",
        "database version: 2.0.0",
        "schema version: 2",
        "categories: 5",
        "- 0301_computer_mouse: Computer mouse",
        "- 0301_keyboard: Keyboard",
        "- 0303_laptop: Laptop",
        "- 0306_mobile_phone: Mobile phone",
        "- 0401_headphones: Headphones",
        "components: 38",
        "null lifecycles: 37",
        "sourced non-null lifecycles: 1",
        "source coverage: 15/15 release claims",
        f"sha256: {APPROVED_CONTENT_SHA256}",
    ]
    assert outputs[0] == outputs[1]
    assert outputs[0].splitlines() == expected_lines
    assert manifests[0] == manifests[1]
    assert manifests[0].version == APPROVED_VERSION
    assert manifests[0].schema_version == APPROVED_SCHEMA_VERSION
    assert manifests[0].content_sha256 == APPROVED_CONTENT_SHA256

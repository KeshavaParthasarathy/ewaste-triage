"""Whole-reference checks for publishing a component database release."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from server.lifecycle import (
    AssessmentInputs,
    Condition,
    Confidence,
    Range,
    assess_component,
)
from server.reference_db import ReferenceStore, compile_reference


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_CATEGORIES = {
    "0301_computer_mouse",
    "0301_keyboard",
    "0303_laptop",
    "0306_mobile_phone",
    "0401_headphones",
}
APPROVED_PRESENCE_LABELS = {"standard", "common", "optional", "unknown"}


def _assert_provenance(record: dict) -> None:
    assert record["source_ids"]
    assert record["evidence_grade"]
    assert record["reviewed_on"]


def test_every_released_rule_is_traceable_and_honest(tmp_path):
    manifest = compile_reference(ROOT / "reference", tmp_path / "components.sqlite")
    lifecycle_claims = []

    with ReferenceStore(tmp_path / "components.sqlite") as store:
        categories = store.list_categories()
        assert {category["category_id"] for category in categories} == EXPECTED_CATEGORIES

        for category in categories:
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

    assert [
        (category_id, component["component_id"], component["lifecycle"])
        for category_id, component in lifecycle_claims
    ] == [
        (
            "0306_mobile_phone",
            "lithium_ion_battery",
            {
                "metric": "cycles_to_capacity",
                "minimum": 800,
                "maximum": 800,
                "capacity_percent": 80,
            },
        )
    ]

    _, phone_battery = lifecycle_claims[0]
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
    assert supported.percent_used == Range(25, 50)


def test_release_summary_and_content_checksum_are_deterministic(tmp_path):
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

    assert outputs[0] == outputs[1]
    assert manifests[0] == manifests[1]
    assert "database version: 1.0.0" in outputs[0]
    assert "categories: 5" in outputs[0]
    assert "components: 38" in outputs[0]
    assert "null lifecycles: 37" in outputs[0]
    assert "sourced non-null lifecycles: 1" in outputs[0]
    assert "source coverage: 15/15 release claims" in outputs[0]
    assert f"sha256: {manifests[0].content_sha256}" in outputs[0]

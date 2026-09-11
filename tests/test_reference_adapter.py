"""Behavioral tests for the opt-in schema-3 to v1 reference adapter."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from server.reference_adapter import V1ReferenceAdapter
from scripts.knowledge_compiler import compile_knowledge_bundle
from server.desktop_app import create_desktop_app
from server.evidence_resolver import EvidenceResolver
from server.knowledge_store import KnowledgeStore
from tests.knowledge_helpers import make_valid_knowledge_source, mutate_yaml


CATEGORY_ID = "0301_keyboard"


def _add_category_standard_unknown(source: Path) -> None:
    category_dir = source / "categories" / CATEGORY_ID

    def add_component_and_association(document: dict[str, object]) -> None:
        document["components"].append(
            {"component_id": "unknown_slot", "display_name": "Unknown slot"}
        )
        document["associations"].append(
            {
                "association_id": f"{CATEGORY_ID}_association_standard_2_unknown",
                "template_id": f"{CATEGORY_ID}_standard",
                "component_id": "unknown_slot",
                "position": 2,
                "status": "unknown",
                "applicability": "Category evidence does not establish this slot.",
                "notes": ["Item-specific evidence would be required."],
                "evidence_level": None,
                "source_ids": [],
            }
        )

    def add_coverage_unknown(document: dict[str, object]) -> None:
        document["unknowns"].append(
            {
                "category_id": CATEGORY_ID,
                "claim_kind": "component_association",
                "claim_id": f"{CATEGORY_ID}_association_standard_2_unknown",
                "evidence_level": None,
                "source_ids": [],
                "reason": "Category evidence does not establish this slot.",
                "evidence_request": "Find a qualified category-level source.",
            }
        )

    mutate_yaml(category_dir / "components.yaml", add_component_and_association)
    mutate_yaml(category_dir / "coverage.yaml", add_coverage_unknown)


@pytest.fixture(scope="module")
def compiled_knowledge_bundle(tmp_path_factory):
    root = tmp_path_factory.mktemp("reference-adapter").resolve()
    source = make_valid_knowledge_source(root / "source")
    _add_category_standard_unknown(source)
    destination = root / "bundle"
    manifest = compile_knowledge_bundle(source, destination)
    return destination, manifest


@pytest.fixture
def knowledge_store(compiled_knowledge_bundle):
    bundle, manifest = compiled_knowledge_bundle
    database = bundle / "knowledge.sqlite"
    coverage = bundle / "evidence-coverage.json"
    with KnowledgeStore(
        database,
        coverage,
        expected_sha256=hashlib.sha256(database.read_bytes()).hexdigest(),
        expected_content_sha256=manifest.content_sha256,
        expected_coverage_sha256=manifest.coverage_sha256,
        expected_schema_version=manifest.schema_version,
        expected_bundle_version=manifest.bundle_version,
        expected_identity_catalog_version=manifest.identity_catalog_version,
        expected_policy_revision=manifest.policy_revision,
    ) as store:
        yield store


@pytest.fixture
def classifier():
    return object()


def imported_modules_for(module_name: str) -> set[str]:
    code = """
import importlib
import json
import sys

importlib.import_module(sys.argv[1])
print(json.dumps(sorted(sys.modules)))
"""
    completed = subprocess.run(
        [sys.executable, "-c", code, module_name],
        check=True,
        capture_output=True,
        text=True,
    )
    return set(json.loads(completed.stdout))


def _adapter(knowledge_store: KnowledgeStore) -> V1ReferenceAdapter:
    return V1ReferenceAdapter(
        knowledge_store,
        EvidenceResolver(knowledge_store),
    )


def test_v1_adapter_maps_only_ordered_category_evidence_without_specificity(
    knowledge_store,
):
    snapshot = _adapter(knowledge_store).snapshot(CATEGORY_ID)

    assert set(snapshot) == {
        "category_id",
        "display_name",
        "template_version",
        "schema_version",
        "components",
        "rules",
    }
    assert snapshot["category_id"] == CATEGORY_ID
    assert snapshot["template_version"] == "3.0.0"
    assert snapshot["schema_version"] == 3
    assert [item["component_id"] for item in snapshot["components"]] == [
        "chassis",
        "battery",
        "unknown_slot",
    ]
    assert [item["presence_label"] for item in snapshot["components"]] == [
        "standard",
        "optional",
        "unknown",
    ]
    assert [item["association_status"] for item in snapshot["components"]] == [
        "commonly_associated",
        "conditional",
        "unknown",
    ]
    assert not any(
        item.get("association_status") == "exact_model_confirmed"
        for item in snapshot["components"]
    )
    assert "storage" not in {
        item["component_id"] for item in snapshot["components"]
    }
    assert not any(
        "legacy" in item["association_id"] for item in snapshot["components"]
    )


def test_v1_adapter_preserves_component_claims_without_inventing_legacy_fields(
    knowledge_store,
):
    components = _adapter(knowledge_store).snapshot(CATEGORY_ID)["components"]
    chassis, battery, unknown = components

    assert chassis == {
        "association_id": f"{CATEGORY_ID}_association_standard_0",
        "association_status": "commonly_associated",
        "component_id": "chassis",
        "display_name": "Chassis",
        "presence_label": "standard",
        "applicability": "Category-standard enclosure.",
        "lifecycle": None,
        "source_ids": [f"{CATEGORY_ID}_claim_source"],
        "sources": [
            {
                "source_id": f"{CATEGORY_ID}_claim_source",
                "title": f"{CATEGORY_ID} claim evidence",
                "publisher": "Synthetic Evidence Publisher",
                "canonical_url": (
                    f"https://example.invalid/{CATEGORY_ID}_claim_source"
                ),
                "publication_or_revision_date": "2026-01-01",
                "accessed_on": "2026-09-07",
                "license_or_use_basis": "synthetic-test-fixture",
                "reviewed_by": "test-reviewer",
                "reviewed_on": "2026-09-07",
            }
        ],
        "evidence_grade": "C",
        "reviewed_on": None,
        "safety_sensitive": None,
        "notes": [],
    }
    assert battery["presence_label"] == "optional"
    assert battery["applicability"] == "Present only in battery-bearing variants."
    assert battery["notes"] == ["Omission never establishes absence."]
    assert battery["lifecycle"] is None
    assert battery["reviewed_on"] is None
    assert battery["safety_sensitive"] is None
    assert unknown["presence_label"] == "unknown"
    assert unknown["evidence_grade"] is None
    assert unknown["source_ids"] == []
    assert unknown["sources"] == []


def test_v1_adapter_keeps_possible_hazard_guidance_and_provenance_separate(
    knowledge_store,
):
    snapshot = _adapter(knowledge_store).snapshot(CATEGORY_ID)
    rule = snapshot["rules"][0]

    assert rule["rule_id"] == f"{CATEGORY_ID}_damaged_battery_hazard"
    assert rule["component_id"] == "battery"
    assert rule["applicability"] == "Possible only when the user reports damage."
    assert rule["trigger_observation_keys"] == [
        "observations.issue_flags.odor",
        "observations.issue_flags.overheating",
    ]
    assert rule["severity"] == "urgent"
    assert rule["immediate_actions"] == ["Stop using the item."]
    assert rule["follow_up_actions"] == ["Seek specialist handling."]
    assert rule["handling_guidance"] == ["Avoid pressure or puncture."]
    assert rule["disposal_guidance"] == ["Use a certified recycler."]
    assert rule["revision"] is None
    assert rule["reviewed_on"] is None
    assert rule["evidence_grade"] == "D"
    assert rule["source_ids"] == [f"{CATEGORY_ID}_hazard_source"]
    assert rule["sources"] == [
        {
            "source_id": f"{CATEGORY_ID}_hazard_source",
            "title": f"{CATEGORY_ID} hazard evidence",
            "publisher": "Synthetic Evidence Publisher",
            "canonical_url": (
                f"https://example.invalid/{CATEGORY_ID}_hazard_source"
            ),
            "publication_or_revision_date": "2026-01-01",
            "accessed_on": "2026-09-07",
            "license_or_use_basis": "synthetic-test-fixture",
            "reviewed_by": "test-reviewer",
            "reviewed_on": "2026-09-07",
        }
    ]
    assert "possible" in rule["text"].lower()
    assert "not evaluated" in rule["text"].lower()
    assert rule["applicability"] in rule["text"]
    for action in (
        *rule["immediate_actions"],
        *rule["follow_up_actions"],
        *rule["handling_guidance"],
        *rule["disposal_guidance"],
    ):
        assert action in rule["text"]
    assert (
        snapshot["components"][0]["sources"][0]["source_id"]
        != rule["sources"][0]["source_id"]
    )
    assert all(
        component["safety_sensitive"] is None
        for component in snapshot["components"]
    )
    assert "triggered" not in rule


def test_v1_adapter_outputs_plain_json_and_preserves_category_lookup_contract(
    knowledge_store,
):
    adapter = _adapter(knowledge_store)
    categories = adapter.list_categories()

    assert categories[1] == {
        "category_id": CATEGORY_ID,
        "display_name": f"Synthetic category {CATEGORY_ID}",
        "template_version": "3.0.0",
    }
    assert set(categories[0]) == {
        "category_id",
        "display_name",
        "template_version",
    }
    assert adapter.get_category(CATEGORY_ID) == categories[1]
    assert adapter.get_category("missing") is None
    with pytest.raises(KeyError, match="missing"):
        adapter.snapshot("missing")
    json.dumps(adapter.snapshot(CATEGORY_ID), sort_keys=True)


def test_v1_app_uses_adapter_only_when_explicitly_injected(
    classifier,
    knowledge_store,
):
    adapter = _adapter(knowledge_store)
    app = create_desktop_app(classifier=classifier, reference_store=adapter)

    assert app.config["REFERENCE_STORE"] is adapter
    response = app.test_client().get("/api/v1/reference/categories")
    assert response.status_code == 200
    assert response.json[1]["category_id"] == CATEGORY_ID

    unavailable = create_desktop_app(
        classifier=classifier,
        reference_store=None,
    )
    assert unavailable.config["REFERENCE_STORE"] is None
    response = unavailable.test_client().get("/api/v1/reference/categories")
    assert response.status_code == 503
    assert response.json == {"error": "component reference data is unavailable"}


def test_adapter_imports_no_yaml_or_admin_compiler():
    imported = imported_modules_for("server.reference_adapter")

    assert "scripts.knowledge_schema" not in imported
    assert "scripts.knowledge_compiler" not in imported
    assert "yaml" not in imported

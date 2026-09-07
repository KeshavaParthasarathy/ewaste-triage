"""Synthetic schema-3 knowledge trees and exhaustive mutation descriptors."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil
from typing import Callable

import yaml

from server.evidence_types import RELEASED_CATEGORY_IDS


TEST_CATEGORY_ID = RELEASED_CATEGORY_IDS[0]


class _NoAliasSafeDumper(yaml.SafeDumper):
    def ignore_aliases(self, data: object) -> bool:
        return True


@dataclass(frozen=True)
class SchemaCase:
    name: str
    relative_path: str
    selector: Callable[[dict[str, object]], dict[str, object]]
    expected_keys: frozenset[str]
    field_types: tuple[tuple[str, str], ...]
    required_nonnull_fields: frozenset[str]
    nullable_fields: frozenset[str]
    nullable_underlying_types: frozenset[tuple[str, str]]
    list_fields: frozenset[str]
    list_item_types: frozenset[tuple[str, str]]
    integer_fields: frozenset[str]
    number_fields: frozenset[str]
    enum_fields: frozenset[str]
    id_fields: frozenset[str]
    text_fields: frozenset[str]
    date_fields: frozenset[str]
    semver_fields: frozenset[str]
    https_url_fields: frozenset[str]
    nested_mapping_fields: frozenset[tuple[str, str]]
    reference_fields: frozenset[str]


@dataclass(frozen=True)
class SchemaMutation:
    name: str
    kind: str
    target_field: str
    type_contract: str
    apply: Callable[[Path], None]
    expected_error: str


_ROOT_KEYS: dict[str, frozenset[str]] = {
    "bundle.yaml": frozenset({"bundle"}),
    "common/sources.yaml": frozenset({"sources"}),
    "common/policies.yaml": frozenset({"policy_revision", "policies"}),
    "categories/{category_id}/sources.yaml": frozenset({"sources"}),
    "categories/{category_id}/identities.yaml": frozenset(
        {"category", "subtypes", "variants", "identities"}
    ),
    "categories/{category_id}/lifecycles.yaml": frozenset({"lifecycles"}),
    "categories/{category_id}/industry_averages.yaml": frozenset(
        {"industry_averages"}
    ),
    "categories/{category_id}/components.yaml": frozenset(
        {"components", "templates", "associations"}
    ),
    "categories/{category_id}/hazards.yaml": frozenset({"hazards"}),
    "categories/{category_id}/coverage.yaml": frozenset({"unknowns"}),
}

_ROOT_VALUE_TYPES: dict[str, dict[str, str]] = {
    "bundle.yaml": {"bundle": "mapping:bundle"},
    "common/sources.yaml": {"sources": "nonempty_list:source"},
    "common/policies.yaml": {
        "policy_revision": "semver",
        "policies": "nonempty_list:policy",
    },
    "categories/{category_id}/sources.yaml": {"sources": "list:source"},
    "categories/{category_id}/identities.yaml": {
        "category": "mapping:category",
        "subtypes": "list:subtype",
        "variants": "list:variant",
        "identities": "list:identity",
    },
    "categories/{category_id}/lifecycles.yaml": {
        "lifecycles": "list:specific_lifecycle"
    },
    "categories/{category_id}/industry_averages.yaml": {
        "industry_averages": "list:industry_average"
    },
    "categories/{category_id}/components.yaml": {
        "components": "list:component_definition",
        "templates": "list:component_template",
        "associations": "list:component_association",
    },
    "categories/{category_id}/hazards.yaml": {"hazards": "list:hazard"},
    "categories/{category_id}/coverage.yaml": {"unknowns": "list:unknown"},
}

_FIELD_TYPES: dict[str, dict[str, str]] = {
    "bundle": {
        "schema_version": "int",
        "bundle_version": "semver",
        "identity_catalog_version": "semver",
        "policy_revision": "semver",
        "category_ids": "nonempty_list:id",
    },
    "source": {
        "source_id": "id",
        "title": "text",
        "publisher": "text",
        "canonical_url": "https_url",
        "publication_or_revision_date": "date",
        "accessed_on": "date",
        "license_or_use_basis": "text",
        "reviewed_by": "text",
        "reviewed_on": "date",
    },
    "policy": {
        "rule_id": "id",
        "priority": "int",
        "outcome": "enum:RecommendationValue",
        "when_all": "list:policy_predicate",
        "when_any": "list:policy_predicate",
        "rationale": "text",
        "evidence_level": "enum:EvidenceLevel",
        "source_ids": "nonempty_list:id",
    },
    "category": {"category_id": "id", "display_name": "text"},
    "subtype": {
        "subtype_id": "id",
        "category_id": "id",
        "display_name": "text",
        "market_state": "enum:MarketState",
        "battery_architecture": "enum:BatteryArchitecture",
        "evidence_level": "enum:EvidenceLevel",
        "source_ids": "nonempty_list:id",
    },
    "variant": {
        "variant_id": "id",
        "category_id": "id",
        "subtype_id": "id",
        "display_name": "text",
        "battery_architecture": "enum:BatteryArchitecture",
        "evidence_level": "enum:EvidenceLevel",
        "source_ids": "nonempty_list:id",
    },
    "identity": {
        "identity_id": "id",
        "identity_kind": "enum:IdentityKind",
        "category_id": "id",
        "subtype_id": "id",
        "manufacturer_id": "id",
        "manufacturer_name": "text",
        "family_id": "id",
        "family_name": "text",
        "model_id": "nullable:id",
        "model_name": "nullable:text",
        "display_name": "text",
        "aliases": "nonempty_list:text",
        "distinguishing_tokens": "nonempty_list:text",
        "model_year_from": "nullable:int",
        "model_year_to": "nullable:int",
        "applicable_from": "nullable:date",
        "applicable_to": "nullable:date",
        "variant_ids": "list:id",
        "market_state": "enum:MarketState",
        "battery_architecture": "enum:BatteryArchitecture",
        "evidence_level": "enum:EvidenceLevel",
        "source_ids": "nonempty_list:id",
    },
    "specific_lifecycle": {
        "record_id": "id",
        "scope": "mapping:scope",
        "subject": "id",
        "endpoint": "id",
        "endpoint_kind": "enum:LifecycleEndpointKind",
        "metric": "id",
        "unit": "id",
        "lower_bound": "number",
        "upper_bound": "number",
        "endpoint_qualification": "text",
        "applicable_from": "nullable:date",
        "applicable_to": "nullable:date",
        "model_year_from": "nullable:int",
        "model_year_to": "nullable:int",
        "required_variant_ids": "list:id",
        "excluded_variant_ids": "list:id",
        "precedence": "int",
        "evidence_level": "enum:EvidenceLevel",
        "assumptions": "list:text",
        "source_ids": "nonempty_list:id",
    },
    "industry_average": {
        "record_id": "id",
        "scope": "mapping:scope",
        "subject": "id",
        "endpoint": "id",
        "endpoint_kind": "enum:LifecycleEndpointKind",
        "metric": "id",
        "unit": "id",
        "lower_bound": "number",
        "upper_bound": "number",
        "endpoint_qualification": "text",
        "applicable_from": "nullable:date",
        "applicable_to": "nullable:date",
        "model_year_from": "nullable:int",
        "model_year_to": "nullable:int",
        "required_variant_ids": "list:id",
        "excluded_variant_ids": "list:id",
        "precedence": "int",
        "evidence_level": "enum:EvidenceLevel",
        "assumptions": "list:text",
        "population_definition": "text",
        "publication_period": "text",
        "methodology": "text",
        "uncertainty": "text",
        "limitations": "nonempty_list:text",
        "source_ids": "nonempty_list:id",
    },
    "component_definition": {"component_id": "id", "display_name": "text"},
    "component_template": {
        "template_id": "id",
        "template_kind": "enum:TemplateKind",
        "scope": "mapping:scope",
        "application_order": "int",
    },
    "component_association": {
        "association_id": "id",
        "template_id": "id",
        "component_id": "id",
        "position": "int",
        "status": "enum:AssociationStatus",
        "applicability": "text",
        "notes": "list:text",
        "evidence_level": "nullable:enum:EvidenceLevel",
        "source_ids": "list:id",
    },
    "hazard": {
        "hazard_id": "id",
        "component_id": "id",
        "scope": "mapping:scope",
        "applicability": "text",
        "trigger_observation_keys": "nonempty_list:hazard_trigger_key",
        "severity": "enum:HazardSeverity",
        "immediate_actions": "nonempty_list:text",
        "follow_up_actions": "nonempty_list:text",
        "handling_guidance": "nonempty_list:text",
        "disposal_guidance": "nonempty_list:text",
        "evidence_level": "enum:EvidenceLevel",
        "source_ids": "nonempty_list:id",
    },
    "unknown": {
        "category_id": "id",
        "claim_kind": "enum:UnknownClaimKind",
        "claim_id": "id",
        "evidence_level": "literal:null",
        "source_ids": "list:id",
        "reason": "text",
        "evidence_request": "text",
    },
    "scope": {"kind": "enum:ScopeKind", "id": "id"},
}

_REFERENCE_FIELDS: dict[str, frozenset[str]] = {
    "policy": frozenset({"source_ids"}),
    "subtype": frozenset({"category_id", "source_ids"}),
    "variant": frozenset({"category_id", "subtype_id", "source_ids"}),
    "identity": frozenset(
        {"category_id", "subtype_id", "variant_ids", "source_ids"}
    ),
    "specific_lifecycle": frozenset(
        {"required_variant_ids", "excluded_variant_ids", "source_ids"}
    ),
    "industry_average": frozenset(
        {"required_variant_ids", "excluded_variant_ids", "source_ids"}
    ),
    "component_association": frozenset(
        {"template_id", "component_id", "source_ids"}
    ),
    "hazard": frozenset({"component_id", "source_ids"}),
    "scope": frozenset({"id"}),
}

_SORTED_SET_FIELDS: dict[str, frozenset[str]] = {
    "bundle": frozenset({"category_ids"}),
    "policy": frozenset({"when_all", "when_any", "source_ids"}),
    "subtype": frozenset({"source_ids"}),
    "variant": frozenset({"source_ids"}),
    "identity": frozenset({"variant_ids", "source_ids"}),
    "specific_lifecycle": frozenset(
        {"required_variant_ids", "excluded_variant_ids", "source_ids"}
    ),
    "industry_average": frozenset(
        {"required_variant_ids", "excluded_variant_ids", "source_ids"}
    ),
    "component_association": frozenset({"source_ids"}),
    "hazard": frozenset({"trigger_observation_keys", "source_ids"}),
}

_BAD_EVIDENCE_LEVEL: dict[str, str] = {
    "subtype": "D",
    "variant": "A",
    "identity": "A",
    "specific_lifecycle": "D",
    "industry_average": "B",
    "component_association": "A",
    "hazard": "A",
}


def _write_yaml(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(
            document,
            Dumper=_NoAliasSafeDumper,
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )


def _source(source_id: str, title: str) -> dict[str, object]:
    return {
        "source_id": source_id,
        "title": title,
        "publisher": "Synthetic Evidence Publisher",
        "canonical_url": f"https://example.invalid/{source_id}",
        "publication_or_revision_date": "2026-01-01",
        "accessed_on": "2026-09-07",
        "license_or_use_basis": "synthetic-test-fixture",
        "reviewed_by": "test-reviewer",
        "reviewed_on": "2026-09-07",
    }


def make_valid_shared_knowledge_source(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _write_yaml(
        root / "bundle.yaml",
        {
            "bundle": {
                "schema_version": 3,
                "bundle_version": "3.0.0",
                "identity_catalog_version": "1.0.0",
                "policy_revision": "2.0.0",
                "category_ids": list(RELEASED_CATEGORY_IDS),
            }
        },
    )
    _write_yaml(
        root / "common/sources.yaml",
        {
            "sources": [
                _source("shared_policy_source", "Shared policy evidence"),
                _source("shared_process_source", "Shared process evidence"),
            ]
        },
    )
    _write_yaml(
        root / "common/policies.yaml",
        {
            "policy_revision": "2.0.0",
            "policies": [
                {
                    "rule_id": "baseline_canonical_policy",
                    "priority": 0,
                    "outcome": "reuse",
                    "when_all": ["identity.state=canonical"],
                    "when_any": [],
                    "rationale": "Canonical records can reach reviewed policy.",
                    "evidence_level": "D",
                    "source_ids": ["shared_policy_source"],
                },
                {
                    "rule_id": "baseline_unknown_policy",
                    "priority": 1,
                    "outcome": "more_information_needed",
                    "when_all": ["identity.state=unknown"],
                    "when_any": [],
                    "rationale": "Unknown identity needs more information.",
                    "evidence_level": "D",
                    "source_ids": ["shared_process_source"],
                },
            ],
        },
    )
    return root


def _category_documents(category_id: str) -> dict[str, dict[str, object]]:
    claim_source = f"{category_id}_claim_source"
    hazard_source = f"{category_id}_hazard_source"
    subtype_ids = [f"{category_id}_subtype_{index}" for index in range(4)]
    architectures = [
        "battery_bearing",
        "battery_free",
        "battery_bearing",
        "battery_free",
    ]
    market_states = ["current", "current", "discontinued", "legacy"]
    subtypes = [
        {
            "subtype_id": subtype_id,
            "category_id": category_id,
            "display_name": f"Synthetic subtype {index}",
            "market_state": market_states[index],
            "battery_architecture": architectures[index],
            "evidence_level": "B",
            "source_ids": [claim_source],
        }
        for index, subtype_id in enumerate(subtype_ids)
    ]
    variants: list[dict[str, object]] = []
    for index, subtype_id in enumerate(subtype_ids):
        for suffix in ("a", "b"):
            variants.append(
                {
                    "variant_id": f"{category_id}_variant_{index}{suffix}",
                    "category_id": category_id,
                    "subtype_id": subtype_id,
                    "display_name": f"Synthetic variant {index}{suffix}",
                    "battery_architecture": architectures[index],
                    "evidence_level": "B",
                    "source_ids": [claim_source],
                }
            )
    identities: list[dict[str, object]] = []
    for index in range(10):
        family_index = index // 2
        subtype_index = family_index % 4
        manufacturer_index = family_index % 2
        is_family = index == 0
        family_id = f"{category_id}_family_{family_index:02d}"
        identity_id = family_id if is_family else f"{category_id}_model_{index:02d}"
        display_name = (
            f"Synthetic {category_id} family {family_index:02d}"
            if is_family
            else f"Synthetic {category_id} model {index:02d}"
        )
        identities.append(
            {
                "identity_id": identity_id,
                "identity_kind": "family" if is_family else "model",
                "category_id": category_id,
                "subtype_id": subtype_ids[subtype_index],
                "manufacturer_id": f"{category_id}_maker_{manufacturer_index}",
                "manufacturer_name": f"Synthetic Maker {manufacturer_index}",
                "family_id": family_id,
                "family_name": f"Synthetic Family {family_index:02d}",
                "model_id": None if is_family else identity_id,
                "model_name": None if is_family else f"Model {index:02d}",
                "display_name": display_name,
                "aliases": [f"{display_name} Alias", f"Catalog code {index:02d}"],
                "distinguishing_tokens": [
                    f"synthetic token {index:02d}",
                    f"synthetic series {index:02d}",
                ],
                "model_year_from": 2020 + index,
                "model_year_to": 2020 + index,
                "applicable_from": "2020-01-01",
                "applicable_to": "2020-12-31",
                "variant_ids": [
                    f"{category_id}_variant_{subtype_index}a",
                    f"{category_id}_variant_{subtype_index}b",
                ],
                "market_state": market_states[subtype_index],
                "battery_architecture": architectures[subtype_index],
                "evidence_level": "B" if is_family else "A",
                "source_ids": [claim_source],
            }
        )
    lifecycles = [
        {
            "record_id": f"{category_id}_lifecycle_0_model_service",
            "scope": {"kind": "model", "id": identities[1]["model_id"]},
            "subject": "device",
            "endpoint": "service_life",
            "endpoint_kind": "total_life",
            "metric": "elapsed_time",
            "unit": "years",
            "lower_bound": 4.0,
            "upper_bound": 6.0,
            "endpoint_qualification": "Synthetic total service life.",
            "applicable_from": None,
            "applicable_to": None,
            "model_year_from": None,
            "model_year_to": None,
            "required_variant_ids": [f"{category_id}_variant_0a"],
            "excluded_variant_ids": [],
            "precedence": 0,
            "evidence_level": "A",
            "assumptions": ["Normal operation", "Comparable configuration"],
            "source_ids": [claim_source],
        },
        {
            "record_id": f"{category_id}_lifecycle_1_family_capacity",
            "scope": {"kind": "family", "id": identities[2]["family_id"]},
            "subject": "battery",
            "endpoint": "capacity_threshold",
            "endpoint_kind": "capacity_threshold",
            "metric": "full_charge_cycles",
            "unit": "cycles",
            "lower_bound": 800.0,
            "upper_bound": 800.0,
            "endpoint_qualification": "Synthetic sourced point threshold.",
            "applicable_from": "2020-01-01",
            "applicable_to": "2030-01-01",
            "model_year_from": 2020,
            "model_year_to": 2030,
            "required_variant_ids": [],
            "excluded_variant_ids": [],
            "precedence": 1,
            "evidence_level": "B",
            "assumptions": [],
            "source_ids": [claim_source],
        },
        {
            "record_id": f"{category_id}_lifecycle_2_subtype_runtime",
            "scope": {"kind": "subtype", "id": subtype_ids[2]},
            "subject": "device",
            "endpoint": "charge_runtime",
            "endpoint_kind": "operating_endurance",
            "metric": "elapsed_time",
            "unit": "hours",
            "lower_bound": 10.0,
            "upper_bound": 20.0,
            "endpoint_qualification": "Synthetic one-charge runtime.",
            "applicable_from": None,
            "applicable_to": None,
            "model_year_from": None,
            "model_year_to": None,
            "required_variant_ids": [],
            "excluded_variant_ids": [],
            "precedence": 2,
            "evidence_level": "B",
            "assumptions": ["Nominal settings"],
            "source_ids": [claim_source],
        },
    ]
    average = {
        "record_id": f"{category_id}_industry_service_life",
        "scope": {"kind": "category", "id": category_id},
        "subject": "device",
        "endpoint": "service_life",
        "endpoint_kind": "total_life",
        "metric": "elapsed_time",
        "unit": "years",
        "lower_bound": 3.0,
        "upper_bound": 7.0,
        "endpoint_qualification": "Synthetic broad service-life interval.",
        "applicable_from": None,
        "applicable_to": None,
        "model_year_from": None,
        "model_year_to": None,
        "required_variant_ids": [],
        "excluded_variant_ids": [],
        "precedence": 0,
        "evidence_level": "C",
        "assumptions": ["Comparable population"],
        "population_definition": "Synthetic devices in the category.",
        "publication_period": "2020-2025",
        "methodology": "Synthetic test-fixture interval study.",
        "uncertainty": "Category-level uncertainty remains.",
        "limitations": ["Not an exact-model estimate."],
        "source_ids": [claim_source],
    }
    legacy_template = f"{category_id}_legacy_overlay"
    modern_template = f"{category_id}_modern_overlay"
    standard_template = f"{category_id}_standard"
    unknown_association = f"{category_id}_association_modern_1_unknown"
    return {
        "sources.yaml": {
            "sources": [
                _source(claim_source, f"{category_id} claim evidence"),
                _source(hazard_source, f"{category_id} hazard evidence"),
            ]
        },
        "identities.yaml": {
            "category": {
                "category_id": category_id,
                "display_name": f"Synthetic category {category_id}",
            },
            "subtypes": subtypes,
            "variants": variants,
            "identities": identities,
        },
        "lifecycles.yaml": {"lifecycles": lifecycles},
        "industry_averages.yaml": {"industry_averages": [average]},
        "components.yaml": {
            "components": [
                {"component_id": "battery", "display_name": "Battery"},
                {"component_id": "chassis", "display_name": "Chassis"},
                {"component_id": "storage", "display_name": "Storage"},
            ],
            "templates": [
                {
                    "template_id": legacy_template,
                    "template_kind": "legacy_overlay",
                    "scope": {"kind": "subtype", "id": subtype_ids[2]},
                    "application_order": 0,
                },
                {
                    "template_id": modern_template,
                    "template_kind": "modern_overlay",
                    "scope": {"kind": "subtype", "id": subtype_ids[0]},
                    "application_order": 0,
                },
                {
                    "template_id": standard_template,
                    "template_kind": "standard",
                    "scope": {"kind": "category", "id": category_id},
                    "application_order": 0,
                },
            ],
            "associations": [
                {
                    "association_id": f"{category_id}_association_legacy_0",
                    "template_id": legacy_template,
                    "component_id": "battery",
                    "position": 0,
                    "status": "legacy_specific",
                    "applicability": "Legacy architecture association.",
                    "notes": ["Conditional on the selected legacy subtype."],
                    "evidence_level": "B",
                    "source_ids": [claim_source],
                },
                {
                    "association_id": f"{category_id}_association_modern_0",
                    "template_id": modern_template,
                    "component_id": "battery",
                    "position": 0,
                    "status": "commonly_associated",
                    "applicability": "Modern architecture association.",
                    "notes": [],
                    "evidence_level": "B",
                    "source_ids": [claim_source],
                },
                {
                    "association_id": unknown_association,
                    "template_id": modern_template,
                    "component_id": "storage",
                    "position": 1,
                    "status": "unknown",
                    "applicability": "The hidden storage form is unsupported.",
                    "notes": ["Requires a model-specific source."],
                    "evidence_level": None,
                    "source_ids": [],
                },
                {
                    "association_id": f"{category_id}_association_standard_0",
                    "template_id": standard_template,
                    "component_id": "chassis",
                    "position": 0,
                    "status": "commonly_associated",
                    "applicability": "Category-standard enclosure.",
                    "notes": [],
                    "evidence_level": "C",
                    "source_ids": [claim_source],
                },
                {
                    "association_id": f"{category_id}_association_standard_1",
                    "template_id": standard_template,
                    "component_id": "battery",
                    "position": 1,
                    "status": "conditional",
                    "applicability": "Present only in battery-bearing variants.",
                    "notes": ["Omission never establishes absence."],
                    "evidence_level": "C",
                    "source_ids": [claim_source],
                },
            ],
        },
        "hazards.yaml": {
            "hazards": [
                {
                    "hazard_id": f"{category_id}_damaged_battery_hazard",
                    "component_id": "battery",
                    "scope": {"kind": "category", "id": category_id},
                    "applicability": "Possible only when the user reports damage.",
                    "trigger_observation_keys": [
                        "observations.issue_flags.odor",
                        "observations.issue_flags.overheating",
                    ],
                    "severity": "urgent",
                    "immediate_actions": ["Stop using the item."],
                    "follow_up_actions": ["Seek specialist handling."],
                    "handling_guidance": ["Avoid pressure or puncture."],
                    "disposal_guidance": ["Use a certified recycler."],
                    "evidence_level": "D",
                    "source_ids": [hazard_source],
                }
            ]
        },
        "coverage.yaml": {
            "unknowns": [
                {
                    "category_id": category_id,
                    "claim_kind": "component_association",
                    "claim_id": unknown_association,
                    "evidence_level": None,
                    "source_ids": [],
                    "reason": "No reviewed exact association is available.",
                    "evidence_request": "Find a qualified model-specific source.",
                }
            ]
        },
    }


def make_valid_category_knowledge_source(root: Path, category_id: str) -> Path:
    make_valid_shared_knowledge_source(root)
    category_dir = root / "categories" / category_id
    category_dir.mkdir(parents=True, exist_ok=True)
    for filename, document in _category_documents(category_id).items():
        _write_yaml(category_dir / filename, document)
    return root


def make_valid_knowledge_source(root: Path) -> Path:
    make_valid_shared_knowledge_source(root)
    for category_id in RELEASED_CATEGORY_IDS:
        category_dir = root / "categories" / category_id
        category_dir.mkdir(parents=True, exist_ok=True)
        for filename, document in _category_documents(category_id).items():
            _write_yaml(category_dir / filename, document)
    return root


def mutate_yaml(
    path: Path, mutation: Callable[[dict[str, object]], None]
) -> None:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise AssertionError(f"fixture document is not a mapping: {path}")
    mutation(document)
    _write_yaml(path, document)


def _fixture_path(source: Path, relative_path: str) -> Path:
    return source / relative_path.format(category_id=TEST_CATEGORY_ID)


def mutate_document_root(
    source: Path,
    relative_path: str,
    expected_keys: set[str] | frozenset[str],
    mutation_kind: str,
) -> None:
    path = _fixture_path(source, relative_path)

    def mutate(document: dict[str, object]) -> None:
        if mutation_kind == "unknown_key":
            document["unexpected_root_key"] = None
            return
        prefix = "missing_key:"
        if mutation_kind.startswith(prefix):
            key = mutation_kind.removeprefix(prefix)
            if key not in expected_keys:
                raise AssertionError(key)
            del document[key]
            return
        raise AssertionError(mutation_kind)

    mutate_yaml(path, mutate)


def replace_with_non_mapping_yaml_root(
    source: Path, relative_path: str
) -> None:
    _fixture_path(source, relative_path).write_text(
        "- not\n- a\n- mapping\n", encoding="utf-8"
    )


def _read_fixture_document(source: Path, relative_path: str) -> dict[str, object]:
    document = yaml.safe_load(_fixture_path(source, relative_path).read_text("utf-8"))
    if not isinstance(document, dict):
        raise AssertionError(relative_path)
    return document


def root_key_sets(source: Path) -> dict[str, set[str]]:
    return {
        relative_path: set(_read_fixture_document(source, relative_path))
        for relative_path in _ROOT_KEYS
    }


def _root_contract_matches(value: object, contract: str) -> bool:
    if contract.startswith("mapping:"):
        return isinstance(value, dict)
    if contract.startswith("nonempty_list:"):
        return isinstance(value, list) and bool(value)
    if contract.startswith("list:"):
        return isinstance(value, list)
    if contract == "semver":
        return isinstance(value, str)
    return False


def root_value_type_sets(source: Path) -> dict[str, dict[str, str]]:
    for relative_path, fields in _ROOT_VALUE_TYPES.items():
        document = _read_fixture_document(source, relative_path)
        for field_name, contract in fields.items():
            if not _root_contract_matches(document[field_name], contract):
                raise AssertionError(f"{relative_path}:{field_name} is not {contract}")
    return {
        relative_path: dict(fields)
        for relative_path, fields in _ROOT_VALUE_TYPES.items()
    }


def _select_mapping(field: str) -> Callable[[dict[str, object]], dict[str, object]]:
    def select(document: dict[str, object]) -> dict[str, object]:
        value = document[field]
        if not isinstance(value, dict):
            raise AssertionError(field)
        return value

    return select


def _select_first(field: str) -> Callable[[dict[str, object]], dict[str, object]]:
    def select(document: dict[str, object]) -> dict[str, object]:
        values = document[field]
        if not isinstance(values, list) or not values or not isinstance(values[0], dict):
            raise AssertionError(field)
        return values[0]

    return select


def _select_scope(document: dict[str, object]) -> dict[str, object]:
    record = _select_first("lifecycles")(document)
    scope = record["scope"]
    if not isinstance(scope, dict):
        raise AssertionError("scope")
    return scope


_CASE_LOCATIONS: tuple[
    tuple[str, str, Callable[[dict[str, object]], dict[str, object]]], ...
] = (
    ("bundle", "bundle.yaml", _select_mapping("bundle")),
    ("source", "common/sources.yaml", _select_first("sources")),
    ("policy", "common/policies.yaml", _select_first("policies")),
    (
        "category",
        "categories/{category_id}/identities.yaml",
        _select_mapping("category"),
    ),
    (
        "subtype",
        "categories/{category_id}/identities.yaml",
        _select_first("subtypes"),
    ),
    (
        "variant",
        "categories/{category_id}/identities.yaml",
        _select_first("variants"),
    ),
    (
        "identity",
        "categories/{category_id}/identities.yaml",
        _select_first("identities"),
    ),
    (
        "specific_lifecycle",
        "categories/{category_id}/lifecycles.yaml",
        _select_first("lifecycles"),
    ),
    (
        "industry_average",
        "categories/{category_id}/industry_averages.yaml",
        _select_first("industry_averages"),
    ),
    (
        "component_definition",
        "categories/{category_id}/components.yaml",
        _select_first("components"),
    ),
    (
        "component_template",
        "categories/{category_id}/components.yaml",
        _select_first("templates"),
    ),
    (
        "component_association",
        "categories/{category_id}/components.yaml",
        _select_first("associations"),
    ),
    (
        "hazard",
        "categories/{category_id}/hazards.yaml",
        _select_first("hazards"),
    ),
    (
        "unknown",
        "categories/{category_id}/coverage.yaml",
        _select_first("unknowns"),
    ),
    ("scope", "categories/{category_id}/lifecycles.yaml", _select_scope),
)


def _atomic_contract(contract: str) -> str:
    for prefix in ("nullable:", "nonempty_list:", "list:"):
        if contract.startswith(prefix):
            return contract.removeprefix(prefix)
    return contract


def all_closed_record_cases() -> tuple[SchemaCase, ...]:
    cases: list[SchemaCase] = []
    for name, relative_path, selector in _CASE_LOCATIONS:
        field_types = _FIELD_TYPES[name]
        nullable = frozenset(
            field
            for field, contract in field_types.items()
            if contract.startswith("nullable:") or contract == "literal:null"
        )
        lists = frozenset(
            field
            for field, contract in field_types.items()
            if contract.startswith(("list:", "nonempty_list:"))
        )
        cases.append(
            SchemaCase(
                name=name,
                relative_path=relative_path,
                selector=selector,
                expected_keys=frozenset(field_types),
                field_types=tuple(field_types.items()),
                required_nonnull_fields=frozenset(field_types) - nullable,
                nullable_fields=nullable,
                nullable_underlying_types=frozenset(
                    (field, contract.removeprefix("nullable:"))
                    for field, contract in field_types.items()
                    if contract.startswith("nullable:")
                ),
                list_fields=lists,
                list_item_types=frozenset(
                    (
                        field,
                        contract.removeprefix("nonempty_list:").removeprefix(
                            "list:"
                        ),
                    )
                    for field, contract in field_types.items()
                    if contract.startswith(("list:", "nonempty_list:"))
                ),
                integer_fields=frozenset(
                    field
                    for field, contract in field_types.items()
                    if _atomic_contract(contract) == "int"
                ),
                number_fields=frozenset(
                    field
                    for field, contract in field_types.items()
                    if _atomic_contract(contract) == "number"
                ),
                enum_fields=frozenset(
                    field
                    for field, contract in field_types.items()
                    if _atomic_contract(contract).startswith("enum:")
                ),
                id_fields=frozenset(
                    field
                    for field, contract in field_types.items()
                    if _atomic_contract(contract) == "id"
                ),
                text_fields=frozenset(
                    field
                    for field, contract in field_types.items()
                    if _atomic_contract(contract) == "text"
                ),
                date_fields=frozenset(
                    field
                    for field, contract in field_types.items()
                    if _atomic_contract(contract) == "date"
                ),
                semver_fields=frozenset(
                    field
                    for field, contract in field_types.items()
                    if _atomic_contract(contract) == "semver"
                ),
                https_url_fields=frozenset(
                    field
                    for field, contract in field_types.items()
                    if _atomic_contract(contract) == "https_url"
                ),
                nested_mapping_fields=frozenset(
                    (field, contract.removeprefix("mapping:"))
                    for field, contract in field_types.items()
                    if contract.startswith("mapping:")
                ),
                reference_fields=_REFERENCE_FIELDS.get(name, frozenset()),
            )
        )
    return tuple(cases)


def record_key_sets(source: Path) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for case in all_closed_record_cases():
        record = case.selector(_read_fixture_document(source, case.relative_path))
        result[case.name] = set(record)
    return result


def _fixture_value_matches(value: object, contract: str) -> bool:
    if contract.startswith("nullable:"):
        return value is None or _fixture_value_matches(
            value, contract.removeprefix("nullable:")
        )
    if contract == "literal:null":
        return value is None
    if contract.startswith(("list:", "nonempty_list:")):
        if not isinstance(value, list):
            return False
        if contract.startswith("nonempty_list:") and not value:
            return False
        item_contract = contract.split(":", 1)[1]
        return all(_fixture_value_matches(item, item_contract) for item in value)
    if contract.startswith("mapping:"):
        return isinstance(value, dict)
    if contract == "int":
        return type(value) is int
    if contract == "number":
        return type(value) in {int, float}
    return isinstance(value, str)


def record_field_type_sets(source: Path) -> dict[str, dict[str, str]]:
    for case in all_closed_record_cases():
        record = case.selector(_read_fixture_document(source, case.relative_path))
        for field_name, contract in case.field_types:
            if not _fixture_value_matches(record[field_name], contract):
                raise AssertionError(f"{case.name}.{field_name} is not {contract}")
    return {name: dict(fields) for name, fields in _FIELD_TYPES.items()}


def _wrong_value(contract: str) -> object:
    if contract.startswith("nullable:"):
        return _wrong_value(contract.removeprefix("nullable:"))
    if contract.startswith(("list:", "nonempty_list:")):
        return {"not": "a list"}
    if contract.startswith("mapping:"):
        return ["not", "a", "mapping"]
    if contract in {"int", "number"}:
        return "not-a-number"
    if contract == "literal:null":
        return "not-null"
    return 17


def _invalid_atomic(contract: str) -> object:
    contract = contract.removeprefix("nullable:")
    if contract == "id":
        return "Invalid ID!"
    if contract == "text":
        return " "
    if contract == "date":
        return "2026-02-30"
    if contract == "semver":
        return "01.0.0"
    if contract == "https_url":
        return "http://example.invalid/not-https"
    if contract.startswith("enum:"):
        return "not_a_closed_enum_value"
    if contract == "policy_predicate":
        return "arbitrary.expression=true"
    if contract == "hazard_trigger_key":
        return "visible_condition.grade=critical"
    raise AssertionError(contract)


def _valid_list_values(case_name: str, field_name: str) -> list[object]:
    category_id = TEST_CATEGORY_ID
    claim_source = f"{category_id}_claim_source"
    hazard_source = f"{category_id}_hazard_source"
    if field_name == "category_ids":
        return list(RELEASED_CATEGORY_IDS[:2])
    if field_name in {"when_all", "when_any"}:
        return [
            "identity.state=canonical",
            "observations.age_months=present",
        ]
    if field_name == "trigger_observation_keys":
        return [
            "observations.issue_flags.odor",
            "observations.issue_flags.overheating",
        ]
    if field_name == "source_ids":
        if case_name == "policy":
            return ["shared_policy_source", "shared_process_source"]
        return [claim_source, "shared_process_source"]
    if field_name in {
        "variant_ids",
        "required_variant_ids",
        "excluded_variant_ids",
    }:
        return [
            f"{category_id}_variant_0a",
            f"{category_id}_variant_0b",
        ]
    if field_name == "aliases":
        return ["First valid alias", "Second valid alias"]
    if field_name == "distinguishing_tokens":
        return ["first valid token", "second valid token"]
    if field_name in {
        "assumptions",
        "limitations",
        "notes",
        "immediate_actions",
        "follow_up_actions",
        "handling_guidance",
        "disposal_guidance",
    }:
        return ["First display value", "Second display value"]
    if case_name == "hazard" and field_name == "source_ids":
        return [hazard_source, "shared_process_source"]
    raise AssertionError((case_name, field_name))


def _record_mutation(
    case: SchemaCase, change: Callable[[dict[str, object]], None]
) -> Callable[[Path], None]:
    def apply(source: Path) -> None:
        path = _fixture_path(source, case.relative_path)

        def mutate(document: dict[str, object]) -> None:
            change(case.selector(document))

        mutate_yaml(path, mutate)

    return apply


def _set_field(field_name: str, value: object) -> Callable[[dict[str, object]], None]:
    def change(record: dict[str, object]) -> None:
        record[field_name] = value

    return change


def _delete_field(field_name: str) -> Callable[[dict[str, object]], None]:
    def change(record: dict[str, object]) -> None:
        del record[field_name]

    return change


def _duplicate_list(field_name: str, values: list[object]) -> Callable[[dict[str, object]], None]:
    def change(record: dict[str, object]) -> None:
        current = record[field_name]
        if isinstance(current, list) and current:
            value = current[0]
        else:
            value = values[0]
        record[field_name] = [value, value]

    return change


def _break_reference(field_name: str) -> Callable[[dict[str, object]], None]:
    def change(record: dict[str, object]) -> None:
        if field_name in {
            "source_ids",
            "variant_ids",
            "required_variant_ids",
            "excluded_variant_ids",
        }:
            record[field_name] = ["missing_reference"]
        elif field_name == "template_id":
            record[field_name] = "0000_missing_reference"
        else:
            record[field_name] = "missing_reference"

    return change


def closed_schema_mutations(case: SchemaCase) -> tuple[SchemaMutation, ...]:
    mutations: list[SchemaMutation] = [
        SchemaMutation(
            name=f"{case.name}-unknown-key",
            kind="unknown_key",
            target_field="unexpected_field",
            type_contract="closed_mapping",
            apply=_record_mutation(
                case, lambda record: record.update({"unexpected_field": True})
            ),
            expected_error="unknown field",
        )
    ]
    for field_name, contract in case.field_types:
        mutations.append(
            SchemaMutation(
                name=f"{case.name}-{field_name}-missing",
                kind="missing_key",
                target_field=field_name,
                type_contract=contract,
                apply=_record_mutation(case, _delete_field(field_name)),
                expected_error="missing field",
            )
        )
        if field_name in case.required_nonnull_fields:
            mutations.append(
                SchemaMutation(
                    name=f"{case.name}-{field_name}-null",
                    kind="null_nonnullable",
                    target_field=field_name,
                    type_contract=contract,
                    apply=_record_mutation(case, _set_field(field_name, None)),
                    expected_error="must not be null",
                )
            )
        mutations.append(
            SchemaMutation(
                name=f"{case.name}-{field_name}-wrong-type",
                kind="wrong_type",
                target_field=field_name,
                type_contract=contract,
                apply=_record_mutation(
                    case, _set_field(field_name, _wrong_value(contract))
                ),
                expected_error="must be",
            )
        )
        atomic = _atomic_contract(contract)
        if field_name in case.nullable_fields and contract.startswith("nullable:"):
            mutations.append(
                SchemaMutation(
                    name=f"{case.name}-{field_name}-nullable-wrong-type",
                    kind="nullable_wrong_underlying_type",
                    target_field=field_name,
                    type_contract=contract.removeprefix("nullable:"),
                    apply=_record_mutation(
                        case, _set_field(field_name, _wrong_value(contract))
                    ),
                    expected_error="must be",
                )
            )
        if field_name not in case.list_fields and (
            atomic in {"id", "text", "date", "semver", "https_url"}
            or atomic.startswith("enum:")
        ):
            mutations.append(
                SchemaMutation(
                    name=f"{case.name}-{field_name}-invalid-value",
                    kind="invalid_contract_value",
                    target_field=field_name,
                    type_contract=atomic,
                    apply=_record_mutation(
                        case, _set_field(field_name, _invalid_atomic(atomic))
                    ),
                    expected_error="invalid",
                )
            )
        if field_name in case.integer_fields | case.number_fields:
            mutations.append(
                SchemaMutation(
                    name=f"{case.name}-{field_name}-boolean",
                    kind="boolean_as_integer",
                    target_field=field_name,
                    type_contract=atomic,
                    apply=_record_mutation(case, _set_field(field_name, True)),
                    expected_error="boolean",
                )
            )
        if field_name in case.number_fields:
            mutations.append(
                SchemaMutation(
                    name=f"{case.name}-{field_name}-nonfinite",
                    kind="nonfinite_number",
                    target_field=field_name,
                    type_contract=atomic,
                    apply=_record_mutation(
                        case, _set_field(field_name, float("nan"))
                    ),
                    expected_error="finite",
                )
            )
        if field_name in case.list_fields:
            item_contract = contract.split(":", 1)[1]
            mutations.extend(
                [
                    SchemaMutation(
                        name=f"{case.name}-{field_name}-null-list",
                        kind="null_list",
                        target_field=field_name,
                        type_contract=item_contract,
                        apply=_record_mutation(case, _set_field(field_name, None)),
                        expected_error="list",
                    ),
                    SchemaMutation(
                        name=f"{case.name}-{field_name}-wrong-item-type",
                        kind="wrong_list_item_type",
                        target_field=field_name,
                        type_contract=item_contract,
                        apply=_record_mutation(
                            case, _set_field(field_name, [{"wrong": "item"}])
                        ),
                        expected_error="list item",
                    ),
                    SchemaMutation(
                        name=f"{case.name}-{field_name}-invalid-item",
                        kind="invalid_list_item_value",
                        target_field=field_name,
                        type_contract=item_contract,
                        apply=_record_mutation(
                            case,
                            _set_field(field_name, [_invalid_atomic(item_contract)]),
                        ),
                        expected_error="invalid",
                    ),
                    SchemaMutation(
                        name=f"{case.name}-{field_name}-duplicate-item",
                        kind="duplicate_list_item",
                        target_field=field_name,
                        type_contract=item_contract,
                        apply=_record_mutation(
                            case,
                            _duplicate_list(
                                field_name,
                                _valid_list_values(case.name, field_name),
                            ),
                        ),
                        expected_error="duplicate",
                    ),
                ]
            )
            if field_name in _SORTED_SET_FIELDS.get(case.name, frozenset()):
                values = _valid_list_values(case.name, field_name)
                mutations.append(
                    SchemaMutation(
                        name=f"{case.name}-{field_name}-unsorted",
                        kind="unsorted_set_list",
                        target_field=field_name,
                        type_contract=item_contract,
                        apply=_record_mutation(
                            case, _set_field(field_name, list(reversed(values)))
                        ),
                        expected_error="sorted",
                    )
                )
        if contract.startswith("mapping:"):
            nested_name = contract.removeprefix("mapping:")
            mutations.append(
                SchemaMutation(
                    name=f"{case.name}-{field_name}-invalid-mapping",
                    kind="invalid_nested_mapping_shape",
                    target_field=field_name,
                    type_contract=nested_name,
                    apply=_record_mutation(case, _set_field(field_name, {})),
                    expected_error="missing field",
                )
            )
    for field_name in case.reference_fields:
        mutations.append(
            SchemaMutation(
                name=f"{case.name}-{field_name}-broken-reference",
                kind="broken_reference",
                target_field=field_name,
                type_contract=dict(case.field_types)[field_name],
                apply=_record_mutation(case, _break_reference(field_name)),
                expected_error="reference",
            )
        )
    if case.name in _BAD_EVIDENCE_LEVEL:
        mutations.append(
            SchemaMutation(
                name=f"{case.name}-evidence-scope-mismatch",
                kind="evidence_scope_mismatch",
                target_field="evidence_level",
                type_contract=dict(case.field_types)["evidence_level"],
                apply=_record_mutation(
                    case,
                    _set_field("evidence_level", _BAD_EVIDENCE_LEVEL[case.name]),
                ),
                expected_error=(
                    "grade D cannot support lifecycle"
                    if case.name == "specific_lifecycle"
                    else "evidence level"
                ),
            )
        )
    return tuple(mutations)


def all_closed_schema_mutations() -> tuple[SchemaMutation, ...]:
    return tuple(
        mutation
        for case in all_closed_record_cases()
        for mutation in closed_schema_mutations(case)
    )


def root_schema_mutations() -> tuple[SchemaMutation, ...]:
    mutations: list[SchemaMutation] = []
    for relative_path, fields in _ROOT_VALUE_TYPES.items():
        for field_name, contract in fields.items():
            target = f"{relative_path}:{field_name}"

            def apply_wrong(
                source: Path,
                path: str = relative_path,
                field: str = field_name,
                expected: str = contract,
            ) -> None:
                mutate_yaml(
                    _fixture_path(source, path),
                    lambda document: document.update(
                        {field: _wrong_value(expected)}
                    ),
                )

            mutations.append(
                SchemaMutation(
                    name=f"root-{relative_path.replace('/', '-')}-{field_name}-wrong",
                    kind="wrong_type",
                    target_field=target,
                    type_contract=contract,
                    apply=apply_wrong,
                    expected_error="must be",
                )
            )
            if contract.startswith(("list:", "nonempty_list:")):
                item_contract = contract.split(":", 1)[1]

                def apply_item(
                    source: Path,
                    path: str = relative_path,
                    field: str = field_name,
                ) -> None:
                    mutate_yaml(
                        _fixture_path(source, path),
                        lambda document: document.update(
                            {field: ["not-a-record-mapping"]}
                        ),
                    )

                mutations.append(
                    SchemaMutation(
                        name=f"root-{relative_path.replace('/', '-')}-{field_name}-item",
                        kind="wrong_list_item_type",
                        target_field=target,
                        type_contract=item_contract,
                        apply=apply_item,
                        expected_error="list item",
                    )
                )
            if contract.startswith("mapping:"):
                nested_name = contract.removeprefix("mapping:")

                def apply_mapping(
                    source: Path,
                    path: str = relative_path,
                    field: str = field_name,
                ) -> None:
                    mutate_yaml(
                        _fixture_path(source, path),
                        lambda document: document.update({field: {}}),
                    )

                mutations.append(
                    SchemaMutation(
                        name=f"root-{relative_path.replace('/', '-')}-{field_name}-mapping",
                        kind="invalid_nested_mapping_shape",
                        target_field=target,
                        type_contract=nested_name,
                        apply=apply_mapping,
                        expected_error="missing field",
                    )
                )
            if contract == "semver":

                def apply_semver(
                    source: Path,
                    path: str = relative_path,
                    field: str = field_name,
                ) -> None:
                    mutate_yaml(
                        _fixture_path(source, path),
                        lambda document: document.update({field: "2.0"}),
                    )

                mutations.append(
                    SchemaMutation(
                        name=f"root-{relative_path.replace('/', '-')}-{field_name}-semver",
                        kind="invalid_contract_value",
                        target_field=target,
                        type_contract="semver",
                        apply=apply_semver,
                        expected_error="invalid",
                    )
                )
    return tuple(mutations)


def _replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise AssertionError(f"fixture token not found in {path}: {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _regex_replace_once(path: Path, pattern: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    changed, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise AssertionError(f"fixture pattern not found in {path}: {pattern!r}")
    path.write_text(changed, encoding="utf-8")


_RAW_ERRORS = {
    "duplicate_key": "duplicate key",
    "anchor_definition": "anchors",
    "alias_reference": "aliases",
    "merge_key": "merge keys",
    "explicit_tag": "explicit tags",
    "non_scalar_mapping_key": "scalar mapping keys",
    "non_mapping_document_root": "mapping root",
    "non_nfc_text": "NFC",
    "untrimmed_text": "trimmed",
    "control_character_text": "control",
    "native_yaml_timestamp": "quoted date",
}


def shared_raw_yaml_mutations() -> tuple[SchemaMutation, ...]:
    def sources(source: Path) -> Path:
        return source / "common/sources.yaml"

    def bundle(source: Path) -> Path:
        return source / "bundle.yaml"

    operations: dict[str, tuple[str, Callable[[Path], None]]] = {
        "duplicate_key": (
            "common/sources.yaml:sources[0].title",
            lambda source: _regex_replace_once(
                sources(source),
                r"^(  title: .+)$",
                r"\1\n  title: Duplicate title",
            ),
        ),
        "anchor_definition": (
            "common/sources.yaml:sources[0]",
            lambda source: _replace_once(
                sources(source), "- source_id:", "- &source_anchor\n  source_id:"
            ),
        ),
        "alias_reference": (
            "common/sources.yaml:sources[0]",
            lambda source: sources(source).write_text(
                "sources:\n- *missing_source_alias\n", encoding="utf-8"
            ),
        ),
        "merge_key": (
            "common/sources.yaml:sources[0]",
            lambda source: _replace_once(
                sources(source), "- source_id:", "- <<: {title: merged}\n  source_id:"
            ),
        ),
        "explicit_tag": (
            "bundle.yaml:bundle.schema_version",
            lambda source: _regex_replace_once(
                bundle(source),
                r"^(  schema_version:) 3$",
                r'\1 !!int "3"',
            ),
        ),
        "non_scalar_mapping_key": (
            "bundle.yaml:document_root",
            lambda source: bundle(source).write_text(
                "? [bundle]\n: {}\n", encoding="utf-8"
            ),
        ),
        "non_mapping_document_root": (
            "bundle.yaml:document_root",
            lambda source: bundle(source).write_text(
                "- bundle\n- is\n- not\n- a\n- mapping\n", encoding="utf-8"
            ),
        ),
        "non_nfc_text": (
            "common/sources.yaml:sources[0].title",
            lambda source: _regex_replace_once(
                sources(source), r"^  title: .+$", "  title: Cafe\u0301 evidence"
            ),
        ),
        "untrimmed_text": (
            "common/sources.yaml:sources[0].title",
            lambda source: _regex_replace_once(
                sources(source), r"^  title: .+$", "  title: ' padded title '"
            ),
        ),
        "control_character_text": (
            "common/sources.yaml:sources[0].title",
            lambda source: _regex_replace_once(
                sources(source), r"^  title: .+$", r'  title: "bad\\u0001title"'
            ),
        ),
        "native_yaml_timestamp": (
            "common/sources.yaml:sources[0].publication_or_revision_date",
            lambda source: _regex_replace_once(
                sources(source),
                r"^(  publication_or_revision_date:) ['\"]2026-01-01['\"]$",
                r"\1 2026-01-01",
            ),
        ),
    }
    return tuple(
        SchemaMutation(
            name=name,
            kind=name,
            target_field=target,
            type_contract="raw_yaml",
            apply=operation,
            expected_error=_RAW_ERRORS[name],
        )
        for name, (target, operation) in operations.items()
    )


def category_raw_yaml_mutations(category_id: str) -> tuple[SchemaMutation, ...]:
    relative = f"categories/{category_id}/identities.yaml"

    def identities(source: Path) -> Path:
        return source / relative

    operations: dict[str, tuple[str, Callable[[Path], None]]] = {
        "duplicate_key": (
            f"{relative}:category.display_name",
            lambda source: _regex_replace_once(
                identities(source),
                r"^(  display_name: .+)$",
                r"\1\n  display_name: Duplicate category",
            ),
        ),
        "anchor_definition": (
            f"{relative}:category",
            lambda source: _replace_once(
                identities(source), "category:\n", "category: &category_anchor\n"
            ),
        ),
        "alias_reference": (
            f"{relative}:category",
            lambda source: _regex_replace_once(
                identities(source),
                r"^category:\n(?:  .+\n)+?(?=subtypes:)",
                "category: *missing_category_alias\n",
            ),
        ),
        "merge_key": (
            f"{relative}:category",
            lambda source: _replace_once(
                identities(source),
                "category:\n",
                "category:\n  <<: {display_name: merged}\n",
            ),
        ),
        "explicit_tag": (
            f"{relative}:category.category_id",
            lambda source: _regex_replace_once(
                identities(source),
                r"^(  category_id:) (.+)$",
                r'\1 !!str "\2"',
            ),
        ),
        "non_scalar_mapping_key": (
            f"{relative}:document_root",
            lambda source: identities(source).write_text(
                "? [category]\n: {}\n", encoding="utf-8"
            ),
        ),
        "non_mapping_document_root": (
            f"{relative}:document_root",
            lambda source: identities(source).write_text(
                "- category\n- is\n- not\n- a\n- mapping\n", encoding="utf-8"
            ),
        ),
        "non_nfc_text": (
            f"{relative}:category.display_name",
            lambda source: _regex_replace_once(
                identities(source), r"^  display_name: .+$", "  display_name: Cafe\u0301"
            ),
        ),
        "untrimmed_text": (
            f"{relative}:category.display_name",
            lambda source: _regex_replace_once(
                identities(source), r"^  display_name: .+$", "  display_name: ' padded '"
            ),
        ),
        "control_character_text": (
            f"{relative}:category.display_name",
            lambda source: _regex_replace_once(
                identities(source), r"^  display_name: .+$", r'  display_name: "bad\\u0001name"'
            ),
        ),
        "native_yaml_timestamp": (
            f"{relative}:identities[0].applicable_from",
            lambda source: _regex_replace_once(
                identities(source),
                r"^(  applicable_from:) ['\"]2020-01-01['\"]$",
                r"\1 2020-01-01",
            ),
        ),
    }
    return tuple(
        SchemaMutation(
            name=name,
            kind=name,
            target_field=target,
            type_contract="raw_yaml",
            apply=operation,
            expected_error=_RAW_ERRORS[name],
        )
        for name, (target, operation) in operations.items()
    )


def _replace_path_with_symlink(path: Path) -> None:
    was_directory = path.is_dir()
    if was_directory:
        shutil.rmtree(path)
    else:
        path.unlink()
    missing_target = path.with_name(f".{path.name}.missing-target")
    path.symlink_to(missing_target, target_is_directory=was_directory)


def shared_path_mutations() -> tuple[SchemaMutation, ...]:
    entries: list[tuple[str, str, Callable[[Path], None], str]] = [
        (
            "symlink_source_dir",
            ".",
            _replace_path_with_symlink,
            "unsafe path",
        ),
        (
            "symlink_common_directory",
            "common",
            lambda source: _replace_path_with_symlink(source / "common"),
            "unsafe path",
        ),
    ]
    for relative_path in (
        "bundle.yaml",
        "common/sources.yaml",
        "common/policies.yaml",
    ):
        entries.append(
            (
                f"symlink_document_{relative_path.replace('/', '_')}",
                relative_path,
                lambda source, path=relative_path: _replace_path_with_symlink(
                    source / path
                ),
                "unsafe path",
            )
        )
    entries.extend(
        [
            (
                "unexpected_root_entry",
                "unexpected-root.yaml",
                lambda source: (source / "unexpected-root.yaml").write_text(
                    "unexpected: true\n", encoding="utf-8"
                ),
                "unexpected",
            ),
            (
                "unexpected_common_entry",
                "common/unexpected.yaml",
                lambda source: (source / "common/unexpected.yaml").write_text(
                    "unexpected: true\n", encoding="utf-8"
                ),
                "unexpected",
            ),
        ]
    )
    return tuple(
        SchemaMutation(
            name,
            "symlink_document" if name.startswith("symlink_document") else name,
            target,
            "path",
            apply,
            error,
        )
        for name, target, apply, error in entries
    )


def category_path_mutations(category_id: str) -> tuple[SchemaMutation, ...]:
    category_prefix = f"categories/{category_id}"
    entries: list[tuple[str, str, Callable[[Path], None], str]] = [
        (
            "symlink_categories_directory",
            "categories",
            lambda source: _replace_path_with_symlink(source / "categories"),
            "unsafe path",
        ),
        (
            "symlink_category_directory",
            category_prefix,
            lambda source: _replace_path_with_symlink(source / category_prefix),
            "unsafe path",
        ),
    ]
    for filename in (
        "sources.yaml",
        "identities.yaml",
        "lifecycles.yaml",
        "industry_averages.yaml",
        "components.yaml",
        "hazards.yaml",
        "coverage.yaml",
    ):
        relative_path = f"{category_prefix}/{filename}"
        entries.append(
            (
                f"symlink_document_{filename.replace('.', '_')}",
                relative_path,
                lambda source, path=relative_path: _replace_path_with_symlink(
                    source / path
                ),
                "unsafe path",
            )
        )
    entries.append(
        (
            "unexpected_category_entry",
            f"{category_prefix}/unexpected.yaml",
            lambda source: (
                source / category_prefix / "unexpected.yaml"
            ).write_text("unexpected: true\n", encoding="utf-8"),
            "unexpected",
        )
    )
    return tuple(
        SchemaMutation(name, "symlink_document" if name.startswith("symlink_document") else name, target, "path", apply, error)
        for name, target, apply, error in entries
    )


def complete_tree_mutations() -> tuple[SchemaMutation, ...]:
    headphones = "categories/0401_headphones"

    def remove_headphones(source: Path) -> None:
        shutil.rmtree(source / headphones)

    def extra_category(source: Path) -> None:
        (source / "categories/not_released").mkdir()

    return (
        SchemaMutation(
            "missing_released_sibling",
            "missing_released_sibling",
            headphones,
            "path",
            remove_headphones,
            "missing category directory",
        ),
        SchemaMutation(
            "extra_sibling_category",
            "extra_sibling_category",
            "categories/not_released",
            "path",
            extra_category,
            "unexpected category directory",
        ),
        SchemaMutation(
            "symlink_released_sibling",
            "symlink_released_sibling",
            headphones,
            "path",
            lambda source: _replace_path_with_symlink(source / headphones),
            "unsafe path",
        ),
    )

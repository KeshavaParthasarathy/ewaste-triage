from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from datetime import date
import os
from pathlib import Path
import shutil
from typing import Callable

import pytest

import scripts.knowledge_schema as knowledge_schema
from scripts.knowledge_schema import (
    CategoryEvidenceDocuments,
    EvidenceDocuments,
    EvidenceValidationError,
    SharedEvidenceDocuments,
    load_category_evidence_documents,
    load_evidence_documents,
    load_shared_evidence_documents,
)
from server.evidence_types import (
    AssociationStatus,
    BatteryArchitecture,
    EvidenceLevel,
    IdentityKind,
    LifecycleEndpointKind,
    MarketState,
    RecommendationValue,
    RELEASED_CATEGORY_IDS,
    ScopeKind,
)
from tests.knowledge_helpers import (
    SchemaCase,
    all_closed_record_cases,
    all_closed_schema_mutations,
    category_path_mutations,
    category_raw_yaml_mutations,
    closed_schema_mutations,
    complete_tree_mutations,
    make_valid_category_knowledge_source,
    make_valid_knowledge_source,
    make_valid_shared_knowledge_source,
    mutate_document_root,
    mutate_yaml,
    record_field_type_sets,
    record_key_sets,
    replace_with_non_mapping_yaml_root,
    root_key_sets,
    root_schema_mutations,
    root_value_type_sets,
    shared_path_mutations,
    shared_raw_yaml_mutations,
)


TEST_CATEGORY_ID = "0301_computer_mouse"

ROOT_KEYS = {
    "bundle.yaml": {"bundle"},
    "common/sources.yaml": {"sources"},
    "common/policies.yaml": {"policy_revision", "policies"},
    "categories/{category_id}/sources.yaml": {"sources"},
    "categories/{category_id}/identities.yaml": {
        "category",
        "subtypes",
        "variants",
        "identities",
    },
    "categories/{category_id}/lifecycles.yaml": {"lifecycles"},
    "categories/{category_id}/industry_averages.yaml": {"industry_averages"},
    "categories/{category_id}/components.yaml": {
        "components",
        "templates",
        "associations",
    },
    "categories/{category_id}/hazards.yaml": {"hazards"},
    "categories/{category_id}/coverage.yaml": {"unknowns"},
}

ROOT_VALUE_TYPES = {
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

RECORD_KEYS = {
    "bundle": {
        "schema_version",
        "bundle_version",
        "identity_catalog_version",
        "policy_revision",
        "category_ids",
    },
    "source": {
        "source_id",
        "title",
        "publisher",
        "canonical_url",
        "publication_or_revision_date",
        "accessed_on",
        "license_or_use_basis",
        "reviewed_by",
        "reviewed_on",
    },
    "policy": {
        "rule_id",
        "priority",
        "outcome",
        "when_all",
        "when_any",
        "rationale",
        "evidence_level",
        "source_ids",
    },
    "category": {"category_id", "display_name"},
    "subtype": {
        "subtype_id",
        "category_id",
        "display_name",
        "market_state",
        "battery_architecture",
        "evidence_level",
        "source_ids",
    },
    "variant": {
        "variant_id",
        "category_id",
        "subtype_id",
        "display_name",
        "battery_architecture",
        "evidence_level",
        "source_ids",
    },
    "identity": {
        "identity_id",
        "identity_kind",
        "category_id",
        "subtype_id",
        "manufacturer_id",
        "manufacturer_name",
        "family_id",
        "family_name",
        "model_id",
        "model_name",
        "display_name",
        "aliases",
        "distinguishing_tokens",
        "model_year_from",
        "model_year_to",
        "applicable_from",
        "applicable_to",
        "variant_ids",
        "market_state",
        "battery_architecture",
        "evidence_level",
        "source_ids",
    },
    "specific_lifecycle": {
        "record_id",
        "scope",
        "subject",
        "endpoint",
        "endpoint_kind",
        "metric",
        "unit",
        "lower_bound",
        "upper_bound",
        "endpoint_qualification",
        "applicable_from",
        "applicable_to",
        "model_year_from",
        "model_year_to",
        "required_variant_ids",
        "excluded_variant_ids",
        "precedence",
        "evidence_level",
        "assumptions",
        "source_ids",
    },
    "industry_average": {
        "record_id",
        "scope",
        "subject",
        "endpoint",
        "endpoint_kind",
        "metric",
        "unit",
        "lower_bound",
        "upper_bound",
        "endpoint_qualification",
        "applicable_from",
        "applicable_to",
        "model_year_from",
        "model_year_to",
        "required_variant_ids",
        "excluded_variant_ids",
        "precedence",
        "evidence_level",
        "assumptions",
        "population_definition",
        "publication_period",
        "methodology",
        "uncertainty",
        "limitations",
        "source_ids",
    },
    "component_definition": {"component_id", "display_name"},
    "component_template": {
        "template_id",
        "template_kind",
        "scope",
        "application_order",
    },
    "component_association": {
        "association_id",
        "template_id",
        "component_id",
        "position",
        "status",
        "applicability",
        "notes",
        "evidence_level",
        "source_ids",
    },
    "hazard": {
        "hazard_id",
        "component_id",
        "scope",
        "applicability",
        "trigger_observation_keys",
        "severity",
        "immediate_actions",
        "follow_up_actions",
        "handling_guidance",
        "disposal_guidance",
        "evidence_level",
        "source_ids",
    },
    "unknown": {
        "category_id",
        "claim_kind",
        "claim_id",
        "evidence_level",
        "source_ids",
        "reason",
        "evidence_request",
    },
    "scope": {"kind", "id"},
}

FIELD_TYPES = {
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


def _is_shared_path(relative_path: str) -> bool:
    return not relative_path.startswith("categories/")


def _make_source_for_path(tmp_path: Path, relative_path: str, name: str) -> Path:
    root = tmp_path / name
    if _is_shared_path(relative_path):
        return make_valid_shared_knowledge_source(root)
    return make_valid_category_knowledge_source(root, TEST_CATEGORY_ID)


def _load_for_path(source: Path, relative_path: str):
    if _is_shared_path(relative_path):
        return load_shared_evidence_documents(source)
    shared = load_shared_evidence_documents(source)
    return load_category_evidence_documents(
        source, TEST_CATEGORY_ID, shared=shared
    )


def test_normalized_document_surfaces_have_no_aliases():
    assert tuple(field.name for field in fields(SharedEvidenceDocuments)) == (
        "bundle",
        "sources",
        "policies",
    )
    assert tuple(field.name for field in fields(CategoryEvidenceDocuments)) == (
        "category",
        "sources",
        "subtypes",
        "variants",
        "identities",
        "specific_lifecycles",
        "industry_averages",
        "component_definitions",
        "component_templates",
        "component_associations",
        "hazards",
        "unknowns",
    )
    assert tuple(field.name for field in fields(EvidenceDocuments)) == (
        "shared",
        "categories",
    )


def test_helper_fixture_pins_every_root_and_record_shape(tmp_path):
    source = make_valid_knowledge_source(tmp_path)
    assert root_key_sets(source) == ROOT_KEYS
    assert root_value_type_sets(source) == ROOT_VALUE_TYPES
    assert record_key_sets(source) == RECORD_KEYS
    assert record_field_type_sets(source) == FIELD_TYPES


@pytest.mark.parametrize("relative_path,expected_keys", ROOT_KEYS.items())
def test_every_document_root_is_closed_through_its_direct_loader(
    tmp_path, relative_path, expected_keys
):
    source = _make_source_for_path(tmp_path, relative_path, "unknown")
    mutate_document_root(source, relative_path, expected_keys, "unknown_key")
    with pytest.raises(EvidenceValidationError, match="document root"):
        _load_for_path(source, relative_path)
    for missing_key in expected_keys:
        source = _make_source_for_path(
            tmp_path, relative_path, f"missing-{missing_key}"
        )
        mutate_document_root(
            source, relative_path, expected_keys, f"missing_key:{missing_key}"
        )
        with pytest.raises(EvidenceValidationError, match="document root"):
            _load_for_path(source, relative_path)


def test_every_root_value_type_and_list_item_type_is_mutated_via_direct_loader(
    tmp_path,
):
    expected = {
        ("wrong_type", f"{path}:{key}", contract)
        for path, root_fields in ROOT_VALUE_TYPES.items()
        for key, contract in root_fields.items()
    }
    expected |= {
        ("wrong_list_item_type", f"{path}:{key}", contract.split(":", 1)[1])
        for path, root_fields in ROOT_VALUE_TYPES.items()
        for key, contract in root_fields.items()
        if contract.startswith(("list:", "nonempty_list:"))
    }
    expected |= {
        (
            "invalid_nested_mapping_shape",
            f"{path}:{key}",
            contract.split(":", 1)[1],
        )
        for path, root_fields in ROOT_VALUE_TYPES.items()
        for key, contract in root_fields.items()
        if contract.startswith("mapping:")
    }
    expected |= {
        ("invalid_contract_value", f"{path}:{key}", "semver")
        for path, root_fields in ROOT_VALUE_TYPES.items()
        for key, contract in root_fields.items()
        if contract == "semver"
    }
    mutations = root_schema_mutations()
    assert {
        (item.kind, item.target_field, item.type_contract) for item in mutations
    } == expected
    for mutation in mutations:
        relative_path = mutation.target_field.split(":", 1)[0]
        source = _make_source_for_path(
            tmp_path, relative_path, f"root-{mutation.name}"
        )
        mutation.apply(source)
        with pytest.raises(
            EvidenceValidationError, match=mutation.expected_error
        ):
            _load_for_path(source, relative_path)


@pytest.mark.parametrize("case", all_closed_record_cases(), ids=lambda case: case.name)
def test_every_record_schema_rejects_its_complete_mutation_matrix(
    tmp_path, case: SchemaCase
):
    for mutation in closed_schema_mutations(case):
        source = _make_source_for_path(
            tmp_path, case.relative_path, mutation.name
        )
        mutation.apply(source)
        with pytest.raises(
            EvidenceValidationError, match=mutation.expected_error
        ):
            _load_for_path(source, case.relative_path)


def test_mutation_matrix_covers_every_closed_failure_class():
    assert {mutation.kind for mutation in all_closed_schema_mutations()} == {
        "unknown_key",
        "missing_key",
        "null_nonnullable",
        "wrong_type",
        "invalid_contract_value",
        "boolean_as_integer",
        "nonfinite_number",
        "nullable_wrong_underlying_type",
        "null_list",
        "wrong_list_item_type",
        "invalid_list_item_value",
        "duplicate_list_item",
        "unsorted_set_list",
        "invalid_nested_mapping_shape",
        "broken_reference",
        "evidence_scope_mismatch",
    }


def _nullable_contracts(field_types):
    return {
        (field_name, contract.removeprefix("nullable:"))
        for field_name, contract in field_types.items()
        if contract.startswith("nullable:")
    }


def _list_contracts(field_types):
    return {
        (
            field_name,
            contract.removeprefix("nonempty_list:").removeprefix("list:"),
        )
        for field_name, contract in field_types.items()
        if contract.startswith(("list:", "nonempty_list:"))
    }


def _nested_contracts(field_types):
    return {
        (field_name, contract.removeprefix("mapping:"))
        for field_name, contract in field_types.items()
        if contract.startswith("mapping:")
    }


def _fields_with_atomic_contract(field_types, atomic_contract):
    result = set()
    for field_name, contract in field_types.items():
        unwrapped = contract
        for prefix in ("nullable:", "nonempty_list:", "list:"):
            if unwrapped.startswith(prefix):
                unwrapped = unwrapped.removeprefix(prefix)
                break
        if unwrapped == atomic_contract:
            result.add(field_name)
    return result


def _fields_with_prefix_contract(field_types, prefix):
    return {
        field_name
        for field_name, contract in field_types.items()
        if contract.startswith(prefix) or contract.startswith(f"nullable:{prefix}")
    }


@pytest.mark.parametrize("case", all_closed_record_cases(), ids=lambda case: case.name)
def test_each_case_mutates_every_required_key_typed_field_and_reference(case):
    mutations = closed_schema_mutations(case)
    assert case.expected_keys == RECORD_KEYS[case.name]
    assert dict(case.field_types) == FIELD_TYPES[case.name]
    assert set(case.nullable_underlying_types) == _nullable_contracts(
        FIELD_TYPES[case.name]
    )
    assert set(case.list_item_types) == _list_contracts(FIELD_TYPES[case.name])
    assert set(case.nested_mapping_fields) == _nested_contracts(
        FIELD_TYPES[case.name]
    )
    assert case.id_fields == _fields_with_atomic_contract(
        FIELD_TYPES[case.name], "id"
    )
    assert case.text_fields == _fields_with_atomic_contract(
        FIELD_TYPES[case.name], "text"
    )
    assert case.date_fields == _fields_with_atomic_contract(
        FIELD_TYPES[case.name], "date"
    )
    assert case.semver_fields == _fields_with_atomic_contract(
        FIELD_TYPES[case.name], "semver"
    )
    assert case.https_url_fields == _fields_with_atomic_contract(
        FIELD_TYPES[case.name], "https_url"
    )
    assert case.nullable_fields == {
        field_name
        for field_name, contract in FIELD_TYPES[case.name].items()
        if contract.startswith("nullable:") or contract == "literal:null"
    }
    assert case.required_nonnull_fields == case.expected_keys - case.nullable_fields
    assert case.list_fields == _fields_with_prefix_contract(
        FIELD_TYPES[case.name], "list:"
    ) | _fields_with_prefix_contract(FIELD_TYPES[case.name], "nonempty_list:")
    assert case.integer_fields == _fields_with_atomic_contract(
        FIELD_TYPES[case.name], "int"
    )
    assert case.number_fields == _fields_with_atomic_contract(
        FIELD_TYPES[case.name], "number"
    )
    assert case.enum_fields == _fields_with_prefix_contract(
        FIELD_TYPES[case.name], "enum:"
    )
    assert {
        item.target_field for item in mutations if item.kind == "missing_key"
    } == case.expected_keys
    assert {
        item.target_field
        for item in mutations
        if item.kind == "null_nonnullable"
    } == case.required_nonnull_fields
    assert case.required_nonnull_fields | case.nullable_fields == case.expected_keys
    assert case.required_nonnull_fields.isdisjoint(case.nullable_fields)
    assert {
        (item.target_field, item.type_contract)
        for item in mutations
        if item.kind == "wrong_type"
    } == set(FIELD_TYPES[case.name].items())
    assert {
        (item.target_field, item.type_contract)
        for item in mutations
        if item.kind == "nullable_wrong_underlying_type"
    } == set(case.nullable_underlying_types)
    assert {
        (item.target_field, item.type_contract)
        for item in mutations
        if item.kind == "wrong_list_item_type"
    } == set(case.list_item_types)
    assert {
        item.target_field for item in mutations if item.kind == "null_list"
    } == case.list_fields
    assert {
        (item.target_field, item.type_contract)
        for item in mutations
        if item.kind == "invalid_list_item_value"
    } == set(case.list_item_types)
    assert {
        (item.target_field, item.type_contract)
        for item in mutations
        if item.kind == "invalid_nested_mapping_shape"
    } == set(case.nested_mapping_fields)
    assert {
        item.target_field
        for item in mutations
        if item.kind == "boolean_as_integer"
    } == case.integer_fields | case.number_fields
    assert {
        item.target_field for item in mutations if item.kind == "nonfinite_number"
    } == case.number_fields
    assert {
        item.target_field for item in mutations if item.kind == "broken_reference"
    } == case.reference_fields
    assert all(
        any(
            item.target_field == field_name
            and item.kind
            in {"invalid_contract_value", "invalid_list_item_value"}
            for item in mutations
        )
        for field_name in (
            case.id_fields
            | case.text_fields
            | case.date_fields
            | case.semver_fields
            | case.https_url_fields
            | case.enum_fields
        )
    )


RAW_YAML_REJECTIONS = {
    "duplicate_key",
    "anchor_definition",
    "alias_reference",
    "merge_key",
    "explicit_tag",
    "non_scalar_mapping_key",
    "non_mapping_document_root",
    "non_nfc_text",
    "untrimmed_text",
    "control_character_text",
    "native_yaml_timestamp",
}

SHARED_RAW_YAML_REJECTION_TARGETS = {
    "duplicate_key": "common/sources.yaml:sources[0].title",
    "anchor_definition": "common/sources.yaml:sources[0]",
    "alias_reference": "common/sources.yaml:sources[0]",
    "merge_key": "common/sources.yaml:sources[0]",
    "explicit_tag": "bundle.yaml:bundle.schema_version",
    "non_scalar_mapping_key": "bundle.yaml:document_root",
    "non_mapping_document_root": "bundle.yaml:document_root",
    "non_nfc_text": "common/sources.yaml:sources[0].title",
    "untrimmed_text": "common/sources.yaml:sources[0].title",
    "control_character_text": "common/sources.yaml:sources[0].title",
    "native_yaml_timestamp": (
        "common/sources.yaml:sources[0].publication_or_revision_date"
    ),
}

CATEGORY_RAW_YAML_REJECTION_TARGETS = {
    "duplicate_key": (
        "categories/0301_computer_mouse/identities.yaml:category.display_name"
    ),
    "anchor_definition": (
        "categories/0301_computer_mouse/identities.yaml:category"
    ),
    "alias_reference": (
        "categories/0301_computer_mouse/identities.yaml:category"
    ),
    "merge_key": "categories/0301_computer_mouse/identities.yaml:category",
    "explicit_tag": (
        "categories/0301_computer_mouse/identities.yaml:category.category_id"
    ),
    "non_scalar_mapping_key": (
        "categories/0301_computer_mouse/identities.yaml:document_root"
    ),
    "non_mapping_document_root": (
        "categories/0301_computer_mouse/identities.yaml:document_root"
    ),
    "non_nfc_text": (
        "categories/0301_computer_mouse/identities.yaml:category.display_name"
    ),
    "untrimmed_text": (
        "categories/0301_computer_mouse/identities.yaml:category.display_name"
    ),
    "control_character_text": (
        "categories/0301_computer_mouse/identities.yaml:category.display_name"
    ),
    "native_yaml_timestamp": (
        "categories/0301_computer_mouse/identities.yaml:identities[0].applicable_from"
    ),
}

SHARED_ROOT_PATHS = (
    "bundle.yaml",
    "common/sources.yaml",
    "common/policies.yaml",
)
CATEGORY_ROOT_PATHS = tuple(
    path.format(category_id=TEST_CATEGORY_ID)
    for path in ROOT_KEYS
    if path.startswith("categories/")
)

SHARED_PATH_REJECTION_TARGETS = {
    ("symlink_source_dir", "."),
    ("symlink_common_directory", "common"),
    *{("symlink_document", path) for path in SHARED_ROOT_PATHS},
    ("unexpected_root_entry", "unexpected-root.yaml"),
    ("unexpected_common_entry", "common/unexpected.yaml"),
}

CATEGORY_PATH_REJECTION_TARGETS = {
    ("symlink_categories_directory", "categories"),
    ("symlink_category_directory", f"categories/{TEST_CATEGORY_ID}"),
    *{("symlink_document", path) for path in CATEGORY_ROOT_PATHS},
    (
        "unexpected_category_entry",
        f"categories/{TEST_CATEGORY_ID}/unexpected.yaml",
    ),
}

COMPLETE_TREE_REJECTION_TARGETS = {
    ("missing_released_sibling", "categories/0401_headphones"),
    ("extra_sibling_category", "categories/not_released"),
    ("symlink_released_sibling", "categories/0401_headphones"),
}


def test_shared_loader_executes_every_hostile_raw_yaml_case(tmp_path):
    mutations = shared_raw_yaml_mutations()
    assert {item.name for item in mutations} == RAW_YAML_REJECTIONS
    assert {
        (item.kind, item.target_field) for item in mutations
    } == set(SHARED_RAW_YAML_REJECTION_TARGETS.items())
    for mutation in mutations:
        source = make_valid_shared_knowledge_source(tmp_path / mutation.name)
        mutation.apply(source)
        with pytest.raises(
            EvidenceValidationError, match=mutation.expected_error
        ):
            load_shared_evidence_documents(source)


def test_category_loader_executes_every_hostile_raw_yaml_case(tmp_path):
    mutations = category_raw_yaml_mutations(TEST_CATEGORY_ID)
    assert {item.name for item in mutations} == RAW_YAML_REJECTIONS
    assert {
        (item.kind, item.target_field) for item in mutations
    } == set(CATEGORY_RAW_YAML_REJECTION_TARGETS.items())
    for mutation in mutations:
        source = make_valid_category_knowledge_source(
            tmp_path / mutation.name, TEST_CATEGORY_ID
        )
        shared = load_shared_evidence_documents(source)
        mutation.apply(source)
        with pytest.raises(
            EvidenceValidationError, match=mutation.expected_error
        ):
            load_category_evidence_documents(
                source, TEST_CATEGORY_ID, shared=shared
            )


@pytest.mark.parametrize("relative_path", SHARED_ROOT_PATHS)
def test_shared_loader_rejects_each_non_mapping_root(tmp_path, relative_path):
    source = make_valid_shared_knowledge_source(
        tmp_path / relative_path.replace("/", "-")
    )
    replace_with_non_mapping_yaml_root(source, relative_path)
    with pytest.raises(EvidenceValidationError, match="mapping root"):
        load_shared_evidence_documents(source)


@pytest.mark.parametrize("relative_path", CATEGORY_ROOT_PATHS)
def test_category_loader_rejects_each_non_mapping_root(tmp_path, relative_path):
    source = make_valid_category_knowledge_source(tmp_path, TEST_CATEGORY_ID)
    shared = load_shared_evidence_documents(source)
    replace_with_non_mapping_yaml_root(source, relative_path)
    with pytest.raises(EvidenceValidationError, match="mapping root"):
        load_category_evidence_documents(source, TEST_CATEGORY_ID, shared=shared)


def test_shared_loader_rejects_its_own_hostile_paths(tmp_path):
    mutations = shared_path_mutations()
    assert {
        (item.kind, item.target_field) for item in mutations
    } == SHARED_PATH_REJECTION_TARGETS
    for mutation in mutations:
        source = make_valid_shared_knowledge_source(tmp_path / mutation.name)
        mutation.apply(source)
        with pytest.raises(
            EvidenceValidationError, match=mutation.expected_error
        ):
            load_shared_evidence_documents(source)


def test_category_loader_rejects_its_own_hostile_paths(tmp_path):
    mutations = category_path_mutations(TEST_CATEGORY_ID)
    assert {
        (item.kind, item.target_field) for item in mutations
    } == CATEGORY_PATH_REJECTION_TARGETS
    for mutation in mutations:
        source = make_valid_category_knowledge_source(
            tmp_path / mutation.name, TEST_CATEGORY_ID
        )
        shared = load_shared_evidence_documents(source)
        mutation.apply(source)
        with pytest.raises(
            EvidenceValidationError, match=mutation.expected_error
        ):
            load_category_evidence_documents(
                source, TEST_CATEGORY_ID, shared=shared
            )


def test_complete_loader_enforces_global_sibling_category_closure(tmp_path):
    mutations = complete_tree_mutations()
    assert {
        (item.kind, item.target_field) for item in mutations
    } == COMPLETE_TREE_REJECTION_TARGETS
    for mutation in mutations:
        source = make_valid_knowledge_source(tmp_path / mutation.name)
        mutation.apply(source)
        with pytest.raises(
            EvidenceValidationError, match=mutation.expected_error
        ):
            load_evidence_documents(source)


@pytest.mark.parametrize(
    "category_id",
    [
        "../0301_computer_mouse",
        "0301_COMPUTER_MOUSE",
        "not_released",
        "0301_computer_mouse/child",
        "",
        None,
        True,
    ],
)
def test_category_loader_validates_id_before_path_join(tmp_path, category_id):
    source = make_valid_category_knowledge_source(tmp_path, TEST_CATEGORY_ID)
    shared = load_shared_evidence_documents(source)
    with pytest.raises(EvidenceValidationError, match="category_id"):
        load_category_evidence_documents(source, category_id, shared=shared)


def test_missing_and_non_directory_source_paths_fail_closed(tmp_path):
    with pytest.raises(EvidenceValidationError, match="source directory"):
        load_shared_evidence_documents(tmp_path / "missing")
    regular_file = tmp_path / "file"
    regular_file.write_text("not a directory", encoding="utf-8")
    with pytest.raises(EvidenceValidationError, match="source directory"):
        load_shared_evidence_documents(regular_file)


def test_shared_loader_is_green_before_category_authoring(tmp_path):
    source = make_valid_shared_knowledge_source(tmp_path)
    shared = load_shared_evidence_documents(source)
    assert tuple(shared.bundle.category_ids) == RELEASED_CATEGORY_IDS
    assert len(shared.sources) == 2
    assert len(shared.policies) == 2
    assert not (source / "categories").exists()


def test_single_category_loader_does_not_require_or_enumerate_siblings(tmp_path):
    source = make_valid_category_knowledge_source(tmp_path, TEST_CATEGORY_ID)
    unrelated = source / "categories/not_a_sibling_owned_by_this_gate"
    unrelated.mkdir()
    (unrelated / "hostile-symlink").symlink_to(source / "bundle.yaml")
    shared = load_shared_evidence_documents(source)
    category = load_category_evidence_documents(
        source, TEST_CATEGORY_ID, shared=shared
    )
    assert category.category.category_id == TEST_CATEGORY_ID
    with pytest.raises(EvidenceValidationError, match="category directory"):
        load_evidence_documents(source)


def test_shared_loader_ignores_optional_categories_and_legacy_v1_files(tmp_path):
    source = make_valid_shared_knowledge_source(tmp_path)
    (source / "categories").mkdir()
    (source / "categories/unexamined").symlink_to(source / "common")
    (source / "sources.yaml").write_text("not: opened\n", encoding="utf-8")
    (source / "device_components.yaml").write_text(
        "not: opened\n", encoding="utf-8"
    )
    shared = load_shared_evidence_documents(source)
    assert shared.bundle.bundle_version == "3.0.0"


def test_complete_loader_is_green_ordered_and_immutable(tmp_path):
    source = make_valid_knowledge_source(tmp_path)
    documents = load_evidence_documents(source)
    assert tuple(
        item.category.category_id for item in documents.categories
    ) == RELEASED_CATEGORY_IDS
    assert isinstance(documents.categories, tuple)
    assert isinstance(documents.shared.sources, tuple)
    first = documents.categories[0]
    assert isinstance(first.identities, tuple)
    assert isinstance(first.identities[0].aliases, tuple)
    assert first.sources[0].publication_or_revision_date == date(2026, 1, 1)
    assert first.identities[0].identity_kind is IdentityKind.FAMILY
    assert first.identities[0].model_id is None
    assert first.identities[1].identity_kind is IdentityKind.MODEL
    assert first.subtypes[0].market_state is MarketState.CURRENT
    assert (
        first.subtypes[0].battery_architecture
        is BatteryArchitecture.BATTERY_BEARING
    )
    assert first.specific_lifecycles[0].scope.kind is ScopeKind.MODEL
    assert (
        first.specific_lifecycles[0].endpoint_kind
        is LifecycleEndpointKind.TOTAL_LIFE
    )
    assert type(first.industry_averages[0].lower_bound) is float
    assert first.component_associations[0].status is AssociationStatus.LEGACY_SPECIFIC
    assert first.hazards[0].evidence_level is EvidenceLevel.D
    assert documents.shared.policies[0].outcome is RecommendationValue.REUSE
    with pytest.raises(FrozenInstanceError):
        first.category.display_name = "mutated"


def test_validation_error_exposes_filename_record_path_and_message(tmp_path):
    source = make_valid_shared_knowledge_source(tmp_path)
    mutate_yaml(
        source / "common/sources.yaml",
        lambda document: document["sources"][0].update({"trust_me": True}),
    )
    with pytest.raises(EvidenceValidationError) as caught:
        load_shared_evidence_documents(source)
    error = caught.value
    assert error.filename == "common/sources.yaml"
    assert error.record_path == "sources[0]"
    assert "trust_me" in error.message
    assert str(error).startswith("common/sources.yaml: sources[0]:")


def _set_root_field(root_key: str, field: str, value: object):
    def mutate(document: dict[str, object]) -> None:
        document[root_key][field] = value

    return mutate


@pytest.mark.parametrize(
    ("name", "relative_path", "root_key", "field"),
    [
        ("shared-sources", "common/sources.yaml", "sources", None),
        ("policies", "common/policies.yaml", "policies", None),
        ("bundle-categories", "bundle.yaml", "bundle", "category_ids"),
        ("identity-aliases", f"categories/{TEST_CATEGORY_ID}/identities.yaml", "identities", "aliases"),
        ("identity-tokens", f"categories/{TEST_CATEGORY_ID}/identities.yaml", "identities", "distinguishing_tokens"),
        ("subtype-sources", f"categories/{TEST_CATEGORY_ID}/identities.yaml", "subtypes", "source_ids"),
        ("variant-sources", f"categories/{TEST_CATEGORY_ID}/identities.yaml", "variants", "source_ids"),
        ("identity-sources", f"categories/{TEST_CATEGORY_ID}/identities.yaml", "identities", "source_ids"),
        ("specific-sources", f"categories/{TEST_CATEGORY_ID}/lifecycles.yaml", "lifecycles", "source_ids"),
        ("average-limitations", f"categories/{TEST_CATEGORY_ID}/industry_averages.yaml", "industry_averages", "limitations"),
        ("average-sources", f"categories/{TEST_CATEGORY_ID}/industry_averages.yaml", "industry_averages", "source_ids"),
        ("hazard-triggers", f"categories/{TEST_CATEGORY_ID}/hazards.yaml", "hazards", "trigger_observation_keys"),
        ("hazard-immediate", f"categories/{TEST_CATEGORY_ID}/hazards.yaml", "hazards", "immediate_actions"),
        ("hazard-follow-up", f"categories/{TEST_CATEGORY_ID}/hazards.yaml", "hazards", "follow_up_actions"),
        ("hazard-handling", f"categories/{TEST_CATEGORY_ID}/hazards.yaml", "hazards", "handling_guidance"),
        ("hazard-disposal", f"categories/{TEST_CATEGORY_ID}/hazards.yaml", "hazards", "disposal_guidance"),
        ("hazard-sources", f"categories/{TEST_CATEGORY_ID}/hazards.yaml", "hazards", "source_ids"),
    ],
)
def test_every_nonempty_list_contract_rejects_empty(
    tmp_path, name, relative_path, root_key, field
):
    source = _make_source_for_path(tmp_path, relative_path, name)

    def mutation(document: dict[str, object]) -> None:
        if field is None:
            document[root_key] = []
        elif root_key == "bundle":
            document[root_key][field] = []
        else:
            document[root_key][0][field] = []

    mutate_yaml(source / relative_path, mutation)
    with pytest.raises(EvidenceValidationError, match="non-empty"):
        _load_for_path(source, relative_path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schema_version", 2, "schema_version"),
        ("bundle_version", "3.0.1", "bundle_version"),
        ("identity_catalog_version", "1.0.1", "identity_catalog_version"),
        ("policy_revision", "2.0.1", "policy_revision"),
        ("category_ids", list(reversed(RELEASED_CATEGORY_IDS)), "category_ids"),
    ],
)
def test_bundle_release_identity_is_exact(tmp_path, field, value, message):
    source = make_valid_shared_knowledge_source(tmp_path)
    mutate_yaml(source / "bundle.yaml", _set_root_field("bundle", field, value))
    with pytest.raises(EvidenceValidationError, match=message):
        load_shared_evidence_documents(source)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("publication_or_revision_date", "2026-09-08", "publication"),
        ("reviewed_on", "2026-09-06", "review"),
    ],
)
def test_source_date_chronology_is_enforced(tmp_path, field, value, message):
    source = make_valid_shared_knowledge_source(tmp_path)
    mutate_yaml(
        source / "common/sources.yaml",
        lambda document: document["sources"][0].update({field: value}),
    )
    with pytest.raises(EvidenceValidationError, match=message):
        load_shared_evidence_documents(source)


@pytest.mark.parametrize(
    "url",
    [
        "HTTPs://example.invalid/source",
        "https://user@example.invalid/source",
        "https://example.invalid/source#fragment",
        "https://example.invalid/has space",
        "https:///missing-host",
    ],
)
def test_canonical_source_url_is_strict_https_and_round_tripping(tmp_path, url):
    source = make_valid_shared_knowledge_source(tmp_path)
    mutate_yaml(
        source / "common/sources.yaml",
        lambda document: document["sources"][0].update({"canonical_url": url}),
    )
    with pytest.raises(EvidenceValidationError, match="canonical HTTPS URL"):
        load_shared_evidence_documents(source)


def test_shared_source_ids_are_unique_and_sorted(tmp_path):
    duplicate = make_valid_shared_knowledge_source(tmp_path / "duplicate")
    mutate_yaml(
        duplicate / "common/sources.yaml",
        lambda document: document["sources"][1].update(
            {"source_id": document["sources"][0]["source_id"]}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="source_id.*unique"):
        load_shared_evidence_documents(duplicate)

    unsorted = make_valid_shared_knowledge_source(tmp_path / "unsorted")
    mutate_yaml(
        unsorted / "common/sources.yaml",
        lambda document: document["sources"].reverse(),
    )
    with pytest.raises(EvidenceValidationError, match="sources.*sorted"):
        load_shared_evidence_documents(unsorted)


def test_policy_revision_priority_and_record_order_are_closed(tmp_path):
    revision = make_valid_shared_knowledge_source(tmp_path / "revision")
    mutate_yaml(
        revision / "common/policies.yaml",
        lambda document: document.update({"policy_revision": "2.0.1"}),
    )
    with pytest.raises(EvidenceValidationError, match="policy revision"):
        load_shared_evidence_documents(revision)

    negative = make_valid_shared_knowledge_source(tmp_path / "negative")
    mutate_yaml(
        negative / "common/policies.yaml",
        lambda document: document["policies"][0].update({"priority": -1}),
    )
    with pytest.raises(EvidenceValidationError, match="priority.*non-negative"):
        load_shared_evidence_documents(negative)

    duplicate = make_valid_shared_knowledge_source(tmp_path / "duplicate")
    mutate_yaml(
        duplicate / "common/policies.yaml",
        lambda document: document["policies"][1].update({"priority": 0}),
    )
    with pytest.raises(EvidenceValidationError, match="priority.*unique"):
        load_shared_evidence_documents(duplicate)

    unsorted = make_valid_shared_knowledge_source(tmp_path / "unsorted")
    mutate_yaml(
        unsorted / "common/policies.yaml",
        lambda document: document["policies"].reverse(),
    )
    with pytest.raises(EvidenceValidationError, match="policies.*sorted"):
        load_shared_evidence_documents(unsorted)


@pytest.mark.parametrize(
    ("name", "when_all", "when_any", "message"),
    [
        (
            "unknown",
            ["arbitrary.expression=true"],
            [],
            "policy predicate",
        ),
        (
            "duplicate",
            ["identity.state=canonical", "identity.state=canonical"],
            [],
            "duplicate",
        ),
        (
            "overlap",
            ["identity.state=canonical"],
            ["identity.state=canonical"],
            "both predicate groups",
        ),
        (
            "mutually-exclusive",
            ["identity.state=canonical", "identity.state=unknown"],
            [],
            "mutually exclusive",
        ),
        (
            "unsorted",
            [
                "observations.age_months=present",
                "identity.state=canonical",
            ],
            [],
            "predicates.*sorted",
        ),
    ],
)
def test_policy_predicate_vocabulary_and_group_semantics(
    tmp_path, name, when_all, when_any, message
):
    source = make_valid_shared_knowledge_source(tmp_path / name)
    mutate_yaml(
        source / "common/policies.yaml",
        lambda document: document["policies"][0].update(
            {"when_all": when_all, "when_any": when_any}
        ),
    )
    with pytest.raises(EvidenceValidationError, match=message):
        load_shared_evidence_documents(source)


def test_policy_may_reference_shared_sources_only(tmp_path):
    source = make_valid_shared_knowledge_source(tmp_path)
    mutate_yaml(
        source / "common/policies.yaml",
        lambda document: document["policies"][0].update(
            {"source_ids": [f"{TEST_CATEGORY_ID}_claim_source"]}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="source reference"):
        load_shared_evidence_documents(source)


def _load_mouse_category(source: Path):
    shared = load_shared_evidence_documents(source)
    return load_category_evidence_documents(
        source, TEST_CATEGORY_ID, shared=shared
    )


def test_category_source_ids_are_unique_sorted_and_disjoint_from_shared(tmp_path):
    duplicate = make_valid_category_knowledge_source(
        tmp_path / "duplicate", TEST_CATEGORY_ID
    )
    mutate_yaml(
        duplicate / f"categories/{TEST_CATEGORY_ID}/sources.yaml",
        lambda document: document["sources"][1].update(
            {"source_id": document["sources"][0]["source_id"]}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="source_id.*unique"):
        _load_mouse_category(duplicate)

    shared_collision = make_valid_category_knowledge_source(
        tmp_path / "shared-collision", TEST_CATEGORY_ID
    )
    mutate_yaml(
        shared_collision / f"categories/{TEST_CATEGORY_ID}/sources.yaml",
        lambda document: document["sources"][1].update(
            {"source_id": "shared_policy_source"}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="source_id.*globally unique"):
        _load_mouse_category(shared_collision)

    unsorted = make_valid_category_knowledge_source(
        tmp_path / "unsorted", TEST_CATEGORY_ID
    )
    mutate_yaml(
        unsorted / f"categories/{TEST_CATEGORY_ID}/sources.yaml",
        lambda document: document["sources"].reverse(),
    )
    with pytest.raises(EvidenceValidationError, match="sources.*sorted"):
        _load_mouse_category(unsorted)


@pytest.mark.parametrize(
    ("root_key", "record_index"),
    [
        ("subtypes", 0),
        ("variants", 0),
        ("identities", 0),
    ],
)
def test_every_authored_identity_category_id_matches_directory(
    tmp_path, root_key, record_index
):
    source = make_valid_category_knowledge_source(tmp_path, TEST_CATEGORY_ID)
    path = source / f"categories/{TEST_CATEGORY_ID}/identities.yaml"
    mutate_yaml(
        path,
        lambda document: document[root_key][record_index].update(
            {"category_id": "0301_keyboard"}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="category_id.*directory"):
        _load_mouse_category(source)


def test_category_mapping_id_matches_directory(tmp_path):
    source = make_valid_category_knowledge_source(tmp_path, TEST_CATEGORY_ID)
    mutate_yaml(
        source / f"categories/{TEST_CATEGORY_ID}/identities.yaml",
        _set_root_field("category", "category_id", "0301_keyboard"),
    )
    with pytest.raises(EvidenceValidationError, match="category.*directory"):
        _load_mouse_category(source)


def test_unknown_category_id_matches_directory(tmp_path):
    source = make_valid_category_knowledge_source(tmp_path, TEST_CATEGORY_ID)
    mutate_yaml(
        source / f"categories/{TEST_CATEGORY_ID}/coverage.yaml",
        lambda document: document["unknowns"][0].update(
            {"category_id": "0301_keyboard"}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="category_id.*directory"):
        _load_mouse_category(source)


def test_variant_must_reference_its_category_subtype(tmp_path):
    source = make_valid_category_knowledge_source(tmp_path, TEST_CATEGORY_ID)
    mutate_yaml(
        source / f"categories/{TEST_CATEGORY_ID}/identities.yaml",
        lambda document: document["variants"][0].update(
            {"subtype_id": "missing_subtype"}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="subtype reference"):
        _load_mouse_category(source)


def test_identity_must_reference_subtype_and_only_its_variants(tmp_path):
    missing_subtype = make_valid_category_knowledge_source(
        tmp_path / "missing-subtype", TEST_CATEGORY_ID
    )
    mutate_yaml(
        missing_subtype / f"categories/{TEST_CATEGORY_ID}/identities.yaml",
        lambda document: document["identities"][0].update(
            {"subtype_id": "missing_subtype"}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="subtype reference"):
        _load_mouse_category(missing_subtype)

    wrong_variant = make_valid_category_knowledge_source(
        tmp_path / "wrong-variant", TEST_CATEGORY_ID
    )
    mutate_yaml(
        wrong_variant / f"categories/{TEST_CATEGORY_ID}/identities.yaml",
        lambda document: document["identities"][0].update(
            {"variant_ids": [f"{TEST_CATEGORY_ID}_variant_1a"]}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="variant.*subtype"):
        _load_mouse_category(wrong_variant)


def test_battery_architecture_agrees_across_subtype_variant_and_identity(tmp_path):
    wrong_variant = make_valid_category_knowledge_source(
        tmp_path / "variant", TEST_CATEGORY_ID
    )
    mutate_yaml(
        wrong_variant / f"categories/{TEST_CATEGORY_ID}/identities.yaml",
        lambda document: document["variants"][0].update(
            {"battery_architecture": "battery_free"}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="battery architecture"):
        _load_mouse_category(wrong_variant)

    wrong_identity = make_valid_category_knowledge_source(
        tmp_path / "identity", TEST_CATEGORY_ID
    )
    mutate_yaml(
        wrong_identity / f"categories/{TEST_CATEGORY_ID}/identities.yaml",
        lambda document: document["identities"][0].update(
            {"battery_architecture": "battery_free"}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="battery architecture"):
        _load_mouse_category(wrong_identity)


def test_family_and_model_identity_shapes_are_conditional(tmp_path):
    broken_family = make_valid_category_knowledge_source(
        tmp_path / "family", TEST_CATEGORY_ID
    )
    mutate_yaml(
        broken_family / f"categories/{TEST_CATEGORY_ID}/identities.yaml",
        lambda document: document["identities"][0].update(
            {"family_id": f"{TEST_CATEGORY_ID}_wrong_family"}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="family identity"):
        _load_mouse_category(broken_family)

    family_with_model = make_valid_category_knowledge_source(
        tmp_path / "family-model", TEST_CATEGORY_ID
    )
    mutate_yaml(
        family_with_model / f"categories/{TEST_CATEGORY_ID}/identities.yaml",
        lambda document: document["identities"][0].update(
            {"model_id": f"{TEST_CATEGORY_ID}_invented", "model_name": "Invented"}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="family identity"):
        _load_mouse_category(family_with_model)

    broken_model = make_valid_category_knowledge_source(
        tmp_path / "model", TEST_CATEGORY_ID
    )
    mutate_yaml(
        broken_model / f"categories/{TEST_CATEGORY_ID}/identities.yaml",
        lambda document: document["identities"][1].update(
            {"model_id": f"{TEST_CATEGORY_ID}_different_model"}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="model identity"):
        _load_mouse_category(broken_model)

    model_without_name = make_valid_category_knowledge_source(
        tmp_path / "model-name", TEST_CATEGORY_ID
    )
    mutate_yaml(
        model_without_name / f"categories/{TEST_CATEGORY_ID}/identities.yaml",
        lambda document: document["identities"][1].update({"model_name": None}),
    )
    with pytest.raises(EvidenceValidationError, match="model identity"):
        _load_mouse_category(model_without_name)


def test_identity_alias_namespace_and_token_normalization_are_collision_safe(tmp_path):
    aliases = make_valid_category_knowledge_source(
        tmp_path / "aliases", TEST_CATEGORY_ID
    )

    def collide_alias(document: dict[str, object]) -> None:
        second_name = document["identities"][1]["display_name"]
        document["identities"][0]["aliases"] = [second_name.upper()]

    mutate_yaml(
        aliases / f"categories/{TEST_CATEGORY_ID}/identities.yaml", collide_alias
    )
    with pytest.raises(EvidenceValidationError, match="identity alias.*unique"):
        _load_mouse_category(aliases)

    tokens = make_valid_category_knowledge_source(
        tmp_path / "tokens", TEST_CATEGORY_ID
    )
    mutate_yaml(
        tokens / f"categories/{TEST_CATEGORY_ID}/identities.yaml",
        lambda document: document["identities"][0].update(
            {"distinguishing_tokens": ["Token\u2003Value", "token value"]}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="distinguishing token.*unique"):
        _load_mouse_category(tokens)


def test_manufacturer_and_family_ancestry_names_stay_consistent(tmp_path):
    manufacturer = make_valid_category_knowledge_source(
        tmp_path / "manufacturer", TEST_CATEGORY_ID
    )
    mutate_yaml(
        manufacturer / f"categories/{TEST_CATEGORY_ID}/identities.yaml",
        lambda document: document["identities"][1].update(
            {"manufacturer_name": "Conflicting Manufacturer"}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="manufacturer.*consistent"):
        _load_mouse_category(manufacturer)

    family_name = make_valid_category_knowledge_source(
        tmp_path / "family-name", TEST_CATEGORY_ID
    )
    mutate_yaml(
        family_name / f"categories/{TEST_CATEGORY_ID}/identities.yaml",
        lambda document: document["identities"][1].update(
            {"family_name": "Conflicting Family"}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="family.*consistent"):
        _load_mouse_category(family_name)

    family_scope = make_valid_category_knowledge_source(
        tmp_path / "family-scope", TEST_CATEGORY_ID
    )

    def move_family_member(document: dict[str, object]) -> None:
        record = document["identities"][1]
        record.update(
            {
                "subtype_id": f"{TEST_CATEGORY_ID}_subtype_1",
                "variant_ids": [
                    f"{TEST_CATEGORY_ID}_variant_1a",
                    f"{TEST_CATEGORY_ID}_variant_1b",
                ],
                "battery_architecture": "battery_free",
            }
        )

    mutate_yaml(
        family_scope / f"categories/{TEST_CATEGORY_ID}/identities.yaml",
        move_family_member,
    )
    with pytest.raises(EvidenceValidationError, match="family.*ancestry"):
        _load_mouse_category(family_scope)


@pytest.mark.parametrize(
    ("field_from", "field_to", "from_value", "to_value", "message"),
    [
        ("model_year_from", "model_year_to", 2025, 2024, "model year range"),
        (
            "applicable_from",
            "applicable_to",
            "2025-01-01",
            "2024-01-01",
            "applicability date range",
        ),
    ],
)
def test_identity_ranges_allow_open_ends_but_reject_reversal(
    tmp_path, field_from, field_to, from_value, to_value, message
):
    source = make_valid_category_knowledge_source(tmp_path, TEST_CATEGORY_ID)
    path = source / f"categories/{TEST_CATEGORY_ID}/identities.yaml"
    mutate_yaml(
        path,
        lambda document: document["identities"][1].update(
            {field_from: from_value, field_to: to_value}
        ),
    )
    with pytest.raises(EvidenceValidationError, match=message):
        _load_mouse_category(source)

    open_source = make_valid_category_knowledge_source(
        tmp_path / "open", TEST_CATEGORY_ID
    )
    mutate_yaml(
        open_source / f"categories/{TEST_CATEGORY_ID}/identities.yaml",
        lambda document: document["identities"][1].update(
            {field_from: None, field_to: to_value}
        ),
    )
    assert _load_mouse_category(open_source).identities[1]


def test_grade_d_cannot_support_lifecycle(tmp_path):
    source = make_valid_category_knowledge_source(tmp_path, TEST_CATEGORY_ID)
    path = source / f"categories/{TEST_CATEGORY_ID}/lifecycles.yaml"
    mutate_yaml(
        path,
        lambda document: document["lifecycles"][0].update(
            {"evidence_level": "D"}
        ),
    )
    with pytest.raises(
        EvidenceValidationError, match="grade D cannot support lifecycle"
    ):
        _load_mouse_category(source)


@pytest.mark.parametrize(
    ("record_index", "endpoint", "endpoint_kind", "message"),
    [
        (0, "service_life", "capacity_threshold", "service_life.*total_life"),
        (
            1,
            "capacity_threshold",
            "operating_endurance",
            "capacity_threshold.*capacity_threshold",
        ),
        (2, "charge_runtime", "total_life", "operating_endurance"),
    ],
)
def test_endpoint_label_and_endpoint_kind_stay_separate(
    tmp_path, record_index, endpoint, endpoint_kind, message
):
    source = make_valid_category_knowledge_source(tmp_path, TEST_CATEGORY_ID)
    path = source / f"categories/{TEST_CATEGORY_ID}/lifecycles.yaml"
    mutate_yaml(
        path,
        lambda document: document["lifecycles"][record_index].update(
            {"endpoint": endpoint, "endpoint_kind": endpoint_kind}
        ),
    )
    with pytest.raises(EvidenceValidationError, match=message):
        _load_mouse_category(source)


@pytest.mark.parametrize(
    ("relative_name", "root_key"),
    [
        ("lifecycles.yaml", "lifecycles"),
        ("industry_averages.yaml", "industry_averages"),
    ],
)
@pytest.mark.parametrize(
    ("case_name", "lower_bound", "upper_bound", "message"),
    [
        ("zero", 0.0, 1.0, "positive"),
        ("negative", -1.0, 1.0, "positive"),
        ("reversed", 2.0, 1.0, "bounds"),
    ],
)
def test_both_lifecycle_record_types_reject_invalid_bounds(
    tmp_path,
    relative_name,
    root_key,
    case_name,
    lower_bound,
    upper_bound,
    message,
):
    source = make_valid_category_knowledge_source(
        tmp_path / f"{root_key}-{case_name}", TEST_CATEGORY_ID
    )
    path = source / f"categories/{TEST_CATEGORY_ID}/{relative_name}"
    mutate_yaml(
        path,
        lambda document: document[root_key][0].update(
            {"lower_bound": lower_bound, "upper_bound": upper_bound}
        ),
    )
    with pytest.raises(EvidenceValidationError, match=message):
        _load_mouse_category(source)


def test_lifecycle_numeric_overflow_is_a_location_bearing_validation_error(tmp_path):
    source = make_valid_category_knowledge_source(tmp_path, TEST_CATEGORY_ID)
    mutate_yaml(
        source / f"categories/{TEST_CATEGORY_ID}/lifecycles.yaml",
        lambda document: document["lifecycles"][0].update(
            {"lower_bound": 10**400}
        ),
    )

    with pytest.raises(EvidenceValidationError) as caught:
        _load_mouse_category(source)
    assert caught.value.filename.endswith("/lifecycles.yaml")
    assert caught.value.record_path == "lifecycles[0].lower_bound"
    assert "finite" in caught.value.message


def test_yaml_integer_digit_limit_is_a_location_bearing_validation_error(tmp_path):
    source = make_valid_category_knowledge_source(tmp_path, TEST_CATEGORY_ID)
    path = source / f"categories/{TEST_CATEGORY_ID}/lifecycles.yaml"
    original = b"  lower_bound: 4.0\n"
    replacement = b"  lower_bound: " + (b"9" * 5_000) + b"\n"
    raw = path.read_bytes()
    assert raw.count(original) == 1
    path.write_bytes(raw.replace(original, replacement))

    with pytest.raises(EvidenceValidationError) as caught:
        _load_mouse_category(source)
    assert caught.value.filename == f"categories/{TEST_CATEGORY_ID}/lifecycles.yaml"
    assert caught.value.record_path == "document root"
    assert "invalid YAML scalar" in caught.value.message
    assert "line 11, column 16" in caught.value.message


def test_normal_yaml_integer_scalar_remains_a_valid_number(tmp_path):
    source = make_valid_category_knowledge_source(tmp_path, TEST_CATEGORY_ID)
    mutate_yaml(
        source / f"categories/{TEST_CATEGORY_ID}/lifecycles.yaml",
        lambda document: document["lifecycles"][0].update({"lower_bound": 5}),
    )

    category = _load_mouse_category(source)
    assert category.specific_lifecycles[0].lower_bound == 5.0


def test_yaml_scalar_guard_does_not_mask_programmer_exceptions(
    tmp_path, monkeypatch
):
    source = make_valid_category_knowledge_source(tmp_path, TEST_CATEGORY_ID)
    mutate_yaml(
        source / f"categories/{TEST_CATEGORY_ID}/lifecycles.yaml",
        lambda document: document["lifecycles"][0].update({"lower_bound": 5001}),
    )
    integer_tag = "tag:yaml.org,2002:int"
    original = knowledge_schema._ClosedLoader.yaml_constructors[integer_tag]

    def raise_programmer_error(loader, node):
        if node.value == "5001":
            raise RuntimeError("synthetic constructor bug")
        return original(loader, node)

    monkeypatch.setitem(
        knowledge_schema._ClosedLoader.yaml_constructors,
        integer_tag,
        raise_programmer_error,
    )
    with pytest.raises(RuntimeError, match="synthetic constructor bug"):
        _load_mouse_category(source)


def test_specific_lifecycle_may_preserve_positive_sourced_point_records(tmp_path):
    source = make_valid_category_knowledge_source(tmp_path, TEST_CATEGORY_ID)
    path = source / f"categories/{TEST_CATEGORY_ID}/lifecycles.yaml"
    mutate_yaml(
        path,
        lambda document: document["lifecycles"][0].update(
            {"lower_bound": 800.0, "upper_bound": 800.0}
        ),
    )
    record = _load_mouse_category(source).specific_lifecycles[0]
    assert record.lower_bound == record.upper_bound == 800.0


def test_industry_average_requires_a_positive_proper_interval(tmp_path):
    source = make_valid_category_knowledge_source(tmp_path, TEST_CATEGORY_ID)
    path = source / f"categories/{TEST_CATEGORY_ID}/industry_averages.yaml"
    mutate_yaml(
        path,
        lambda document: document["industry_averages"][0].update(
            {"lower_bound": 4.0, "upper_bound": 4.0}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="proper interval"):
        _load_mouse_category(source)

    valid = make_valid_category_knowledge_source(
        tmp_path / "proper", TEST_CATEGORY_ID
    )
    average = _load_mouse_category(valid).industry_averages[0]
    assert (average.lower_bound, average.upper_bound) == (3.0, 7.0)
    assert average.population_definition
    assert average.publication_period
    assert average.methodology
    assert average.uncertainty
    assert average.limitations


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model_year_from", 2020),
        ("model_year_to", 2025),
        ("applicable_from", "2020-01-01"),
        ("applicable_to", "2025-01-01"),
        ("required_variant_ids", [f"{TEST_CATEGORY_ID}_variant_0a"]),
        ("excluded_variant_ids", [f"{TEST_CATEGORY_ID}_variant_0a"]),
    ],
)
def test_industry_average_must_be_unconstrained(tmp_path, field, value):
    source = make_valid_category_knowledge_source(tmp_path, TEST_CATEGORY_ID)
    path = source / f"categories/{TEST_CATEGORY_ID}/industry_averages.yaml"
    mutate_yaml(
        path,
        lambda document: document["industry_averages"][0].update({field: value}),
    )
    with pytest.raises(
        EvidenceValidationError, match="industry average.*unconstrained"
    ):
        _load_mouse_category(source)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("scope", {"kind": "subtype", "id": f"{TEST_CATEGORY_ID}_subtype_0"}, "category scope"),
        ("subject", "battery", "subject.*device"),
        ("endpoint", "capacity_threshold", "endpoint.*service_life"),
        ("endpoint_kind", "operating_endurance", "endpoint kind.*total_life"),
        ("metric", "full_charge_cycles", "metric.*elapsed_time"),
        ("unit", "cycles", "unit.*years"),
        ("evidence_level", "B", "evidence level.*C"),
        ("precedence", -1, "precedence.*non-negative"),
    ],
)
def test_industry_average_closed_category_service_life_contract(
    tmp_path, field, value, message
):
    source = make_valid_category_knowledge_source(tmp_path, TEST_CATEGORY_ID)
    path = source / f"categories/{TEST_CATEGORY_ID}/industry_averages.yaml"
    mutate_yaml(
        path,
        lambda document: document["industry_averages"][0].update({field: value}),
    )
    with pytest.raises(EvidenceValidationError, match=message):
        _load_mouse_category(source)


def test_specific_lifecycle_scope_and_evidence_are_derived_from_hierarchy(tmp_path):
    category_scope = make_valid_category_knowledge_source(
        tmp_path / "category", TEST_CATEGORY_ID
    )
    mutate_yaml(
        category_scope / f"categories/{TEST_CATEGORY_ID}/lifecycles.yaml",
        lambda document: document["lifecycles"][0].update(
            {"scope": {"kind": "category", "id": TEST_CATEGORY_ID}}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="specific lifecycle.*scope"):
        _load_mouse_category(category_scope)

    wrong_model_level = make_valid_category_knowledge_source(
        tmp_path / "model-level", TEST_CATEGORY_ID
    )
    mutate_yaml(
        wrong_model_level / f"categories/{TEST_CATEGORY_ID}/lifecycles.yaml",
        lambda document: document["lifecycles"][0].update(
            {"evidence_level": "B"}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="evidence level.*A"):
        _load_mouse_category(wrong_model_level)

    wrong_family_level = make_valid_category_knowledge_source(
        tmp_path / "family-level", TEST_CATEGORY_ID
    )
    mutate_yaml(
        wrong_family_level / f"categories/{TEST_CATEGORY_ID}/lifecycles.yaml",
        lambda document: document["lifecycles"][1].update(
            {"evidence_level": "A"}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="evidence level.*B"):
        _load_mouse_category(wrong_family_level)


def test_model_scope_must_match_canonical_hierarchy(tmp_path):
    source = make_valid_category_knowledge_source(tmp_path, TEST_CATEGORY_ID)
    path = source / f"categories/{TEST_CATEGORY_ID}/lifecycles.yaml"
    mutate_yaml(
        path,
        lambda document: document["lifecycles"][0]["scope"].update(
            {"id": "0303_laptop_model_01"}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="scope hierarchy"):
        _load_mouse_category(source)


@pytest.mark.parametrize(
    ("field_from", "field_to", "from_value", "to_value", "message"),
    [
        ("model_year_from", "model_year_to", 2030, 2020, "model year range"),
        (
            "applicable_from",
            "applicable_to",
            "2030-01-01",
            "2020-01-01",
            "applicability date range",
        ),
    ],
)
def test_specific_lifecycle_date_and_year_ranges_reject_reversal(
    tmp_path, field_from, field_to, from_value, to_value, message
):
    source = make_valid_category_knowledge_source(tmp_path, TEST_CATEGORY_ID)
    mutate_yaml(
        source / f"categories/{TEST_CATEGORY_ID}/lifecycles.yaml",
        lambda document: document["lifecycles"][0].update(
            {field_from: from_value, field_to: to_value}
        ),
    )
    with pytest.raises(EvidenceValidationError, match=message):
        _load_mouse_category(source)


def test_lifecycle_variant_filters_are_disjoint_and_scope_owned(tmp_path):
    overlap = make_valid_category_knowledge_source(
        tmp_path / "overlap", TEST_CATEGORY_ID
    )
    mutate_yaml(
        overlap / f"categories/{TEST_CATEGORY_ID}/lifecycles.yaml",
        lambda document: document["lifecycles"][0].update(
            {
                "required_variant_ids": [f"{TEST_CATEGORY_ID}_variant_0a"],
                "excluded_variant_ids": [f"{TEST_CATEGORY_ID}_variant_0a"],
            }
        ),
    )
    with pytest.raises(EvidenceValidationError, match="variant filters.*disjoint"):
        _load_mouse_category(overlap)

    wrong_subtype = make_valid_category_knowledge_source(
        tmp_path / "wrong-subtype", TEST_CATEGORY_ID
    )
    mutate_yaml(
        wrong_subtype / f"categories/{TEST_CATEGORY_ID}/lifecycles.yaml",
        lambda document: document["lifecycles"][0].update(
            {"required_variant_ids": [f"{TEST_CATEGORY_ID}_variant_1a"]}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="variant.*scoped subtype"):
        _load_mouse_category(wrong_subtype)


@pytest.mark.parametrize(
    ("lifecycle_index", "identity_indexes", "owned_variant", "sibling_variant"),
    [
        (
            0,
            (1,),
            f"{TEST_CATEGORY_ID}_variant_0a",
            f"{TEST_CATEGORY_ID}_variant_0b",
        ),
        (
            1,
            (2, 3),
            f"{TEST_CATEGORY_ID}_variant_1a",
            f"{TEST_CATEGORY_ID}_variant_1b",
        ),
    ],
    ids=("model", "family"),
)
@pytest.mark.parametrize(
    "filter_field", ("required_variant_ids", "excluded_variant_ids")
)
def test_specific_lifecycle_variant_filters_reject_same_subtype_sibling_variants(
    tmp_path,
    lifecycle_index,
    identity_indexes,
    owned_variant,
    sibling_variant,
    filter_field,
):
    source = make_valid_category_knowledge_source(tmp_path, TEST_CATEGORY_ID)
    identities_path = source / f"categories/{TEST_CATEGORY_ID}/identities.yaml"
    lifecycle_path = source / f"categories/{TEST_CATEGORY_ID}/lifecycles.yaml"

    def narrow_identity_variants(document: dict[str, object]) -> None:
        for index in identity_indexes:
            document["identities"][index]["variant_ids"] = [owned_variant]

    mutate_yaml(identities_path, narrow_identity_variants)
    mutate_yaml(
        lifecycle_path,
        lambda document: document["lifecycles"][lifecycle_index].update(
            {filter_field: [sibling_variant]}
        ),
    )

    with pytest.raises(
        EvidenceValidationError,
        match="variant filter.*declared.*(model|family)",
    ):
        _load_mouse_category(source)


@pytest.mark.parametrize(
    ("lifecycle_index", "identity_indexes", "owned_variant"),
    [
        (0, (1,), f"{TEST_CATEGORY_ID}_variant_0a"),
        (1, (2,), f"{TEST_CATEGORY_ID}_variant_1a"),
    ],
    ids=("model", "family"),
)
@pytest.mark.parametrize(
    "filter_field", ("required_variant_ids", "excluded_variant_ids")
)
def test_specific_lifecycle_variant_filters_accept_variants_declared_by_scope(
    tmp_path,
    lifecycle_index,
    identity_indexes,
    owned_variant,
    filter_field,
):
    source = make_valid_category_knowledge_source(tmp_path, TEST_CATEGORY_ID)
    identities_path = source / f"categories/{TEST_CATEGORY_ID}/identities.yaml"
    lifecycle_path = source / f"categories/{TEST_CATEGORY_ID}/lifecycles.yaml"

    def narrow_identity_variants(document: dict[str, object]) -> None:
        if lifecycle_index == 1:
            for index in (2, 3):
                document["identities"][index]["variant_ids"] = []
        for index in identity_indexes:
            document["identities"][index]["variant_ids"] = [owned_variant]

    mutate_yaml(identities_path, narrow_identity_variants)

    filters = {
        "required_variant_ids": [],
        "excluded_variant_ids": [],
    }
    filters[filter_field] = [owned_variant]
    mutate_yaml(
        lifecycle_path,
        lambda document: document["lifecycles"][lifecycle_index].update(filters),
    )

    category = _load_mouse_category(source)
    lifecycle = category.specific_lifecycles[lifecycle_index]
    assert getattr(lifecycle, filter_field) == (owned_variant,)


@pytest.mark.parametrize("root_key", ["lifecycles", "industry_averages"])
def test_lifecycle_precedence_is_nonnegative(tmp_path, root_key):
    source = make_valid_category_knowledge_source(tmp_path, TEST_CATEGORY_ID)
    filename = (
        "lifecycles.yaml" if root_key == "lifecycles" else "industry_averages.yaml"
    )
    mutate_yaml(
        source / f"categories/{TEST_CATEGORY_ID}/{filename}",
        lambda document: document[root_key][0].update({"precedence": -1}),
    )
    with pytest.raises(EvidenceValidationError, match="precedence.*non-negative"):
        _load_mouse_category(source)


def test_component_templates_have_one_canonical_standard(tmp_path):
    no_standard = make_valid_category_knowledge_source(
        tmp_path / "none", TEST_CATEGORY_ID
    )
    mutate_yaml(
        no_standard / f"categories/{TEST_CATEGORY_ID}/components.yaml",
        lambda document: document["templates"][2].update(
            {"template_kind": "modern_overlay"}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="exactly one standard"):
        _load_mouse_category(no_standard)

    two_standard = make_valid_category_knowledge_source(
        tmp_path / "two", TEST_CATEGORY_ID
    )
    mutate_yaml(
        two_standard / f"categories/{TEST_CATEGORY_ID}/components.yaml",
        lambda document: document["templates"][0].update(
            {
                "template_kind": "standard",
                "scope": {"kind": "category", "id": TEST_CATEGORY_ID},
            }
        ),
    )
    with pytest.raises(EvidenceValidationError, match="exactly one standard"):
        _load_mouse_category(two_standard)


@pytest.mark.parametrize(
    ("template_index", "updates", "message"),
    [
        (
            2,
            {"scope": {"kind": "subtype", "id": f"{TEST_CATEGORY_ID}_subtype_1"}},
            "standard.*category scope",
        ),
        (2, {"application_order": 1}, "standard.*application_order=0"),
        (
            1,
            {"scope": {"kind": "category", "id": TEST_CATEGORY_ID}},
            "overlay.*category scope",
        ),
        (1, {"application_order": -1}, "application_order.*non-negative"),
    ],
)
def test_component_template_scope_and_order_rules(
    tmp_path, template_index, updates, message
):
    source = make_valid_category_knowledge_source(tmp_path, TEST_CATEGORY_ID)
    mutate_yaml(
        source / f"categories/{TEST_CATEGORY_ID}/components.yaml",
        lambda document: document["templates"][template_index].update(updates),
    )
    with pytest.raises(EvidenceValidationError, match=message):
        _load_mouse_category(source)


def test_template_application_order_is_unique_within_scope(tmp_path):
    source = make_valid_category_knowledge_source(tmp_path, TEST_CATEGORY_ID)

    def duplicate_scope_order(document: dict[str, object]) -> None:
        document["templates"][0]["scope"] = dict(document["templates"][1]["scope"])

    mutate_yaml(
        source / f"categories/{TEST_CATEGORY_ID}/components.yaml",
        duplicate_scope_order,
    )
    with pytest.raises(
        EvidenceValidationError, match="application_order.*unique.*scope"
    ):
        _load_mouse_category(source)


def test_association_positions_are_contiguous_per_template(tmp_path):
    source = make_valid_category_knowledge_source(tmp_path, TEST_CATEGORY_ID)
    mutate_yaml(
        source / f"categories/{TEST_CATEGORY_ID}/components.yaml",
        lambda document: document["associations"][2].update({"position": 2}),
    )
    with pytest.raises(EvidenceValidationError, match="positions.*contiguous"):
        _load_mouse_category(source)


def test_authored_association_status_restrictions_are_enforced(tmp_path):
    user_confirmed = make_valid_category_knowledge_source(
        tmp_path / "user", TEST_CATEGORY_ID
    )
    mutate_yaml(
        user_confirmed / f"categories/{TEST_CATEGORY_ID}/components.yaml",
        lambda document: document["associations"][0].update(
            {"status": "user_confirmed"}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="user_confirmed"):
        _load_mouse_category(user_confirmed)

    exact_on_subtype = make_valid_category_knowledge_source(
        tmp_path / "exact", TEST_CATEGORY_ID
    )
    mutate_yaml(
        exact_on_subtype / f"categories/{TEST_CATEGORY_ID}/components.yaml",
        lambda document: document["associations"][1].update(
            {"status": "exact_model_confirmed"}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="exact_model_confirmed.*model"):
        _load_mouse_category(exact_on_subtype)

    legacy_on_modern = make_valid_category_knowledge_source(
        tmp_path / "legacy", TEST_CATEGORY_ID
    )
    mutate_yaml(
        legacy_on_modern / f"categories/{TEST_CATEGORY_ID}/components.yaml",
        lambda document: document["associations"][1].update(
            {"status": "legacy_specific"}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="legacy_specific.*legacy_overlay"):
        _load_mouse_category(legacy_on_modern)


def test_reviewed_and_unknown_association_provenance_shapes_are_distinct(tmp_path):
    null_reviewed = make_valid_category_knowledge_source(
        tmp_path / "null-reviewed", TEST_CATEGORY_ID
    )
    mutate_yaml(
        null_reviewed / f"categories/{TEST_CATEGORY_ID}/components.yaml",
        lambda document: document["associations"][0].update(
            {"evidence_level": None}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="reviewed association.*evidence"):
        _load_mouse_category(null_reviewed)

    no_reviewed_sources = make_valid_category_knowledge_source(
        tmp_path / "no-reviewed-source", TEST_CATEGORY_ID
    )
    mutate_yaml(
        no_reviewed_sources / f"categories/{TEST_CATEGORY_ID}/components.yaml",
        lambda document: document["associations"][0].update({"source_ids": []}),
    )
    with pytest.raises(EvidenceValidationError, match="reviewed association.*source"):
        _load_mouse_category(no_reviewed_sources)

    evidence_on_unknown = make_valid_category_knowledge_source(
        tmp_path / "unknown-evidence", TEST_CATEGORY_ID
    )
    mutate_yaml(
        evidence_on_unknown / f"categories/{TEST_CATEGORY_ID}/components.yaml",
        lambda document: document["associations"][2].update(
            {"evidence_level": "B"}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="unknown association.*null"):
        _load_mouse_category(evidence_on_unknown)

    source_on_unknown = make_valid_category_knowledge_source(
        tmp_path / "unknown-source", TEST_CATEGORY_ID
    )
    mutate_yaml(
        source_on_unknown / f"categories/{TEST_CATEGORY_ID}/components.yaml",
        lambda document: document["associations"][2].update(
            {"source_ids": [f"{TEST_CATEGORY_ID}_claim_source"]}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="unknown association.*source_ids"):
        _load_mouse_category(source_on_unknown)


@pytest.mark.parametrize(
    ("association_index", "level", "message"),
    [
        (0, "C", "evidence level.*B"),
        (1, "A", "evidence level.*B"),
        (3, "B", "evidence level.*C"),
    ],
)
def test_association_evidence_level_follows_template_scope(
    tmp_path, association_index, level, message
):
    source = make_valid_category_knowledge_source(tmp_path, TEST_CATEGORY_ID)
    mutate_yaml(
        source / f"categories/{TEST_CATEGORY_ID}/components.yaml",
        lambda document: document["associations"][association_index].update(
            {"evidence_level": level}
        ),
    )
    with pytest.raises(EvidenceValidationError, match=message):
        _load_mouse_category(source)


def test_unknown_association_has_exactly_one_matching_unknown_row(tmp_path):
    missing = make_valid_category_knowledge_source(
        tmp_path / "missing", TEST_CATEGORY_ID
    )
    mutate_yaml(
        missing / f"categories/{TEST_CATEGORY_ID}/coverage.yaml",
        lambda document: document.update({"unknowns": []}),
    )
    with pytest.raises(EvidenceValidationError, match="unknown association.*Unknown"):
        _load_mouse_category(missing)

    wrong_kind = make_valid_category_knowledge_source(
        tmp_path / "wrong-kind", TEST_CATEGORY_ID
    )
    mutate_yaml(
        wrong_kind / f"categories/{TEST_CATEGORY_ID}/coverage.yaml",
        lambda document: document["unknowns"][0].update({"claim_kind": "hazard"}),
    )
    with pytest.raises(EvidenceValidationError, match="unknown association.*Unknown"):
        _load_mouse_category(wrong_kind)


def test_hazard_uses_closed_trigger_vocabulary_and_nonempty_actions(tmp_path):
    empty_triggers = make_valid_category_knowledge_source(
        tmp_path / "triggers", TEST_CATEGORY_ID
    )
    mutate_yaml(
        empty_triggers / f"categories/{TEST_CATEGORY_ID}/hazards.yaml",
        lambda document: document["hazards"][0].update(
            {"trigger_observation_keys": []}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="non-empty"):
        _load_mouse_category(empty_triggers)

    for field in (
        "immediate_actions",
        "follow_up_actions",
        "handling_guidance",
        "disposal_guidance",
    ):
        source = make_valid_category_knowledge_source(
            tmp_path / field, TEST_CATEGORY_ID
        )
        mutate_yaml(
            source / f"categories/{TEST_CATEGORY_ID}/hazards.yaml",
            lambda document, field=field: document["hazards"][0].update(
                {field: []}
            ),
        )
        with pytest.raises(EvidenceValidationError, match="non-empty"):
            _load_mouse_category(source)


def test_hazard_evidence_is_scope_derived_but_category_grade_d_is_allowed(tmp_path):
    valid = make_valid_category_knowledge_source(tmp_path / "valid", TEST_CATEGORY_ID)
    category = _load_mouse_category(valid)
    assert category.hazards[0].evidence_level is EvidenceLevel.D
    assert category.hazards[0].source_ids == (
        f"{TEST_CATEGORY_ID}_hazard_source",
    )
    assert category.specific_lifecycles[0].source_ids == (
        f"{TEST_CATEGORY_ID}_claim_source",
    )

    wrong_model = make_valid_category_knowledge_source(
        tmp_path / "wrong", TEST_CATEGORY_ID
    )

    def make_model_hazard(document: dict[str, object]) -> None:
        document["hazards"][0].update(
            {
                "scope": {"kind": "model", "id": f"{TEST_CATEGORY_ID}_model_01"},
                "evidence_level": "B",
            }
        )

    mutate_yaml(
        wrong_model / f"categories/{TEST_CATEGORY_ID}/hazards.yaml",
        make_model_hazard,
    )
    with pytest.raises(EvidenceValidationError, match="evidence level.*A"):
        _load_mouse_category(wrong_model)


def test_hazard_component_and_scope_references_are_required(tmp_path):
    missing_component = make_valid_category_knowledge_source(
        tmp_path / "component", TEST_CATEGORY_ID
    )
    mutate_yaml(
        missing_component / f"categories/{TEST_CATEGORY_ID}/hazards.yaml",
        lambda document: document["hazards"][0].update(
            {"component_id": "missing_component"}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="component reference"):
        _load_mouse_category(missing_component)

    missing_scope = make_valid_category_knowledge_source(
        tmp_path / "scope", TEST_CATEGORY_ID
    )
    mutate_yaml(
        missing_scope / f"categories/{TEST_CATEGORY_ID}/hazards.yaml",
        lambda document: document["hazards"][0].update(
            {"scope": {"kind": "family", "id": "missing_family"}}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="scope hierarchy"):
        _load_mouse_category(missing_scope)


def test_unknown_stable_keys_are_unique_and_source_free(tmp_path):
    duplicate = make_valid_category_knowledge_source(
        tmp_path / "duplicate", TEST_CATEGORY_ID
    )
    mutate_yaml(
        duplicate / f"categories/{TEST_CATEGORY_ID}/coverage.yaml",
        lambda document: document["unknowns"].append(dict(document["unknowns"][0])),
    )
    with pytest.raises(EvidenceValidationError, match="Unknown stable key.*unique"):
        _load_mouse_category(duplicate)

    source_bearing = make_valid_category_knowledge_source(
        tmp_path / "sources", TEST_CATEGORY_ID
    )
    mutate_yaml(
        source_bearing / f"categories/{TEST_CATEGORY_ID}/coverage.yaml",
        lambda document: document["unknowns"][0].update(
            {"source_ids": [f"{TEST_CATEGORY_ID}_claim_source"]}
        ),
    )
    with pytest.raises(EvidenceValidationError, match=r"Unknown.source_ids.*\[\]"):
        _load_mouse_category(source_bearing)


@pytest.mark.parametrize(
    ("claim_kind", "claim_id"),
    [
        ("subtype", f"{TEST_CATEGORY_ID}_subtype_0"),
        ("variant", f"{TEST_CATEGORY_ID}_variant_0a"),
        ("identity", f"{TEST_CATEGORY_ID}_family_00"),
        ("specific_lifecycle", f"{TEST_CATEGORY_ID}_lifecycle_0_model_service"),
        ("industry_average", f"{TEST_CATEGORY_ID}_industry_service_life"),
        ("component_association", f"{TEST_CATEGORY_ID}_association_legacy_0"),
        ("hazard", f"{TEST_CATEGORY_ID}_damaged_battery_hazard"),
    ],
)
def test_unknown_rows_cannot_collide_with_reviewed_claims(
    tmp_path, claim_kind, claim_id
):
    source = make_valid_category_knowledge_source(tmp_path, TEST_CATEGORY_ID)
    mutate_yaml(
        source / f"categories/{TEST_CATEGORY_ID}/coverage.yaml",
        lambda document: document["unknowns"][0].update(
            {"claim_kind": claim_kind, "claim_id": claim_id}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="Unknown.*reviewed claim"):
        _load_mouse_category(source)


@pytest.mark.parametrize(
    ("relative_name", "root_key", "message"),
    [
        ("identities.yaml", "subtypes", "subtypes.*sorted"),
        ("identities.yaml", "variants", "variants.*sorted"),
        ("identities.yaml", "identities", "identities.*sorted"),
        ("lifecycles.yaml", "lifecycles", "lifecycles.*sorted"),
        ("components.yaml", "components", "components.*sorted"),
        ("components.yaml", "templates", "templates.*sorted"),
        ("components.yaml", "associations", "associations.*sorted"),
    ],
)
def test_every_multi_record_category_list_uses_its_normative_sort_key(
    tmp_path, relative_name, root_key, message
):
    source = make_valid_category_knowledge_source(tmp_path, TEST_CATEGORY_ID)
    mutate_yaml(
        source / f"categories/{TEST_CATEGORY_ID}/{relative_name}",
        lambda document: document[root_key].reverse(),
    )
    with pytest.raises(EvidenceValidationError, match=message):
        _load_mouse_category(source)


@pytest.mark.parametrize(
    ("relative_name", "root_key", "id_field", "new_id", "message"),
    [
        (
            "industry_averages.yaml",
            "industry_averages",
            "record_id",
            "zz_industry_average",
            "industry_averages.*sorted",
        ),
        (
            "hazards.yaml",
            "hazards",
            "hazard_id",
            "zz_hazard",
            "hazards.*sorted",
        ),
    ],
)
def test_singleton_claim_lists_also_enforce_sorting_when_extended(
    tmp_path, relative_name, root_key, id_field, new_id, message
):
    source = make_valid_category_knowledge_source(tmp_path, TEST_CATEGORY_ID)

    def append_then_reverse(document: dict[str, object]) -> None:
        clone = dict(document[root_key][0])
        clone[id_field] = new_id
        document[root_key].append(clone)
        document[root_key].reverse()

    mutate_yaml(
        source / f"categories/{TEST_CATEGORY_ID}/{relative_name}",
        append_then_reverse,
    )
    with pytest.raises(EvidenceValidationError, match=message):
        _load_mouse_category(source)


def test_unknowns_sort_by_stable_three_field_key(tmp_path):
    source = make_valid_category_knowledge_source(tmp_path, TEST_CATEGORY_ID)

    def add_unsorted_unknown(document: dict[str, object]) -> None:
        document["unknowns"].insert(
            0,
            {
                "category_id": TEST_CATEGORY_ID,
                "claim_kind": "hazard",
                "claim_id": "unsupported_hazard",
                "evidence_level": None,
                "source_ids": [],
                "reason": "No reviewed hazard evidence.",
                "evidence_request": "Find hazard evidence.",
            },
        )

    mutate_yaml(
        source / f"categories/{TEST_CATEGORY_ID}/coverage.yaml",
        add_unsorted_unknown,
    )
    with pytest.raises(EvidenceValidationError, match="unknowns.*sorted"):
        _load_mouse_category(source)


@pytest.mark.parametrize(
    ("relative_name", "root_key", "message"),
    [
        ("identities.yaml", "subtypes", "subtype_id.*unique"),
        ("identities.yaml", "variants", "variant_id.*unique"),
        ("identities.yaml", "identities", "identity_id.*unique"),
        ("lifecycles.yaml", "lifecycles", "record_id.*unique"),
        ("components.yaml", "components", "component_id.*unique"),
        ("components.yaml", "templates", "template_id.*unique"),
        ("components.yaml", "associations", "association_id.*unique"),
    ],
)
def test_category_record_identity_keys_are_unique(
    tmp_path, relative_name, root_key, message
):
    source = make_valid_category_knowledge_source(tmp_path, TEST_CATEGORY_ID)

    def duplicate_id(document: dict[str, object]) -> None:
        records = document[root_key]
        id_field = {
            "subtypes": "subtype_id",
            "variants": "variant_id",
            "identities": "identity_id",
            "lifecycles": "record_id",
            "components": "component_id",
            "templates": "template_id",
            "associations": "association_id",
        }[root_key]
        records[1][id_field] = records[0][id_field]

    mutate_yaml(
        source / f"categories/{TEST_CATEGORY_ID}/{relative_name}", duplicate_id
    )
    with pytest.raises(EvidenceValidationError, match=message):
        _load_mouse_category(source)


def test_hazard_ids_and_cross_lifecycle_ids_are_unique_within_category(tmp_path):
    hazards = make_valid_category_knowledge_source(
        tmp_path / "hazards", TEST_CATEGORY_ID
    )

    def duplicate_hazard(document: dict[str, object]) -> None:
        clone = dict(document["hazards"][0])
        document["hazards"].append(clone)

    mutate_yaml(
        hazards / f"categories/{TEST_CATEGORY_ID}/hazards.yaml", duplicate_hazard
    )
    with pytest.raises(EvidenceValidationError, match="hazard_id.*unique"):
        _load_mouse_category(hazards)

    lifecycle_namespace = make_valid_category_knowledge_source(
        tmp_path / "lifecycle", TEST_CATEGORY_ID
    )
    mutate_yaml(
        lifecycle_namespace
        / f"categories/{TEST_CATEGORY_ID}/industry_averages.yaml",
        lambda document: document["industry_averages"][0].update(
            {"record_id": f"{TEST_CATEGORY_ID}_lifecycle_0_model_service"}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="record_id.*unique"):
        _load_mouse_category(lifecycle_namespace)


def test_category_claim_cannot_reference_a_sibling_category_source(tmp_path):
    source = make_valid_knowledge_source(tmp_path)
    mutate_yaml(
        source / f"categories/{TEST_CATEGORY_ID}/lifecycles.yaml",
        lambda document: document["lifecycles"][0].update(
            {"source_ids": ["0303_laptop_claim_source"]}
        ),
    )
    shared = load_shared_evidence_documents(source)
    with pytest.raises(EvidenceValidationError, match="source reference"):
        load_category_evidence_documents(
            source, TEST_CATEGORY_ID, shared=shared
        )


def _deep_replace(value: object, old: str, new: str) -> object:
    if isinstance(value, dict):
        return {key: _deep_replace(item, old, new) for key, item in value.items()}
    if isinstance(value, list):
        return [_deep_replace(item, old, new) for item in value]
    return new if value == old else value


def _replace_scalar_everywhere_in_category(
    source: Path, category_id: str, old: str, new: str
) -> None:
    category_dir = source / "categories" / category_id
    for path in sorted(category_dir.iterdir()):
        def mutation(document: dict[str, object], old=old, new=new) -> None:
            replaced = _deep_replace(document, old, new)
            assert isinstance(replaced, dict)
            document.clear()
            document.update(replaced)

        mutate_yaml(path, mutation)


@pytest.mark.parametrize(
    ("name", "old", "new", "message"),
    [
        (
            "source",
            "0301_keyboard_claim_source",
            "0301_computer_mouse_claim_source",
            "source_id.*globally unique",
        ),
        (
            "subtype",
            "0301_keyboard_subtype_0",
            "0301_computer_mouse_subtype_0",
            "subtype_id.*globally unique",
        ),
        (
            "variant",
            "0301_keyboard_variant_0a",
            "0301_computer_mouse_variant_0a",
            "variant_id.*globally unique",
        ),
        (
            "identity",
            "0301_keyboard_family_00",
            "0301_computer_mouse_family_00",
            "identity_id.*globally unique",
        ),
        (
            "template",
            "0301_keyboard_legacy_overlay",
            "0301_computer_mouse_legacy_overlay",
            "template_id.*globally unique",
        ),
        (
            "association",
            "0301_keyboard_association_legacy_0",
            "0301_computer_mouse_association_legacy_0",
            "association_id.*globally unique",
        ),
        (
            "hazard",
            "0301_keyboard_damaged_battery_hazard",
            "0301_computer_mouse_damaged_battery_hazard",
            "hazard_id.*globally unique",
        ),
    ],
)
def test_complete_loader_enforces_cross_category_global_ids(
    tmp_path, name, old, new, message
):
    source = make_valid_knowledge_source(tmp_path / name)
    _replace_scalar_everywhere_in_category(source, "0301_keyboard", old, new)
    with pytest.raises(EvidenceValidationError, match=message):
        load_evidence_documents(source)


def test_complete_loader_has_one_global_lifecycle_record_id_namespace(tmp_path):
    source = make_valid_knowledge_source(tmp_path)
    mutate_yaml(
        source / "categories/0301_keyboard/industry_averages.yaml",
        lambda document: document["industry_averages"][0].update(
            {"record_id": "0301_computer_mouse_lifecycle_0_model_service"}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="record_id.*globally unique"):
        load_evidence_documents(source)


def test_component_ids_may_repeat_across_categories(tmp_path):
    documents = load_evidence_documents(make_valid_knowledge_source(tmp_path))
    assert all(
        category.component_definitions[0].component_id == "battery"
        for category in documents.categories
    )


@pytest.mark.parametrize("relative_path", SHARED_ROOT_PATHS)
def test_shared_loader_requires_each_fixed_regular_document(tmp_path, relative_path):
    missing = make_valid_shared_knowledge_source(tmp_path / "missing")
    (missing / relative_path).unlink()
    with pytest.raises(EvidenceValidationError, match="required regular file"):
        load_shared_evidence_documents(missing)

    directory = make_valid_shared_knowledge_source(tmp_path / "directory")
    path = directory / relative_path
    path.unlink()
    path.mkdir()
    with pytest.raises(EvidenceValidationError, match="required regular file"):
        load_shared_evidence_documents(directory)


@pytest.mark.parametrize("relative_path", CATEGORY_ROOT_PATHS)
def test_category_loader_requires_each_fixed_regular_document(tmp_path, relative_path):
    missing = make_valid_category_knowledge_source(
        tmp_path / "missing" / relative_path.replace("/", "-"), TEST_CATEGORY_ID
    )
    shared = load_shared_evidence_documents(missing)
    (missing / relative_path).unlink()
    with pytest.raises(EvidenceValidationError, match="required regular file"):
        load_category_evidence_documents(
            missing, TEST_CATEGORY_ID, shared=shared
        )

    directory = make_valid_category_knowledge_source(
        tmp_path / "directory" / relative_path.replace("/", "-"),
        TEST_CATEGORY_ID,
    )
    shared = load_shared_evidence_documents(directory)
    path = directory / relative_path
    path.unlink()
    path.mkdir()
    with pytest.raises(EvidenceValidationError, match="required regular file"):
        load_category_evidence_documents(
            directory, TEST_CATEGORY_ID, shared=shared
        )


def test_loader_rejects_a_symlink_in_an_ancestor_path_component(tmp_path):
    real_parent = tmp_path / "real-parent"
    source = make_valid_shared_knowledge_source(real_parent / "source")
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    hostile_source = linked_parent / source.name
    with pytest.raises(EvidenceValidationError, match="unsafe path"):
        load_shared_evidence_documents(hostile_source)


@pytest.mark.parametrize(
    ("name", "relative_path", "category_loader"),
    [
        ("bundle", "bundle.yaml", False),
        (
            "category-identities",
            f"categories/{TEST_CATEGORY_ID}/identities.yaml",
            True,
        ),
    ],
)
def test_loader_rejects_document_swapped_to_out_of_tree_symlink_after_validation(
    tmp_path,
    monkeypatch,
    name,
    relative_path,
    category_loader,
):
    source = make_valid_category_knowledge_source(
        tmp_path / "source", TEST_CATEGORY_ID
    )
    shared = load_shared_evidence_documents(source) if category_loader else None
    target = source / relative_path
    outside = tmp_path / f"outside-{name}.yaml"
    shutil.copy2(target, outside)
    original = knowledge_schema._require_regular_file
    swap_count = 0

    def swap_after_validation(path: Path, filename: str) -> Path:
        nonlocal swap_count
        checked = original(path, filename)
        if checked == target and swap_count == 0:
            target.unlink()
            target.symlink_to(outside)
            swap_count += 1
        return checked

    monkeypatch.setattr(
        knowledge_schema, "_require_regular_file", swap_after_validation
    )
    with pytest.raises(EvidenceValidationError, match="unsafe path|changed"):
        if category_loader:
            load_category_evidence_documents(
                source, TEST_CATEGORY_ID, shared=shared
            )
        else:
            load_shared_evidence_documents(source)
    assert swap_count == 1


@pytest.mark.parametrize(
    ("name", "ancestor_path", "last_document", "category_loader"),
    [
        ("common", "common", "common/policies.yaml", False),
        (
            "category",
            f"categories/{TEST_CATEGORY_ID}",
            f"categories/{TEST_CATEGORY_ID}/coverage.yaml",
            True,
        ),
    ],
)
def test_loader_rejects_ancestor_swapped_to_out_of_tree_symlink_before_read(
    tmp_path,
    monkeypatch,
    name,
    ancestor_path,
    last_document,
    category_loader,
):
    source = make_valid_category_knowledge_source(
        tmp_path / "source", TEST_CATEGORY_ID
    )
    shared = load_shared_evidence_documents(source) if category_loader else None
    ancestor = source / ancestor_path
    target = source / last_document
    outside = tmp_path / f"outside-{name}"
    shutil.copytree(ancestor, outside)
    original = knowledge_schema._require_regular_file
    swap_count = 0

    def swap_after_validation(path: Path, filename: str) -> Path:
        nonlocal swap_count
        checked = original(path, filename)
        if checked == target and swap_count == 0:
            shutil.rmtree(ancestor)
            ancestor.symlink_to(outside, target_is_directory=True)
            swap_count += 1
        return checked

    monkeypatch.setattr(
        knowledge_schema, "_require_regular_file", swap_after_validation
    )
    with pytest.raises(EvidenceValidationError, match="unsafe path|changed"):
        if category_loader:
            load_category_evidence_documents(
                source, TEST_CATEGORY_ID, shared=shared
            )
        else:
            load_shared_evidence_documents(source)
    assert swap_count == 1


def test_loader_rejects_regular_entry_replaced_after_directory_snapshot(
    tmp_path, monkeypatch
):
    source = make_valid_shared_knowledge_source(tmp_path / "source")
    target = source / "bundle.yaml"
    outside = tmp_path / "outside-bundle.yaml"
    shutil.copy2(target, outside)
    original = knowledge_schema._directory_names_no_follow
    swap_count = 0

    def swap_after_snapshot(
        path: Path,
        filename: str,
        *,
        checked=None,
    ) -> dict[str, object]:
        nonlocal swap_count
        entries = original(path, filename, checked=checked)
        if filename == "." and swap_count == 0:
            target.unlink()
            os.link(outside, target)
            swap_count += 1
        return entries

    monkeypatch.setattr(
        knowledge_schema, "_directory_names_no_follow", swap_after_snapshot
    )
    with pytest.raises(EvidenceValidationError, match="unsafe path|changed"):
        load_shared_evidence_documents(source)
    assert swap_count == 1


def test_category_source_list_may_be_empty_when_claims_use_shared_sources(tmp_path):
    source = make_valid_category_knowledge_source(tmp_path, TEST_CATEGORY_ID)
    claim_source = f"{TEST_CATEGORY_ID}_claim_source"
    category_dir = source / "categories" / TEST_CATEGORY_ID
    for filename in (
        "identities.yaml",
        "lifecycles.yaml",
        "industry_averages.yaml",
        "components.yaml",
    ):
        path = category_dir / filename

        def replace_refs(document: dict[str, object]) -> None:
            replaced = _deep_replace(document, claim_source, "shared_process_source")
            assert isinstance(replaced, dict)
            document.clear()
            document.update(replaced)

        mutate_yaml(path, replace_refs)
    hazard_path = category_dir / "hazards.yaml"
    mutate_yaml(
        hazard_path,
        lambda document: document["hazards"][0].update(
            {"source_ids": ["shared_process_source"]}
        ),
    )
    mutate_yaml(
        category_dir / "sources.yaml",
        lambda document: document.update({"sources": []}),
    )
    assert _load_mouse_category(source).sources == ()


def test_model_template_may_author_exact_model_confirmed_association(tmp_path):
    source = make_valid_category_knowledge_source(tmp_path, TEST_CATEGORY_ID)
    path = source / f"categories/{TEST_CATEGORY_ID}/components.yaml"

    def add_model_layer(document: dict[str, object]) -> None:
        template_id = f"{TEST_CATEGORY_ID}_model_overlay"
        document["templates"].append(
            {
                "template_id": template_id,
                "template_kind": "modern_overlay",
                "scope": {"kind": "model", "id": f"{TEST_CATEGORY_ID}_model_01"},
                "application_order": 0,
            }
        )
        document["templates"].sort(key=lambda item: item["template_id"])
        document["associations"].append(
            {
                "association_id": f"{TEST_CATEGORY_ID}_association_model_0",
                "template_id": template_id,
                "component_id": "storage",
                "position": 0,
                "status": "exact_model_confirmed",
                "applicability": "Exact synthetic model association.",
                "notes": [],
                "evidence_level": "A",
                "source_ids": [f"{TEST_CATEGORY_ID}_claim_source"],
            }
        )
        document["associations"].sort(
            key=lambda item: (
                item["template_id"], item["position"], item["association_id"]
            )
        )

    mutate_yaml(path, add_model_layer)
    category = _load_mouse_category(source)
    exact = next(
        association
        for association in category.component_associations
        if association.status is AssociationStatus.EXACT_MODEL_CONFIRMED
    )
    assert exact.evidence_level is EvidenceLevel.A

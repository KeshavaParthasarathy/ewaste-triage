"""Independent projection, SQLite, filesystem, promotion, and CLI contracts."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import date, timedelta
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import socket
import stat
import subprocess
import sys
from typing import Callable, Mapping
import unicodedata

import pytest
import yaml

import scripts.knowledge_compiler as compiler_module
import scripts.knowledge_schema as schema_module
from scripts.evidence_coverage import CoverageError, build_coverage, coverage_json_bytes
from scripts.knowledge_compiler import (
    KnowledgeCompilationError,
    compile_knowledge_bundle,
    logical_content_sha256,
    normalized_sql_rows,
)
from scripts.knowledge_schema import (
    EvidenceDocuments,
    EvidenceValidationError,
    load_evidence_documents,
)
from server.evidence_types import RELEASED_CATEGORY_IDS
from tests.knowledge_helpers import (
    category_path_mutations,
    complete_tree_mutations,
    make_valid_knowledge_source,
    mutate_yaml,
    record_field_type_sets,
    root_value_type_sets,
    shared_path_mutations,
)
from tests.test_evidence_coverage import expected_coverage_report


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv/bin/python"

TABLE_ORDER = (
    "metadata",
    "sources",
    "categories",
    "subtypes",
    "variants",
    "identities",
    "identity_aliases",
    "identity_tokens",
    "identity_variants",
    "lifecycle_records",
    "lifecycle_required_variants",
    "lifecycle_excluded_variants",
    "lifecycle_assumptions",
    "industry_averages",
    "lifecycle_limitations",
    "components",
    "component_templates",
    "component_associations",
    "component_association_notes",
    "hazards",
    "hazard_triggers",
    "hazard_actions",
    "policy_rules",
    "policy_predicates",
    "coverage_unknowns",
    "claim_sources",
)

EXPECTED_TABLE_COLUMNS = {
    "metadata": ("key", "value"),
    "sources": (
        "source_id", "title", "publisher", "canonical_url",
        "publication_or_revision_date", "accessed_on", "license_or_use_basis",
        "reviewed_by", "reviewed_on",
    ),
    "categories": ("category_id", "display_name", "release_order"),
    "subtypes": (
        "subtype_id", "category_id", "display_name", "market_state",
        "battery_architecture", "evidence_level",
    ),
    "variants": (
        "variant_id", "category_id", "subtype_id", "display_name",
        "battery_architecture", "evidence_level",
    ),
    "identities": (
        "identity_id", "identity_kind", "category_id", "subtype_id",
        "manufacturer_id", "manufacturer_name", "family_id", "family_name",
        "model_id", "model_name", "display_name", "model_year_from",
        "model_year_to", "applicable_from", "applicable_to", "market_state",
        "battery_architecture", "evidence_level",
    ),
    "identity_aliases": ("identity_id", "ordinal", "alias", "alias_casefold"),
    "identity_tokens": ("identity_id", "ordinal", "token", "token_casefold"),
    "identity_variants": ("identity_id", "ordinal", "variant_id"),
    "lifecycle_records": (
        "record_id", "category_id", "resolution_tier", "scope_kind",
        "scope_id", "subject", "endpoint", "endpoint_kind", "metric", "unit",
        "lower_bound", "upper_bound", "endpoint_qualification",
        "applicable_from", "applicable_to", "model_year_from", "model_year_to",
        "precedence", "evidence_level",
    ),
    "lifecycle_required_variants": ("record_id", "ordinal", "variant_id"),
    "lifecycle_excluded_variants": ("record_id", "ordinal", "variant_id"),
    "lifecycle_assumptions": ("record_id", "ordinal", "assumption"),
    "industry_averages": (
        "record_id", "population_definition", "publication_period",
        "methodology", "uncertainty",
    ),
    "lifecycle_limitations": ("record_id", "ordinal", "limitation"),
    "components": ("category_id", "component_id", "display_name"),
    "component_templates": (
        "template_id", "category_id", "template_kind", "scope_kind",
        "scope_id", "application_order",
    ),
    "component_associations": (
        "association_id", "category_id", "template_id", "component_id",
        "position", "status", "applicability", "evidence_level",
    ),
    "component_association_notes": ("association_id", "ordinal", "note"),
    "hazards": (
        "hazard_id", "category_id", "component_id", "scope_kind", "scope_id",
        "applicability", "severity", "evidence_level",
    ),
    "hazard_triggers": ("hazard_id", "ordinal", "observation_key"),
    "hazard_actions": ("hazard_id", "action_kind", "ordinal", "action_text"),
    "policy_rules": ("rule_id", "priority", "outcome", "rationale", "evidence_level"),
    "policy_predicates": ("rule_id", "predicate_group", "ordinal", "predicate"),
    "coverage_unknowns": (
        "category_id", "claim_kind", "claim_id", "reason", "evidence_request",
    ),
    "claim_sources": (
        "claim_kind", "category_key", "claim_id", "ordinal", "source_id",
    ),
}

EXPECTED_PRIMARY_KEY_COLUMNS = {
    "metadata": ("key",),
    "sources": ("source_id",),
    "categories": ("category_id",),
    "subtypes": ("subtype_id",),
    "variants": ("variant_id",),
    "identities": ("identity_id",),
    "identity_aliases": ("identity_id", "ordinal"),
    "identity_tokens": ("identity_id", "ordinal"),
    "identity_variants": ("identity_id", "ordinal"),
    "lifecycle_records": ("record_id",),
    "lifecycle_required_variants": ("record_id", "ordinal"),
    "lifecycle_excluded_variants": ("record_id", "ordinal"),
    "lifecycle_assumptions": ("record_id", "ordinal"),
    "industry_averages": ("record_id",),
    "lifecycle_limitations": ("record_id", "ordinal"),
    "components": ("category_id", "component_id"),
    "component_templates": ("template_id",),
    "component_associations": ("association_id",),
    "component_association_notes": ("association_id", "ordinal"),
    "hazards": ("hazard_id",),
    "hazard_triggers": ("hazard_id", "ordinal"),
    "hazard_actions": ("hazard_id", "action_kind", "ordinal"),
    "policy_rules": ("rule_id",),
    "policy_predicates": ("rule_id", "predicate_group", "ordinal"),
    "coverage_unknowns": ("category_id", "claim_kind", "claim_id"),
    "claim_sources": ("claim_kind", "category_key", "claim_id", "ordinal"),
}

CATEGORY_RELEASE_ORDER = {
    "0301_computer_mouse": 0,
    "0301_keyboard": 1,
    "0303_laptop": 2,
    "0306_mobile_phone": 3,
    "0401_headphones": 4,
}
EXPECTED_SCHEMA_SIGNATURE_SHA256 = (
    "9e46f4501848c75de67d7b7cbe806217d8d31f51b6964ffbd85792293f061c74"
)

NULLABLE_COLUMNS = {
    ("identities", "model_id"),
    ("identities", "model_name"),
    ("identities", "model_year_from"),
    ("identities", "model_year_to"),
    ("identities", "applicable_from"),
    ("identities", "applicable_to"),
    ("lifecycle_records", "applicable_from"),
    ("lifecycle_records", "applicable_to"),
    ("lifecycle_records", "model_year_from"),
    ("lifecycle_records", "model_year_to"),
    ("component_associations", "evidence_level"),
}

REAL_COLUMNS = {
    ("lifecycle_records", "lower_bound"),
    ("lifecycle_records", "upper_bound"),
}
INTEGER_COLUMN_NAMES = {
    "release_order",
    "ordinal",
    "precedence",
    "application_order",
    "position",
    "priority",
    "model_year_from",
    "model_year_to",
}

EXPECTED_UNIQUE_COLUMNS = {
    "categories": {("release_order",)},
    "subtypes": {("category_id", "subtype_id")},
    "identity_aliases": {
        ("identity_id", "alias"),
        ("identity_id", "alias_casefold"),
    },
    "identity_tokens": {
        ("identity_id", "token"),
        ("identity_id", "token_casefold"),
    },
    "identity_variants": {("identity_id", "variant_id")},
    "lifecycle_required_variants": {("record_id", "variant_id")},
    "lifecycle_excluded_variants": {("record_id", "variant_id")},
    "lifecycle_assumptions": {("record_id", "assumption")},
    "lifecycle_limitations": {("record_id", "limitation")},
    "component_templates": {
        ("category_id", "template_id"),
        ("category_id", "scope_kind", "scope_id", "application_order"),
    },
    "component_associations": {("template_id", "position")},
    "component_association_notes": {("association_id", "note")},
    "hazard_triggers": {("hazard_id", "observation_key")},
    "hazard_actions": {("hazard_id", "action_kind", "action_text")},
    "policy_rules": {("priority",)},
    "policy_predicates": {("rule_id", "predicate")},
    "claim_sources": {
        ("claim_kind", "category_key", "claim_id", "source_id")
    },
}

EXPECTED_FOREIGN_KEYS = {
    ("subtypes", ("category_id",), "categories", ("category_id",)),
    ("variants", ("category_id",), "categories", ("category_id",)),
    (
        "variants",
        ("category_id", "subtype_id"),
        "subtypes",
        ("category_id", "subtype_id"),
    ),
    ("identities", ("category_id",), "categories", ("category_id",)),
    (
        "identities",
        ("category_id", "subtype_id"),
        "subtypes",
        ("category_id", "subtype_id"),
    ),
    ("identity_aliases", ("identity_id",), "identities", ("identity_id",)),
    ("identity_tokens", ("identity_id",), "identities", ("identity_id",)),
    ("identity_variants", ("identity_id",), "identities", ("identity_id",)),
    ("identity_variants", ("variant_id",), "variants", ("variant_id",)),
    ("lifecycle_records", ("category_id",), "categories", ("category_id",)),
    (
        "lifecycle_required_variants",
        ("record_id",),
        "lifecycle_records",
        ("record_id",),
    ),
    (
        "lifecycle_required_variants",
        ("variant_id",),
        "variants",
        ("variant_id",),
    ),
    (
        "lifecycle_excluded_variants",
        ("record_id",),
        "lifecycle_records",
        ("record_id",),
    ),
    (
        "lifecycle_excluded_variants",
        ("variant_id",),
        "variants",
        ("variant_id",),
    ),
    (
        "lifecycle_assumptions",
        ("record_id",),
        "lifecycle_records",
        ("record_id",),
    ),
    ("industry_averages", ("record_id",), "lifecycle_records", ("record_id",)),
    (
        "lifecycle_limitations",
        ("record_id",),
        "industry_averages",
        ("record_id",),
    ),
    ("components", ("category_id",), "categories", ("category_id",)),
    (
        "component_templates",
        ("category_id",),
        "categories",
        ("category_id",),
    ),
    (
        "component_associations",
        ("category_id", "template_id"),
        "component_templates",
        ("category_id", "template_id"),
    ),
    (
        "component_associations",
        ("category_id", "component_id"),
        "components",
        ("category_id", "component_id"),
    ),
    (
        "component_association_notes",
        ("association_id",),
        "component_associations",
        ("association_id",),
    ),
    (
        "hazards",
        ("category_id", "component_id"),
        "components",
        ("category_id", "component_id"),
    ),
    ("hazard_triggers", ("hazard_id",), "hazards", ("hazard_id",)),
    ("hazard_actions", ("hazard_id",), "hazards", ("hazard_id",)),
    ("policy_predicates", ("rule_id",), "policy_rules", ("rule_id",)),
    ("coverage_unknowns", ("category_id",), "categories", ("category_id",)),
    ("claim_sources", ("source_id",), "sources", ("source_id",)),
}

EXPECTED_HELP = """usage: build_knowledge_bundle.py --source PATH --out DIRECTORY [--print-summary]

Compile reviewed schema-3 knowledge YAML into one atomic bundle directory.

options:
  -h, --help       show this help message and exit
  --source PATH    reviewed schema-3 source directory
  --out DIRECTORY  destination bundle directory
  --print-summary  print the deterministic bundle summary
"""

# This inventory is deliberately test-owned.  It repeats the complete Task 2
# authoring surface so a new field cannot silently disappear in projection.
AUTHORING_ROOT_FIELDS = {
    "bundle.yaml": ("bundle",),
    "common/sources.yaml": ("sources",),
    "common/policies.yaml": ("policy_revision", "policies"),
    "categories/{category_id}/sources.yaml": ("sources",),
    "categories/{category_id}/identities.yaml": (
        "category", "subtypes", "variants", "identities",
    ),
    "categories/{category_id}/lifecycles.yaml": ("lifecycles",),
    "categories/{category_id}/industry_averages.yaml": ("industry_averages",),
    "categories/{category_id}/components.yaml": (
        "components", "templates", "associations",
    ),
    "categories/{category_id}/hazards.yaml": ("hazards",),
    "categories/{category_id}/coverage.yaml": ("unknowns",),
}

AUTHORING_RECORD_FIELDS = {
    "bundle": (
        "schema_version", "bundle_version", "identity_catalog_version",
        "policy_revision", "category_ids",
    ),
    "source": (
        "source_id", "title", "publisher", "canonical_url",
        "publication_or_revision_date", "accessed_on", "license_or_use_basis",
        "reviewed_by", "reviewed_on",
    ),
    "policy": (
        "rule_id", "priority", "outcome", "when_all", "when_any", "rationale",
        "evidence_level", "source_ids",
    ),
    "category": ("category_id", "display_name"),
    "subtype": (
        "subtype_id", "category_id", "display_name", "market_state",
        "battery_architecture", "evidence_level", "source_ids",
    ),
    "variant": (
        "variant_id", "category_id", "subtype_id", "display_name",
        "battery_architecture", "evidence_level", "source_ids",
    ),
    "identity": (
        "identity_id", "identity_kind", "category_id", "subtype_id",
        "manufacturer_id", "manufacturer_name", "family_id", "family_name",
        "model_id", "model_name", "display_name", "aliases",
        "distinguishing_tokens", "model_year_from", "model_year_to",
        "applicable_from", "applicable_to", "variant_ids", "market_state",
        "battery_architecture", "evidence_level", "source_ids",
    ),
    "specific_lifecycle": (
        "record_id", "scope", "subject", "endpoint", "endpoint_kind", "metric",
        "unit", "lower_bound", "upper_bound", "endpoint_qualification",
        "applicable_from", "applicable_to", "model_year_from", "model_year_to",
        "required_variant_ids", "excluded_variant_ids", "precedence",
        "evidence_level", "assumptions", "source_ids",
    ),
    "industry_average": (
        "record_id", "scope", "subject", "endpoint", "endpoint_kind", "metric",
        "unit", "lower_bound", "upper_bound", "endpoint_qualification",
        "applicable_from", "applicable_to", "model_year_from", "model_year_to",
        "required_variant_ids", "excluded_variant_ids", "precedence",
        "evidence_level", "assumptions", "population_definition",
        "publication_period", "methodology", "uncertainty", "limitations",
        "source_ids",
    ),
    "component_definition": ("component_id", "display_name"),
    "component_template": (
        "template_id", "template_kind", "scope", "application_order",
    ),
    "component_association": (
        "association_id", "template_id", "component_id", "position", "status",
        "applicability", "notes", "evidence_level", "source_ids",
    ),
    "hazard": (
        "hazard_id", "component_id", "scope", "applicability",
        "trigger_observation_keys", "severity", "immediate_actions",
        "follow_up_actions", "handling_guidance", "disposal_guidance",
        "evidence_level", "source_ids",
    ),
    "unknown": (
        "category_id", "claim_kind", "claim_id", "evidence_level", "source_ids",
        "reason", "evidence_request",
    ),
    "scope": ("kind", "id"),
}

_RECORD_TABLE = {
    "source": "sources",
    "policy": "policy_rules",
    "category": "categories",
    "subtype": "subtypes",
    "variant": "variants",
    "identity": "identities",
    "specific_lifecycle": "lifecycle_records",
    "industry_average": "lifecycle_records",
    "component_definition": "components",
    "component_template": "component_templates",
    "component_association": "component_associations",
    "hazard": "hazards",
    "unknown": "coverage_unknowns",
}
_COVERAGE_TOP_FIELDS = {
    ("top", "schema_version"),
    ("top", "bundle_version"),
    ("top", "knowledge_content_sha256"),
    ("top", "summary"),
    ("top", "claims"),
}
_COVERAGE_SUMMARY_FIELDS = {
    ("summary", field)
    for field in (
        "categories", "canonical_identities", "subtypes", "lifecycle_records",
        "industry_averages", "component_templates", "modern_overlays",
        "legacy_overlays", "hazard_records", "reviewed_claims", "unknown_claims",
    )
}
_COVERAGE_CLAIM_FIELDS = {
    ("claim", field)
    for field in (
        "category_id", "claim_kind", "claim_id", "evidence_level",
        "source_state", "source_ids", "unknown_reason",
    )
}


def _record_authoring_targets(
    record: str, field: str
) -> tuple[frozenset[tuple[str, str]], frozenset[tuple[str, str]]]:
    """Return the literal semantic cells changed by one authored field kind."""
    sql: set[tuple[str, str]] = set()
    coverage: set[tuple[str, str]] = set()
    table = _RECORD_TABLE.get(record)
    if table is not None and field in EXPECTED_TABLE_COLUMNS[table]:
        sql.add((table, field))

    if record == "bundle":
        if field != "category_ids":
            sql.add(("metadata", "value"))
        else:
            sql.add(("categories", "category_id"))
        if field == "bundle_version":
            coverage.add(("top", "bundle_version"))
    elif record == "policy":
        if field in {"when_all", "when_any"}:
            sql |= {
                ("policy_predicates", "rule_id"),
                ("policy_predicates", "predicate"),
                ("policy_predicates", "predicate_group"),
                ("policy_predicates", "ordinal"),
            }
        if field == "rule_id":
            sql |= {
                ("policy_predicates", "rule_id"),
                ("claim_sources", "claim_id"),
            }
        if field == "source_ids":
            sql |= {
                ("claim_sources", "claim_kind"),
                ("claim_sources", "category_key"),
                ("claim_sources", "claim_id"),
                ("claim_sources", "source_id"),
                ("claim_sources", "ordinal"),
            }
    elif record == "category" and field == "category_id":
        sql |= {
            ("lifecycle_records", "category_id"),
            ("components", "category_id"),
            ("component_templates", "category_id"),
            ("component_associations", "category_id"),
            ("hazards", "category_id"),
        }
        coverage.add(("claim", "category_id"))
    elif record == "identity":
        if field == "identity_id":
            sql |= {
                ("identity_aliases", "identity_id"),
                ("identity_tokens", "identity_id"),
                ("identity_variants", "identity_id"),
                ("claim_sources", "claim_id"),
            }
        if field == "aliases":
            sql |= {
                ("identity_aliases", "identity_id"),
                ("identity_aliases", "alias"),
                ("identity_aliases", "alias_casefold"),
                ("identity_aliases", "ordinal"),
            }
        if field == "distinguishing_tokens":
            sql |= {
                ("identity_tokens", "identity_id"),
                ("identity_tokens", "token"),
                ("identity_tokens", "token_casefold"),
                ("identity_tokens", "ordinal"),
            }
        if field == "variant_ids":
            sql |= {
                ("identity_variants", "identity_id"),
                ("identity_variants", "variant_id"),
                ("identity_variants", "ordinal"),
            }
    elif record in {"specific_lifecycle", "industry_average"}:
        if field == "record_id":
            sql |= {
                ("lifecycle_required_variants", "record_id"),
                ("lifecycle_excluded_variants", "record_id"),
                ("lifecycle_assumptions", "record_id"),
                ("claim_sources", "claim_id"),
            }
            if record == "industry_average":
                sql |= {
                    ("industry_averages", "record_id"),
                    ("lifecycle_limitations", "record_id"),
                }
        if field == "required_variant_ids":
            sql |= {
                ("lifecycle_required_variants", "record_id"),
                ("lifecycle_required_variants", "variant_id"),
                ("lifecycle_required_variants", "ordinal"),
            }
        if field == "excluded_variant_ids":
            sql |= {
                ("lifecycle_excluded_variants", "record_id"),
                ("lifecycle_excluded_variants", "variant_id"),
                ("lifecycle_excluded_variants", "ordinal"),
            }
        if field == "assumptions":
            sql |= {
                ("lifecycle_assumptions", "record_id"),
                ("lifecycle_assumptions", "assumption"),
                ("lifecycle_assumptions", "ordinal"),
            }
        if record == "industry_average" and field in EXPECTED_TABLE_COLUMNS["industry_averages"]:
            sql.add(("industry_averages", field))
        if record == "industry_average" and field == "limitations":
            sql |= {
                ("lifecycle_limitations", "record_id"),
                ("lifecycle_limitations", "limitation"),
                ("lifecycle_limitations", "ordinal"),
            }
    elif record == "component_template" and field == "template_id":
        sql.add(("component_associations", "template_id"))
    elif record == "component_template" and field == "template_kind":
        coverage |= {
            ("summary", "modern_overlays"),
            ("summary", "legacy_overlays"),
        }
    elif record == "component_association":
        if field == "association_id":
            sql |= {
                ("component_association_notes", "association_id"),
                ("claim_sources", "claim_id"),
            }
        if field == "notes":
            sql |= {
                ("component_association_notes", "association_id"),
                ("component_association_notes", "note"),
                ("component_association_notes", "ordinal"),
            }
    elif record == "hazard":
        if field == "hazard_id":
            sql |= {
                ("hazard_triggers", "hazard_id"),
                ("hazard_actions", "hazard_id"),
                ("claim_sources", "claim_id"),
            }
        if field == "trigger_observation_keys":
            sql |= {
                ("hazard_triggers", "hazard_id"),
                ("hazard_triggers", "observation_key"),
                ("hazard_triggers", "ordinal"),
            }
        if field in {
            "immediate_actions", "follow_up_actions", "handling_guidance",
            "disposal_guidance",
        }:
            sql |= {
                ("hazard_actions", "hazard_id"),
                ("hazard_actions", "action_text"),
                ("hazard_actions", "action_kind"),
                ("hazard_actions", "ordinal"),
            }

    reviewed_claim_records = {
        "subtype", "variant", "identity", "specific_lifecycle",
        "industry_average", "component_association", "hazard",
    }
    id_field = {
        "subtype": "subtype_id",
        "variant": "variant_id",
        "identity": "identity_id",
        "specific_lifecycle": "record_id",
        "industry_average": "record_id",
        "component_association": "association_id",
        "hazard": "hazard_id",
    }.get(record)
    if record in reviewed_claim_records:
        if field == id_field:
            sql.add(("claim_sources", "claim_id"))
            coverage.add(("claim", "claim_id"))
        if field == "category_id":
            sql.add(("claim_sources", "category_key"))
            coverage.add(("claim", "category_id"))
        if field == "evidence_level":
            coverage.add(("claim", "evidence_level"))
        if field == "source_ids":
            sql |= {
                ("claim_sources", "claim_kind"),
                ("claim_sources", "category_key"),
                ("claim_sources", "claim_id"),
                ("claim_sources", "source_id"),
                ("claim_sources", "ordinal"),
            }
            coverage.add(("claim", "source_ids"))
    if record == "component_association" and field == "status":
        coverage |= _COVERAGE_CLAIM_FIELDS | {
            ("summary", "reviewed_claims"),
            ("summary", "unknown_claims"),
        }
    if record == "unknown":
        unknown_coverage = {
            "category_id": "category_id",
            "claim_kind": "claim_kind",
            "claim_id": "claim_id",
            "evidence_level": "evidence_level",
            "source_ids": "source_ids",
            "reason": "unknown_reason",
        }
        if field in unknown_coverage:
            coverage.add(("claim", unknown_coverage[field]))
        if field in {"category_id", "claim_kind", "claim_id"}:
            sql.add(("coverage_unknowns", field))
        if field in {"evidence_level", "source_ids"}:
            sql |= {
                ("coverage_unknowns", column)
                for column in EXPECTED_TABLE_COLUMNS["coverage_unknowns"]
            }

    if record == "scope":
        column = "scope_kind" if field == "kind" else "scope_id"
        sql |= {
            ("lifecycle_records", column),
            ("component_templates", column),
            ("hazards", column),
        }
        if field == "kind":
            sql.add(("lifecycle_records", "resolution_tier"))
    if field == "scope" and record in {
        "specific_lifecycle", "industry_average", "component_template", "hazard",
    }:
        scope_table = {
            "specific_lifecycle": "lifecycle_records",
            "industry_average": "lifecycle_records",
            "component_template": "component_templates",
            "hazard": "hazards",
        }[record]
        sql |= {(scope_table, "scope_kind"), (scope_table, "scope_id")}
        if record in {"specific_lifecycle", "industry_average"}:
            sql.add(("lifecycle_records", "resolution_tier"))

    if sql:
        coverage.add(("top", "knowledge_content_sha256"))
    if any(section == "claim" for section, _field in coverage):
        coverage.add(("top", "claims"))
    if any(section == "summary" for section, _field in coverage):
        coverage.add(("top", "summary"))
    return frozenset(sql), frozenset(coverage)


AUTHORING_FIELD_TARGETS = {
    **{
        ("record", record, field): _record_authoring_targets(record, field)
        for record, fields in AUTHORING_RECORD_FIELDS.items()
        for field in fields
    },
}


def _record_union(record: str) -> tuple[frozenset[tuple[str, str]], frozenset[tuple[str, str]]]:
    sql: set[tuple[str, str]] = set()
    coverage: set[tuple[str, str]] = set()
    for field in AUTHORING_RECORD_FIELDS[record]:
        field_sql, field_coverage = AUTHORING_FIELD_TARGETS[("record", record, field)]
        sql.update(field_sql)
        coverage.update(field_coverage)
    return frozenset(sql), frozenset(coverage)


_ROOT_RECORD = {
    ("bundle.yaml", "bundle"): "bundle",
    ("common/sources.yaml", "sources"): "source",
    ("common/policies.yaml", "policies"): "policy",
    ("categories/{category_id}/sources.yaml", "sources"): "source",
    ("categories/{category_id}/identities.yaml", "category"): "category",
    ("categories/{category_id}/identities.yaml", "subtypes"): "subtype",
    ("categories/{category_id}/identities.yaml", "variants"): "variant",
    ("categories/{category_id}/identities.yaml", "identities"): "identity",
    ("categories/{category_id}/lifecycles.yaml", "lifecycles"): "specific_lifecycle",
    ("categories/{category_id}/industry_averages.yaml", "industry_averages"): "industry_average",
    ("categories/{category_id}/components.yaml", "components"): "component_definition",
    ("categories/{category_id}/components.yaml", "templates"): "component_template",
    ("categories/{category_id}/components.yaml", "associations"): "component_association",
    ("categories/{category_id}/hazards.yaml", "hazards"): "hazard",
    ("categories/{category_id}/coverage.yaml", "unknowns"): "unknown",
}
for _path, _fields in AUTHORING_ROOT_FIELDS.items():
    for _field in _fields:
        if (_path, _field) == ("common/policies.yaml", "policy_revision"):
            _root_targets = _record_authoring_targets("bundle", "policy_revision")
        else:
            _root_targets = _record_union(_ROOT_RECORD[(_path, _field)])
        AUTHORING_FIELD_TARGETS[("root", _path, _field)] = _root_targets


def _derived(
    sql: tuple[tuple[str, str], ...] = (),
    coverage: tuple[tuple[str, str], ...] = (),
) -> tuple[frozenset[tuple[str, str]], frozenset[tuple[str, str]]]:
    return frozenset(sql), frozenset(coverage)


DERIVED_TARGETS = {
    "metadata.semantic_keys": _derived(sql=(("metadata", "key"),)),
    "metadata.content_sha256": _derived(sql=(("metadata", "key"), ("metadata", "value"))),
    "metadata.coverage_sha256": _derived(sql=(("metadata", "key"), ("metadata", "value"))),
    "category.release_order": _derived(sql=(("categories", "release_order"),)),
    "current_category.components": _derived(sql=(("components", "category_id"),)),
    "current_category.templates": _derived(sql=(("component_templates", "category_id"),)),
    "current_category.associations": _derived(sql=(("component_associations", "category_id"),)),
    "current_category.hazards": _derived(sql=(("hazards", "category_id"),)),
    "current_category.lifecycles": _derived(sql=(("lifecycle_records", "category_id"),)),
    "scope.flattened": _derived(sql=(
        ("lifecycle_records", "scope_kind"), ("lifecycle_records", "scope_id"),
        ("component_templates", "scope_kind"), ("component_templates", "scope_id"),
        ("hazards", "scope_kind"), ("hazards", "scope_id"),
    )),
    "lifecycle.resolution_tier": _derived(sql=(("lifecycle_records", "resolution_tier"),)),
    "identity_aliases.ordinal": _derived(sql=(("identity_aliases", "ordinal"),)),
    "identity_aliases.casefold": _derived(sql=(("identity_aliases", "alias_casefold"),)),
    "identity_tokens.ordinal": _derived(sql=(("identity_tokens", "ordinal"),)),
    "identity_tokens.casefold": _derived(sql=(("identity_tokens", "token_casefold"),)),
    "identity_variants.ordinal": _derived(sql=(("identity_variants", "ordinal"),)),
    "lifecycle_required_variants.ordinal": _derived(sql=(("lifecycle_required_variants", "ordinal"),)),
    "lifecycle_excluded_variants.ordinal": _derived(sql=(("lifecycle_excluded_variants", "ordinal"),)),
    "lifecycle_assumptions.ordinal": _derived(sql=(("lifecycle_assumptions", "ordinal"),)),
    "lifecycle_limitations.ordinal": _derived(sql=(("lifecycle_limitations", "ordinal"),)),
    "component_association_notes.ordinal": _derived(sql=(("component_association_notes", "ordinal"),)),
    "hazard_triggers.ordinal": _derived(sql=(("hazard_triggers", "ordinal"),)),
    "hazard_actions.action_kind": _derived(sql=(("hazard_actions", "action_kind"),)),
    "hazard_actions.ordinal": _derived(sql=(("hazard_actions", "ordinal"),)),
    "policy_predicates.group": _derived(sql=(("policy_predicates", "predicate_group"),)),
    "policy_predicates.ordinal": _derived(sql=(("policy_predicates", "ordinal"),)),
    "claim_sources.claim_kind": _derived(sql=(("claim_sources", "claim_kind"),)),
    "claim_sources.category_key": _derived(sql=(("claim_sources", "category_key"),)),
    "claim_sources.claim_id": _derived(sql=(("claim_sources", "claim_id"),)),
    "claim_sources.ordinal": _derived(sql=(("claim_sources", "ordinal"),)),
    "coverage.schema_version": _derived(coverage=(("top", "schema_version"),)),
    "coverage.summary_object": _derived(coverage=(("top", "summary"),)),
    "coverage.claims_array": _derived(coverage=(("top", "claims"),)),
    "coverage.reviewed_state": _derived(coverage=(("claim", "source_state"),)),
    "coverage.reviewed_category": _derived(coverage=(("claim", "category_id"),)),
    "coverage.reviewed_claim_kind": _derived(coverage=(("claim", "claim_kind"),)),
    "coverage.reviewed_reason_null": _derived(coverage=(("claim", "unknown_reason"),)),
    "coverage.unknown_state": _derived(coverage=(("claim", "source_state"),)),
    "coverage.unknown_evidence_null": _derived(coverage=(("claim", "evidence_level"),)),
    "coverage.unknown_sources_empty": _derived(coverage=(("claim", "source_ids"),)),
    **{
        f"coverage.summary.{field}": _derived(coverage=(("summary", field),))
        for field in (
            "categories", "canonical_identities", "subtypes", "lifecycle_records",
            "industry_averages", "component_templates", "modern_overlays",
            "legacy_overlays", "hazard_records", "reviewed_claims", "unknown_claims",
        )
    },
}

EXPECTED_DERIVED_TARGET_NAMES = frozenset(
    {
        "metadata.semantic_keys",
        "metadata.content_sha256",
        "metadata.coverage_sha256",
        "category.release_order",
        "current_category.components",
        "current_category.templates",
        "current_category.associations",
        "current_category.hazards",
        "current_category.lifecycles",
        "scope.flattened",
        "lifecycle.resolution_tier",
        "identity_aliases.ordinal",
        "identity_aliases.casefold",
        "identity_tokens.ordinal",
        "identity_tokens.casefold",
        "identity_variants.ordinal",
        "lifecycle_required_variants.ordinal",
        "lifecycle_excluded_variants.ordinal",
        "lifecycle_assumptions.ordinal",
        "lifecycle_limitations.ordinal",
        "component_association_notes.ordinal",
        "hazard_triggers.ordinal",
        "hazard_actions.action_kind",
        "hazard_actions.ordinal",
        "policy_predicates.group",
        "policy_predicates.ordinal",
        "claim_sources.claim_kind",
        "claim_sources.category_key",
        "claim_sources.claim_id",
        "claim_sources.ordinal",
        "coverage.schema_version",
        "coverage.summary_object",
        "coverage.claims_array",
        "coverage.reviewed_state",
        "coverage.reviewed_category",
        "coverage.reviewed_claim_kind",
        "coverage.reviewed_reason_null",
        "coverage.unknown_state",
        "coverage.unknown_evidence_null",
        "coverage.unknown_sources_empty",
    }
    | {
        f"coverage.summary.{field}"
        for _section, field in _COVERAGE_SUMMARY_FIELDS
    }
)


def _wire(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        return float(value)
    return value


def _normalized_search_key(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).strip().split()).casefold()


def expected_normalized_sql_rows(
    documents: EvidenceDocuments,
) -> dict[str, tuple[tuple[object, ...], ...]]:
    """Independently traverse every normalized record and authored child list."""
    rows: dict[str, list[tuple[object, ...]]] = {table: [] for table in TABLE_ORDER}
    bundle = documents.shared.bundle
    rows["metadata"].extend(
        [
            ("schema_version", str(bundle.schema_version)),
            ("bundle_version", bundle.bundle_version),
            ("identity_catalog_version", bundle.identity_catalog_version),
            ("policy_revision", bundle.policy_revision),
        ]
    )

    def source_row(record: object) -> tuple[object, ...]:
        return tuple(
            _wire(getattr(record, field))
            for field in EXPECTED_TABLE_COLUMNS["sources"]
        )

    for source in documents.shared.sources:
        rows["sources"].append(source_row(source))

    def claim_sources(
        kind: str, category_key: str, claim_id: str, source_ids: tuple[str, ...]
    ) -> None:
        for ordinal, source_id in enumerate(source_ids):
            rows["claim_sources"].append(
                (kind, category_key, claim_id, ordinal, source_id)
            )

    for policy in documents.shared.policies:
        rows["policy_rules"].append(
            (
                policy.rule_id,
                policy.priority,
                policy.outcome.value,
                policy.rationale,
                policy.evidence_level.value,
            )
        )
        for ordinal, predicate in enumerate(policy.when_all):
            rows["policy_predicates"].append(
                (policy.rule_id, "all", ordinal, predicate)
            )
        for ordinal, predicate in enumerate(policy.when_any):
            rows["policy_predicates"].append(
                (policy.rule_id, "any", ordinal, predicate)
            )
        claim_sources("policy", "", policy.rule_id, policy.source_ids)

    tier_for_scope = {
        "model": "exact_model",
        "family": "family",
        "subtype": "subtype",
        "category": "industry_average",
    }

    def lifecycle_base(record: object, category_id: str) -> tuple[object, ...]:
        return (
            record.record_id,
            category_id,
            tier_for_scope[record.scope.kind.value],
            record.scope.kind.value,
            record.scope.id,
            record.subject,
            record.endpoint,
            record.endpoint_kind.value,
            record.metric,
            record.unit,
            float(record.lower_bound),
            float(record.upper_bound),
            record.endpoint_qualification,
            _wire(record.applicable_from),
            _wire(record.applicable_to),
            record.model_year_from,
            record.model_year_to,
            record.precedence,
            record.evidence_level.value,
        )

    def lifecycle_children(record: object) -> None:
        for ordinal, variant_id in enumerate(record.required_variant_ids):
            rows["lifecycle_required_variants"].append(
                (record.record_id, ordinal, variant_id)
            )
        for ordinal, variant_id in enumerate(record.excluded_variant_ids):
            rows["lifecycle_excluded_variants"].append(
                (record.record_id, ordinal, variant_id)
            )
        for ordinal, assumption in enumerate(record.assumptions):
            rows["lifecycle_assumptions"].append(
                (record.record_id, ordinal, assumption)
            )

    for category in documents.categories:
        category_id = category.category.category_id
        rows["categories"].append(
            (
                category_id,
                category.category.display_name,
                CATEGORY_RELEASE_ORDER[category_id],
            )
        )
        for source in category.sources:
            rows["sources"].append(source_row(source))
        for subtype in category.subtypes:
            rows["subtypes"].append(
                (
                    subtype.subtype_id,
                    subtype.category_id,
                    subtype.display_name,
                    subtype.market_state.value,
                    subtype.battery_architecture.value,
                    subtype.evidence_level.value,
                )
            )
            claim_sources("subtype", category_id, subtype.subtype_id, subtype.source_ids)
        for variant in category.variants:
            rows["variants"].append(
                (
                    variant.variant_id,
                    variant.category_id,
                    variant.subtype_id,
                    variant.display_name,
                    variant.battery_architecture.value,
                    variant.evidence_level.value,
                )
            )
            claim_sources("variant", category_id, variant.variant_id, variant.source_ids)
        for identity in category.identities:
            rows["identities"].append(
                (
                    identity.identity_id,
                    identity.identity_kind.value,
                    identity.category_id,
                    identity.subtype_id,
                    identity.manufacturer_id,
                    identity.manufacturer_name,
                    identity.family_id,
                    identity.family_name,
                    identity.model_id,
                    identity.model_name,
                    identity.display_name,
                    identity.model_year_from,
                    identity.model_year_to,
                    _wire(identity.applicable_from),
                    _wire(identity.applicable_to),
                    identity.market_state.value,
                    identity.battery_architecture.value,
                    identity.evidence_level.value,
                )
            )
            for ordinal, alias in enumerate(identity.aliases):
                rows["identity_aliases"].append(
                    (identity.identity_id, ordinal, alias, _normalized_search_key(alias))
                )
            for ordinal, token in enumerate(identity.distinguishing_tokens):
                rows["identity_tokens"].append(
                    (identity.identity_id, ordinal, token, _normalized_search_key(token))
                )
            for ordinal, variant_id in enumerate(identity.variant_ids):
                rows["identity_variants"].append(
                    (identity.identity_id, ordinal, variant_id)
                )
            claim_sources("identity", category_id, identity.identity_id, identity.source_ids)
        for lifecycle in category.specific_lifecycles:
            rows["lifecycle_records"].append(lifecycle_base(lifecycle, category_id))
            lifecycle_children(lifecycle)
            claim_sources(
                "specific_lifecycle", category_id, lifecycle.record_id, lifecycle.source_ids
            )
        for average in category.industry_averages:
            rows["lifecycle_records"].append(lifecycle_base(average, category_id))
            lifecycle_children(average)
            rows["industry_averages"].append(
                (
                    average.record_id,
                    average.population_definition,
                    average.publication_period,
                    average.methodology,
                    average.uncertainty,
                )
            )
            for ordinal, limitation in enumerate(average.limitations):
                rows["lifecycle_limitations"].append(
                    (average.record_id, ordinal, limitation)
                )
            claim_sources(
                "industry_average", category_id, average.record_id, average.source_ids
            )
        for component in category.component_definitions:
            rows["components"].append(
                (category_id, component.component_id, component.display_name)
            )
        for template in category.component_templates:
            rows["component_templates"].append(
                (
                    template.template_id,
                    category_id,
                    template.template_kind.value,
                    template.scope.kind.value,
                    template.scope.id,
                    template.application_order,
                )
            )
        for association in category.component_associations:
            rows["component_associations"].append(
                (
                    association.association_id,
                    category_id,
                    association.template_id,
                    association.component_id,
                    association.position,
                    association.status.value,
                    association.applicability,
                    _wire(association.evidence_level),
                )
            )
            for ordinal, note in enumerate(association.notes):
                rows["component_association_notes"].append(
                    (association.association_id, ordinal, note)
                )
            claim_sources(
                "component_association",
                category_id,
                association.association_id,
                association.source_ids,
            )
        for hazard in category.hazards:
            rows["hazards"].append(
                (
                    hazard.hazard_id,
                    category_id,
                    hazard.component_id,
                    hazard.scope.kind.value,
                    hazard.scope.id,
                    hazard.applicability,
                    hazard.severity.value,
                    hazard.evidence_level.value,
                )
            )
            for ordinal, trigger in enumerate(hazard.trigger_observation_keys):
                rows["hazard_triggers"].append(
                    (hazard.hazard_id, ordinal, trigger)
                )
            for kind, actions in (
                ("immediate", hazard.immediate_actions),
                ("follow_up", hazard.follow_up_actions),
                ("handling", hazard.handling_guidance),
                ("disposal", hazard.disposal_guidance),
            ):
                for ordinal, action in enumerate(actions):
                    rows["hazard_actions"].append(
                        (hazard.hazard_id, kind, ordinal, action)
                    )
            claim_sources("hazard", category_id, hazard.hazard_id, hazard.source_ids)
        for unknown in category.unknowns:
            rows["coverage_unknowns"].append(
                (
                    unknown.category_id,
                    unknown.claim_kind.value,
                    unknown.claim_id,
                    unknown.reason,
                    unknown.evidence_request,
                )
            )

    result: dict[str, tuple[tuple[object, ...], ...]] = {}
    for table in TABLE_ORDER:
        columns = EXPECTED_TABLE_COLUMNS[table]
        positions = tuple(columns.index(column) for column in EXPECTED_PRIMARY_KEY_COLUMNS[table])
        result[table] = tuple(
            sorted(rows[table], key=lambda row, pos=positions: tuple(row[i] for i in pos))
        )
    return result


def expected_logical_payload(
    rows: Mapping[str, tuple[tuple[object, ...], ...]],
) -> dict[str, object]:
    tables = []
    for table in TABLE_ORDER:
        table_rows = rows[table]
        if table == "metadata":
            table_rows = tuple(
                row
                for row in table_rows
                if row[0] not in {"content_sha256", "coverage_sha256"}
            )
        tables.append(
            {
                "name": table,
                "columns": list(EXPECTED_TABLE_COLUMNS[table]),
                "rows": [list(row) for row in table_rows],
            }
        )
    return {"format": "ewaste-knowledge-logical-v1", "tables": tables}


def read_normalized_sql_rows(
    database: Path,
) -> dict[str, tuple[tuple[object, ...], ...]]:
    actual: dict[str, tuple[tuple[object, ...], ...]] = {}
    uri = f"file:{database}?mode=ro&immutable=1"
    with sqlite3.connect(uri, uri=True) as connection:
        for table in TABLE_ORDER:
            columns = EXPECTED_TABLE_COLUMNS[table]
            order = EXPECTED_PRIMARY_KEY_COLUMNS[table]
            query = (
                f'SELECT {", ".join(columns)} FROM "{table}" '
                f'ORDER BY {", ".join(order)}'
            )
            table_rows = tuple(connection.execute(query))
            if table == "metadata":
                table_rows = tuple(
                    row
                    for row in table_rows
                    if row[0] not in {"content_sha256", "coverage_sha256"}
                )
            actual[table] = table_rows
    return actual


def _metadata(database: Path) -> dict[str, str]:
    with sqlite3.connect(f"file:{database}?mode=ro&immutable=1", uri=True) as connection:
        return dict(connection.execute("SELECT key, value FROM metadata ORDER BY key"))


def _snapshot_tree(path: Path) -> dict[str, bytes | None]:
    if not path.exists():
        return {}
    return {
        str(item.relative_to(path)): None if item.is_dir() else item.read_bytes()
        for item in sorted(path.rglob("*"))
    }


@pytest.fixture
def source_and_documents(tmp_path: Path) -> tuple[Path, EvidenceDocuments]:
    source = make_valid_knowledge_source(tmp_path / "source")
    return source, load_evidence_documents(source)


def test_projection_matches_independent_oracle_for_all_26_tables_and_145_columns(
    source_and_documents: tuple[Path, EvidenceDocuments],
) -> None:
    _source, documents = source_and_documents
    expected = expected_normalized_sql_rows(documents)

    assert len(TABLE_ORDER) == 26
    assert sum(map(len, EXPECTED_TABLE_COLUMNS.values())) == 145
    assert tuple(expected) == TABLE_ORDER
    assert normalized_sql_rows(documents) == expected


def test_semantic_targets_are_exact_for_every_authored_derived_sql_and_coverage_field(
    source_and_documents: tuple[Path, EvidenceDocuments],
) -> None:
    source, _documents = source_and_documents
    expected_authoring_keys = {
        ("root", relative_path, field)
        for relative_path, fields in root_value_type_sets(source).items()
        for field in fields
    } | {
        ("record", record, field)
        for record, fields in record_field_type_sets(source).items()
        for field in fields
    }

    assert set(AUTHORING_FIELD_TARGETS) == expected_authoring_keys
    assert set(DERIVED_TARGETS) == EXPECTED_DERIVED_TARGET_NAMES
    assert all(
        sql_targets or coverage_targets
        for sql_targets, coverage_targets in AUTHORING_FIELD_TARGETS.values()
    )

    all_targets = tuple(AUTHORING_FIELD_TARGETS.values()) + tuple(
        DERIVED_TARGETS.values()
    )
    mapped_sql = {
        target
        for sql_targets, _coverage_targets in all_targets
        for target in sql_targets
    }
    mapped_coverage = {
        target
        for _sql_targets, coverage_targets in all_targets
        for target in coverage_targets
    }
    assert mapped_sql == {
        (table, column)
        for table, columns in EXPECTED_TABLE_COLUMNS.items()
        for column in columns
    }
    assert mapped_coverage == (
        _COVERAGE_TOP_FIELDS | _COVERAGE_SUMMARY_FIELDS | _COVERAGE_CLAIM_FIELDS
    )


def test_alias_and_token_keys_collapse_unicode_whitespace_but_retain_authored_text(
    tmp_path: Path,
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    category_id = RELEASED_CATEGORY_IDS[0]
    path = source / f"categories/{category_id}/identities.yaml"

    def add_unicode_whitespace(document: dict[str, object]) -> None:
        identity = document["identities"][0]
        identity["aliases"][0] = "Alias\u2003Value"
        identity["distinguishing_tokens"][0] = "Token\u2003Value"

    mutate_yaml(path, add_unicode_whitespace)
    documents = load_evidence_documents(source)
    rows = normalized_sql_rows(documents)
    identity_id = documents.categories[0].identities[0].identity_id
    alias_row = next(row for row in rows["identity_aliases"] if row[0] == identity_id)
    token_row = next(row for row in rows["identity_tokens"] if row[0] == identity_id)

    assert alias_row[2:] == ("Alias\u2003Value", "alias value")
    assert token_row[2:] == ("Token\u2003Value", "token value")
    assert rows == expected_normalized_sql_rows(documents)


_CATEGORY_COLLECTION_FOR_RECORD = {
    "subtype": "subtypes",
    "variant": "variants",
    "identity": "identities",
    "specific_lifecycle": "specific_lifecycles",
    "industry_average": "industry_averages",
    "component_association": "component_associations",
    "hazard": "hazards",
}


def _replace_first_authored_list(
    documents: EvidenceDocuments,
    record_name: str,
    field: str,
    values: tuple[object, ...],
) -> EvidenceDocuments:
    if record_name == "policy":
        policy = replace(documents.shared.policies[0], **{field: values})
        return replace(
            documents,
            shared=replace(
                documents.shared,
                policies=(policy, *documents.shared.policies[1:]),
            ),
        )
    collection_name = _CATEGORY_COLLECTION_FOR_RECORD[record_name]
    category = documents.categories[0]
    collection = getattr(category, collection_name)
    changed_record = replace(collection[0], **{field: values})
    changed_category = replace(
        category,
        **{collection_name: (changed_record, *collection[1:])},
    )
    return replace(
        documents,
        categories=(changed_category, *documents.categories[1:]),
    )


def _changed_sql_columns(
    before: Mapping[str, tuple[tuple[object, ...], ...]],
    after: Mapping[str, tuple[tuple[object, ...], ...]],
) -> frozenset[tuple[str, str]]:
    changed: set[tuple[str, str]] = set()
    for table in TABLE_ORDER:
        for index, column in enumerate(EXPECTED_TABLE_COLUMNS[table]):
            # Projection rows are already ordered by each table's declared PK.
            # Preserve that binding here: comparing an unordered bag of column
            # values would miss a coordinated swap between two authored rows.
            before_values = tuple(row[index] for row in before[table])
            after_values = tuple(row[index] for row in after[table])
            if before_values != after_values:
                changed.add((table, column))
    return frozenset(changed)


def _changed_report_fields(
    before: Mapping[str, object], after: Mapping[str, object]
) -> frozenset[tuple[str, str]]:
    changed: set[tuple[str, str]] = set()
    for field in ("schema_version", "bundle_version", "knowledge_content_sha256"):
        if before[field] != after[field]:
            changed.add(("top", field))
    if before["summary"] != after["summary"]:
        changed.add(("top", "summary"))
    if before["claims"] != after["claims"]:
        changed.add(("top", "claims"))
    for field in (value for section, value in _COVERAGE_SUMMARY_FIELDS if section == "summary"):
        if before["summary"][field] != after["summary"][field]:
            changed.add(("summary", field))
    for field in (value for section, value in _COVERAGE_CLAIM_FIELDS if section == "claim"):
        # Claims are canonically key-sorted. Preserve that row binding so a
        # reviewed/Unknown state swap cannot hide behind equal value bags.
        before_values = tuple(claim[field] for claim in before["claims"])
        after_values = tuple(claim[field] for claim in after["claims"])
        if before_values != after_values:
            changed.add(("claim", field))
    return frozenset(changed)


def _semantic_list_mutation_values(
    documents: EvidenceDocuments,
) -> dict[tuple[str, str], tuple[object, ...]]:
    category_id = documents.categories[0].category.category_id
    claim_source = f"{category_id}_claim_source"
    shared_source = "shared_process_source"
    first = documents.categories[0]
    values: dict[tuple[str, str], tuple[object, ...]] = {
        ("policy", "when_all"): tuple(sorted((*documents.shared.policies[0].when_all, "observations.age_months=present"))),
        ("policy", "when_any"): ("visible_condition.grade=good",),
        ("policy", "source_ids"): tuple(sorted((*documents.shared.policies[0].source_ids, shared_source))),
        ("subtype", "source_ids"): (claim_source, shared_source),
        ("variant", "source_ids"): (claim_source, shared_source),
        ("identity", "aliases"): (*first.identities[0].aliases, "Additional authored alias"),
        ("identity", "distinguishing_tokens"): (*first.identities[0].distinguishing_tokens, "additional authored token"),
        ("identity", "variant_ids"): first.identities[0].variant_ids[:-1],
        ("identity", "source_ids"): (claim_source, shared_source),
        ("specific_lifecycle", "required_variant_ids"): (
            *first.specific_lifecycles[0].required_variant_ids,
            f"{category_id}_variant_0b",
        ),
        ("specific_lifecycle", "excluded_variant_ids"): (f"{category_id}_variant_0b",),
        ("specific_lifecycle", "assumptions"): (*first.specific_lifecycles[0].assumptions, "Additional assumption"),
        ("specific_lifecycle", "source_ids"): (claim_source, shared_source),
        ("industry_average", "assumptions"): (*first.industry_averages[0].assumptions, "Additional population assumption"),
        ("industry_average", "limitations"): (*first.industry_averages[0].limitations, "Additional limitation."),
        ("industry_average", "source_ids"): (claim_source, shared_source),
        ("component_association", "notes"): (*first.component_associations[0].notes, "Additional association note."),
        ("component_association", "source_ids"): (claim_source, shared_source),
        ("hazard", "trigger_observation_keys"): tuple(sorted((*first.hazards[0].trigger_observation_keys, "observations.issue_flags.swelling_or_battery_damage"))),
        ("hazard", "immediate_actions"): (*first.hazards[0].immediate_actions, "Move away from the item."),
        ("hazard", "follow_up_actions"): (*first.hazards[0].follow_up_actions, "Document the incident."),
        ("hazard", "handling_guidance"): (*first.hazards[0].handling_guidance, "Isolate the item."),
        ("hazard", "disposal_guidance"): (*first.hazards[0].disposal_guidance, "Follow local disposal rules."),
        ("hazard", "source_ids"): tuple(sorted((*first.hazards[0].source_ids, shared_source))),
    }
    return values


def test_every_mutable_authored_list_has_exact_sql_coverage_targets_and_ordinals(
    source_and_documents: tuple[Path, EvidenceDocuments],
) -> None:
    source, documents = source_and_documents
    baseline_rows = expected_normalized_sql_rows(documents)
    baseline_hash = logical_content_sha256(baseline_rows)
    baseline_report = build_coverage(documents, baseline_hash)
    mutations = _semantic_list_mutation_values(documents)
    authored_lists = {
        (record, field)
        for record, fields in record_field_type_sets(source).items()
        for field, contract in fields.items()
        if contract.startswith(("list:", "nonempty_list:"))
    }
    validation_only_or_frozen = {
        ("bundle", "category_ids"),
        ("industry_average", "required_variant_ids"),
        ("industry_average", "excluded_variant_ids"),
        ("unknown", "source_ids"),
    }
    assert set(mutations) | validation_only_or_frozen == authored_lists
    assert not set(mutations) & validation_only_or_frozen

    for (record_name, field), values in mutations.items():
        changed_documents = _replace_first_authored_list(
            documents, record_name, field, values
        )
        expected_rows = expected_normalized_sql_rows(changed_documents)
        actual_rows = normalized_sql_rows(changed_documents)
        assert actual_rows == expected_rows, f"{record_name}.{field}"
        expected_sql, expected_coverage = AUTHORING_FIELD_TARGETS[
            ("record", record_name, field)
        ]
        assert _changed_sql_columns(baseline_rows, actual_rows) == expected_sql, (
            record_name,
            field,
        )
        changed_hash = logical_content_sha256(actual_rows)
        assert changed_hash != baseline_hash
        changed_report = build_coverage(changed_documents, changed_hash)
        assert _changed_report_fields(baseline_report, changed_report) == expected_coverage
        assert coverage_json_bytes(changed_report) != coverage_json_bytes(baseline_report)


def test_display_order_reordering_rebinds_each_value_to_its_zero_based_ordinal(
    source_and_documents: tuple[Path, EvidenceDocuments],
) -> None:
    _source, documents = source_and_documents
    cases = (
        ("identity", "aliases", "identity_aliases", "alias"),
        ("identity", "distinguishing_tokens", "identity_tokens", "token"),
        ("specific_lifecycle", "assumptions", "lifecycle_assumptions", "assumption"),
        ("industry_average", "limitations", "lifecycle_limitations", "limitation"),
        ("component_association", "notes", "component_association_notes", "note"),
        ("hazard", "immediate_actions", "hazard_actions", "action_text"),
        ("hazard", "follow_up_actions", "hazard_actions", "action_text"),
        ("hazard", "handling_guidance", "hazard_actions", "action_text"),
        ("hazard", "disposal_guidance", "hazard_actions", "action_text"),
    )
    for record_name, field, table, value_column in cases:
        category = documents.categories[0]
        collection = getattr(category, _CATEGORY_COLLECTION_FOR_RECORD[record_name])
        original = getattr(collection[0], field)
        assert len(original) >= 1
        values = tuple(reversed(original)) if len(original) > 1 else (*original, "Second authored value")
        changed = _replace_first_authored_list(documents, record_name, field, values)
        changed_category = changed.categories[0]
        changed_collection = getattr(
            changed_category, _CATEGORY_COLLECTION_FOR_RECORD[record_name]
        )
        owner_field = {
            "identity": "identity_id",
            "specific_lifecycle": "record_id",
            "industry_average": "record_id",
            "component_association": "association_id",
            "hazard": "hazard_id",
        }[record_name]
        owner = getattr(changed_collection[0], owner_field)
        rows = normalized_sql_rows(changed)[table]
        value_index = EXPECTED_TABLE_COLUMNS[table].index(value_column)
        ordinal_index = EXPECTED_TABLE_COLUMNS[table].index("ordinal")
        if table == "hazard_actions":
            action_kind = {
                "immediate_actions": "immediate",
                "follow_up_actions": "follow_up",
                "handling_guidance": "handling",
                "disposal_guidance": "disposal",
            }[field]
            rows = tuple(row for row in rows if row[1] == action_kind)
        owned_rows = tuple(row for row in rows if row[0] == owner)
        assert tuple(row[ordinal_index] for row in owned_rows) == tuple(range(len(values)))
        assert tuple(row[value_index] for row in owned_rows) == values
        assert normalized_sql_rows(changed) == expected_normalized_sql_rows(changed)


def _knowledge_document_paths() -> tuple[str, ...]:
    category_paths = (
        "sources.yaml",
        "identities.yaml",
        "lifecycles.yaml",
        "industry_averages.yaml",
        "components.yaml",
        "hazards.yaml",
        "coverage.yaml",
    )
    return (
        "bundle.yaml",
        "common/sources.yaml",
        "common/policies.yaml",
        *(
            f"categories/{category_id}/{name}"
            for category_id in RELEASED_CATEGORY_IDS
            for name in category_paths
        ),
    )


def _yaml_record_views(
    document: dict[str, object], relative_path: str
) -> tuple[tuple[str, tuple[object, ...], dict[str, object]], ...]:
    views: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def one(record_name: str, field: str) -> None:
        value = document[field]
        assert isinstance(value, dict)
        views.append((record_name, (field,), value))

    def many(record_name: str, field: str) -> None:
        value = document[field]
        assert isinstance(value, list)
        for index, item in enumerate(value):
            assert isinstance(item, dict)
            views.append((record_name, (field, index), item))

    if relative_path == "bundle.yaml":
        one("bundle", "bundle")
    elif relative_path.endswith("sources.yaml"):
        many("source", "sources")
    elif relative_path == "common/policies.yaml":
        many("policy", "policies")
    elif relative_path.endswith("identities.yaml"):
        one("category", "category")
        many("subtype", "subtypes")
        many("variant", "variants")
        many("identity", "identities")
    elif relative_path.endswith("lifecycles.yaml"):
        many("specific_lifecycle", "lifecycles")
    elif relative_path.endswith("industry_averages.yaml"):
        many("industry_average", "industry_averages")
    elif relative_path.endswith("components.yaml"):
        many("component_definition", "components")
        many("component_template", "templates")
        many("component_association", "associations")
    elif relative_path.endswith("hazards.yaml"):
        many("hazard", "hazards")
    elif relative_path.endswith("coverage.yaml"):
        many("unknown", "unknowns")
    for record_name, record_path, record in tuple(views):
        scope = record.get("scope")
        if isinstance(scope, dict):
            views.append(("scope", (*record_path, "scope"), scope))
    return tuple(views)


def _read_yaml_document(path: Path) -> dict[str, object]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _all_concrete_yaml_value_paths(
    source: Path,
) -> tuple[
    set[tuple[object, ...]],
    set[tuple[object, ...]],
]:
    concrete: set[tuple[object, ...]] = set()
    empty_lists: set[tuple[object, ...]] = set()
    for relative_path in _knowledge_document_paths():
        document = _read_yaml_document(source / relative_path)
        if relative_path == "common/policies.yaml":
            concrete.add((relative_path, "root", "policy_revision"))
        for record_name, record_path, record in _yaml_record_views(
            document, relative_path
        ):
            assert set(record) == set(AUTHORING_RECORD_FIELDS[record_name])
            for field, value in record.items():
                if isinstance(value, dict):
                    continue
                if isinstance(value, list):
                    if not value:
                        empty_lists.add(
                            (relative_path, *record_path, record_name, field, "empty")
                        )
                    for index in range(len(value)):
                        concrete.add(
                            (relative_path, *record_path, record_name, field, index)
                        )
                else:
                    concrete.add((relative_path, *record_path, record_name, field))
    return concrete, empty_lists


def _atomic_contract(contract: str) -> str:
    for prefix in ("nullable:", "nonempty_list:", "list:"):
        if contract.startswith(prefix):
            return contract.removeprefix(prefix)
    return contract


def _transform_valid_fixture(
    source: Path,
) -> tuple[set[tuple[object, ...]], set[tuple[object, ...]]]:
    baseline_entries = _concrete_yaml_entries(source)
    contracts = record_field_type_sets(source)
    id_map: dict[str, str] = {}
    fixed_id_fields = {"category_id", "subject", "endpoint", "metric", "unit"}
    for relative_path in _knowledge_document_paths():
        document = _read_yaml_document(source / relative_path)
        for record_name, _record_path, record in _yaml_record_views(
            document, relative_path
        ):
            for field, value in record.items():
                contract = contracts[record_name][field]
                if _atomic_contract(contract) != "id" or field in fixed_id_fields:
                    continue
                values = value if isinstance(value, list) else [value]
                for item in values:
                    if isinstance(item, str) and item not in RELEASED_CATEGORY_IDS:
                        id_map.setdefault(item, item + "_v2")

    changed_paths: set[tuple[object, ...]] = set()
    frozen_paths: set[tuple[object, ...]] = set()
    outcome_map = {
        "reuse": "repair",
        "more_information_needed": "certified_recycling",
    }
    battery_map = {
        "battery_free": "battery_bearing",
        "battery_bearing": "battery_free",
    }
    trigger_map = {
        "observations.issue_flags.odor": "observations.issue_flags.recall",
        "observations.issue_flags.overheating": (
            "observations.issue_flags.swelling_or_battery_damage"
        ),
    }
    predicate_map = {
        "identity.state=canonical": "visible_condition.grade=good",
        "identity.state=unknown": "visible_condition.grade=unknown",
    }

    def transform_value(
        record_name: str, field: str, value: object, contract: str
    ) -> object:
        atomic = _atomic_contract(contract)
        if value is None:
            return value
        if atomic == "id":
            if field in fixed_id_fields or value in RELEASED_CATEGORY_IDS:
                return value
            assert isinstance(value, str)
            return id_map[value]
        if atomic == "text":
            assert isinstance(value, str)
            return value + " [amended]"
        if atomic == "https_url":
            assert isinstance(value, str)
            return value + "/amended"
        if atomic == "date":
            assert isinstance(value, str)
            return (date.fromisoformat(value) - timedelta(days=1)).isoformat()
        if atomic == "number":
            assert type(value) in {int, float}
            return float(value) * 2.0
        if atomic == "int":
            if field in {"priority", "precedence"}:
                assert type(value) is int
                return value + 10
            if field in {"model_year_from", "model_year_to"}:
                assert type(value) is int
                return value + 1
            return value
        if atomic == "policy_predicate":
            return predicate_map.get(str(value), value)
        if atomic == "hazard_trigger_key":
            return trigger_map.get(str(value), value)
        if atomic == "enum:RecommendationValue":
            return outcome_map.get(str(value), value)
        if atomic == "enum:BatteryArchitecture":
            return battery_map[str(value)]
        if atomic == "enum:HazardSeverity":
            return "caution" if value != "caution" else "advisory"
        return value

    for relative_path in _knowledge_document_paths():
        path = source / relative_path

        def mutate(document: dict[str, object], rel: str = relative_path) -> None:
            for record_name, record_path, record in _yaml_record_views(document, rel):
                for field, value in tuple(record.items()):
                    if isinstance(value, dict):
                        continue
                    contract = contracts[record_name][field]
                    if isinstance(value, list):
                        changed_values = [
                            transform_value(record_name, field, item, contract)
                            for item in value
                        ]
                        if field in {
                            "category_ids", "source_ids", "variant_ids",
                            "required_variant_ids", "excluded_variant_ids", "when_all",
                            "when_any", "trigger_observation_keys",
                        }:
                            changed_values.sort()
                        record[field] = changed_values
                        for index, (before, after) in enumerate(
                            zip(value, changed_values, strict=True)
                        ):
                            target = (rel, *record_path, record_name, field, index)
                            (changed_paths if before != after else frozen_paths).add(target)
                    else:
                        changed = transform_value(record_name, field, value, contract)
                        record[field] = changed
                        target = (rel, *record_path, record_name, field)
                        (changed_paths if value != changed else frozen_paths).add(target)

        mutate_yaml(path, mutate)

    market_state_map = {
        "current": "discontinued",
        "discontinued": "legacy",
        "legacy": "current",
    }
    for category_id in RELEASED_CATEGORY_IDS:
        identities_path = source / f"categories/{category_id}/identities.yaml"

        def mutate_identities(document: dict[str, object]) -> None:
            for subtype in document["subtypes"]:
                subtype["market_state"] = market_state_map[subtype["market_state"]]
            for identity in document["identities"]:
                identity["market_state"] = market_state_map[identity["market_state"]]

        mutate_yaml(identities_path, mutate_identities)

        lifecycles_path = source / f"categories/{category_id}/lifecycles.yaml"

        def mutate_lifecycles(document: dict[str, object]) -> None:
            endpoint_cases = (
                ("service_duration", "operating_endurance"),
                ("cycle_endurance", "operating_endurance"),
                ("service_life", "total_life"),
            )
            for index, lifecycle in enumerate(document["lifecycles"]):
                endpoint, endpoint_kind = endpoint_cases[index]
                lifecycle["endpoint"] = endpoint
                lifecycle["endpoint_kind"] = endpoint_kind
                for field in ("subject", "metric", "unit"):
                    lifecycle[field] = lifecycle[field] + "_v2"
                if lifecycle["applicable_from"] is None:
                    lifecycle["applicable_from"] = "2021-01-01"
                if lifecycle["applicable_to"] is None:
                    lifecycle["applicable_to"] = "2022-01-01"
                if lifecycle["model_year_from"] is None:
                    lifecycle["model_year_from"] = 2021
                if lifecycle["model_year_to"] is None:
                    lifecycle["model_year_to"] = 2022

        mutate_yaml(lifecycles_path, mutate_lifecycles)

        components_path = source / f"categories/{category_id}/components.yaml"

        def mutate_components(document: dict[str, object]) -> None:
            templates = document["templates"]
            templates[0]["application_order"] = 1
            templates[1]["application_order"] = 1
            reviewed_status = {
                "legacy_specific": "conditional",
                "commonly_associated": "conditional",
                "conditional": "commonly_associated",
                "exact_model_confirmed": "not_present",
                "not_present": "commonly_associated",
            }
            for association in document["associations"]:
                status = association["status"]
                if status != "unknown":
                    association["status"] = reviewed_status[status]

        mutate_yaml(components_path, mutate_components)

        hazards_path = source / f"categories/{category_id}/hazards.yaml"

        def mutate_hazards(document: dict[str, object]) -> None:
            for hazard in document["hazards"]:
                hazard["evidence_level"] = "C"

        mutate_yaml(hazards_path, mutate_hazards)

    mutate_yaml(
        source / "common/policies.yaml",
        lambda document: [
            policy.__setitem__("evidence_level", "C")
            for policy in document["policies"]
        ],
    )

    transformed_entries = _concrete_yaml_entries(source)
    assert set(transformed_entries) == set(baseline_entries)
    changed_paths = {
        path
        for path, entry in baseline_entries.items()
        if entry[-1] != transformed_entries[path][-1]
    }
    frozen_paths = set(baseline_entries) - changed_paths
    frozen_paths.add(("common/policies.yaml", "root", "policy_revision"))
    return changed_paths, frozen_paths


def test_every_concrete_mutable_yaml_value_survives_valid_coordinated_transformation(
    tmp_path: Path,
) -> None:
    baseline_source = make_valid_knowledge_source(tmp_path / "baseline")
    changed_source = tmp_path / "changed"
    shutil.copytree(baseline_source, changed_source)
    all_paths, empty_paths = _all_concrete_yaml_value_paths(baseline_source)
    changed_paths, frozen_paths = _transform_valid_fixture(changed_source)

    assert changed_paths | frozen_paths == all_paths
    assert not changed_paths & frozen_paths
    assert (len(all_paths), len(changed_paths), len(frozen_paths), len(empty_paths)) == (
        2637,
        2132,
        505,
        62,
    )

    baseline_documents = load_evidence_documents(baseline_source)
    changed_documents = load_evidence_documents(changed_source)
    baseline_expected = expected_normalized_sql_rows(baseline_documents)
    changed_expected = expected_normalized_sql_rows(changed_documents)
    baseline_actual = normalized_sql_rows(baseline_documents)
    changed_actual = normalized_sql_rows(changed_documents)
    assert baseline_actual == baseline_expected
    assert changed_actual == changed_expected
    assert _changed_sql_columns(baseline_actual, changed_actual) == (
        _changed_sql_columns(baseline_expected, changed_expected)
    )

    baseline_hash = logical_content_sha256(baseline_expected)
    changed_hash = logical_content_sha256(changed_expected)
    assert changed_hash != baseline_hash
    baseline_expected_report = expected_coverage_report(
        baseline_documents, baseline_hash
    )
    changed_expected_report = expected_coverage_report(changed_documents, changed_hash)
    baseline_actual_report = build_coverage(baseline_documents, baseline_hash)
    changed_actual_report = build_coverage(changed_documents, changed_hash)
    assert baseline_actual_report == baseline_expected_report
    assert changed_actual_report == changed_expected_report
    assert _changed_report_fields(
        baseline_actual_report, changed_actual_report
    ) == _changed_report_fields(baseline_expected_report, changed_expected_report)
    assert coverage_json_bytes(changed_actual_report) != coverage_json_bytes(
        baseline_actual_report
    )


def _concrete_yaml_entries(
    source: Path,
) -> dict[
    tuple[object, ...],
    tuple[str, tuple[object, ...], str, str, object],
]:
    entries: dict[
        tuple[object, ...],
        tuple[str, tuple[object, ...], str, str, object],
    ] = {}
    for relative_path in _knowledge_document_paths():
        document = _read_yaml_document(source / relative_path)
        for record_name, record_path, record in _yaml_record_views(
            document, relative_path
        ):
            for field, value in record.items():
                if isinstance(value, dict):
                    continue
                if isinstance(value, list):
                    for index, item in enumerate(value):
                        path = (
                            relative_path,
                            *record_path,
                            record_name,
                            field,
                            index,
                        )
                        entries[path] = (
                            relative_path,
                            (*record_path, field, index),
                            record_name,
                            field,
                            item,
                        )
                else:
                    path = (relative_path, *record_path, record_name, field)
                    entries[path] = (
                        relative_path,
                        (*record_path, field),
                        record_name,
                        field,
                        value,
                    )
    return entries


def _concrete_yaml_record_contexts(
    source: Path,
) -> dict[tuple[object, ...], Mapping[str, object]]:
    """Index each scalar/list-item path to its containing raw YAML record."""
    contexts: dict[tuple[object, ...], Mapping[str, object]] = {}
    for relative_path in _knowledge_document_paths():
        document = _read_yaml_document(source / relative_path)
        if relative_path == "common/policies.yaml":
            contexts[(relative_path, "root", "policy_revision")] = document
        for record_name, record_path, record in _yaml_record_views(
            document, relative_path
        ):
            for field, value in record.items():
                if isinstance(value, dict):
                    continue
                if isinstance(value, list):
                    for index in range(len(value)):
                        contexts[
                            (
                                relative_path,
                                *record_path,
                                record_name,
                                field,
                                index,
                            )
                        ] = record
                else:
                    contexts[
                        (relative_path, *record_path, record_name, field)
                    ] = record
    return contexts


def _semantic_mutation_group(
    path: tuple[object, ...],
    entry: tuple[str, tuple[object, ...], str, str, object],
    contract: str,
) -> tuple[object, ...]:
    relative_path, navigation, record_name, field, value = entry
    atomic = _atomic_contract(contract)
    record_navigation = navigation[:-2] if isinstance(navigation[-1], int) else navigation[:-1]
    category_id = (
        relative_path.split("/")[1]
        if relative_path.startswith("categories/")
        else None
    )
    if relative_path.endswith("components.yaml") and (
        (record_name == "component_template" and field in {
            "template_kind", "application_order",
        })
        or (record_name == "component_association" and field in {
            "status", "evidence_level",
        })
    ):
        return ("category-polymorphic-shape", category_id)
    if relative_path.endswith("lifecycles.yaml") and (
        (record_name == "specific_lifecycle" and field in {"endpoint", "endpoint_kind"})
    ):
        return ("lifecycle-endpoint", relative_path, *record_navigation)
    if atomic in {"id", "text", "date"}:
        return (atomic, value)
    if atomic in {"https_url", "policy_predicate", "enum:RecommendationValue", "enum:HazardSeverity"}:
        return (atomic, *path)
    if atomic == "number":
        return ("lifecycle-range", relative_path, *record_navigation)
    if atomic == "int":
        if field in {"model_year_from", "model_year_to"}:
            return ("year-range", relative_path, *record_navigation)
        if field == "priority":
            return ("policy-priorities",)
        if field == "precedence":
            return ("lifecycle-precedence", relative_path)
    if atomic == "hazard_trigger_key":
        return ("hazard-triggers", relative_path, *record_navigation)
    if atomic == "enum:BatteryArchitecture":
        return ("battery-architecture",)
    if atomic in {
        "enum:AssociationStatus",
        "enum:EvidenceLevel",
        "enum:IdentityKind",
        "enum:LifecycleEndpointKind",
        "enum:MarketState",
        "enum:ScopeKind",
        "enum:TemplateKind",
    }:
        return (atomic, *path)
    raise AssertionError((path, contract, value))


def _set_yaml_navigation(
    document: dict[str, object], navigation: tuple[object, ...], value: object
) -> None:
    current: object = document
    for component in navigation[:-1]:
        current = current[component]
    current[navigation[-1]] = deepcopy(value)


def targets_for_concrete_paths(
    value_paths: frozenset[tuple[object, ...]],
    record_contexts: Mapping[tuple[object, ...], Mapping[str, object]],
) -> tuple[frozenset[tuple[str, str]], frozenset[tuple[str, str]]]:
    """Declare exact value-replacement targets without consulting either oracle."""
    sql: set[tuple[str, str]] = set()
    coverage: set[tuple[str, str]] = set()
    claim_id_field = {
        "subtype": "subtype_id",
        "variant": "variant_id",
        "identity": "identity_id",
        "specific_lifecycle": "record_id",
        "industry_average": "record_id",
        "component_association": "association_id",
        "hazard": "hazard_id",
    }
    for path in value_paths:
        record = record_contexts[path]
        relative_path = str(path[0])
        if isinstance(path[-1], int):
            record_name, field = str(path[-3]), str(path[-2])
        else:
            record_name, field = str(path[-2]), str(path[-1])
        table = _RECORD_TABLE.get(record_name)
        if table is not None and field in EXPECTED_TABLE_COLUMNS[table]:
            sql.add((table, field))
        if record_name == "bundle" and field != "category_ids":
            sql.add(("metadata", "value"))
            if field == "bundle_version":
                coverage.add(("top", "bundle_version"))
        if record_name == "policy":
            if field in {"when_all", "when_any"}:
                sql.add(("policy_predicates", "predicate"))
            if field == "rule_id":
                if record["when_all"] or record["when_any"]:
                    sql.add(("policy_predicates", "rule_id"))
                if record["source_ids"]:
                    sql.add(("claim_sources", "claim_id"))
            if field == "source_ids":
                sql.add(("claim_sources", "source_id"))
        if record_name == "identity":
            if field == "identity_id":
                for child_field, child_table in (
                    ("aliases", "identity_aliases"),
                    ("distinguishing_tokens", "identity_tokens"),
                    ("variant_ids", "identity_variants"),
                ):
                    if record[child_field]:
                        sql.add((child_table, "identity_id"))
            if field == "aliases":
                sql |= {
                    ("identity_aliases", "alias"),
                    ("identity_aliases", "alias_casefold"),
                }
            if field == "distinguishing_tokens":
                sql |= {
                    ("identity_tokens", "token"),
                    ("identity_tokens", "token_casefold"),
                }
            if field == "variant_ids":
                sql.add(("identity_variants", "variant_id"))
        if record_name in {"specific_lifecycle", "industry_average"}:
            if field == "record_id":
                for child_field, child_table in (
                    ("required_variant_ids", "lifecycle_required_variants"),
                    ("excluded_variant_ids", "lifecycle_excluded_variants"),
                    ("assumptions", "lifecycle_assumptions"),
                ):
                    if record[child_field]:
                        sql.add((child_table, "record_id"))
                if record_name == "industry_average":
                    sql.add(("industry_averages", "record_id"))
                    if record["limitations"]:
                        sql.add(("lifecycle_limitations", "record_id"))
            child_value_target = {
                "required_variant_ids": ("lifecycle_required_variants", "variant_id"),
                "excluded_variant_ids": ("lifecycle_excluded_variants", "variant_id"),
                "assumptions": ("lifecycle_assumptions", "assumption"),
            }.get(field)
            if child_value_target is not None:
                sql.add(child_value_target)
            if (
                record_name == "industry_average"
                and field in EXPECTED_TABLE_COLUMNS["industry_averages"]
            ):
                sql.add(("industry_averages", field))
            if record_name == "industry_average" and field == "limitations":
                sql.add(("lifecycle_limitations", "limitation"))
        if record_name == "component_association":
            if field == "association_id":
                if record["notes"]:
                    sql.add(("component_association_notes", "association_id"))
            if field == "notes":
                sql.add(("component_association_notes", "note"))
        if record_name == "hazard":
            if field == "hazard_id":
                if record["trigger_observation_keys"]:
                    sql.add(("hazard_triggers", "hazard_id"))
                if any(
                    record[action_field]
                    for action_field in (
                        "immediate_actions",
                        "follow_up_actions",
                        "handling_guidance",
                        "disposal_guidance",
                    )
                ):
                    sql.add(("hazard_actions", "hazard_id"))
            if field == "trigger_observation_keys":
                sql.add(("hazard_triggers", "observation_key"))
            if field in {
                "immediate_actions", "follow_up_actions", "handling_guidance",
                "disposal_guidance",
            }:
                sql.add(("hazard_actions", "action_text"))
        if record_name == "scope" and field in {"kind", "id"}:
            scope_table = (
                "lifecycle_records"
                if relative_path.endswith(("lifecycles.yaml", "industry_averages.yaml"))
                else "component_templates"
                if relative_path.endswith("components.yaml")
                else "hazards"
            )
            sql.add((scope_table, "scope_kind" if field == "kind" else "scope_id"))
            if scope_table == "lifecycle_records" and field == "kind":
                sql.add((scope_table, "resolution_tier"))

        if record_name in claim_id_field:
            if field == claim_id_field[record_name]:
                if record["source_ids"]:
                    sql.add(("claim_sources", "claim_id"))
                coverage.add(("claim", "claim_id"))
            if field == "evidence_level":
                coverage.add(("claim", "evidence_level"))
            if field == "source_ids":
                sql.add(("claim_sources", "source_id"))
                coverage.add(("claim", "source_ids"))
        if record_name == "unknown":
            unknown_field = {
                "category_id": "category_id",
                "claim_kind": "claim_kind",
                "claim_id": "claim_id",
                "reason": "unknown_reason",
            }.get(field)
            if unknown_field is not None:
                coverage.add(("claim", unknown_field))
        if sql:
            coverage.add(("top", "knowledge_content_sha256"))
    if any(section == "claim" for section, _field in coverage):
        coverage.add(("top", "claims"))
    return frozenset(sql), frozenset(coverage)


def semantic_authoring_mutations(
    baseline_source: Path, transformed_source: Path
) -> tuple[
    tuple[str, frozenset[tuple[object, ...]], tuple[tuple[str, tuple[object, ...], object], ...]],
    ...,
]:
    baseline_entries = _concrete_yaml_entries(baseline_source)
    transformed_entries = _concrete_yaml_entries(transformed_source)
    contracts = record_field_type_sets(baseline_source)
    groups: dict[
        tuple[object, ...],
        list[tuple[tuple[object, ...], str, tuple[object, ...], object]],
    ] = {}
    for path, entry in baseline_entries.items():
        transformed = transformed_entries[path][-1]
        if transformed == entry[-1]:
            continue
        relative_path, navigation, record_name, field, _value = entry
        group = _semantic_mutation_group(path, entry, contracts[record_name][field])
        groups.setdefault(group, []).append(
            (path, relative_path, navigation, transformed)
        )

    mutations = []
    for ordinal, (group, changes) in enumerate(
        sorted(groups.items(), key=lambda item: repr(item[0]))
    ):
        writes = tuple(
            (relative_path, navigation, transformed)
            for _path, relative_path, navigation, transformed in changes
        )
        mutations.append(
            (
                f"{ordinal:04d}-{'-'.join(str(item) for item in group[:2])}",
                frozenset(path for path, *_rest in changes),
                writes,
            )
        )
    return tuple(mutations)


@dataclass(frozen=True)
class _SupplementalAuthoringMutation:
    name: str
    covered_paths: frozenset[tuple[object, ...]]
    mutate_source: Callable[[Path], None]
    expected_sql: frozenset[tuple[str, str]]
    expected_coverage: frozenset[tuple[str, str]]


def _targets(
    *values: tuple[str, str],
) -> frozenset[tuple[str, str]]:
    return frozenset(values)


_HASH_ONLY = _targets(("top", "knowledge_content_sha256"))
_CLAIM_EVIDENCE_COVERAGE = _targets(
    ("top", "knowledge_content_sha256"),
    ("top", "claims"),
    ("claim", "evidence_level"),
)


def supplemental_authoring_mutations() -> tuple[_SupplementalAuthoringMutation, ...]:
    """Return valid raw-source scenarios for context-coupled concrete values."""
    cases: list[_SupplementalAuthoringMutation] = []
    for category_id in RELEASED_CATEGORY_IDS:
        identity_relative = f"categories/{category_id}/identities.yaml"
        lifecycle_relative = f"categories/{category_id}/lifecycles.yaml"
        component_relative = f"categories/{category_id}/components.yaml"
        hazard_relative = f"categories/{category_id}/hazards.yaml"
        coverage_relative = f"categories/{category_id}/coverage.yaml"

        def convert_family(source: Path, *, relative: str = identity_relative) -> None:
            def mutate(document: dict[str, object]) -> None:
                identity = document["identities"][0]
                identity["identity_kind"] = "model"
                identity["model_id"] = identity["identity_id"]
                identity["model_name"] = identity["family_name"] + " Model"
                identity["evidence_level"] = "A"

            mutate_yaml(source / relative, mutate)

        family_paths = frozenset(
            (identity_relative, "identities", 0, "identity", field)
            for field in (
                "identity_kind", "model_id", "model_name", "evidence_level"
            )
        )
        cases.append(
            _SupplementalAuthoringMutation(
                f"{category_id}-family-to-model",
                family_paths,
                convert_family,
                _targets(
                    ("identities", "identity_kind"),
                    ("identities", "model_id"),
                    ("identities", "model_name"),
                    ("identities", "evidence_level"),
                ),
                _CLAIM_EVIDENCE_COVERAGE,
            )
        )

        for identity_index in range(1, 10):
            def convert_model(
                source: Path,
                *,
                relative: str = identity_relative,
                lifecycle: str = lifecycle_relative,
                index: int = identity_index,
            ) -> None:
                def mutate_identity(document: dict[str, object]) -> None:
                    identity = document["identities"][index]
                    identity["identity_kind"] = "family"
                    identity["family_id"] = identity["identity_id"]
                    identity["model_id"] = None
                    identity["model_name"] = None
                    identity["evidence_level"] = "B"

                mutate_yaml(source / relative, mutate_identity)
                if index == 1:
                    def mutate_lifecycle(document: dict[str, object]) -> None:
                        record = document["lifecycles"][0]
                        record["scope"]["kind"] = "family"
                        record["evidence_level"] = "B"

                    mutate_yaml(source / lifecycle, mutate_lifecycle)

            covered = {
                (identity_relative, "identities", identity_index, "identity", "identity_kind"),
                (identity_relative, "identities", identity_index, "identity", "evidence_level"),
            }
            expected_sql = {
                ("identities", "identity_kind"),
                ("identities", "family_id"),
                ("identities", "model_id"),
                ("identities", "model_name"),
                ("identities", "evidence_level"),
            }
            if identity_index == 1:
                covered |= {
                    (lifecycle_relative, "lifecycles", 0, "scope", "scope", "kind"),
                    (lifecycle_relative, "lifecycles", 0, "specific_lifecycle", "evidence_level"),
                }
                expected_sql |= {
                    ("lifecycle_records", "resolution_tier"),
                    ("lifecycle_records", "scope_kind"),
                    ("lifecycle_records", "evidence_level"),
                }
            cases.append(
                _SupplementalAuthoringMutation(
                    f"{category_id}-model-{identity_index}-to-family",
                    frozenset(covered),
                    convert_model,
                    frozenset(expected_sql),
                    _CLAIM_EVIDENCE_COVERAGE,
                )
            )

        for lifecycle_index, model_index in ((1, 2), (2, 4)):
            def change_lifecycle_scope(
                source: Path,
                *,
                relative: str = lifecycle_relative,
                index: int = lifecycle_index,
                model: int = model_index,
                category: str = category_id,
            ) -> None:
                def mutate(document: dict[str, object]) -> None:
                    record = document["lifecycles"][index]
                    record["scope"] = {
                        "kind": "model",
                        "id": f"{category}_model_{model:02d}",
                    }
                    record["evidence_level"] = "A"

                mutate_yaml(source / relative, mutate)

            cases.append(
                _SupplementalAuthoringMutation(
                    f"{category_id}-lifecycle-{lifecycle_index}-model-scope",
                    frozenset(
                        {
                            (lifecycle_relative, "lifecycles", lifecycle_index, "scope", "scope", "kind"),
                            (lifecycle_relative, "lifecycles", lifecycle_index, "specific_lifecycle", "evidence_level"),
                        }
                    ),
                    change_lifecycle_scope,
                    _targets(
                        ("lifecycle_records", "resolution_tier"),
                        ("lifecycle_records", "scope_kind"),
                        ("lifecycle_records", "scope_id"),
                        ("lifecycle_records", "evidence_level"),
                    ),
                    _CLAIM_EVIDENCE_COVERAGE,
                )
            )

        def rotate_template_roles(
            source: Path,
            *,
            relative: str = component_relative,
            category: str = category_id,
        ) -> None:
            def mutate(document: dict[str, object]) -> None:
                templates = document["templates"]
                templates[0]["template_kind"] = "modern_overlay"
                templates[1]["template_kind"] = "standard"
                templates[1]["scope"] = {"kind": "category", "id": category}
                templates[2]["template_kind"] = "legacy_overlay"
                templates[2]["scope"] = {
                    "kind": "subtype",
                    "id": f"{category}_subtype_0",
                }
                templates[2]["application_order"] = 1
                associations = document["associations"]
                associations[0]["status"] = "conditional"
                associations[1]["evidence_level"] = "C"
                associations[3]["evidence_level"] = "B"
                associations[4]["evidence_level"] = "B"

            mutate_yaml(source / relative, mutate)

        role_paths = {
            (component_relative, "templates", index, "component_template", "template_kind")
            for index in range(3)
        }
        role_paths |= {
            (component_relative, "templates", index, "scope", "scope", "kind")
            for index in (1, 2)
        }
        role_paths |= {
            (component_relative, "templates", 2, "scope", "scope", "id"),
            (component_relative, "templates", 2, "component_template", "application_order"),
        }
        role_paths |= {
            (component_relative, "associations", index, "component_association", "evidence_level")
            for index in (1, 3, 4)
        }
        cases.append(
            _SupplementalAuthoringMutation(
                f"{category_id}-rotate-template-roles",
                frozenset(role_paths),
                rotate_template_roles,
                _targets(
                    ("component_templates", "template_kind"),
                    ("component_templates", "scope_kind"),
                    ("component_templates", "scope_id"),
                    ("component_templates", "application_order"),
                    ("component_associations", "status"),
                    ("component_associations", "evidence_level"),
                ),
                _CLAIM_EVIDENCE_COVERAGE,
            )
        )

        def change_legacy_scope(
            source: Path,
            *,
            relative: str = component_relative,
            category: str = category_id,
        ) -> None:
            def mutate(document: dict[str, object]) -> None:
                document["templates"][0]["scope"] = {
                    "kind": "model",
                    "id": f"{category}_model_04",
                }
                document["associations"][0]["evidence_level"] = "A"

            mutate_yaml(source / relative, mutate)

        cases.append(
            _SupplementalAuthoringMutation(
                f"{category_id}-legacy-model-scope",
                frozenset(
                    {
                        (component_relative, "templates", 0, "scope", "scope", "kind"),
                        (component_relative, "associations", 0, "component_association", "evidence_level"),
                    }
                ),
                change_legacy_scope,
                _targets(
                    ("component_templates", "scope_kind"),
                    ("component_templates", "scope_id"),
                    ("component_associations", "evidence_level"),
                ),
                _CLAIM_EVIDENCE_COVERAGE,
            )
        )

        def change_hazard_scope(
            source: Path,
            *,
            relative: str = hazard_relative,
            category: str = category_id,
        ) -> None:
            def mutate(document: dict[str, object]) -> None:
                hazard = document["hazards"][0]
                hazard["scope"] = {
                    "kind": "subtype",
                    "id": f"{category}_subtype_0",
                }
                hazard["evidence_level"] = "B"

            mutate_yaml(source / relative, mutate)

        cases.append(
            _SupplementalAuthoringMutation(
                f"{category_id}-hazard-subtype-scope",
                frozenset(
                    {
                        (hazard_relative, "hazards", 0, "scope", "scope", "kind"),
                        (hazard_relative, "hazards", 0, "scope", "scope", "id"),
                    }
                ),
                change_hazard_scope,
                _targets(
                    ("hazards", "scope_kind"),
                    ("hazards", "scope_id"),
                    ("hazards", "evidence_level"),
                ),
                _CLAIM_EVIDENCE_COVERAGE,
            )
        )

        def swap_unknown_association(
            source: Path,
            *,
            components: str = component_relative,
            coverage: str = coverage_relative,
            category: str = category_id,
        ) -> None:
            def mutate_components(document: dict[str, object]) -> None:
                reviewed, unknown = document["associations"][1:3]
                reviewed.update(
                    {"status": "unknown", "evidence_level": None, "source_ids": []}
                )
                unknown.update(
                    {
                        "status": "commonly_associated",
                        "evidence_level": "B",
                        "source_ids": [f"{category}_claim_source"],
                    }
                )

            mutate_yaml(source / components, mutate_components)
            mutate_yaml(
                source / coverage,
                lambda document: document["unknowns"][0].__setitem__(
                    "claim_id", f"{category}_association_modern_0"
                ),
            )

        cases.append(
            _SupplementalAuthoringMutation(
                f"{category_id}-swap-unknown-association",
                frozenset(
                    {
                        (component_relative, "associations", 2, "component_association", "status"),
                        (component_relative, "associations", 2, "component_association", "evidence_level"),
                    }
                ),
                swap_unknown_association,
                _targets(
                    ("component_associations", "status"),
                    ("component_associations", "evidence_level"),
                    ("coverage_unknowns", "claim_id"),
                    ("claim_sources", "claim_id"),
                ),
                _targets(
                    ("top", "knowledge_content_sha256"),
                    ("top", "claims"),
                    ("claim", "evidence_level"),
                    ("claim", "source_state"),
                    ("claim", "source_ids"),
                    ("claim", "unknown_reason"),
                ),
            )
        )

        def retarget_unknown_claim_kind(
            source: Path,
            *,
            components: str = component_relative,
            coverage: str = coverage_relative,
            category: str = category_id,
        ) -> None:
            def review_association(document: dict[str, object]) -> None:
                document["associations"][2].update(
                    {
                        "status": "commonly_associated",
                        "evidence_level": "B",
                        "source_ids": [f"{category}_claim_source"],
                    }
                )

            def retarget_unknown(document: dict[str, object]) -> None:
                document["unknowns"][0].update(
                    {
                        "claim_kind": "hazard",
                        "claim_id": f"{category}_unsupported_hazard_claim",
                    }
                )

            mutate_yaml(source / components, review_association)
            mutate_yaml(source / coverage, retarget_unknown)

        cases.append(
            _SupplementalAuthoringMutation(
                f"{category_id}-retarget-unknown-claim-kind",
                frozenset(
                    {
                        (
                            coverage_relative,
                            "unknowns",
                            0,
                            "unknown",
                            "claim_kind",
                        )
                    }
                ),
                retarget_unknown_claim_kind,
                frozenset(
                    {
                        ("component_associations", "status"),
                        ("component_associations", "evidence_level"),
                        ("coverage_unknowns", "claim_kind"),
                        ("coverage_unknowns", "claim_id"),
                    }
                    | {
                        ("claim_sources", column)
                        for column in EXPECTED_TABLE_COLUMNS["claim_sources"]
                    }
                ),
                frozenset(
                    _HASH_ONLY
                    | _COVERAGE_CLAIM_FIELDS
                    | {
                        ("top", "summary"),
                        ("top", "claims"),
                        ("summary", "reviewed_claims"),
                    }
                ),
            )
        )

        def regroup_later_associations(
            source: Path,
            *,
            relative: str = component_relative,
            category: str = category_id,
        ) -> None:
            def mutate(document: dict[str, object]) -> None:
                associations = document["associations"]
                associations[1].update(
                    {"template_id": f"{category}_legacy_overlay", "position": 1}
                )
                associations[2].update(
                    {"template_id": f"{category}_standard", "position": 0}
                )
                associations[3]["position"] = 1
                associations[4]["position"] = 2

            mutate_yaml(source / relative, mutate)

        cases.append(
            _SupplementalAuthoringMutation(
                f"{category_id}-regroup-later-association-positions",
                frozenset(
                    (component_relative, "associations", index, "component_association", "position")
                    for index in range(1, 5)
                ),
                regroup_later_associations,
                _targets(
                    ("component_associations", "template_id"),
                    ("component_associations", "position"),
                ),
                _HASH_ONLY,
            )
        )

        def insert_preceding_association(
            source: Path,
            *,
            relative: str = component_relative,
            category: str = category_id,
        ) -> None:
            def mutate(document: dict[str, object]) -> None:
                associations = document["associations"]
                associations[0]["position"] = 1
                associations.insert(
                    0,
                    {
                        "association_id": f"{category}_association_000_added",
                        "template_id": f"{category}_legacy_overlay",
                        "component_id": "battery",
                        "position": 0,
                        "status": "conditional",
                        "applicability": "Added before the prior first association.",
                        "notes": [],
                        "evidence_level": "B",
                        "source_ids": [f"{category}_claim_source"],
                    },
                )

            mutate_yaml(source / relative, mutate)

        cases.append(
            _SupplementalAuthoringMutation(
                f"{category_id}-first-association-position",
                frozenset(
                    {
                        (component_relative, "associations", 0, "component_association", "position")
                    }
                ),
                insert_preceding_association,
                frozenset(
                    {
                        ("component_associations", column)
                        for column in EXPECTED_TABLE_COLUMNS["component_associations"]
                    }
                    | {
                        ("claim_sources", column)
                        for column in EXPECTED_TABLE_COLUMNS["claim_sources"]
                    }
                ),
                frozenset(
                    _HASH_ONLY
                    | _COVERAGE_CLAIM_FIELDS
                    | {
                        ("top", "claims"),
                        ("top", "summary"),
                        ("summary", "reviewed_claims"),
                    }
                ),
            )
        )
    return tuple(cases)


EXPECTED_EMPTY_AUTHORING_PATHS = frozenset(
    {
        ("common/policies.yaml", "policies", index, "policy", "when_any", "empty")
        for index in range(2)
    }
    | {
        path
        for category_id in RELEASED_CATEGORY_IDS
        for path in (
            (f"categories/{category_id}/components.yaml", "associations", 1, "component_association", "notes", "empty"),
            (f"categories/{category_id}/components.yaml", "associations", 2, "component_association", "source_ids", "empty"),
            (f"categories/{category_id}/components.yaml", "associations", 3, "component_association", "notes", "empty"),
            (f"categories/{category_id}/coverage.yaml", "unknowns", 0, "unknown", "source_ids", "empty"),
            (f"categories/{category_id}/industry_averages.yaml", "industry_averages", 0, "industry_average", "required_variant_ids", "empty"),
            (f"categories/{category_id}/industry_averages.yaml", "industry_averages", 0, "industry_average", "excluded_variant_ids", "empty"),
            (f"categories/{category_id}/lifecycles.yaml", "lifecycles", 0, "specific_lifecycle", "excluded_variant_ids", "empty"),
            (f"categories/{category_id}/lifecycles.yaml", "lifecycles", 1, "specific_lifecycle", "required_variant_ids", "empty"),
            (f"categories/{category_id}/lifecycles.yaml", "lifecycles", 1, "specific_lifecycle", "excluded_variant_ids", "empty"),
            (f"categories/{category_id}/lifecycles.yaml", "lifecycles", 1, "specific_lifecycle", "assumptions", "empty"),
            (f"categories/{category_id}/lifecycles.yaml", "lifecycles", 2, "specific_lifecycle", "required_variant_ids", "empty"),
            (f"categories/{category_id}/lifecycles.yaml", "lifecycles", 2, "specific_lifecycle", "excluded_variant_ids", "empty"),
        )
    }
)


EXPECTED_FIXED_AUTHORING_PATHS = frozenset(
    {
        ("bundle.yaml", "bundle", "bundle", field)
        for field in (
            "schema_version", "bundle_version", "identity_catalog_version", "policy_revision"
        )
    }
    | {
        ("bundle.yaml", "bundle", "bundle", "category_ids", index)
        for index in range(5)
    }
    | {("common/policies.yaml", "root", "policy_revision")}
    | {
        path
        for category_id in RELEASED_CATEGORY_IDS
        for path in (
            (f"categories/{category_id}/identities.yaml", "category", "category", "category_id"),
            *(
                (f"categories/{category_id}/identities.yaml", "subtypes", index, "subtype", field)
                for index in range(4)
                for field in ("category_id", "evidence_level")
            ),
            *(
                (f"categories/{category_id}/identities.yaml", "variants", index, "variant", field)
                for index in range(8)
                for field in ("category_id", "evidence_level")
            ),
            *(
                (f"categories/{category_id}/identities.yaml", "identities", index, "identity", "category_id")
                for index in range(10)
            ),
            *(
                (f"categories/{category_id}/industry_averages.yaml", "industry_averages", 0, "industry_average", field)
                for field in (
                    "subject", "endpoint", "endpoint_kind", "metric", "unit",
                    "applicable_from", "applicable_to", "model_year_from",
                    "model_year_to", "evidence_level",
                )
            ),
            (f"categories/{category_id}/industry_averages.yaml", "industry_averages", 0, "scope", "scope", "kind"),
            (f"categories/{category_id}/industry_averages.yaml", "industry_averages", 0, "scope", "scope", "id"),
            (f"categories/{category_id}/coverage.yaml", "unknowns", 0, "unknown", "category_id"),
            (f"categories/{category_id}/coverage.yaml", "unknowns", 0, "unknown", "evidence_level"),
        )
    }
)


def test_each_concrete_mutable_yaml_path_has_a_valid_exact_oracle_mutation(
    tmp_path: Path,
) -> None:
    baseline_source = make_valid_knowledge_source(tmp_path / "baseline")
    transformed_source = tmp_path / "transformed"
    shutil.copytree(baseline_source, transformed_source)
    all_paths, empty_paths = _all_concrete_yaml_value_paths(baseline_source)
    transformed_paths, frozen_paths = _transform_valid_fixture(transformed_source)
    mutations = semantic_authoring_mutations(
        baseline_source, transformed_source
    )
    supplemental = supplemental_authoring_mutations()
    supplemental_paths = set().union(
        *(case.covered_paths for case in supplemental)
    )
    mutation_paths = set().union(
        *(paths for _name, paths, _writes in mutations)
    )
    assert (len(all_paths), len(empty_paths)) == (2637, 62)
    assert empty_paths == EXPECTED_EMPTY_AUTHORING_PATHS
    assert len(EXPECTED_FIXED_AUTHORING_PATHS) == 255
    assert len(transformed_paths) == 2132
    assert len(mutations) == 665
    assert len(supplemental) == 95
    assert len(supplemental_paths) == 250
    assert mutation_paths == transformed_paths
    assert sum(len(paths) for _name, paths, _writes in mutations) == len(
        transformed_paths
    )
    assert not transformed_paths & supplemental_paths
    assert not transformed_paths & EXPECTED_FIXED_AUTHORING_PATHS
    assert not supplemental_paths & EXPECTED_FIXED_AUTHORING_PATHS
    assert frozen_paths == supplemental_paths | EXPECTED_FIXED_AUTHORING_PATHS
    assert (
        all_paths | empty_paths
        == transformed_paths
        | supplemental_paths
        | EXPECTED_FIXED_AUTHORING_PATHS
        | EXPECTED_EMPTY_AUTHORING_PATHS
    )

    baseline_documents = load_evidence_documents(baseline_source)
    baseline_expected_rows = expected_normalized_sql_rows(baseline_documents)
    baseline_actual_rows = normalized_sql_rows(baseline_documents)
    assert baseline_actual_rows == baseline_expected_rows
    baseline_hash = logical_content_sha256(baseline_expected_rows)
    baseline_expected_report = expected_coverage_report(
        baseline_documents, baseline_hash
    )
    baseline_actual_report = build_coverage(baseline_documents, baseline_hash)
    assert baseline_actual_report == baseline_expected_report
    record_contexts = _concrete_yaml_record_contexts(baseline_source)
    assert set(record_contexts) == all_paths
    case_source = tmp_path / "mutation"

    for name, value_paths, writes in mutations:
        if case_source.exists():
            shutil.rmtree(case_source)
        shutil.copytree(baseline_source, case_source)
        writes_by_document: dict[
            str, list[tuple[tuple[object, ...], object]]
        ] = {}
        for relative_path, navigation, value in writes:
            writes_by_document.setdefault(relative_path, []).append(
                (navigation, value)
            )
        for relative_path, document_writes in writes_by_document.items():
            def apply_writes(
                document: dict[str, object],
                changes: list[tuple[tuple[object, ...], object]] = document_writes,
            ) -> None:
                for navigation, value in changes:
                    _set_yaml_navigation(document, navigation, value)

            mutate_yaml(
                case_source / relative_path,
                apply_writes,
            )

        changed_documents = load_evidence_documents(case_source)
        expected_rows = expected_normalized_sql_rows(changed_documents)
        actual_rows = normalized_sql_rows(changed_documents)
        assert actual_rows == expected_rows, (name, value_paths)
        oracle_sql_targets = _changed_sql_columns(
            baseline_expected_rows, expected_rows
        )
        declared_sql_targets, declared_coverage_targets = (
            targets_for_concrete_paths(value_paths, record_contexts)
        )
        assert oracle_sql_targets == declared_sql_targets, (name, value_paths)
        assert _changed_sql_columns(
            baseline_actual_rows, actual_rows
        ) == declared_sql_targets, (name, value_paths)
        changed_hash = logical_content_sha256(expected_rows)
        assert changed_hash != baseline_hash, (name, value_paths)
        expected_report = expected_coverage_report(changed_documents, changed_hash)
        actual_report = build_coverage(changed_documents, changed_hash)
        assert actual_report == expected_report, (name, value_paths)
        oracle_coverage_targets = _changed_report_fields(
            baseline_expected_report, expected_report
        )
        assert oracle_coverage_targets == declared_coverage_targets, (
            name,
            value_paths,
        )
        assert _changed_report_fields(
            baseline_actual_report, actual_report
        ) == declared_coverage_targets, (name, value_paths)
        assert coverage_json_bytes(actual_report) != coverage_json_bytes(
            baseline_actual_report
        ), (name, value_paths)

    for case in supplemental:
        if case_source.exists():
            shutil.rmtree(case_source)
        shutil.copytree(baseline_source, case_source)
        case.mutate_source(case_source)
        changed_documents = load_evidence_documents(case_source)
        expected_rows = expected_normalized_sql_rows(changed_documents)
        actual_rows = normalized_sql_rows(changed_documents)
        assert actual_rows == expected_rows, case.name
        assert _changed_sql_columns(
            baseline_expected_rows, expected_rows
        ) == case.expected_sql, case.name
        assert _changed_sql_columns(
            baseline_actual_rows, actual_rows
        ) == case.expected_sql, case.name
        changed_hash = logical_content_sha256(expected_rows)
        assert changed_hash != baseline_hash, case.name
        expected_report = expected_coverage_report(changed_documents, changed_hash)
        actual_report = build_coverage(changed_documents, changed_hash)
        assert actual_report == expected_report, case.name
        assert _changed_report_fields(
            baseline_expected_report, expected_report
        ) == case.expected_coverage, case.name
        assert _changed_report_fields(
            baseline_actual_report, actual_report
        ) == case.expected_coverage, case.name
        assert coverage_json_bytes(actual_report) != coverage_json_bytes(
            baseline_actual_report
        ), case.name


def _assert_valid_source_semantic_diff(
    baseline_source: Path, changed_source: Path
) -> tuple[frozenset[tuple[str, str]], frozenset[tuple[str, str]]]:
    baseline_documents = load_evidence_documents(baseline_source)
    changed_documents = load_evidence_documents(changed_source)
    baseline_expected = expected_normalized_sql_rows(baseline_documents)
    changed_expected = expected_normalized_sql_rows(changed_documents)
    baseline_actual = normalized_sql_rows(baseline_documents)
    changed_actual = normalized_sql_rows(changed_documents)
    assert baseline_actual == baseline_expected
    assert changed_actual == changed_expected
    sql_targets = _changed_sql_columns(baseline_expected, changed_expected)
    assert _changed_sql_columns(baseline_actual, changed_actual) == sql_targets
    baseline_hash = logical_content_sha256(baseline_expected)
    changed_hash = logical_content_sha256(changed_expected)
    assert changed_hash != baseline_hash
    baseline_expected_report = expected_coverage_report(
        baseline_documents, baseline_hash
    )
    changed_expected_report = expected_coverage_report(changed_documents, changed_hash)
    baseline_actual_report = build_coverage(baseline_documents, baseline_hash)
    changed_actual_report = build_coverage(changed_documents, changed_hash)
    assert baseline_actual_report == baseline_expected_report
    assert changed_actual_report == changed_expected_report
    coverage_targets = _changed_report_fields(
        baseline_expected_report, changed_expected_report
    )
    assert _changed_report_fields(
        baseline_actual_report, changed_actual_report
    ) == coverage_targets
    assert coverage_json_bytes(changed_actual_report) != coverage_json_bytes(
        baseline_actual_report
    )
    return sql_targets, coverage_targets


@pytest.mark.parametrize(
    ("claim_kind", "relative_path", "root_field", "record_index"),
    [
        ("policy", "common/policies.yaml", "policies", 0),
        ("subtype", "identities.yaml", "subtypes", 1),
        ("variant", "identities.yaml", "variants", 2),
        ("identity", "identities.yaml", "identities", 3),
        ("specific_lifecycle", "lifecycles.yaml", "lifecycles", 1),
        ("industry_average", "industry_averages.yaml", "industry_averages", 0),
        ("component_association", "components.yaml", "associations", 3),
        ("hazard", "hazards.yaml", "hazards", 0),
    ],
)
def test_each_claim_kind_source_provenance_changes_only_its_owned_source_cell(
    tmp_path: Path,
    claim_kind: str,
    relative_path: str,
    root_field: str,
    record_index: int,
) -> None:
    baseline = make_valid_knowledge_source(tmp_path / "baseline")
    changed = tmp_path / "changed"
    shutil.copytree(baseline, changed)
    if claim_kind == "policy":
        path = changed / relative_path
    else:
        path = changed / f"categories/{RELEASED_CATEGORY_IDS[0]}/{relative_path}"

    def replace_source(document: dict[str, object]) -> None:
        record = document[root_field][record_index]
        record["source_ids"] = ["shared_process_source"]

    mutate_yaml(path, replace_source)
    sql_targets, coverage_targets = _assert_valid_source_semantic_diff(
        baseline, changed
    )
    assert sql_targets == frozenset({("claim_sources", "source_id")})
    expected_coverage = {("top", "knowledge_content_sha256")}
    if claim_kind != "policy":
        expected_coverage |= {("top", "claims"), ("claim", "source_ids")}
    assert coverage_targets == frozenset(expected_coverage)


def _deep_replace_scalar(value: object, old: str, new: str) -> object:
    if isinstance(value, dict):
        return {key: _deep_replace_scalar(item, old, new) for key, item in value.items()}
    if isinstance(value, list):
        return [_deep_replace_scalar(item, old, new) for item in value]
    return new if value == old else value


def test_coordinated_model_id_rename_propagates_to_every_child_scope_and_claim_key(
    tmp_path: Path,
) -> None:
    baseline = make_valid_knowledge_source(tmp_path / "baseline")
    changed = tmp_path / "changed"
    shutil.copytree(baseline, changed)
    category_id = RELEASED_CATEGORY_IDS[0]
    old = f"{category_id}_model_01"
    new = f"{old}_v2"
    for relative_path in _knowledge_document_paths():
        path = changed / relative_path

        def rename(document: dict[str, object]) -> None:
            replaced = _deep_replace_scalar(document, old, new)
            assert isinstance(replaced, dict)
            document.clear()
            document.update(replaced)

        mutate_yaml(path, rename)

    sql_targets, coverage_targets = _assert_valid_source_semantic_diff(
        baseline, changed
    )
    assert sql_targets == frozenset(
        {
            ("identities", "identity_id"),
            ("identities", "model_id"),
            ("identity_aliases", "identity_id"),
            ("identity_tokens", "identity_id"),
            ("identity_variants", "identity_id"),
            ("lifecycle_records", "scope_id"),
            ("claim_sources", "claim_id"),
        }
    )
    assert coverage_targets == frozenset(
        {
            ("top", "knowledge_content_sha256"),
            ("top", "claims"),
            ("claim", "claim_id"),
        }
    )


def test_valid_nested_scope_tier_change_updates_only_scope_tier_and_evidence_targets(
    tmp_path: Path,
) -> None:
    baseline = make_valid_knowledge_source(tmp_path / "baseline")
    changed = tmp_path / "changed"
    shutil.copytree(baseline, changed)
    category_id = RELEASED_CATEGORY_IDS[0]
    path = changed / f"categories/{category_id}/lifecycles.yaml"

    def change_scope(document: dict[str, object]) -> None:
        record = document["lifecycles"][0]
        record["scope"] = {"kind": "family", "id": f"{category_id}_family_00"}
        record["evidence_level"] = "B"

    mutate_yaml(path, change_scope)
    sql_targets, coverage_targets = _assert_valid_source_semantic_diff(
        baseline, changed
    )
    assert sql_targets == frozenset(
        {
            ("lifecycle_records", "resolution_tier"),
            ("lifecycle_records", "scope_kind"),
            ("lifecycle_records", "scope_id"),
            ("lifecycle_records", "evidence_level"),
        }
    )
    assert coverage_targets == frozenset(
        {
            ("top", "knowledge_content_sha256"),
            ("top", "claims"),
            ("claim", "evidence_level"),
        }
    )


def test_later_policy_any_group_and_last_category_action_keep_exact_ownership_ordinals(
    tmp_path: Path,
) -> None:
    baseline = make_valid_knowledge_source(tmp_path / "baseline")
    changed = tmp_path / "changed"
    shutil.copytree(baseline, changed)
    mutate_yaml(
        changed / "common/policies.yaml",
        lambda document: document["policies"][1].__setitem__(
            "when_any", ["visible_condition.grade=good"]
        ),
    )
    last_category = RELEASED_CATEGORY_IDS[-1]
    mutate_yaml(
        changed / f"categories/{last_category}/hazards.yaml",
        lambda document: document["hazards"][-1]["disposal_guidance"].append(
            "Record the recycler receipt."
        ),
    )
    sql_targets, coverage_targets = _assert_valid_source_semantic_diff(
        baseline, changed
    )
    assert sql_targets == frozenset(
        {
            ("policy_predicates", "rule_id"),
            ("policy_predicates", "predicate_group"),
            ("policy_predicates", "ordinal"),
            ("policy_predicates", "predicate"),
            ("hazard_actions", "hazard_id"),
            ("hazard_actions", "action_kind"),
            ("hazard_actions", "ordinal"),
            ("hazard_actions", "action_text"),
        }
    )
    assert coverage_targets == frozenset(
        {("top", "knowledge_content_sha256")}
    )


def test_every_parent_child_value_and_zero_based_ordinal_round_trips_exactly(
    source_and_documents: tuple[Path, EvidenceDocuments], tmp_path: Path
) -> None:
    source, documents = source_and_documents
    expected = expected_normalized_sql_rows(documents)
    output = tmp_path / "bundle"

    manifest = compile_knowledge_bundle(source, output)

    assert read_normalized_sql_rows(output / "knowledge.sqlite") == expected
    assert expected == normalized_sql_rows(documents)
    assert manifest.content_sha256 == logical_content_sha256(expected)
    assert _metadata(output / "knowledge.sqlite") == {
        "bundle_version": "3.0.0",
        "content_sha256": manifest.content_sha256,
        "coverage_sha256": manifest.coverage_sha256,
        "identity_catalog_version": "1.0.0",
        "policy_revision": "2.0.0",
        "schema_version": "3",
    }


def test_logical_payload_is_exact_nonrecursive_canonical_json(
    source_and_documents: tuple[Path, EvidenceDocuments],
) -> None:
    _source, documents = source_and_documents
    rows = expected_normalized_sql_rows(documents)
    payload = expected_logical_payload(rows)
    expected_bytes = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    assert payload["format"] == "ewaste-knowledge-logical-v1"
    assert [item["name"] for item in payload["tables"]] == list(TABLE_ORDER)
    assert not expected_bytes.endswith(b"\n")
    assert logical_content_sha256(rows) == hashlib.sha256(expected_bytes).hexdigest()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda rows: rows.pop("hazards"),
        lambda rows: rows.__setitem__("extra", ()),
        lambda rows: rows.__setitem__("metadata", (("only-one",),)),
        lambda rows: rows.__setitem__("categories", tuple(reversed(rows["categories"]))),
        lambda rows: rows.__setitem__(
            "categories", (("0301_computer_mouse", "Mouse", True),)
        ),
        lambda rows: rows.__setitem__(
            "lifecycle_records",
            (tuple(list(rows["lifecycle_records"][0][:-9]) + [float("nan")] + list(rows["lifecycle_records"][0][-8:])),),
        ),
    ],
    ids=["missing-table", "extra-table", "row-width", "unsorted", "bool", "nan"],
)
def test_logical_digest_rejects_noncanonical_row_mappings(
    source_and_documents: tuple[Path, EvidenceDocuments],
    mutation: Callable[[dict[str, tuple[tuple[object, ...], ...]]], None],
) -> None:
    _source, documents = source_and_documents
    rows = deepcopy(expected_normalized_sql_rows(documents))
    mutation(rows)
    with pytest.raises(KnowledgeCompilationError):
        logical_content_sha256(rows)


def test_every_semantic_sql_cell_including_derived_ordinals_is_hash_bound(
    source_and_documents: tuple[Path, EvidenceDocuments],
) -> None:
    _source, documents = source_and_documents
    projected = expected_normalized_sql_rows(documents)
    rows = {table: tuple(values) for table, values in projected.items()}
    for table, values in tuple(rows.items()):
        if values:
            continue
        rows[table] = (
            tuple(
                0
                if column in INTEGER_COLUMN_NAMES
                else 1.0
                if (table, column) in REAL_COLUMNS
                else "synthetic"
                for column in EXPECTED_TABLE_COLUMNS[table]
            ),
        )
    baseline = logical_content_sha256(rows)
    visited: set[tuple[str, str]] = set()

    for table in TABLE_ORDER:
        for column_index, column in enumerate(EXPECTED_TABLE_COLUMNS[table]):
            if table == "metadata" and column == "value":
                candidate_rows = rows[table]
            else:
                candidate_rows = rows[table]
            assert candidate_rows
            selected = 0
            changed = {name: tuple(values) for name, values in rows.items()}
            mutable = [list(value) for value in changed[table]]
            value = mutable[selected][column_index]
            if value is None:
                replacement: object = (
                    2099 if column in INTEGER_COLUMN_NAMES else "replacement"
                )
            elif isinstance(value, int):
                replacement = value + 1000
            elif isinstance(value, float):
                replacement = value + 0.125
            else:
                replacement = f"{value}_changed"
            mutable[selected][column_index] = replacement
            pk_positions = tuple(
                EXPECTED_TABLE_COLUMNS[table].index(key)
                for key in EXPECTED_PRIMARY_KEY_COLUMNS[table]
            )
            changed[table] = tuple(
                sorted(
                    (tuple(value) for value in mutable),
                    key=lambda row: tuple(row[index] for index in pk_positions),
                )
            )
            visited.add((table, column))
            assert logical_content_sha256(changed) != baseline, f"{table}.{column}"

    assert visited == {
        (table, column)
        for table, columns in EXPECTED_TABLE_COLUMNS.items()
        for column in columns
    }


def test_compile_emits_fixed_files_and_deterministic_manifest_and_coverage(
    source_and_documents: tuple[Path, EvidenceDocuments], tmp_path: Path
) -> None:
    source, _documents = source_and_documents
    first = compile_knowledge_bundle(source, tmp_path / "first")
    second = compile_knowledge_bundle(source, tmp_path / "second")

    assert first == second
    assert first.schema_version == 3
    assert first.bundle_version == "3.0.0"
    assert first.identity_catalog_version == "1.0.0"
    assert first.policy_revision == "2.0.0"
    for name in ("first", "second"):
        assert sorted(path.name for path in (tmp_path / name).iterdir()) == [
            "evidence-coverage.json",
            "knowledge.sqlite",
        ]
    assert (tmp_path / "first/evidence-coverage.json").read_bytes() == (
        tmp_path / "second/evidence-coverage.json"
    ).read_bytes()
    assert first.coverage_sha256 == hashlib.sha256(
        (tmp_path / "first/evidence-coverage.json").read_bytes()
    ).hexdigest()


def _table_names(database: Path) -> tuple[str, ...]:
    with sqlite3.connect(database) as connection:
        return tuple(
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY rowid"
            )
        )


def _foreign_keys(database: Path) -> set[tuple[str, tuple[str, ...], str, tuple[str, ...]]]:
    found: set[tuple[str, tuple[str, ...], str, tuple[str, ...]]] = set()
    with sqlite3.connect(database) as connection:
        for table in TABLE_ORDER:
            grouped: dict[int, list[tuple[object, ...]]] = {}
            for row in connection.execute(f'PRAGMA foreign_key_list("{table}")'):
                grouped.setdefault(row[0], []).append(row)
            for rows in grouped.values():
                ordered = sorted(rows, key=lambda item: item[1])
                assert all(item[5:8] == ("NO ACTION", "NO ACTION", "NONE") for item in ordered)
                found.add(
                    (
                        table,
                        tuple(str(item[3]) for item in ordered),
                        str(ordered[0][2]),
                        tuple(str(item[4]) for item in ordered),
                    )
                )
    return found


def _unique_indexes(database: Path, table: str) -> set[tuple[str, ...]]:
    found: set[tuple[str, ...]] = set()
    with sqlite3.connect(database) as connection:
        for _seq, name, unique, origin, _partial in connection.execute(
            f'PRAGMA index_list("{table}")'
        ):
            if unique and origin == "u":
                found.add(
                    tuple(
                        row[2]
                        for row in connection.execute(f'PRAGMA index_info("{name}")')
                    )
                )
    return found


def test_schema_columns_affinities_nullability_primary_keys_uniques_and_fks_are_exact(
    source_and_documents: tuple[Path, EvidenceDocuments], tmp_path: Path
) -> None:
    source, _documents = source_and_documents
    database = tmp_path / "bundle/knowledge.sqlite"
    compile_knowledge_bundle(source, database.parent)

    assert _table_names(database) == TABLE_ORDER
    assert _foreign_keys(database) == EXPECTED_FOREIGN_KEYS
    assert sum(len(columns) for columns in EXPECTED_TABLE_COLUMNS.values()) == 145
    with sqlite3.connect(database) as connection:
        schema_objects = tuple(
            connection.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master "
                "ORDER BY type, name, tbl_name, sql"
            )
        )
        assert len(schema_objects) == 72
        assert {row[0] for row in schema_objects} == {"index", "table"}
        schema_bytes = json.dumps(
            schema_objects,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        assert hashlib.sha256(schema_bytes).hexdigest() == (
            EXPECTED_SCHEMA_SIGNATURE_SHA256
        )
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("delete",)
        assert connection.execute("PRAGMA quick_check").fetchall() == [("ok",)]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'"
        ).fetchone() == (0,)
        schema_sql = "\n".join(
            row[0]
            for row in connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' ORDER BY rowid"
            )
        )
        assert "AUTOINCREMENT" not in schema_sql.upper()
        assert schema_sql.upper().count("DEFERRABLE INITIALLY DEFERRED") == 28

        for table in TABLE_ORDER:
            info = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
            assert tuple(row[1] for row in info) == EXPECTED_TABLE_COLUMNS[table]
            expected_pk = EXPECTED_PRIMARY_KEY_COLUMNS[table]
            for row in info:
                _cid, column, affinity, not_null, default, pk_position = row
                expected_affinity = (
                    "REAL"
                    if (table, column) in REAL_COLUMNS
                    else "INTEGER"
                    if column in INTEGER_COLUMN_NAMES
                    else "TEXT"
                )
                assert affinity == expected_affinity, (table, column)
                assert not_null == int((table, column) not in NULLABLE_COLUMNS), (
                    table,
                    column,
                )
                assert default is None
                assert pk_position == (
                    expected_pk.index(column) + 1 if column in expected_pk else 0
                )
            assert _unique_indexes(database, table) == EXPECTED_UNIQUE_COLUMNS.get(
                table, set()
            )


@pytest.mark.parametrize(
    ("name", "table", "needle", "replacement"),
    [
        ("affinity", "sources", "title TEXT NOT NULL", "title BLOB NOT NULL"),
        ("nullability", "sources", "publisher TEXT NOT NULL", "publisher TEXT"),
        (
            "primary-key",
            "metadata",
            "key TEXT NOT NULL PRIMARY KEY",
            "key TEXT NOT NULL UNIQUE",
        ),
        (
            "unique",
            "categories",
            "release_order INTEGER NOT NULL UNIQUE",
            "release_order INTEGER NOT NULL",
        ),
        (
            "deferred-foreign-key",
            "subtypes",
            "DEFERRABLE INITIALLY DEFERRED",
            "NOT DEFERRABLE INITIALLY IMMEDIATE",
        ),
        (
            "range-check",
            "categories",
            "CHECK (release_order BETWEEN 0 AND 4)",
            "CHECK (1)",
        ),
        (
            "excluded-variant-ordinal-check",
            "lifecycle_excluded_variants",
            "ordinal INTEGER NOT NULL CHECK (ordinal >= 0)",
            "ordinal INTEGER NOT NULL",
        ),
        (
            "identity-shape-check",
            "identities",
            "identity_id = family_id",
            "identity_id = identity_id",
        ),
        (
            "lifecycle-tier-check",
            "lifecycle_records",
            "(scope_kind='model' AND resolution_tier='exact_model' AND evidence_level='A')",
            "(scope_kind='model')",
        ),
        (
            "lifecycle-endpoint-check",
            "lifecycle_records",
            "(endpoint='service_life' AND endpoint_kind='total_life')",
            "(endpoint='service_life')",
        ),
        (
            "industry-average-check",
            "lifecycle_records",
            "resolution_tier != 'industry_average' OR",
            "1 OR",
        ),
        (
            "template-shape-check",
            "component_templates",
            "scope_id=category_id AND application_order=0",
            "1",
        ),
        (
            "association-evidence-check",
            "component_associations",
            "status='unknown' AND evidence_level IS NULL",
            "status='unknown'",
        ),
        (
            "hazard-evidence-check",
            "hazards",
            "(scope_kind='model' AND evidence_level='A')",
            "(scope_kind='model')",
        ),
        (
            "claim-category-check",
            "claim_sources",
            "claim_kind='policy' AND category_key=''",
            "claim_kind='policy'",
        ),
    ],
)
def test_reopen_rejects_each_structurally_weakened_ddl_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    table: str,
    needle: str,
    replacement: str,
) -> None:
    del name
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "bundle"
    statements = list(compiler_module._SCHEMA_STATEMENTS)
    index = next(
        index
        for index, statement in enumerate(statements)
        if statement.startswith(f"CREATE TABLE {table} (")
    )
    assert statements[index].count(needle) == 1
    statements[index] = statements[index].replace(needle, replacement, 1)
    monkeypatch.setattr(compiler_module, "_SCHEMA_STATEMENTS", tuple(statements))

    with pytest.raises(KnowledgeCompilationError):
        compile_knowledge_bundle(source, destination)

    assert not destination.exists()


@pytest.mark.parametrize(
    "statement",
    [
        "CREATE VIEW leaked_view AS SELECT key FROM metadata",
        (
            "CREATE TRIGGER leaked_trigger AFTER INSERT ON metadata "
            "BEGIN SELECT 1; END"
        ),
        "CREATE INDEX leaked_index ON sources(title)",
    ],
    ids=("view", "trigger", "index"),
)
def test_reopen_rejects_every_extra_schema_object(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    statement: str,
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "bundle"
    monkeypatch.setattr(
        compiler_module,
        "_SCHEMA_STATEMENTS",
        (*compiler_module._SCHEMA_STATEMENTS, statement),
    )

    with pytest.raises(KnowledgeCompilationError):
        compile_knowledge_bundle(source, destination)

    assert not destination.exists()


def _assert_integrity_rejected(database: Path, sql: str) -> None:
    # UPDATE/DELETE LIMIT is an optional SQLite compile-time extension. Updating
    # every matching fixture row exercises the same declared constraint.
    sql = sql.removesuffix(" LIMIT 1")
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("BEGIN")
    try:
        try:
            connection.execute(sql)
            connection.commit()
        except sqlite3.IntegrityError:
            return
        pytest.fail(f"invalid statement was accepted: {sql}")
    finally:
        if connection.in_transaction:
            connection.rollback()
        connection.close()


@pytest.mark.parametrize(
    ("name", "sql"),
    [
        ("metadata-key", "UPDATE metadata SET key='other' WHERE key='schema_version'"),
        ("category-range-low", "UPDATE categories SET release_order=-1 LIMIT 1"),
        ("category-range-high", "UPDATE categories SET release_order=5 LIMIT 1"),
        ("category-unique-order", "UPDATE categories SET release_order=0 WHERE release_order=1"),
        ("subtype-market", "UPDATE subtypes SET market_state='other' LIMIT 1"),
        ("subtype-battery", "UPDATE subtypes SET battery_architecture='other' LIMIT 1"),
        ("subtype-evidence", "UPDATE subtypes SET evidence_level='A' LIMIT 1"),
        ("variant-battery", "UPDATE variants SET battery_architecture='other' LIMIT 1"),
        ("variant-evidence", "UPDATE variants SET evidence_level='A' LIMIT 1"),
        ("identity-kind", "UPDATE identities SET identity_kind='other' LIMIT 1"),
        ("identity-market", "UPDATE identities SET market_state='other' LIMIT 1"),
        ("identity-battery", "UPDATE identities SET battery_architecture='other' LIMIT 1"),
        ("identity-evidence", "UPDATE identities SET evidence_level='D' LIMIT 1"),
        ("identity-year-order", "UPDATE identities SET model_year_from=2030, model_year_to=2020 LIMIT 1"),
        ("identity-date-order", "UPDATE identities SET applicable_from='2030-01-01', applicable_to='2020-01-01' LIMIT 1"),
        ("family-id-shape", "UPDATE identities SET family_id='other' WHERE identity_kind='family'"),
        ("family-model-null", "UPDATE identities SET model_id='model' WHERE identity_kind='family' LIMIT 1"),
        ("model-id-shape", "UPDATE identities SET model_id='other' WHERE identity_kind='model'"),
        ("model-model-required", "UPDATE identities SET model_id=NULL WHERE identity_kind='model' LIMIT 1"),
        ("model-name-required", "UPDATE identities SET model_name=NULL WHERE identity_kind='model' LIMIT 1"),
        ("lifecycle-positive", "UPDATE lifecycle_records SET lower_bound=0 LIMIT 1"),
        ("lifecycle-bound-order", "UPDATE lifecycle_records SET lower_bound=10, upper_bound=5 LIMIT 1"),
        ("lifecycle-precedence", "UPDATE lifecycle_records SET precedence=-1 LIMIT 1"),
        ("lifecycle-resolution-tier", "UPDATE lifecycle_records SET resolution_tier='other' LIMIT 1"),
        ("lifecycle-scope-kind", "UPDATE lifecycle_records SET scope_kind='other' LIMIT 1"),
        ("lifecycle-year-order", "UPDATE lifecycle_records SET model_year_from=2030, model_year_to=2020 WHERE scope_kind='family'"),
        ("lifecycle-date-order", "UPDATE lifecycle_records SET applicable_from='2030-01-01', applicable_to='2020-01-01' WHERE scope_kind='family'"),
        ("lifecycle-tier", "UPDATE lifecycle_records SET resolution_tier='family' WHERE scope_kind='model' LIMIT 1"),
        ("model-tier-evidence", "UPDATE lifecycle_records SET evidence_level='B' WHERE scope_kind='model'"),
        ("family-tier-evidence", "UPDATE lifecycle_records SET evidence_level='A' WHERE scope_kind='family'"),
        ("subtype-tier-evidence", "UPDATE lifecycle_records SET evidence_level='A' WHERE scope_kind='subtype'"),
        ("category-tier-evidence", "UPDATE lifecycle_records SET evidence_level='B' WHERE scope_kind='category'"),
        ("lifecycle-endpoint-kind", "UPDATE lifecycle_records SET endpoint_kind='operating_endurance' WHERE endpoint='service_life' LIMIT 1"),
        ("capacity-endpoint-kind", "UPDATE lifecycle_records SET endpoint_kind='total_life' WHERE endpoint='capacity_threshold'"),
        ("other-endpoint-kind", "UPDATE lifecycle_records SET endpoint_kind='total_life' WHERE endpoint NOT IN ('service_life','capacity_threshold')"),
        ("industry-strict-range", "UPDATE lifecycle_records SET upper_bound=lower_bound WHERE resolution_tier='industry_average' LIMIT 1"),
        ("industry-subject", "UPDATE lifecycle_records SET subject='battery' WHERE resolution_tier='industry_average'"),
        ("industry-metric", "UPDATE lifecycle_records SET metric='full_charge_cycles' WHERE resolution_tier='industry_average'"),
        ("industry-unit", "UPDATE lifecycle_records SET unit='months' WHERE resolution_tier='industry_average'"),
        ("industry-date-bounds", "UPDATE lifecycle_records SET applicable_from='2020-01-01' WHERE resolution_tier='industry_average'"),
        ("industry-year-bounds", "UPDATE lifecycle_records SET model_year_from=2020 WHERE resolution_tier='industry_average'"),
        ("template-kind", "UPDATE component_templates SET template_kind='other' LIMIT 1"),
        ("template-scope-kind", "UPDATE component_templates SET scope_kind='other' LIMIT 1"),
        ("template-order", "UPDATE component_templates SET application_order=-1 LIMIT 1"),
        ("standard-scope", "UPDATE component_templates SET scope_kind='subtype' WHERE template_kind='standard' LIMIT 1"),
        ("standard-scope-id", "UPDATE component_templates SET scope_id='other' WHERE template_kind='standard'"),
        ("standard-order", "UPDATE component_templates SET application_order=1 WHERE template_kind='standard'"),
        ("overlay-category-scope", "UPDATE component_templates SET scope_kind='category' WHERE template_kind!='standard'"),
        ("association-position", "UPDATE component_associations SET position=-1 LIMIT 1"),
        ("association-status", "UPDATE component_associations SET status='other' LIMIT 1"),
        ("association-user-confirmed", "UPDATE component_associations SET status='user_confirmed' LIMIT 1"),
        ("association-unknown-evidence", "UPDATE component_associations SET evidence_level='B' WHERE status='unknown' LIMIT 1"),
        ("association-reviewed-evidence", "UPDATE component_associations SET evidence_level=NULL WHERE status!='unknown' LIMIT 1"),
        ("association-reviewed-grade", "UPDATE component_associations SET evidence_level='D' WHERE status!='unknown'"),
        ("hazard-scope", "UPDATE hazards SET scope_kind='other' LIMIT 1"),
        ("hazard-severity", "UPDATE hazards SET severity='other' LIMIT 1"),
        ("hazard-evidence", "UPDATE hazards SET evidence_level='A' WHERE scope_kind='category' LIMIT 1"),
        ("hazard-category-grade", "UPDATE hazards SET evidence_level='B' WHERE scope_kind='category'"),
        ("hazard-family-grade", "UPDATE hazards SET scope_kind='family', evidence_level='C' WHERE scope_kind='category'"),
        ("trigger-key", "UPDATE hazard_triggers SET observation_key='other' LIMIT 1"),
        ("action-kind", "UPDATE hazard_actions SET action_kind='other' LIMIT 1"),
        ("policy-priority", "UPDATE policy_rules SET priority=-1 LIMIT 1"),
        ("policy-outcome", "UPDATE policy_rules SET outcome='other' LIMIT 1"),
        ("policy-evidence", "UPDATE policy_rules SET evidence_level='other' LIMIT 1"),
        ("predicate-group", "UPDATE policy_predicates SET predicate_group='other' LIMIT 1"),
        ("predicate-value", "UPDATE policy_predicates SET predicate='other' LIMIT 1"),
        ("unknown-kind", "UPDATE coverage_unknowns SET claim_kind='policy' LIMIT 1"),
        ("claim-kind", "UPDATE claim_sources SET claim_kind='other' LIMIT 1"),
        ("policy-category", "UPDATE claim_sources SET category_key='category' WHERE claim_kind='policy' LIMIT 1"),
        ("nonpolicy-category", "UPDATE claim_sources SET category_key='' WHERE claim_kind!='policy' LIMIT 1"),
        ("foreign-key", "UPDATE claim_sources SET source_id='missing_source' LIMIT 1"),
    ],
)
def test_named_row_local_constraints_reject_invalid_writes(
    source_and_documents: tuple[Path, EvidenceDocuments],
    tmp_path: Path,
    name: str,
    sql: str,
) -> None:
    del name
    source, _documents = source_and_documents
    database = tmp_path / "bundle/knowledge.sqlite"
    compile_knowledge_bundle(source, database.parent)
    _assert_integrity_rejected(database, sql)


@pytest.mark.parametrize(
    "table",
    [
        "identity_aliases",
        "identity_tokens",
        "identity_variants",
        "lifecycle_required_variants",
        "lifecycle_assumptions",
        "lifecycle_limitations",
        "component_association_notes",
        "hazard_triggers",
        "hazard_actions",
        "policy_predicates",
        "claim_sources",
    ],
)
def test_child_ordinals_are_nonnegative(
    source_and_documents: tuple[Path, EvidenceDocuments], tmp_path: Path, table: str
) -> None:
    source, _documents = source_and_documents
    database = tmp_path / "bundle/knowledge.sqlite"
    compile_knowledge_bundle(source, database.parent)
    _assert_integrity_rejected(database, f'UPDATE "{table}" SET ordinal=-1 LIMIT 1')


def test_lifecycle_excluded_variant_ordinal_is_nonnegative_even_when_fixture_is_empty(
    source_and_documents: tuple[Path, EvidenceDocuments], tmp_path: Path
) -> None:
    source, _documents = source_and_documents
    database = tmp_path / "bundle/knowledge.sqlite"
    compile_knowledge_bundle(source, database.parent)
    with sqlite3.connect(database) as connection:
        record_id = connection.execute(
            "SELECT record_id FROM lifecycle_records ORDER BY record_id LIMIT 1"
        ).fetchone()[0]
        variant_id = connection.execute(
            "SELECT variant_id FROM variants ORDER BY variant_id LIMIT 1"
        ).fetchone()[0]
    _assert_integrity_rejected(
        database,
        "INSERT INTO lifecycle_excluded_variants "
        f"VALUES ('{record_id}', -1, '{variant_id}')",
    )


def test_exact_category_release_order_survives_reopen(
    source_and_documents: tuple[Path, EvidenceDocuments], tmp_path: Path
) -> None:
    source, _documents = source_and_documents
    database = tmp_path / "bundle/knowledge.sqlite"
    compile_knowledge_bundle(source, database.parent)
    with sqlite3.connect(f"file:{database}?mode=ro&immutable=1", uri=True) as connection:
        assert dict(connection.execute("SELECT category_id, release_order FROM categories")) == CATEGORY_RELEASE_ORDER


@pytest.mark.parametrize(
    "relationship",
    ["same_as_source", "inside_source", "ancestor_of_source"],
)
def test_source_and_destination_may_not_overlap(
    tmp_path: Path, relationship: str
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = {
        "same_as_source": source,
        "inside_source": source / "bundle",
        "ancestor_of_source": tmp_path,
    }[relationship]
    before = _snapshot_tree(source)

    with pytest.raises(KnowledgeCompilationError, match="must not overlap"):
        compile_knowledge_bundle(source, destination)

    assert _snapshot_tree(source) == before


def test_invalid_source_creates_no_missing_destination_parent(tmp_path: Path) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    mutate_yaml(
        source / "bundle.yaml",
        lambda document: document["bundle"].__setitem__("schema_version", 99),
    )
    destination = tmp_path / "missing/inner/bundle"

    with pytest.raises(EvidenceValidationError):
        compile_knowledge_bundle(source, destination)

    assert not (tmp_path / "missing").exists()


def test_destination_appearing_after_preflight_is_rejected_without_touching_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "bundle"
    marker = b"belongs to another creator"
    real_capture = compiler_module._capture_directory_chain
    destination_captures = 0

    def create_before_second_destination_capture(
        path: Path, *, label: str, require_final: bool
    ) -> tuple[tuple[object, ...], bool]:
        nonlocal destination_captures
        if label == "destination":
            destination_captures += 1
            if destination_captures == 2:
                destination.mkdir()
                (destination / "marker").write_bytes(marker)
        return real_capture(path, label=label, require_final=require_final)

    monkeypatch.setattr(
        compiler_module,
        "_capture_directory_chain",
        create_before_second_destination_capture,
    )

    with pytest.raises(KnowledgeCompilationError, match="identity|existence"):
        compile_knowledge_bundle(source, destination)

    assert destination_captures == 2
    assert (destination / "marker").read_bytes() == marker
    assert sorted(path.name for path in destination.iterdir()) == ["marker"]
    assert not list(tmp_path.glob(".bundle-*.stage"))
    assert not list(tmp_path.glob(".bundle-*.backup"))


def test_real_source_identity_swap_before_first_destination_mkdir_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "outer/inner/bundle"
    before = _snapshot_tree(source)
    real_loader = compiler_module.load_evidence_documents
    swapped = False

    def load_then_swap(path: Path) -> EvidenceDocuments:
        nonlocal swapped
        documents = real_loader(path)
        original = tmp_path / "source-before-mkdir"
        source.rename(original)
        shutil.copytree(original, source)
        swapped = True
        return documents

    monkeypatch.setattr(compiler_module, "load_evidence_documents", load_then_swap)
    with pytest.raises(KnowledgeCompilationError, match="identity changed"):
        compile_knowledge_bundle(source, destination)
    assert swapped
    assert not (tmp_path / "outer").exists()
    assert _snapshot_tree(source) == before


def test_real_source_identity_swap_between_destination_parent_mkdirs_stops_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "outer/inner/bundle"
    before = _snapshot_tree(source)
    real_fsync_directory = compiler_module._fsync_directory
    swapped = False

    def swap_after_first_parent_fsync(path: Path) -> None:
        nonlocal swapped
        real_fsync_directory(path)
        if Path(path) == tmp_path and not swapped:
            original = tmp_path / "source-between-mkdirs"
            source.rename(original)
            shutil.copytree(original, source)
            swapped = True

    monkeypatch.setattr(
        compiler_module, "_fsync_directory", swap_after_first_parent_fsync
    )
    with pytest.raises(KnowledgeCompilationError, match="identity changed"):
        compile_knowledge_bundle(source, destination)
    assert swapped
    assert (tmp_path / "outer").is_dir()
    assert not (tmp_path / "outer/inner").exists()
    assert _snapshot_tree(source) == before


@pytest.mark.parametrize(
    "window",
    ["file-after-lstat", "ancestor-before-open", "entry-after-snapshot"],
)
def test_compiler_preserves_task2_descriptor_binding_across_source_swap_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, window: str
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "missing/bundle"
    target = source / "bundle.yaml"
    outside_file = tmp_path / "outside-bundle.yaml"
    shutil.copy2(target, outside_file)
    swaps = 0

    if window == "file-after-lstat":
        original = schema_module._require_regular_file

        def swap_file(path: Path, filename: str) -> Path:
            nonlocal swaps
            checked = original(path, filename)
            if checked == target and swaps == 0:
                target.unlink()
                target.symlink_to(outside_file)
                swaps += 1
            return checked

        monkeypatch.setattr(schema_module, "_require_regular_file", swap_file)
    elif window == "ancestor-before-open":
        original = schema_module._require_regular_file
        ancestor = source / "common"
        outside_ancestor = tmp_path / "outside-common"
        shutil.copytree(ancestor, outside_ancestor)
        trigger = ancestor / "sources.yaml"

        def swap_ancestor(path: Path, filename: str) -> Path:
            nonlocal swaps
            checked = original(path, filename)
            if checked == trigger and swaps == 0:
                shutil.rmtree(ancestor)
                ancestor.symlink_to(outside_ancestor, target_is_directory=True)
                swaps += 1
            return checked

        monkeypatch.setattr(schema_module, "_require_regular_file", swap_ancestor)
    else:
        original = schema_module._directory_names_no_follow

        def swap_after_snapshot(
            path: Path, filename: str, *, checked: object = None
        ) -> dict[str, object]:
            nonlocal swaps
            entries = original(path, filename, checked=checked)
            if filename == "." and Path(path) == source and swaps == 0:
                target.unlink()
                os.link(outside_file, target)
                swaps += 1
            return entries

        monkeypatch.setattr(
            schema_module, "_directory_names_no_follow", swap_after_snapshot
        )

    with pytest.raises(EvidenceValidationError, match="unsafe path|changed"):
        compile_knowledge_bundle(source, destination)
    assert swaps == 1
    assert not destination.parent.exists()


@pytest.mark.parametrize("which", ["source", "destination-parent", "destination"])
def test_symlinked_required_directories_are_rejected_without_mutation(
    tmp_path: Path, which: str
) -> None:
    real_source = make_valid_knowledge_source(tmp_path / "real-source")
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    source = real_source
    destination = real_parent / "bundle"
    if which == "source":
        source = tmp_path / "source-link"
        source.symlink_to(real_source, target_is_directory=True)
    elif which == "destination-parent":
        link = tmp_path / "parent-link"
        link.symlink_to(real_parent, target_is_directory=True)
        destination = link / "bundle"
    else:
        destination.symlink_to(real_source, target_is_directory=True)
    before = _snapshot_tree(real_source)

    with pytest.raises(KnowledgeCompilationError, match="symlink|unsafe"):
        compile_knowledge_bundle(source, destination)

    assert _snapshot_tree(real_source) == before


def test_case_alias_identity_overlap_seam_rejects_before_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "other" / "bundle"
    (tmp_path / "other").mkdir()
    source_identity = compiler_module._path_identity(source)
    real_identity = compiler_module._path_identity

    def aliased_identity(path: Path) -> tuple[int, int]:
        if Path(path) == tmp_path / "other":
            return source_identity
        return real_identity(path)

    monkeypatch.setattr(compiler_module, "_path_identity", aliased_identity)
    with pytest.raises(KnowledgeCompilationError, match="must not overlap"):
        compile_knowledge_bundle(source, destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".bundle-*.stage"))


def test_two_missing_parent_entries_are_fsynced_before_stage_in_creation_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "outer/inner/bundle"
    calls: list[tuple[str, Path]] = []
    real_fsync = compiler_module._fsync_directory
    real_stage = compiler_module._create_stage_directory

    def traced_fsync(path: Path) -> None:
        calls.append(("fsync", Path(path)))
        real_fsync(path)

    def traced_stage(path: Path) -> Path:
        calls.append(("stage", Path(path).parent))
        return real_stage(path)

    monkeypatch.setattr(compiler_module, "_fsync_directory", traced_fsync)
    monkeypatch.setattr(compiler_module, "_create_stage_directory", traced_stage)
    compile_knowledge_bundle(source, destination)

    stage_index = next(index for index, call in enumerate(calls) if call[0] == "stage")
    assert calls[:stage_index] == [
        ("fsync", tmp_path),
        ("fsync", tmp_path / "outer"),
    ]


@pytest.mark.parametrize("failure_index", [0, 1])
def test_parent_fsync_failure_stops_before_later_parent_or_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_index: int
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "outer/inner/bundle"
    real_fsync = compiler_module._fsync_directory
    calls = 0

    def failed_fsync(path: Path) -> None:
        nonlocal calls
        if calls == failure_index:
            calls += 1
            raise OSError("injected parent fsync failure")
        calls += 1
        real_fsync(path)

    monkeypatch.setattr(compiler_module, "_fsync_directory", failed_fsync)
    with pytest.raises(KnowledgeCompilationError, match="fsync"):
        compile_knowledge_bundle(source, destination)

    assert (tmp_path / "outer").is_dir()
    assert (tmp_path / "outer/inner").is_dir() is (failure_index == 1)
    assert not destination.exists()
    assert not list((tmp_path / "outer/inner" if failure_index else tmp_path / "outer").glob(".bundle-*.stage"))


def test_failed_stage_to_destination_promotion_restores_old_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "bundle"
    compile_knowledge_bundle(source, destination)
    before = _snapshot_tree(destination)
    unrelated = tmp_path / ".bundle-unrelated.stage"
    unrelated.mkdir()
    real_replace = compiler_module._rename_noreplace

    def fail_stage(source_path: object, destination_path: object, *args: object) -> None:
        if str(source_path).endswith(".stage") and Path(destination_path) == destination:
            raise OSError("injected promotion failure")
        real_replace(source_path, destination_path, *args)

    monkeypatch.setattr(compiler_module, "_rename_noreplace", fail_stage)
    with pytest.raises(KnowledgeCompilationError, match="promotion failure"):
        compile_knowledge_bundle(source, destination)

    assert _snapshot_tree(destination) == before
    assert unrelated.is_dir()
    assert not list(tmp_path.glob(".bundle-????????????????????????????????.stage"))
    assert not list(tmp_path.glob(".bundle-????????????????????????????????.backup"))


def test_tampered_staged_coverage_is_rejected_before_promotion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "bundle"
    real_verify = compiler_module._verify_staged_bundle

    def tamper_then_verify(*args: object, **kwargs: object) -> object:
        stage = Path(args[0])
        (stage / "evidence-coverage.json").write_bytes(b"{}\n")
        return real_verify(*args, **kwargs)

    monkeypatch.setattr(compiler_module, "_verify_staged_bundle", tamper_then_verify)
    with pytest.raises(KnowledgeCompilationError, match="coverage"):
        compile_knowledge_bundle(source, destination)
    assert not destination.exists()


def test_rebuild_validation_failure_preserves_previous_bundle(tmp_path: Path) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    output = tmp_path / "bundle"
    original = compile_knowledge_bundle(source, output)
    before = _snapshot_tree(output)
    mutate_yaml(
        source / "bundle.yaml",
        lambda document: document["bundle"].__setitem__("schema_version", 99),
    )

    with pytest.raises(EvidenceValidationError):
        compile_knowledge_bundle(source, output)

    assert _snapshot_tree(output) == before
    assert _metadata(output / "knowledge.sqlite")["content_sha256"] == original.content_sha256


HOSTILE_SOURCE_PATH_MUTATIONS = (
    *shared_path_mutations(),
    *category_path_mutations(RELEASED_CATEGORY_IDS[0]),
)


@pytest.mark.parametrize(
    "mutation", HOSTILE_SOURCE_PATH_MUTATIONS, ids=lambda mutation: mutation.name
)
def test_every_loader_hostile_source_path_is_rejected_before_output_creation(
    tmp_path: Path, mutation: object
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    mutation.apply(source)
    output = tmp_path / "missing/inner/bundle"
    expected_error = (
        KnowledgeCompilationError
        if mutation.name == "symlink_source_dir"
        else EvidenceValidationError
    )
    with pytest.raises(expected_error, match=mutation.expected_error):
        compile_knowledge_bundle(source, output)
    assert not (tmp_path / "missing").exists()


def _make_wrong_kind(path: Path, kind: str) -> socket.socket | None:
    if kind == "regular":
        path.write_text("not a directory", encoding="utf-8")
    elif kind == "fifo":
        os.mkfifo(path)
    elif kind == "socket":
        listener = socket.socket(socket.AF_UNIX)
        previous = Path.cwd()
        try:
            os.chdir(path.parent)
            listener.bind(path.name)
        finally:
            os.chdir(previous)
        return listener
    elif kind == "symlink":
        target = path.parent / f"{path.name}-target"
        target.mkdir()
        path.symlink_to(target, target_is_directory=True)
    else:
        raise AssertionError(kind)
    return None


@pytest.mark.parametrize("kind", ["regular", "fifo", "socket", "symlink"])
@pytest.mark.parametrize("layer", ["ancestor", "destination"])
def test_every_wrong_destination_kind_is_rejected_before_destructive_work(
    tmp_path: Path, kind: str, layer: str
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    bad = tmp_path / "bad"
    listener = _make_wrong_kind(bad, kind)
    destination = bad / "bundle" if layer == "ancestor" else bad
    try:
        with pytest.raises(KnowledgeCompilationError, match="symlink|non-directory"):
            compile_knowledge_bundle(source, destination)
    finally:
        if listener is not None:
            listener.close()
    assert not list(tmp_path.glob(".bundle-*.stage"))


@pytest.mark.parametrize(
    "relationship", ["same_inode", "destination_below", "destination_above"]
)
def test_all_case_alias_identity_relationships_are_rejected_before_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relationship: str
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    alias = tmp_path / "alias"
    alias.mkdir()
    destination = alias if relationship != "destination_below" else alias / "bundle"
    source_root_identity = compiler_module._path_identity(source)
    source_parent_identity = compiler_module._path_identity(source.parent)
    real_identity = compiler_module._path_identity

    def identity_view(path: Path) -> tuple[int, int]:
        path = Path(path)
        if path == alias:
            return (
                source_parent_identity
                if relationship == "destination_above"
                else source_root_identity
            )
        return real_identity(path)

    monkeypatch.setattr(compiler_module, "_path_identity", identity_view)
    replace_calls: list[tuple[object, object]] = []
    def record_promotion(source_path: Path, destination_path: Path) -> None:
        if source_path == destination or destination_path == destination:
            replace_calls.append((source_path, destination_path))

    _intercept_promotion_move(monkeypatch, record_promotion)
    with pytest.raises(KnowledgeCompilationError, match="must not overlap"):
        compile_knowledge_bundle(source, destination)
    assert replace_calls == []
    assert not list(tmp_path.glob(".*.stage"))


def test_identity_drift_immediately_before_promotion_cleans_stage_without_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "bundle"
    before = _snapshot_tree(source)
    replace_calls: list[tuple[object, object]] = []
    real_fsync_directory = compiler_module._fsync_stage_directory
    swapped = False

    def swap_source_identity_after_stage_fsync(
        path: Path, stage_identity: tuple[int, int]
    ) -> None:
        nonlocal swapped
        real_fsync_directory(path, stage_identity)
        if str(path).endswith(".stage") and not swapped:
            original = tmp_path / "source-original"
            source.rename(original)
            shutil.copytree(original, source)
            swapped = True

    monkeypatch.setattr(
        compiler_module,
        "_fsync_stage_directory",
        swap_source_identity_after_stage_fsync,
    )
    monkeypatch.setattr(
        compiler_module.os,
        "replace",
        lambda source_path, destination_path: replace_calls.append(
            (source_path, destination_path)
        ),
    )
    with pytest.raises(KnowledgeCompilationError, match="identity changed"):
        compile_knowledge_bundle(source, destination)
    assert swapped
    assert replace_calls == []
    assert not destination.exists()
    assert not list(tmp_path.glob(".bundle-*.stage"))
    assert _snapshot_tree(source) == before


class _FixedUuid:
    def __init__(self, value: str) -> None:
        self.hex = value


@pytest.mark.parametrize("kind", ["regular", "directory", "fifo", "socket", "symlink"])
def test_stage_name_collision_of_every_kind_is_retried_without_touching_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "bundle"
    collision = tmp_path / f".bundle-{'0' * 32}.stage"
    listener: socket.socket | None = None
    if kind == "directory":
        collision.mkdir()
    else:
        listener = _make_wrong_kind(collision, kind)
    before = os.lstat(collision)
    identifiers = iter((_FixedUuid("0" * 32), _FixedUuid("1" * 32)))
    monkeypatch.setattr(compiler_module, "uuid4", lambda: next(identifiers))
    try:
        compile_knowledge_bundle(source, destination)
    finally:
        if listener is not None:
            listener.close()
    after = os.lstat(collision)
    assert (after.st_dev, after.st_ino, after.st_mode) == (
        before.st_dev,
        before.st_ino,
        before.st_mode,
    )


@pytest.mark.parametrize("kind", ["regular", "directory", "fifo", "socket", "symlink"])
def test_backup_name_collision_of_every_kind_is_retried_without_touching_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "bundle"
    compile_knowledge_bundle(source, destination)
    collision = tmp_path / f".bundle-{'2' * 32}.backup"
    listener: socket.socket | None = None
    if kind == "directory":
        collision.mkdir()
    else:
        listener = _make_wrong_kind(collision, kind)
    before = os.lstat(collision)
    identifiers = iter(
        (_FixedUuid("1" * 32), _FixedUuid("2" * 32), _FixedUuid("3" * 32))
    )
    monkeypatch.setattr(compiler_module, "uuid4", lambda: next(identifiers))
    try:
        compile_knowledge_bundle(source, destination)
    finally:
        if listener is not None:
            listener.close()
    after = os.lstat(collision)
    assert (after.st_dev, after.st_ino, after.st_mode) == (
        before.st_dev,
        before.st_ino,
        before.st_mode,
    )


@pytest.mark.parametrize("existing", [False, True])
def test_unreadable_stage_mode_failure_preserves_exact_inode_and_closes_descriptors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing: bool
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "bundle"
    if existing:
        compile_knowledge_bundle(source, destination)
    old = _snapshot_tree(destination) if existing else None
    source_before = _snapshot_tree(source)
    captured: list[tuple[Path, tuple[int, int, int]]] = []
    opened: set[int] = set()
    destructive: list[object] = []
    real_mkdir, real_open, real_close = Path.mkdir, os.open, os.close
    real_rmdir, real_move = os.rmdir, compiler_module._rename_noreplace

    def mkdir(path: Path, *args: object, **kwargs: object) -> None:
        real_mkdir(path, *args, **kwargs)
        if path.suffix == ".stage":
            result = os.lstat(path)
            captured.append((path, (result.st_dev, result.st_ino, result.st_mode)))

    def tracked_open(*args: object, **kwargs: object) -> int:
        fd = real_open(*args, **kwargs)
        opened.add(fd)
        return fd

    def tracked_close(fd: int) -> None:
        real_close(fd)
        opened.discard(fd)

    def rmdir(*args: object, **kwargs: object) -> None:
        destructive.append(args)
        real_rmdir(*args, **kwargs)

    def move(*args: object, **kwargs: object) -> None:
        destructive.append(args)
        real_move(*args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", mkdir)
    monkeypatch.setattr(os, "open", tracked_open)
    monkeypatch.setattr(os, "close", tracked_close)
    monkeypatch.setattr(os, "rmdir", rmdir)
    monkeypatch.setattr(compiler_module, "_rename_noreplace", move)
    previous_umask = os.umask(0o700)
    try:
        with pytest.raises(KnowledgeCompilationError, match="mode 0700") as error:
            compile_knowledge_bundle(source, destination)
    finally:
        os.umask(previous_umask)

    # A mode-000 directory cannot be safely opened for descriptor-bound cleanup.
    # Preserve it, as required by the current C4 conservative-recovery contract.
    assert len(captured) == 1
    stage, identity = captured[0]
    result = os.lstat(stage)
    assert (result.st_dev, result.st_ino, result.st_mode) == identity
    assert stat.S_IMODE(result.st_mode) == 0
    assert list(tmp_path.glob(".bundle-*.stage")) == [stage]
    assert not list(tmp_path.glob(".bundle-*.cleanup"))
    assert not list(tmp_path.glob(".bundle-*.backup"))
    assert "cleanup failed" in str(error.value)
    assert "PermissionError" in str(error.value)
    assert "preserved recovery path" in str(error.value)
    assert str(stage) in str(error.value)
    assert _snapshot_tree(source) == source_before
    assert (_snapshot_tree(destination) if destination.exists() else None) == old
    assert opened == set()
    assert destructive == []


def test_failed_stage_cleanup_never_deletes_a_substituted_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "bundle"
    displaced_stage = tmp_path / "invocation-stage-original-inode"
    replacement_marker = b"replacement owned by another creator"

    def substitute_stage_then_fail(stage: Path, *_args: object) -> None:
        stage.rename(displaced_stage)
        stage.mkdir(mode=0o700)
        (stage / "marker").write_bytes(replacement_marker)
        raise OSError("injected write failure after stage substitution")

    monkeypatch.setattr(compiler_module, "_write_database", substitute_stage_then_fail)

    with pytest.raises(KnowledgeCompilationError, match="preserved recovery"):
        compile_knowledge_bundle(source, destination)

    replacements = list(tmp_path.glob(".bundle-*.stage"))
    assert len(replacements) == 1
    assert (replacements[0] / "marker").read_bytes() == replacement_marker
    assert displaced_stage.is_dir()
    assert not destination.exists()


def test_database_entry_swap_after_safe_create_never_writes_external_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "bundle"
    outside = tmp_path / "outside.sqlite"
    with sqlite3.connect(outside) as connection:
        connection.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
        connection.execute("INSERT INTO sentinel VALUES ('unchanged')")
    outside_before = outside.read_bytes()

    real_open = compiler_module.os.open
    real_close = compiler_module.os.close
    database_descriptor: int | None = None
    attacked = False

    def record_database_open(
        path: object, flags: int, *args: object, **kwargs: object
    ) -> int:
        nonlocal database_descriptor
        descriptor = real_open(path, flags, *args, **kwargs)
        if path == "knowledge.sqlite" and flags & os.O_EXCL:
            database_descriptor = descriptor
        return descriptor

    def swap_database_entry_on_close(descriptor: int) -> None:
        nonlocal attacked
        if descriptor == database_descriptor and not attacked:
            stage = next(tmp_path.glob(".bundle-*.stage"))
            database = stage / "knowledge.sqlite"
            database.unlink()
            database.symlink_to(outside)
            attacked = True
        real_close(descriptor)

    monkeypatch.setattr(compiler_module.os, "open", record_database_open)
    monkeypatch.setattr(compiler_module.os, "close", swap_database_entry_on_close)

    with pytest.raises(KnowledgeCompilationError):
        compile_knowledge_bundle(source, destination)

    assert attacked
    assert outside.read_bytes() == outside_before
    with sqlite3.connect(outside) as connection:
        assert connection.execute("SELECT value FROM sentinel").fetchall() == [
            ("unchanged",)
        ]
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall() == [("sentinel",)]
    assert not destination.exists()


@pytest.mark.parametrize(
    ("artifact", "replacement"),
    [
        ("knowledge.sqlite", "symlink"),
        ("knowledge.sqlite", "directory"),
        ("knowledge.sqlite", "fifo"),
        ("evidence-coverage.json", "symlink"),
        ("evidence-coverage.json", "directory"),
        ("evidence-coverage.json", "fifo"),
        ("knowledge.sqlite-wal", "extra"),
        ("knowledge.sqlite-journal", "extra"),
        ("unexpected", "extra"),
    ],
)
def test_staged_symlink_nonregular_sidecar_and_extra_are_rejected_before_promotion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact: str,
    replacement: str,
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "bundle"
    real_entries = compiler_module._stage_entries
    attacked = False

    def attack(stage: Path, *args: object) -> object:
        nonlocal attacked
        if not attacked:
            attacked = True
            target = stage / artifact
            if replacement != "extra":
                target.unlink()
            if replacement == "symlink":
                target.symlink_to(source / "bundle.yaml")
            elif replacement == "directory":
                target.mkdir()
            elif replacement == "fifo":
                os.mkfifo(target)
            else:
                target.write_bytes(b"extra")
        return real_entries(stage, *args)

    monkeypatch.setattr(compiler_module, "_stage_entries", attack)
    with pytest.raises(KnowledgeCompilationError, match="stage|artifact"):
        compile_knowledge_bundle(source, destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".bundle-*.stage"))


def _mutate_release_content(source: Path) -> str:
    path = source / f"categories/{RELEASED_CATEGORY_IDS[0]}/identities.yaml"
    mutate_yaml(
        path,
        lambda document: document["category"].__setitem__(
            "display_name", "Changed category display"
        ),
    )
    documents = load_evidence_documents(source)
    return logical_content_sha256(normalized_sql_rows(documents))


@pytest.mark.parametrize("parent_fsync_index", [0, 1])
def test_existing_destination_parent_fsync_failure_rolls_back_old_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    parent_fsync_index: int,
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "bundle"
    old = compile_knowledge_bundle(source, destination)
    old_tree = _snapshot_tree(destination)
    _mutate_release_content(source)
    real_fsync = compiler_module._fsync_directory
    parent_calls = 0

    def fail_selected(path: Path) -> None:
        nonlocal parent_calls
        if Path(path) == destination.parent:
            current = parent_calls
            parent_calls += 1
            if current == parent_fsync_index:
                raise OSError("injected promotion parent fsync failure")
        real_fsync(path)

    monkeypatch.setattr(compiler_module, "_fsync_directory", fail_selected)
    with pytest.raises(KnowledgeCompilationError, match="fsync failure"):
        compile_knowledge_bundle(source, destination)
    assert _snapshot_tree(destination) == old_tree
    assert _metadata(destination / "knowledge.sqlite")["content_sha256"] == old.content_sha256
    assert not list(tmp_path.glob(".bundle-*.stage"))
    assert not list(tmp_path.glob(".bundle-*.backup"))


def test_final_parent_fsync_failure_keeps_new_bundle_and_has_no_backup_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "bundle"
    compile_knowledge_bundle(source, destination)
    new_hash = _mutate_release_content(source)
    real_fsync = compiler_module._fsync_directory
    parent_calls = 0

    def fail_final(path: Path) -> None:
        nonlocal parent_calls
        if Path(path) == destination.parent:
            current = parent_calls
            parent_calls += 1
            if current == 2:
                raise OSError("injected final durability failure")
        real_fsync(path)

    monkeypatch.setattr(compiler_module, "_fsync_directory", fail_final)
    with pytest.raises(KnowledgeCompilationError, match="final parent fsync") as error:
        compile_knowledge_bundle(source, destination)
    assert _metadata(destination / "knowledge.sqlite")["content_sha256"] == new_hash
    assert "backup" not in str(error.value).lower()
    assert not list(tmp_path.glob(".bundle-*.backup"))


def test_backup_removal_failure_keeps_new_bundle_and_exact_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "bundle"
    old = compile_knowledge_bundle(source, destination)
    new_hash = _mutate_release_content(source)
    real_remove = compiler_module._remove_directory_contents

    def fail_backup(descriptor: int) -> None:
        if str(compiler_module._descriptor_path(descriptor)).endswith(".backup"):
            raise OSError("injected backup removal failure")
        real_remove(descriptor)

    monkeypatch.setattr(compiler_module, "_remove_directory_contents", fail_backup)
    with pytest.raises(KnowledgeCompilationError, match="backup cleanup failed") as error:
        compile_knowledge_bundle(source, destination)
    backups = list(tmp_path.glob(".bundle-*.backup"))
    assert len(backups) == 1
    assert str(backups[0]) in str(error.value)
    assert _metadata(destination / "knowledge.sqlite")["content_sha256"] == new_hash
    assert _metadata(backups[0] / "knowledge.sqlite")["content_sha256"] == old.content_sha256


def test_restore_failure_preserves_stage_and_backup_recovery_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "bundle"
    compile_knowledge_bundle(source, destination)
    _mutate_release_content(source)
    real_replace = compiler_module._rename_noreplace

    def fail_promotion_and_restore(source_path: object, destination_path: object, *args: object) -> None:
        source_path = Path(source_path)
        destination_path = Path(destination_path)
        if source_path.name.endswith(".stage") and destination_path == destination:
            raise OSError("injected promotion failure")
        if source_path.name.endswith(".backup") and destination_path == destination:
            raise OSError("injected restore failure")
        real_replace(source_path, destination_path, *args)

    monkeypatch.setattr(compiler_module, "_rename_noreplace", fail_promotion_and_restore)
    with pytest.raises(KnowledgeCompilationError, match="restore previous") as error:
        compile_knowledge_bundle(source, destination)
    stages = list(tmp_path.glob(".bundle-*.stage"))
    backups = list(tmp_path.glob(".bundle-*.backup"))
    assert len(stages) == len(backups) == 1
    assert str(stages[0]) in str(error.value)
    assert str(backups[0]) in str(error.value)
    assert not destination.exists()


def test_move_aside_failure_preserves_new_destination_and_old_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "bundle"
    old = compile_knowledge_bundle(source, destination)
    new_hash = _mutate_release_content(source)
    real_replace = compiler_module._rename_noreplace
    real_fsync = compiler_module._fsync_directory
    parent_calls = 0

    def fail_move_aside(source_path: object, destination_path: object, *args: object) -> None:
        if Path(source_path) == destination and str(destination_path).endswith(".stage"):
            raise OSError("injected move-aside failure")
        real_replace(source_path, destination_path, *args)

    def fail_new_fsync(path: Path) -> None:
        nonlocal parent_calls
        if Path(path) == destination.parent:
            current = parent_calls
            parent_calls += 1
            if current == 1:
                raise OSError("injected new-destination fsync failure")
        real_fsync(path)

    monkeypatch.setattr(compiler_module, "_rename_noreplace", fail_move_aside)
    monkeypatch.setattr(compiler_module, "_fsync_directory", fail_new_fsync)
    with pytest.raises(KnowledgeCompilationError, match="move new destination aside") as error:
        compile_knowledge_bundle(source, destination)
    backups = list(tmp_path.glob(".bundle-*.backup"))
    assert len(backups) == 1
    assert str(destination) in str(error.value)
    assert str(backups[0]) in str(error.value)
    assert _metadata(destination / "knowledge.sqlite")["content_sha256"] == new_hash
    assert _metadata(backups[0] / "knowledge.sqlite")["content_sha256"] == old.content_sha256


@pytest.mark.parametrize(
    ("seam", "artifact"),
    [
        ("database-write", None),
        ("coverage-write", None),
        ("file-fsync", "knowledge.sqlite"),
        ("file-fsync", "evidence-coverage.json"),
        ("reopen", None),
        ("stage-fsync", None),
    ],
)
def test_each_pre_promotion_write_fsync_and_reopen_failure_cleans_only_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    seam: str,
    artifact: str | None,
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "bundle"
    unrelated = tmp_path / ".bundle-unrelated.stage"
    unrelated.mkdir()

    if seam == "database-write":
        monkeypatch.setattr(
            compiler_module,
            "_write_database",
            lambda *_args: (_ for _ in ()).throw(OSError("database write failed")),
        )
    elif seam == "coverage-write":
        monkeypatch.setattr(
            compiler_module,
            "_write_coverage",
            lambda *_args: (_ for _ in ()).throw(OSError("coverage write failed")),
        )
    elif seam == "file-fsync":
        real_fsync_file = compiler_module._fsync_stage_regular

        def fail_artifact(
            stage: Path,
            name: str,
            stage_identity: tuple[int, int] | None = None,
        ) -> None:
            if name == artifact:
                raise OSError(f"{name} fsync failed")
            real_fsync_file(stage, name, stage_identity)

        monkeypatch.setattr(compiler_module, "_fsync_stage_regular", fail_artifact)
    elif seam == "reopen":
        monkeypatch.setattr(
            compiler_module,
            "_verify_staged_bundle",
            lambda *_args: (_ for _ in ()).throw(sqlite3.OperationalError("reopen failed")),
        )
    else:
        real_fsync_directory = compiler_module._fsync_stage_directory

        def fail_stage(path: Path, stage_identity: tuple[int, int]) -> None:
            if str(path).endswith(".stage"):
                raise OSError("stage directory fsync failed")
            real_fsync_directory(path, stage_identity)

        monkeypatch.setattr(compiler_module, "_fsync_stage_directory", fail_stage)

    with pytest.raises(KnowledgeCompilationError):
        compile_knowledge_bundle(source, destination)
    assert not destination.exists()
    assert unrelated.is_dir()
    assert list(tmp_path.glob(".bundle-*.stage")) == [unrelated]
    assert not list(tmp_path.glob(".bundle-*.backup"))


def test_absent_destination_promotion_fsync_failure_rolls_back_to_absence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "bundle"
    real_fsync = compiler_module._fsync_directory
    failed = False

    def fail_first_parent(path: Path) -> None:
        nonlocal failed
        if Path(path) == destination.parent and not failed:
            failed = True
            raise OSError("promoted destination fsync failed")
        real_fsync(path)

    monkeypatch.setattr(compiler_module, "_fsync_directory", fail_first_parent)
    with pytest.raises(KnowledgeCompilationError, match="fsync failed"):
        compile_knowledge_bundle(source, destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".bundle-*.stage"))
    assert not list(tmp_path.glob(".bundle-*.backup"))


def test_old_destination_rename_failure_preserves_old_and_cleans_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "bundle"
    old_tree = _snapshot_tree(destination) if destination.exists() else None
    compile_knowledge_bundle(source, destination)
    old_tree = _snapshot_tree(destination)
    _mutate_release_content(source)
    real_replace = compiler_module._rename_noreplace

    def fail_old(source_path: object, destination_path: object, *args: object) -> None:
        if Path(source_path) == destination and str(destination_path).endswith(".backup"):
            raise OSError("old destination rename failed")
        real_replace(source_path, destination_path, *args)

    monkeypatch.setattr(compiler_module, "_rename_noreplace", fail_old)
    with pytest.raises(KnowledgeCompilationError, match="rename failed"):
        compile_knowledge_bundle(source, destination)
    assert _snapshot_tree(destination) == old_tree
    assert not list(tmp_path.glob(".bundle-*.stage"))
    assert not list(tmp_path.glob(".bundle-*.backup"))


def test_rollback_parent_fsync_failure_preserves_both_recovery_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "bundle"
    old = compile_knowledge_bundle(source, destination)
    new_hash = _mutate_release_content(source)
    real_replace = compiler_module._rename_noreplace
    real_fsync = compiler_module._fsync_directory
    parent_calls = 0

    def fail_stage_rename(source_path: object, destination_path: object, *args: object) -> None:
        if str(source_path).endswith(".stage") and Path(destination_path) == destination:
            raise OSError("stage rename failed")
        real_replace(source_path, destination_path, *args)

    def fail_rollback_fsync(path: Path) -> None:
        nonlocal parent_calls
        if Path(path) == destination.parent:
            current = parent_calls
            parent_calls += 1
            if current == 1:
                raise OSError("rollback fsync failed")
        real_fsync(path)

    monkeypatch.setattr(compiler_module, "_rename_noreplace", fail_stage_rename)
    monkeypatch.setattr(compiler_module, "_fsync_directory", fail_rollback_fsync)
    with pytest.raises(KnowledgeCompilationError, match="rollback parent fsync") as error:
        compile_knowledge_bundle(source, destination)
    stages = list(tmp_path.glob(".bundle-*.stage"))
    backups = list(tmp_path.glob(".bundle-*.backup"))
    assert len(stages) == len(backups) == 1
    assert str(stages[0]) in str(error.value)
    assert str(backups[0]) in str(error.value)
    assert not destination.exists()
    assert _metadata(stages[0] / "knowledge.sqlite")["content_sha256"] == new_hash
    assert _metadata(backups[0] / "knowledge.sqlite")["content_sha256"] == old.content_sha256


def test_cleanup_failure_preserves_exact_stage_and_reports_both_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "bundle"
    monkeypatch.setattr(
        compiler_module,
        "_write_database",
        lambda *_args: (_ for _ in ()).throw(OSError("original write failure")),
    )
    real_remove = compiler_module._remove_directory_contents

    def fail_stage_cleanup(descriptor: int) -> None:
        if str(compiler_module._descriptor_path(descriptor)).endswith(".stage"):
            raise OSError("stage cleanup failure")
        real_remove(descriptor)

    monkeypatch.setattr(compiler_module, "_remove_directory_contents", fail_stage_cleanup)
    with pytest.raises(KnowledgeCompilationError) as error:
        compile_knowledge_bundle(source, destination)
    stages = list(tmp_path.glob(".bundle-*.stage"))
    assert len(stages) == 1
    assert "original write failure" in str(error.value)
    assert "stage cleanup failure" in str(error.value)
    assert str(stages[0]) in str(error.value)
    assert not destination.exists()


@pytest.mark.parametrize("helper", ["directory", "regular"])
def test_stage_open_helpers_close_every_descriptor_when_fstat_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    helper: str,
) -> None:
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "artifact").write_bytes(b"artifact")
    real_open = compiler_module.os.open
    real_close = compiler_module.os.close
    real_fstat = compiler_module.os.fstat
    opened: set[int] = set()
    fstat_calls = 0
    failure_call = 1 if helper == "directory" else 2

    def tracked_open(*args: object, **kwargs: object) -> int:
        descriptor = real_open(*args, **kwargs)
        opened.add(descriptor)
        return descriptor

    def tracked_close(descriptor: int) -> None:
        real_close(descriptor)
        opened.discard(descriptor)

    def fail_selected_fstat(descriptor: int) -> os.stat_result:
        nonlocal fstat_calls
        fstat_calls += 1
        if fstat_calls == failure_call:
            raise OSError("injected fstat failure")
        return real_fstat(descriptor)

    monkeypatch.setattr(compiler_module.os, "open", tracked_open)
    monkeypatch.setattr(compiler_module.os, "close", tracked_close)
    monkeypatch.setattr(compiler_module.os, "fstat", fail_selected_fstat)
    try:
        with pytest.raises(OSError, match="injected fstat failure"):
            if helper == "directory":
                compiler_module._open_stage_directory(stage)
            else:
                compiler_module._open_stage_regular(stage, "artifact")
        assert opened == set()
    finally:
        for descriptor in tuple(opened):
            real_close(descriptor)
            opened.discard(descriptor)


def test_every_compiler_opened_descriptor_is_closed_on_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    real_open = compiler_module.os.open
    real_close = compiler_module.os.close
    opened: set[int] = set()

    def tracked_open(*args: object, **kwargs: object) -> int:
        descriptor = real_open(*args, **kwargs)
        opened.add(descriptor)
        return descriptor

    def tracked_close(descriptor: int) -> None:
        real_close(descriptor)
        opened.discard(descriptor)

    monkeypatch.setattr(compiler_module.os, "open", tracked_open)
    monkeypatch.setattr(compiler_module.os, "close", tracked_close)
    compile_knowledge_bundle(source, tmp_path / "bundle")
    assert opened == set()


def _intercept_promotion_move(monkeypatch: pytest.MonkeyPatch, attack: Callable) -> None:
    """Inject at the actual move boundary, across the no-replace migration."""
    if hasattr(compiler_module, "_rename_noreplace"):
        import ctypes
        import fcntl
        from types import SimpleNamespace

        library = ctypes.CDLL(None, use_errno=True)
        symbol = "renameatx_np" if sys.platform == "darwin" else "renameat2"
        real_native = getattr(library, symbol)
        real_native.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                                ctypes.c_char_p, ctypes.c_uint)
        real_native.restype = ctypes.c_int

        def parent_path(fd: int) -> Path:
            if sys.platform == "darwin":
                return Path(os.fsdecode(fcntl.fcntl(fd, 50, bytes(1024)).split(b"\0", 1)[0]))
            return Path(os.readlink(f"/proc/self/fd/{fd}"))

        def native(src_fd: int, src: bytes, dst_fd: int, dst: bytes, flags: int) -> int:
            assert src_fd >= 0 and dst_fd >= 0
            assert flags == (4 if sys.platform == "darwin" else 1)
            attack(parent_path(src_fd) / os.fsdecode(src), parent_path(dst_fd) / os.fsdecode(dst))
            return real_native(src_fd, src, dst_fd, dst, flags)

        monkeypatch.setattr(ctypes, "CDLL", lambda *_a, **_k: SimpleNamespace(**{symbol: native}))
        return
    owner = compiler_module if hasattr(compiler_module, "_rename_noreplace") else os
    name = "_rename_noreplace" if owner is compiler_module else "replace"
    real = getattr(owner, name)

    def intercepted(source: object, destination: object, *args: object, **kwargs: object):
        attack(Path(source), Path(destination))
        return real(source, destination, *args, **kwargs)

    monkeypatch.setattr(owner, name, intercepted)


def _sql_constraint_parts(sql: str) -> list[str]:
    """Split the real CREATE TABLE at top-level commas, preserving checks."""
    body = sql[sql.index("(") + 1:sql.rindex(")")]
    depth = 0
    start = 0
    parts = []
    quoted = False
    for index, char in enumerate(body):
        if char == "'":
            quoted = not quoted
        elif not quoted:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            elif char == "," and depth == 0:
                parts.append(body[start:index].strip())
                start = index + 1
    parts.append(body[start:].strip())
    return parts


def _sql_declared_constraints(sql: str) -> list[tuple[str, tuple[str, ...], str]]:
    import re

    constraints = []
    for part in _sql_constraint_parts(sql):
        match = re.match(r"(PRIMARY KEY|UNIQUE|FOREIGN KEY)\s*\(([^)]+)\)", part)
        if match:
            kind = {"PRIMARY KEY": "pk", "UNIQUE": "unique", "FOREIGN KEY": "fk"}[match[1]]
            constraints.append((kind, tuple(v.strip() for v in match[2].split(",")), part))
        elif not part.startswith("CHECK"):
            column = part.split()[0]
            if "NOT NULL" in part:
                constraints.append(("notnull", (column,), "NOT NULL"))
            if "PRIMARY KEY" in part:
                constraints.append(("pk", (column,), f"PRIMARY KEY ({column})"))
            if "UNIQUE" in part:
                constraints.append(("unique", (column,), f"UNIQUE ({column})"))
    return constraints


def test_fix2_every_pk_notnull_unique_and_deferred_fk_rejects_insert(
    source_and_documents: tuple[Path, EvidenceDocuments], tmp_path: Path
) -> None:
    """Removing any one actual constraint permits its isolated invalid INSERT.

    Overlapping constraints are deliberately removed in a private SQL sandbox:
    e.g. UNIQUE(category_id, subtype_id) otherwise hides behind the subtype PK.
    The tested constraint text comes from the compiled artifact, while the
    complete inventory and row-value cases are test-owned.
    """
    source, _ = source_and_documents
    database = tmp_path / "bundle/knowledge.sqlite"
    compile_knowledge_bundle(source, database.parent)
    with sqlite3.connect(database) as baseline:
        schema = dict(baseline.execute("SELECT name,sql FROM sqlite_master WHERE type='table'"))
        rows = {table: baseline.execute(f'SELECT * FROM "{table}"').fetchall()
                for table in TABLE_ORDER}
    rows["lifecycle_excluded_variants"] = [rows["lifecycle_required_variants"][0]]
    expected = {
        ("pk", table, columns) for table, columns in EXPECTED_PRIMARY_KEY_COLUMNS.items()
    } | {
        ("notnull", table, (column,))
        for table, columns in EXPECTED_TABLE_COLUMNS.items() for column in columns
        if (table, column) not in NULLABLE_COLUMNS
    } | {
        ("unique", table, columns) for table, groups in EXPECTED_UNIQUE_COLUMNS.items()
        for columns in groups
    } | {("fk", table, columns) for table, columns, _, _ in EXPECTED_FOREIGN_KEYS}
    actual = {(kind, table, columns) for table, ddl in schema.items()
              for kind, columns, _ in _sql_declared_constraints(ddl)}
    assert actual == expected
    assert {kind: sum(item[0] == kind for item in expected)
            for kind in ("pk", "notnull", "unique", "fk")} == {
                "pk": 26, "notnull": 134, "unique": 20, "fk": 28,
            }
    visited = set()
    for table, ddl in schema.items():
        column_defs = [" ".join(part.split()[:2]) for part in _sql_constraint_parts(ddl)
                       if not part.startswith(("CHECK", "PRIMARY KEY", "UNIQUE", "FOREIGN KEY"))]
        for kind, columns, constraint in _sql_declared_constraints(ddl):
            case = (kind, table, columns)
            row = list(rows[table][0])
            if kind == "notnull":
                row[EXPECTED_TABLE_COLUMNS[table].index(columns[0])] = None
            elif kind == "fk":
                row[EXPECTED_TABLE_COLUMNS[table].index(columns[-1])] = "missing-parent"
            # Positive sensitivity control: deleting exactly the selected
            # constraint from this isolated actual DDL accepts the same INSERT.
            for enabled in (True, False):
                connection = sqlite3.connect(":memory:")
                try:
                    if kind == "fk":
                        parent_name = next(parent for child, cols, parent, _ in EXPECTED_FOREIGN_KEYS
                                           if child == table and cols == columns)
                        for parent, parent_ddl in schema.items():
                            if parent == parent_name:
                                parent_ddl = f'CREATE TABLE "{parent}" (' + ", ".join(
                                    part for part in _sql_constraint_parts(parent_ddl)
                                    if not part.startswith("FOREIGN KEY")
                                ) + ")"
                                connection.execute(parent_ddl)
                                connection.executemany(
                                    f'INSERT INTO "{parent}" VALUES ({",".join("?" for _ in EXPECTED_TABLE_COLUMNS[parent])})',
                                    rows[parent],
                                )
                        connection.commit()
                    defs = list(column_defs)
                    if enabled:
                        if kind == "notnull":
                            index = EXPECTED_TABLE_COLUMNS[table].index(columns[0])
                            defs[index] += " NOT NULL"
                        else:
                            defs.append(constraint)
                    connection.execute(f'CREATE TABLE "{table}" ({", ".join(defs)})')
                    insert = f'INSERT INTO "{table}" VALUES ({",".join("?" for _ in row)})'
                    if kind in {"pk", "unique"}:
                        connection.execute(insert, rows[table][0])
                        connection.commit()
                    connection.execute("PRAGMA foreign_keys=ON")
                    connection.execute("BEGIN")
                    if enabled and kind != "fk":
                        with pytest.raises(sqlite3.IntegrityError, match={
                            "pk": "UNIQUE constraint failed", "unique": "UNIQUE constraint failed",
                            "notnull": "NOT NULL constraint failed",
                        }[kind]):
                            connection.execute(insert, row)
                    else:
                        connection.execute(insert, row)
                        if enabled:
                            # Each of all 28 FKs must defer until COMMIT.
                            with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
                                connection.commit()
                        else:
                            connection.commit()
                except Exception as exc:
                    raise AssertionError(f"constraint case {case}, enabled={enabled}: {exc}") from exc
                finally:
                    connection.close()
            visited.add(case)
    assert visited == expected


# Exact test-owned CHECK inventory, in CREATE TABLE occurrence order. The
# independently frozen whole-schema signature additionally pins each expression.
EXPECTED_CHECK_RULES = {
    "metadata": ("metadata-key",), "sources": (),
    "categories": ("release-range",),
    "subtypes": ("market", "battery", "evidence"),
    "variants": ("battery", "evidence"),
    "identities": ("kind", "market", "battery", "years", "dates", "shape"),
    "identity_aliases": ("ordinal",), "identity_tokens": ("ordinal",),
    "identity_variants": ("ordinal",),
    "lifecycle_records": ("tier", "scope", "endpoint-kind", "lower", "upper",
                          "precedence", "dates", "years", "scope-tier-evidence",
                          "endpoint-coupling", "industry-shape"),
    "lifecycle_required_variants": ("ordinal",),
    "lifecycle_excluded_variants": ("ordinal",),
    "lifecycle_assumptions": ("ordinal",), "industry_averages": (),
    "lifecycle_limitations": ("ordinal",), "components": (),
    "component_templates": ("kind", "scope", "order", "shape"),
    "component_associations": ("position", "status", "evidence"),
    "component_association_notes": ("ordinal",),
    "hazards": ("scope", "severity", "evidence"),
    "hazard_triggers": ("ordinal", "observation"),
    "hazard_actions": ("kind", "ordinal"),
    "policy_rules": ("priority", "outcome", "evidence"),
    "policy_predicates": ("group", "ordinal", "predicate"),
    "coverage_unknowns": ("kind",), "claim_sources": ("kind", "ordinal", "ownership"),
}


def _sql_check_expressions(sql: str) -> list[str]:
    result = []
    for part in _sql_constraint_parts(sql):
        if "CHECK (" not in part:
            continue
        start = part.index("CHECK (") + len("CHECK (")
        depth = 1
        for end in range(start, len(part)):
            if part[end] == "(":
                depth += 1
            elif part[end] == ")":
                depth -= 1
                if depth == 0:
                    result.append(part[start:end])
                    break
    return result


def _check_insert_cases() -> list[tuple[str, str, str, dict, dict]]:
    cases = []

    def add(table: str, rule: str, valid: dict, *invalid: dict) -> None:
        for index, bad in enumerate(invalid):
            cases.append((table, rule, f"{table}.{rule}.{len(cases)}.{index}", valid, bad))

    for table, rule, column, bad_values in (
        ("metadata", "metadata-key", "key", ("other",)),
        ("categories", "release-range", "release_order", (-1, 5)),
        ("subtypes", "market", "market_state", ("other",)),
        ("subtypes", "battery", "battery_architecture", ("other",)),
        ("subtypes", "evidence", "evidence_level", ("A",)),
        ("variants", "battery", "battery_architecture", ("other",)),
        ("variants", "evidence", "evidence_level", ("A",)),
        ("identities", "kind", "identity_kind", ("other",)),
        ("identities", "market", "market_state", ("other",)),
        ("identities", "battery", "battery_architecture", ("other",)),
        ("lifecycle_records", "tier", "resolution_tier", ("other",)),
        ("lifecycle_records", "scope", "scope_kind", ("other",)),
        ("lifecycle_records", "endpoint-kind", "endpoint_kind", ("other",)),
        ("lifecycle_records", "lower", "lower_bound", (0, -1)),
        ("lifecycle_records", "precedence", "precedence", (-1,)),
        ("component_templates", "kind", "template_kind", ("other",)),
        ("component_templates", "scope", "scope_kind", ("other",)),
        ("component_templates", "order", "application_order", (-1,)),
        ("component_associations", "position", "position", (-1,)),
        ("component_associations", "status", "status", ("other", "user_confirmed")),
        ("hazards", "scope", "scope_kind", ("other",)),
        ("hazards", "severity", "severity", ("other",)),
        ("hazard_triggers", "observation", "observation_key", ("other",)),
        ("hazard_actions", "kind", "action_kind", ("other",)),
        ("policy_rules", "priority", "priority", (-1,)),
        ("policy_rules", "outcome", "outcome", ("other",)),
        ("policy_rules", "evidence", "evidence_level", ("other",)),
        ("policy_predicates", "group", "predicate_group", ("other",)),
        ("policy_predicates", "predicate", "predicate", ("other",)),
        ("coverage_unknowns", "kind", "claim_kind", ("policy", "other")),
        ("claim_sources", "kind", "claim_kind", ("other",)),
    ):
        add(table, rule, {}, *({column: value} for value in bad_values))
    for table, rules in EXPECTED_CHECK_RULES.items():
        if "ordinal" in rules:
            add(table, "ordinal", {}, {"ordinal": -1})
    for table in ("identities", "lifecycle_records"):
        add(table, "years", {}, {"model_year_from": 2030, "model_year_to": 2020})
        add(table, "dates", {}, {"applicable_from": "2030-01-01", "applicable_to": "2020-01-01"})
    family = dict(identity_kind="family", identity_id="family", family_id="family",
                  model_id=None, model_name=None, evidence_level="B")
    add("identities", "shape", family, {"family_id": "wrong"}, {"model_id": "model"},
        {"model_name": "Model"}, {"evidence_level": "A"})
    model = dict(identity_kind="model", identity_id="model", model_id="model",
                 model_name="Model", evidence_level="A")
    add("identities", "shape", model, {"model_id": None}, {"model_name": None},
        {"identity_id": "wrong"}, {"evidence_level": "B"})
    add("lifecycle_records", "upper", {"lower_bound": 1, "upper_bound": 2},
        {"lower_bound": -2, "upper_bound": 0}, {"upper_bound": 0.5})
    for scope, tier, evidence in (("model", "exact_model", "A"), ("family", "family", "B"),
                                   ("subtype", "subtype", "B"), ("category", "industry_average", "C")):
        add("lifecycle_records", "scope-tier-evidence",
            dict(scope_kind=scope, resolution_tier=tier, evidence_level=evidence),
            {"resolution_tier": "wrong"}, {"evidence_level": "D"}, {"scope_kind": "wrong"})
    for endpoint, kind in (("service_life", "total_life"), ("capacity_threshold", "capacity_threshold"),
                           ("battery_runtime", "operating_endurance")):
        add("lifecycle_records", "endpoint-coupling", dict(endpoint=endpoint, endpoint_kind=kind),
            {"endpoint_kind": "wrong"})
    industry = dict(resolution_tier="industry_average", subject="device", endpoint="service_life",
                    endpoint_kind="total_life", metric="elapsed_time", unit="years",
                    lower_bound=1, upper_bound=2, applicable_from=None, applicable_to=None,
                    model_year_from=None, model_year_to=None)
    add("lifecycle_records", "industry-shape", industry,
        {"subject": "other"}, {"endpoint": "other"}, {"endpoint_kind": "other"},
        {"metric": "other"}, {"unit": "other"}, {"upper_bound": 1},
        {"applicable_from": "2020-01-01"}, {"applicable_to": "2020-01-01"},
        {"model_year_from": 2020}, {"model_year_to": 2020})
    add("component_templates", "shape", dict(template_kind="standard", category_id="category",
        scope_kind="category", scope_id="category", application_order=0),
        {"scope_kind": "subtype"}, {"scope_id": "other"}, {"application_order": 1})
    for kind in ("modern_overlay", "legacy_overlay"):
        for scope in ("subtype", "family", "model"):
            add("component_templates", "shape", dict(template_kind=kind, scope_kind=scope),
                {"scope_kind": "category"})
    add("component_associations", "evidence", dict(status="unknown", evidence_level=None),
        {"evidence_level": "A"})
    for status in ("commonly_associated", "conditional", "legacy_specific", "exact_model_confirmed", "not_present"):
        add("component_associations", "evidence", dict(status=status, evidence_level="B"),
            {"evidence_level": None}, {"evidence_level": "D"})
    for scope, evidence in (("model", "A"), ("family", "B"), ("subtype", "B"),
                            ("category", "C"), ("category", "D")):
        add("hazards", "evidence", dict(scope_kind=scope, evidence_level=evidence),
            {"evidence_level": "wrong"})
    add("claim_sources", "ownership", dict(claim_kind="policy", category_key=""),
        {"category_key": "0301_computer_mouse"})
    for kind in ("subtype", "variant", "identity", "specific_lifecycle", "industry_average", "component_association", "hazard"):
        add("claim_sources", "ownership", dict(claim_kind=kind, category_key="0301_computer_mouse"),
            {"category_key": ""}, {"category_key": "unreleased"})
    return cases


def test_fix2_every_check_and_conditional_branch_rejects_insert(
    source_and_documents: tuple[Path, EvidenceDocuments], tmp_path: Path
) -> None:
    source, _ = source_and_documents
    database = tmp_path / "bundle/knowledge.sqlite"
    compile_knowledge_bundle(source, database.parent)
    with sqlite3.connect(database) as baseline:
        schema = dict(baseline.execute("SELECT name,sql FROM sqlite_master WHERE type='table'"))
        rows = {table: baseline.execute(f'SELECT * FROM "{table}"').fetchone() for table in TABLE_ORDER}
    rows["lifecycle_excluded_variants"] = rows["lifecycle_required_variants"]
    assert set(schema) == set(EXPECTED_CHECK_RULES)
    checks = {table: _sql_check_expressions(ddl) for table, ddl in schema.items()}
    assert {table: len(values) for table, values in checks.items()} == {
        table: len(rules) for table, rules in EXPECTED_CHECK_RULES.items()
    }
    cases = _check_insert_cases()
    assert sum(map(len, EXPECTED_CHECK_RULES.values())) == 56
    assert len(cases) == 126
    assert {(table, rule) for table, rule, *_ in cases} == {
        (table, rule) for table, rules in EXPECTED_CHECK_RULES.items() for rule in rules
    }
    assert len({name for _, _, name, _, _ in cases}) == len(cases)
    for table, rule, name, valid, invalid in cases:
        columns = EXPECTED_TABLE_COLUMNS[table]
        row = dict(zip(columns, rows[table])) | valid
        bad = row | invalid
        expression = checks[table][EXPECTED_CHECK_RULES[table].index(rule)]
        defs = [" ".join(part.split()[:2]) for part in _sql_constraint_parts(schema[table])
                if not part.startswith(("CHECK", "PRIMARY KEY", "UNIQUE", "FOREIGN KEY"))]
        for enabled in (True, False):
            connection = sqlite3.connect(":memory:")
            try:
                ddl = defs + ([f"CHECK ({expression})"] if enabled else [])
                connection.execute(f'CREATE TABLE "{table}" ({", ".join(ddl)})')
                insert = f'INSERT INTO "{table}" VALUES ({",".join("?" for _ in columns)})'
                connection.execute(insert, tuple(row[c] for c in columns))
                connection.commit()
                connection.execute("BEGIN")
                if enabled:
                    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
                        connection.execute(insert, tuple(bad[c] for c in columns))
                else:
                    connection.execute(insert, tuple(bad[c] for c in columns))
                    connection.commit()
            except Exception as exc:
                raise AssertionError(f"CHECK case {name}, enabled={enabled}: {exc}") from exc
            finally:
                connection.close()


@pytest.mark.parametrize("appearing", ["destination", "backup"])
def test_fix2_atomic_absence_survives_move_seam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, appearing: str
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "bundle"
    if appearing == "backup":
        compile_knowledge_bundle(source, destination)
    before = _snapshot_tree(destination) if destination.exists() else None
    appeared: list[tuple[Path, int]] = []

    def attack(src: Path, dst: Path) -> None:
        if not appeared and ((appearing == "destination" and dst == destination)
                             or (appearing == "backup" and dst.suffix == ".backup")):
            dst.mkdir()
            appeared.append((dst, dst.stat().st_ino))

    _intercept_promotion_move(monkeypatch, attack)
    with pytest.raises(KnowledgeCompilationError):
        compile_knowledge_bundle(source, destination)
    assert len(appeared) == 1
    path, inode = appeared[0]
    assert path.stat().st_ino == inode
    assert list(path.iterdir()) == []
    if before is not None:
        assert _snapshot_tree(destination) == before


@pytest.mark.parametrize("existing", [False, True])
def test_fix2_substituted_stage_is_never_accepted_or_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing: bool
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "bundle"
    if existing:
        compile_knowledge_bundle(source, destination)
    displaced = tmp_path / "genuine-stage"
    foreign: list[int] = []

    def attack(src: Path, dst: Path) -> None:
        if not foreign and src.suffix == ".stage" and dst == destination:
            src.rename(displaced)
            src.mkdir(mode=0o700)
            (src / "foreign-marker").write_text("foreign")
            foreign.append(src.stat().st_ino)

    _intercept_promotion_move(monkeypatch, attack)
    with pytest.raises(KnowledgeCompilationError, match="identity|replaced") as error:
        compile_knowledge_bundle(source, destination)
    assert displaced.is_dir()
    found = [p for p in tmp_path.iterdir() if p.is_dir() and p.stat().st_ino in foreign]
    assert len(found) == 1
    assert (found[0] / "foreign-marker").read_text() == "foreign"
    assert str(found[0]) in str(error.value)


def test_fix2_rollback_never_restores_substituted_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "bundle"
    compile_knowledge_bundle(source, destination)
    displaced = tmp_path / "genuine-backup"
    foreign: list[Path] = []

    def attack(src: Path, dst: Path) -> None:
        if src.suffix == ".stage" and dst == destination:
            backup = next(tmp_path.glob(".bundle-*.backup"))
            backup.rename(displaced)
            backup.mkdir()
            (backup / "foreign-marker").write_text("foreign")
            foreign.append(backup)
            raise OSError("original promotion failure")

    _intercept_promotion_move(monkeypatch, attack)
    with pytest.raises(KnowledgeCompilationError) as error:
        compile_knowledge_bundle(source, destination)
    assert not destination.exists()
    assert (foreign[0] / "foreign-marker").read_text() == "foreign"
    assert displaced.is_dir()
    assert "original promotion failure" in str(error.value)
    assert str(foreign[0]) in str(error.value)


def test_fix3_native_public_backup_source_swap_never_restores_foreign_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "bundle"
    compile_knowledge_bundle(source, destination)
    old = _snapshot_tree(destination)
    new_hash = _mutate_release_content(source)
    source_before = _snapshot_tree(source)
    displaced = tmp_path / "genuine-old-bundle"
    attacked = False

    def attack(src: Path, dst: Path) -> None:
        nonlocal attacked
        if src.suffix == ".stage" and dst == destination:
            raise OSError("original promotion failure")
        # Actual libc seam: public backup -> destination on the old code,
        # public backup -> private holder on the corrected restoration path.
        if src.parent == tmp_path and src.suffix == ".backup" and not attacked:
            attacked = True
            src.rename(displaced)
            src.mkdir()
            (src / "foreign-marker").write_text("foreign")

    _intercept_promotion_move(monkeypatch, attack)
    with pytest.raises(KnowledgeCompilationError) as error:
        compile_knowledge_bundle(source, destination)
    assert attacked
    assert not destination.exists(), "rollback installed a foreign public backup"
    assert _snapshot_tree(displaced) == old
    assert _snapshot_tree(source) == source_before
    foreign = list(tmp_path.rglob("foreign-marker"))
    assert len(foreign) == 1
    assert foreign[0].read_text() == "foreign"
    stages = list(tmp_path.glob(".bundle-*.stage"))
    assert len(stages) == 1
    assert _metadata(stages[0] / "knowledge.sqlite")["content_sha256"] == new_hash
    message = str(error.value)
    assert "original promotion failure" in message
    assert "identity" in message
    for path in (displaced, foreign[0].parent, stages[0]):
        assert str(path) in message


@pytest.mark.parametrize("appears", ["public-backup", "destination", "both"])
def test_fix3_private_restore_does_not_overwrite_reappearing_public_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, appears: str
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "bundle"
    compile_knowledge_bundle(source, destination)
    old = _snapshot_tree(destination)
    new_hash = _mutate_release_content(source)
    foreign: list[Path] = []

    def attack(src: Path, dst: Path) -> None:
        if src.suffix == ".stage" and dst == destination:
            raise OSError("original promotion failure")
        if src.parent.suffix == ".restore" and dst == destination and not foreign:
            paths = ([tmp_path / src.name, destination] if appears == "both" else
                     [tmp_path / src.name if appears == "public-backup" else destination])
            for path in paths:
                path.mkdir()
                (path / "foreign-marker").write_text("foreign")
                foreign.append(path)

    _intercept_promotion_move(monkeypatch, attack)
    with pytest.raises(KnowledgeCompilationError) as error:
        compile_knowledge_bundle(source, destination)
    assert len(foreign) == (2 if appears == "both" else 1)
    for path in foreign:
        assert (path / "foreign-marker").read_text() == "foreign"
        assert str(path) in str(error.value)
    assert "original promotion failure" in str(error.value)
    assert str(foreign[0]) in str(error.value)
    holders = list(tmp_path.glob(".bundle-*.restore"))
    assert len(holders) == (1 if appears == "both" else 0)
    if appears == "public-backup":
        assert _snapshot_tree(destination) == old
        assert not list(tmp_path.glob(".bundle-*.stage"))
    else:
        backup = next((holders[0] if holders else tmp_path).glob(".bundle-*.backup"))
        assert _snapshot_tree(backup) == old
        stage = next(tmp_path.glob(".bundle-*.stage"))
        assert _metadata(stage / "knowledge.sqlite")["content_sha256"] == new_hash
        assert str(backup) in str(error.value)
        assert str(stage) in str(error.value)


@pytest.mark.parametrize("phase", [
    "mkdir", "stat", "open", "fstat", "mode-fstat", "fstat-close", "mode", "holder-fsync",
    "parent-before-detach", "parent-after-detach", "detach-native", "restore-native",
    "retire-rmdir", "retire-parent-fsync", "close", "report-probe",
    "successful-rollback",
])
def test_fix3_restoration_holder_failures_preserve_bundles_and_close_descriptors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "bundle"
    old_hash = compile_knowledge_bundle(source, destination).content_sha256
    new_hash = _mutate_release_content(source)
    source_before = _snapshot_tree(source)
    real_open, real_close, real_fstat = os.open, os.close, os.fstat
    real_mkdir, real_stat, real_fsync = os.mkdir, os.stat, os.fsync
    real_rmdir, real_lstat = os.rmdir, os.lstat
    parent_stat = tmp_path.stat()
    parent_identity = (parent_stat.st_dev, parent_stat.st_ino)
    opened: set[int] = set()
    holder_fds: set[int] = set()
    holders: list[Path] = []
    injected = False
    parent_syncs = 0
    holder_stats = 0

    def fail(at: str | None) -> None:
        nonlocal injected
        if phase == at and not injected:
            injected = True
            raise OSError("injected restoration " + phase)

    def mkdir(path: object, *args: object, **kwargs: object):
        nonlocal injected
        if Path(path).suffix == ".restore":
            fail("mkdir")
            result = real_mkdir(path, *args, **kwargs)
            holders.append(tmp_path / Path(path).name)
            if phase == "mode":
                # Change only this test's newly created private fixture.
                holders[-1].chmod(0o755)
                injected = True
            return result
        return real_mkdir(path, *args, **kwargs)

    def inspect(path: object, *args: object, **kwargs: object):
        if not isinstance(path, int) and Path(path).suffix == ".restore":
            fail("stat")
        return real_stat(path, *args, **kwargs)

    def open_fd(path: object, *args: object, **kwargs: object):
        is_holder = Path(path).suffix == ".restore"
        if is_holder:
            fail("open")
        descriptor = real_open(path, *args, **kwargs)
        opened.add(descriptor)
        if is_holder:
            holder_fds.add(descriptor)
        return descriptor

    def fstat(descriptor: int):
        nonlocal holder_stats
        if descriptor in holder_fds:
            holder_stats += 1
            fail("fstat")
            fail("fstat-close")
            if holder_stats == 2:
                fail("mode-fstat")
        return real_fstat(descriptor)

    def close(descriptor: int):
        was_holder = descriptor in holder_fds
        result = real_close(descriptor)
        opened.discard(descriptor)
        holder_fds.discard(descriptor)
        if was_holder:
            fail("close")
            if phase == "fstat-close":
                raise OSError("injected restoration inner close")
        return result

    def fsync(descriptor: int):
        nonlocal parent_syncs
        if descriptor in holder_fds:
            fail("holder-fsync")
        info = real_fstat(descriptor)
        if holders and (info.st_dev, info.st_ino) == parent_identity:
            at = {0: "parent-before-detach", 1: "parent-after-detach",
                  3: "retire-parent-fsync"}.get(parent_syncs)
            parent_syncs += 1
            fail(at)
        return real_fsync(descriptor)

    def rmdir(path: object, *args: object, **kwargs: object):
        if Path(path).suffix == ".restore":
            fail("retire-rmdir")
            fail("report-probe")
        return real_rmdir(path, *args, **kwargs)

    def lstat(path: object, *args: object, **kwargs: object):
        if phase == "report-probe" and injected and Path(path) in holders:
            raise PermissionError("restoration holder inspection denied")
        return real_lstat(path, *args, **kwargs)

    def attack(src: Path, dst: Path) -> None:
        if src.suffix == ".stage" and dst == destination:
            raise OSError("original promotion failure")
        if src.parent.suffix == ".restore" and dst == destination:
            fail("restore-native")
        if src.parent == tmp_path and dst.parent.suffix == ".restore":
            fail("detach-native")

    _intercept_promotion_move(monkeypatch, attack)
    for name, wrapper in (("mkdir", mkdir), ("stat", inspect), ("open", open_fd),
                          ("fstat", fstat), ("close", close), ("fsync", fsync),
                          ("rmdir", rmdir), ("lstat", lstat)):
        monkeypatch.setattr(os, name, wrapper)
    with pytest.raises(KnowledgeCompilationError) as error:
        compile_knowledge_bundle(source, destination)
    monkeypatch.undo()
    assert injected or phase == "successful-rollback"
    assert not opened, "restoration failure leaked compiler-owned descriptors"
    assert _snapshot_tree(source) == source_before
    hashes = [_metadata(path)["content_sha256"] for path in tmp_path.rglob("knowledge.sqlite")]
    assert sorted(hashes) == sorted([old_hash] if phase == "successful-rollback" else
                                   [old_hash, new_hash])
    message = str(error.value)
    assert "original promotion failure" in message
    if phase != "successful-rollback":
        assert ("mode 0700" if phase == "mode" else "injected restoration " + phase) in message
    else:
        assert not list(tmp_path.glob(".bundle-*.restore"))
        assert not list(tmp_path.glob(".bundle-*.backup"))
        assert not list(tmp_path.glob(".bundle-*.stage"))
    if phase == "fstat-close":
        assert "injected restoration inner close" in message
    for path in tmp_path.rglob("knowledge.sqlite"):
        assert str(path.parent) in message
    for holder in holders:
        if holder.exists():
            assert str(holder) in message
    if phase == "report-probe":
        assert "restoration holder inspection denied" in message


@pytest.mark.parametrize("deny_displaced_probe", [False, True])
def test_fix3_backup_cleanup_reports_displaced_old_and_foreign_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, deny_displaced_probe: bool
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "bundle"
    compile_knowledge_bundle(source, destination)
    old = _snapshot_tree(destination)
    new_hash = _mutate_release_content(source)
    displaced = tmp_path / "genuine-old-bundle"
    foreign: list[Path] = []
    real_fsync, real_lstat = compiler_module._fsync_directory, os.lstat
    calls = 0

    def fsync_then_substitute(path: Path) -> None:
        nonlocal calls
        real_fsync(path)
        if path == destination.parent:
            calls += 1
            if calls == 2:
                backup = next(tmp_path.glob(".bundle-*.backup"))
                backup.rename(displaced)
                backup.mkdir()
                (backup / "foreign-marker").write_text("foreign")
                foreign.append(backup)

    def inspect(path: object, *args: object, **kwargs: object):
        if deny_displaced_probe and foreign and Path(path) == displaced:
            raise PermissionError("displaced old inspection denied")
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(compiler_module, "_fsync_directory", fsync_then_substitute)
    monkeypatch.setattr(os, "lstat", inspect)
    with pytest.raises(KnowledgeCompilationError) as error:
        compile_knowledge_bundle(source, destination)
    monkeypatch.setattr(os, "lstat", real_lstat)
    assert calls == 2
    assert _snapshot_tree(displaced) == old
    assert _metadata(destination / "knowledge.sqlite")["content_sha256"] == new_hash
    assert (foreign[0] / "foreign-marker").read_text() == "foreign"
    message = str(error.value)
    assert "backup cleanup failed" in message
    assert "replaced recovery path" in message
    assert str(displaced) in message
    assert str(foreign[0]) in message
    if deny_displaced_probe:
        assert "displaced old inspection denied" in message


@pytest.mark.parametrize("seam", ["recursive", "bad-mode"])
def test_fix2_cleanup_seam_preserves_foreign_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, seam: str
) -> None:
    destination = tmp_path / "bundle"
    stage = tmp_path / (".bundle-" + "a" * 32 + ".stage")
    displaced = tmp_path / "genuine-stage"
    foreign: list[Path] = []
    real_rmtree, real_rmdir = shutil.rmtree, os.rmdir

    def substitute(path: Path) -> None:
        if path == stage and not foreign:
            path.rename(displaced)
            path.mkdir()
            foreign.append(path)

    def rmtree(path: object, *args: object, **kwargs: object):
        substitute(Path(path))
        return real_rmtree(path, *args, **kwargs)

    def rmdir(path: object, *args: object, **kwargs: object):
        # The obsolete full-path seam must no longer be used by safe cleanup.
        substitute(Path(path))
        return real_rmdir(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", rmtree)
    monkeypatch.setattr(os, "rmdir", rmdir)
    if seam == "recursive":
        stage.mkdir(mode=0o700)
        identity = (stage.stat().st_dev, stage.stat().st_ino)
        try:
            compiler_module._remove_owned_directory(stage, destination, ".stage", identity)
        except KnowledgeCompilationError:
            pass
    else:
        monkeypatch.setattr(compiler_module, "_generated_sibling", lambda *_: stage)
        real_mkdir = Path.mkdir

        def bad_mode(path: Path, *args: object, **kwargs: object):
            real_mkdir(path, *args, **kwargs)
            path.chmod(0o755)

        monkeypatch.setattr(Path, "mkdir", bad_mode)
        with pytest.raises(KnowledgeCompilationError, match="0700"):
            compiler_module._create_stage_directory(destination)
    if foreign:
        assert foreign[0].is_dir(), "cleanup deleted the foreign replacement"
        assert displaced.is_dir()


def test_fix2_recovery_probe_errors_keep_original_and_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "bundle"
    compile_knowledge_bundle(source, destination)
    failed = False
    real_lstat = os.lstat

    def attack(src: Path, dst: Path) -> None:
        nonlocal failed
        if src.suffix == ".stage" and dst == destination:
            failed = True
            raise OSError("original promotion failure")

    def failed_probe(path: object, *args: object, **kwargs: object):
        if failed and str(path).endswith(".backup"):
            raise PermissionError("backup inspection denied")
        return real_lstat(path, *args, **kwargs)

    _intercept_promotion_move(monkeypatch, attack)
    monkeypatch.setattr(os, "lstat", failed_probe)
    with pytest.raises(KnowledgeCompilationError) as error:
        compile_knowledge_bundle(source, destination)
    assert "original promotion failure" in str(error.value)
    assert "backup inspection denied" in str(error.value)
    for path in tmp_path.iterdir():
        if path.suffix in {".stage", ".backup"}:
            assert str(path) in str(error.value)


def test_fix2_cleanup_detach_substitution_preserves_both_objects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "bundle"
    stage = tmp_path / (".bundle-" + "b" * 32 + ".stage")
    stage.mkdir(mode=0o700)
    (stage / "owned").write_text("owned")
    identity = (stage.stat().st_dev, stage.stat().st_ino)
    displaced = tmp_path / "genuine-stage"
    attacked = False

    def attack(src: Path, dst: Path) -> None:
        nonlocal attacked
        if src == stage and not attacked:
            attacked = True
            src.rename(displaced)
            src.mkdir()
            (src / "foreign-marker").write_text("foreign")

    if hasattr(compiler_module, "_rename_noreplace"):
        _intercept_promotion_move(monkeypatch, attack)
    else:
        real = shutil.rmtree

        def intercept(path: Path, *args: object, **kwargs: object):
            attack(path, path)
            return real(path, *args, **kwargs)

        monkeypatch.setattr(shutil, "rmtree", intercept)
    with pytest.raises(KnowledgeCompilationError, match="preserved") as error:
        compiler_module._remove_owned_directory(stage, destination, ".stage", identity)
    assert attacked
    assert (displaced / "owned").read_text() == "owned"
    foreign = list(tmp_path.rglob("foreign-marker"))
    assert len(foreign) == 1
    assert str(foreign[0].parent) in str(error.value)


@pytest.mark.parametrize("failure", ["missing-symbol", "unsupported", "io-error", "invalid-flags"])
def test_fix2_native_rename_failures_are_explicit_without_overwrite_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    import ctypes
    import errno
    from types import SimpleNamespace

    source = tmp_path / "stage"
    source.mkdir()
    (source / "owned").write_text("owned")
    destination = tmp_path / "destination"
    destination.mkdir()
    before = source.stat().st_ino, destination.stat().st_ino
    symbol = "renameatx_np" if sys.platform == "darwin" else "renameat2"
    errors = {"unsupported": errno.ENOTSUP, "io-error": errno.EIO, "invalid-flags": errno.EINVAL}

    def native(*_args: object) -> int:
        ctypes.set_errno(errors[failure])
        return -1

    library = SimpleNamespace() if failure == "missing-symbol" else SimpleNamespace(**{symbol: native})
    monkeypatch.setattr(ctypes, "CDLL", lambda *_a, **_k: library)
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(KnowledgeCompilationError, match="atomic no-replace rename") as error:
            compiler_module._rename_noreplace(source, destination, fd)
        if failure != "missing-symbol":
            assert f"errno {errors[failure]}" in str(error.value)
        assert "\n" not in str(error.value)
    finally:
        os.close(fd)
    assert (source.stat().st_ino, destination.stat().st_ino) == before
    assert (source / "owned").read_text() == "owned"
    assert list(destination.iterdir()) == []


def test_fix2_old_destination_source_swap_at_native_backup_move_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "bundle"
    compile_knowledge_bundle(source, destination)
    before = _snapshot_tree(destination)
    displaced = tmp_path / "genuine-old-bundle"
    attacked = False

    def attack(src: Path, dst: Path) -> None:
        nonlocal attacked
        if src == destination and dst.suffix == ".backup" and not attacked:
            attacked = True
            src.rename(displaced)
            src.mkdir()
            (src / "foreign-marker").write_text("foreign")

    _intercept_promotion_move(monkeypatch, attack)
    with pytest.raises(KnowledgeCompilationError, match="identity") as error:
        compile_knowledge_bundle(source, destination)
    assert attacked
    assert _snapshot_tree(displaced) == before
    foreign = list(tmp_path.rglob("foreign-marker"))
    assert len(foreign) == 1
    assert str(foreign[0].parent) in str(error.value)
    assert str(displaced) in str(error.value)


@pytest.mark.parametrize("substitution", ["directory", "contents"])
@pytest.mark.parametrize("boundary", [2, 3])
def test_fix2_post_fsync_substitution_is_not_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, substitution: str, boundary: int
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "bundle"
    old = compile_knowledge_bundle(source, destination)
    displaced = tmp_path / "genuine-new-bundle"
    real_fsync = compiler_module._fsync_directory
    calls = 0

    def attack(path: Path) -> None:
        nonlocal calls
        real_fsync(path)
        if path == destination.parent:
            calls += 1
            if calls == boundary:
                if substitution == "directory":
                    destination.rename(displaced)
                    destination.mkdir()
                    (destination / "foreign-marker").write_text("foreign")
                else:
                    (destination / "evidence-coverage.json").write_bytes(b"tampered")

    monkeypatch.setattr(compiler_module, "_fsync_directory", attack)
    with pytest.raises(KnowledgeCompilationError):
        compile_knowledge_bundle(source, destination)
    if substitution == "directory":
        assert (destination / "foreign-marker").read_text() == "foreign"
        assert displaced.is_dir()
        assert bool(list(tmp_path.glob(".bundle-*.backup"))) is (boundary == 2)
    elif boundary == 2:
        assert _metadata(destination / "knowledge.sqlite")["content_sha256"] == old.content_sha256
    else:
        assert not list(tmp_path.glob(".bundle-*.backup"))


def test_fix2_recovery_error_formatting_cannot_mask_unprintable_original(tmp_path: Path) -> None:
    class Unprintable(OSError):
        def __repr__(self) -> str:
            raise ValueError("repr failure")

    stage = tmp_path / "stage"
    stage.mkdir()
    error = compiler_module._promotion_error(Unprintable(), [], tmp_path / "bundle", stage, None)
    assert isinstance(error, KnowledgeCompilationError)
    assert "Unprintable" in str(error)
    assert str(stage) in str(error)


def test_fix2_successful_rebuild_cleans_nested_old_bundle_without_following_links(
    tmp_path: Path,
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "bundle"
    (destination / "old/nested").mkdir(parents=True)
    (destination / "old/nested/owned").write_text("old")
    external = tmp_path / "external"
    external.mkdir()
    (external / "foreign-marker").write_text("foreign")
    (destination / "old/link").symlink_to(external, target_is_directory=True)
    before = _snapshot_tree(source)
    compile_knowledge_bundle(source, destination)
    assert (external / "foreign-marker").read_text() == "foreign"
    assert _snapshot_tree(source) == before
    assert sorted(path.name for path in destination.iterdir()) == ["evidence-coverage.json", "knowledge.sqlite"]
    assert not list(tmp_path.glob(".bundle-*"))


@pytest.mark.parametrize("helper", ["regular", "database", "coverage"])
def test_fix2_nested_close_failure_does_not_leak_directory_fd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, helper: str
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    real_open, real_close, real_fstat = os.open, os.close, os.fstat
    opened: dict[int, bool] = {}
    failed = False

    def tracked_open(*args: object, **kwargs: object) -> int:
        fd = real_open(*args, **kwargs)
        opened[fd] = (stat.S_ISREG(real_fstat(fd).st_mode)
                      and Path(args[0]).name in {"knowledge.sqlite", "evidence-coverage.json"})
        return fd

    def failed_close(fd: int) -> None:
        nonlocal failed
        regular = opened.pop(fd, False)
        real_close(fd)
        if regular and not failed:
            failed = True
            raise OSError("artifact close failed")

    monkeypatch.setattr(os, "open", tracked_open)
    monkeypatch.setattr(os, "close", failed_close)
    if helper == "regular":
        real_regular = compiler_module._open_stage_regular

        def fail_regular(stage: Path, name: str, *args: object) -> int:
            def fail_artifact_fstat(fd: int):
                if opened.get(fd):
                    raise OSError("artifact fstat failed")
                return real_fstat(fd)
            with monkeypatch.context() as patch:
                patch.setattr(os, "fstat", fail_artifact_fstat)
                return real_regular(stage, name, *args)

        monkeypatch.setattr(compiler_module, "_open_stage_regular", fail_regular)
        # Arm the close injection only after the writes complete.
        real_entries = compiler_module._stage_entries
        failed = True

        def arm(stage: Path, *args: object):
            nonlocal failed
            failed = False
            return real_entries(stage, *args)

        monkeypatch.setattr(compiler_module, "_stage_entries", arm)
    elif helper == "coverage":
        real_write = compiler_module._write_database
        failed = True

        def write_then_arm(*args: object):
            nonlocal failed
            real_write(*args)
            failed = False

        monkeypatch.setattr(compiler_module, "_write_database", write_then_arm)
    try:
        with pytest.raises(KnowledgeCompilationError, match="artifact close failed"):
            compile_knowledge_bundle(source, tmp_path / "bundle")
        assert failed
        assert opened == {}, f"unclosed descriptors: {opened}"
    finally:
        for fd in opened:
            real_close(fd)


def test_complete_task2_validation_matrix_never_creates_output(
    tmp_path: Path, mutation: object
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    mutation.apply(source)
    output = tmp_path / "missing/bundle"
    with pytest.raises(EvidenceValidationError):
        compile_knowledge_bundle(source, output)
    assert not (tmp_path / "missing").exists()


test_complete_task2_validation_matrix_never_creates_output = pytest.mark.parametrize(
    "mutation", complete_tree_mutations(), ids=lambda mutation: mutation.name
)(test_complete_task2_validation_matrix_never_creates_output)


def _run_cli(*arguments: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(PYTHON), str(ROOT / "scripts/build_knowledge_bundle.py"), *arguments],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_help_is_byte_exact_and_has_no_side_effect(tmp_path: Path) -> None:
    result = _run_cli("--help", cwd=tmp_path)
    assert result.returncode == 0
    assert result.stdout == EXPECTED_HELP
    assert result.stderr == ""
    assert list(tmp_path.iterdir()) == []


def test_cli_argument_error_is_deterministic(tmp_path: Path) -> None:
    result = _run_cli(cwd=tmp_path)
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == (
        "usage: build_knowledge_bundle.py --source PATH --out DIRECTORY "
        "[--print-summary]\n"
        "build_knowledge_bundle.py: error: the following arguments are required: "
        "--source, --out\n"
    )
    assert list(tmp_path.iterdir()) == []


def test_cli_expected_failure_is_one_line_without_traceback(tmp_path: Path) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    mutate_yaml(
        source / "bundle.yaml",
        lambda document: document["bundle"].__setitem__("schema_version", 99),
    )
    result = _run_cli("--source", str(source), "--out", str(tmp_path / "bundle"))
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("error: bundle.yaml: bundle.schema_version:")
    assert result.stderr.endswith("\n")
    assert "Traceback" not in result.stderr


def test_cli_success_and_summary_are_deterministic_across_output_paths(
    tmp_path: Path,
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    quiet = _run_cli("--source", str(source), "--out", str(tmp_path / "quiet"))
    first = _run_cli(
        "--source",
        str(source),
        "--out",
        str(tmp_path / "first"),
        "--print-summary",
    )
    second = _run_cli(
        "--source",
        str(source),
        "--out",
        str(tmp_path / "second"),
        "--print-summary",
    )

    assert (quiet.returncode, quiet.stdout, quiet.stderr) == (0, "", "")
    assert (first.returncode, first.stderr) == (0, "")
    assert (second.returncode, second.stderr) == (0, "")
    assert first.stdout == second.stdout
    lines = first.stdout.splitlines()
    assert lines[:15] == [
        "knowledge bundle summary",
        "schema_version=3",
        "bundle_version=3.0.0",
        "identity_catalog_version=1.0.0",
        "policy_revision=2.0.0",
        "summary.categories=5",
        "summary.canonical_identities=50",
        "summary.subtypes=20",
        "summary.lifecycle_records=15",
        "summary.industry_averages=5",
        "summary.component_templates=15",
        "summary.modern_overlays=5",
        "summary.legacy_overlays=5",
        "summary.hazard_records=5",
        "summary.reviewed_claims=155",
    ]
    assert lines[15] == "summary.unknown_claims=5"
    assert len([line for line in lines if line.startswith("claims ")]) == 35
    assert lines[-2].startswith("content_sha256=")
    assert lines[-1].startswith("coverage_sha256=")
    assert first.stdout.endswith("\n")
    assert str(tmp_path) not in first.stdout


@pytest.mark.parametrize(
    ("floor", "message"),
    [
        (
            "report_lifecycle",
            "0301_computer_mouse requires at least three reviewed specific lifecycle records",
        ),
        (
            "input_battery_variants",
            "0301_computer_mouse requires battery-bearing and battery-free variants",
        ),
    ],
)
def test_compiler_floor_failure_precedes_staging_and_preserves_old_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    floor: str,
    message: str,
) -> None:
    source = make_valid_knowledge_source(tmp_path / "source")
    destination = tmp_path / "bundle"
    compile_knowledge_bundle(source, destination)
    before_source = _snapshot_tree(source)
    before_destination = _snapshot_tree(destination)
    documents = load_evidence_documents(source)
    first = documents.categories[0]
    if floor == "report_lifecycle":
        changed_first = replace(
            first, specific_lifecycles=first.specific_lifecycles[:-1]
        )
    else:
        changed_first = replace(
            first,
            variants=tuple(
                variant
                for variant in first.variants
                if variant.battery_architecture.value == "battery_free"
            ),
        )
    changed_documents = replace(
        documents, categories=(changed_first, *documents.categories[1:])
    )
    monkeypatch.setattr(
        compiler_module,
        "load_evidence_documents",
        lambda _source: changed_documents,
    )
    monkeypatch.setattr(
        compiler_module,
        "coverage_json_bytes",
        lambda _report: pytest.fail("coverage bytes accepted before release floor"),
    )

    with pytest.raises(CoverageError, match=message):
        compile_knowledge_bundle(source, destination)

    missing_destination = tmp_path / "missing/inner/bundle"
    with pytest.raises(CoverageError, match=message):
        compile_knowledge_bundle(source, missing_destination)

    assert _snapshot_tree(source) == before_source
    assert _snapshot_tree(destination) == before_destination
    assert not (tmp_path / "missing").exists()
    assert not list(tmp_path.glob(".bundle-*.stage"))
    assert not list(tmp_path.glob(".bundle-*.backup"))

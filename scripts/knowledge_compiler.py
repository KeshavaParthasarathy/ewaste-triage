"""Compile normalized schema-3 evidence into one atomic knowledge bundle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
from typing import Mapping
import unicodedata
from uuid import uuid4

from scripts.evidence_coverage import (
    CoverageError,
    build_coverage,
    coverage_json_bytes,
    validate_coverage_report,
)
from scripts.knowledge_schema import EvidenceDocuments, load_evidence_documents
from server.evidence_types import KnowledgeManifest, RELEASED_CATEGORY_IDS


class KnowledgeCompilationError(RuntimeError):
    """A stable compiler, path-safety, or promotion failure."""


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

_CATEGORY_RELEASE_ORDER = {
    "0301_computer_mouse": 0,
    "0301_keyboard": 1,
    "0303_laptop": 2,
    "0306_mobile_phone": 3,
    "0401_headphones": 4,
}
_NULLABLE_COLUMNS = {
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
_REAL_COLUMNS = {
    ("lifecycle_records", "lower_bound"),
    ("lifecycle_records", "upper_bound"),
}
_INTEGER_COLUMN_NAMES = {
    "release_order",
    "ordinal",
    "precedence",
    "application_order",
    "position",
    "priority",
    "model_year_from",
    "model_year_to",
}
_COMPUTED_METADATA_KEYS = frozenset({"content_sha256", "coverage_sha256"})
_SEMANTIC_METADATA_KEYS = frozenset(
    {"schema_version", "bundle_version", "identity_catalog_version", "policy_revision"}
)

_EVIDENCE = "'A','B','C','D'"
_POLICY_PREDICATES = (
    "identity.state=canonical",
    "identity.state=unknown",
    "observations.age_months=present",
    "observations.age_months=missing",
    "observations.full_charge_cycles=present",
    "observations.full_charge_cycles=missing",
    "observations.operational_state=unknown",
    "observations.operational_state=working",
    "observations.operational_state=intermittent",
    "observations.operational_state=not_working",
    "observations.issue_flags.overheating=true",
    "observations.issue_flags.overheating=false",
    "observations.issue_flags.odor=true",
    "observations.issue_flags.odor=false",
    "observations.issue_flags.swelling_or_battery_damage=true",
    "observations.issue_flags.swelling_or_battery_damage=false",
    "observations.issue_flags.recall=true",
    "observations.issue_flags.recall=false",
    "visible_condition.grade=excellent",
    "visible_condition.grade=good",
    "visible_condition.grade=fair",
    "visible_condition.grade=poor",
    "visible_condition.grade=critical",
    "visible_condition.grade=unknown",
    "visible_condition.image_sufficiency=sufficient",
    "visible_condition.image_sufficiency=insufficient",
    "visible_condition.image_sufficiency=unknown",
    "lifecycle.resolution=resolved",
    "lifecycle.resolution=unknown",
    "lifecycle.resolution=unavailable",
    "lifecycle.required_usage=present",
    "lifecycle.required_usage=missing",
    "lifecycle.position=within_reference",
    "lifecycle.position=at_or_beyond_reference",
    "lifecycle.position=not_calculable",
    "component_decisions.any_present=true",
    "component_decisions.any_present=false",
    "hazards.triggered_severity=none",
    "hazards.triggered_severity=advisory",
    "hazards.triggered_severity=caution",
    "hazards.triggered_severity=urgent",
)


def _sql_values(values: tuple[str, ...]) -> str:
    return ",".join("'" + value.replace("'", "''") + "'" for value in values)


_SCHEMA_STATEMENTS = (
    """CREATE TABLE metadata (
        key TEXT NOT NULL PRIMARY KEY,
        value TEXT NOT NULL,
        CHECK (key IN ('schema_version','bundle_version','identity_catalog_version',
                       'policy_revision','content_sha256','coverage_sha256'))
    )""",
    """CREATE TABLE sources (
        source_id TEXT NOT NULL PRIMARY KEY,
        title TEXT NOT NULL,
        publisher TEXT NOT NULL,
        canonical_url TEXT NOT NULL,
        publication_or_revision_date TEXT NOT NULL,
        accessed_on TEXT NOT NULL,
        license_or_use_basis TEXT NOT NULL,
        reviewed_by TEXT NOT NULL,
        reviewed_on TEXT NOT NULL
    )""",
    """CREATE TABLE categories (
        category_id TEXT NOT NULL PRIMARY KEY,
        display_name TEXT NOT NULL,
        release_order INTEGER NOT NULL UNIQUE,
        CHECK (release_order BETWEEN 0 AND 4)
    )""",
    """CREATE TABLE subtypes (
        subtype_id TEXT NOT NULL PRIMARY KEY,
        category_id TEXT NOT NULL,
        display_name TEXT NOT NULL,
        market_state TEXT NOT NULL CHECK (market_state IN ('current','discontinued','legacy')),
        battery_architecture TEXT NOT NULL CHECK (battery_architecture IN ('battery_free','battery_bearing')),
        evidence_level TEXT NOT NULL CHECK (evidence_level = 'B'),
        UNIQUE (category_id, subtype_id),
        FOREIGN KEY (category_id) REFERENCES categories(category_id)
            DEFERRABLE INITIALLY DEFERRED
    )""",
    """CREATE TABLE variants (
        variant_id TEXT NOT NULL PRIMARY KEY,
        category_id TEXT NOT NULL,
        subtype_id TEXT NOT NULL,
        display_name TEXT NOT NULL,
        battery_architecture TEXT NOT NULL CHECK (battery_architecture IN ('battery_free','battery_bearing')),
        evidence_level TEXT NOT NULL CHECK (evidence_level = 'B'),
        FOREIGN KEY (category_id) REFERENCES categories(category_id)
            DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY (category_id, subtype_id)
            REFERENCES subtypes(category_id, subtype_id)
            DEFERRABLE INITIALLY DEFERRED
    )""",
    """CREATE TABLE identities (
        identity_id TEXT NOT NULL PRIMARY KEY,
        identity_kind TEXT NOT NULL CHECK (identity_kind IN ('family','model')),
        category_id TEXT NOT NULL,
        subtype_id TEXT NOT NULL,
        manufacturer_id TEXT NOT NULL,
        manufacturer_name TEXT NOT NULL,
        family_id TEXT NOT NULL,
        family_name TEXT NOT NULL,
        model_id TEXT,
        model_name TEXT,
        display_name TEXT NOT NULL,
        model_year_from INTEGER,
        model_year_to INTEGER,
        applicable_from TEXT,
        applicable_to TEXT,
        market_state TEXT NOT NULL CHECK (market_state IN ('current','discontinued','legacy')),
        battery_architecture TEXT NOT NULL CHECK (battery_architecture IN ('battery_free','battery_bearing')),
        evidence_level TEXT NOT NULL,
        CHECK (model_year_from IS NULL OR model_year_to IS NULL OR model_year_from <= model_year_to),
        CHECK (applicable_from IS NULL OR applicable_to IS NULL OR applicable_from <= applicable_to),
        CHECK (
            (identity_kind = 'family' AND identity_id = family_id
             AND model_id IS NULL AND model_name IS NULL AND evidence_level = 'B')
            OR
            (identity_kind = 'model' AND model_id IS NOT NULL AND model_name IS NOT NULL
             AND identity_id = model_id AND evidence_level = 'A')
        ),
        FOREIGN KEY (category_id) REFERENCES categories(category_id)
            DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY (category_id, subtype_id)
            REFERENCES subtypes(category_id, subtype_id)
            DEFERRABLE INITIALLY DEFERRED
    )""",
    """CREATE TABLE identity_aliases (
        identity_id TEXT NOT NULL,
        ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
        alias TEXT NOT NULL,
        alias_casefold TEXT NOT NULL,
        PRIMARY KEY (identity_id, ordinal),
        UNIQUE (identity_id, alias),
        UNIQUE (identity_id, alias_casefold),
        FOREIGN KEY (identity_id) REFERENCES identities(identity_id)
            DEFERRABLE INITIALLY DEFERRED
    )""",
    """CREATE TABLE identity_tokens (
        identity_id TEXT NOT NULL,
        ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
        token TEXT NOT NULL,
        token_casefold TEXT NOT NULL,
        PRIMARY KEY (identity_id, ordinal),
        UNIQUE (identity_id, token),
        UNIQUE (identity_id, token_casefold),
        FOREIGN KEY (identity_id) REFERENCES identities(identity_id)
            DEFERRABLE INITIALLY DEFERRED
    )""",
    """CREATE TABLE identity_variants (
        identity_id TEXT NOT NULL,
        ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
        variant_id TEXT NOT NULL,
        PRIMARY KEY (identity_id, ordinal),
        UNIQUE (identity_id, variant_id),
        FOREIGN KEY (identity_id) REFERENCES identities(identity_id)
            DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY (variant_id) REFERENCES variants(variant_id)
            DEFERRABLE INITIALLY DEFERRED
    )""",
    """CREATE TABLE lifecycle_records (
        record_id TEXT NOT NULL PRIMARY KEY,
        category_id TEXT NOT NULL,
        resolution_tier TEXT NOT NULL CHECK (resolution_tier IN ('exact_model','family','subtype','industry_average')),
        scope_kind TEXT NOT NULL CHECK (scope_kind IN ('model','family','subtype','category')),
        scope_id TEXT NOT NULL,
        subject TEXT NOT NULL,
        endpoint TEXT NOT NULL,
        endpoint_kind TEXT NOT NULL CHECK (endpoint_kind IN ('total_life','capacity_threshold','operating_endurance')),
        metric TEXT NOT NULL,
        unit TEXT NOT NULL,
        lower_bound REAL NOT NULL CHECK (lower_bound > 0),
        upper_bound REAL NOT NULL CHECK (upper_bound > 0 AND lower_bound <= upper_bound),
        endpoint_qualification TEXT NOT NULL,
        applicable_from TEXT,
        applicable_to TEXT,
        model_year_from INTEGER,
        model_year_to INTEGER,
        precedence INTEGER NOT NULL CHECK (precedence >= 0),
        evidence_level TEXT NOT NULL,
        CHECK (applicable_from IS NULL OR applicable_to IS NULL OR applicable_from <= applicable_to),
        CHECK (model_year_from IS NULL OR model_year_to IS NULL OR model_year_from <= model_year_to),
        CHECK (
            (scope_kind='model' AND resolution_tier='exact_model' AND evidence_level='A') OR
            (scope_kind='family' AND resolution_tier='family' AND evidence_level='B') OR
            (scope_kind='subtype' AND resolution_tier='subtype' AND evidence_level='B') OR
            (scope_kind='category' AND resolution_tier='industry_average' AND evidence_level='C')
        ),
        CHECK (
            (endpoint='service_life' AND endpoint_kind='total_life') OR
            (endpoint='capacity_threshold' AND endpoint_kind='capacity_threshold') OR
            (endpoint NOT IN ('service_life','capacity_threshold') AND endpoint_kind='operating_endurance')
        ),
        CHECK (
            resolution_tier != 'industry_average' OR
            (subject='device' AND endpoint='service_life' AND endpoint_kind='total_life'
             AND metric='elapsed_time' AND unit='years' AND lower_bound < upper_bound
             AND applicable_from IS NULL AND applicable_to IS NULL
             AND model_year_from IS NULL AND model_year_to IS NULL)
        ),
        FOREIGN KEY (category_id) REFERENCES categories(category_id)
            DEFERRABLE INITIALLY DEFERRED
    )""",
    """CREATE TABLE lifecycle_required_variants (
        record_id TEXT NOT NULL,
        ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
        variant_id TEXT NOT NULL,
        PRIMARY KEY (record_id, ordinal),
        UNIQUE (record_id, variant_id),
        FOREIGN KEY (record_id) REFERENCES lifecycle_records(record_id)
            DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY (variant_id) REFERENCES variants(variant_id)
            DEFERRABLE INITIALLY DEFERRED
    )""",
    """CREATE TABLE lifecycle_excluded_variants (
        record_id TEXT NOT NULL,
        ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
        variant_id TEXT NOT NULL,
        PRIMARY KEY (record_id, ordinal),
        UNIQUE (record_id, variant_id),
        FOREIGN KEY (record_id) REFERENCES lifecycle_records(record_id)
            DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY (variant_id) REFERENCES variants(variant_id)
            DEFERRABLE INITIALLY DEFERRED
    )""",
    """CREATE TABLE lifecycle_assumptions (
        record_id TEXT NOT NULL,
        ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
        assumption TEXT NOT NULL,
        PRIMARY KEY (record_id, ordinal),
        UNIQUE (record_id, assumption),
        FOREIGN KEY (record_id) REFERENCES lifecycle_records(record_id)
            DEFERRABLE INITIALLY DEFERRED
    )""",
    """CREATE TABLE industry_averages (
        record_id TEXT NOT NULL PRIMARY KEY,
        population_definition TEXT NOT NULL,
        publication_period TEXT NOT NULL,
        methodology TEXT NOT NULL,
        uncertainty TEXT NOT NULL,
        FOREIGN KEY (record_id) REFERENCES lifecycle_records(record_id)
            DEFERRABLE INITIALLY DEFERRED
    )""",
    """CREATE TABLE lifecycle_limitations (
        record_id TEXT NOT NULL,
        ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
        limitation TEXT NOT NULL,
        PRIMARY KEY (record_id, ordinal),
        UNIQUE (record_id, limitation),
        FOREIGN KEY (record_id) REFERENCES industry_averages(record_id)
            DEFERRABLE INITIALLY DEFERRED
    )""",
    """CREATE TABLE components (
        category_id TEXT NOT NULL,
        component_id TEXT NOT NULL,
        display_name TEXT NOT NULL,
        PRIMARY KEY (category_id, component_id),
        FOREIGN KEY (category_id) REFERENCES categories(category_id)
            DEFERRABLE INITIALLY DEFERRED
    )""",
    """CREATE TABLE component_templates (
        template_id TEXT NOT NULL PRIMARY KEY,
        category_id TEXT NOT NULL,
        template_kind TEXT NOT NULL CHECK (template_kind IN ('standard','modern_overlay','legacy_overlay')),
        scope_kind TEXT NOT NULL CHECK (scope_kind IN ('category','subtype','family','model')),
        scope_id TEXT NOT NULL,
        application_order INTEGER NOT NULL CHECK (application_order >= 0),
        UNIQUE (category_id, template_id),
        UNIQUE (category_id, scope_kind, scope_id, application_order),
        CHECK (
            (template_kind='standard' AND scope_kind='category'
             AND scope_id=category_id AND application_order=0) OR
            (template_kind IN ('modern_overlay','legacy_overlay')
             AND scope_kind IN ('subtype','family','model'))
        ),
        FOREIGN KEY (category_id) REFERENCES categories(category_id)
            DEFERRABLE INITIALLY DEFERRED
    )""",
    """CREATE TABLE component_associations (
        association_id TEXT NOT NULL PRIMARY KEY,
        category_id TEXT NOT NULL,
        template_id TEXT NOT NULL,
        component_id TEXT NOT NULL,
        position INTEGER NOT NULL CHECK (position >= 0),
        status TEXT NOT NULL CHECK (status IN ('commonly_associated','conditional','legacy_specific','exact_model_confirmed','not_present','unknown')),
        applicability TEXT NOT NULL,
        evidence_level TEXT,
        UNIQUE (template_id, position),
        CHECK ((status='unknown' AND evidence_level IS NULL) OR
               (status!='unknown' AND evidence_level IS NOT NULL
                AND evidence_level IN ('A','B','C'))),
        FOREIGN KEY (category_id, template_id)
            REFERENCES component_templates(category_id, template_id)
            DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY (category_id, component_id)
            REFERENCES components(category_id, component_id)
            DEFERRABLE INITIALLY DEFERRED
    )""",
    """CREATE TABLE component_association_notes (
        association_id TEXT NOT NULL,
        ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
        note TEXT NOT NULL,
        PRIMARY KEY (association_id, ordinal),
        UNIQUE (association_id, note),
        FOREIGN KEY (association_id) REFERENCES component_associations(association_id)
            DEFERRABLE INITIALLY DEFERRED
    )""",
    """CREATE TABLE hazards (
        hazard_id TEXT NOT NULL PRIMARY KEY,
        category_id TEXT NOT NULL,
        component_id TEXT NOT NULL,
        scope_kind TEXT NOT NULL CHECK (scope_kind IN ('model','family','subtype','category')),
        scope_id TEXT NOT NULL,
        applicability TEXT NOT NULL,
        severity TEXT NOT NULL CHECK (severity IN ('advisory','caution','urgent')),
        evidence_level TEXT NOT NULL,
        CHECK ((scope_kind='model' AND evidence_level='A') OR
               (scope_kind='family' AND evidence_level='B') OR
               (scope_kind='subtype' AND evidence_level='B') OR
               (scope_kind='category' AND evidence_level IN ('C','D'))),
        FOREIGN KEY (category_id, component_id)
            REFERENCES components(category_id, component_id)
            DEFERRABLE INITIALLY DEFERRED
    )""",
    """CREATE TABLE hazard_triggers (
        hazard_id TEXT NOT NULL,
        ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
        observation_key TEXT NOT NULL CHECK (observation_key IN (
            'observations.issue_flags.overheating','observations.issue_flags.odor',
            'observations.issue_flags.swelling_or_battery_damage',
            'observations.issue_flags.recall')),
        PRIMARY KEY (hazard_id, ordinal),
        UNIQUE (hazard_id, observation_key),
        FOREIGN KEY (hazard_id) REFERENCES hazards(hazard_id)
            DEFERRABLE INITIALLY DEFERRED
    )""",
    """CREATE TABLE hazard_actions (
        hazard_id TEXT NOT NULL,
        action_kind TEXT NOT NULL CHECK (action_kind IN ('immediate','follow_up','handling','disposal')),
        ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
        action_text TEXT NOT NULL,
        PRIMARY KEY (hazard_id, action_kind, ordinal),
        UNIQUE (hazard_id, action_kind, action_text),
        FOREIGN KEY (hazard_id) REFERENCES hazards(hazard_id)
            DEFERRABLE INITIALLY DEFERRED
    )""",
    """CREATE TABLE policy_rules (
        rule_id TEXT NOT NULL PRIMARY KEY,
        priority INTEGER NOT NULL UNIQUE CHECK (priority >= 0),
        outcome TEXT NOT NULL CHECK (outcome IN ('reuse','repair','parts_recovery','specialist_handling','certified_recycling','more_information_needed')),
        rationale TEXT NOT NULL,
        evidence_level TEXT NOT NULL CHECK (evidence_level IN ('A','B','C','D'))
    )""",
    f"""CREATE TABLE policy_predicates (
        rule_id TEXT NOT NULL,
        predicate_group TEXT NOT NULL CHECK (predicate_group IN ('all','any')),
        ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
        predicate TEXT NOT NULL CHECK (predicate IN ({_sql_values(_POLICY_PREDICATES)})),
        PRIMARY KEY (rule_id, predicate_group, ordinal),
        UNIQUE (rule_id, predicate),
        FOREIGN KEY (rule_id) REFERENCES policy_rules(rule_id)
            DEFERRABLE INITIALLY DEFERRED
    )""",
    """CREATE TABLE coverage_unknowns (
        category_id TEXT NOT NULL,
        claim_kind TEXT NOT NULL CHECK (claim_kind IN ('subtype','variant','identity','specific_lifecycle','industry_average','component_association','hazard')),
        claim_id TEXT NOT NULL,
        reason TEXT NOT NULL,
        evidence_request TEXT NOT NULL,
        PRIMARY KEY (category_id, claim_kind, claim_id),
        FOREIGN KEY (category_id) REFERENCES categories(category_id)
            DEFERRABLE INITIALLY DEFERRED
    )""",
    """CREATE TABLE claim_sources (
        claim_kind TEXT NOT NULL CHECK (claim_kind IN ('subtype','variant','identity','specific_lifecycle','industry_average','component_association','hazard','policy')),
        category_key TEXT NOT NULL,
        claim_id TEXT NOT NULL,
        ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
        source_id TEXT NOT NULL,
        PRIMARY KEY (claim_kind, category_key, claim_id, ordinal),
        UNIQUE (claim_kind, category_key, claim_id, source_id),
        CHECK ((claim_kind='policy' AND category_key='') OR
               (claim_kind!='policy' AND category_key IN
                ('0301_computer_mouse','0301_keyboard','0303_laptop','0306_mobile_phone','0401_headphones'))),
        FOREIGN KEY (source_id) REFERENCES sources(source_id)
            DEFERRABLE INITIALLY DEFERRED
    )""",
)


def _wire(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    return value


def _normalized_search_key(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).strip().split()).casefold()


def normalized_sql_rows(
    documents: EvidenceDocuments,
) -> Mapping[str, tuple[tuple[object, ...], ...]]:
    projected: dict[str, list[tuple[object, ...]]] = {
        table: [] for table in TABLE_ORDER
    }
    bundle = documents.shared.bundle
    projected["metadata"].extend(
        (
            ("schema_version", str(bundle.schema_version)),
            ("bundle_version", bundle.bundle_version),
            ("identity_catalog_version", bundle.identity_catalog_version),
            ("policy_revision", bundle.policy_revision),
        )
    )

    def add_source(source: object) -> None:
        projected["sources"].append(
            tuple(
                _wire(getattr(source, column))
                for column in EXPECTED_TABLE_COLUMNS["sources"]
            )
        )

    def add_claim_sources(
        kind: str, category_key: str, claim_id: str, source_ids: tuple[str, ...]
    ) -> None:
        projected["claim_sources"].extend(
            (kind, category_key, claim_id, ordinal, source_id)
            for ordinal, source_id in enumerate(source_ids)
        )

    for source in documents.shared.sources:
        add_source(source)
    for policy in documents.shared.policies:
        projected["policy_rules"].append(
            (
                policy.rule_id,
                policy.priority,
                policy.outcome.value,
                policy.rationale,
                policy.evidence_level.value,
            )
        )
        projected["policy_predicates"].extend(
            (policy.rule_id, "all", ordinal, predicate)
            for ordinal, predicate in enumerate(policy.when_all)
        )
        projected["policy_predicates"].extend(
            (policy.rule_id, "any", ordinal, predicate)
            for ordinal, predicate in enumerate(policy.when_any)
        )
        add_claim_sources("policy", "", policy.rule_id, policy.source_ids)

    resolution_tiers = {
        "model": "exact_model",
        "family": "family",
        "subtype": "subtype",
        "category": "industry_average",
    }

    def add_lifecycle(record: object, category_id: str, claim_kind: str) -> None:
        projected["lifecycle_records"].append(
            (
                record.record_id,
                category_id,
                resolution_tiers[record.scope.kind.value],
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
        )
        projected["lifecycle_required_variants"].extend(
            (record.record_id, ordinal, variant_id)
            for ordinal, variant_id in enumerate(record.required_variant_ids)
        )
        projected["lifecycle_excluded_variants"].extend(
            (record.record_id, ordinal, variant_id)
            for ordinal, variant_id in enumerate(record.excluded_variant_ids)
        )
        projected["lifecycle_assumptions"].extend(
            (record.record_id, ordinal, assumption)
            for ordinal, assumption in enumerate(record.assumptions)
        )
        add_claim_sources(claim_kind, category_id, record.record_id, record.source_ids)

    for category in documents.categories:
        category_id = category.category.category_id
        try:
            release_order = _CATEGORY_RELEASE_ORDER[category_id]
        except KeyError as exc:
            raise KnowledgeCompilationError(
                f"unsupported category for release ordering: {category_id}"
            ) from exc
        projected["categories"].append(
            (category_id, category.category.display_name, release_order)
        )
        for source in category.sources:
            add_source(source)
        for subtype in category.subtypes:
            projected["subtypes"].append(
                (
                    subtype.subtype_id,
                    subtype.category_id,
                    subtype.display_name,
                    subtype.market_state.value,
                    subtype.battery_architecture.value,
                    subtype.evidence_level.value,
                )
            )
            add_claim_sources("subtype", category_id, subtype.subtype_id, subtype.source_ids)
        for variant in category.variants:
            projected["variants"].append(
                (
                    variant.variant_id,
                    variant.category_id,
                    variant.subtype_id,
                    variant.display_name,
                    variant.battery_architecture.value,
                    variant.evidence_level.value,
                )
            )
            add_claim_sources("variant", category_id, variant.variant_id, variant.source_ids)
        for identity in category.identities:
            projected["identities"].append(
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
            projected["identity_aliases"].extend(
                (identity.identity_id, ordinal, alias, _normalized_search_key(alias))
                for ordinal, alias in enumerate(identity.aliases)
            )
            projected["identity_tokens"].extend(
                (identity.identity_id, ordinal, token, _normalized_search_key(token))
                for ordinal, token in enumerate(identity.distinguishing_tokens)
            )
            projected["identity_variants"].extend(
                (identity.identity_id, ordinal, variant_id)
                for ordinal, variant_id in enumerate(identity.variant_ids)
            )
            add_claim_sources("identity", category_id, identity.identity_id, identity.source_ids)
        for lifecycle in category.specific_lifecycles:
            add_lifecycle(lifecycle, category_id, "specific_lifecycle")
        for average in category.industry_averages:
            add_lifecycle(average, category_id, "industry_average")
            projected["industry_averages"].append(
                (
                    average.record_id,
                    average.population_definition,
                    average.publication_period,
                    average.methodology,
                    average.uncertainty,
                )
            )
            projected["lifecycle_limitations"].extend(
                (average.record_id, ordinal, limitation)
                for ordinal, limitation in enumerate(average.limitations)
            )
        projected["components"].extend(
            (category_id, component.component_id, component.display_name)
            for component in category.component_definitions
        )
        projected["component_templates"].extend(
            (
                template.template_id,
                category_id,
                template.template_kind.value,
                template.scope.kind.value,
                template.scope.id,
                template.application_order,
            )
            for template in category.component_templates
        )
        for association in category.component_associations:
            projected["component_associations"].append(
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
            projected["component_association_notes"].extend(
                (association.association_id, ordinal, note)
                for ordinal, note in enumerate(association.notes)
            )
            add_claim_sources(
                "component_association",
                category_id,
                association.association_id,
                association.source_ids,
            )
        for hazard in category.hazards:
            projected["hazards"].append(
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
            projected["hazard_triggers"].extend(
                (hazard.hazard_id, ordinal, trigger)
                for ordinal, trigger in enumerate(hazard.trigger_observation_keys)
            )
            for action_kind, actions in (
                ("immediate", hazard.immediate_actions),
                ("follow_up", hazard.follow_up_actions),
                ("handling", hazard.handling_guidance),
                ("disposal", hazard.disposal_guidance),
            ):
                projected["hazard_actions"].extend(
                    (hazard.hazard_id, action_kind, ordinal, action)
                    for ordinal, action in enumerate(actions)
                )
            add_claim_sources("hazard", category_id, hazard.hazard_id, hazard.source_ids)
        projected["coverage_unknowns"].extend(
            (
                unknown.category_id,
                unknown.claim_kind.value,
                unknown.claim_id,
                unknown.reason,
                unknown.evidence_request,
            )
            for unknown in category.unknowns
        )

    normalized: dict[str, tuple[tuple[object, ...], ...]] = {}
    for table in TABLE_ORDER:
        columns = EXPECTED_TABLE_COLUMNS[table]
        key_positions = tuple(
            columns.index(column) for column in EXPECTED_PRIMARY_KEY_COLUMNS[table]
        )
        normalized[table] = tuple(
            sorted(
                projected[table],
                key=lambda row, positions=key_positions: tuple(
                    row[position] for position in positions
                ),
            )
        )
    return normalized


def _validated_logical_tables(
    rows: Mapping[str, tuple[tuple[object, ...], ...]],
) -> list[dict[str, object]]:
    if not isinstance(rows, Mapping) or set(rows) != set(TABLE_ORDER):
        raise KnowledgeCompilationError("logical rows must contain exactly 26 tables")
    tables: list[dict[str, object]] = []
    for table in TABLE_ORDER:
        table_rows = rows[table]
        if not isinstance(table_rows, tuple):
            raise KnowledgeCompilationError(f"{table} rows must be a tuple")
        columns = EXPECTED_TABLE_COLUMNS[table]
        primary_key = EXPECTED_PRIMARY_KEY_COLUMNS[table]
        key_positions = tuple(columns.index(column) for column in primary_key)
        keys: list[tuple[object, ...]] = []
        logical_rows: list[list[object]] = []
        for row_index, row in enumerate(table_rows):
            if not isinstance(row, tuple) or len(row) != len(columns):
                raise KnowledgeCompilationError(
                    f"{table} row {row_index} has the wrong width"
                )
            for column, value in zip(columns, row):
                nullable = (table, column) in _NULLABLE_COLUMNS
                if value is None:
                    if not nullable:
                        raise KnowledgeCompilationError(
                            f"{table}.{column} may not be null"
                        )
                    continue
                if (table, column) in _REAL_COLUMNS:
                    if type(value) is not float or not math.isfinite(value):
                        raise KnowledgeCompilationError(
                            f"{table}.{column} must be a finite float"
                        )
                elif column in _INTEGER_COLUMN_NAMES:
                    if type(value) is not int:
                        raise KnowledgeCompilationError(
                            f"{table}.{column} must be an integer"
                        )
                elif type(value) is not str:
                    raise KnowledgeCompilationError(f"{table}.{column} must be text")
            key = tuple(row[position] for position in key_positions)
            keys.append(key)
            logical_rows.append(list(row))
        if keys != sorted(keys) or len(keys) != len(set(keys)):
            raise KnowledgeCompilationError(
                f"{table} rows must be uniquely sorted by primary key"
            )
        if table == "metadata":
            logical_rows = [
                list(row)
                for row in table_rows
                if row[0] not in _COMPUTED_METADATA_KEYS
            ]
        tables.append(
            {"name": table, "columns": list(columns), "rows": logical_rows}
        )
    return tables


def logical_content_sha256(
    rows: Mapping[str, tuple[tuple[object, ...], ...]],
) -> str:
    payload = {
        "format": "ewaste-knowledge-logical-v1",
        "tables": _validated_logical_tables(rows),
    }
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise KnowledgeCompilationError(
            f"logical rows are not canonical JSON: {exc}"
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class _PathEntry:
    path: Path
    identity: tuple[int, int]


@dataclass
class _PathState:
    source: Path
    destination: Path
    source_chain: tuple[_PathEntry, ...]
    destination_chain: tuple[_PathEntry, ...]
    destination_exists: bool


_STAGE_SUFFIX = ".stage"
_BACKUP_SUFFIX = ".backup"
_UUID_ATTEMPTS = 128


def _absolute_lexical(path: Path) -> Path:
    try:
        return Path(os.path.abspath(os.fspath(path)))
    except (OSError, TypeError, ValueError) as exc:
        raise KnowledgeCompilationError(f"invalid filesystem path: {exc}") from exc


def _path_identity(path: Path) -> tuple[int, int]:
    result = os.lstat(path)
    return (result.st_dev, result.st_ino)


def _path_components(path: Path) -> tuple[Path, ...]:
    if not path.is_absolute():
        raise AssertionError("path components require an absolute path")
    current = Path(path.anchor)
    components = [current]
    for part in path.parts[1:]:
        current = current / part
        components.append(current)
    return tuple(components)


def _capture_directory_chain(
    path: Path, *, label: str, require_final: bool
) -> tuple[tuple[_PathEntry, ...], bool]:
    entries: list[_PathEntry] = []
    exists = True
    for component in _path_components(path):
        try:
            result = os.lstat(component)
        except FileNotFoundError:
            exists = False
            break
        except OSError as exc:
            raise KnowledgeCompilationError(
                f"cannot inspect {label} path {component}: {exc}"
            ) from exc
        if stat.S_ISLNK(result.st_mode):
            raise KnowledgeCompilationError(
                f"unsafe path: symlink in {label}: {component}"
            )
        if not stat.S_ISDIR(result.st_mode):
            raise KnowledgeCompilationError(
                f"unsafe non-directory in {label} path: {component}"
            )
        try:
            identity = _path_identity(component)
        except OSError as exc:
            raise KnowledgeCompilationError(
                f"cannot capture {label} path identity {component}: {exc}"
            ) from exc
        entries.append(_PathEntry(component, identity))
    final_exists = exists and bool(entries) and entries[-1].path == path
    if require_final and not final_exists:
        raise KnowledgeCompilationError(f"{label} directory does not exist: {path}")
    return tuple(entries), final_exists


def _reject_overlap(
    source_chain: tuple[_PathEntry, ...],
    destination_chain: tuple[_PathEntry, ...],
    destination_exists: bool,
) -> None:
    source_root = source_chain[-1].identity
    destination_identities = {entry.identity for entry in destination_chain}
    if source_root in destination_identities:
        raise KnowledgeCompilationError("source and destination must not overlap")
    if destination_exists:
        destination = destination_chain[-1].identity
        if destination in {entry.identity for entry in source_chain}:
            raise KnowledgeCompilationError("source and destination must not overlap")


def _preflight_paths(source: Path, destination: Path) -> _PathState:
    source_chain, _ = _capture_directory_chain(
        source, label="source", require_final=True
    )
    destination_chain, destination_exists = _capture_directory_chain(
        destination, label="destination", require_final=False
    )
    _reject_overlap(source_chain, destination_chain, destination_exists)
    return _PathState(
        source,
        destination,
        source_chain,
        destination_chain,
        destination_exists,
    )


def _require_entries_unchanged(
    expected: tuple[_PathEntry, ...], actual: tuple[_PathEntry, ...], label: str
) -> None:
    actual_by_path = {entry.path: entry.identity for entry in actual}
    for entry in expected:
        if actual_by_path.get(entry.path) != entry.identity:
            raise KnowledgeCompilationError(
                f"unsafe path identity changed for {label}: {entry.path}"
            )


def _recheck_identity_chains(state: _PathState) -> None:
    source_chain, _ = _capture_directory_chain(
        state.source, label="source", require_final=True
    )
    destination_chain, destination_exists = _capture_directory_chain(
        state.destination, label="destination", require_final=False
    )
    _require_entries_unchanged(state.source_chain, source_chain, "source")
    _require_entries_unchanged(
        state.destination_chain, destination_chain, "destination"
    )
    if destination_exists != state.destination_exists:
        raise KnowledgeCompilationError(
            "unsafe path identity changed for destination existence"
        )
    _reject_overlap(source_chain, destination_chain, destination_exists)


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        result = os.fstat(descriptor)
        if not stat.S_ISDIR(result.st_mode):
            raise KnowledgeCompilationError(f"fsync target is not a directory: {path}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _create_missing_destination_parents(state: _PathState) -> None:
    parent_components = _path_components(state.destination.parent)
    existing_paths = {entry.path for entry in state.destination_chain}
    for component in parent_components:
        if component in existing_paths:
            continue
        _recheck_identity_chains(state)
        try:
            component.mkdir(mode=0o755, exist_ok=False)
        except OSError as exc:
            raise KnowledgeCompilationError(
                f"cannot create destination parent {component}: {exc}"
            ) from exc
        try:
            result = os.lstat(component)
            if stat.S_ISLNK(result.st_mode) or not stat.S_ISDIR(result.st_mode):
                raise KnowledgeCompilationError(
                    f"created destination parent is unsafe: {component}"
                )
            entry = _PathEntry(component, _path_identity(component))
            state.destination_chain += (entry,)
            _fsync_directory(component.parent)
        except KnowledgeCompilationError:
            raise
        except OSError as exc:
            raise KnowledgeCompilationError(
                f"cannot fsync destination parent {component.parent}: {exc}"
            ) from exc
        _recheck_identity_chains(state)
        existing_paths.add(component)


def _generated_sibling(destination: Path, suffix: str) -> Path:
    return destination.parent / f".{destination.name}-{uuid4().hex}{suffix}"


def _create_stage_directory(destination: Path) -> tuple[Path, tuple[int, int]]:
    for _attempt in range(_UUID_ATTEMPTS):
        candidate = _generated_sibling(destination, _STAGE_SUFFIX)
        try:
            candidate.mkdir(mode=0o700, exist_ok=False)
        except FileExistsError:
            continue
        except OSError as exc:
            raise KnowledgeCompilationError(
                f"cannot create bundle stage {candidate}: {exc}"
            ) from exc
        try:
            result = os.lstat(candidate)
        except OSError as exc:
            raise KnowledgeCompilationError(
                f"cannot capture created bundle stage identity; preserved at {candidate}: {exc}"
            ) from exc
        identity = (result.st_dev, result.st_ino)
        try:
            if stat.S_ISLNK(result.st_mode) or not stat.S_ISDIR(result.st_mode):
                raise KnowledgeCompilationError(f"bundle stage is unsafe: {candidate}")
            if stat.S_IMODE(result.st_mode) != 0o700:
                raise KnowledgeCompilationError(
                    f"bundle stage does not have mode 0700: {candidate}"
                )
        except BaseException as original:
            try:
                current = os.lstat(candidate)
                if (current.st_dev, current.st_ino) != identity:
                    raise KnowledgeCompilationError(
                        f"created bundle stage identity changed; preserved at {candidate}"
                    )
                os.rmdir(candidate)
            except BaseException as cleanup_error:
                raise KnowledgeCompilationError(
                    f"bundle stage validation failed ({original!r}); cleanup failed "
                    f"({cleanup_error!r}); preserved recovery path: {candidate}"
                ) from original
            raise
        return candidate, identity
    raise KnowledgeCompilationError("could not allocate a unique bundle stage")


def _choose_backup_path(destination: Path) -> Path:
    for _attempt in range(_UUID_ATTEMPTS):
        candidate = _generated_sibling(destination, _BACKUP_SUFFIX)
        try:
            os.lstat(candidate)
        except FileNotFoundError:
            return candidate
        except OSError as exc:
            raise KnowledgeCompilationError(
                f"cannot inspect bundle backup candidate {candidate}: {exc}"
            ) from exc
    raise KnowledgeCompilationError("could not allocate a unique bundle backup")


def _expected_generated_name(destination: Path, suffix: str, name: str) -> bool:
    pattern = rf"\.{re.escape(destination.name)}-[0-9a-f]{{32}}{re.escape(suffix)}\Z"
    return re.fullmatch(pattern, name) is not None


def _remove_owned_directory(
    path: Path,
    destination: Path,
    suffix: str,
    expected_identity: tuple[int, int],
) -> None:
    if path.parent != destination.parent or not _expected_generated_name(
        destination, suffix, path.name
    ):
        raise KnowledgeCompilationError(f"refusing unsafe cleanup path: {path}")
    try:
        result = os.lstat(path)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise KnowledgeCompilationError(f"cannot inspect cleanup path {path}: {exc}") from exc
    if stat.S_ISLNK(result.st_mode) or not stat.S_ISDIR(result.st_mode):
        raise KnowledgeCompilationError(
            f"refusing to clean unsafe recovery path; preserved at {path}"
        )
    if (result.st_dev, result.st_ino) != expected_identity:
        raise KnowledgeCompilationError(
            f"refusing to clean replaced recovery path; preserved at {path}"
        )
    try:
        shutil.rmtree(path)
    except OSError as exc:
        raise KnowledgeCompilationError(
            f"could not clean recovery directory; preserved at {path}: {exc}"
        ) from exc


def _open_stage_directory(
    stage: Path, expected_identity: tuple[int, int] | None = None
) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(stage, flags)
    verified = False
    try:
        result = os.fstat(descriptor)
        if not stat.S_ISDIR(result.st_mode):
            raise KnowledgeCompilationError(f"bundle stage is not a directory: {stage}")
        if expected_identity is not None and (
            result.st_dev,
            result.st_ino,
        ) != expected_identity:
            raise KnowledgeCompilationError(
                f"bundle stage identity changed before open: {stage}"
            )
        verified = True
        return descriptor
    finally:
        if not verified:
            os.close(descriptor)


def _fsync_stage_directory(
    stage: Path, stage_identity: tuple[int, int]
) -> None:
    descriptor = _open_stage_directory(stage, stage_identity)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _open_stage_regular(
    stage: Path,
    name: str,
    stage_identity: tuple[int, int] | None = None,
) -> int:
    stage_descriptor = _open_stage_directory(stage, stage_identity)
    descriptor = -1
    try:
        try:
            before = os.stat(name, dir_fd=stage_descriptor, follow_symlinks=False)
        except OSError as exc:
            raise KnowledgeCompilationError(
                f"cannot inspect staged artifact {name}: {exc}"
            ) from exc
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise KnowledgeCompilationError(
                f"staged artifact is not a regular file: {name}"
            )
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(name, flags, dir_fd=stage_descriptor)
        after = os.fstat(descriptor)
        if not stat.S_ISREG(after.st_mode) or (
            before.st_dev,
            before.st_ino,
        ) != (after.st_dev, after.st_ino):
            raise KnowledgeCompilationError(
                f"staged artifact identity changed while opening: {name}"
            )
        result = descriptor
        descriptor = -1
        return result
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(stage_descriptor)


def _stage_entries(
    stage: Path, stage_identity: tuple[int, int] | None = None
) -> dict[str, os.stat_result]:
    descriptor = _open_stage_directory(stage, stage_identity)
    try:
        entries: dict[str, os.stat_result] = {}
        with os.scandir(descriptor) as iterator:
            for entry in iterator:
                entries[entry.name] = entry.stat(follow_symlinks=False)
    finally:
        os.close(descriptor)
    if set(entries) != {"knowledge.sqlite", "evidence-coverage.json"}:
        raise KnowledgeCompilationError(
            "bundle stage must contain exactly knowledge.sqlite and evidence-coverage.json"
        )
    for name, result in entries.items():
        if stat.S_ISLNK(result.st_mode) or not stat.S_ISREG(result.st_mode):
            raise KnowledgeCompilationError(
                f"staged artifact is not a regular file: {name}"
            )
    return entries


def _fsync_stage_regular(
    stage: Path,
    name: str,
    stage_identity: tuple[int, int] | None = None,
) -> None:
    descriptor = _open_stage_regular(stage, name, stage_identity)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_stage_regular(
    stage: Path,
    name: str,
    stage_identity: tuple[int, int] | None = None,
) -> bytes:
    descriptor = _open_stage_regular(stage, name, stage_identity)
    try:
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    finally:
        os.close(descriptor)


def _schema_signature(
    connection: sqlite3.Connection,
) -> tuple[tuple[object, ...], ...]:
    return tuple(
        connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "ORDER BY type, name, tbl_name, sql"
        )
    )


def _build_expected_schema_signature() -> tuple[tuple[object, ...], ...]:
    connection = sqlite3.connect(":memory:")
    try:
        for statement in _SCHEMA_STATEMENTS:
            connection.execute(statement)
        return _schema_signature(connection)
    finally:
        connection.close()


_EXPECTED_SCHEMA_SIGNATURE = _build_expected_schema_signature()


def _write_database(
    stage: Path,
    rows: Mapping[str, tuple[tuple[object, ...], ...]],
    content_sha256: str,
    coverage_sha256: str,
    stage_identity: tuple[int, int] | None = None,
) -> None:
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        if connection.execute("PRAGMA foreign_keys").fetchone() != (1,):
            raise KnowledgeCompilationError("SQLite foreign keys could not be enabled")
        connection.execute("BEGIN")
        for statement in _SCHEMA_STATEMENTS:
            connection.execute(statement)
        for table in TABLE_ORDER:
            columns = EXPECTED_TABLE_COLUMNS[table]
            table_rows = list(rows[table])
            if table == "metadata":
                table_rows.extend(
                    [
                        ("content_sha256", content_sha256),
                        ("coverage_sha256", coverage_sha256),
                    ]
                )
                table_rows.sort(key=lambda row: row[0])
            placeholders = ",".join("?" for _ in columns)
            connection.executemany(
                f'INSERT INTO "{table}" ({", ".join(columns)}) VALUES ({placeholders})',
                table_rows,
            )
        connection.commit()
        database_bytes = connection.serialize()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()

    stage_descriptor = _open_stage_directory(stage, stage_identity)
    descriptor = -1
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(
            "knowledge.sqlite", flags, 0o600, dir_fd=stage_descriptor
        )
        view = memoryview(database_bytes)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short write for SQLite database")
            view = view[written:]
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(stage_descriptor)


def _write_coverage(
    stage: Path,
    data: bytes,
    stage_identity: tuple[int, int] | None = None,
) -> None:
    stage_descriptor = _open_stage_directory(stage, stage_identity)
    descriptor = -1
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(
            "evidence-coverage.json", flags, 0o600, dir_fd=stage_descriptor
        )
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short write for evidence coverage")
            view = view[written:]
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(stage_descriptor)


def _read_database_rows(
    connection: sqlite3.Connection,
) -> dict[str, tuple[tuple[object, ...], ...]]:
    readback: dict[str, tuple[tuple[object, ...], ...]] = {}
    for table in TABLE_ORDER:
        columns = EXPECTED_TABLE_COLUMNS[table]
        primary_key = EXPECTED_PRIMARY_KEY_COLUMNS[table]
        table_rows = tuple(
            connection.execute(
                f'SELECT {", ".join(columns)} FROM "{table}" '
                f'ORDER BY {", ".join(primary_key)}'
            )
        )
        if table == "metadata":
            table_rows = tuple(
                row for row in table_rows if row[0] not in _COMPUTED_METADATA_KEYS
            )
        readback[table] = table_rows
    return readback


def _readonly_sqlite_from_descriptor(descriptor: int) -> sqlite3.Connection:
    uri = f"file:/dev/fd/{descriptor}?mode=ro&immutable=1"
    return sqlite3.connect(uri, uri=True)


def _verify_staged_bundle(
    stage: Path,
    expected_rows: Mapping[str, tuple[tuple[object, ...], ...]],
    manifest: KnowledgeManifest,
    expected_coverage_bytes: bytes,
    stage_identity: tuple[int, int] | None = None,
) -> None:
    _stage_entries(stage, stage_identity)
    coverage_data = _read_stage_regular(
        stage, "evidence-coverage.json", stage_identity
    )
    if coverage_data != expected_coverage_bytes:
        raise KnowledgeCompilationError("staged coverage bytes changed before reopen")
    try:
        parsed = json.loads(coverage_data)
        validate_coverage_report(parsed)
    except (json.JSONDecodeError, CoverageError) as exc:
        raise KnowledgeCompilationError(f"staged coverage is invalid: {exc}") from exc
    if coverage_json_bytes(parsed) != coverage_data:
        raise KnowledgeCompilationError("staged coverage is not canonical")
    if hashlib.sha256(coverage_data).hexdigest() != manifest.coverage_sha256:
        raise KnowledgeCompilationError("staged coverage hash does not match manifest")

    descriptor = _open_stage_regular(stage, "knowledge.sqlite", stage_identity)
    try:
        connection = _readonly_sqlite_from_descriptor(descriptor)
        try:
            table_names = tuple(
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY rowid"
                )
            )
            if table_names != TABLE_ORDER:
                raise KnowledgeCompilationError("staged database tables do not match schema")
            if _schema_signature(connection) != _EXPECTED_SCHEMA_SIGNATURE:
                raise KnowledgeCompilationError(
                    "staged database schema objects do not match"
                )
            for table in TABLE_ORDER:
                table_info = tuple(
                    row[1:6]
                    for row in connection.execute(f'PRAGMA table_info("{table}")')
                )
                expected_primary_key = EXPECTED_PRIMARY_KEY_COLUMNS[table]
                expected_table_info = tuple(
                    (
                        column,
                        "REAL"
                        if (table, column) in _REAL_COLUMNS
                        else "INTEGER"
                        if column in _INTEGER_COLUMN_NAMES
                        else "TEXT",
                        int((table, column) not in _NULLABLE_COLUMNS),
                        None,
                        expected_primary_key.index(column) + 1
                        if column in expected_primary_key
                        else 0,
                    )
                    for column in EXPECTED_TABLE_COLUMNS[table]
                )
                if table_info != expected_table_info:
                    raise KnowledgeCompilationError(
                        f"staged database column contract does not match for {table}"
                    )
            if connection.execute("PRAGMA journal_mode").fetchone() != ("delete",):
                raise KnowledgeCompilationError(
                    "staged database journal mode does not match"
                )
            if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise KnowledgeCompilationError("staged database quick_check failed")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise KnowledgeCompilationError("staged database foreign keys failed")
            metadata = dict(
                connection.execute("SELECT key, value FROM metadata ORDER BY key")
            )
            expected_metadata = {
                "schema_version": str(manifest.schema_version),
                "bundle_version": manifest.bundle_version,
                "identity_catalog_version": manifest.identity_catalog_version,
                "policy_revision": manifest.policy_revision,
                "content_sha256": manifest.content_sha256,
                "coverage_sha256": manifest.coverage_sha256,
            }
            if metadata != expected_metadata:
                raise KnowledgeCompilationError("staged database metadata does not match")
            category_order = dict(
                connection.execute("SELECT category_id, release_order FROM categories")
            )
            if category_order != _CATEGORY_RELEASE_ORDER:
                raise KnowledgeCompilationError("staged category release order does not match")
            readback = _read_database_rows(connection)
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise KnowledgeCompilationError(f"staged database reopen failed: {exc}") from exc
    finally:
        os.close(descriptor)

    if readback != expected_rows:
        raise KnowledgeCompilationError("staged database rows changed before reopen")
    if logical_content_sha256(readback) != manifest.content_sha256:
        raise KnowledgeCompilationError("staged logical content hash does not match")
    if parsed["schema_version"] != 1:
        raise KnowledgeCompilationError("staged coverage schema does not match")
    if parsed["bundle_version"] != manifest.bundle_version:
        raise KnowledgeCompilationError("staged coverage bundle linkage does not match")
    if parsed["knowledge_content_sha256"] != manifest.content_sha256:
        raise KnowledgeCompilationError("staged coverage content linkage does not match")


def _stage_is_present(path: Path) -> bool:
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    return True


def _rollback_promotion(
    *,
    destination: Path,
    stage: Path,
    backup: Path | None,
    had_destination: bool,
) -> list[str]:
    failures: list[str] = []
    restored_backup = False
    try:
        if _stage_is_present(destination) and not _stage_is_present(stage):
            os.replace(destination, stage)
    except BaseException as exc:
        failures.append(f"move new destination aside failed: {exc!r}")
    if backup is not None and _stage_is_present(backup):
        try:
            if _stage_is_present(destination):
                failures.append("restore blocked because destination is still present")
            else:
                os.replace(backup, destination)
                restored_backup = True
        except BaseException as exc:
            failures.append(f"restore previous destination failed: {exc!r}")
    elif had_destination and not _stage_is_present(destination):
        failures.append("previous destination backup is missing")
    try:
        _fsync_directory(destination.parent)
    except BaseException as exc:
        failures.append(f"rollback parent fsync failed: {exc!r}")
        if restored_backup and backup is not None:
            try:
                os.replace(destination, backup)
            except BaseException as preserve_error:
                failures.append(
                    f"preserve previous destination backup failed: {preserve_error!r}"
                )
    return failures


def _promotion_error(
    original: BaseException,
    failures: list[str],
    destination: Path,
    stage: Path,
    backup: Path | None,
) -> KnowledgeCompilationError:
    details = [f"bundle promotion failure: {original!r}", *failures]
    preserved = [str(path) for path in (backup, stage) if path is not None and _stage_is_present(path)]
    if failures and _stage_is_present(destination):
        preserved.append(str(destination))
    if preserved:
        details.append("preserved recovery paths: " + ", ".join(preserved))
    return KnowledgeCompilationError("; ".join(details))


def _promote(
    stage: Path, stage_identity: tuple[int, int], state: _PathState
) -> None:
    destination = state.destination
    backup: Path | None = None
    backup_identity: tuple[int, int] | None = None
    try:
        _recheck_identity_chains(state)
        stage_result = os.lstat(stage)
        if stat.S_ISLNK(stage_result.st_mode) or not stat.S_ISDIR(stage_result.st_mode):
            raise KnowledgeCompilationError(
                f"bundle stage is unsafe before promotion: {stage}"
            )
        if (stage_result.st_dev, stage_result.st_ino) != stage_identity:
            raise KnowledgeCompilationError(
                f"bundle stage identity changed before promotion: {stage}"
            )
        if _path_identity(stage.parent) != _path_identity(destination.parent):
            raise KnowledgeCompilationError("stage and destination parents do not match")
        backup = _choose_backup_path(destination) if state.destination_exists else None
        if backup is not None:
            backup_identity = state.destination_chain[-1].identity
            try:
                os.lstat(backup)
            except FileNotFoundError:
                pass
            else:
                raise KnowledgeCompilationError(
                    f"bundle backup appeared before promotion: {backup}"
                )
    except BaseException as original:
        try:
            _remove_owned_directory(
                stage, destination, _STAGE_SUFFIX, stage_identity
            )
        except BaseException as cleanup_error:
            raise _promotion_error(
                original,
                [f"stage cleanup failed: {cleanup_error!r}"],
                destination,
                stage,
                backup,
            ) from original
        if isinstance(original, KnowledgeCompilationError):
            raise original
        raise _promotion_error(original, [], destination, stage, backup) from original
    moved_old = False
    moved_new = False
    try:
        if backup is not None:
            os.replace(destination, backup)
            moved_old = True
            _fsync_directory(destination.parent)
        os.replace(stage, destination)
        moved_new = True
        _fsync_directory(destination.parent)
    except BaseException as original:
        moved_old = moved_old or (backup is not None and _stage_is_present(backup))
        moved_new = moved_new or (
            _stage_is_present(destination) and not _stage_is_present(stage)
        )
        if moved_old or moved_new:
            failures = _rollback_promotion(
                destination=destination,
                stage=stage,
                backup=backup,
                had_destination=state.destination_exists,
            )
            if failures:
                raise _promotion_error(
                    original, failures, destination, stage, backup
                ) from original
        try:
            _remove_owned_directory(
                stage, destination, _STAGE_SUFFIX, stage_identity
            )
        except BaseException as cleanup_error:
            raise _promotion_error(
                original,
                [f"stage cleanup failed: {cleanup_error!r}"],
                destination,
                stage,
                backup,
            ) from original
        raise _promotion_error(original, [], destination, stage, backup) from original

    if backup is not None:
        if backup_identity is None:
            raise AssertionError("existing destination requires captured backup identity")
        try:
            _remove_owned_directory(
                backup, destination, _BACKUP_SUFFIX, backup_identity
            )
        except BaseException as exc:
            raise KnowledgeCompilationError(
                f"new bundle is durable but backup cleanup failed; preserved at {backup}: {exc}"
            ) from exc
        try:
            _fsync_directory(destination.parent)
        except BaseException as exc:
            raise KnowledgeCompilationError(
                f"new bundle remains installed but final parent fsync failed: {exc}"
            ) from exc


def _clean_failed_stage(
    stage: Path,
    stage_identity: tuple[int, int],
    destination: Path,
    original: BaseException,
) -> None:
    try:
        _remove_owned_directory(
            stage, destination, _STAGE_SUFFIX, stage_identity
        )
    except BaseException as cleanup_error:
        raise KnowledgeCompilationError(
            f"bundle compilation failed ({original!r}); cleanup failed "
            f"({cleanup_error!r}); preserved recovery path: {stage}"
        ) from original


def compile_knowledge_bundle(
    source_dir: Path, destination_dir: Path
) -> KnowledgeManifest:
    source = _absolute_lexical(source_dir)
    destination = _absolute_lexical(destination_dir)
    state = _preflight_paths(source, destination)

    documents = load_evidence_documents(source)
    rows = normalized_sql_rows(documents)
    content_sha256 = logical_content_sha256(rows)
    coverage = build_coverage(documents, content_sha256)
    validate_coverage_report(coverage)
    coverage_bytes = coverage_json_bytes(coverage)
    coverage_sha256 = hashlib.sha256(coverage_bytes).hexdigest()
    bundle = documents.shared.bundle
    manifest = KnowledgeManifest(
        bundle.schema_version,
        bundle.bundle_version,
        bundle.identity_catalog_version,
        bundle.policy_revision,
        content_sha256,
        coverage_sha256,
    )

    _create_missing_destination_parents(state)
    _recheck_identity_chains(state)
    stage, stage_identity = _create_stage_directory(destination)
    promotion_started = False
    try:
        _write_database(
            stage, rows, content_sha256, coverage_sha256, stage_identity
        )
        _write_coverage(stage, coverage_bytes, stage_identity)
        _stage_entries(stage, stage_identity)
        _fsync_stage_regular(stage, "knowledge.sqlite", stage_identity)
        _fsync_stage_regular(stage, "evidence-coverage.json", stage_identity)
        _verify_staged_bundle(
            stage, rows, manifest, coverage_bytes, stage_identity
        )
        _fsync_stage_directory(stage, stage_identity)
        promotion_started = True
        _promote(stage, stage_identity, state)
    except (KnowledgeCompilationError, CoverageError, sqlite3.Error, OSError) as exc:
        if not promotion_started:
            _clean_failed_stage(stage, stage_identity, destination, exc)
            if isinstance(exc, KnowledgeCompilationError):
                raise
            raise KnowledgeCompilationError(f"bundle compilation failed: {exc}") from exc
        raise
    return manifest

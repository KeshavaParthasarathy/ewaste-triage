"""Strict administrator-only validation for schema-3 knowledge sources."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
import math
import os
from pathlib import Path
import re
import stat
import unicodedata
from urllib.parse import urlsplit, urlunsplit

import yaml
from yaml.nodes import MappingNode, ScalarNode
from yaml.tokens import AliasToken, AnchorToken, DirectiveToken, ScalarToken, TagToken

from server.evidence_types import (
    AssociationStatus,
    BatteryArchitecture,
    EvidenceLevel,
    HazardSeverity,
    IdentityKind,
    LifecycleEndpointKind,
    MarketState,
    RecommendationValue,
    RELEASED_CATEGORY_IDS,
    ScopeKind,
)


class EvidenceValidationError(ValueError):
    """A stable, location-bearing source validation failure."""

    def __init__(self, filename: str, record_path: str, message: str) -> None:
        self.filename = filename
        self.record_path = record_path
        self.message = message
        super().__init__(f"{filename}: {record_path}: {message}")


class TemplateKind(str, Enum):
    STANDARD = "standard"
    MODERN_OVERLAY = "modern_overlay"
    LEGACY_OVERLAY = "legacy_overlay"


class UnknownClaimKind(str, Enum):
    SUBTYPE = "subtype"
    VARIANT = "variant"
    IDENTITY = "identity"
    SPECIFIC_LIFECYCLE = "specific_lifecycle"
    INDUSTRY_AVERAGE = "industry_average"
    COMPONENT_ASSOCIATION = "component_association"
    HAZARD = "hazard"


@dataclass(frozen=True)
class BundleMetadata:
    schema_version: int
    bundle_version: str
    identity_catalog_version: str
    policy_revision: str
    category_ids: tuple[str, ...]


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    title: str
    publisher: str
    canonical_url: str
    publication_or_revision_date: date
    accessed_on: date
    license_or_use_basis: str
    reviewed_by: str
    reviewed_on: date


@dataclass(frozen=True)
class PolicyRecord:
    rule_id: str
    priority: int
    outcome: RecommendationValue
    when_all: tuple[str, ...]
    when_any: tuple[str, ...]
    rationale: str
    evidence_level: EvidenceLevel
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class CategoryRecord:
    category_id: str
    display_name: str


@dataclass(frozen=True)
class SubtypeRecord:
    subtype_id: str
    category_id: str
    display_name: str
    market_state: MarketState
    battery_architecture: BatteryArchitecture
    evidence_level: EvidenceLevel
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class VariantRecord:
    variant_id: str
    category_id: str
    subtype_id: str
    display_name: str
    battery_architecture: BatteryArchitecture
    evidence_level: EvidenceLevel
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class IdentityRecord:
    identity_id: str
    identity_kind: IdentityKind
    category_id: str
    subtype_id: str
    manufacturer_id: str
    manufacturer_name: str
    family_id: str
    family_name: str
    model_id: str | None
    model_name: str | None
    display_name: str
    aliases: tuple[str, ...]
    distinguishing_tokens: tuple[str, ...]
    model_year_from: int | None
    model_year_to: int | None
    applicable_from: date | None
    applicable_to: date | None
    variant_ids: tuple[str, ...]
    market_state: MarketState
    battery_architecture: BatteryArchitecture
    evidence_level: EvidenceLevel
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class Scope:
    kind: ScopeKind
    id: str


@dataclass(frozen=True)
class SpecificLifecycleRecord:
    record_id: str
    scope: Scope
    subject: str
    endpoint: str
    endpoint_kind: LifecycleEndpointKind
    metric: str
    unit: str
    lower_bound: float
    upper_bound: float
    endpoint_qualification: str
    applicable_from: date | None
    applicable_to: date | None
    model_year_from: int | None
    model_year_to: int | None
    required_variant_ids: tuple[str, ...]
    excluded_variant_ids: tuple[str, ...]
    precedence: int
    evidence_level: EvidenceLevel
    assumptions: tuple[str, ...]
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class IndustryAverageRecord:
    record_id: str
    scope: Scope
    subject: str
    endpoint: str
    endpoint_kind: LifecycleEndpointKind
    metric: str
    unit: str
    lower_bound: float
    upper_bound: float
    endpoint_qualification: str
    applicable_from: date | None
    applicable_to: date | None
    model_year_from: int | None
    model_year_to: int | None
    required_variant_ids: tuple[str, ...]
    excluded_variant_ids: tuple[str, ...]
    precedence: int
    evidence_level: EvidenceLevel
    assumptions: tuple[str, ...]
    population_definition: str
    publication_period: str
    methodology: str
    uncertainty: str
    limitations: tuple[str, ...]
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class ComponentDefinition:
    component_id: str
    display_name: str


@dataclass(frozen=True)
class ComponentTemplate:
    template_id: str
    template_kind: TemplateKind
    scope: Scope
    application_order: int


@dataclass(frozen=True)
class ComponentAssociation:
    association_id: str
    template_id: str
    component_id: str
    position: int
    status: AssociationStatus
    applicability: str
    notes: tuple[str, ...]
    evidence_level: EvidenceLevel | None
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class HazardRecord:
    hazard_id: str
    component_id: str
    scope: Scope
    applicability: str
    trigger_observation_keys: tuple[str, ...]
    severity: HazardSeverity
    immediate_actions: tuple[str, ...]
    follow_up_actions: tuple[str, ...]
    handling_guidance: tuple[str, ...]
    disposal_guidance: tuple[str, ...]
    evidence_level: EvidenceLevel
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class UnknownRecord:
    category_id: str
    claim_kind: UnknownClaimKind
    claim_id: str
    evidence_level: None
    source_ids: tuple[str, ...]
    reason: str
    evidence_request: str


@dataclass(frozen=True)
class SharedEvidenceDocuments:
    bundle: BundleMetadata
    sources: tuple[SourceRecord, ...]
    policies: tuple[PolicyRecord, ...]


@dataclass(frozen=True)
class CategoryEvidenceDocuments:
    category: CategoryRecord
    sources: tuple[SourceRecord, ...]
    subtypes: tuple[SubtypeRecord, ...]
    variants: tuple[VariantRecord, ...]
    identities: tuple[IdentityRecord, ...]
    specific_lifecycles: tuple[SpecificLifecycleRecord, ...]
    industry_averages: tuple[IndustryAverageRecord, ...]
    component_definitions: tuple[ComponentDefinition, ...]
    component_templates: tuple[ComponentTemplate, ...]
    component_associations: tuple[ComponentAssociation, ...]
    hazards: tuple[HazardRecord, ...]
    unknowns: tuple[UnknownRecord, ...]


@dataclass(frozen=True)
class EvidenceDocuments:
    shared: SharedEvidenceDocuments
    categories: tuple[CategoryEvidenceDocuments, ...]


_ID_RE = re.compile(r"[a-z0-9][a-z0-9_.-]*\Z")
_SEMVER_RE = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")

_POLICY_PREDICATES = frozenset(
    """identity.state=canonical
identity.state=unknown
observations.age_months=present
observations.age_months=missing
observations.full_charge_cycles=present
observations.full_charge_cycles=missing
observations.operational_state=unknown
observations.operational_state=working
observations.operational_state=intermittent
observations.operational_state=not_working
observations.issue_flags.overheating=true
observations.issue_flags.overheating=false
observations.issue_flags.odor=true
observations.issue_flags.odor=false
observations.issue_flags.swelling_or_battery_damage=true
observations.issue_flags.swelling_or_battery_damage=false
observations.issue_flags.recall=true
observations.issue_flags.recall=false
visible_condition.grade=excellent
visible_condition.grade=good
visible_condition.grade=fair
visible_condition.grade=poor
visible_condition.grade=critical
visible_condition.grade=unknown
visible_condition.image_sufficiency=sufficient
visible_condition.image_sufficiency=insufficient
visible_condition.image_sufficiency=unknown
lifecycle.resolution=resolved
lifecycle.resolution=unknown
lifecycle.resolution=unavailable
lifecycle.required_usage=present
lifecycle.required_usage=missing
lifecycle.position=within_reference
lifecycle.position=at_or_beyond_reference
lifecycle.position=not_calculable
component_decisions.any_present=true
component_decisions.any_present=false
hazards.triggered_severity=none
hazards.triggered_severity=advisory
hazards.triggered_severity=caution
hazards.triggered_severity=urgent""".splitlines()
)

_HAZARD_TRIGGERS = frozenset(
    {
        "observations.issue_flags.overheating",
        "observations.issue_flags.odor",
        "observations.issue_flags.swelling_or_battery_damage",
        "observations.issue_flags.recall",
    }
)

_SCHEMAS: dict[str, tuple[type[object], dict[str, str]]] = {
    "bundle": (
        BundleMetadata,
        {
            "schema_version": "int",
            "bundle_version": "semver",
            "identity_catalog_version": "semver",
            "policy_revision": "semver",
            "category_ids": "nonempty_list:id",
        },
    ),
    "source": (
        SourceRecord,
        {
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
    ),
    "policy": (
        PolicyRecord,
        {
            "rule_id": "id",
            "priority": "int",
            "outcome": "enum:RecommendationValue",
            "when_all": "list:policy_predicate",
            "when_any": "list:policy_predicate",
            "rationale": "text",
            "evidence_level": "enum:EvidenceLevel",
            "source_ids": "nonempty_list:id",
        },
    ),
    "category": (
        CategoryRecord,
        {"category_id": "id", "display_name": "text"},
    ),
    "subtype": (
        SubtypeRecord,
        {
            "subtype_id": "id",
            "category_id": "id",
            "display_name": "text",
            "market_state": "enum:MarketState",
            "battery_architecture": "enum:BatteryArchitecture",
            "evidence_level": "enum:EvidenceLevel",
            "source_ids": "nonempty_list:id",
        },
    ),
    "variant": (
        VariantRecord,
        {
            "variant_id": "id",
            "category_id": "id",
            "subtype_id": "id",
            "display_name": "text",
            "battery_architecture": "enum:BatteryArchitecture",
            "evidence_level": "enum:EvidenceLevel",
            "source_ids": "nonempty_list:id",
        },
    ),
    "identity": (
        IdentityRecord,
        {
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
    ),
    "scope": (Scope, {"kind": "enum:ScopeKind", "id": "id"}),
    "specific_lifecycle": (
        SpecificLifecycleRecord,
        {
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
    ),
    "industry_average": (
        IndustryAverageRecord,
        {
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
    ),
    "component_definition": (
        ComponentDefinition,
        {"component_id": "id", "display_name": "text"},
    ),
    "component_template": (
        ComponentTemplate,
        {
            "template_id": "id",
            "template_kind": "enum:TemplateKind",
            "scope": "mapping:scope",
            "application_order": "int",
        },
    ),
    "component_association": (
        ComponentAssociation,
        {
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
    ),
    "hazard": (
        HazardRecord,
        {
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
    ),
    "unknown": (
        UnknownRecord,
        {
            "category_id": "id",
            "claim_kind": "enum:UnknownClaimKind",
            "claim_id": "id",
            "evidence_level": "literal:null",
            "source_ids": "list:id",
            "reason": "text",
            "evidence_request": "text",
        },
    ),
}

_ENUMS: dict[str, type[Enum]] = {
    "RecommendationValue": RecommendationValue,
    "EvidenceLevel": EvidenceLevel,
    "MarketState": MarketState,
    "BatteryArchitecture": BatteryArchitecture,
    "IdentityKind": IdentityKind,
    "ScopeKind": ScopeKind,
    "LifecycleEndpointKind": LifecycleEndpointKind,
    "TemplateKind": TemplateKind,
    "AssociationStatus": AssociationStatus,
    "HazardSeverity": HazardSeverity,
    "UnknownClaimKind": UnknownClaimKind,
}

_SORTED_LIST_FIELDS = frozenset(
    {
        ("policy", "when_all"),
        ("policy", "when_any"),
        ("policy", "source_ids"),
        ("subtype", "source_ids"),
        ("variant", "source_ids"),
        ("identity", "variant_ids"),
        ("identity", "source_ids"),
        ("specific_lifecycle", "required_variant_ids"),
        ("specific_lifecycle", "excluded_variant_ids"),
        ("specific_lifecycle", "source_ids"),
        ("industry_average", "required_variant_ids"),
        ("industry_average", "excluded_variant_ids"),
        ("industry_average", "source_ids"),
        ("component_association", "source_ids"),
        ("hazard", "trigger_observation_keys"),
        ("hazard", "source_ids"),
    }
)

_SHARED_ROOT_KEYS = {
    "bundle.yaml": frozenset({"bundle"}),
    "common/sources.yaml": frozenset({"sources"}),
    "common/policies.yaml": frozenset({"policy_revision", "policies"}),
}

_CATEGORY_ROOT_KEYS = {
    "sources.yaml": frozenset({"sources"}),
    "identities.yaml": frozenset({"category", "subtypes", "variants", "identities"}),
    "lifecycles.yaml": frozenset({"lifecycles"}),
    "industry_averages.yaml": frozenset({"industry_averages"}),
    "components.yaml": frozenset({"components", "templates", "associations"}),
    "hazards.yaml": frozenset({"hazards"}),
    "coverage.yaml": frozenset({"unknowns"}),
}


class _YamlRuleError(Exception):
    pass


class _ClosedLoader(yaml.SafeLoader):
    pass


def _construct_closed_mapping(
    loader: _ClosedLoader, node: MappingNode, deep: bool = False
) -> dict[object, object]:
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        if not isinstance(key_node, ScalarNode):
            raise _YamlRuleError("YAML mappings require scalar mapping keys")
        key = loader.construct_object(key_node, deep=deep)
        if type(key) is not str:
            raise _YamlRuleError("YAML mappings require scalar string mapping keys")
        if key == "<<":
            raise _YamlRuleError("YAML merge keys are not permitted")
        if key in mapping:
            raise _YamlRuleError(f"duplicate key {key!r} is not permitted")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_ClosedLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_closed_mapping
)


def _fail(filename: str, record_path: str, message: str) -> None:
    raise EvidenceValidationError(filename, record_path, message)


def _absolute_without_resolving(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _ensure_no_symlink_components(path: Path, filename: str = ".") -> Path:
    absolute = _absolute_without_resolving(path)
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            break
        except OSError as exc:
            _fail(filename, "path", f"unsafe path: {exc}")
        if stat.S_ISLNK(mode):
            _fail(filename, "path", f"unsafe path contains symlink component {current}")
    return absolute


def _require_directory(path: Path, filename: str, missing_message: str) -> Path:
    absolute = _ensure_no_symlink_components(path, filename)
    try:
        mode = absolute.lstat().st_mode
    except (FileNotFoundError, OSError):
        _fail(filename, "path", missing_message)
    if not stat.S_ISDIR(mode):
        _fail(filename, "path", missing_message)
    return absolute


def _require_regular_file(path: Path, filename: str) -> Path:
    absolute = _ensure_no_symlink_components(path, filename)
    try:
        mode = absolute.lstat().st_mode
    except (FileNotFoundError, OSError):
        _fail(filename, "path", "required regular file is missing")
    if not stat.S_ISREG(mode):
        _fail(filename, "path", "required regular file is missing or not regular")
    return absolute


def _closed_directory(
    path: Path,
    allowed_names: frozenset[str],
    filename: str,
    *,
    optional_names: frozenset[str] = frozenset(),
) -> None:
    try:
        names = {entry.name for entry in path.iterdir()}
    except OSError as exc:
        _fail(filename, "path", f"unsafe path: {exc}")
    unexpected = names - allowed_names - optional_names
    if unexpected:
        _fail(
            filename,
            "path",
            f"unexpected directory entry: {sorted(unexpected)!r}",
        )


def _load_yaml(path: Path, filename: str) -> dict[str, object]:
    regular = _require_regular_file(path, filename)
    try:
        text = regular.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        _fail(filename, "document root", f"invalid YAML encoding: {exc}")
    try:
        for token in yaml.scan(text):
            if isinstance(token, AnchorToken):
                _fail(filename, "document root", "YAML anchors are not permitted")
            if isinstance(token, AliasToken):
                _fail(filename, "document root", "YAML aliases are not permitted")
            if isinstance(token, TagToken):
                _fail(filename, "document root", "YAML explicit tags are not permitted")
            if isinstance(token, DirectiveToken):
                _fail(filename, "document root", "YAML directives/defaults are not permitted")
            if isinstance(token, ScalarToken) and token.value == "<<":
                _fail(filename, "document root", "YAML merge keys are not permitted")
        value = yaml.load(text, Loader=_ClosedLoader)
    except EvidenceValidationError:
        raise
    except _YamlRuleError as exc:
        _fail(filename, "document root", str(exc))
    except yaml.YAMLError as exc:
        _fail(filename, "document root", f"invalid YAML: {exc}")
    if type(value) is not dict:
        _fail(filename, "document root", "document must have a mapping root")
    return value


def _closed_mapping(
    value: object,
    expected_keys: frozenset[str] | set[str],
    filename: str,
    record_path: str,
    *,
    root: bool = False,
) -> dict[str, object]:
    if type(value) is not dict:
        _fail(filename, record_path, "value must be a mapping")
    actual = set(value)
    unknown = actual - set(expected_keys)
    missing = set(expected_keys) - actual
    context = "document root" if root else "record"
    if unknown:
        _fail(
            filename,
            record_path,
            f"{context} has unknown field(s): {sorted(unknown)!r}",
        )
    if missing:
        _fail(
            filename,
            record_path,
            f"{context} has missing field(s): {sorted(missing)!r}",
        )
    return value


def _validate_document_root(
    document: dict[str, object], expected: frozenset[str], filename: str
) -> None:
    _closed_mapping(document, expected, filename, "document root", root=True)


def _type_failure(filename: str, path: str, expected: str, value: object) -> None:
    if value is None:
        _fail(filename, path, f"must not be null; must be {expected}")
    if type(value) is bool and expected in {"an integer", "a number"}:
        _fail(filename, path, f"boolean is not {expected}; must be {expected}")
    _fail(filename, path, f"must be {expected}")


def _parse_text(value: object, filename: str, path: str) -> str:
    if type(value) is not str:
        _type_failure(filename, path, "text", value)
    if not value or value != value.strip():
        _fail(filename, path, "invalid text: must be non-empty and trimmed")
    if unicodedata.normalize("NFC", value) != value:
        _fail(filename, path, "invalid text: must be NFC")
    if any(ch == "\x00" or unicodedata.category(ch).startswith("C") for ch in value):
        _fail(filename, path, "invalid text: Unicode control characters are forbidden")
    return value


def _parse_id(value: object, filename: str, path: str) -> str:
    if type(value) is not str:
        _type_failure(filename, path, "an ID string", value)
    if unicodedata.normalize("NFC", value) != value or not _ID_RE.fullmatch(value):
        _fail(filename, path, "invalid ID")
    return value


def _parse_date(value: object, filename: str, path: str) -> date:
    if type(value) is not str:
        if isinstance(value, date):
            _fail(filename, path, "must be a quoted date string")
        _type_failure(filename, path, "a quoted date string", value)
    if not _DATE_RE.fullmatch(value):
        _fail(filename, path, "invalid canonical date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        _fail(filename, path, "invalid canonical date")
    if parsed.isoformat() != value:
        _fail(filename, path, "invalid canonical date")
    return parsed


def _parse_semver(value: object, filename: str, path: str) -> str:
    if type(value) is not str:
        _type_failure(filename, path, "a semantic-version string", value)
    if not _SEMVER_RE.fullmatch(value):
        _fail(filename, path, "invalid semantic version")
    return value


def _parse_int(value: object, filename: str, path: str) -> int:
    if type(value) is bool:
        _type_failure(filename, path, "an integer", value)
    if type(value) is not int:
        _type_failure(filename, path, "an integer", value)
    return value


def _parse_number(value: object, filename: str, path: str) -> float:
    if type(value) is bool:
        _type_failure(filename, path, "a number", value)
    if type(value) not in {int, float}:
        _type_failure(filename, path, "a number", value)
    result = float(value)
    if not math.isfinite(result):
        _fail(filename, path, "number must be finite")
    return result


def _parse_url(value: object, filename: str, path: str) -> str:
    text = _parse_text(value, filename, path)
    if any(character.isspace() for character in text):
        _fail(filename, path, "invalid canonical HTTPS URL")
    try:
        parsed = urlsplit(text)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        _fail(filename, path, "invalid canonical HTTPS URL")
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or urlunsplit(parsed) != text
    ):
        _fail(filename, path, "invalid canonical HTTPS URL")
    del port
    return text


def _parse_enum(value: object, enum_name: str, filename: str, path: str) -> Enum:
    if type(value) is not str:
        _type_failure(filename, path, f"a {enum_name} string", value)
    enum_type = _ENUMS[enum_name]
    try:
        return enum_type(value)
    except ValueError:
        _fail(filename, path, f"invalid {enum_name} value")


def _parse_policy_predicate(value: object, filename: str, path: str) -> str:
    text = _parse_text(value, filename, path)
    if text not in _POLICY_PREDICATES:
        _fail(filename, path, "invalid policy predicate")
    return text


def _parse_hazard_trigger(value: object, filename: str, path: str) -> str:
    text = _parse_text(value, filename, path)
    if text not in _HAZARD_TRIGGERS:
        _fail(filename, path, "invalid hazard trigger key")
    return text


def _parse_atomic(value: object, contract: str, filename: str, path: str) -> object:
    if contract == "id":
        return _parse_id(value, filename, path)
    if contract == "text":
        return _parse_text(value, filename, path)
    if contract == "date":
        return _parse_date(value, filename, path)
    if contract == "semver":
        return _parse_semver(value, filename, path)
    if contract == "https_url":
        return _parse_url(value, filename, path)
    if contract == "int":
        return _parse_int(value, filename, path)
    if contract == "number":
        return _parse_number(value, filename, path)
    if contract == "policy_predicate":
        return _parse_policy_predicate(value, filename, path)
    if contract == "hazard_trigger_key":
        return _parse_hazard_trigger(value, filename, path)
    if contract.startswith("enum:"):
        return _parse_enum(
            value, contract.removeprefix("enum:"), filename, path
        )
    _fail(filename, path, f"invalid internal schema contract {contract}")


def _parse_contract(
    value: object,
    contract: str,
    filename: str,
    path: str,
    record_name: str,
    field_name: str,
) -> object:
    if contract.startswith("nullable:"):
        if value is None:
            return None
        return _parse_atomic(
            value, contract.removeprefix("nullable:"), filename, path
        )
    if contract == "literal:null":
        if value is not None:
            _fail(filename, path, "must be literal null")
        return None
    if contract.startswith("mapping:"):
        nested_name = contract.removeprefix("mapping:")
        if type(value) is not dict:
            _type_failure(filename, path, "a mapping", value)
        return _parse_record(value, nested_name, filename, path)
    if contract.startswith(("list:", "nonempty_list:")):
        nonempty = contract.startswith("nonempty_list:")
        item_contract = contract.split(":", 1)[1]
        if type(value) is not list:
            if value is None:
                _fail(filename, path, "must not be null; must be a list")
            _type_failure(filename, path, "a list", value)
        if nonempty and not value:
            _fail(filename, path, "must be a non-empty list")
        parsed: list[object] = []
        for index, item in enumerate(value):
            item_path = f"{path}[{index}]"
            if item_contract in _SCHEMAS:
                if type(item) is not dict:
                    _fail(filename, item_path, "list item must be a mapping")
                parsed_item = _parse_record(item, item_contract, filename, item_path)
            else:
                try:
                    parsed_item = _parse_atomic(item, item_contract, filename, item_path)
                except EvidenceValidationError as exc:
                    _fail(
                        filename,
                        item_path,
                        f"list item {exc.message}",
                    )
            parsed.append(parsed_item)
        if len(parsed) != len(set(parsed)):
            _fail(filename, path, "list contains an exact duplicate item")
        if (record_name, field_name) in _SORTED_LIST_FIELDS:
            if tuple(parsed) != tuple(sorted(parsed)):
                subject = (
                    "predicates"
                    if item_contract == "policy_predicate"
                    else "list items"
                )
                _fail(filename, path, f"{subject} must be sorted")
        return tuple(parsed)
    return _parse_atomic(value, contract, filename, path)


def _parse_record(
    value: object, record_name: str, filename: str, path: str
) -> object:
    record_type, field_contracts = _SCHEMAS[record_name]
    mapping = _closed_mapping(value, set(field_contracts), filename, path)
    values = {
        field_name: _parse_contract(
            mapping[field_name],
            contract,
            filename,
            f"{path}.{field_name}",
            record_name,
            field_name,
        )
        for field_name, contract in field_contracts.items()
    }
    return record_type(**values)


def _parse_record_list(
    value: object,
    record_name: str,
    filename: str,
    root_name: str,
    *,
    nonempty: bool = False,
) -> tuple[object, ...]:
    if type(value) is not list:
        if value is None:
            _fail(filename, root_name, "must not be null; must be a list")
        _type_failure(filename, root_name, "a list", value)
    if nonempty and not value:
        _fail(filename, root_name, "must be a non-empty list")
    result: list[object] = []
    for index, item in enumerate(value):
        path = f"{root_name}[{index}]"
        if type(item) is not dict:
            _fail(filename, path, "list item must be a mapping")
        result.append(_parse_record(item, record_name, filename, path))
    return tuple(result)


def _validate_source(source: SourceRecord, filename: str, path: str) -> None:
    if source.publication_or_revision_date > source.accessed_on:
        _fail(filename, path, "source publication date must not follow access date")
    if source.reviewed_on < source.accessed_on:
        _fail(filename, path, "source review date must be on or after access date")


def _validate_unique_sorted(
    records: tuple[object, ...],
    key,
    filename: str,
    root_name: str,
    identity_label: str,
) -> None:
    keys = [key(record) for record in records]
    if len(keys) != len(set(keys)):
        _fail(filename, root_name, f"{identity_label} values must be unique")
    if keys != sorted(keys):
        _fail(filename, root_name, f"{root_name} must be sorted by its normative key")


def _normalize_search_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).strip().split()).casefold()


def _validate_range(
    lower: object | None,
    upper: object | None,
    filename: str,
    path: str,
    label: str,
) -> None:
    if lower is not None and upper is not None and lower > upper:
        _fail(filename, path, f"{label} range has reversed bounds")


def _source_refs(
    source_ids: tuple[str, ...],
    available: frozenset[str],
    filename: str,
    path: str,
) -> None:
    missing = set(source_ids) - available
    if missing:
        _fail(filename, path, f"source reference does not resolve: {sorted(missing)!r}")


def _validate_policy_predicates(policy: PolicyRecord, filename: str, path: str) -> None:
    overlap = set(policy.when_all) & set(policy.when_any)
    if overlap:
        _fail(filename, path, "a predicate cannot occur in both predicate groups")
    family_values: dict[str, str] = {}
    for predicate in policy.when_all:
        family, value = predicate.rsplit("=", 1)
        prior = family_values.get(family)
        if prior is not None and prior != value:
            _fail(filename, path, "when_all contains mutually exclusive predicates")
        family_values[family] = value


def _shared_root(source_dir: Path) -> Path:
    root = _require_directory(
        source_dir, ".", "source directory is missing or not a directory"
    )
    _closed_directory(
        root,
        frozenset({"bundle.yaml", "common"}),
        ".",
        optional_names=frozenset(
            {"categories", "sources.yaml", "device_components.yaml"}
        ),
    )
    common = _require_directory(
        root / "common", "common", "common directory is missing or not a directory"
    )
    _closed_directory(
        common,
        frozenset({"sources.yaml", "policies.yaml"}),
        "common",
    )
    return root


def load_shared_evidence_documents(source_dir: Path) -> SharedEvidenceDocuments:
    root = _shared_root(Path(source_dir))

    bundle_filename = "bundle.yaml"
    bundle_doc = _load_yaml(root / bundle_filename, bundle_filename)
    _validate_document_root(
        bundle_doc, _SHARED_ROOT_KEYS[bundle_filename], bundle_filename
    )
    bundle = _parse_record(
        bundle_doc["bundle"], "bundle", bundle_filename, "bundle"
    )
    assert isinstance(bundle, BundleMetadata)
    if bundle.schema_version != 3:
        _fail(bundle_filename, "bundle.schema_version", "schema_version must equal 3")
    if bundle.bundle_version != "3.0.0":
        _fail(bundle_filename, "bundle.bundle_version", "bundle_version must equal 3.0.0")
    if bundle.identity_catalog_version != "1.0.0":
        _fail(
            bundle_filename,
            "bundle.identity_catalog_version",
            "identity_catalog_version must equal 1.0.0",
        )
    if bundle.policy_revision != "2.0.0":
        _fail(bundle_filename, "bundle.policy_revision", "policy_revision must equal 2.0.0")
    if len(bundle.category_ids) != len(set(bundle.category_ids)):
        _fail(bundle_filename, "bundle.category_ids", "list contains an exact duplicate item")
    if bundle.category_ids != RELEASED_CATEGORY_IDS:
        _fail(
            bundle_filename,
            "bundle.category_ids",
            "category_ids must use the exact released order (sorted contract)",
        )

    source_filename = "common/sources.yaml"
    source_doc = _load_yaml(root / source_filename, source_filename)
    _validate_document_root(
        source_doc, _SHARED_ROOT_KEYS[source_filename], source_filename
    )
    sources = _parse_record_list(
        source_doc["sources"],
        "source",
        source_filename,
        "sources",
        nonempty=True,
    )
    assert all(isinstance(item, SourceRecord) for item in sources)
    sources = tuple(sources)
    _validate_unique_sorted(
        sources,
        lambda item: item.source_id,
        source_filename,
        "sources",
        "source_id",
    )
    for index, source in enumerate(sources):
        _validate_source(source, source_filename, f"sources[{index}]")

    policy_filename = "common/policies.yaml"
    policy_doc = _load_yaml(root / policy_filename, policy_filename)
    _validate_document_root(
        policy_doc, _SHARED_ROOT_KEYS[policy_filename], policy_filename
    )
    revision = _parse_semver(
        policy_doc["policy_revision"], policy_filename, "policy_revision"
    )
    if revision != bundle.policy_revision:
        _fail(
            policy_filename,
            "policy_revision",
            "policy revision must equal bundle policy revision",
        )
    policies = _parse_record_list(
        policy_doc["policies"],
        "policy",
        policy_filename,
        "policies",
        nonempty=True,
    )
    assert all(isinstance(item, PolicyRecord) for item in policies)
    policies = tuple(policies)
    _validate_unique_sorted(
        policies,
        lambda item: (item.priority, item.rule_id),
        policy_filename,
        "policies",
        "policy sort key",
    )
    rule_ids = [item.rule_id for item in policies]
    if len(rule_ids) != len(set(rule_ids)):
        _fail(policy_filename, "policies", "rule_id values must be unique")
    priorities = [item.priority for item in policies]
    if len(priorities) != len(set(priorities)):
        _fail(policy_filename, "policies", "policy priority values must be unique")
    shared_source_ids = frozenset(item.source_id for item in sources)
    for index, policy in enumerate(policies):
        path = f"policies[{index}]"
        if policy.priority < 0:
            _fail(policy_filename, path, "policy priority must be non-negative")
        _validate_policy_predicates(policy, policy_filename, path)
        _source_refs(policy.source_ids, shared_source_ids, policy_filename, path)

    return SharedEvidenceDocuments(
        bundle=bundle,
        sources=sources,
        policies=policies,
    )


def _category_directory(source_dir: Path, category_id: object) -> tuple[Path, str]:
    root = _require_directory(
        Path(source_dir), ".", "source directory is missing or not a directory"
    )
    parsed_category_id = _parse_id(category_id, ".", "category_id")
    if parsed_category_id not in RELEASED_CATEGORY_IDS:
        _fail(".", "category_id", "category_id is not a released category_id")
    categories = _require_directory(
        root / "categories",
        "categories",
        "missing category directory",
    )
    category_dir = categories / parsed_category_id
    absolute_category = _absolute_without_resolving(category_dir)
    try:
        if os.path.commonpath((str(categories), str(absolute_category))) != str(categories):
            _fail("categories", "path", "unsafe category_id path containment")
    except ValueError:
        _fail("categories", "path", "unsafe category_id path containment")
    category_dir = _require_directory(
        absolute_category,
        f"categories/{parsed_category_id}",
        "missing category directory",
    )
    _closed_directory(
        category_dir,
        frozenset(_CATEGORY_ROOT_KEYS),
        f"categories/{parsed_category_id}",
    )
    return category_dir, parsed_category_id


def _category_filename(category_id: str, leaf: str) -> str:
    return f"categories/{category_id}/{leaf}"


def _category_document(category_dir: Path, category_id: str, leaf: str) -> dict[str, object]:
    filename = _category_filename(category_id, leaf)
    document = _load_yaml(category_dir / leaf, filename)
    _validate_document_root(document, _CATEGORY_ROOT_KEYS[leaf], filename)
    return document


def _parse_category_documents(
    category_dir: Path, category_id: str
) -> CategoryEvidenceDocuments:
    sources_doc = _category_document(category_dir, category_id, "sources.yaml")
    sources = _parse_record_list(
        sources_doc["sources"],
        "source",
        _category_filename(category_id, "sources.yaml"),
        "sources",
    )

    identities_doc = _category_document(
        category_dir, category_id, "identities.yaml"
    )
    identity_filename = _category_filename(category_id, "identities.yaml")
    category = _parse_record(
        identities_doc["category"], "category", identity_filename, "category"
    )
    subtypes = _parse_record_list(
        identities_doc["subtypes"],
        "subtype",
        identity_filename,
        "subtypes",
    )
    variants = _parse_record_list(
        identities_doc["variants"],
        "variant",
        identity_filename,
        "variants",
    )
    identities = _parse_record_list(
        identities_doc["identities"],
        "identity",
        identity_filename,
        "identities",
    )

    lifecycle_doc = _category_document(
        category_dir, category_id, "lifecycles.yaml"
    )
    specific_lifecycles = _parse_record_list(
        lifecycle_doc["lifecycles"],
        "specific_lifecycle",
        _category_filename(category_id, "lifecycles.yaml"),
        "lifecycles",
    )

    averages_doc = _category_document(
        category_dir, category_id, "industry_averages.yaml"
    )
    industry_averages = _parse_record_list(
        averages_doc["industry_averages"],
        "industry_average",
        _category_filename(category_id, "industry_averages.yaml"),
        "industry_averages",
    )

    components_doc = _category_document(
        category_dir, category_id, "components.yaml"
    )
    components_filename = _category_filename(category_id, "components.yaml")
    component_definitions = _parse_record_list(
        components_doc["components"],
        "component_definition",
        components_filename,
        "components",
    )
    component_templates = _parse_record_list(
        components_doc["templates"],
        "component_template",
        components_filename,
        "templates",
    )
    component_associations = _parse_record_list(
        components_doc["associations"],
        "component_association",
        components_filename,
        "associations",
    )

    hazards_doc = _category_document(category_dir, category_id, "hazards.yaml")
    hazards = _parse_record_list(
        hazards_doc["hazards"],
        "hazard",
        _category_filename(category_id, "hazards.yaml"),
        "hazards",
    )

    coverage_doc = _category_document(
        category_dir, category_id, "coverage.yaml"
    )
    unknowns = _parse_record_list(
        coverage_doc["unknowns"],
        "unknown",
        _category_filename(category_id, "coverage.yaml"),
        "unknowns",
    )

    assert isinstance(category, CategoryRecord)
    return CategoryEvidenceDocuments(
        category=category,
        sources=tuple(sources),
        subtypes=tuple(subtypes),
        variants=tuple(variants),
        identities=tuple(identities),
        specific_lifecycles=tuple(specific_lifecycles),
        industry_averages=tuple(industry_averages),
        component_definitions=tuple(component_definitions),
        component_templates=tuple(component_templates),
        component_associations=tuple(component_associations),
        hazards=tuple(hazards),
        unknowns=tuple(unknowns),
    )


def _validate_category_record_order(documents: CategoryEvidenceDocuments, category_id: str) -> None:
    identity_filename = _category_filename(category_id, "identities.yaml")
    component_filename = _category_filename(category_id, "components.yaml")
    lifecycle_filename = _category_filename(category_id, "lifecycles.yaml")
    average_filename = _category_filename(category_id, "industry_averages.yaml")
    hazard_filename = _category_filename(category_id, "hazards.yaml")
    coverage_filename = _category_filename(category_id, "coverage.yaml")
    source_filename = _category_filename(category_id, "sources.yaml")
    _validate_unique_sorted(
        documents.sources,
        lambda item: item.source_id,
        source_filename,
        "sources",
        "source_id",
    )
    _validate_unique_sorted(
        documents.subtypes,
        lambda item: item.subtype_id,
        identity_filename,
        "subtypes",
        "subtype_id",
    )
    _validate_unique_sorted(
        documents.variants,
        lambda item: item.variant_id,
        identity_filename,
        "variants",
        "variant_id",
    )
    _validate_unique_sorted(
        documents.identities,
        lambda item: item.identity_id,
        identity_filename,
        "identities",
        "identity_id",
    )
    _validate_unique_sorted(
        documents.specific_lifecycles,
        lambda item: item.record_id,
        lifecycle_filename,
        "lifecycles",
        "record_id",
    )
    _validate_unique_sorted(
        documents.industry_averages,
        lambda item: item.record_id,
        average_filename,
        "industry_averages",
        "record_id",
    )
    lifecycle_ids = [item.record_id for item in documents.specific_lifecycles]
    lifecycle_ids.extend(item.record_id for item in documents.industry_averages)
    if len(lifecycle_ids) != len(set(lifecycle_ids)):
        _fail(lifecycle_filename, "lifecycles", "record_id values must be unique")
    _validate_unique_sorted(
        documents.component_definitions,
        lambda item: item.component_id,
        component_filename,
        "components",
        "component_id",
    )
    _validate_unique_sorted(
        documents.component_templates,
        lambda item: item.template_id,
        component_filename,
        "templates",
        "template_id",
    )
    _validate_unique_sorted(
        documents.component_associations,
        lambda item: (item.template_id, item.position, item.association_id),
        component_filename,
        "associations",
        "association_id",
    )
    association_ids = [item.association_id for item in documents.component_associations]
    if len(association_ids) != len(set(association_ids)):
        _fail(component_filename, "associations", "association_id values must be unique")
    _validate_unique_sorted(
        documents.hazards,
        lambda item: item.hazard_id,
        hazard_filename,
        "hazards",
        "hazard_id",
    )
    _validate_unique_sorted(
        documents.unknowns,
        lambda item: (item.category_id, item.claim_kind.value, item.claim_id),
        coverage_filename,
        "unknowns",
        "Unknown stable key",
    )


def _validate_identity_hierarchy(
    documents: CategoryEvidenceDocuments,
    category_id: str,
    available_sources: frozenset[str],
) -> tuple[
    dict[str, SubtypeRecord],
    dict[str, VariantRecord],
    dict[str, tuple[str, str, str, str, str]],
    dict[str, IdentityRecord],
]:
    filename = _category_filename(category_id, "identities.yaml")
    if documents.category.category_id != category_id:
        _fail(filename, "category", "category must match category directory")
    subtype_by_id = {item.subtype_id: item for item in documents.subtypes}
    for index, subtype in enumerate(documents.subtypes):
        path = f"subtypes[{index}]"
        if subtype.category_id != category_id:
            _fail(filename, path, "category_id reference must match category directory")
        if subtype.evidence_level is not EvidenceLevel.B:
            _fail(filename, path, "subtype evidence level must be B; grade D cannot support subtype")
        _source_refs(subtype.source_ids, available_sources, filename, path)

    variant_by_id = {item.variant_id: item for item in documents.variants}
    for index, variant in enumerate(documents.variants):
        path = f"variants[{index}]"
        if variant.category_id != category_id:
            _fail(filename, path, "category_id reference must match category directory")
        subtype = subtype_by_id.get(variant.subtype_id)
        if subtype is None:
            _fail(filename, path, "subtype reference does not resolve")
        if variant.battery_architecture is not subtype.battery_architecture:
            _fail(filename, path, "variant battery architecture must match subtype")
        if variant.evidence_level is not EvidenceLevel.B:
            _fail(filename, path, "variant evidence level must be B; grade D cannot support variant")
        _source_refs(variant.source_ids, available_sources, filename, path)

    manufacturer_names: dict[str, str] = {}
    family_ancestry: dict[str, tuple[str, str, str, str, str]] = {}
    model_by_id: dict[str, IdentityRecord] = {}
    alias_namespace: dict[str, str] = {}
    for index, identity in enumerate(documents.identities):
        path = f"identities[{index}]"
        if identity.category_id != category_id:
            _fail(filename, path, "category_id reference must match category directory")
        subtype = subtype_by_id.get(identity.subtype_id)
        if subtype is None:
            _fail(filename, path, "subtype reference does not resolve")
        if identity.battery_architecture is not subtype.battery_architecture:
            _fail(filename, path, "identity battery architecture must match subtype")
        for variant_id in identity.variant_ids:
            variant = variant_by_id.get(variant_id)
            if variant is None:
                _fail(filename, path, "variant reference does not resolve")
            if variant.subtype_id != identity.subtype_id:
                _fail(filename, path, "identity variant must belong to identity subtype")
            if variant.battery_architecture is not identity.battery_architecture:
                _fail(filename, path, "identity battery architecture must match every variant")
        if identity.identity_kind is IdentityKind.FAMILY:
            if (
                identity.identity_id != identity.family_id
                or identity.model_id is not None
                or identity.model_name is not None
            ):
                _fail(filename, path, "family identity must equal family_id and have null model fields")
            if identity.evidence_level is not EvidenceLevel.B:
                _fail(filename, path, "family identity evidence level must be B")
        else:
            if (
                identity.model_id is None
                or identity.model_name is None
                or identity.identity_id != identity.model_id
            ):
                _fail(filename, path, "model identity must equal non-null model_id and have model_name")
            if identity.evidence_level is not EvidenceLevel.A:
                _fail(filename, path, "model identity evidence level must be A")
            model_by_id[identity.model_id] = identity
        _validate_range(
            identity.model_year_from,
            identity.model_year_to,
            filename,
            path,
            "model year",
        )
        _validate_range(
            identity.applicable_from,
            identity.applicable_to,
            filename,
            path,
            "applicability date",
        )
        prior_manufacturer = manufacturer_names.setdefault(
            identity.manufacturer_id, identity.manufacturer_name
        )
        if prior_manufacturer != identity.manufacturer_name:
            _fail(filename, path, "manufacturer ID/name pair must remain consistent")
        ancestry = (
            identity.category_id,
            identity.subtype_id,
            identity.manufacturer_id,
            identity.manufacturer_name,
            identity.family_name,
        )
        prior_family = family_ancestry.setdefault(identity.family_id, ancestry)
        if prior_family != ancestry:
            if prior_family[-1] != identity.family_name:
                _fail(filename, path, "family ID/name pair must remain consistent")
            _fail(filename, path, "family ancestry must remain consistent")
        for display in (identity.display_name, *identity.aliases):
            normalized = _normalize_search_text(display)
            prior = alias_namespace.get(normalized)
            if prior is not None:
                _fail(filename, path, "identity alias/display namespace must be unique")
            alias_namespace[normalized] = identity.identity_id
        normalized_tokens = [_normalize_search_text(item) for item in identity.distinguishing_tokens]
        if len(normalized_tokens) != len(set(normalized_tokens)):
            _fail(filename, path, "distinguishing token values must be unique after normalization")
        _source_refs(identity.source_ids, available_sources, filename, path)
    return subtype_by_id, variant_by_id, family_ancestry, model_by_id


def _scope_subtype_id(
    scope: Scope,
    category_id: str,
    subtype_by_id: dict[str, SubtypeRecord],
    family_ancestry: dict[str, tuple[str, str, str, str, str]],
    model_by_id: dict[str, IdentityRecord],
    filename: str,
    path: str,
) -> str | None:
    if scope.kind is ScopeKind.CATEGORY:
        if scope.id != category_id:
            _fail(filename, path, "scope hierarchy reference does not match category")
        return None
    if scope.kind is ScopeKind.SUBTYPE:
        if scope.id not in subtype_by_id:
            _fail(filename, path, "scope hierarchy reference does not resolve")
        return scope.id
    if scope.kind is ScopeKind.FAMILY:
        ancestry = family_ancestry.get(scope.id)
        if ancestry is None or ancestry[0] != category_id:
            _fail(filename, path, "scope hierarchy reference does not resolve")
        return ancestry[1]
    model = model_by_id.get(scope.id)
    if model is None or model.category_id != category_id:
        _fail(filename, path, "scope hierarchy reference does not resolve")
    return model.subtype_id


def _validate_endpoint(
    endpoint: str,
    endpoint_kind: LifecycleEndpointKind,
    filename: str,
    path: str,
) -> None:
    if endpoint == "service_life":
        if endpoint_kind is not LifecycleEndpointKind.TOTAL_LIFE:
            _fail(filename, path, "endpoint service_life requires endpoint kind total_life")
    elif endpoint == "capacity_threshold":
        if endpoint_kind is not LifecycleEndpointKind.CAPACITY_THRESHOLD:
            _fail(
                filename,
                path,
                "endpoint capacity_threshold requires endpoint kind capacity_threshold",
            )
    elif endpoint_kind is not LifecycleEndpointKind.OPERATING_ENDURANCE:
        _fail(filename, path, "other endpoints require operating_endurance endpoint kind")


def _validate_lifecycle_common(
    record: SpecificLifecycleRecord | IndustryAverageRecord,
    subtype_id: str | None,
    variant_by_id: dict[str, VariantRecord],
    available_sources: frozenset[str],
    filename: str,
    path: str,
) -> None:
    if record.lower_bound <= 0.0 or record.upper_bound <= 0.0:
        _fail(filename, path, "lifecycle bounds must be positive")
    if record.lower_bound > record.upper_bound:
        _fail(filename, path, "lifecycle bounds are reversed")
    if record.precedence < 0:
        _fail(filename, path, "precedence must be non-negative")
    _validate_range(
        record.model_year_from,
        record.model_year_to,
        filename,
        path,
        "model year",
    )
    _validate_range(
        record.applicable_from,
        record.applicable_to,
        filename,
        path,
        "applicability date",
    )
    intersection = set(record.required_variant_ids) & set(record.excluded_variant_ids)
    if intersection:
        _fail(filename, path, "lifecycle variant filters must be disjoint")
    for variant_id in (*record.required_variant_ids, *record.excluded_variant_ids):
        variant = variant_by_id.get(variant_id)
        if variant is None:
            _fail(filename, path, "variant filter reference does not resolve")
        if subtype_id is None or variant.subtype_id != subtype_id:
            _fail(filename, path, "variant filter must belong to the scoped subtype")
    _validate_endpoint(record.endpoint, record.endpoint_kind, filename, path)
    _source_refs(record.source_ids, available_sources, filename, path)


def _validate_lifecycles(
    documents: CategoryEvidenceDocuments,
    category_id: str,
    subtype_by_id: dict[str, SubtypeRecord],
    variant_by_id: dict[str, VariantRecord],
    family_ancestry: dict[str, tuple[str, str, str, str, str]],
    model_by_id: dict[str, IdentityRecord],
    available_sources: frozenset[str],
) -> None:
    filename = _category_filename(category_id, "lifecycles.yaml")
    for index, record in enumerate(documents.specific_lifecycles):
        path = f"lifecycles[{index}]"
        if record.scope.kind is ScopeKind.CATEGORY:
            _fail(filename, path, "specific lifecycle scope cannot be category")
        subtype_id = _scope_subtype_id(
            record.scope,
            category_id,
            subtype_by_id,
            family_ancestry,
            model_by_id,
            filename,
            path,
        )
        expected = (
            EvidenceLevel.A
            if record.scope.kind is ScopeKind.MODEL
            else EvidenceLevel.B
        )
        if record.evidence_level is EvidenceLevel.D:
            _fail(filename, path, "grade D cannot support lifecycle")
        if record.evidence_level is not expected:
            _fail(filename, path, f"specific lifecycle evidence level must be {expected.value}")
        _validate_lifecycle_common(
            record,
            subtype_id,
            variant_by_id,
            available_sources,
            filename,
            path,
        )

    filename = _category_filename(category_id, "industry_averages.yaml")
    for index, record in enumerate(documents.industry_averages):
        path = f"industry_averages[{index}]"
        _scope_subtype_id(
            record.scope,
            category_id,
            subtype_by_id,
            family_ancestry,
            model_by_id,
            filename,
            path,
        )
        if record.scope != Scope(ScopeKind.CATEGORY, category_id):
            _fail(filename, path, "industry average requires exact category scope")
        if record.subject != "device":
            _fail(filename, path, "industry average subject must be device")
        if record.endpoint != "service_life":
            _fail(filename, path, "industry average endpoint must be service_life")
        if record.endpoint_kind is not LifecycleEndpointKind.TOTAL_LIFE:
            _fail(filename, path, "industry average endpoint kind must be total_life")
        if record.metric != "elapsed_time":
            _fail(filename, path, "industry average metric must be elapsed_time")
        if record.unit != "years":
            _fail(filename, path, "industry average unit must be years")
        if record.evidence_level is not EvidenceLevel.C:
            _fail(filename, path, "industry average evidence level must be C")
        for variant_id in (*record.required_variant_ids, *record.excluded_variant_ids):
            if variant_id not in variant_by_id:
                _fail(filename, path, "variant filter reference does not resolve")
        if (
            record.model_year_from is not None
            or record.model_year_to is not None
            or record.applicable_from is not None
            or record.applicable_to is not None
            or record.required_variant_ids
            or record.excluded_variant_ids
        ):
            _fail(filename, path, "industry average must be unconstrained")
        _validate_lifecycle_common(
            record,
            None,
            variant_by_id,
            available_sources,
            filename,
            path,
        )
        if record.lower_bound >= record.upper_bound:
            _fail(filename, path, "industry average requires a proper interval")


def _scope_evidence_level(scope: Scope, *, allow_category_d: bool = False) -> tuple[EvidenceLevel, ...]:
    if scope.kind is ScopeKind.MODEL:
        return (EvidenceLevel.A,)
    if scope.kind in {ScopeKind.FAMILY, ScopeKind.SUBTYPE}:
        return (EvidenceLevel.B,)
    return (EvidenceLevel.C, EvidenceLevel.D) if allow_category_d else (EvidenceLevel.C,)


def _validate_components(
    documents: CategoryEvidenceDocuments,
    category_id: str,
    subtype_by_id: dict[str, SubtypeRecord],
    family_ancestry: dict[str, tuple[str, str, str, str, str]],
    model_by_id: dict[str, IdentityRecord],
    available_sources: frozenset[str],
) -> dict[str, ComponentTemplate]:
    filename = _category_filename(category_id, "components.yaml")
    component_ids = {item.component_id for item in documents.component_definitions}
    templates_by_id = {item.template_id: item for item in documents.component_templates}
    standards = [
        item
        for item in documents.component_templates
        if item.template_kind is TemplateKind.STANDARD
    ]
    if len(standards) != 1:
        _fail(filename, "templates", "category requires exactly one standard template")
    seen_orders: set[tuple[ScopeKind, str, int]] = set()
    for index, template in enumerate(documents.component_templates):
        path = f"templates[{index}]"
        _scope_subtype_id(
            template.scope,
            category_id,
            subtype_by_id,
            family_ancestry,
            model_by_id,
            filename,
            path,
        )
        if template.application_order < 0:
            _fail(filename, path, "application_order must be non-negative")
        order_key = (template.scope.kind, template.scope.id, template.application_order)
        if order_key in seen_orders:
            _fail(filename, path, "application_order must be unique within a scope")
        seen_orders.add(order_key)
        if template.template_kind is TemplateKind.STANDARD:
            if template.scope != Scope(ScopeKind.CATEGORY, category_id):
                _fail(filename, path, "standard template requires category scope")
            if template.application_order != 0:
                _fail(filename, path, "standard template requires application_order=0")
        elif template.scope.kind is ScopeKind.CATEGORY:
            _fail(filename, path, "overlay template cannot use category scope")

    associations_by_template: dict[str, list[ComponentAssociation]] = {}
    for index, association in enumerate(documents.component_associations):
        path = f"associations[{index}]"
        template = templates_by_id.get(association.template_id)
        if template is None:
            _fail(filename, path, "template reference does not resolve")
        if association.component_id not in component_ids:
            _fail(filename, path, "component reference does not resolve")
        associations_by_template.setdefault(template.template_id, []).append(association)
        if association.position < 0:
            _fail(filename, path, "association position must be non-negative")
        if association.status is AssociationStatus.USER_CONFIRMED:
            _fail(filename, path, "user_confirmed association status cannot be authored")
        if (
            association.status is AssociationStatus.EXACT_MODEL_CONFIRMED
            and template.scope.kind is not ScopeKind.MODEL
        ):
            _fail(filename, path, "exact_model_confirmed requires a model template")
        if (
            association.status is AssociationStatus.LEGACY_SPECIFIC
            and template.template_kind is not TemplateKind.LEGACY_OVERLAY
        ):
            _fail(filename, path, "legacy_specific requires a legacy_overlay")
        if association.status is AssociationStatus.UNKNOWN:
            if association.evidence_level is not None:
                _fail(filename, path, "unknown association evidence level must be null")
            if association.source_ids:
                _fail(filename, path, "unknown association source_ids must be empty")
        else:
            if association.evidence_level is None:
                _fail(filename, path, "reviewed association requires non-null evidence")
            if not association.source_ids:
                _fail(filename, path, "reviewed association requires a source")
            expected = _scope_evidence_level(template.scope)
            if association.evidence_level not in expected:
                _fail(
                    filename,
                    path,
                    f"association evidence level must be {expected[0].value}",
                )
            _source_refs(association.source_ids, available_sources, filename, path)
    for template_id, associations in associations_by_template.items():
        positions = [item.position for item in associations]
        if positions != list(range(len(positions))):
            _fail(
                filename,
                f"templates[{template_id}]",
                "association positions must be contiguous from zero",
            )
    return templates_by_id


def _validate_hazards(
    documents: CategoryEvidenceDocuments,
    category_id: str,
    subtype_by_id: dict[str, SubtypeRecord],
    family_ancestry: dict[str, tuple[str, str, str, str, str]],
    model_by_id: dict[str, IdentityRecord],
    available_sources: frozenset[str],
) -> None:
    filename = _category_filename(category_id, "hazards.yaml")
    component_ids = {item.component_id for item in documents.component_definitions}
    for index, hazard in enumerate(documents.hazards):
        path = f"hazards[{index}]"
        if hazard.component_id not in component_ids:
            _fail(filename, path, "component reference does not resolve")
        _scope_subtype_id(
            hazard.scope,
            category_id,
            subtype_by_id,
            family_ancestry,
            model_by_id,
            filename,
            path,
        )
        allowed = _scope_evidence_level(hazard.scope, allow_category_d=True)
        if hazard.evidence_level not in allowed:
            labels = " or ".join(item.value for item in allowed)
            _fail(filename, path, f"hazard evidence level must be {labels}")
        _source_refs(hazard.source_ids, available_sources, filename, path)


def _validate_unknowns(
    documents: CategoryEvidenceDocuments,
    category_id: str,
) -> None:
    filename = _category_filename(category_id, "coverage.yaml")
    unknown_keys = {
        (item.category_id, item.claim_kind.value, item.claim_id)
        for item in documents.unknowns
    }
    if len(unknown_keys) != len(documents.unknowns):
        _fail(filename, "unknowns", "Unknown stable key values must be unique")
    reviewed: dict[str, set[str]] = {
        "subtype": {item.subtype_id for item in documents.subtypes},
        "variant": {item.variant_id for item in documents.variants},
        "identity": {item.identity_id for item in documents.identities},
        "specific_lifecycle": {
            item.record_id for item in documents.specific_lifecycles
        },
        "industry_average": {
            item.record_id for item in documents.industry_averages
        },
        "component_association": {
            item.association_id
            for item in documents.component_associations
            if item.status is not AssociationStatus.UNKNOWN
        },
        "hazard": {item.hazard_id for item in documents.hazards},
    }
    for index, unknown in enumerate(documents.unknowns):
        path = f"unknowns[{index}]"
        if unknown.category_id != category_id:
            _fail(filename, path, "Unknown category_id must match category directory")
        if unknown.evidence_level is not None:
            _fail(filename, path, "Unknown.evidence_level must be null")
        if unknown.source_ids != ():
            _fail(filename, path, "Unknown.source_ids must be exactly []")
        if unknown.claim_id in reviewed[unknown.claim_kind.value]:
            _fail(filename, path, "Unknown cannot collide with a reviewed claim")
    expected_unknown_associations = {
        item.association_id
        for item in documents.component_associations
        if item.status is AssociationStatus.UNKNOWN
    }
    authored_unknown_associations = {
        item.claim_id
        for item in documents.unknowns
        if item.claim_kind is UnknownClaimKind.COMPONENT_ASSOCIATION
    }
    if expected_unknown_associations != authored_unknown_associations:
        _fail(
            filename,
            "unknowns",
            "every unknown association requires exactly one matching Unknown row",
        )


def _validate_category_documents(
    documents: CategoryEvidenceDocuments,
    category_id: str,
    shared: SharedEvidenceDocuments,
) -> None:
    _validate_category_record_order(documents, category_id)

    source_filename = _category_filename(category_id, "sources.yaml")
    shared_source_ids = frozenset(item.source_id for item in shared.sources)
    category_source_ids = frozenset(item.source_id for item in documents.sources)
    if shared_source_ids & category_source_ids:
        _fail(
            source_filename,
            "sources",
            "source_id values must be globally unique",
        )
    for index, source in enumerate(documents.sources):
        _validate_source(source, source_filename, f"sources[{index}]")
    available_sources = shared_source_ids | category_source_ids

    (
        subtype_by_id,
        variant_by_id,
        family_ancestry,
        model_by_id,
    ) = _validate_identity_hierarchy(
        documents,
        category_id,
        available_sources,
    )
    _validate_lifecycles(
        documents,
        category_id,
        subtype_by_id,
        variant_by_id,
        family_ancestry,
        model_by_id,
        available_sources,
    )
    _validate_components(
        documents,
        category_id,
        subtype_by_id,
        family_ancestry,
        model_by_id,
        available_sources,
    )
    _validate_hazards(
        documents,
        category_id,
        subtype_by_id,
        family_ancestry,
        model_by_id,
        available_sources,
    )
    _validate_unknowns(documents, category_id)


def load_category_evidence_documents(
    source_dir: Path,
    category_id: str,
    *,
    shared: SharedEvidenceDocuments | None = None,
) -> CategoryEvidenceDocuments:
    """Load and validate one category without examining sibling categories."""

    if shared is None:
        shared = load_shared_evidence_documents(Path(source_dir))
    elif not isinstance(shared, SharedEvidenceDocuments):
        _fail(".", "shared", "shared must be SharedEvidenceDocuments")

    category_dir, parsed_category_id = _category_directory(
        Path(source_dir), category_id
    )
    if parsed_category_id not in shared.bundle.category_ids:
        _fail(
            "bundle.yaml",
            "bundle.category_ids",
            "category_id is not declared by the bundle",
        )
    documents = _parse_category_documents(category_dir, parsed_category_id)
    _validate_category_documents(documents, parsed_category_id, shared)
    return documents


def _complete_categories_directory(source_dir: Path) -> Path:
    root = _require_directory(
        Path(source_dir), ".", "source directory is missing or not a directory"
    )
    categories = _require_directory(
        root / "categories",
        "categories",
        "missing category directory",
    )
    try:
        names = {entry.name for entry in categories.iterdir()}
    except OSError as exc:
        _fail("categories", "path", f"unsafe path: {exc}")
    expected = frozenset(RELEASED_CATEGORY_IDS)
    missing = expected - names
    if missing:
        _fail(
            "categories",
            "path",
            f"missing category directory: {sorted(missing)!r}",
        )
    unexpected = names - expected
    if unexpected:
        _fail(
            "categories",
            "path",
            f"unexpected category directory: {sorted(unexpected)!r}",
        )
    return categories


def _validate_global_identifier_namespace(
    categories: tuple[CategoryEvidenceDocuments, ...],
    shared: SharedEvidenceDocuments,
) -> None:
    def require_unique(values: list[str], label: str) -> None:
        if len(values) != len(set(values)):
            _fail(
                "categories",
                label,
                f"{label} values must be globally unique",
            )

    source_ids = [item.source_id for item in shared.sources]
    source_ids.extend(
        item.source_id
        for category in categories
        for item in category.sources
    )
    require_unique(source_ids, "source_id")
    require_unique(
        [
            item.subtype_id
            for category in categories
            for item in category.subtypes
        ],
        "subtype_id",
    )
    require_unique(
        [
            item.variant_id
            for category in categories
            for item in category.variants
        ],
        "variant_id",
    )
    require_unique(
        [
            item.identity_id
            for category in categories
            for item in category.identities
        ],
        "identity_id",
    )
    lifecycle_ids = [
        item.record_id
        for category in categories
        for item in category.specific_lifecycles
    ]
    lifecycle_ids.extend(
        item.record_id
        for category in categories
        for item in category.industry_averages
    )
    require_unique(lifecycle_ids, "record_id")
    require_unique(
        [
            item.template_id
            for category in categories
            for item in category.component_templates
        ],
        "template_id",
    )
    require_unique(
        [
            item.association_id
            for category in categories
            for item in category.component_associations
        ],
        "association_id",
    )
    require_unique(
        [
            item.hazard_id
            for category in categories
            for item in category.hazards
        ],
        "hazard_id",
    )


def load_evidence_documents(source_dir: Path) -> EvidenceDocuments:
    """Load and validate the complete five-category release tree."""

    source_dir = Path(source_dir)
    shared = load_shared_evidence_documents(source_dir)
    _complete_categories_directory(source_dir)
    categories = tuple(
        load_category_evidence_documents(
            source_dir,
            category_id,
            shared=shared,
        )
        for category_id in RELEASED_CATEGORY_IDS
    )
    _validate_global_identifier_namespace(categories, shared)
    return EvidenceDocuments(shared=shared, categories=categories)

"""Frozen public contracts for reviewed evidence bundles."""

from dataclasses import dataclass
from datetime import date
from enum import Enum


RELEASED_CATEGORY_IDS: tuple[str, ...] = (
    "0301_computer_mouse",
    "0301_keyboard",
    "0303_laptop",
    "0306_mobile_phone",
    "0401_headphones",
)


class EvidenceLevel(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class ResolutionTier(str, Enum):
    EXACT_MODEL = "exact_model"
    FAMILY = "family"
    SUBTYPE = "subtype"
    INDUSTRY_AVERAGE = "industry_average"


class ScopeKind(str, Enum):
    CATEGORY = "category"
    SUBTYPE = "subtype"
    FAMILY = "family"
    MODEL = "model"


class IdentityKind(str, Enum):
    FAMILY = "family"
    MODEL = "model"


class MarketState(str, Enum):
    CURRENT = "current"
    DISCONTINUED = "discontinued"
    LEGACY = "legacy"


class BatteryArchitecture(str, Enum):
    BATTERY_FREE = "battery_free"
    BATTERY_BEARING = "battery_bearing"


class LifecycleEndpointKind(str, Enum):
    TOTAL_LIFE = "total_life"
    CAPACITY_THRESHOLD = "capacity_threshold"
    OPERATING_ENDURANCE = "operating_endurance"


class AssociationStatus(str, Enum):
    COMMONLY_ASSOCIATED = "commonly_associated"
    CONDITIONAL = "conditional"
    LEGACY_SPECIFIC = "legacy_specific"
    EXACT_MODEL_CONFIRMED = "exact_model_confirmed"
    USER_CONFIRMED = "user_confirmed"
    NOT_PRESENT = "not_present"
    UNKNOWN = "unknown"


class HazardSeverity(str, Enum):
    ADVISORY = "advisory"
    CAUTION = "caution"
    URGENT = "urgent"


class SourceState(str, Enum):
    REVIEWED = "reviewed"
    UNKNOWN = "unknown"


class RecommendationValue(str, Enum):
    REUSE = "reuse"
    REPAIR = "repair"
    PARTS_RECOVERY = "parts_recovery"
    SPECIALIST_HANDLING = "specialist_handling"
    CERTIFIED_RECYCLING = "certified_recycling"
    MORE_INFORMATION_NEEDED = "more_information_needed"


@dataclass(frozen=True)
class CanonicalIdentityScope:
    category_id: str
    subtype_id: str | None = None
    family_id: str | None = None
    model_id: str | None = None
    variant_ids: tuple[str, ...] = ()
    model_year: int | None = None
    applicable_on: date | None = None


@dataclass(frozen=True)
class LifecycleRequest:
    subject: str
    endpoint: str
    metric: str
    unit: str


@dataclass(frozen=True)
class CategorySnapshot:
    category_id: str
    display_name: str


@dataclass(frozen=True)
class SourceSnapshot:
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
class IdentityRecordSnapshot:
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
    sources: tuple[SourceSnapshot, ...]


@dataclass(frozen=True)
class LifecycleRecordSnapshot:
    record_id: str
    resolution_tier: ResolutionTier
    scope_kind: ScopeKind
    scope_id: str
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
    population_definition: str | None
    publication_period: str | None
    methodology: str | None
    uncertainty: str | None
    limitations: tuple[str, ...]
    sources: tuple[SourceSnapshot, ...]


@dataclass(frozen=True)
class ResolutionStep:
    tier: ResolutionTier
    considered_record_ids: tuple[str, ...]
    rejected: tuple[tuple[str, str], ...]
    selected_record_id: str | None
    outcome: str


@dataclass(frozen=True)
class LifecycleResolution:
    record: LifecycleRecordSnapshot | None
    tier: ResolutionTier | None
    trace: tuple[ResolutionStep, ...]
    unknown_reason: str | None


@dataclass(frozen=True)
class ComponentAssociationSnapshot:
    association_id: str
    template_id: str
    component_id: str
    display_name: str
    status: AssociationStatus
    scope_kind: ScopeKind
    scope_id: str
    applicability: str
    notes: tuple[str, ...]
    evidence_level: EvidenceLevel | None
    sources: tuple[SourceSnapshot, ...]


@dataclass(frozen=True)
class ComponentResolution:
    components: tuple[ComponentAssociationSnapshot, ...]
    applied_template_ids: tuple[str, ...]


@dataclass(frozen=True)
class HazardSnapshot:
    hazard_id: str
    component_id: str
    scope_kind: ScopeKind
    scope_id: str
    applicability: str
    trigger_observation_keys: tuple[str, ...]
    severity: HazardSeverity
    immediate_actions: tuple[str, ...]
    follow_up_actions: tuple[str, ...]
    handling_guidance: tuple[str, ...]
    disposal_guidance: tuple[str, ...]
    evidence_level: EvidenceLevel
    sources: tuple[SourceSnapshot, ...]


@dataclass(frozen=True)
class HazardResolution:
    hazards: tuple[HazardSnapshot, ...]


@dataclass(frozen=True)
class PolicyRuleSnapshot:
    rule_id: str
    priority: int
    outcome: RecommendationValue
    when_all: tuple[str, ...]
    when_any: tuple[str, ...]
    rationale: str
    evidence_level: EvidenceLevel
    sources: tuple[SourceSnapshot, ...]


@dataclass(frozen=True)
class PolicyBundleSnapshot:
    revision: str
    rules: tuple[PolicyRuleSnapshot, ...]


@dataclass(frozen=True)
class BundleStamp:
    schema_version: int
    bundle_version: str
    identity_catalog_version: str
    policy_revision: str
    content_sha256: str


@dataclass(frozen=True)
class ResolvedEvidence:
    scope: CanonicalIdentityScope
    lifecycle: LifecycleResolution
    components: ComponentResolution
    hazards: HazardResolution
    policy: PolicyBundleSnapshot
    bundle: BundleStamp


@dataclass(frozen=True)
class KnowledgeManifest:
    schema_version: int
    bundle_version: str
    identity_catalog_version: str
    policy_revision: str
    content_sha256: str
    coverage_sha256: str

    @property
    def stamp(self) -> BundleStamp:
        return BundleStamp(
            self.schema_version,
            self.bundle_version,
            self.identity_catalog_version,
            self.policy_revision,
            self.content_sha256,
        )

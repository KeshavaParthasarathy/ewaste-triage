# Evidence Bundle and Resolver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the sparse component reference with one immutable, release-bound identity, lifecycle, industry-average, component, hazard, and policy bundle for the five approved categories, plus deterministic resolution and coverage evidence.

**Architecture:** Administrators review category-scoped YAML and compile it outside the product runtime into an atomic schema-3 bundle directory containing `knowledge.sqlite` and `evidence-coverage.json`. The packaged app opens those artifacts through a standard-library-only `KnowledgeStore`; `EvidenceResolver` applies compatibility filters and the exact model → family → subtype → industry-average order, then returns immutable records with complete source snapshots. Lifecycle arithmetic, visible-condition interpretation, recommendation evaluation, scan persistence, and UI presentation remain consumers of this slice rather than responsibilities of the resolver.

**Tech Stack:** Python 3.11, PyYAML 6.0.3 for administrator tooling only, SQLite, frozen dataclasses/enums, JSON, pytest 9.1.1

**Spec:** `docs/superpowers/specs/2026-09-06-ewaste-evidence-condition-prototype-design.md`

## Global Constraints

- The category IDs and order remain exactly `0301_computer_mouse`, `0301_keyboard`, `0303_laptop`, `0306_mobile_phone`, and `0401_headphones`.
- The compiled knowledge schema is `3`; the first bundle version is `3.0.0`; the first identity-catalog version is `1.0.0`; the first policy revision is `2.0.0`.
- Runtime operation is offline. YAML parsing, source acquisition, coverage comparison, and compilation stay in administrator-only `scripts/` modules.
- The schema-2 `ReferenceStore`, source YAML, packaged `components.sqlite`, and its PyYAML dependency remain untouched as a temporary frozen-v1 compatibility path until Slice 5 performs the single manifest/package cutover. A service instance receives either that legacy store or the schema-3 adapter by explicit injection, never both.
- Slice 1 does not modify desktop paths, release metadata, `prepare_release.py`, bundle verification, the macOS build script, the PyInstaller specification, release-manifest schema, packaged smoke tests, or release-note rendering.
- Every imported source records title, publisher, canonical HTTPS URL, publication or revision date, access date, license or use basis, reviewer, and review date.
- Evidence levels are exactly A (exact model), B (family or subtype), C (category or industry range), and D (process or context). Grade D cannot populate lifecycle or item-composition claims.
- Lifecycle and hazard claims own separate provenance; no code copies lifecycle sources into a hazard snapshot or vice versa.
- Lifecycle selection checks subject, endpoint, metric, unit, applicability date, model year, and variant before considering specificity.
- Resolution uses exact model → family → subtype → industry average, selects one reviewed tier, never blends tiers, and returns Unknown for an unresolved same-tier conflict.
- Category-only confirmation can resolve only a category template and industry-average lifecycle record. Unknown identity and free-form text never receive exact-model, family, or subtype evidence.
- Component layers apply category → subtype → family → exact model. Omission never means absence, and hidden parts are never labeled visually detected.
- Hazard records are applicable possibilities with trigger keys; Slice 2 decides whether user observations trigger policy action.
- Unsupported claims remain explicit Unknown records. Missing evidence is never treated as evidence of absence.
- The first release must contain at least ten canonical family/model identities, four technical subtypes, one reviewed broad service-life range, three more-specific lifecycle/endurance records, one standard template, one modern overlay, and one legacy overlay per category.
- Headphones, mice, and keyboards must contain explicit battery-bearing and battery-free variants.
- The compiler emits both a canonical logical content digest and a deterministic coverage artifact. Release tooling separately records raw file hashes.
- No old history or assessment snapshot is rewritten. A newer bundle affects only a user-requested new assessment revision.

## Cross-Slice Contracts

- Slice 1 produces `BundleStamp`, `ResolvedEvidence`, `KnowledgeStore`, and `EvidenceResolver` from the exact interfaces below.
- Slice 2 consumes `ResolvedEvidence`; it owns `AssessmentEngine.assess(...)`, interval arithmetic, threshold-progress presentation, condition adjustments, safety precedence, the closed recommendation result, and verbatim persistence of `BundleStamp`, selected lifecycle records, resolution traces, component/hazard snapshots, and source snapshots in immutable assessment revisions.
- Slice 3 supplies the frozen visible-condition decision consumed by Slice 2; it does not mutate a sourced lifecycle interval or any Slice 1 evidence snapshot.
- Slice 4 consumes the `/api/v2` serialized forms and must not query SQLite or recalculate evidence in browser code.
- Slice 5 consumes the approved three-file handoff and hash expectations defined in Task 14; it alone changes the release manifest from schema 1 to schema 2 and replaces packaged `components.sqlite` with `knowledge.sqlite`.

## File Structure

| File | Responsibility |
|---|---|
| `server/evidence_types.py` | Frozen runtime-neutral evidence, source, scope, resolution, policy, bundle, and manifest contracts |
| `scripts/knowledge_schema.py` | Administrator-only shared, single-category, and complete-tree YAML discovery, strict validation, normalization, and cross-document checks |
| `scripts/knowledge_compiler.py` | Atomic schema-3 SQLite and deterministic coverage-artifact compiler |
| `scripts/build_knowledge_bundle.py` | Stable administrator CLI for compiling and summarizing a bundle |
| `server/knowledge_store.py` | Standard-library-only read-only SQLite/coverage integrity validation and immutable queries |
| `server/evidence_resolver.py` | Lifecycle tier selection plus component and hazard applicability resolution |
| `scripts/evidence_coverage.py` | Coverage report serialization, validation, and release-floor enforcement |
| `scripts/compare_evidence_coverage.py` | Deterministic current-versus-previous coverage change artifact |
| `server/reference_adapter.py` | Temporary `/api/v1` category/template adapter over `KnowledgeStore` and `EvidenceResolver` |
| `reference/bundle.yaml` | Closed bundle, catalog, policy, schema, and category identity |
| `reference/common/sources.yaml` | Sources shared across categories, including handling/process guidance |
| `reference/common/policies.yaml` | Versioned deterministic policy records consumed by Slice 2 |
| `reference/categories/` | The five isolated category corpora; Tasks 8–12 enumerate every exact source path |
| `packaging/evidence-coverage.schema.json` | Closed JSON schema for the full evidence matrix |
| `packaging/evidence-coverage-change.schema.json` | Closed JSON schema for release-to-release evidence changes |
| `tests/knowledge_helpers.py` | Valid synthetic shared, single-category, and five-category source trees plus mutation helpers for unit tests |
| `tests/test_evidence_types.py` | Frozen type, enum, scope, and serialization contracts |
| `tests/test_knowledge_schema.py` | Shared/category/full-tree staging, closed schema, provenance, hierarchy, endpoint, path, and license validation |
| `tests/test_knowledge_compiler.py` | SQL schema, atomic output, logical digest, deterministic report, and failure recovery |
| `tests/test_knowledge_store.py` | Read-only startup, raw/logical/report integrity, queries, and tamper rejection |
| `tests/test_evidence_resolver.py` | Compatibility-before-specificity, conflicts, overlays, hazards, sources, and Unknown behavior |
| `tests/test_evidence_coverage.py` | Coverage schema, floor, comparison, and deterministic serialization |
| `tests/corpus/test_mouse_evidence.py` | Mouse roster and claim-level release acceptance |
| `tests/corpus/test_keyboard_evidence.py` | Keyboard roster and claim-level release acceptance |
| `tests/corpus/test_laptop_evidence.py` | Laptop roster and claim-level release acceptance |
| `tests/corpus/test_phone_evidence.py` | Mobile-phone roster and claim-level release acceptance |
| `tests/corpus/test_headphones_evidence.py` | Headphones roster and claim-level release acceptance |
| `tests/test_knowledge_release.py` | Whole-corpus digest, coverage, resolver, and release-boundary acceptance |

---

### Task 1: Freeze the evidence and bundle contracts

**Files:**
- Create: `server/evidence_types.py`
- Create: `tests/test_evidence_types.py`

**Interfaces:**
- Produces constant: `RELEASED_CATEGORY_IDS: tuple[str, ...]`
- Produces closed enums: `EvidenceLevel`, `ResolutionTier`, `ScopeKind`, `IdentityKind`, `MarketState`, `BatteryArchitecture`, `LifecycleEndpointKind`, `AssociationStatus`, `HazardSeverity`, `SourceState`, and `RecommendationValue`
- Produces frozen records: `CanonicalIdentityScope`, `LifecycleRequest`, `CategorySnapshot`, `SourceSnapshot`, `IdentityRecordSnapshot`, `LifecycleRecordSnapshot`, `ResolutionStep`, `LifecycleResolution`, `ComponentAssociationSnapshot`, `ComponentResolution`, `HazardSnapshot`, `HazardResolution`, `PolicyRuleSnapshot`, `PolicyBundleSnapshot`, `BundleStamp`, `ResolvedEvidence`, and `KnowledgeManifest`
- Produces: `KnowledgeManifest.stamp -> BundleStamp`

- [ ] **Step 1: Write failing enum, immutability, and bundle-stamp tests**

```python
from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from server.evidence_types import (
    BundleStamp,
    CanonicalIdentityScope,
    EvidenceLevel,
    KnowledgeManifest,
    RELEASED_CATEGORY_IDS,
    RecommendationValue,
    ResolutionTier,
)


def test_bundle_stamp_is_exact_and_immutable():
    stamp = BundleStamp(3, "3.0.0", "1.0.0", "2.0.0", "a" * 64)
    assert stamp == BundleStamp(
        schema_version=3,
        bundle_version="3.0.0",
        identity_catalog_version="1.0.0",
        policy_revision="2.0.0",
        content_sha256="a" * 64,
    )
    with pytest.raises(FrozenInstanceError):
        stamp.bundle_version = "3.0.1"


def test_manifest_projects_the_only_assessment_bundle_stamp():
    manifest = KnowledgeManifest(3, "3.0.0", "1.0.0", "2.0.0", "a" * 64, "b" * 64)
    assert manifest.stamp == BundleStamp(3, "3.0.0", "1.0.0", "2.0.0", "a" * 64)


def test_scope_and_closed_values_match_the_approved_contract():
    scope = CanonicalIdentityScope(
        category_id="0306_mobile_phone",
        subtype_id="phone_slate_smartphone",
        family_id="apple_iphone_15_family",
        model_id="apple_iphone_15",
        variant_ids=("battery_integrated",),
        model_year=2023,
        applicable_on=date(2026, 9, 7),
    )
    assert scope.model_id == "apple_iphone_15"
    assert {item.value for item in EvidenceLevel} == {"A", "B", "C", "D"}
    assert [item.value for item in ResolutionTier] == [
        "exact_model", "family", "subtype", "industry_average"
    ]
    assert {item.value for item in RecommendationValue} == {
        "reuse", "repair", "parts_recovery", "specialist_handling",
        "certified_recycling", "more_information_needed",
    }


def test_released_category_ids_are_ordered_and_closed():
    assert RELEASED_CATEGORY_IDS == (
        "0301_computer_mouse",
        "0301_keyboard",
        "0303_laptop",
        "0306_mobile_phone",
        "0401_headphones",
    )
```

- [ ] **Step 2: Run the contract test and verify RED**

Run: `.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_evidence_types.py -v`

Expected: FAIL during collection because `server.evidence_types` does not exist.

- [ ] **Step 3: Implement the exact frozen public contracts**

Use these enum values and field signatures in `server/evidence_types.py`; tuple fields prevent callers from mutating store output:

```python
RELEASED_CATEGORY_IDS = (
    "0301_computer_mouse",
    "0301_keyboard",
    "0303_laptop",
    "0306_mobile_phone",
    "0401_headphones",
)

# Enum values are closed to these strings.
# EvidenceLevel: A, B, C, D
# ResolutionTier: exact_model, family, subtype, industry_average
# ScopeKind: category, subtype, family, model
# IdentityKind: family, model
# MarketState: current, discontinued, legacy
# BatteryArchitecture: battery_free, battery_bearing
# LifecycleEndpointKind: total_life, capacity_threshold, operating_endurance
# AssociationStatus: commonly_associated, conditional, legacy_specific,
#                    exact_model_confirmed, user_confirmed, not_present, unknown
# HazardSeverity: advisory, caution, urgent
# SourceState: reviewed, unknown
# RecommendationValue: reuse, repair, parts_recovery, specialist_handling,
#                      certified_recycling, more_information_needed


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
```

`ResolutionStep.outcome` accepts only `no_candidates`, `filtered`, `selected`, or `conflict`. Industry-average lifecycle rows populate all five industry fields; other lifecycle rows set the first four to `None` and `limitations` to an empty tuple. Authored component records may not use `user_confirmed`; Slice 2 may use that status only for an attributed user override. No convenience property may flatten source IDs or bundle fields in persisted v2 snapshots.

- [ ] **Step 4: Run contract tests and compile the module**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_evidence_types.py -v
.venv/bin/python -m py_compile server/evidence_types.py
```

Expected: PASS; mutation attempts fail; enum values and every dataclass field match the cross-slice contract.

- [ ] **Step 5: Commit the contracts**

```bash
git add server/evidence_types.py tests/test_evidence_types.py
git commit -m "feat: define evidence bundle contracts"
```

## Normative Authoring YAML Contract

This section is the sole schema for the schema-3 administrator source tree. An
implementer must not infer fields from the frozen-v1 YAML, a corpus narrative,
or a compiler table. Every mapping is closed: every listed key is required,
unknown keys are rejected, and a key may be `null` only where its type below
explicitly includes `null`. A `list[T]` is always present and may be empty; a
`nonempty list[T]` is always present and has at least one item. YAML defaults,
anchors, aliases, merge keys, explicit tags, duplicate keys, and non-scalar map
keys are rejected before record validation.

### Fixed paths and document roots

The tree has ten fixed paths using nine document schemas because the shared and
category source files reuse the same closed `Source` schema. Their exact
top-level keys are:

| Relative path | Exact root keys |
|---|---|
| `bundle.yaml` | `bundle` |
| `common/sources.yaml` | `sources` |
| `common/policies.yaml` | `policy_revision`, `policies` |
| `categories/<category_id>/sources.yaml` | `sources` |
| `categories/<category_id>/identities.yaml` | `category`, `subtypes`, `variants`, `identities` |
| `categories/<category_id>/lifecycles.yaml` | `lifecycles` |
| `categories/<category_id>/industry_averages.yaml` | `industry_averages` |
| `categories/<category_id>/components.yaml` | `components`, `templates`, `associations` |
| `categories/<category_id>/hazards.yaml` | `hazards` |
| `categories/<category_id>/coverage.yaml` | `unknowns` |

`sources` has one schema in both source files. The shared source list must be
non-empty; a category source list may be empty when every category claim uses a
shared source. All other root list values are lists rather than `null`; Task 6,
not the scalar parser, enforces the release-count floor. `bundle` and `category`
are mappings. `policy_revision` is a scalar and `policies` is a non-empty list.

The only schema-3 entries directly below `source_dir` are `bundle.yaml`,
`common/`, and optional `categories/`. While the frozen-v1 path coexists,
`source_dir/sources.yaml` and `source_dir/device_components.yaml` are permitted
but never opened by these loaders. No other root or `common/` entry is accepted.
Each requested category directory contains exactly the seven category files
above, all regular files. No loader follows a symlink at any path component.
`category_id` is first checked against `RELEASED_CATEGORY_IDS` as a scalar ID,
then joined as one path component, resolved, and checked for containment. The
directory name, its `category.category_id`, and every authored `category_id`
must match exactly.

`load_shared_evidence_documents` validates only `bundle.yaml` and `common/` and
does not require or enumerate `categories/`. `load_category_evidence_documents`
validates only the requested category against shared records and does not
enumerate siblings. `load_evidence_documents` calls those two stages, requires
exactly the five category directories in `RELEASED_CATEGORY_IDS`, and performs
the cross-category uniqueness checks. Thus the shared, single-category, and
complete-tree validators remain independently green.

### Scalar, ID, ordering, and reference rules

- `Id` is an NFC YAML string matching `[a-z0-9][a-z0-9_.-]*`. IDs and references
  are case-sensitive and are never repaired or case-folded.
- `Text` is a non-empty, trimmed NFC YAML string without NUL or Unicode control
  characters. Nullable text is either `Text` or YAML `null`, never `""`.
- `Date` is a quoted YAML string in canonical `YYYY-MM-DD` form that round-trips
  through `datetime.date.isoformat()`. Native YAML timestamps are rejected.
- `SemVer` is a YAML string matching
  `(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)`; prerelease/build forms
  are not used by this bundle. The first values remain exactly `3.0.0`, `1.0.0`,
  and `2.0.0`.
- `int` means `type(value) is int`; `number` means an `int` or `float`, excluding
  booleans, normalized to `float`, finite, and not NaN or infinity.
- Record-list sort keys are exact: sources by `source_id`; policies by
  `(priority, rule_id)`; subtypes by `subtype_id`; variants by `variant_id`;
  identities by `identity_id`; both lifecycle lists by `record_id`; component
  definitions by `component_id`; templates by `template_id`; associations by
  `(template_id, position, association_id)`; hazards by `hazard_id`; and
  Unknowns by `(category_id, claim_kind, claim_id)`. `category_ids` has the
  released order rather than lexical order. Reference-ID lists are sorted by ID
  and have no duplicates. Predicates are sorted bytewise. Display-order lists
  (`assumptions`, `limitations`, association `notes`, and hazard action/guidance
  lists) preserve authored order but reject exact duplicate strings.
- Identity aliases are normalized only for collision checks by NFC, trimming,
  collapsing internal Unicode whitespace to one ASCII space, and `casefold()`.
  That key must be unique across every identity display name and alias in one
  category. Distinguishing tokens use the same normalization and must be unique
  within their identity. Stored display text remains the authored NFC text.
- Shared `source_id` values and all category `source_id` values are globally
  unique. Policy rules may reference shared sources only. A category claim may
  reference shared sources or sources from its own category, never a sibling
  category. References do not inherit: every claim-bearing record owns its
  exact `source_ids` list.
- `subtype_id`, `variant_id`, `identity_id`, lifecycle `record_id`,
  `template_id`, `association_id`, and `hazard_id` are globally unique in a
  complete tree. `component_id` is unique within a category because generic
  component IDs such as `storage` may validly recur across categories. A
  `(manufacturer_id, manufacturer_name)` and `(family_id, family_name)` pair
  must be consistent everywhere it occurs in a category.
- All nullable `from`/`to` pairs permit either open end; when both are present,
  `from <= to`. Source publication/revision date must be on or before access
  date, and review date must be on or after access date.
- A canonical URL is an NFC `Text` parsed with no whitespace or user-info,
  lowercase `https` scheme, non-empty host, and no fragment. Its parsed and
  reserialized value must equal the authored value. `https://example.invalid/`
  and descendants are valid only for synthetic test fixtures.

### Exact record shapes

The notation below is normative. Fields appear in this order in normalized
frozen authoring records, although YAML mapping order is not semantic.

```text
BundleMetadata = {
  schema_version: int, bundle_version: SemVer,
  identity_catalog_version: SemVer, policy_revision: SemVer,
  category_ids: nonempty list[Id]
}

Source = {
  source_id: Id, title: Text, publisher: Text, canonical_url: HTTPS URL,
  publication_or_revision_date: Date, accessed_on: Date,
  license_or_use_basis: Text, reviewed_by: Text, reviewed_on: Date
}

Policy = {
  rule_id: Id, priority: int, outcome: RecommendationValue,
  when_all: list[PolicyPredicate], when_any: list[PolicyPredicate],
  rationale: Text, evidence_level: EvidenceLevel,
  source_ids: nonempty list[Id]
}

Category = {category_id: Id, display_name: Text}

Subtype = {
  subtype_id: Id, category_id: Id, display_name: Text,
  market_state: MarketState, battery_architecture: BatteryArchitecture,
  evidence_level: EvidenceLevel, source_ids: nonempty list[Id]
}

Variant = {
  variant_id: Id, category_id: Id, subtype_id: Id, display_name: Text,
  battery_architecture: BatteryArchitecture,
  evidence_level: EvidenceLevel, source_ids: nonempty list[Id]
}

Identity = {
  identity_id: Id, identity_kind: IdentityKind, category_id: Id,
  subtype_id: Id, manufacturer_id: Id, manufacturer_name: Text,
  family_id: Id, family_name: Text, model_id: Id | null,
  model_name: Text | null, display_name: Text,
  aliases: nonempty list[Text], distinguishing_tokens: nonempty list[Text],
  model_year_from: int | null, model_year_to: int | null,
  applicable_from: Date | null, applicable_to: Date | null,
  variant_ids: list[Id], market_state: MarketState,
  battery_architecture: BatteryArchitecture,
  evidence_level: EvidenceLevel, source_ids: nonempty list[Id]
}

Scope = {kind: ScopeKind, id: Id}

SpecificLifecycle = {
  record_id: Id, scope: Scope, subject: Id, endpoint: Id,
  endpoint_kind: LifecycleEndpointKind, metric: Id, unit: Id,
  lower_bound: number, upper_bound: number, endpoint_qualification: Text,
  applicable_from: Date | null, applicable_to: Date | null,
  model_year_from: int | null, model_year_to: int | null,
  required_variant_ids: list[Id], excluded_variant_ids: list[Id],
  precedence: int, evidence_level: EvidenceLevel,
  assumptions: list[Text], source_ids: nonempty list[Id]
}

IndustryAverage = {
  record_id: Id, scope: Scope, subject: Id, endpoint: Id,
  endpoint_kind: LifecycleEndpointKind, metric: Id, unit: Id,
  lower_bound: number, upper_bound: number, endpoint_qualification: Text,
  applicable_from: Date | null, applicable_to: Date | null,
  model_year_from: int | null, model_year_to: int | null,
  required_variant_ids: list[Id], excluded_variant_ids: list[Id],
  precedence: int, evidence_level: EvidenceLevel,
  assumptions: list[Text], population_definition: Text,
  publication_period: Text, methodology: Text, uncertainty: Text,
  limitations: nonempty list[Text], source_ids: nonempty list[Id]
}

ComponentDefinition = {component_id: Id, display_name: Text}

ComponentTemplate = {
  template_id: Id,
  template_kind: standard | modern_overlay | legacy_overlay,
  scope: Scope, application_order: int
}

ComponentAssociation = {
  association_id: Id, template_id: Id, component_id: Id, position: int,
  status: AssociationStatus, applicability: Text, notes: list[Text],
  evidence_level: EvidenceLevel | null, source_ids: list[Id]
}

Hazard = {
  hazard_id: Id, component_id: Id, scope: Scope, applicability: Text,
  trigger_observation_keys: nonempty list[HazardTriggerKey],
  severity: HazardSeverity, immediate_actions: nonempty list[Text],
  follow_up_actions: nonempty list[Text],
  handling_guidance: nonempty list[Text],
  disposal_guidance: nonempty list[Text],
  evidence_level: EvidenceLevel, source_ids: nonempty list[Id]
}

Unknown = {
  category_id: Id, claim_kind: UnknownClaimKind, claim_id: Id,
  evidence_level: null, source_ids: list[Id],
  reason: Text, evidence_request: Text
}
```

`Unknown.source_ids` must be exactly `[]`; its stable identity is exactly the
tuple `(category_id, claim_kind, claim_id)`, and no `unknown_id` or generated ID
exists. `UnknownClaimKind` is exactly `subtype`, `variant`, `identity`,
`specific_lifecycle`, `industry_average`, `component_association`, or `hazard`.
An Unknown row describes an unsupported intended claim; it neither creates the
referenced domain record nor proves absence. Unknown stable keys are unique and
must not collide with a reviewed claim of the same key. The coverage compiler
emits it as `source_state="unknown"`, `evidence_level=null`, and
`unknown_reason=reason`.

### Hierarchy, scope, endpoint, component, and evidence rules

- `bundle.category_ids` equals `RELEASED_CATEGORY_IDS` exactly. Bundle schema is
  `3`, bundle version is `3.0.0`, identity catalog version is `1.0.0`, and its
  policy revision is `2.0.0`. `common/policies.yaml.policy_revision` must equal
  the bundle value. Policy priorities are non-negative and unique; rules are
  evaluated by `(priority, rule_id)`, and the first matching rule supplies the
  outcome.
- A subtype belongs to its authored category. A variant references a subtype in
  that category. An identity references a subtype and only variants owned by
  that subtype. Its battery architecture equals its subtype and every referenced
  variant. A family identity has `identity_id == family_id`,
  `identity_kind=family`, and null model fields. A model identity has
  `identity_id == model_id`, `identity_kind=model`, and non-null model fields.
  A model's family need not have a separate search-result row, but every use of
  that `family_id` must have identical category, subtype, manufacturer, and
  family-name ancestry.
- A `Scope` has exactly `kind` and `id`. Its ID resolves inside the current
  category: category → category ID, subtype → `subtype_id`, family → a
  `family_id` present in identities, and model → a non-null `model_id` present in
  identities. No redundant `category_id`, `subtype_id`, `family_id`, or
  `model_id` is accepted inside a scope.
- A specific lifecycle permits only model, family, or subtype scope. Its
  resolution tier is derived, never authored: model → `exact_model`, family →
  `family`, subtype → `subtype`. Model records require evidence A; family and
  subtype records require evidence B. An industry average requires exact scope
  `{kind: category, id: <current category>}`, evidence C, endpoint
  `service_life`, endpoint kind `total_life`, subject `device`, metric
  `elapsed_time`, and unit `years`; its year/date constraints are all `null`,
  its required/excluded variant lists are both empty, and its tier is derived as
  `industry_average`.
- `endpoint_kind` is separate from the endpoint label. `endpoint=service_life`
  requires `total_life`; `endpoint=capacity_threshold` requires
  `capacity_threshold`; every other first-bundle endpoint requires
  `operating_endurance`. A threshold/endurance row cannot satisfy the broad
  total-life floor. All bounds are finite and positive. A specific lifecycle
  permits `lower_bound <= upper_bound`, including a sourced point threshold;
  an industry average requires the proper interval `lower_bound < upper_bound`
  and can never publish a point estimate.
  Precedence is a non-negative integer; equal precedence remains legal so the
  resolver can return the specified same-tier conflict. Required and excluded
  variants are sorted, disjoint, and valid for the scoped subtype/family/model.
- Applicability uses only the immutable `CanonicalIdentityScope`; there is no
  wall-clock input and no range endpoint, midpoint, or current date is guessed.
  As frozen by Slice 2's **Closed Wire Contracts**, confirmed/edited decisions
  contain only `identity_id`, reject client-authored scope fields, and obtain
  their entire scope from `KnowledgeStore.identity_scope(identity_id)`.
  Therefore that method copies `category_id`, `subtype_id`, `family_id`,
  `model_id`, and the identity's exact ordered `variant_ids`; it sets
  `model_year` to the one bound only when `model_year_from` and
  `model_year_to` are both non-null and equal, otherwise `None`; and it sets
  `applicable_on` to the one date only when `applicable_from` and
  `applicable_to` are both non-null and equal, otherwise `None`. Slice 2 has no
  user decision field from which either singular value could otherwise come.
- Lifecycle year and date bounds are inclusive. If a candidate has either
  model-year bound while `scope.model_year is None`, it is ineligible with
  trace reason `model year unavailable`; a present value outside either bound
  is ineligible with `model year out of range`. The identical rule for
  applicability dates uses `applicability date unavailable` and
  `applicability date out of range`. An unconstrained candidate (both bounds
  null) remains eligible when the corresponding singular scope value is
  missing. Required variants must be a subset of `scope.variant_ids`; otherwise
  the candidate is ineligible with `required variant missing`. Any intersection
  with excluded variants makes it ineligible with `excluded variant present`.
  Category-only constructs exactly `CanonicalIdentityScope(category_id)`, so
  subtype/family/model/year/date are `None` and variants are empty; it can
  select only category-scoped records with null year/date bounds and empty
  variant filters. The preceding industry-average rule guarantees those
  constraints for every authored average.
- Component definitions are structural and carry no evidence/source fields.
  Each category has exactly one `standard` template with category scope and
  `application_order=0`. Modern/legacy templates are overlays scoped only to a
  subtype, family, or model. `application_order` is non-negative and unique
  within one `(scope.kind, scope.id)`; eligible templates apply by fixed scope
  order category → subtype → family → model, then by
  `(application_order, template_id)` within a scope. Task 6 enforces at least one
  modern and one legacy overlay for release.
- An association references one same-category template and component. Positions
  are the contiguous integers `0..n-1` within a template and determine display
  order. `user_confirmed` is never authored. A more-specific/later eligible
  association replaces the prior association for that component, including an
  explicit `not_present` or `unknown`; omitting a component from an overlay
  preserves the previous association. Category-only resolution applies only the
  standard category template. `exact_model_confirmed` is valid only on a model
  template and `legacy_specific` only on a `legacy_overlay`.
- Final component order is deterministic and does not add a field to the Task 1
  snapshot. Visit eligible templates in the layer order just specified and
  visit each template's associations by ascending `position`. Maintain an
  ordered slot list plus a `component_id → slot` index. The first occurrence of
  a component appends a slot. A later occurrence of that component replaces the
  association in its established slot; it never moves the slot. A component
  first introduced by an overlay appends when first encountered. Omission from
  an overlay is a no-op. Explicit `not_present` and `unknown` associations are
  ordinary replacements and retain the established slot. Return
  `ComponentResolution.components` as the resulting tuple and
  `applied_template_ids` in the same template visitation order.
- A non-Unknown association requires non-null evidence and non-empty sources:
  category scope → C, family/subtype → B, model → A. An authored association
  with status `unknown` requires `evidence_level=null` and `source_ids=[]`; its
  development/release gap is represented by exactly one `Unknown` row with
  `claim_kind=component_association` and `claim_id=association_id`. That
  association does not emit a reviewed coverage row.
- A hazard references a component definition and a valid same-category scope.
  Model hazards use A, family/subtype hazards use B, and category hazards use C
  or process/context D. Grade D never supports lifecycle, subtype, variant,
  identity, or component-association claims. Hazard sources are authored and
  compiled independently of lifecycle sources; neither list is copied or
  inherited from the other.
- Source-bearing subtype and variant rows use B; family identity rows use B;
  model identity rows use A; industry averages use C. Every non-Unknown
  claim-bearing row has at least one resolvable source ID. License/use basis is
  never inferred from publisher or URL.

### Closed policy predicates and hazard triggers

`PolicyPredicate` is one exact string from the list below. There is no `not`,
comparison, wildcard, path lookup, interpolation, or executable expression
syntax.

```text
identity.state=canonical
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
hazards.triggered_severity=urgent
```

The first four observation families map directly to Slice 2's closed
`UserObservations` keys. `lifecycle.required_usage` means `age_months` for
`elapsed_time` or `full_charge_cycles` for that metric; unsupported metrics are
`missing`. `lifecycle.position` comes only from Slice 2's endpoint-compatible
calculation. `component_decisions.any_present` inspects only user decisions with
status `present`. `hazards.triggered_severity` is the greatest severity among
applicable hazards whose trigger matches, or `none`. A rule matches when every
`when_all` predicate is true and `when_any` is empty or at least one `when_any`
predicate is true. A predicate may occur only once per rule and not in both
groups; mutually exclusive values for one family in `when_all` are rejected.

`HazardTriggerKey` is exactly one of:

```text
observations.issue_flags.overheating
observations.issue_flags.odor
observations.issue_flags.swelling_or_battery_damage
observations.issue_flags.recall
```

Trigger keys are sorted and unique. A hazard is triggered when any listed flag
is true. The list is deliberately non-empty: the approved hazard contract ties
every conditional safety action to an explicit user observation. An applicable
but untriggered hazard may still be displayed as a sourced possibility; it does
not select hazard policy action. General process guidance with no observation
trigger remains source/policy context rather than a synthetic triggered hazard.
`issue_flags.notes`, visible findings/grades, OCR, and image-model output are
deliberately absent from this vocabulary: a photograph never triggers a hazard
claim.

### Normalized documents and compiler conversion

`scripts.knowledge_schema` produces frozen authoring records and these exact
aggregate fields; it exposes no aliases such as `lifecycles`, `components`, or
`templates` on `CategoryEvidenceDocuments`:

```text
SharedEvidenceDocuments = {bundle, sources, policies}
CategoryEvidenceDocuments = {
  category, sources, subtypes, variants, identities, specific_lifecycles,
  industry_averages, component_definitions, component_templates,
  component_associations, hazards, unknowns
}
EvidenceDocuments = {shared, categories}
```

YAML root `lifecycles` normalizes to `specific_lifecycles`; YAML roots
`components`, `templates`, and `associations` normalize respectively to
`component_definitions`, `component_templates`, and `component_associations`.
All list values normalize to immutable tuples, dates to `date`, enums to the
Task 1 enums, and bounds to `float`. `EvidenceDocuments.categories` is ordered
exactly as `RELEASED_CATEGORY_IDS`.

Compiler/store conversion is exact:

- `Source` becomes `SourceSnapshot`; `Category` becomes `CategorySnapshot`.
- `Identity` becomes `IdentityRecordSnapshot` after its evidence level is kept
  for coverage and each `source_id` is expanded to a complete `SourceSnapshot`.
- Both lifecycle authoring types become `LifecycleRecordSnapshot`. Scope is
  flattened to `scope_kind/scope_id`; tier is derived as above. A specific row
  sets `population_definition`, `publication_period`, `methodology`, and
  `uncertainty` to `None` and `limitations` to `()`. An average populates all
  five industry fields. Sources are expanded independently per row.
- A component association joins its template and definition to form
  `ComponentAssociationSnapshot`: template ID, component ID/display name,
  template-derived scope, association fields, and that association's expanded
  sources. Resolver layer order is the template order specified above.
- `Hazard` flattens its scope and independently expands its sources into
  `HazardSnapshot`. Policy rows expand to `PolicyRuleSnapshot` and the root
  revision plus sorted rules become `PolicyBundleSnapshot`.
- Bundle metadata plus the compiler digest/report hashes becomes
  `KnowledgeManifest`; `.stamp` remains the Task 1 five-field `BundleStamp`.
  Unknown rows never become runtime evidence snapshots.

The schema-3 database tables and semantic columns are exactly:

```text
metadata(key, value)
sources(source_id, title, publisher, canonical_url,
        publication_or_revision_date, accessed_on, license_or_use_basis,
        reviewed_by, reviewed_on)
categories(category_id, display_name, release_order)
subtypes(subtype_id, category_id, display_name, market_state,
         battery_architecture, evidence_level)
variants(variant_id, category_id, subtype_id, display_name,
         battery_architecture, evidence_level)
identities(identity_id, identity_kind, category_id, subtype_id,
           manufacturer_id, manufacturer_name, family_id, family_name,
           model_id, model_name, display_name, model_year_from, model_year_to,
           applicable_from, applicable_to, market_state,
           battery_architecture, evidence_level)
identity_aliases(identity_id, ordinal, alias, alias_casefold)
identity_tokens(identity_id, ordinal, token, token_casefold)
identity_variants(identity_id, ordinal, variant_id)
lifecycle_records(record_id, category_id, resolution_tier, scope_kind,
                  scope_id, subject, endpoint, endpoint_kind, metric, unit,
                  lower_bound, upper_bound, endpoint_qualification,
                  applicable_from, applicable_to, model_year_from,
                  model_year_to, precedence, evidence_level)
lifecycle_required_variants(record_id, ordinal, variant_id)
lifecycle_excluded_variants(record_id, ordinal, variant_id)
lifecycle_assumptions(record_id, ordinal, assumption)
industry_averages(record_id, population_definition, publication_period,
                  methodology, uncertainty)
lifecycle_limitations(record_id, ordinal, limitation)
components(category_id, component_id, display_name)
component_templates(template_id, category_id, template_kind, scope_kind,
                    scope_id, application_order)
component_associations(association_id, category_id, template_id, component_id,
                       position, status, applicability, evidence_level)
component_association_notes(association_id, ordinal, note)
hazards(hazard_id, category_id, component_id, scope_kind, scope_id,
        applicability, severity, evidence_level)
hazard_triggers(hazard_id, ordinal, observation_key)
hazard_actions(hazard_id, action_kind, ordinal, action_text)
policy_rules(rule_id, priority, outcome, rationale, evidence_level)
policy_predicates(rule_id, predicate_group, ordinal, predicate)
coverage_unknowns(category_id, claim_kind, claim_id, reason, evidence_request)
claim_sources(claim_kind, category_key, claim_id, ordinal, source_id)
```

Primary/foreign keys follow the authored identities: components use
`(category_id, component_id)`; coverage Unknowns use their three-field stable
key; ordinal child tables use `(parent_id, ordinal)` and also reject duplicate
values. `hazard_actions.action_kind` is exactly `immediate`, `follow_up`,
`handling`, or `disposal`; `policy_predicates.predicate_group` is `all` or
`any`. `claim_sources.category_key` is the released category ID for category
claims and the empty string for a shared policy. Its `claim_kind` is exactly
`subtype`, `variant`, `identity`, `specific_lifecycle`, `industry_average`,
`component_association`, `hazard`, or `policy`. All semantic columns and ordinal
rows participate in canonical JSON and `content_sha256`; no YAML-only semantic
value is discarded.

### Task 2: Validate the administrator authoring tree

**Files:**
- Create: `scripts/knowledge_schema.py`
- Create: `tests/knowledge_helpers.py`
- Create: `tests/test_knowledge_schema.py`

**Interfaces:**
- Produces: `EvidenceValidationError(filename: str, record_path: str, message: str)`
- Produces frozen `SharedEvidenceDocuments`, `CategoryEvidenceDocuments`, and `EvidenceDocuments`
- `SharedEvidenceDocuments` owns exactly `bundle`, `sources`, and `policies`
- `CategoryEvidenceDocuments` owns exactly `category`, `sources`, `subtypes`, `variants`, `identities`, `specific_lifecycles`, `industry_averages`, `component_definitions`, `component_templates`, `component_associations`, `hazards`, and `unknowns`; there are no `lifecycles`, `components`, or `templates` aliases
- `EvidenceDocuments` owns exactly `shared` and the complete `categories` tuple ordered by `RELEASED_CATEGORY_IDS`
- Produces: `load_shared_evidence_documents(source_dir: Path) -> SharedEvidenceDocuments`
- Produces: `load_category_evidence_documents(source_dir: Path, category_id: str, *, shared: SharedEvidenceDocuments | None = None) -> CategoryEvidenceDocuments`
- Produces: `load_evidence_documents(source_dir: Path) -> EvidenceDocuments`
- `tests/knowledge_helpers.py` produces `make_valid_shared_knowledge_source(root: Path) -> Path`, `make_valid_category_knowledge_source(root: Path, category_id: str) -> Path`, `make_valid_knowledge_source(root: Path) -> Path`, `mutate_yaml(path: Path, mutation: Callable[[dict[str, object]], None]) -> None`, `mutate_document_root(source: Path, relative_path: str, expected_keys: set[str], mutation_kind: str) -> None`, `replace_with_non_mapping_yaml_root(source: Path, relative_path: str) -> None`, `root_key_sets(source: Path) -> dict[str, set[str]]`, `root_value_type_sets(source: Path) -> dict[str, dict[str, str]]`, `record_key_sets(source: Path) -> dict[str, set[str]]`, `record_field_type_sets(source: Path) -> dict[str, dict[str, str]]`, `root_schema_mutations() -> tuple[SchemaMutation, ...]`, `all_closed_record_cases() -> tuple[SchemaCase, ...]`, `closed_schema_mutations(case: SchemaCase) -> tuple[SchemaMutation, ...]`, `all_closed_schema_mutations() -> tuple[SchemaMutation, ...]`, `shared_raw_yaml_mutations() -> tuple[SchemaMutation, ...]`, `category_raw_yaml_mutations(category_id: str) -> tuple[SchemaMutation, ...]`, `shared_path_mutations() -> tuple[SchemaMutation, ...]`, `category_path_mutations(category_id: str) -> tuple[SchemaMutation, ...]`, and `complete_tree_mutations() -> tuple[SchemaMutation, ...]`
- Consumes: the exact fixed-path and authoring contract above

`SchemaCase` is frozen and has exactly `name`, `relative_path`, `selector`,
`expected_keys`, `field_types`, `required_nonnull_fields`, `nullable_fields`,
`nullable_underlying_types`, `list_fields`, `list_item_types`, `integer_fields`,
`number_fields`, `enum_fields`, `id_fields`, `text_fields`, `date_fields`,
`semver_fields`, `https_url_fields`, `nested_mapping_fields`, and
`reference_fields`.
`SchemaMutation` is frozen and has exactly `name`, `kind`, `target_field`,
`type_contract`, `apply`, and `expected_error`. `field_types`, nullable
underlying types, list item types, and nested-map case names use the exact type
tokens below. The cases repeat the normative field contract in machine-checkable
test data; mutation generation is driven by those cases, not by a hand-picked
list of a few representative records.

- [ ] **Step 1: Write failing closed-schema, provenance, hierarchy, and path tests**

```python
from dataclasses import fields


ROOT_KEYS = {
    "bundle.yaml": {"bundle"},
    "common/sources.yaml": {"sources"},
    "common/policies.yaml": {"policy_revision", "policies"},
    "categories/{category_id}/sources.yaml": {"sources"},
    "categories/{category_id}/identities.yaml": {
        "category", "subtypes", "variants", "identities",
    },
    "categories/{category_id}/lifecycles.yaml": {"lifecycles"},
    "categories/{category_id}/industry_averages.yaml": {"industry_averages"},
    "categories/{category_id}/components.yaml": {
        "components", "templates", "associations",
    },
    "categories/{category_id}/hazards.yaml": {"hazards"},
    "categories/{category_id}/coverage.yaml": {"unknowns"},
}

ROOT_VALUE_TYPES = {
    "bundle.yaml": {"bundle": "mapping:bundle"},
    "common/sources.yaml": {"sources": "nonempty_list:source"},
    "common/policies.yaml": {
        "policy_revision": "semver", "policies": "nonempty_list:policy",
    },
    "categories/{category_id}/sources.yaml": {"sources": "list:source"},
    "categories/{category_id}/identities.yaml": {
        "category": "mapping:category", "subtypes": "list:subtype",
        "variants": "list:variant", "identities": "list:identity",
    },
    "categories/{category_id}/lifecycles.yaml": {
        "lifecycles": "list:specific_lifecycle",
    },
    "categories/{category_id}/industry_averages.yaml": {
        "industry_averages": "list:industry_average",
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
        "schema_version", "bundle_version", "identity_catalog_version",
        "policy_revision", "category_ids",
    },
    "source": {
        "source_id", "title", "publisher", "canonical_url",
        "publication_or_revision_date", "accessed_on", "license_or_use_basis",
        "reviewed_by", "reviewed_on",
    },
    "policy": {
        "rule_id", "priority", "outcome", "when_all", "when_any",
        "rationale", "evidence_level", "source_ids",
    },
    "category": {"category_id", "display_name"},
    "subtype": {
        "subtype_id", "category_id", "display_name", "market_state",
        "battery_architecture", "evidence_level", "source_ids",
    },
    "variant": {
        "variant_id", "category_id", "subtype_id", "display_name",
        "battery_architecture", "evidence_level", "source_ids",
    },
    "identity": {
        "identity_id", "identity_kind", "category_id", "subtype_id",
        "manufacturer_id", "manufacturer_name", "family_id", "family_name",
        "model_id", "model_name", "display_name", "aliases",
        "distinguishing_tokens", "model_year_from", "model_year_to",
        "applicable_from", "applicable_to", "variant_ids", "market_state",
        "battery_architecture", "evidence_level", "source_ids",
    },
    "specific_lifecycle": {
        "record_id", "scope", "subject", "endpoint", "endpoint_kind",
        "metric", "unit", "lower_bound", "upper_bound",
        "endpoint_qualification", "applicable_from", "applicable_to",
        "model_year_from", "model_year_to", "required_variant_ids",
        "excluded_variant_ids", "precedence", "evidence_level", "assumptions",
        "source_ids",
    },
    "industry_average": {
        "record_id", "scope", "subject", "endpoint", "endpoint_kind",
        "metric", "unit", "lower_bound", "upper_bound",
        "endpoint_qualification", "applicable_from", "applicable_to",
        "model_year_from", "model_year_to", "required_variant_ids",
        "excluded_variant_ids", "precedence", "evidence_level", "assumptions",
        "population_definition", "publication_period", "methodology",
        "uncertainty", "limitations", "source_ids",
    },
    "component_definition": {"component_id", "display_name"},
    "component_template": {
        "template_id", "template_kind", "scope", "application_order",
    },
    "component_association": {
        "association_id", "template_id", "component_id", "position", "status",
        "applicability", "notes", "evidence_level", "source_ids",
    },
    "hazard": {
        "hazard_id", "component_id", "scope", "applicability",
        "trigger_observation_keys", "severity", "immediate_actions",
        "follow_up_actions", "handling_guidance", "disposal_guidance",
        "evidence_level", "source_ids",
    },
    "unknown": {
        "category_id", "claim_kind", "claim_id", "evidence_level",
        "source_ids", "reason", "evidence_request",
    },
    "scope": {"kind", "id"},
}

FIELD_TYPES = {
    "bundle": {
        "schema_version": "int", "bundle_version": "semver",
        "identity_catalog_version": "semver", "policy_revision": "semver",
        "category_ids": "nonempty_list:id",
    },
    "source": {
        "source_id": "id", "title": "text", "publisher": "text",
        "canonical_url": "https_url",
        "publication_or_revision_date": "date", "accessed_on": "date",
        "license_or_use_basis": "text", "reviewed_by": "text",
        "reviewed_on": "date",
    },
    "policy": {
        "rule_id": "id", "priority": "int",
        "outcome": "enum:RecommendationValue",
        "when_all": "list:policy_predicate",
        "when_any": "list:policy_predicate", "rationale": "text",
        "evidence_level": "enum:EvidenceLevel",
        "source_ids": "nonempty_list:id",
    },
    "category": {"category_id": "id", "display_name": "text"},
    "subtype": {
        "subtype_id": "id", "category_id": "id", "display_name": "text",
        "market_state": "enum:MarketState",
        "battery_architecture": "enum:BatteryArchitecture",
        "evidence_level": "enum:EvidenceLevel",
        "source_ids": "nonempty_list:id",
    },
    "variant": {
        "variant_id": "id", "category_id": "id", "subtype_id": "id",
        "display_name": "text",
        "battery_architecture": "enum:BatteryArchitecture",
        "evidence_level": "enum:EvidenceLevel",
        "source_ids": "nonempty_list:id",
    },
    "identity": {
        "identity_id": "id", "identity_kind": "enum:IdentityKind",
        "category_id": "id", "subtype_id": "id", "manufacturer_id": "id",
        "manufacturer_name": "text", "family_id": "id",
        "family_name": "text", "model_id": "nullable:id",
        "model_name": "nullable:text", "display_name": "text",
        "aliases": "nonempty_list:text",
        "distinguishing_tokens": "nonempty_list:text",
        "model_year_from": "nullable:int", "model_year_to": "nullable:int",
        "applicable_from": "nullable:date", "applicable_to": "nullable:date",
        "variant_ids": "list:id", "market_state": "enum:MarketState",
        "battery_architecture": "enum:BatteryArchitecture",
        "evidence_level": "enum:EvidenceLevel",
        "source_ids": "nonempty_list:id",
    },
    "specific_lifecycle": {
        "record_id": "id", "scope": "mapping:scope", "subject": "id",
        "endpoint": "id", "endpoint_kind": "enum:LifecycleEndpointKind",
        "metric": "id", "unit": "id", "lower_bound": "number",
        "upper_bound": "number", "endpoint_qualification": "text",
        "applicable_from": "nullable:date", "applicable_to": "nullable:date",
        "model_year_from": "nullable:int", "model_year_to": "nullable:int",
        "required_variant_ids": "list:id", "excluded_variant_ids": "list:id",
        "precedence": "int", "evidence_level": "enum:EvidenceLevel",
        "assumptions": "list:text", "source_ids": "nonempty_list:id",
    },
    "industry_average": {
        "record_id": "id", "scope": "mapping:scope", "subject": "id",
        "endpoint": "id", "endpoint_kind": "enum:LifecycleEndpointKind",
        "metric": "id", "unit": "id", "lower_bound": "number",
        "upper_bound": "number", "endpoint_qualification": "text",
        "applicable_from": "nullable:date", "applicable_to": "nullable:date",
        "model_year_from": "nullable:int", "model_year_to": "nullable:int",
        "required_variant_ids": "list:id", "excluded_variant_ids": "list:id",
        "precedence": "int", "evidence_level": "enum:EvidenceLevel",
        "assumptions": "list:text", "population_definition": "text",
        "publication_period": "text", "methodology": "text",
        "uncertainty": "text", "limitations": "nonempty_list:text",
        "source_ids": "nonempty_list:id",
    },
    "component_definition": {"component_id": "id", "display_name": "text"},
    "component_template": {
        "template_id": "id", "template_kind": "enum:TemplateKind",
        "scope": "mapping:scope", "application_order": "int",
    },
    "component_association": {
        "association_id": "id", "template_id": "id", "component_id": "id",
        "position": "int", "status": "enum:AssociationStatus",
        "applicability": "text", "notes": "list:text",
        "evidence_level": "nullable:enum:EvidenceLevel",
        "source_ids": "list:id",
    },
    "hazard": {
        "hazard_id": "id", "component_id": "id", "scope": "mapping:scope",
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
        "category_id": "id", "claim_kind": "enum:UnknownClaimKind",
        "claim_id": "id", "evidence_level": "literal:null",
        "source_ids": "list:id", "reason": "text", "evidence_request": "text",
    },
    "scope": {"kind": "enum:ScopeKind", "id": "id"},
}


def test_normalized_document_surfaces_have_no_aliases():
    assert tuple(field.name for field in fields(SharedEvidenceDocuments)) == (
        "bundle", "sources", "policies",
    )
    assert tuple(field.name for field in fields(CategoryEvidenceDocuments)) == (
        "category", "sources", "subtypes", "variants", "identities",
        "specific_lifecycles", "industry_averages", "component_definitions",
        "component_templates", "component_associations", "hazards", "unknowns",
    )
    assert tuple(field.name for field in fields(EvidenceDocuments)) == (
        "shared", "categories",
    )


def test_helper_fixture_pins_every_root_and_record_shape(tmp_path):
    source = make_valid_knowledge_source(tmp_path)
    assert root_key_sets(source) == ROOT_KEYS
    assert root_value_type_sets(source) == ROOT_VALUE_TYPES
    assert record_key_sets(source) == RECORD_KEYS
    assert record_field_type_sets(source) == FIELD_TYPES


@pytest.mark.parametrize("relative_path,expected_keys", ROOT_KEYS.items())
def test_every_document_root_is_closed(tmp_path, relative_path, expected_keys):
    source = make_valid_knowledge_source(tmp_path / "unknown")
    mutate_document_root(source, relative_path, expected_keys, "unknown_key")
    with pytest.raises(EvidenceValidationError, match="document root"):
        load_evidence_documents(source)
    for missing_key in expected_keys:
        source = make_valid_knowledge_source(tmp_path / f"missing-{missing_key}")
        mutate_document_root(
            source, relative_path, expected_keys, f"missing_key:{missing_key}"
        )
        with pytest.raises(EvidenceValidationError, match="document root"):
            load_evidence_documents(source)


def test_every_root_value_type_and_list_item_type_is_mutated(tmp_path):
    expected = {
        ("wrong_type", f"{path}:{key}", contract)
        for path, fields in ROOT_VALUE_TYPES.items()
        for key, contract in fields.items()
    }
    expected |= {
        ("wrong_list_item_type", f"{path}:{key}", contract.split(":", 1)[1])
        for path, fields in ROOT_VALUE_TYPES.items()
        for key, contract in fields.items()
        if contract.startswith(("list:", "nonempty_list:"))
    }
    expected |= {
        ("invalid_nested_mapping_shape", f"{path}:{key}", contract.split(":", 1)[1])
        for path, fields in ROOT_VALUE_TYPES.items()
        for key, contract in fields.items()
        if contract.startswith("mapping:")
    }
    expected |= {
        ("invalid_contract_value", f"{path}:{key}", "semver")
        for path, fields in ROOT_VALUE_TYPES.items()
        for key, contract in fields.items()
        if contract == "semver"
    }
    mutations = root_schema_mutations()
    assert {(item.kind, item.target_field, item.type_contract) for item in mutations} == expected
    for mutation in mutations:
        source = make_valid_knowledge_source(tmp_path / mutation.name)
        mutation.apply(source)
        with pytest.raises(EvidenceValidationError, match=mutation.expected_error):
            load_evidence_documents(source)


@pytest.mark.parametrize("case", all_closed_record_cases())
def test_every_record_schema_rejects_its_complete_mutation_matrix(tmp_path, case):
    for mutation in closed_schema_mutations(case):
        source = make_valid_knowledge_source(tmp_path / mutation.name)
        mutation.apply(source)
        with pytest.raises(EvidenceValidationError, match=mutation.expected_error):
            load_evidence_documents(source)


def test_mutation_matrix_covers_every_closed_failure_class():
    assert {mutation.kind for mutation in all_closed_schema_mutations()} == {
        "unknown_key", "missing_key", "null_nonnullable", "wrong_type",
        "invalid_contract_value", "boolean_as_integer", "nonfinite_number",
        "nullable_wrong_underlying_type", "null_list", "wrong_list_item_type",
        "invalid_list_item_value", "duplicate_list_item", "unsorted_set_list",
        "invalid_nested_mapping_shape", "broken_reference",
        "evidence_scope_mismatch",
    }


def nullable_contracts(field_types):
    return {
        (field_name, contract.removeprefix("nullable:"))
        for field_name, contract in field_types.items()
        if contract.startswith("nullable:")
    }


def list_contracts(field_types):
    return {
        (
            field_name,
            contract.removeprefix("nonempty_list:").removeprefix("list:"),
        )
        for field_name, contract in field_types.items()
        if contract.startswith(("list:", "nonempty_list:"))
    }


def nested_contracts(field_types):
    return {
        (field_name, contract.removeprefix("mapping:"))
        for field_name, contract in field_types.items()
        if contract.startswith("mapping:")
    }


def fields_with_atomic_contract(field_types, atomic_contract):
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


def fields_with_prefix_contract(field_types, prefix):
    return {
        field_name
        for field_name, contract in field_types.items()
        if contract.startswith(prefix) or contract.startswith(f"nullable:{prefix}")
    }


@pytest.mark.parametrize("case", all_closed_record_cases())
def test_each_case_mutates_every_required_key_and_typed_field(case):
    mutations = closed_schema_mutations(case)
    assert case.expected_keys == RECORD_KEYS[case.name]
    assert dict(case.field_types) == FIELD_TYPES[case.name]
    assert set(case.nullable_underlying_types) == nullable_contracts(
        FIELD_TYPES[case.name]
    )
    assert set(case.list_item_types) == list_contracts(FIELD_TYPES[case.name])
    assert set(case.nested_mapping_fields) == nested_contracts(
        FIELD_TYPES[case.name]
    )
    assert case.id_fields == fields_with_atomic_contract(FIELD_TYPES[case.name], "id")
    assert case.text_fields == fields_with_atomic_contract(
        FIELD_TYPES[case.name], "text"
    )
    assert case.date_fields == fields_with_atomic_contract(
        FIELD_TYPES[case.name], "date"
    )
    assert case.semver_fields == fields_with_atomic_contract(
        FIELD_TYPES[case.name], "semver"
    )
    assert case.https_url_fields == fields_with_atomic_contract(
        FIELD_TYPES[case.name], "https_url"
    )
    assert case.nullable_fields == {
        field_name
        for field_name, contract in FIELD_TYPES[case.name].items()
        if contract.startswith("nullable:") or contract == "literal:null"
    }
    assert case.required_nonnull_fields == case.expected_keys - case.nullable_fields
    assert case.list_fields == fields_with_prefix_contract(
        FIELD_TYPES[case.name], "list:"
    ) | fields_with_prefix_contract(FIELD_TYPES[case.name], "nonempty_list:")
    assert case.integer_fields == fields_with_atomic_contract(
        FIELD_TYPES[case.name], "int"
    )
    assert case.number_fields == fields_with_atomic_contract(
        FIELD_TYPES[case.name], "number"
    )
    assert case.enum_fields == fields_with_prefix_contract(
        FIELD_TYPES[case.name], "enum:"
    )
    assert {item.target_field for item in mutations if item.kind == "missing_key"} == (
        case.expected_keys
    )
    assert {
        item.target_field for item in mutations if item.kind == "null_nonnullable"
    } == case.required_nonnull_fields
    assert case.required_nonnull_fields | case.nullable_fields == case.expected_keys
    assert case.required_nonnull_fields.isdisjoint(case.nullable_fields)
    assert {
        (item.target_field, item.type_contract)
        for item in mutations if item.kind == "wrong_type"
    } == set(FIELD_TYPES[case.name].items())
    assert {
        (item.target_field, item.type_contract)
        for item in mutations if item.kind == "nullable_wrong_underlying_type"
    } == set(case.nullable_underlying_types)
    assert {
        (item.target_field, item.type_contract)
        for item in mutations if item.kind == "wrong_list_item_type"
    } == set(case.list_item_types)
    assert {
        item.target_field for item in mutations if item.kind == "null_list"
    } == case.list_fields
    assert {
        (item.target_field, item.type_contract)
        for item in mutations if item.kind == "invalid_list_item_value"
    } == set(case.list_item_types)
    assert {
        (item.target_field, item.type_contract)
        for item in mutations if item.kind == "invalid_nested_mapping_shape"
    } == set(case.nested_mapping_fields)
    assert {
        item.target_field for item in mutations if item.kind == "boolean_as_integer"
    } == case.integer_fields | case.number_fields
    assert {
        item.target_field for item in mutations if item.kind == "nonfinite_number"
    } == case.number_fields
    assert all(
        any(
            item.target_field == field_name
            and item.kind in {"invalid_contract_value", "invalid_list_item_value"}
            for item in mutations
        )
        for field_name in (
            case.id_fields | case.text_fields | case.date_fields
            | case.semver_fields | case.https_url_fields | case.enum_fields
        )
    )


RAW_YAML_REJECTIONS = {
    "duplicate_key", "anchor_definition", "alias_reference", "merge_key",
    "explicit_tag", "non_scalar_mapping_key", "non_mapping_document_root",
    "non_nfc_text", "untrimmed_text", "control_character_text",
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
    "bundle.yaml", "common/sources.yaml", "common/policies.yaml",
)
CATEGORY_ROOT_PATHS = tuple(
    path.format(category_id="0301_computer_mouse")
    for path in ROOT_KEYS
    if path.startswith("categories/")
)

SHARED_PATH_REJECTION_TARGETS = {
    ("symlink_source_dir", "."),
    ("symlink_common_directory", "common"),
    *{
        ("symlink_document", path)
        for path in SHARED_ROOT_PATHS
    },
    ("unexpected_root_entry", "unexpected-root.yaml"),
    ("unexpected_common_entry", "common/unexpected.yaml"),
}

CATEGORY_PATH_REJECTION_TARGETS = {
    ("symlink_categories_directory", "categories"),
    ("symlink_category_directory", "categories/0301_computer_mouse"),
    *{("symlink_document", path) for path in CATEGORY_ROOT_PATHS},
    (
        "unexpected_category_entry",
        "categories/0301_computer_mouse/unexpected.yaml",
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
        with pytest.raises(EvidenceValidationError, match=mutation.expected_error):
            load_shared_evidence_documents(source)


def test_category_loader_executes_every_hostile_raw_yaml_case(tmp_path):
    mutations = category_raw_yaml_mutations("0301_computer_mouse")
    assert {item.name for item in mutations} == RAW_YAML_REJECTIONS
    assert {
        (item.kind, item.target_field) for item in mutations
    } == set(CATEGORY_RAW_YAML_REJECTION_TARGETS.items())
    for mutation in mutations:
        source = make_valid_category_knowledge_source(
            tmp_path / mutation.name, "0301_computer_mouse",
        )
        shared = load_shared_evidence_documents(source)
        mutation.apply(source)
        with pytest.raises(EvidenceValidationError, match=mutation.expected_error):
            load_category_evidence_documents(
                source, "0301_computer_mouse", shared=shared,
            )


@pytest.mark.parametrize("relative_path", SHARED_ROOT_PATHS)
def test_shared_loader_rejects_each_non_mapping_root(tmp_path, relative_path):
    source = make_valid_shared_knowledge_source(tmp_path / relative_path.replace("/", "-"))
    replace_with_non_mapping_yaml_root(source, relative_path)
    with pytest.raises(EvidenceValidationError, match="mapping root"):
        load_shared_evidence_documents(source)


@pytest.mark.parametrize("relative_path", CATEGORY_ROOT_PATHS)
def test_category_loader_rejects_each_non_mapping_root(tmp_path, relative_path):
    source = make_valid_category_knowledge_source(tmp_path, "0301_computer_mouse")
    shared = load_shared_evidence_documents(source)
    replace_with_non_mapping_yaml_root(source, relative_path)
    with pytest.raises(EvidenceValidationError, match="mapping root"):
        load_category_evidence_documents(
            source, "0301_computer_mouse", shared=shared,
        )


def test_shared_loader_rejects_its_own_hostile_paths(tmp_path):
    mutations = shared_path_mutations()
    assert {
        (item.kind, item.target_field) for item in mutations
    } == SHARED_PATH_REJECTION_TARGETS
    for mutation in mutations:
        source = make_valid_shared_knowledge_source(tmp_path / mutation.name)
        mutation.apply(source)
        with pytest.raises(EvidenceValidationError, match=mutation.expected_error):
            load_shared_evidence_documents(source)


def test_category_loader_rejects_its_own_hostile_paths(tmp_path):
    mutations = category_path_mutations("0301_computer_mouse")
    assert {
        (item.kind, item.target_field) for item in mutations
    } == CATEGORY_PATH_REJECTION_TARGETS
    for mutation in mutations:
        source = make_valid_category_knowledge_source(
            tmp_path / mutation.name, "0301_computer_mouse",
        )
        shared = load_shared_evidence_documents(source)
        mutation.apply(source)
        with pytest.raises(EvidenceValidationError, match=mutation.expected_error):
            load_category_evidence_documents(
                source, "0301_computer_mouse", shared=shared,
            )


def test_complete_loader_enforces_global_sibling_category_closure(tmp_path):
    mutations = complete_tree_mutations()
    assert {
        (item.kind, item.target_field) for item in mutations
    } == COMPLETE_TREE_REJECTION_TARGETS
    for mutation in mutations:
        source = make_valid_knowledge_source(tmp_path / mutation.name)
        mutation.apply(source)
        with pytest.raises(EvidenceValidationError, match=mutation.expected_error):
            load_evidence_documents(source)


def test_loader_rejects_unknown_source_fields(tmp_path):
    source = make_valid_knowledge_source(tmp_path)
    mutate_yaml(source / "common/sources.yaml", lambda doc: doc["sources"][0].update({"trust_me": True}))
    with pytest.raises(EvidenceValidationError, match=r"common/sources.yaml: sources\[0\].*trust_me"):
        load_evidence_documents(source)


def test_grade_d_cannot_support_lifecycle(tmp_path):
    source = make_valid_knowledge_source(tmp_path)
    path = source / "categories/0303_laptop/lifecycles.yaml"
    mutate_yaml(path, lambda doc: doc["lifecycles"][0].update({"evidence_level": "D"}))
    with pytest.raises(EvidenceValidationError, match="grade D cannot support lifecycle"):
        load_evidence_documents(source)


def test_industry_average_rejects_a_point_value(tmp_path):
    source = make_valid_knowledge_source(tmp_path)
    path = source / "categories/0303_laptop/industry_averages.yaml"
    mutate_yaml(
        path,
        lambda doc: doc["industry_averages"][0].update(
            {"lower_bound": 4.0, "upper_bound": 4.0}
        ),
    )
    with pytest.raises(EvidenceValidationError, match="proper interval"):
        load_evidence_documents(source)


def test_specific_lifecycle_may_preserve_a_sourced_point_threshold(tmp_path):
    source = make_valid_knowledge_source(tmp_path)
    path = source / "categories/0306_mobile_phone/lifecycles.yaml"
    mutate_yaml(
        path,
        lambda doc: doc["lifecycles"][0].update(
            {"lower_bound": 800.0, "upper_bound": 800.0}
        ),
    )
    assert load_evidence_documents(source).categories[3].specific_lifecycles[0]


@pytest.mark.parametrize(
    ("relative_path", "root_key"),
    [
        ("categories/0303_laptop/lifecycles.yaml", "lifecycles"),
        (
            "categories/0303_laptop/industry_averages.yaml",
            "industry_averages",
        ),
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
    tmp_path, relative_path, root_key, case_name, lower_bound, upper_bound, message,
):
    source = make_valid_knowledge_source(
        tmp_path / f"{root_key}-{case_name}",
    )
    path = source / relative_path
    mutate_yaml(
        path,
        lambda doc: doc[root_key][0].update(
            {"lower_bound": lower_bound, "upper_bound": upper_bound}
        ),
    )
    with pytest.raises(EvidenceValidationError, match=message):
        load_evidence_documents(source)


@pytest.mark.parametrize(
    "field,value",
    (
        ("model_year_from", 2020), ("model_year_to", 2025),
        ("applicable_from", "2020-01-01"), ("applicable_to", "2025-01-01"),
        ("required_variant_ids", ["phone_battery_integrated"]),
        ("excluded_variant_ids", ["phone_battery_integrated"]),
    ),
)
def test_industry_average_must_be_unconstrained(tmp_path, field, value):
    source = make_valid_knowledge_source(tmp_path)
    path = source / "categories/0306_mobile_phone/industry_averages.yaml"
    mutate_yaml(path, lambda doc: doc["industry_averages"][0].update({field: value}))
    with pytest.raises(EvidenceValidationError, match="industry average.*unconstrained"):
        load_evidence_documents(source)


def test_model_scope_must_match_the_canonical_hierarchy(tmp_path):
    source = make_valid_knowledge_source(tmp_path)
    path = source / "categories/0306_mobile_phone/lifecycles.yaml"
    mutate_yaml(path, lambda doc: doc["lifecycles"][0]["scope"].update({"id": "0303_laptop_model_00"}))
    with pytest.raises(EvidenceValidationError, match="scope hierarchy"):
        load_evidence_documents(source)


def test_shared_loader_is_green_before_category_authoring(tmp_path):
    source = make_valid_shared_knowledge_source(tmp_path)
    shared = load_shared_evidence_documents(source)
    assert tuple(shared.bundle.category_ids) == RELEASED_CATEGORY_IDS
    assert shared.sources
    assert shared.policies


def test_single_category_loader_does_not_require_sibling_categories(tmp_path):
    source = make_valid_category_knowledge_source(
        tmp_path, "0301_computer_mouse"
    )
    shared = load_shared_evidence_documents(source)
    category = load_category_evidence_documents(
        source, "0301_computer_mouse", shared=shared
    )
    assert category.category.category_id == "0301_computer_mouse"
    with pytest.raises(EvidenceValidationError, match="missing category directory"):
        load_evidence_documents(source)


def test_complete_loader_is_green_and_ordered(tmp_path):
    source = make_valid_knowledge_source(tmp_path)
    documents = load_evidence_documents(source)
    assert tuple(
        item.category.category_id for item in documents.categories
    ) == RELEASED_CATEGORY_IDS
```

- [ ] **Step 2: Run schema tests and verify RED**

Run: `.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_knowledge_schema.py -v`

Expected: FAIL during collection because the loader and helpers do not exist.

- [ ] **Step 3: Implement fixed discovery and scalar validation**

Implement three explicit validation stages rather than making partial authoring impersonate a complete release tree:

- `load_shared_evidence_documents` reads only `bundle.yaml` and the two fixed `common/*.yaml` files. It validates the exact released category list, bundle/catalog/policy identities, shared source records, and policy syntax without requiring `reference/categories/` to exist.
- `load_category_evidence_documents` first accepts or loads the shared documents, verifies that `category_id` is declared by the bundle, and reads only the seven fixed files below that one category. It validates the category against shared sources and policy vocabulary but does not require sibling category directories. Reject an unexpected file or symlink inside the requested category.
- `load_evidence_documents` is the release-complete entry point. It loads shared documents, calls the single-category loader for every category in `RELEASED_CATEGORY_IDS`, rejects missing or extra category directories, and then applies cross-category checks before returning `EvidenceDocuments`.

The shared and category entry points each run their own path-component,
regular-file, hostile-YAML, and closed-directory checks before decoding a
record; their safety does not depend on being called through the complete
loader. The direct shared tests cover the source directory, `bundle.yaml`, and
all `common/` paths. The direct category tests pass an already-valid shared
object, then cover the requested `categories/` path, category directory, and
all seven category documents. Only `load_evidence_documents` enumerates sibling
categories, so its direct mutation matrix owns missing, extra, and symlinked
released-sibling closure. Across their respective scopes, reject symlinks,
duplicate YAML keys, non-mapping roots, unknown fields, booleans used as
integers, non-finite numbers, non-NFC text, IDs outside
`[a-z0-9][a-z0-9_.-]*`, invalid semantic versions, invalid ISO dates, and
non-HTTPS canonical URLs. A missing sibling category is an error only for
`load_evidence_documents`, never for the shared or requested-category entry
point.

Each source mapping accepts exactly:

```yaml
source_id: epa_used_li_ion_2026
title: Used Lithium-Ion Batteries
publisher: United States Environmental Protection Agency
canonical_url: https://www.epa.gov/recycle/used-lithium-ion-batteries
publication_or_revision_date: "2026-01-01"
accessed_on: "2026-09-07"
license_or_use_basis: public-government-guidance
reviewed_by: release-reviewer
reviewed_on: "2026-09-07"
```

`tests/knowledge_helpers.py` must define the `SchemaCase`/`SchemaMutation`
descriptors and helpers used above, generate reusable valid shared documents, a
requested-category tree, and a fully valid synthetic five-category tree. Every
synthetic category has ten identities, at least four subtypes, subtype-owned
variants (including the required battery architectures), one average, three
specific lifecycle/endurance records, component definitions, exactly three
component templates with ordered associations, one hazard, and one explicit
Unknown. The helper writes every nullable field and list explicitly, uses only
the fixed roots, and uses `https://example.invalid/` URLs; none of its synthetic
records is copied into production `reference/`.

The raw-YAML mutations splice bytes directly rather than round-tripping through
`yaml.safe_dump`, so duplicate keys, anchors, aliases, merge keys, tags,
non-scalar keys, native timestamps, and malformed root kinds reach the loader
unchanged. Shared/category path mutations exercise every path component and
document through that exact public loader; complete-tree mutations exercise
only global sibling closure. `all_closed_schema_mutations()` is the flattened
record matrix; tests compare its `(case, field, type_contract, rejection class)`
coverage to `FIELD_TYPES`; root, raw-parser, and filesystem tests compare exact
targets to `ROOT_VALUE_TYPES`, `RAW_YAML_REJECTIONS`, both scoped raw target
maps, both scoped path target sets, and `COMPLETE_TREE_REJECTION_TARGETS`. A new
field, type, fixed path, public-loader scope, or rejection class therefore
cannot silently lack a negative test.

- [ ] **Step 4: Implement cross-document claim checks**

The shared loader validates shared-source ID uniqueness, policy revision equality,
unique non-negative priorities, the exact predicate vocabulary/group semantics,
policy source references, and all closed source/policy fields. The
single-category loader constructs all twelve canonical
`CategoryEvidenceDocuments` fields and validates uniqueness against shared IDs,
casefolded identity-display/alias uniqueness, category/subtype/variant/family/
model ancestry, year/date ranges, scoped variant references, per-claim source
references, scope-derived evidence tiers, endpoint-kind separation, finite
positive ordered bounds, all industry methodology fields, the three distinct
component record types and their overlay/position rules, authored association
statuses excluding `user_confirmed`, hazard component/scope references, the
four exact trigger keys, ordered actions/guidance, independent hazard
provenance, and stable deliberate-Unknown keys/reason/evidence request. The
complete loader additionally validates globally unique IDs and exact
category-directory closure.

- [ ] **Step 5: Run schema and type suites**

Run: `.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_evidence_types.py tests/test_knowledge_schema.py -v`

Expected: PASS for each valid shared-only, requested-category, and complete
synthetic tree and every root/record closure, type/null/list, source, predicate,
trigger, hierarchy, range, applicability, component overlay, provenance,
symlink, and Unknown mutation.

- [ ] **Step 6: Commit the authoring validator**

```bash
git add scripts/knowledge_schema.py tests/knowledge_helpers.py tests/test_knowledge_schema.py
git commit -m "feat: validate knowledge authoring sources"
```

### Task 3: Compile one atomic schema-3 knowledge bundle

**Files:**
- Create: `scripts/knowledge_compiler.py`
- Create: `scripts/build_knowledge_bundle.py`
- Create: `scripts/evidence_coverage.py`
- Create: `packaging/evidence-coverage.schema.json`
- Create: `tests/test_knowledge_compiler.py`
- Create: `tests/test_evidence_coverage.py`

**Interfaces:**
- Consumes: `load_evidence_documents(source_dir: Path) -> EvidenceDocuments`
- Consumes only the canonical category fields `specific_lifecycles`, `component_definitions`, `component_templates`, and `component_associations`; it does not look for `lifecycles`, `components`, or `templates` aliases
- Produces: `KnowledgeCompilationError` for stable compiler/path/promotion failures
- Produces: `CoverageError` for closed full-report validation failures
- Produces the testable pure projection `normalized_sql_rows(documents: EvidenceDocuments) -> Mapping[str, tuple[tuple[object, ...], ...]]`; keys, columns, rows, SQLite scalar conversion, and primary-key ordering are the exact contracts below. Its `metadata` rows are the four semantic release values; the two computed hash rows are appended only after their inputs exist
- Produces `logical_content_sha256(rows: Mapping[str, tuple[tuple[object, ...], ...]]) -> str`; the compiler writes and hashes the same projected rows
- Produces `build_coverage(documents: EvidenceDocuments, content_sha256: str) -> dict[str, object]`
- Produces `validate_coverage_report(report: Mapping[str, object]) -> None`
- Produces `coverage_json_bytes(report: Mapping[str, object]) -> bytes`
- Produces: `compile_knowledge_bundle(source_dir: Path, destination_dir: Path) -> KnowledgeManifest`
- Produces fixed files: `<destination_dir>/knowledge.sqlite` and `<destination_dir>/evidence-coverage.json`
- Produces CLI: `python scripts/build_knowledge_bundle.py --source PATH --out DIRECTORY --print-summary`

#### Frozen SQLite wire schema

The database has exactly 26 application tables in this exact `TABLE_ORDER`;
SQLite internal tables are forbidden because none of these declarations uses
`AUTOINCREMENT`:

```python
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
        "publication_or_revision_date", "accessed_on",
        "license_or_use_basis", "reviewed_by", "reviewed_on",
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
    "hazard_actions": (
        "hazard_id", "action_kind", "ordinal", "action_text",
    ),
    "policy_rules": (
        "rule_id", "priority", "outcome", "rationale", "evidence_level",
    ),
    "policy_predicates": (
        "rule_id", "predicate_group", "ordinal", "predicate",
    ),
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
    "claim_sources": (
        "claim_kind", "category_key", "claim_id", "ordinal",
    ),
}
```

Every projected tuple follows `EXPECTED_TABLE_COLUMNS[table]`, and every table's
tuple sequence is sorted by `EXPECTED_PRIMARY_KEY_COLUMNS[table]` using the
normalized SQLite wire values. Dates become ISO strings, enums become `.value`,
finite numeric bounds become `float`, integer fields remain exact `int`, and
nullable fields become `None`. Every authored list becomes zero-based ordinal
rows in authored order; there is no one-based ordinal anywhere. Categories are
projected in this exact zero-based mapping, never by discovery or locale order:

```python
CATEGORY_RELEASE_ORDER = {
    "0301_computer_mouse": 0,
    "0301_keyboard": 1,
    "0303_laptop": 2,
    "0306_mobile_phone": 3,
    "0401_headphones": 4,
}
```

Column affinity is also closed. `lower_bound` and `upper_bound` are `REAL`;
`release_order`, every `ordinal`, `precedence`, `application_order`, `position`,
`priority`, and every `model_year_from`/`model_year_to` are `INTEGER`; every
other column is `TEXT`. Every column is declared `NOT NULL`, including every
text primary key, except exactly these nullable semantic fields:

```text
identities.model_id
identities.model_name
identities.model_year_from
identities.model_year_to
identities.applicable_from
identities.applicable_to
lifecycle_records.applicable_from
lifecycle_records.applicable_to
lifecycle_records.model_year_from
lifecycle_records.model_year_to
component_associations.evidence_level
```

The compiler enables `PRAGMA foreign_keys = ON` before starting the write
transaction. Every foreign key below is `DEFERRABLE INITIALLY DEFERRED` with
SQLite's default `NO ACTION`; compilation must commit successfully and the
reopened database must return no rows from `PRAGMA foreign_key_check`:

```text
subtypes.category_id -> categories.category_id
variants.category_id -> categories.category_id
variants.(category_id, subtype_id) -> subtypes.(category_id, subtype_id)
identities.category_id -> categories.category_id
identities.(category_id, subtype_id) -> subtypes.(category_id, subtype_id)
identity_aliases.identity_id -> identities.identity_id
identity_tokens.identity_id -> identities.identity_id
identity_variants.identity_id -> identities.identity_id
identity_variants.variant_id -> variants.variant_id
lifecycle_records.category_id -> categories.category_id
lifecycle_required_variants.record_id -> lifecycle_records.record_id
lifecycle_required_variants.variant_id -> variants.variant_id
lifecycle_excluded_variants.record_id -> lifecycle_records.record_id
lifecycle_excluded_variants.variant_id -> variants.variant_id
lifecycle_assumptions.record_id -> lifecycle_records.record_id
industry_averages.record_id -> lifecycle_records.record_id
lifecycle_limitations.record_id -> industry_averages.record_id
components.category_id -> categories.category_id
component_templates.category_id -> categories.category_id
component_associations.(category_id, template_id) -> component_templates.(category_id, template_id)
component_associations.(category_id, component_id) -> components.(category_id, component_id)
component_association_notes.association_id -> component_associations.association_id
hazards.(category_id, component_id) -> components.(category_id, component_id)
hazard_triggers.hazard_id -> hazards.hazard_id
hazard_actions.hazard_id -> hazards.hazard_id
policy_predicates.rule_id -> policy_rules.rule_id
coverage_unknowns.category_id -> categories.category_id
claim_sources.source_id -> sources.source_id
```

The DDL, not merely Task 2's validator, enforces these row-local integrity
rules. Tests inspect the PK ordinals, `NOT NULL` flags, unique indexes, foreign
keys, and execute invalid inserts inside a deferred transaction:

- `metadata.key` is one of exactly `schema_version`, `bundle_version`,
  `identity_catalog_version`, `policy_revision`, `content_sha256`, or
  `coverage_sha256`.
- `categories.release_order` is unique and in `0..4`;
  `(category_id, release_order)` must equal the exact
  `CATEGORY_RELEASE_ORDER` mapping after reopen.
- `subtypes` has `UNIQUE(category_id, subtype_id)`; market state and battery
  architecture use the Task 1 enums; subtype evidence is exactly B.
- `variants` uses the battery enum and evidence exactly B.
- `identities` checks market/battery enums and nullable year/date ordering. A
  family row has `identity_id=family_id`, null model ID/name, and evidence B; a
  model row has non-null `model_id`/`model_name`, `identity_id=model_id`, and
  evidence A.
- Every ordinal is non-negative. Alias, token, identity-variant, lifecycle
  variant, assumption, limitation, association-note, hazard-trigger,
  hazard-action, policy-predicate, and claim-source child tables reject a
  duplicate value under the same owning parent (under the same action kind for
  hazard actions). Alias and token tables additionally reject duplicate
  normalized casefold values.
- `lifecycle_records` checks positive `lower_bound <= upper_bound`, non-negative
  precedence, nullable year/date ordering, the four scope/tier/evidence triples
  `(model, exact_model, A)`, `(family, family, B)`, `(subtype, subtype, B)`, and
  `(category, industry_average, C)`, plus endpoint-kind coupling:
  `service_life -> total_life`, `capacity_threshold -> capacity_threshold`, and
  every other endpoint -> `operating_endurance`. An industry-average base row
  additionally has subject `device`, endpoint `service_life`, kind `total_life`,
  metric `elapsed_time`, unit `years`, strict `lower_bound < upper_bound`, and
  null year/date bounds.
- `component_templates` has `UNIQUE(category_id, template_id)` and
  `UNIQUE(category_id, scope_kind, scope_id, application_order)`, a non-negative
  application order, and the exact three template kinds. A standard template is
  category-scoped with `scope_id=category_id` and order 0; modern and legacy
  overlays are subtype-, family-, or model-scoped.
- `component_associations` has `UNIQUE(template_id, position)`, a non-negative
  position, and the authored association statuses excluding `user_confirmed`.
  `unknown` requires null evidence; every other status requires A, B, or C.
- `hazards` checks the scope/severity enums and accepts exactly these
  scope/evidence pairs: model/A, family/B, subtype/B, or category/C-or-D.
  `hazard_triggers.observation_key` is one of the exact four
  `HazardTriggerKey` values, and `hazard_actions.action_kind` is exactly
  `immediate`, `follow_up`, `handling`, or `disposal`.
- `policy_rules.priority` is unique and non-negative; its outcome is one of the
  exact six `RecommendationValue` strings and its evidence is A, B, C, or D.
  `policy_predicates.predicate_group` is `all` or `any`, its predicate is one of
  the exact strings in **Closed policy predicates and hazard triggers**, and
  `UNIQUE(rule_id, predicate)` rejects duplication across both groups.
- `coverage_unknowns.claim_kind` is exactly `subtype`, `variant`, `identity`,
  `specific_lifecycle`, `industry_average`, `component_association`, or
  `hazard`.
- `claim_sources.claim_kind` is those seven values plus `policy`. Its
  `category_key` is the empty string if and only if the kind is `policy`, and
  is otherwise a non-empty released category ID. Its full primary key is
  `(claim_kind, category_key, claim_id, ordinal)`, and
  `UNIQUE(claim_kind, category_key, claim_id, source_id)` rejects duplicate
  sources for one claim.

The following are deliberately validator/compiler checks rather than fake SQL
foreign keys, triggers, or synthetic supertables: NFC/ID/URL/date/SemVer/text
syntax; exact five-category closure; family ancestry/name consistency;
identity-to-variant category/subtype and battery equality; display/alias
collisions; resolution of polymorphic lifecycle/template/hazard scopes in the
same category; scoped lifecycle variant ancestry and required/excluded
disjointness; existence of exactly one industry extension and its non-empty
limitations; absence of industry variant child rows; contiguous ordinals and
positions; required non-empty child lists; exactly one standard template (the
modern/legacy release overlay floor is added only in Task 6); association
scope/evidence/template restrictions and
source cardinality; the one-to-one authored `unknown` association to Unknown
row; hazard source cardinality; shared-versus-category source locality;
Unknown/reviewed-claim collision; polymorphic `claim_sources` parent existence
and ownership; policy shared-source-only rules; and mutually exclusive policy
predicate families. Each check is run before promotion and receives a named
negative test.

#### One logical digest, with no recursive hash input

`normalized_sql_rows()` is the only production traversal from normalized
documents to SQL semantics. `logical_content_sha256()` validates the exact
26-key mapping and serializes this one payload:

```json
{"format":"ewaste-knowledge-logical-v1","tables":[{"columns":["key","value"],"name":"metadata","rows":[["bundle_version","3.0.0"],["identity_catalog_version","1.0.0"],["policy_revision","2.0.0"],["schema_version","3"]]}]}
```

The example shows the complete metadata table and abbreviates the remaining 25
table objects; the real array contains one object for every table in
`TABLE_ORDER`, every full column list from
`EXPECTED_TABLE_COLUMNS`, and every row as a JSON array in declared primary-key
order. Serialization is exactly:

```python
json.dumps(
    payload,
    ensure_ascii=False,
    allow_nan=False,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
```

There is no trailing LF in the logical payload. The `metadata` table participates
in its ordinary position, but the rows keyed `content_sha256` and
`coverage_sha256` are the only rows omitted. No table, column, empty child
table, semantic null, row boundary, derived value, or ordinal is omitted. The
function does not read SQLite, walk documents again, include a raw database
hash, include coverage bytes, or hash a hash-containing payload.

The compile order is exact:

1. validate safe source/destination paths, then load and validate all documents;
2. call `normalized_sql_rows()` once, with exactly the four semantic metadata
   rows, and calculate `content_sha256` from the logical payload;
3. call `build_coverage(documents, content_sha256)`, validate the report, produce
   its final canonical bytes, and hash those exact bytes as `coverage_sha256`;
4. write the projected SQL rows, then append exactly the two computed metadata
   rows, commit, close SQLite, write the already-final coverage bytes, and fsync
   both files;
5. reopen the database read-only and the coverage file read-only; require the
   exact schema/metadata/category order, `quick_check == [("ok",)]`, no foreign
   key errors, oracle-equal SQL rows, the recomputed logical digest, byte-for-byte
   canonical coverage encoding, the recomputed coverage hash, and exact
   report-to-database bundle/content linkage; and
6. fsync the completed stage directory and only then begin promotion.

Thus content identity precedes coverage construction, coverage identity is over
the final bytes including their LF, both artifacts are closed and independently
reopened, and neither hash recursively contains itself.

#### Final immutable full-coverage report

Task 3, not Task 6, owns the final `scripts/evidence_coverage.py`,
`packaging/evidence-coverage.schema.json`, full-report builder, validator,
canonical serializer, and full-report tests. The coverage schema version is 1.
The in-memory report has exactly this key insertion order and recursively closed
shape:

```text
CoverageReport = {
  schema_version: 1,
  bundle_version: SemVer,
  knowledge_content_sha256: lowercase SHA-256,
  summary: {
    categories: nonnegative int,
    canonical_identities: nonnegative int,
    subtypes: nonnegative int,
    lifecycle_records: nonnegative int,
    industry_averages: nonnegative int,
    component_templates: nonnegative int,
    modern_overlays: nonnegative int,
    legacy_overlays: nonnegative int,
    hazard_records: nonnegative int,
    reviewed_claims: nonnegative int,
    unknown_claims: nonnegative int,
  },
  claims: list[CoverageClaim],
}

CoverageClaim = {
  category_id: released category ID,
  claim_kind: subtype | variant | identity | specific_lifecycle |
              industry_average | component_association | hazard,
  claim_id: Id,
  evidence_level: A | B | C | D | null,
  source_state: reviewed | unknown,
  source_ids: list[Id],
  unknown_reason: Text | null,
}
```

The summary mapping uses exactly the displayed 11-key order. Its meanings are
closed: `categories` counts category records; `canonical_identities` identities;
`subtypes` subtypes; `lifecycle_records` specific lifecycle records only;
`industry_averages` industry-average records only; `component_templates` all
templates; `modern_overlays` and `legacy_overlays` those exact template kinds;
`hazard_records` hazards; and the last two fields count claim rows by
`source_state`. No count includes an Unknown placeholder as a reviewed record,
and an industry average is never double-counted as a specific lifecycle.
`validate_coverage_report()` itself requires `reviewed_claims` and
`unknown_claims` to equal their claim-row state counts; requires the identity,
subtype, specific-lifecycle, industry-average, and hazard summary counts to
equal their respective reviewed claim-row counts. Category and template counts
cannot always be reconstructed from claim rows in a valid under-floor authoring
tree, so their exact derivation is proved by the independent
documents-to-report oracle rather than reinterpreted later.

Emit one reviewed claim for every authored subtype, variant, identity, specific
lifecycle, industry average, non-`unknown` component association, and hazard.
Definitions, templates, policies, and source records are not coverage claims.
An authored component association with status `unknown` emits no reviewed row;
its required matching Unknown emits the sole Unknown row. Every other authored
Unknown emits one Unknown row directly under its three-part key. A reviewed row
has non-null evidence, non-empty source IDs sorted bytewise, and null
`unknown_reason`; an Unknown row has null evidence, `source_state="unknown"`,
exactly `source_ids=[]`, and the authored reason. Claims are sorted exactly by
the Python string tuple `(category_id, claim_kind, claim_id)`; duplicates are an
error rather than last-write-wins behavior.

The schema file uses JSON Schema draft 2020-12, has `additionalProperties: false`
at every object level, fixes all required/property sets to the shapes above,
fixes `schema_version` to 1 and category/kind/state/evidence enums to the values
above, rejects booleans as counts, and expresses the reviewed-versus-Unknown
field coupling with `oneOf`. Semantic count equality, source sorting, claim
sorting, duplicate claim keys, and authored source ownership remain explicit
Python validation because JSON Schema cannot prove them.

`coverage_json_bytes()` first calls `validate_coverage_report()` and returns
exactly:

```python
json.dumps(
    report,
    ensure_ascii=False,
    allow_nan=False,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8") + b"\n"
```

This is the immutable full-report byte contract. Task 6 may add release-floor
validation and comparison, but may not add, remove, rename, reorder, or reinterpret
a full-report field or change `build_coverage()`/`coverage_json_bytes()` output
for the same normalized documents and content hash.

#### Exhaustive independent oracles

`tests/test_knowledge_compiler.py` repeats `TABLE_ORDER`,
`EXPECTED_TABLE_COLUMNS`, and `EXPECTED_PRIMARY_KEY_COLUMNS` as test-owned
literals; it does not import a production table/column/PK constant. Its
`expected_normalized_sql_rows(documents)` independently visits every normalized
record and list, without calling `normalized_sql_rows()`, any production row
helper, or `logical_content_sha256()`. `read_normalized_sql_rows(database)`
selects the test-owned columns ordered by the test-owned PKs and omits only the
two computed metadata rows. The core equality is always:

```python
assert expected_normalized_sql_rows(documents) == normalized_sql_rows(documents)
assert read_normalized_sql_rows(database) == expected_normalized_sql_rows(documents)
```

`tests/test_evidence_coverage.py` similarly implements
`expected_coverage_report(documents, content_sha256)` without calling the
production coverage builder, projection, claim iterator, summary helper, or
serializer. It asserts whole-object equality, exact insertion orders, and exact
canonical bytes.

Define `AUTHORING_FIELD_TARGETS` with a key for every root/record field in Task
2's `ROOT_VALUE_TYPES` and `FIELD_TYPES`, including nested `Scope` fields. Each
entry names all affected SQL `(table, column)` targets and full-coverage field
targets. Define a separate exhaustive `DERIVED_TARGETS` for metadata keys,
zero-based category release order, flattened/current-category scope columns,
derived lifecycle tier, alias/token casefolds, every child ordinal, hazard
action kind, policy predicate group, every `claim_sources` ownership/key/ordinal
column, coverage schema/state/null fields, and every summary counter. The two
validation-only authored constants `Unknown.evidence_level=null` and
`Unknown.source_ids=[]` are explicitly mapped as reconstructible from a
`coverage_unknowns` row and still receive Task 2 negative mutations.

Assertions compare exact sets, not table-name classes:

- mapping keys equal every normative authored field;
- SQL targets equal every non-computed SQL column and each computed key's
  documented derivation;
- coverage targets equal all five top-level fields, all 11 summary fields, and
  all seven claim-row fields;
- referentially valid `semantic_authoring_mutations()` change every mutable
  authored value at every concrete value path (relative file, record path,
  field, and optional list index) and exactly its declared SQL/coverage targets;
  its enumerated value-path set must equal an independent walk of the valid source
  fixture. Frozen release constants are instead asserted at their exact
  projected targets and retain their Task 2 rejection tests;
- list insert/reorder cases prove the child value and its zero-based ordinal are
  retained, including all four hazard action lists and both policy predicate
  groups;
- `semantic_sql_cell_mutations()` changes every semantic SQL column, including
  each derived/ordinal column, and every case changes the logical digest; only
  the two computed metadata values are excluded from this mutation loop; and
- validity-preserving `semantic_coverage_field_mutations()` covers every mutable
  scalar, list item, null, claim key, source ID, and counter, coordinating claim
  rows and counters where required; every case changes canonical coverage bytes.
  Closed constants that cannot form a second valid report are pinned in the
  independent whole-object and exact-byte oracle instead of being exempted.

- [ ] **Step 1: Write failing schema, projection, digest, coverage, CLI, and atomicity tests**

Write the independent oracles and exhaustive target/mutation matrices above,
then add at least these whole-contract tests:

```python
def test_compile_emits_the_fixed_bundle_files(tmp_path):
    source = make_valid_knowledge_source(tmp_path / "source")
    output = tmp_path / "bundle"
    manifest = compile_knowledge_bundle(source, output)
    assert sorted(path.name for path in output.iterdir()) == [
        "evidence-coverage.json", "knowledge.sqlite"
    ]
    assert manifest.schema_version == 3
    assert manifest.bundle_version == "3.0.0"
    assert manifest.identity_catalog_version == "1.0.0"
    assert manifest.policy_revision == "2.0.0"


def test_schema_columns_types_nullability_primary_keys_and_foreign_keys_are_exact(
    tmp_path,
):
    source = make_valid_knowledge_source(tmp_path / "source")
    compile_knowledge_bundle(source, tmp_path / "bundle")
    database = tmp_path / "bundle/knowledge.sqlite"
    assert application_tables(database) == TABLE_ORDER
    assert table_info_contract(database) == EXPECTED_TABLE_INFO
    assert primary_key_contract(database) == EXPECTED_PRIMARY_KEY_COLUMNS
    assert foreign_key_contract(database) == EXPECTED_DEFERRED_FOREIGN_KEYS
    assert every_declared_constraint_rejects_its_invalid_insert(database)


def test_every_parent_child_value_and_zero_based_ordinal_round_trips_exactly(tmp_path):
    source = make_valid_knowledge_source(tmp_path / "source")
    documents = load_evidence_documents(source)
    expected = expected_normalized_sql_rows(documents)
    manifest = compile_knowledge_bundle(source, tmp_path / "bundle")
    actual = read_normalized_sql_rows(tmp_path / "bundle/knowledge.sqlite")
    assert set(actual) == set(EXPECTED_TABLE_COLUMNS)
    assert actual == expected == normalized_sql_rows(documents)
    assert manifest.content_sha256 == logical_content_sha256(expected)
    assert read_metadata(tmp_path / "bundle/knowledge.sqlite") == {
        "schema_version": "3", "bundle_version": "3.0.0",
        "identity_catalog_version": "1.0.0", "policy_revision": "2.0.0",
        "content_sha256": manifest.content_sha256,
        "coverage_sha256": manifest.coverage_sha256,
    }


def test_logical_payload_is_exact_nonrecursive_canonical_json(valid_documents):
    rows = expected_normalized_sql_rows(valid_documents)
    payload = expected_logical_payload(rows)
    expected_bytes = json.dumps(
        payload, ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert payload["format"] == "ewaste-knowledge-logical-v1"
    assert [item["name"] for item in payload["tables"]] == list(TABLE_ORDER)
    assert not expected_bytes.endswith(b"\n")
    assert logical_content_sha256(rows) == hashlib.sha256(expected_bytes).hexdigest()


def test_semantic_targets_are_exact_per_authored_derived_sql_and_coverage_field(
    tmp_path,
):
    source = make_valid_knowledge_source(tmp_path / "source")
    assert set(AUTHORING_FIELD_TARGETS) == all_normative_authoring_fields()
    assert set(DERIVED_TARGETS) == all_documented_derived_targets()
    authoring_mutations = semantic_authoring_mutations(source)
    assert mutation_targets(authoring_mutations) == mutable_authoring_field_targets()
    assert mutation_value_paths(authoring_mutations) == (
        all_mutable_authoring_value_paths(source)
    )
    assert mapped_sql_columns() == all_noncomputed_sql_columns()
    assert mapped_coverage_fields() == all_coverage_semantic_fields()


def test_every_mutable_authored_value_changes_its_exact_targets_and_hashes(tmp_path):
    source = make_valid_knowledge_source(tmp_path / "source")
    baseline_documents = load_evidence_documents(source)
    baseline_rows = normalized_sql_rows(baseline_documents)
    baseline_hash = logical_content_sha256(baseline_rows)
    baseline_report = build_coverage(baseline_documents, baseline_hash)
    for mutation_name, targets, mutation in semantic_authoring_mutations(source):
        changed_source = clone_and_mutate(source, tmp_path / mutation_name, mutation)
        changed_documents = load_evidence_documents(changed_source)
        changed_rows = normalized_sql_rows(changed_documents)
        changed_hash = logical_content_sha256(changed_rows)
        changed_report = build_coverage(changed_documents, changed_hash)
        assert changed_sql_targets(baseline_rows, changed_rows) == targets.sql
        assert changed_coverage_targets(baseline_report, changed_report) == (
            targets.coverage
        )
        assert changed_hash != baseline_hash
        if targets.coverage:
            assert coverage_json_bytes(changed_report) != coverage_json_bytes(
                baseline_report
            )


def test_every_semantic_sql_cell_including_derived_ordinals_is_hash_bound(tmp_path):
    source = make_valid_knowledge_source(tmp_path / "source")
    rows = normalized_sql_rows(load_evidence_documents(source))
    baseline_hash = logical_content_sha256(rows)
    for table, column, changed_rows in semantic_sql_cell_mutations(rows):
        assert changed_rows != rows
        assert logical_content_sha256(changed_rows) != baseline_hash


def test_full_coverage_matches_independent_oracle_and_exact_bytes(valid_documents):
    report = build_coverage(valid_documents, "a" * 64)
    expected = expected_coverage_report(valid_documents, "a" * 64)
    assert report == expected
    assert list(report) == [
        "schema_version", "bundle_version", "knowledge_content_sha256",
        "summary", "claims",
    ]
    assert list(report["summary"]) == SUMMARY_FIELDS
    assert coverage_json_bytes(report) == json.dumps(
        expected, ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"


def test_every_full_coverage_field_and_counter_changes_canonical_bytes(valid_report):
    baseline = coverage_json_bytes(valid_report)
    mutations = semantic_coverage_field_mutations(valid_report)
    assert coverage_mutation_targets(mutations) == MUTABLE_COVERAGE_FIELDS
    assert FROZEN_COVERAGE_FIELDS <= ALL_COVERAGE_FIELDS
    for _target, changed_report in mutations:
        assert coverage_json_bytes(changed_report) != baseline


def test_failed_rebuild_preserves_the_previous_complete_directory(tmp_path):
    source = make_valid_knowledge_source(tmp_path / "source")
    output = tmp_path / "bundle"
    original = compile_knowledge_bundle(source, output)
    break_source_reference(source)
    with pytest.raises(EvidenceValidationError):
        compile_knowledge_bundle(source, output)
    assert read_bundle_manifest(output) == original


def test_two_rebuilds_have_the_same_logical_identity_and_coverage_bytes(tmp_path):
    source = make_valid_knowledge_source(tmp_path / "source")
    first = compile_knowledge_bundle(source, tmp_path / "first")
    second = compile_knowledge_bundle(source, tmp_path / "second")
    assert first == second
    assert (tmp_path / "first/evidence-coverage.json").read_bytes() == (
        tmp_path / "second/evidence-coverage.json"
    ).read_bytes()


@pytest.mark.parametrize(
    "destination_kind",
    ("same_as_source", "inside_source", "ancestor_of_source"),
)
def test_source_and_destination_may_not_overlap(tmp_path, destination_kind):
    source, destination = overlapping_paths(tmp_path, destination_kind)
    before = snapshot_tree(source)
    with pytest.raises(KnowledgeCompilationError, match="must not overlap"):
        compile_knowledge_bundle(source, destination)
    assert snapshot_tree(source) == before


def test_failed_promotion_restores_old_bundle_and_cleans_only_its_own_stage(
    tmp_path, monkeypatch,
):
    source = make_valid_knowledge_source(tmp_path / "source")
    output = tmp_path / "bundle"
    compile_knowledge_bundle(source, output)
    old_bytes = snapshot_tree(output)
    unrelated = output.parent / f".{output.name}-unrelated.stage"
    unrelated.mkdir()
    fail_stage_to_destination_once(monkeypatch, output)
    with pytest.raises(OSError, match="promotion failed"):
        compile_knowledge_bundle(source, output)
    assert snapshot_tree(output) == old_bytes
    assert unrelated.is_dir()
    assert current_invocation_siblings(output) == []
```

- [ ] **Step 2: Run compiler tests and verify RED**

Run: `.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_knowledge_compiler.py tests/test_evidence_coverage.py -v`

Expected: FAIL during collection because the compiler and Task 3 full-coverage
modules do not exist.

- [ ] **Step 3: Implement the exact projection, DDL, and one logical digest**

Implement the frozen schema, row-local DDL constraints, deferred relationships,
pure row projection, and exact nonrecursive payload above. Insert only the
projection returned by `normalized_sql_rows()`; do not duplicate its traversal
inside either the database writer or digest function. The only post-projection
SQL rows are the two computed metadata rows after both hashes exist.

- [ ] **Step 4: Implement and freeze the full coverage report**

Implement the closed schema, independent semantic validator, builder, and exact
canonical bytes above. Keep source metadata hash-bound through SQL and claim
source IDs visible in coverage; do not enlarge a coverage claim with source
metadata, policy, template, or component-definition fields. Task 3 tests own all
full-report behavior so Task 6 can add gates without redefining the artifact.

- [ ] **Step 5: Make compiler path handling and promotion exact**

This is the safety contract for `compile_knowledge_bundle()` and
`build_knowledge_bundle.py`; do not copy the later model-oriented
`prepare_release.py` CLI or its repository-specific `.release-staging` policy.

Convert source and destination to normalized absolute lexical paths without
using `resolve()` to bless a symlink. Before opening a source document or
writing anything, walk every existing path component with `lstat`. The source
must be an existing non-symlink directory; every authoring subdirectory visited
by the closed loader must be a non-symlink directory; and every authoring file
opened by it must be a non-symlink regular file. Every existing destination
ancestor and an existing destination must be non-symlink directories. Reject a
regular file, directory, socket, FIFO, device, or symlink whenever the contract
requires a different kind. Resolve only the now-verified locations and reject
equality or containment in either direction. Load, validate, project, hash,
build coverage, and (after Task 6) enforce the floor before creating missing
destination parents. Immediately before stage creation, create each missing
parent component one at a time, re-run the `lstat`/non-overlap checks, and then
proceed. Invalid source content therefore creates neither an output parent nor a
stage.

The hostile-path test matrix is exhaustive over: a symlinked source root;
symlink/non-directory source ancestors; symlink, directory, or special-file
authoring files; symlink/non-directory destination ancestors; an existing
destination that is a symlink or any non-directory; source/destination equality
and containment in both directions; a colliding stage/backup candidate of every
file kind; either staged artifact replaced by a symlink or non-regular file; and
every forbidden SQLite sidecar or extra stage entry. Where the host cannot make
a device, the test supplies its `lstat` mode through the path-inspection seam.
Every case asserts that no source byte changes, no invalid output parent is
created, an old destination is unchanged, and unrelated sibling lookalikes are
untouched.

Create one private directory on the destination filesystem with basename
matching `.<destination-name>-<32 lowercase hex>.stage`: generate
`uuid4().hex`, call `Path.mkdir(mode=0o700, exist_ok=False)`, and retry only a
name collision. If an old destination exists, choose an absent
`.<destination-name>-<32 lowercase hex>.backup` beside it using a separate
fresh `uuid4().hex`; `os.replace(destination, backup)` creates that path during
promotion. Both are never descendants of the source or destination. A compiler
invocation records its exact stage/backup paths and never glob-deletes a
lookalike or stale sibling from another run.

Write only `knowledge.sqlite` and `evidence-coverage.json` below the stage. Set
SQLite journal mode to `DELETE`, close the connection before file fsync, and
reject any journal, sidecar, or extra entry. Immediately before fsync and again
before reopen, use `lstat` to require both named artifacts to be non-symlink
regular files. File and directory fsync failures are fatal rather than silently
ignored. After the reopen verification in the compile-order contract, fsync the
stage directory.
Promotion is then:

1. if present, `os.replace(destination, backup)` and fsync the parent;
2. `os.replace(stage, destination)` and fsync the parent;
3. remove this invocation's backup only after the new destination is durable,
   then fsync the parent again.

Any failure before the destination-to-backup rename leaves the old destination
untouched and removes only this invocation's stage. Before recursively removing
a recorded stage or backup, `lstat` must confirm that it is either absent or a
real directory with this invocation's exact parent and generated basename; an
absent path is already clean, while a symlink, non-directory, or mismatched path
is preserved and reported. If cleanup fails, raise `KnowledgeCompilationError`
with the original and cleanup failures plus every preserved recovery path. No
cleanup follows a symlink. Any failure after the destination-to-backup rename
but before the new destination and its parent fsync both succeed enters rollback;
the recorded backup keeps the old destination recoverable. If the stage has
already become the destination, first move it back to the recorded stage path;
then restore with `os.replace(backup, destination)`
and fsync the parent. A destination that did not previously exist is rolled back
to absence by moving the promoted directory back to the stage path and fsyncing
the parent. After successful rollback, remove the stage and re-raise the
original failure. If moving the new destination aside, restoring the backup, or
the rollback fsync fails, raise `KnowledgeCompilationError` containing the
original and rollback failures plus the exact preserved backup/stage paths and
do not delete either recovery artifact. If backup deletion fails after a
successful durable promotion, keep the valid new destination, preserve whatever
remains at the exact backup path, and raise a cleanup error naming it. On
failure of the parent fsync after backup deletion, keep the valid new
destination, report that durability fsync failure, and do not claim the removed
backup is recoverable. On success no stage or backup from that invocation
remains. Tests inject failures at every write, fsync, reopen, rename, rollback,
and cleanup boundary and assert the exact old/new/absent bundle state plus
unrelated sibling preservation.

- [ ] **Step 6: Freeze the compiler CLI contract**

`scripts/build_knowledge_bundle.py` inserts the repository root in `sys.path`,
defines `main(argv: Sequence[str] | None = None) -> int`, and exposes only
`-h/--help`, required `--source PATH`, required `--out DIRECTORY`, and optional
`--print-summary`. Set the parser's `prog` and literal usage so help is exactly:

```text
usage: build_knowledge_bundle.py --source PATH --out DIRECTORY [--print-summary]

Compile reviewed schema-3 knowledge YAML into one atomic bundle directory.

options:
  -h, --help       show this help message and exit
  --source PATH    reviewed schema-3 source directory
  --out DIRECTORY  destination bundle directory
  --print-summary  print the deterministic bundle summary
```

Help exits 0, writes that text plus its final LF to stdout, writes nothing to
stderr, and performs no filesystem mutation. Argument errors use argparse exit
2, empty stdout, and its deterministic `usage: ...` plus
`build_knowledge_bundle.py: error: ...` on stderr. Expected validation,
path-safety, SQLite, coverage, and promotion failures exit 1, write no stdout,
write exactly `error: <public error message>\n` to stderr, and never emit a
traceback. A successful call without `--print-summary` exits 0 with empty stdout
and stderr.

With `--print-summary`, stdout is produced only after successful promotion. It
has one final LF, contains no absolute path or timestamp, and uses exactly this
line order:

```text
knowledge bundle summary
schema_version=<value>
bundle_version=<value>
identity_catalog_version=<value>
policy_revision=<value>
summary.categories=<value>
summary.canonical_identities=<value>
summary.subtypes=<value>
summary.lifecycle_records=<value>
summary.industry_averages=<value>
summary.component_templates=<value>
summary.modern_overlays=<value>
summary.legacy_overlays=<value>
summary.hazard_records=<value>
summary.reviewed_claims=<value>
summary.unknown_claims=<value>
claims <category_id> <claim_kind> reviewed=<value> unknown=<value>
content_sha256=<64 lowercase hex>
coverage_sha256=<64 lowercase hex>
```

The `claims ...` line repeats for every Cartesian pair: categories in
`RELEASED_CATEGORY_IDS` order, then claim kinds in exact order `subtype`,
`variant`, `identity`, `specific_lifecycle`, `industry_average`,
`component_association`, `hazard`. Zero counts are printed. The two hash lines
come last. `summary.*` values are the exact report values; claim counts are
computed only from the final report. Two builds at different output paths must
have byte-identical stdout.

- [ ] **Step 7: Run focused tests and deterministic compilation twice**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_evidence_types.py tests/test_knowledge_schema.py tests/test_knowledge_compiler.py tests/test_evidence_coverage.py -v
```

Expected: tests PASS; exact DDL/PK/FK/nullability and every invalid insert are
covered; oracle/projection/database rows match; every authored, derived, child,
ordinal, SQL, and coverage target is retained; every semantic mutation changes
the correct canonical hash; all hostile paths and injected failures preserve
the previous bundle; and two output locations produce identical summaries,
logical hashes, and coverage bytes. Raw SQLite hashes are not the
platform-independent logical identity.

- [ ] **Step 8: Commit the compiler, full coverage artifact, and CLI**

```bash
git add scripts/knowledge_compiler.py scripts/build_knowledge_bundle.py scripts/evidence_coverage.py packaging/evidence-coverage.schema.json tests/test_knowledge_compiler.py tests/test_evidence_coverage.py
git commit -m "feat: compile atomic knowledge bundles"
```

### Task 4: Open and query the bundle without administrator dependencies

**Files:**
- Create: `server/knowledge_store.py`
- Create: `tests/test_knowledge_store.py`

**Interfaces:**
- Produces the constructor and methods below:

```python
KnowledgeStore(
    database_path: Path,
    coverage_path: Path | None = None,
    *,
    expected_sha256: str | None = None,
    expected_content_sha256: str | None = None,
    expected_coverage_sha256: str | None = None,
    expected_schema_version: int | None = None,
    expected_bundle_version: str | None = None,
    expected_identity_catalog_version: str | None = None,
    expected_policy_revision: str | None = None,
)
```

- Produces property: `KnowledgeStore.manifest -> KnowledgeManifest`
- Produces: `list_categories() -> tuple[CategorySnapshot, ...]`
- Produces: `get_category(category_id: str) -> CategorySnapshot | None`
- Produces: `search_identities(text: str, *, category_id: str | None = None, limit: int = 20) -> tuple[IdentityRecordSnapshot, ...]`
- Produces: `get_identity(identity_id: str) -> IdentityRecordSnapshot | None`
- Produces: `identity_scope(identity_id: str) -> CanonicalIdentityScope`
- Produces: `lifecycle_candidates(scope: CanonicalIdentityScope) -> tuple[LifecycleRecordSnapshot, ...]`
- Produces: `component_layers(scope: CanonicalIdentityScope) -> tuple[tuple[ComponentAssociationSnapshot, ...], ...]`
- Produces: `hazard_candidates(scope: CanonicalIdentityScope) -> tuple[HazardSnapshot, ...]`
- Produces: `policy_bundle() -> PolicyBundleSnapshot`
- Produces: `source_snapshots(source_ids: Iterable[str]) -> tuple[SourceSnapshot, ...]`

- [ ] **Step 1: Write failing startup, immutable-query, and tamper tests**

```python
def test_store_validates_both_bundle_files_and_returns_frozen_records(compiled_bundle):
    database, coverage, manifest = compiled_bundle
    with KnowledgeStore(
        database,
        coverage,
        expected_content_sha256=manifest.content_sha256,
        expected_coverage_sha256=manifest.coverage_sha256,
        expected_schema_version=3,
        expected_bundle_version="3.0.0",
        expected_identity_catalog_version="1.0.0",
        expected_policy_revision="2.0.0",
    ) as store:
        records = store.search_identities("model 00", category_id="0303_laptop")
        assert records[0].category_id == "0303_laptop"
        assert store.manifest.stamp == manifest.stamp


def test_store_rejects_a_coverage_file_from_another_valid_bundle(two_bundles):
    first, second = two_bundles
    with pytest.raises(KnowledgeStartupError, match="knowledge bundle is unavailable or incompatible"):
        KnowledgeStore(first.database, second.coverage)


def test_store_is_query_only(compiled_bundle):
    database, coverage, _manifest = compiled_bundle
    with KnowledgeStore(database, coverage) as store:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            store._connection.execute("DELETE FROM sources")


def test_identity_scope_copies_variants_and_only_uses_singleton_ranges(
    store_with_identity_ranges,
):
    exact = store_with_identity_ranges.identity_scope("exact_identity")
    assert exact == CanonicalIdentityScope(
        category_id="0303_laptop",
        subtype_id="test_laptop_subtype",
        family_id="test_laptop_family",
        model_id="exact_identity",
        variant_ids=("variant_a", "variant_b"),
        model_year=2024,
        applicable_on=date(2024, 6, 1),
    )

    ranged = store_with_identity_ranges.identity_scope("ranged_identity")
    assert ranged == CanonicalIdentityScope(
        category_id="0303_laptop",
        subtype_id="test_laptop_subtype",
        family_id="test_laptop_family",
        model_id="ranged_identity",
        variant_ids=("variant_a",),
        model_year=None,
        applicable_on=None,
    )


def test_identity_scope_does_not_choose_an_open_range_endpoint(
    store_with_identity_ranges,
):
    scope = store_with_identity_ranges.identity_scope("open_range_identity")
    assert scope == CanonicalIdentityScope(
        category_id="0303_laptop",
        subtype_id="test_laptop_subtype",
        family_id="test_laptop_family",
        model_id="open_range_identity",
        variant_ids=(),
        model_year=None,
        applicable_on=None,
    )
```

The range fixture authors all three asserted model identities under exactly
`0303_laptop / test_laptop_subtype / test_laptop_family`:
`exact_identity` has equal non-null year/date bounds, `ranged_identity` has
unequal non-null bounds, and `open_range_identity` has one null endpoint in
each pair. Their authored `variant_ids` are exactly the asserted tuples. These
whole-value comparisons prevent an implementation from deriving year/date
correctly while dropping or inventing another scope field.

- [ ] **Step 2: Run store tests and verify RED**

Run: `.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_knowledge_store.py -v`

Expected: FAIL during collection because `server.knowledge_store` does not exist.

- [ ] **Step 3: Implement fail-closed startup and immutable queries**

Use only `dataclasses`, `datetime`, `hashlib`, `json`, `pathlib`, `sqlite3`, `threading`, and other Python standard-library modules. Resolve paths safely, hash the database before and after opening, use SQLite URI `mode=ro`, set `query_only`, validate exact metadata/table/column sets, run quick/foreign-key checks, recompute the logical digest, validate expected release values, and verify the coverage file hash plus its bundle-version/content-hash linkage. Convert all rows into frozen types and expand claim sources independently.

Identity search normalizes Unicode, whitespace, and case only; it searches display names, aliases, and distinguishing tokens with deterministic exact-prefix-token ordering. It never performs network lookup and never turns a search result into a user decision.

`identity_scope` reads the selected immutable `IdentityRecordSnapshot` and
copies category/subtype/family/model IDs and `variant_ids`. It emits a singular
`model_year` or `applicable_on` only for equal, non-null corresponding bounds;
unequal or open bounds emit `None`. This is the only derivation compatible with
Slice 2's closed confirmed/edited decision shapes, which supply `identity_id`
but reject client-authored year/date/scope fields. The store never consults the
clock and never selects a lower bound, upper bound, or midpoint.

- [ ] **Step 4: Prove the packaged import graph has no YAML/compiler dependency**

```python
def test_runtime_store_does_not_import_admin_or_yaml_modules(monkeypatch):
    forbidden = {"yaml", "scripts.knowledge_schema", "scripts.knowledge_compiler"}
    real_import = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name in forbidden:
            raise AssertionError(name)
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded)
    sys.modules.pop("server.knowledge_store", None)
    importlib.import_module("server.knowledge_store")
```

Run: `.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_knowledge_store.py -v`

Expected: PASS for empty/corrupt/wrong-schema/tampered/swapped inputs, deterministic searches, frozen values, concurrent reads, and clean close.

- [ ] **Step 5: Commit the standard-library schema-3 store**

Do not remove PyYAML from `requirements-app.txt` in this slice: the unchanged frozen-v1 `ReferenceStore` still imports it. Slice 5 removes that dependency in the same atomic change that removes the legacy package path.

```bash
git add server/knowledge_store.py tests/test_knowledge_store.py
git commit -m "feat: add read-only knowledge store"
```

### Task 5: Resolve lifecycle, components, hazards, and policy without calculating an assessment

**Files:**
- Create: `server/evidence_resolver.py`
- Create: `tests/test_evidence_resolver.py`

**Interfaces:**
- Produces: `EvidenceResolver(store: KnowledgeStore)`
- Produces: `resolve_lifecycle(scope: CanonicalIdentityScope, request: LifecycleRequest) -> LifecycleResolution`
- Produces: `resolve_components(scope: CanonicalIdentityScope) -> ComponentResolution`
- Produces: `resolve_hazards(scope: CanonicalIdentityScope) -> HazardResolution`
- Produces: `resolve(scope: CanonicalIdentityScope, request: LifecycleRequest) -> ResolvedEvidence`
- Does not import or call `server.lifecycle`, `AssessmentEngine`, condition code, history, Flask, or UI serialization

- [ ] **Step 1: Write failing precedence and compatibility tests**

```python
def test_compatible_family_beats_subtype_and_average(resolver, phone_scope):
    result = resolver.resolve_lifecycle(
        phone_scope,
        LifecycleRequest("device", "service_life", "elapsed_time", "years"),
    )
    assert result.tier is ResolutionTier.FAMILY
    assert result.record.record_id == "phone_family_service_life"
    assert tuple(step.tier for step in result.trace) == (
        ResolutionTier.EXACT_MODEL,
        ResolutionTier.FAMILY,
    )


def test_incompatible_exact_record_is_filtered_before_specificity(resolver, phone_scope):
    result = resolver.resolve_lifecycle(
        phone_scope,
        LifecycleRequest("battery", "capacity_threshold", "full_charge_cycles", "cycles"),
    )
    assert result.record.record_id == "phone_subtype_capacity_threshold"
    exact = result.trace[0]
    assert ("phone_exact_service_life", "endpoint mismatch") in exact.rejected


def test_equal_precedence_conflict_returns_unknown(resolver_with_conflict, phone_scope):
    result = resolver_with_conflict.resolve_lifecycle(
        phone_scope,
        LifecycleRequest("device", "service_life", "elapsed_time", "years"),
    )
    assert result.record is None
    assert result.unknown_reason == "Conflicting reviewed records at the same evidence tier."


@pytest.mark.parametrize(
    ("model_year", "applicable_on"),
    [(2020, date(2020, 1, 1)), (2025, date(2025, 12, 31))],
)
def test_year_and_date_bounds_are_inclusive(
    resolver_with_applicability, applicability_scope, model_year, applicable_on,
):
    scope = replace(
        applicability_scope, model_year=model_year, applicable_on=applicable_on,
    )
    result = resolver_with_applicability.resolve_lifecycle(scope, SERVICE_LIFE)
    assert result.record.record_id == "bounded_specific"


@pytest.mark.parametrize(
    ("missing_field", "reason"),
    [
        ("model_year", "model year unavailable"),
        ("applicable_on", "applicability date unavailable"),
    ],
)
def test_missing_singular_applicability_rejects_only_constrained_record(
    resolver_with_applicability, applicability_scope, missing_field, reason,
):
    scope = replace(applicability_scope, **{missing_field: None})
    result = resolver_with_applicability.resolve_lifecycle(scope, SERVICE_LIFE)
    assert result.record.record_id == "unconstrained_specific"
    assert ("bounded_specific", reason) in result.trace[0].rejected


@pytest.mark.parametrize(
    ("scope_change", "reason"),
    [
        ({"model_year": 2019}, "model year out of range"),
        ({"applicable_on": date(2026, 1, 1)}, "applicability date out of range"),
    ],
)
def test_out_of_range_values_have_closed_trace_reasons(
    resolver_with_applicability, applicability_scope, scope_change, reason,
):
    result = resolver_with_applicability.resolve_lifecycle(
        replace(applicability_scope, **scope_change), SERVICE_LIFE,
    )
    assert result.record.record_id == "unconstrained_specific"
    assert ("bounded_specific", reason) in result.trace[0].rejected


def test_required_and_excluded_variants_are_deterministic(
    resolver_with_variant_filters, variant_scope,
):
    eligible = replace(variant_scope, variant_ids=("variant_a", "variant_b"))
    assert resolver_with_variant_filters.resolve_lifecycle(
        eligible, SERVICE_LIFE,
    ).record.record_id == "variant_specific"
    for variants, reason in [
        (("variant_b",), "required variant missing"),
        (("variant_a", "variant_x"), "excluded variant present"),
    ]:
        result = resolver_with_variant_filters.resolve_lifecycle(
            replace(variant_scope, variant_ids=variants), SERVICE_LIFE,
        )
        assert result.record.record_id == "unconstrained_specific"
        assert ("variant_specific", reason) in result.trace[0].rejected
```

`resolver_with_applicability` has same-tier records `bounded_specific`
(`model_year_from=2020`, `model_year_to=2025`,
`applicable_from=2020-01-01`, `applicable_to=2025-12-31`),
and the higher-numbered-precedence fallback `unconstrained_specific` with null
year/date bounds and empty variant filters. `resolver_with_variant_filters`
instead has `variant_specific` (requiring `variant_a` and excluding
`variant_x`) plus that unconstrained fallback. Both fixtures prevent a
more-specific tier from masking these checks.

- [ ] **Step 2: Write failing category-only, overlay, hazard, and source tests**

```python
def test_category_only_scope_uses_only_average_and_base_components(resolver):
    scope = CanonicalIdentityScope("0301_keyboard")
    assert scope == CanonicalIdentityScope(
        category_id="0301_keyboard", subtype_id=None, family_id=None,
        model_id=None, variant_ids=(), model_year=None, applicable_on=None,
    )
    resolved = resolver.resolve(
        scope,
        LifecycleRequest("device", "service_life", "elapsed_time", "years"),
    )
    assert resolved.lifecycle.tier is ResolutionTier.INDUSTRY_AVERAGE
    assert resolved.components.applied_template_ids == ("keyboard_standard",)


def test_layers_apply_category_subtype_family_model_order(resolver, laptop_scope):
    result = resolver.resolve_components(laptop_scope)
    assert result.applied_template_ids == (
        "laptop_standard", "laptop_modern_ultrabook", "framework_laptop_13_family",
        "framework_laptop_13_amd_7040_model",
    )
    storage = next(item for item in result.components if item.component_id == "storage")
    assert storage.status is AssociationStatus.EXACT_MODEL_CONFIRMED


def test_component_replacements_retain_slots_and_new_components_append(
    resolver_with_component_slot_layers, component_slot_scope,
):
    first = resolver_with_component_slot_layers.resolve_components(component_slot_scope)
    second = resolver_with_component_slot_layers.resolve_components(component_slot_scope)
    assert first == second
    assert first.applied_template_ids == (
        "base", "subtype_overlay", "family_overlay", "model_overlay",
    )
    assert tuple(item.component_id for item in first.components) == (
        "chassis", "battery", "storage", "radio", "camera",
    )
    assert tuple(item.association_id for item in first.components) == (
        "model_chassis_not_present", "model_battery_unknown", "base_storage",
        "subtype_radio", "model_camera",
    )
    assert first.components[0].status is AssociationStatus.NOT_PRESENT
    assert first.components[1].status is AssociationStatus.UNKNOWN


def test_hazard_sources_are_not_copied_from_lifecycle(resolver, phone_scope):
    resolved = resolver.resolve_hazards(phone_scope)
    battery = next(item for item in resolved.hazards if item.hazard_id == "phone_damaged_li_ion")
    assert {source.source_id for source in battery.sources} == {"epa_used_li_ion_2026"}
    assert "eu_phone_ecodesign_2023_1670" not in {source.source_id for source in battery.sources}
```

The slot-layer fixture authors base positions `chassis`, `battery`, `storage`;
a subtype layer that replaces `battery` then introduces `radio`; a family layer
that again replaces only `battery`; and a model layer that replaces `chassis`
with `not_present`, replaces `battery` with `unknown`, and first introduces
`camera`. Thus the asserted tuple separately pins layer order, per-template
position, repeated in-place replacement, new append, omission retention, both
explicit absence states, and repeat-call determinism.

- [ ] **Step 3: Run resolver tests and verify RED**

Run: `.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_evidence_resolver.py -v`

Expected: FAIL because `EvidenceResolver` does not exist.

- [ ] **Step 4: Implement deterministic resolution**

Filter candidates by canonical hierarchy, subject, endpoint, metric, unit,
inclusive applicability date/model-year bounds, and required/excluded variants
before grouping them into `EXACT_MODEL`, `FAMILY`, `SUBTYPE`, and
`INDUSTRY_AVERAGE`. A missing singular year/date rejects a constrained record
with the exact unavailable trace reason in the normative contract but does not
reject an unconstrained record. Never read the wall clock. At the first tier
with applicable candidates, select the unique lowest integer precedence. A tie
returns Unknown with all conflicting IDs in the trace. Never continue to a
lower tier after finding a same-tier conflict, and never merge numeric ranges.

Apply eligible component templates in category/subtype/family/model layer order
and `(application_order, template_id)` order within a layer, then visit each
template's associations by `position`. Use the normative stable-slot algorithm:
first occurrence appends, replacement updates in place, omission retains, and
explicit `not_present`/`unknown` replaces in place. Return the resulting tuple,
not a component-ID sort. Resolve applicable hazards without interpreting
trigger observations. Attach `store.policy_bundle()` and
`store.manifest.stamp` in `ResolvedEvidence`.

- [ ] **Step 5: Run resolver/store/type tests and commit**

Run: `.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_evidence_types.py tests/test_knowledge_store.py tests/test_evidence_resolver.py -v`

Expected: PASS for all precedence, filtering, conflict, category-only, overlay, source, hazard, policy, and Unknown cases.

```bash
git add server/evidence_resolver.py tests/test_evidence_resolver.py
git commit -m "feat: resolve reviewed evidence records"
```

### Task 6: Enforce release floors and publish coverage changes

**Files:**
- Modify: `scripts/evidence_coverage.py`
- Create: `scripts/compare_evidence_coverage.py`
- Create: `packaging/evidence-coverage-change.schema.json`
- Modify: `tests/test_evidence_coverage.py`
- Modify: `tests/test_knowledge_compiler.py`
- Modify: `scripts/knowledge_compiler.py`

**Interfaces:**
- Consumes without modification Task 3's `build_coverage(...)`,
  `validate_coverage_report(...)`, `coverage_json_bytes(...)`, full-report schema,
  exact full-report semantics, and canonical bytes
- Produces: `validate_release_floor(report: Mapping[str, object]) -> None`
- Produces: `validate_release_floor_inputs(documents: EvidenceDocuments) -> None`
- Produces: `compare_coverage(previous: Mapping[str, object] | None, current: Mapping[str, object]) -> dict[str, object]`
- Produces CLI: `python scripts/compare_evidence_coverage.py --current PATH (--previous PATH | --initial) --out PATH`

- [ ] **Step 1: Write failing floor, immutability, and change tests**

```python
def test_floor_validation_cannot_mutate_task3_full_report_bytes(valid_documents):
    report = build_coverage(valid_documents, "a" * 64)
    before_object = copy.deepcopy(report)
    before_bytes = coverage_json_bytes(report)
    validate_release_floor_inputs(valid_documents)
    validate_release_floor(report)
    assert report == before_object
    assert coverage_json_bytes(report) == before_bytes


def test_floor_rejects_one_missing_category_average(valid_documents):
    report = build_coverage(without_average(valid_documents, "0401_headphones"), "a" * 64)
    with pytest.raises(CoverageError, match="0401_headphones requires one industry average"):
        validate_release_floor(report)


def test_initial_change_lists_every_current_claim_as_added(valid_report):
    change = compare_coverage(None, valid_report)
    assert change["from_bundle_version"] is None
    assert change["to_bundle_version"] == "3.0.0"
    assert len(change["added"]) == len(valid_report["claims"])
    assert change["known_limitations"] == limitations_from_unknown_rows(valid_report)


def test_task3_full_report_schema_and_golden_semantics_are_unchanged(
    valid_documents,
):
    report = build_coverage(valid_documents, "a" * 64)
    assert report == expected_coverage_report(valid_documents, "a" * 64)
    assert coverage_json_bytes(report) == expected_coverage_bytes(
        valid_documents, "a" * 64,
    )
```

- [ ] **Step 2: Run coverage tests and verify RED**

Run: `.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_evidence_coverage.py -v`

Expected: Task 3 full-report tests remain PASS; new tests FAIL because the
release-floor and comparison functions/change schema do not exist.

- [ ] **Step 3: Add the release floor without changing a valid full report**

Keep the public `validate_release_floor(report)` interface. It first calls Task
3's full-report validator, does not mutate or reinterpret the mapping, and
enforces for each exact released category at least ten reviewed identities,
four reviewed subtypes, three reviewed specific lifecycle records, and one
reviewed industry average. It also requires `summary.categories == 5`, at least
15 total component templates, at least five modern overlays, and at least five
legacy overlays. An Unknown never satisfies a reviewed floor.

The immutable public report intentionally does not expose manufacturer IDs,
market state, battery architecture, or template-to-category ownership. Add
`validate_release_floor_inputs(documents: EvidenceDocuments) -> None` rather
than smuggling those fields into the report. It enforces, for each
category, at least two manufacturers, at least four subtypes including one
current and one discontinued-or-legacy subtype, exactly one standard category
template, at least one modern overlay, at least one legacy overlay, and the
battery-bearing/battery-free variant distinction for headphones, mice, and
keyboards. Task 2's semantic validation remains authoritative for proper broad
service-life endpoints, reviewed sources, exact template shape, and all other
claim correctness. Both floor functions raise `CoverageError` with the exact
category ID and failed requirement and leave their inputs unchanged.

Do not edit `build_coverage`, `validate_coverage_report`,
`coverage_json_bytes`, `packaging/evidence-coverage.schema.json`, the report
shape, the summary meanings, claim inclusion, claim sorting, or encoding. The
Task 3 independent oracle/golden-byte tests run in this task and make this a
release gate rather than a prose promise.

- [ ] **Step 4: Implement only the canonical change artifact**

The change artifact contains exactly `schema_version`, `from_bundle_version`, `to_bundle_version`, `added`, `removed`, `changed`, and `known_limitations`. `added` and `removed` are sorted claim keys. Each changed row contains `claim_key`, `before_source_state`, `after_source_state`, `before_evidence_level`, and `after_evidence_level`. Each limitation contains `claim_key` and `reason` and is derived from current Unknown rows rather than free-form release copy.

`schema_version` is 1. A `claim_key` is the closed object
`{"category_id": Id, "claim_kind": ClaimKind, "claim_id": Id}`, where
`ClaimKind` is Task 3's exact seven-value enum. Key arrays and changed rows are
sorted by the same
`(category_id, claim_kind, claim_id)` tuple as the full report. Comparison first
validates both input reports, rejects a previous report when its
`knowledge_content_sha256` equals the current hash but its canonical bytes
differ, and classifies additions/removals by claim key. `changed` contains keys
present in both reports whose evidence level or source state changed. Current
Unknown rows alone produce `known_limitations`, sorted by claim key. The initial
comparison uses `previous=None`, emits `from_bundle_version=null`, and lists all
current keys as added.

`packaging/evidence-coverage-change.schema.json` uses draft 2020-12, closes
every object recursively, fixes schema version 1 and all exact property sets,
and applies the same category/kind/evidence/source-state constraints as the
Task 3 schema. Serialize the change mapping with UTF-8, `allow_nan=False`,
`sort_keys=True`, separators `(",", ":")`, and one trailing LF. The CLI requires
exactly one of `--previous` and `--initial`, validates canonical current/previous
full-report bytes before comparing, writes through a same-directory temporary
regular file with file and parent-directory fsync, and atomically replaces only
the requested output file.

- [ ] **Step 5: Integrate the release floor before computed metadata or staging**

Inside `compile_knowledge_bundle()`, after the Task 3 projection/content hash
and full report are built but before canonical coverage bytes are accepted,
before either computed metadata row is added, and before a stage directory is
created, call `validate_release_floor_inputs(documents)` and
`validate_release_floor(report)`. A floor failure therefore preserves an old
destination and leaves no compiler stage/backup. For the same valid documents
and content hash, the report object, report bytes, coverage hash, database rows,
logical hash, manifest, and compiler summary must be byte-for-byte identical to
Task 3 behavior; this task changes only which under-floor inputs are rejected.

- [ ] **Step 6: Run coverage/compiler regression tests and commit**

Run: `.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_evidence_coverage.py tests/test_knowledge_compiler.py -v`

Expected: PASS for Task 3's independent full-report oracle and bytes, every
report-visible and document-only category floor, non-mutating validation,
initial/changed comparison, closed change schema, deterministic change bytes,
and compiler failure preservation. Confirm the full-report schema is untouched:

```bash
git diff --exit-code HEAD -- packaging/evidence-coverage.schema.json
```

```bash
git add scripts/evidence_coverage.py scripts/compare_evidence_coverage.py scripts/knowledge_compiler.py packaging/evidence-coverage-change.schema.json tests/test_evidence_coverage.py tests/test_knowledge_compiler.py
git commit -m "feat: enforce evidence coverage release gates"
```

### Task 7: Author bundle metadata, shared sources, and policy records

**Files:**
- Create: `reference/bundle.yaml`
- Create: `reference/common/sources.yaml`
- Create: `reference/common/policies.yaml`
- Create: `tests/corpus/__init__.py`
- Create: `tests/corpus/test_common_evidence.py`

**Interfaces:**
- Consumes: Task 2 authoring contracts
- Consumes: `load_shared_evidence_documents(ROOT / "reference") -> SharedEvidenceDocuments`; this task does not call the complete-tree loader
- Produces exact bundle identity `3 / 3.0.0 / 1.0.0 / 2.0.0`
- Produces policy rule IDs consumed by Slice 2: `urgent_hazard_specialist`, `unknown_identity_more_information`, `missing_required_observation`, `nonworking_repair`, `recoverable_parts`, `supported_reuse`, and `end_of_reference_recycle`

- [ ] **Step 1: Write failing shared-release tests**

```python
def test_bundle_metadata_is_exact():
    shared = load_shared_evidence_documents(ROOT / "reference")
    assert shared.bundle.schema_version == 3
    assert shared.bundle.bundle_version == "3.0.0"
    assert shared.bundle.identity_catalog_version == "1.0.0"
    assert shared.bundle.policy_revision == "2.0.0"
    assert tuple(shared.bundle.category_ids) == RELEASED_CATEGORY_IDS


def test_policy_values_and_safety_priority_are_closed():
    shared = load_shared_evidence_documents(ROOT / "reference")
    rules = {rule.rule_id: rule for rule in shared.policies}
    assert set(rules) == {
        "urgent_hazard_specialist", "unknown_identity_more_information",
        "missing_required_observation", "nonworking_repair", "recoverable_parts",
        "supported_reuse", "end_of_reference_recycle",
    }
    assert rules["urgent_hazard_specialist"].priority < rules["supported_reuse"].priority
    assert rules["urgent_hazard_specialist"].outcome is RecommendationValue.SPECIALIST_HANDLING
```

- [ ] **Step 2: Run the common corpus test and verify RED**

Run: `.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/corpus/test_common_evidence.py -v`

Expected: FAIL because production schema-3 metadata and common records do not exist.

- [ ] **Step 3: Independently author the schema-3 shared source records**

Use the reusable claim facts and canonical URLs in the frozen `reference/sources.yaml` as review leads, then independently author schema-3 EPA, EU RoHS, EU phone-ecodesign, and Apple documentation records in `reference/common/sources.yaml`. Re-open each page and record the actual publication/revision date, `2026-09-07` access/review dates, license/use basis, and reviewer. Do not publish a schema-3 source whose current page does not support its intended claim. This is a copy-and-review migration of information, not a file move: do not edit, rename, delete, or stage `reference/sources.yaml` or `reference/device_components.yaml`; both remain byte-for-byte unchanged for the frozen-v1 compatibility path.

- [ ] **Step 4: Author the closed policy bundle**

Set priorities so urgent triggered hazards precede every reuse/parts rule, incomplete identity or required observations yield `more_information_needed`, nonworking status yields `repair` unless safety overrides, and the remaining rules use only the six approved outcomes. Policy conditions refer only to documented observation, lifecycle-resolution, component, and hazard keys; they do not contain executable expressions or arbitrary Python.

- [ ] **Step 5: Run common schema/policy tests and commit**

Run: `.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_knowledge_schema.py tests/corpus/test_common_evidence.py -v`

Then run:

```bash
git diff --exit-code HEAD -- reference/sources.yaml reference/device_components.yaml
```

Expected: both commands PASS; the shared-only loader validates bundle identity, source metadata, exact policy set, closed outcomes, and safety priority without requiring any category directory, and the frozen-v1 source files are unchanged.

```bash
git add reference/bundle.yaml reference/common tests/corpus/__init__.py tests/corpus/test_common_evidence.py
git commit -m "data: define knowledge bundle policy"
```

After Task 7 passes, Tasks 8–12 are five independent work packets and may be dispatched in parallel. Each worker owns only its named category directory and corpus test, validates that category with `load_category_evidence_documents(...)`, must satisfy the shared schema/coverage contracts, and lands one category-scoped atomic commit. No category task calls `load_evidence_documents(...)`; the complete five-category loader and release floor first become green after all five category commits are present in Task 15.

### Task 8: Publish the computer-mouse corpus

**Files:**
- Create: `reference/categories/0301_computer_mouse/sources.yaml`
- Create: `reference/categories/0301_computer_mouse/identities.yaml`
- Create: `reference/categories/0301_computer_mouse/lifecycles.yaml`
- Create: `reference/categories/0301_computer_mouse/industry_averages.yaml`
- Create: `reference/categories/0301_computer_mouse/components.yaml`
- Create: `reference/categories/0301_computer_mouse/hazards.yaml`
- Create: `reference/categories/0301_computer_mouse/coverage.yaml`
- Create: `tests/corpus/test_mouse_evidence.py`

**Interfaces:**
- Produces category ID `0301_computer_mouse`
- Produces subtypes `mouse_wired_optical`, `mouse_wireless_replaceable_battery`, `mouse_wireless_rechargeable`, and `mouse_ball_legacy`
- Produces `CategoryEvidenceDocuments.component_templates` IDs `mouse_standard`, `mouse_modern_wireless`, and `mouse_legacy_ball`
- Consumes: `load_category_evidence_documents(ROOT / "reference", "0301_computer_mouse")` for the category-scoped fixture and acceptance test

- [ ] **Step 1: Write the failing exact-roster and battery-architecture test**

```python
EXPECTED_MOUSE_IDENTITIES = {
    "apple_magic_mouse_usb_c", "logitech_mx_master_3s", "logitech_g502_hero",
    "logitech_m185", "microsoft_basic_optical_mouse", "microsoft_arc_mouse",
    "razer_deathadder_v3", "dell_ms116", "hp_x3000_g3",
    "microsoft_intellimouse_1_1",
}


def test_mouse_corpus_roster_and_floor(mouse_records):
    assert {item.identity_id for item in mouse_records.identities} == EXPECTED_MOUSE_IDENTITIES
    assert len({item.manufacturer_id for item in mouse_records.identities}) >= 2
    assert {item.subtype_id for item in mouse_records.subtypes} == {
        "mouse_wired_optical", "mouse_wireless_replaceable_battery",
        "mouse_wireless_rechargeable", "mouse_ball_legacy",
    }
    assert {item.battery_architecture for item in mouse_records.subtypes} >= {
        BatteryArchitecture.BATTERY_FREE, BatteryArchitecture.BATTERY_BEARING,
    }
```

- [ ] **Step 2: Run the mouse test and verify RED**

Run: `.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/corpus/test_mouse_evidence.py -v`

Expected: FAIL because the mouse category directory does not exist.

- [ ] **Step 3: Review and author mouse identities and evidence**

Use official manufacturer product/support/manual pages for the ten named identities. Author the exact endpoint records `logitech_mx_master_3s_charge_runtime`, `logitech_m185_cell_runtime`, and `razer_deathadder_v3_pro_charge_runtime`; label each as operating endurance, not total product life. Add `mouse_industry_service_life` only from a transparent population study that reports a comparable mouse service-life range; otherwise the release floor remains intentionally failing.

- [ ] **Step 4: Author mouse components, hazards, and Unknowns**

The standard template covers enclosure, controller PCB, sensor/ball mechanism, switches, wheel where applicable, cable/wireless module, and power source. The modern overlay differentiates rechargeable and replaceable-cell devices; the legacy overlay replaces optical sensing with ball/roller mechanics. Add independently sourced conditional damaged-lithium-ion and leaking-primary-cell hazards. Record unsupported exact materials and hidden battery chemistry as explicit Unknowns.

- [ ] **Step 5: Run mouse/schema coverage and commit**

Run: `.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/corpus/test_mouse_evidence.py tests/test_knowledge_schema.py tests/test_evidence_coverage.py -v`

Expected: PASS for the exact roster, four subtypes, three endurance records, broad range, three component templates, battery variants, hazard provenance, and Unknown rows; missing sibling category directories do not affect this category-scoped gate.

```bash
git add reference/categories/0301_computer_mouse tests/corpus/test_mouse_evidence.py
git commit -m "data: publish mouse evidence corpus"
```

### Task 9: Publish the keyboard corpus

**Files:**
- Create: `reference/categories/0301_keyboard/sources.yaml`
- Create: `reference/categories/0301_keyboard/identities.yaml`
- Create: `reference/categories/0301_keyboard/lifecycles.yaml`
- Create: `reference/categories/0301_keyboard/industry_averages.yaml`
- Create: `reference/categories/0301_keyboard/components.yaml`
- Create: `reference/categories/0301_keyboard/hazards.yaml`
- Create: `reference/categories/0301_keyboard/coverage.yaml`
- Create: `tests/corpus/test_keyboard_evidence.py`

**Interfaces:**
- Produces category ID `0301_keyboard`
- Produces subtypes `keyboard_wired_membrane`, `keyboard_wireless_replaceable_battery`, `keyboard_wireless_rechargeable`, `keyboard_mechanical`, and `keyboard_buckling_spring_legacy`
- Produces `CategoryEvidenceDocuments.component_templates` IDs `keyboard_standard`, `keyboard_modern_wireless`, and `keyboard_legacy_buckling_spring`
- Consumes: `load_category_evidence_documents(ROOT / "reference", "0301_keyboard")` for the category-scoped fixture and acceptance test

- [ ] **Step 1: Write the failing keyboard roster test**

```python
EXPECTED_KEYBOARD_IDENTITIES = {
    "apple_magic_keyboard_usb_c", "logitech_mx_keys_s", "logitech_k120",
    "logitech_k780", "microsoft_wired_keyboard_600", "keychron_k2_v2",
    "razer_blackwidow_v4", "dell_kb216", "ibm_model_m_1391401",
    "apple_extended_keyboard_ii",
}


def test_keyboard_corpus_roster_and_floor(keyboard_records):
    assert {item.identity_id for item in keyboard_records.identities} == EXPECTED_KEYBOARD_IDENTITIES
    assert len(keyboard_records.subtypes) >= 4
    assert len(keyboard_records.specific_lifecycles) >= 3
    assert keyboard_records.industry_averages[0].endpoint == "service_life"
    assert {item.template_kind for item in keyboard_records.component_templates} >= {
        "standard", "modern_overlay", "legacy_overlay"
    }
```

- [ ] **Step 2: Run the keyboard test and verify RED**

Run: `.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/corpus/test_keyboard_evidence.py -v`

Expected: FAIL because the keyboard category directory does not exist.

- [ ] **Step 3: Review and author keyboard identities and evidence**

Use official manufacturer manuals, support pages, and archived product documentation for the ten named identities. Author `logitech_mx_keys_s_charge_runtime`, `logitech_k780_cell_runtime`, and `razer_blackwidow_v4_switch_actuation_endurance` with their actual subjects/endpoints; none is total keyboard life. Add `keyboard_industry_service_life` only from a transparent comparable-population study.

- [ ] **Step 4: Author keyboard components, hazards, and Unknowns**

Cover enclosure, keycaps, switch/membrane assembly, matrix/controller, cable or radio module, and optional power source. The modern overlay distinguishes rechargeable from replaceable cells; the legacy overlay records buckling-spring architecture without inferring materials. Add independent damaged-lithium-ion and primary-cell leakage hazards, and declare unsupported hidden chemistry/composition as Unknown.

- [ ] **Step 5: Run keyboard/schema coverage and commit**

Run: `.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/corpus/test_keyboard_evidence.py tests/test_knowledge_schema.py tests/test_evidence_coverage.py -v`

Expected: PASS for roster, subtype, lifecycle/endurance, average, templates, battery architecture, hazards, and Unknowns; missing sibling category directories do not affect this category-scoped gate.

```bash
git add reference/categories/0301_keyboard tests/corpus/test_keyboard_evidence.py
git commit -m "data: publish keyboard evidence corpus"
```

### Task 10: Publish the laptop corpus

**Files:**
- Create: `reference/categories/0303_laptop/sources.yaml`
- Create: `reference/categories/0303_laptop/identities.yaml`
- Create: `reference/categories/0303_laptop/lifecycles.yaml`
- Create: `reference/categories/0303_laptop/industry_averages.yaml`
- Create: `reference/categories/0303_laptop/components.yaml`
- Create: `reference/categories/0303_laptop/hazards.yaml`
- Create: `reference/categories/0303_laptop/coverage.yaml`
- Create: `tests/corpus/test_laptop_evidence.py`

**Interfaces:**
- Produces category ID `0303_laptop`
- Produces subtypes `laptop_modern_ultrabook`, `laptop_modular`, `laptop_two_in_one`, `laptop_gaming`, and `laptop_legacy_notebook`
- Produces `CategoryEvidenceDocuments.component_templates` IDs `laptop_standard`, `laptop_modern_integrated`, and `laptop_legacy_serviceable`
- Consumes: `load_category_evidence_documents(ROOT / "reference", "0303_laptop")` for the category-scoped fixture and acceptance test

- [ ] **Step 1: Write the failing laptop roster test**

```python
EXPECTED_LAPTOP_IDENTITIES = {
    "apple_macbook_air_m2_2022", "dell_xps_13_9315",
    "lenovo_thinkpad_t14_gen_4", "hp_elitebook_840_g10",
    "framework_laptop_13_amd_7040", "microsoft_surface_laptop_5",
    "asus_zenbook_14_ux3402", "acer_aspire_5_a515_58m",
    "toshiba_satellite_110cs", "apple_powerbook_g4_12_inch",
}


def test_laptop_corpus_roster_and_floor(laptop_records):
    assert {item.identity_id for item in laptop_records.identities} == EXPECTED_LAPTOP_IDENTITIES
    assert len({item.manufacturer_id for item in laptop_records.identities}) >= 2
    assert any(item.market_state is MarketState.LEGACY for item in laptop_records.subtypes)
    assert len(laptop_records.specific_lifecycles) >= 3
    assert len(laptop_records.industry_averages) >= 1
```

- [ ] **Step 2: Run the laptop test and verify RED**

Run: `.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/corpus/test_laptop_evidence.py -v`

Expected: FAIL because the laptop category directory does not exist.

- [ ] **Step 3: Review and author laptop identities and evidence**

Use official model-identification, service-manual, and battery-support pages for the ten named identities. Author `apple_macbook_air_m2_battery_capacity_threshold`, `framework_laptop_13_battery_capacity_threshold`, and `lenovo_thinkpad_t14_battery_capacity_threshold` only when the first-party source states the exact cycle/capacity endpoint and scope. Add `laptop_industry_service_life` from a transparent study with an actual laptop population and publication period; warranty/support/LCA assumed-use values remain separately qualified and do not satisfy this range.

- [ ] **Step 4: Author laptop components, hazards, and Unknowns**

Cover enclosure, display, input assembly, logic board, memory, storage, cooling, speakers, ports, adapter, and battery. The modern overlay records integrated memory/storage only for supported scopes; the legacy overlay records serviceable memory/storage and legacy display/backlight possibilities conditionally. Add independent damaged/swollen lithium-ion and exact-scope legacy backlight hazards without using RoHS as proof of an individual substance.

- [ ] **Step 5: Run laptop/schema coverage and commit**

Run: `.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/corpus/test_laptop_evidence.py tests/test_knowledge_schema.py tests/test_evidence_coverage.py -v`

Expected: PASS for roster, current/legacy subtypes, exact endpoint qualification, broad service-life evidence, overlays, hazards, and Unknowns; missing sibling category directories do not affect this category-scoped gate.

```bash
git add reference/categories/0303_laptop tests/corpus/test_laptop_evidence.py
git commit -m "data: publish laptop evidence corpus"
```

### Task 11: Publish the mobile-phone corpus

**Files:**
- Create: `reference/categories/0306_mobile_phone/sources.yaml`
- Create: `reference/categories/0306_mobile_phone/identities.yaml`
- Create: `reference/categories/0306_mobile_phone/lifecycles.yaml`
- Create: `reference/categories/0306_mobile_phone/industry_averages.yaml`
- Create: `reference/categories/0306_mobile_phone/components.yaml`
- Create: `reference/categories/0306_mobile_phone/hazards.yaml`
- Create: `reference/categories/0306_mobile_phone/coverage.yaml`
- Create: `tests/corpus/test_phone_evidence.py`

**Interfaces:**
- Produces category ID `0306_mobile_phone`
- Produces subtypes `phone_slate_smartphone`, `phone_foldable_smartphone`, `phone_modular_smartphone`, `phone_feature_legacy`, and `phone_keyboard_legacy`
- Produces `CategoryEvidenceDocuments.component_templates` IDs `phone_standard`, `phone_modern_integrated`, and `phone_legacy_removable_battery`
- Consumes: `load_category_evidence_documents(ROOT / "reference", "0306_mobile_phone")` for the category-scoped fixture and acceptance test

- [ ] **Step 1: Write the failing phone roster and threshold test**

```python
EXPECTED_PHONE_IDENTITIES = {
    "apple_iphone_15", "apple_iphone_se_3", "samsung_galaxy_s24",
    "google_pixel_8", "fairphone_5", "motorola_razr_40_ultra",
    "samsung_galaxy_s5", "nokia_3310_2017", "motorola_razr_v3",
    "blackberry_bold_9900",
}


def test_phone_corpus_roster_and_capacity_endpoints(phone_records):
    assert {item.identity_id for item in phone_records.identities} == EXPECTED_PHONE_IDENTITIES
    threshold_ids = {item.record_id for item in phone_records.specific_lifecycles}
    assert {
        "eu_phone_battery_800_cycles_80_percent",
        "apple_iphone_15_battery_capacity_threshold",
        "fairphone_5_battery_capacity_threshold",
    } <= threshold_ids
    assert all(
        item.endpoint_kind is LifecycleEndpointKind.CAPACITY_THRESHOLD
        for item in phone_records.specific_lifecycles
        if "battery" in item.record_id
    )
```

- [ ] **Step 2: Run the phone test and verify RED**

Run: `.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/corpus/test_phone_evidence.py -v`

Expected: FAIL because the phone category directory does not exist.

- [ ] **Step 3: Review and author phone identities and evidence**

Use official manufacturer identification/support pages and the reviewed EU regulation for the ten named identities. Preserve the existing EU `800 cycles to 80% capacity` endpoint, add exact Apple and Fairphone capacity-threshold records only at their documented model/family scope, and never mark any as total product life. Add `phone_industry_service_life` from a transparent comparable-population study.

- [ ] **Step 4: Author phone components, hazards, and Unknowns**

Cover enclosure, display, logic board, storage, camera, speakers/microphones, vibration device, ports, and battery. Modern and legacy overlays distinguish integrated versus removable batteries, foldable display/hinge architecture, and physical-keyboard/feature-phone variants. Add damaged-lithium-ion and broken-exterior handling hazards with hazard-specific sources. Generic RoHS/WEEE context remains process evidence, never proof of material presence.

- [ ] **Step 5: Run phone/schema coverage and commit**

Run: `.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/corpus/test_phone_evidence.py tests/test_knowledge_schema.py tests/test_evidence_coverage.py -v`

Expected: PASS for roster, subtypes, threshold qualification, broad range, overlays, hazards, provenance separation, and Unknowns; missing sibling category directories do not affect this category-scoped gate.

```bash
git add reference/categories/0306_mobile_phone tests/corpus/test_phone_evidence.py
git commit -m "data: publish phone evidence corpus"
```

### Task 12: Publish the headphones corpus

**Files:**
- Create: `reference/categories/0401_headphones/sources.yaml`
- Create: `reference/categories/0401_headphones/identities.yaml`
- Create: `reference/categories/0401_headphones/lifecycles.yaml`
- Create: `reference/categories/0401_headphones/industry_averages.yaml`
- Create: `reference/categories/0401_headphones/components.yaml`
- Create: `reference/categories/0401_headphones/hazards.yaml`
- Create: `reference/categories/0401_headphones/coverage.yaml`
- Create: `tests/corpus/test_headphones_evidence.py`

**Interfaces:**
- Produces category ID `0401_headphones`
- Produces subtypes `headphones_wired_over_ear`, `headphones_wired_on_ear_legacy`, `headphones_wireless_over_ear`, and `headphones_true_wireless`
- Produces `CategoryEvidenceDocuments.component_templates` IDs `headphones_standard`, `headphones_modern_wireless`, and `headphones_legacy_wired`
- Consumes: `load_category_evidence_documents(ROOT / "reference", "0401_headphones")` for the category-scoped fixture and acceptance test

- [ ] **Step 1: Write the failing headphones roster and battery test**

```python
EXPECTED_HEADPHONE_IDENTITIES = {
    "apple_airpods_pro_2_usb_c", "sony_wh_1000xm5",
    "bose_quietcomfort_ultra_headphones", "sennheiser_hd_600",
    "audio_technica_ath_m50x", "jabra_elite_8_active",
    "beats_studio_pro", "logitech_g_pro_x_wired", "koss_porta_pro",
    "sony_mdr_7506",
}


def test_headphones_corpus_roster_and_battery_architecture(headphone_records):
    assert {item.identity_id for item in headphone_records.identities} == EXPECTED_HEADPHONE_IDENTITIES
    assert {item.battery_architecture for item in headphone_records.subtypes} >= {
        BatteryArchitecture.BATTERY_FREE, BatteryArchitecture.BATTERY_BEARING,
    }
    assert len(headphone_records.specific_lifecycles) >= 3
    assert len(headphone_records.industry_averages) >= 1
```

- [ ] **Step 2: Run the headphones test and verify RED**

Run: `.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/corpus/test_headphones_evidence.py -v`

Expected: FAIL because the headphones category directory does not exist.

- [ ] **Step 3: Review and author headphone identities and evidence**

Use official manufacturer product/support/manual pages for the ten named identities. Author `airpods_pro_2_listening_runtime`, `sony_wh_1000xm5_charge_runtime`, and `bose_quietcomfort_ultra_charge_runtime` as one-charge operating endpoints, never physical lifespan. Add `headphones_industry_service_life` only from a transparent study that distinguishes headphones from unrelated consumer electronics.

- [ ] **Step 4: Author headphone components, hazards, and Unknowns**

Cover enclosure/headband, cushions or tips, audio drivers, controls/PCB, cable/radio module, microphones, charging case where applicable, and battery only for supported variants. The wired legacy overlay is explicitly battery-free; wireless and true-wireless overlays distinguish device and case batteries. Add independently sourced damaged-lithium-ion guidance and record hidden chemistry/materials as Unknown.

- [ ] **Step 5: Run headphones/schema coverage and commit**

Run: `.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/corpus/test_headphones_evidence.py tests/test_knowledge_schema.py tests/test_evidence_coverage.py -v`

Expected: PASS for roster, four subtypes, runtime endpoints, broad range, overlays, battery distinctions, hazard sources, and Unknowns; missing sibling category directories do not affect this category-scoped gate.

```bash
git add reference/categories/0401_headphones tests/corpus/test_headphones_evidence.py
git commit -m "data: publish headphones evidence corpus"
```

### Task 13: Add an explicit-injection v1 compatibility adapter

**Files:**
- Create: `server/reference_adapter.py`
- Create: `tests/test_reference_adapter.py`

**Interfaces:**
- Produces: `V1ReferenceAdapter(store: KnowledgeStore, resolver: EvidenceResolver)`
- Produces: `V1ReferenceAdapter.list_categories() -> list[dict[str, object]]`
- Produces: `V1ReferenceAdapter.get_category(category_id: str) -> dict[str, object] | None`
- Produces: `V1ReferenceAdapter.snapshot(category_id: str) -> dict[str, object]`
- Consumes the existing `create_desktop_app(..., reference_store=...)` injection point without changing desktop assembly or frozen resource discovery

- [ ] **Step 1: Write failing adapter and authority-boundary tests**

```python
def test_v1_adapter_maps_category_only_without_claiming_specificity(knowledge_store):
    adapter = V1ReferenceAdapter(knowledge_store, EvidenceResolver(knowledge_store))
    snapshot = adapter.snapshot("0301_keyboard")
    assert snapshot["category_id"] == "0301_keyboard"
    assert snapshot["template_version"] == "3.0.0"
    assert all(
        item["presence_label"] in {"standard", "common", "optional", "unknown"}
        for item in snapshot["components"]
    )
    assert not any(
        item.get("association_status") == "exact_model_confirmed"
        for item in snapshot["components"]
    )


def test_v1_app_uses_the_adapter_only_when_it_is_explicitly_injected(
    classifier, knowledge_store
):
    adapter = V1ReferenceAdapter(knowledge_store, EvidenceResolver(knowledge_store))
    app = create_desktop_app(classifier=classifier, reference_store=adapter)
    assert app.config["REFERENCE_STORE"] is adapter
    response = app.test_client().get("/api/v1/reference/categories")
    assert response.status_code == 200


def test_adapter_imports_no_yaml_or_admin_compiler():
    imported = imported_modules_for("server.reference_adapter")
    assert "scripts.knowledge_schema" not in imported
    assert "scripts.knowledge_compiler" not in imported
    assert "yaml" not in imported
```

- [ ] **Step 2: Run the adapter tests and verify RED**

Run: `.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_reference_adapter.py -v`

Expected: FAIL during collection because `server.reference_adapter` does not exist.

- [ ] **Step 3: Implement a category-only projection**

Map schema-3 authored statuses only in the adapter: category-template associations → `standard`, commonly associated → `common`, conditional → `optional`, and legacy-specific/not-present/Unknown → `unknown`. Exclude subtype, family, and model overlays from a category-only snapshot. Preserve complete source dictionaries on each projected component and hazard-derived rule; never substitute lifecycle sources for hazard sources.

The adapter is a temporary v1 projection, not a second resolver. A development or test service may pass it through the existing `reference_store=` argument. The unchanged frozen app continues to construct the schema-2 `ReferenceStore` until Slice 5. No service instance constructs both providers, no schema-3 fallback silently replaces a schema-2 snapshot, and absence of an explicitly injected adapter leaves schema-3 evidence unavailable.

- [ ] **Step 4: Prove old and new compatibility paths independently**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_reference_adapter.py tests/test_reference_db.py tests/test_reference_release.py tests/test_assessment_api.py tests/test_desktop_integration_fixes.py -q
.venv/bin/python -m py_compile server/reference_adapter.py
```

Expected: PASS; adapter-backed v1 tests receive only category evidence, and every unchanged schema-2/runtime/package test remains green.

- [ ] **Step 5: Commit only the opt-in adapter**

```bash
git add server/reference_adapter.py tests/test_reference_adapter.py
git commit -m "feat: add opt-in knowledge compatibility adapter"
```

### Task 14: Define and verify the three-file release-input handoff

**Files:**
- Create: `scripts/knowledge_release.py`
- Create: `tests/test_knowledge_release_inputs.py`

**Interfaces:**
- Produces frozen `KnowledgeReleaseInputs`
- Produces: `verify_knowledge_release_inputs(candidate_dir: Path, approval_path: Path) -> KnowledgeReleaseInputs`
- Produces CLI: `python scripts/knowledge_release.py --candidate DIRECTORY --approval PATH --print-summary`
- Candidate files are exactly `knowledge.sqlite`, `evidence-coverage.json`, and `evidence-coverage-change.json`

`KnowledgeReleaseInputs` fields are exactly `knowledge_database_path`, `evidence_coverage_path`, `evidence_coverage_change_path`, `knowledge_sha256`, `stamp`, `coverage_sha256`, and `coverage_change_sha256`. `stamp` is the canonical `BundleStamp`, so Slice 5 receives schema, bundle, identity-catalog, policy, and logical-content identities without renaming them.

- [ ] **Step 1: Write failing closed-approval and three-artifact tests**

```python
def test_verifier_returns_every_release_expectation(approved_candidate):
    candidate, approval, manifest = approved_candidate
    result = verify_knowledge_release_inputs(candidate, approval)
    assert result.knowledge_database_path == candidate / "knowledge.sqlite"
    assert result.evidence_coverage_path == candidate / "evidence-coverage.json"
    assert result.evidence_coverage_change_path == candidate / "evidence-coverage-change.json"
    assert result.knowledge_sha256 == sha256(candidate / "knowledge.sqlite")
    assert result.stamp == manifest.stamp
    assert result.coverage_sha256 == manifest.coverage_sha256
    assert result.coverage_change_sha256 == sha256(
        candidate / "evidence-coverage-change.json"
    )


@pytest.mark.parametrize(
    "artifact",
    ("knowledge.sqlite", "evidence-coverage.json", "evidence-coverage-change.json"),
)
def test_verifier_rejects_each_tampered_artifact(approved_candidate, artifact):
    candidate, approval, _manifest = approved_candidate
    path = candidate / artifact
    path.write_bytes(path.read_bytes() + b"tampered")
    with pytest.raises(KnowledgeReleaseError, match="unavailable or incompatible"):
        verify_knowledge_release_inputs(candidate, approval)


def test_verifier_rejects_an_extra_candidate_file(approved_candidate):
    candidate, approval, _manifest = approved_candidate
    (candidate / "unreviewed.json").write_text("{}")
    with pytest.raises(KnowledgeReleaseError, match="unavailable or incompatible"):
        verify_knowledge_release_inputs(candidate, approval)


@pytest.mark.parametrize(
    "symlink_target",
    (
        "candidate_dir", "knowledge.sqlite", "evidence-coverage.json",
        "evidence-coverage-change.json", "approval_path",
    ),
)
def test_verifier_rejects_each_symlinked_input(approved_candidate, symlink_target):
    candidate, approval, _manifest = approved_candidate
    if symlink_target == "candidate_dir":
        real_path = candidate.with_name(f"{candidate.name}-real")
        candidate.rename(real_path)
        candidate.symlink_to(real_path, target_is_directory=True)
        hostile_path = candidate
    elif symlink_target == "approval_path":
        real_path = approval.with_name(f"{approval.name}.real")
        approval.rename(real_path)
        approval.symlink_to(real_path)
        hostile_path = approval
    else:
        hostile_path = candidate / symlink_target
        real_path = candidate.parent / f"{symlink_target}.real"
        hostile_path.rename(real_path)
        hostile_path.symlink_to(real_path)
    assert hostile_path.is_symlink()
    with pytest.raises(KnowledgeReleaseError, match="unsafe release input path"):
        verify_knowledge_release_inputs(candidate, approval)
```

- [ ] **Step 2: Run the handoff tests and verify RED**

Run: `.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_knowledge_release_inputs.py -v`

Expected: FAIL during collection because `scripts.knowledge_release` does not exist.

- [ ] **Step 3: Implement the closed approval trust record**

Accept exactly these top-level approval keys: `approval_schema_version`, `schema_version`, `bundle_version`, `identity_catalog_version`, `policy_revision`, `knowledge_sha256`, `content_sha256`, `coverage_sha256`, `coverage_change_sha256`, `corpus_counts`, `reviewed_by`, and `reviewed_on`. Require approval schema 1, knowledge schema 3, bundle `3.0.0`, catalog `1.0.0`, policy `2.0.0`, lowercase SHA-256 strings, a non-empty reviewer, and an ISO review date. `corpus_counts` has the exact immutable full-report summary keys emitted by Task 3 and positive integer values; Task 6 validates those counts without changing their names, meanings, order, or bytes.

Before opening any input, inspect every path component without following links.
The candidate must be a real directory rather than a symlink; each of its three
approved artifacts must be a non-symlinked regular file whose resolved parent is
exactly the resolved candidate directory; and the approval path must itself be
a non-symlinked regular file. Any failure raises
`KnowledgeReleaseError("unsafe release input path")`. Then resolve all paths
strictly; reject special files, path overlap, missing or extra candidate
entries, malformed/non-canonical JSON, and changed bytes during verification.
Open the database and coverage together through `KnowledgeStore` with the
approved raw/logical/coverage/version expectations. Validate the change
artifact against its closed schema, require `to_bundle_version == "3.0.0"`,
require its current limitations to equal the coverage report's Unknown rows,
and then return resolved absolute paths and hashes.

The approval file is the source-controlled trust record; rewriting artifact hashes alone cannot bless a swap. This verifier does not create or modify an app release manifest.

- [ ] **Step 4: Run handoff integrity tests and commit**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_knowledge_release_inputs.py tests/test_knowledge_store.py tests/test_evidence_coverage.py -q
.venv/bin/python -m py_compile scripts/knowledge_release.py
```

Expected: PASS for valid input, every single-artifact tamper, coordinated
bundle/report swaps, the separate extra-file case, candidate-directory and all
three artifact symlinks, approval symlink, containment/regular-file checks,
malformed approval values, version drift, and Unknown-limitation drift.

```bash
git add scripts/knowledge_release.py tests/test_knowledge_release_inputs.py
git commit -m "feat: verify knowledge release inputs"
```

### Task 15: Approve the evidence candidate and document the handoff

**Files:**
- Create: `reference/approved-release.json`
- Create: `tests/test_knowledge_release.py`
- Create: `docs/EVIDENCE_BUNDLE_PROCEDURE.md`

**Interfaces:**
- Produces the checked-in approval record consumed by `verify_knowledge_release_inputs(...)`
- Produces the ignored candidate directory `.release-staging/knowledge-3.0.0/` with the exact three files from Task 14
- Produces reproducible compile, compare, second-person review, approval, and verification commands for the Slice 5 handoff

- [ ] **Step 1: Write the failing whole-release acceptance test**

```python
def test_reviewed_bundle_matches_the_checked_in_approval(tmp_path):
    output = tmp_path / "knowledge"
    manifest = compile_knowledge_bundle(ROOT / "reference", output)
    approved = json.loads((ROOT / "reference/approved-release.json").read_text())
    assert manifest.stamp == BundleStamp(
        approved["schema_version"],
        approved["bundle_version"],
        approved["identity_catalog_version"],
        approved["policy_revision"],
        approved["content_sha256"],
    )
    assert manifest.coverage_sha256 == approved["coverage_sha256"]
    with KnowledgeStore(output / "knowledge.sqlite", output / "evidence-coverage.json") as store:
        resolver = EvidenceResolver(store)
        for category_id in RELEASED_CATEGORY_IDS:
            resolved = resolver.resolve(
                CanonicalIdentityScope(category_id),
                LifecycleRequest("device", "service_life", "elapsed_time", "years"),
            )
            assert resolved.lifecycle.tier is ResolutionTier.INDUSTRY_AVERAGE
            assert resolved.components.components
            assert resolved.bundle == manifest.stamp
```

- [ ] **Step 2: Run the full knowledge test and verify RED**

Run: `.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_knowledge_release.py -v`

Expected: FAIL because `reference/approved-release.json` does not yet exist.

- [ ] **Step 3: Build twice and produce the exact handoff artifacts**

Run:

```bash
first_build="$(mktemp -d)"
.venv/bin/python scripts/build_knowledge_bundle.py --source reference --out "$first_build/knowledge" --print-summary
.venv/bin/python scripts/build_knowledge_bundle.py --source reference --out .release-staging/knowledge-3.0.0 --print-summary
cmp "$first_build/knowledge/evidence-coverage.json" .release-staging/knowledge-3.0.0/evidence-coverage.json
.venv/bin/python scripts/compare_evidence_coverage.py --current .release-staging/knowledge-3.0.0/evidence-coverage.json --initial --out .release-staging/knowledge-3.0.0/evidence-coverage-change.json
```

Confirm that both compiler summaries and logical hashes match. Raw SQLite bytes are not the cross-platform logical identity; approve the raw SHA-256 of the exact `.release-staging/knowledge-3.0.0/knowledge.sqlite` candidate that Slice 5 will consume.

- [ ] **Step 4: Complete second-person review and pin the approval**

Review every source URL, claim endpoint, scope, evidence level, license/use basis, Unknown, and coverage-floor count. Populate `reference/approved-release.json` with the exact closed fields from Task 14, the compiler's corpus counts, the candidate's three SHA-256 values, reviewer identity, and review date. Then run:

```bash
.venv/bin/python scripts/knowledge_release.py --candidate .release-staging/knowledge-3.0.0 --approval reference/approved-release.json --print-summary
```

Do not approve a candidate with a failing floor, unresolved license/use basis, endpoint mismatch, unsupported substitute claim, hash drift, or change report that omits an Unknown limitation.

- [ ] **Step 5: Document the administrator procedure and Slice 5 boundary**

`docs/EVIDENCE_BUNDLE_PROCEDURE.md` documents source selection, separate lifecycle/hazard review, the five category owners, version rules, exact build/compare commands, second-person approval, correction of an Unknown, and the three-file handoff. It states that external citations open only on explicit user action. It also states that Slice 1 does not change the active schema-1 app release: Slice 5 alone updates desktop paths/metadata, `prepare_release.py`, macOS verification/build/spec files, packaged smoke coverage, release notes, and the release-manifest schema, then removes schema-2 data/code and PyYAML from product dependencies atomically.

- [ ] **Step 6: Run focused, compatibility, and full verification**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_evidence_types.py tests/test_knowledge_schema.py tests/test_knowledge_compiler.py tests/test_knowledge_store.py tests/test_evidence_resolver.py tests/test_evidence_coverage.py tests/test_knowledge_release_inputs.py tests/test_reference_adapter.py tests/corpus tests/test_knowledge_release.py -q
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_reference_db.py tests/test_reference_release.py tests/test_release_pipeline.py tests/test_release_metadata.py tests/test_packaging.py tests/test_packaged_smoke.py -q
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' -q
git diff --check
```

Expected: every command passes; the new schema-3 candidate is approved independently, and the unchanged schema-2 frozen package baseline remains green. Verify `git status --short` contains no generated file from `.release-staging/` and no Slice 5 release/package file.

- [ ] **Step 7: Commit the approved evidence handoff**

```bash
git add reference/approved-release.json tests/test_knowledge_release.py docs/EVIDENCE_BUNDLE_PROCEDURE.md
git commit -m "docs: approve knowledge release inputs"
```

Handoff to Slice 5 with these exact inputs and expectations:

| Input | Path or value |
|---|---|
| Knowledge database | `.release-staging/knowledge-3.0.0/knowledge.sqlite` |
| Full coverage matrix | `.release-staging/knowledge-3.0.0/evidence-coverage.json` |
| Coverage change | `.release-staging/knowledge-3.0.0/evidence-coverage-change.json` |
| Approval trust record | `reference/approved-release.json` |
| Runtime stamp fields | `schema_version`, `bundle_version`, `identity_catalog_version`, `policy_revision`, `content_sha256` |
| Raw/report fields | `knowledge_sha256`, `coverage_sha256`, `coverage_change_sha256` |

Slice 5 must validate this triple before staging, package only schema-3 artifacts after its manifest-v2 cutover, and remove the temporary schema-2 path in that same atomic commit. Old and new databases are never packaged together.

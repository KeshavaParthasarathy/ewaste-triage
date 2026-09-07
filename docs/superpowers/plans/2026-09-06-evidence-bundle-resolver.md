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

### Task 2: Validate the administrator authoring tree

**Files:**
- Create: `scripts/knowledge_schema.py`
- Create: `tests/knowledge_helpers.py`
- Create: `tests/test_knowledge_schema.py`

**Interfaces:**
- Produces: `EvidenceValidationError(filename: str, record_path: str, message: str)`
- Produces frozen `SharedEvidenceDocuments`, `CategoryEvidenceDocuments`, and `EvidenceDocuments`
- `SharedEvidenceDocuments` owns exactly `bundle`, `sources`, and `policies`; `CategoryEvidenceDocuments` owns exactly `category`, `sources`, `subtypes`, `identities`, `lifecycles`, `industry_averages`, `components`, `hazards`, and `unknowns`; `EvidenceDocuments` combines one shared value with the complete ordered category tuple
- Produces: `load_shared_evidence_documents(source_dir: Path) -> SharedEvidenceDocuments`
- Produces: `load_category_evidence_documents(source_dir: Path, category_id: str, *, shared: SharedEvidenceDocuments | None = None) -> CategoryEvidenceDocuments`
- Produces: `load_evidence_documents(source_dir: Path) -> EvidenceDocuments`
- Consumes: the exact source-tree layout from the File Structure section

- [ ] **Step 1: Write failing closed-schema, provenance, hierarchy, and path tests**

```python
import shutil


def test_loader_rejects_unknown_source_fields(tmp_path):
    source = make_valid_knowledge_source(tmp_path)
    mutate_yaml(source / "common/sources.yaml", lambda doc: doc["sources"][0].update({"trust_me": True}))
    with pytest.raises(EvidenceValidationError, match=r"common/sources.yaml: sources\[0\].*trust_me"):
        load_evidence_documents(source)


def test_grade_d_cannot_support_lifecycle(tmp_path):
    source = make_valid_knowledge_source(tmp_path)
    path = source / "categories/0303_laptop/lifecycles.yaml"
    mutate_yaml(path, lambda doc: doc["records"][0].update({"evidence_level": "D"}))
    with pytest.raises(EvidenceValidationError, match="grade D cannot support lifecycle"):
        load_evidence_documents(source)


def test_model_scope_must_match_the_canonical_hierarchy(tmp_path):
    source = make_valid_knowledge_source(tmp_path)
    path = source / "categories/0306_mobile_phone/lifecycles.yaml"
    mutate_yaml(path, lambda doc: doc["records"][0]["scope"].update({"model_id": "0303_laptop_model_00"}))
    with pytest.raises(EvidenceValidationError, match="scope hierarchy"):
        load_evidence_documents(source)


def test_loader_rejects_symlinked_category_documents(tmp_path):
    source = make_valid_knowledge_source(tmp_path)
    target = source / "categories/0301_keyboard/sources.yaml"
    target.unlink()
    target.symlink_to(source / "common/sources.yaml")
    with pytest.raises(EvidenceValidationError, match="symbolic links are not accepted"):
        load_evidence_documents(source)


def test_shared_loader_is_green_before_category_authoring(tmp_path):
    source = make_valid_knowledge_source(tmp_path)
    shutil.rmtree(source / "categories")
    shared = load_shared_evidence_documents(source)
    assert tuple(shared.bundle.category_ids) == RELEASED_CATEGORY_IDS
    assert shared.sources
    assert shared.policies


def test_single_category_loader_does_not_require_sibling_categories(tmp_path):
    source = make_valid_knowledge_source(tmp_path)
    for path in (source / "categories").iterdir():
        if path.name != "0301_computer_mouse":
            shutil.rmtree(path)
    shared = load_shared_evidence_documents(source)
    category = load_category_evidence_documents(
        source, "0301_computer_mouse", shared=shared
    )
    assert category.category.category_id == "0301_computer_mouse"
    with pytest.raises(EvidenceValidationError, match="missing category directory"):
        load_evidence_documents(source)
```

- [ ] **Step 2: Run schema tests and verify RED**

Run: `.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_knowledge_schema.py -v`

Expected: FAIL during collection because the loader and helpers do not exist.

- [ ] **Step 3: Implement fixed discovery and scalar validation**

Implement three explicit validation stages rather than making partial authoring impersonate a complete release tree:

- `load_shared_evidence_documents` reads only `bundle.yaml` and the two fixed `common/*.yaml` files. It validates the exact released category list, bundle/catalog/policy identities, shared source records, and policy syntax without requiring `reference/categories/` to exist.
- `load_category_evidence_documents` first accepts or loads the shared documents, verifies that `category_id` is declared by the bundle, and reads only the seven fixed files below that one category. It validates the category against shared sources and policy vocabulary but does not require sibling category directories. Reject an unexpected file or symlink inside the requested category.
- `load_evidence_documents` is the release-complete entry point. It loads shared documents, calls the single-category loader for every category in `RELEASED_CATEGORY_IDS`, rejects missing or extra category directories, and then applies cross-category checks before returning `EvidenceDocuments`.

Across all three entry points, reject symlinks, duplicate YAML keys, non-mapping roots, unknown fields, booleans used as integers, non-finite numbers, non-NFC text, IDs outside `[a-z0-9][a-z0-9_.-]*`, invalid semantic versions, invalid ISO dates, and non-HTTPS canonical URLs. A missing sibling category is an error only for `load_evidence_documents`, never for the shared or requested-category entry point.

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

`tests/knowledge_helpers.py` must generate reusable valid shared documents, a requested-category tree, and a fully valid synthetic five-category tree with ten identities, four subtypes, one average, three specific lifecycle/endurance records, three templates, one hazard, and one explicit Unknown per category. Synthetic records use `https://example.invalid/` URLs and are never copied into production `reference/`.

- [ ] **Step 4: Implement cross-document claim checks**

The shared loader validates shared-source ID uniqueness, policy revision equality, closed policy values/priorities, and policy predicate syntax. The single-category loader validates uniqueness against shared IDs, casefolded alias uniqueness within the requested category, category/subtype/family/model ancestry, model years and applicability ranges, variant references, claim/source references, evidence-level/scope compatibility, endpoint qualification, finite positive ordered ranges, required industry population/methodology/period/uncertainty/limitations, component overlay scope, authored association statuses excluding `user_confirmed`, hazard component IDs, trigger keys, severity, immediate/follow-up actions, handling/disposal guidance, independent source IDs, and deliberate Unknown reason/evidence-request fields. The complete loader additionally validates IDs that must be unique across categories and exact category-directory closure.

- [ ] **Step 5: Run schema and type suites**

Run: `.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_evidence_types.py tests/test_knowledge_schema.py -v`

Expected: PASS for the valid synthetic tree and every closed-schema, source, hierarchy, range, applicability, provenance, symlink, and Unknown mutation.

- [ ] **Step 6: Commit the authoring validator**

```bash
git add scripts/knowledge_schema.py tests/knowledge_helpers.py tests/test_knowledge_schema.py
git commit -m "feat: validate knowledge authoring sources"
```

### Task 3: Compile one atomic schema-3 knowledge bundle

**Files:**
- Create: `scripts/knowledge_compiler.py`
- Create: `scripts/build_knowledge_bundle.py`
- Create: `tests/test_knowledge_compiler.py`

**Interfaces:**
- Consumes: `load_evidence_documents(source_dir: Path) -> EvidenceDocuments`
- Produces: `compile_knowledge_bundle(source_dir: Path, destination_dir: Path) -> KnowledgeManifest`
- Produces fixed files: `<destination_dir>/knowledge.sqlite` and `<destination_dir>/evidence-coverage.json`
- Produces CLI: `python scripts/build_knowledge_bundle.py --source PATH --out DIRECTORY --print-summary`

- [ ] **Step 1: Write failing schema, digest, output, and atomicity tests**

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


def test_every_semantic_table_changes_the_logical_digest(tmp_path):
    source = make_valid_knowledge_source(tmp_path / "source")
    baseline = compile_knowledge_bundle(source, tmp_path / "baseline")
    for mutation_name, mutation in semantic_mutations():
        changed_source = clone_and_mutate(source, tmp_path / mutation_name, mutation)
        changed = compile_knowledge_bundle(changed_source, tmp_path / f"out-{mutation_name}")
        assert changed.content_sha256 != baseline.content_sha256


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
```

- [ ] **Step 2: Run compiler tests and verify RED**

Run: `.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_knowledge_compiler.py -v`

Expected: FAIL during collection because `scripts.knowledge_compiler` does not exist.

- [ ] **Step 3: Implement the normalized schema and logical digest**

Create tables `metadata`, `sources`, `categories`, `subtypes`, `identities`, `identity_aliases`, `identity_tokens`, `lifecycle_records`, `industry_averages`, `components`, `component_templates`, `component_associations`, `hazards`, `hazard_triggers`, `hazard_actions`, `policy_rules`, `coverage_unknowns`, and `claim_sources`. Enable foreign keys, use deterministic primary keys and insert order, and include every semantic column in the canonical JSON hashed as `content_sha256`.

Computed metadata keys are exactly `schema_version`, `bundle_version`, `identity_catalog_version`, `policy_revision`, `content_sha256`, and `coverage_sha256`. Exclude the two computed hashes from their own logical-digest input.

- [ ] **Step 4: Emit coverage and promote the directory atomically**

Write both outputs below a sibling temporary directory, fsync each file and the temporary directory, reopen the SQLite file read-only, verify `PRAGMA quick_check`, foreign keys, logical digest, and coverage linkage, then promote. If the destination exists, move it to a sibling backup, replace it with the completed temporary directory, restore the backup after any promotion failure, and remove the backup only after success.

The CLI summary has stable ordering and prints bundle/catalog/policy/schema versions, counts by category and claim kind, reviewed/Unknown totals, logical SHA-256, and coverage SHA-256.

- [ ] **Step 5: Run deterministic compilation twice**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_knowledge_compiler.py -v
```

Expected: tests PASS; the two summaries, logical hashes, and `evidence-coverage.json` bytes match. Raw SQLite hashes are recorded but are not used as the platform-independent logical identity.

- [ ] **Step 6: Commit the compiler and CLI**

```bash
git add scripts/knowledge_compiler.py scripts/build_knowledge_bundle.py tests/test_knowledge_compiler.py
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
```

- [ ] **Step 2: Run store tests and verify RED**

Run: `.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_knowledge_store.py -v`

Expected: FAIL during collection because `server.knowledge_store` does not exist.

- [ ] **Step 3: Implement fail-closed startup and immutable queries**

Use only `dataclasses`, `datetime`, `hashlib`, `json`, `pathlib`, `sqlite3`, `threading`, and other Python standard-library modules. Resolve paths safely, hash the database before and after opening, use SQLite URI `mode=ro`, set `query_only`, validate exact metadata/table/column sets, run quick/foreign-key checks, recompute the logical digest, validate expected release values, and verify the coverage file hash plus its bundle-version/content-hash linkage. Convert all rows into frozen types and expand claim sources independently.

Identity search normalizes Unicode, whitespace, and case only; it searches display names, aliases, and distinguishing tokens with deterministic exact-prefix-token ordering. It never performs network lookup and never turns a search result into a user decision.

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
```

- [ ] **Step 2: Write failing category-only, overlay, hazard, and source tests**

```python
def test_category_only_scope_uses_only_average_and_base_components(resolver):
    scope = CanonicalIdentityScope("0301_keyboard")
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


def test_hazard_sources_are_not_copied_from_lifecycle(resolver, phone_scope):
    resolved = resolver.resolve_hazards(phone_scope)
    battery = next(item for item in resolved.hazards if item.hazard_id == "phone_damaged_li_ion")
    assert {source.source_id for source in battery.sources} == {"epa_used_li_ion_2026"}
    assert "eu_phone_ecodesign_2023_1670" not in {source.source_id for source in battery.sources}
```

- [ ] **Step 3: Run resolver tests and verify RED**

Run: `.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_evidence_resolver.py -v`

Expected: FAIL because `EvidenceResolver` does not exist.

- [ ] **Step 4: Implement deterministic resolution**

Filter candidates by canonical hierarchy, subject, endpoint, metric, unit, applicable date, model year, and required/excluded variants before grouping them into `EXACT_MODEL`, `FAMILY`, `SUBTYPE`, and `INDUSTRY_AVERAGE`. At the first tier with applicable candidates, select the unique lowest integer precedence. A tie returns Unknown with all conflicting IDs in the trace. Never continue to a lower tier after finding a same-tier conflict, and never merge numeric ranges.

Apply component layers in category/subtype/family/model order by component ID. A more-specific explicit association replaces the prior association; an omitted component leaves the prior value unchanged. Resolve applicable hazards without interpreting trigger observations. Attach `store.policy_bundle()` and `store.manifest.stamp` in `ResolvedEvidence`.

- [ ] **Step 5: Run resolver/store/type tests and commit**

Run: `.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_evidence_types.py tests/test_knowledge_store.py tests/test_evidence_resolver.py -v`

Expected: PASS for all precedence, filtering, conflict, category-only, overlay, source, hazard, policy, and Unknown cases.

```bash
git add server/evidence_resolver.py tests/test_evidence_resolver.py
git commit -m "feat: resolve reviewed evidence records"
```

### Task 6: Publish deterministic evidence coverage and release changes

**Files:**
- Create: `scripts/evidence_coverage.py`
- Create: `scripts/compare_evidence_coverage.py`
- Create: `packaging/evidence-coverage.schema.json`
- Create: `packaging/evidence-coverage-change.schema.json`
- Create: `tests/test_evidence_coverage.py`
- Modify: `scripts/knowledge_compiler.py`

**Interfaces:**
- Produces: `build_coverage(documents: EvidenceDocuments, content_sha256: str) -> dict[str, object]`
- Produces: `validate_release_floor(report: Mapping[str, object]) -> None`
- Produces: `compare_coverage(previous: Mapping[str, object] | None, current: Mapping[str, object]) -> dict[str, object]`
- Produces CLI: `python scripts/compare_evidence_coverage.py --current PATH (--previous PATH | --initial) --out PATH`

- [ ] **Step 1: Write failing closed-shape and floor tests**

```python
def test_coverage_has_the_closed_sorted_shape(valid_documents):
    report = build_coverage(valid_documents, "a" * 64)
    assert set(report) == {
        "schema_version", "bundle_version", "knowledge_content_sha256", "summary", "claims"
    }
    assert list(report["summary"]) == [
        "categories", "canonical_identities", "subtypes", "lifecycle_records",
        "industry_averages", "component_templates", "modern_overlays",
        "legacy_overlays", "hazard_records", "reviewed_claims", "unknown_claims",
    ]
    assert report["claims"] == sorted(
        report["claims"], key=lambda row: (row["category_id"], row["claim_kind"], row["claim_id"])
    )


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
```

- [ ] **Step 2: Run coverage tests and verify RED**

Run: `.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_evidence_coverage.py -v`

Expected: FAIL because the coverage modules and JSON schemas do not exist.

- [ ] **Step 3: Implement canonical full and change artifacts**

Each full claim row contains exactly `category_id`, `claim_kind`, `claim_id`, `evidence_level`, `source_state`, `source_ids`, and `unknown_reason`; `source_state` is `reviewed` or `unknown`. Serialize with sorted keys, no NaN, UTF-8, and one trailing newline.

The change artifact contains exactly `schema_version`, `from_bundle_version`, `to_bundle_version`, `added`, `removed`, `changed`, and `known_limitations`. `added` and `removed` are sorted claim keys. Each changed row contains `claim_key`, `before_source_state`, `after_source_state`, `before_evidence_level`, and `after_evidence_level`. Each limitation contains `claim_key` and `reason` and is derived from current Unknown rows rather than free-form release copy.

- [ ] **Step 4: Integrate the release floor before bundle promotion**

Call `validate_release_floor()` inside `compile_knowledge_bundle()` before writing computed metadata or promoting output. Hash the exact coverage bytes, store that hash as `coverage_sha256`, and verify that `knowledge_content_sha256` matches the database logical digest.

- [ ] **Step 5: Run coverage/compiler tests and commit**

Run: `.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_evidence_coverage.py tests/test_knowledge_compiler.py -v`

Expected: PASS for exact counts, each category floor, battery-bearing/free variants, deterministic bytes, initial comparison, changed comparison, schema rejection, and compiler failure preservation.

```bash
git add scripts/evidence_coverage.py scripts/compare_evidence_coverage.py scripts/knowledge_compiler.py packaging/evidence-coverage.schema.json packaging/evidence-coverage-change.schema.json tests/test_evidence_coverage.py
git commit -m "feat: publish evidence coverage artifacts"
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
    assert rules["urgent_hazard_specialist"].outcome == "specialist_handling"
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
git diff --exit-code -- reference/sources.yaml reference/device_components.yaml
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
- Produces templates `mouse_standard`, `mouse_modern_wireless`, and `mouse_legacy_ball`
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
        "battery_free", "battery_bearing"
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

Expected: PASS for the exact roster, four subtypes, three endurance records, broad range, three templates, battery variants, hazard provenance, and Unknown rows; missing sibling category directories do not affect this category-scoped gate.

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
- Produces templates `keyboard_standard`, `keyboard_modern_wireless`, and `keyboard_legacy_buckling_spring`
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
    assert {item.template_kind for item in keyboard_records.templates} >= {
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
- Produces templates `laptop_standard`, `laptop_modern_integrated`, and `laptop_legacy_serviceable`
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
    assert any(item.market_state == "legacy" for item in laptop_records.subtypes)
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
- Produces templates `phone_standard`, `phone_modern_integrated`, and `phone_legacy_removable_battery`
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
    assert all(item.endpoint_kind == "capacity_threshold" for item in phone_records.specific_lifecycles if "battery" in item.record_id)
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
- Produces templates `headphones_standard`, `headphones_modern_wireless`, and `headphones_legacy_wired`
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
        "battery_free", "battery_bearing"
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


def test_verifier_rejects_extra_or_symlinked_candidate_files(approved_candidate):
    candidate, approval, _manifest = approved_candidate
    (candidate / "unreviewed.json").write_text("{}")
    with pytest.raises(KnowledgeReleaseError, match="unavailable or incompatible"):
        verify_knowledge_release_inputs(candidate, approval)
```

- [ ] **Step 2: Run the handoff tests and verify RED**

Run: `.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_knowledge_release_inputs.py -v`

Expected: FAIL during collection because `scripts.knowledge_release` does not exist.

- [ ] **Step 3: Implement the closed approval trust record**

Accept exactly these top-level approval keys: `approval_schema_version`, `schema_version`, `bundle_version`, `identity_catalog_version`, `policy_revision`, `knowledge_sha256`, `content_sha256`, `coverage_sha256`, `coverage_change_sha256`, `corpus_counts`, `reviewed_by`, and `reviewed_on`. Require approval schema 1, knowledge schema 3, bundle `3.0.0`, catalog `1.0.0`, policy `2.0.0`, lowercase SHA-256 strings, a non-empty reviewer, and an ISO review date. `corpus_counts` has the exact summary keys emitted by Task 6 and positive integer values.

Resolve all paths strictly; reject symlinks, special files, path overlap, missing or extra candidate entries, malformed/non-canonical JSON, and changed bytes during verification. Open the database and coverage together through `KnowledgeStore` with the approved raw/logical/coverage/version expectations. Validate the change artifact against its closed schema, require `to_bundle_version == "3.0.0"`, require its current limitations to equal the coverage report's Unknown rows, and then return resolved absolute paths and hashes.

The approval file is the source-controlled trust record; rewriting artifact hashes alone cannot bless a swap. This verifier does not create or modify an app release manifest.

- [ ] **Step 4: Run handoff integrity tests and commit**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_knowledge_release_inputs.py tests/test_knowledge_store.py tests/test_evidence_coverage.py -q
.venv/bin/python -m py_compile scripts/knowledge_release.py
```

Expected: PASS for valid input, every single-artifact tamper, coordinated bundle/report swaps, extra files, symlinks, malformed approval values, version drift, and Unknown-limitation drift.

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

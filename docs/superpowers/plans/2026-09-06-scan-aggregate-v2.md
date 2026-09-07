# Versioned Scan Aggregate, Assessment Engine, and API v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace mutable assessment history with an offline `/api/v2` scan aggregate that preserves immutable machine evidence, revisioned user decisions, frozen evidence/policy snapshots, private media, and truthful degraded operation.

**Architecture:** Put closed JSON/domain contracts at the service edge, coordinate the three analysis capabilities without coupling their failures, resolve immutable evidence before canonical-scope calculations, and use a policy-only evidence variant for Unknown identity. Persist both variants as append-only user and assessment revisions through a switchable SQLite/session repository. A thin Flask blueprint delegates commands to `ScanService`; local-loopback authorization, privacy cleanup, and `/api/v1` compatibility remain explicit adapters around that core.

**Tech Stack:** Python 3.11, Flask 3.1.3, SQLite, Pillow 12.3.0, dataclasses/enums/protocols, pytest 9.1.1

**Spec:** `docs/superpowers/specs/2026-09-06-ewaste-evidence-condition-prototype-design.md`

## Dependency Contract

This slice starts after Slice 1, `docs/superpowers/plans/2026-09-06-evidence-bundle-resolver.md`, lands these exact public modules:

- `server/evidence_types.py`: `EvidenceLevel`, `ResolutionTier`, `CanonicalIdentityScope`, `LifecycleRequest`, `CategorySnapshot`, `SourceSnapshot`, `IdentityRecordSnapshot`, `LifecycleRecordSnapshot`, `ResolutionStep`, `LifecycleResolution`, `ComponentAssociationSnapshot`, `ComponentResolution`, `HazardSnapshot`, `HazardResolution`, `PolicyRuleSnapshot`, `PolicyBundleSnapshot`, `RecommendationValue`, `BundleStamp`, and `ResolvedEvidence`;
- `server/knowledge_store.py`: `KnowledgeStore(database_path: Path, coverage_path: Path | None = None, *, expected_sha256: str | None = None, expected_content_sha256: str | None = None, expected_coverage_sha256: str | None = None, expected_schema_version: int | None = None, expected_bundle_version: str | None = None, expected_identity_catalog_version: str | None = None, expected_policy_revision: str | None = None)`, `.manifest`, `.search_identities(text, category_id=None, limit=20)`, `.get_identity(identity_id)`, `.identity_scope(identity_id)`, and `.policy_bundle() -> PolicyBundleSnapshot`; and
- `server/evidence_resolver.py`: `EvidenceResolver(store: KnowledgeStore)`, `.resolve_lifecycle(scope: CanonicalIdentityScope, request: LifecycleRequest) -> LifecycleResolution`, `.resolve_components(scope: CanonicalIdentityScope) -> ComponentResolution`, `.resolve_hazards(scope: CanonicalIdentityScope) -> HazardResolution`, and `.resolve(scope: CanonicalIdentityScope, request: LifecycleRequest) -> ResolvedEvidence`.

`BundleStamp` is copied without renaming or flattening and has exactly `schema_version`, `bundle_version`, `identity_catalog_version`, `policy_revision`, and `content_sha256`. For canonical-scope assessment, `ResolvedEvidence` supplies `bundle`, `lifecycle`, `components`, `hazards`, and `policy`. For Unknown assessment, `KnowledgeStore.manifest.stamp` and `KnowledgeStore.policy_bundle()` supply only the frozen bundle/policy inputs; no `ResolvedEvidence` is constructed. The assessment engine never performs a database read. Every evidence record already contains complete `SourceSnapshot` tuples, so this slice must never persist a bare source ID as if it were a frozen citation.

## Global Constraints

- Released category IDs are exactly `0301_computer_mouse`, `0301_keyboard`, `0303_laptop`, `0306_mobile_phone`, and `0401_headphones`.
- Machine evidence is written once and carries exact category-model, identity-engine, condition-engine, preprocessing, rubric, artifact, and confidence provenance.
- Category, identity, and condition each report `ready`, `low_confidence`, or `unavailable`; one failure does not erase another valid result.
- Only an explicit catalog-backed identity or category-only decision creates a `CanonicalIdentityScope`. Unknown and free-form notes bypass `EvidenceResolver`, but an Unknown decision may still freeze a policy-only assessment whose scope is null, lifecycle/components/hazards are explicitly unavailable, visible condition is preserved, and the bundled `unknown_identity_more_information` rule returns `more_information_needed`.
- User decisions and observations are append-only revisions. A canonical-scope assessment revision freezes its user revision, unchanged `ResolvedEvidence`, deterministic calculation, and embedded `BundleStamp`. An Unknown-identity assessment revision freezes its user revision, visible-condition decision, explicit unavailable lifecycle/components/hazards states, `BundleStamp`, `PolicyBundleSnapshot`, and deterministic `more_information_needed` decision without constructing `ResolvedEvidence`.
- Every GET is read-only. Opening Summary or Components never creates, refreshes, or repairs an assessment.
- Service-life text preserves calculated intervals above 100%; only the visualization interval is bounded to `[0, 100]`. A capacity-threshold endpoint never becomes percent service life elapsed.
- Visible condition never widens, narrows, or multiplies a lifecycle interval. The Slice 1 `PolicyBundleSnapshot` contains recommendation rules, not sourced numeric-adjustment records.
- Hazard-triggered specialist handling takes precedence over optimistic lifecycle or reuse rules.
- Recommendations are exactly `reuse`, `repair`, `parts_recovery`, `specialist_handling`, `certified_recycling`, and `more_information_needed`.
- Legacy migration preserves real prediction/provenance and an explicit confirmation as category-only; it invents no OCR, condition, lifecycle, component, hazard, timestamp, or citation fact.
- New and migrated scans retain no original image. History may retain one app-managed JPEG thumbnail; OCR transcripts, bounding boxes, serial-like strings, and absolute client paths are never persisted.
- Delete hides a scan immediately and offers one session-local ten-second Undo token. Expiry, crash recovery, and shutdown purge it. Clear History is explicitly confirmed, immediate, and has no Undo.
- A history-store failure leaves analysis available with `history_saved=false`; retry affects future scans and never silently persists earlier transient scans.
- The desktop service binds only to `127.0.0.1` and requires a fresh per-launch capability key. The key is never embedded in HTML or JavaScript.
- `/api/v1` remains a tested adapter until packaged parity passes; collection-only `/ingest` behavior in `server/app.py` remains available to admin training workflows.

## Closed Wire Contracts

`POST /api/v2/scans` is multipart with exactly one `image` file and one required `idempotency_key` form field. The key is a canonical, non-nil RFC 4122 UUID. A new command returns HTTP 201 with this top-level shape:

```json
{
  "scan": {
    "scan_id": "uuid",
    "created_at": "RFC-3339 UTC",
    "source": "mac",
    "thumbnail_url": "/api/v2/scans/uuid/thumbnail",
    "history_saved": true
  },
  "analysis": {
    "category": {
      "state": "ready",
      "prediction": {"class_name": "0303_laptop", "unu_key": "0303", "confidence": 0.91, "low_confidence": false, "topk": [{"class_name": "0303_laptop", "confidence": 0.91}]},
      "provenance": {"engine_id": "category_onnx", "model_id": "category-model-id", "architecture": "efficientnet_b0", "preprocessing_version": "rgb-224-v1", "artifact_sha256": "0000000000000000000000000000000000000000000000000000000000000000", "schema_version": 1}
    },
    "identity": {"state": "unavailable", "suggestions": [], "provenance": {"engine_id": "identity_unavailable", "version": "1"}, "unavailable_reason": "not_configured"},
    "condition": {"state": "unavailable", "suggested_grade": "unknown", "findings": [], "confidence": null, "image_sufficiency": "unknown", "scope_statement": "Visible exterior only", "provenance": {"engine_id": "manual_condition", "rubric_version": "visible-condition-v1", "guidance_content_sha256": "0000000000000000000000000000000000000000000000000000000000000000"}, "unavailable_reason": "manual_only", "manual_guidance": {"required": true, "url": "/api/v2/condition-rubric", "rubric_version": "visible-condition-v1", "content_sha256": "0000000000000000000000000000000000000000000000000000000000000000"}}
  },
  "user_state": {
    "revision_id": "uuid",
    "sequence": 0,
    "created_at": "RFC-3339 UTC",
    "identity_decision": {"kind": "unknown", "unverified_model_note": null},
    "canonical_scope": null,
    "condition_decision": {"grade": "unknown", "findings": [], "image_sufficiency": "unknown", "note": null},
    "observations": {
      "age_months": null,
      "full_charge_cycles": null,
      "operational_state": "unknown",
      "issue_flags": {"overheating": false, "odor": false, "swelling_or_battery_damage": false, "recall": false, "notes": null},
      "component_decisions": {}
    }
  },
  "assessment": null
}
```

Fresh user revisions always carry an RFC-3339 UTC `created_at`; a migrated legacy confirmation returns `created_at=null` because v1 did not record when confirmation occurred.

Every serialized `user_state` includes `canonical_scope`. It is `null` only for an Unknown decision. For category-only, confirmed, and edited decisions it is a server-authored object with every field present:

```json
{
  "category_id": "0303_laptop",
  "subtype_id": null,
  "family_id": null,
  "model_id": null,
  "variant_ids": [],
  "model_year": null,
  "applicable_on": null
}
```

For confirmed/edited identities, `KnowledgeStore.identity_scope(identity_id)` supplies those values. For category-only, only `category_id` is non-null. The API never omits the object, accepts client-authored scope fields, or substitutes free-form text.

`IdentityDecisionInput` is a closed discriminated union. `expected_user_revision_id` is a sibling request field, not part of the decision:

```text
confirmed     = {kind:"confirmed", identity_id:string}
edited        = {kind:"edited", identity_id:string, unverified_model_note:string|null}
category_only = {kind:"category_only", category_id:ReleasedCategoryId, unverified_model_note:string|null}
unknown       = {kind:"unknown", unverified_model_note:string|null}
```

For `confirmed` and `edited`, the service calls `KnowledgeStore.get_identity(identity_id)` and derives every `CanonicalIdentityScope` field. It rejects client-supplied category, subtype, family, model, variant, year, and date fields. Free-form text is display-only `unverified_model_note` and is never resolved. `category_only` creates `CanonicalIdentityScope(category_id=category_id)` and can reach only industry-average lifecycle evidence and the base component template. `unknown` has no canonical scope.

`PUT /api/v2/scans/{id}/observations` accepts exactly:

```json
{
  "expected_user_revision_id": "uuid",
  "condition_decision": {
    "grade": "excellent|good|fair|poor|critical|unknown",
    "findings": [{"kind": "visible_crack", "severity": "absent"}],
    "image_sufficiency": "sufficient|insufficient|unknown",
    "note": null
  },
  "observations": {
    "age_months": {"lower": 0, "upper": 1200},
    "full_charge_cycles": {"lower": 0, "upper": 10000000},
    "operational_state": "unknown|working|intermittent|not_working",
    "issue_flags": {"overheating": false, "odor": false, "swelling_or_battery_damage": false, "recall": false, "notes": null},
    "component_decisions": {
      "component-id": {
        "status": "present|not_present|unknown",
        "note": null,
        "lifecycle_scenario": {"metric": "metric-id", "unit": "unit-id", "lower": 0, "upper": 1, "citation": null}
      }
    }
  }
}
```

Either numeric interval may be `null`; a component `lifecycle_scenario` may be `null`. User-entered component ranges are labeled `User-provided · Not independently verified`, remain separate from sourced results, and never suppress hazards. Notes are trimmed, nullable, and limited to 500 Unicode code points. Machine findings carry confidence; user findings never do.

Idempotency keys are required in exactly the three create-style mutation bodies below. PUT identity/observation commands instead require `expected_user_revision_id` compare-and-swap and reject an `idempotency_key` field.

```text
POST /api/v2/scans multipart:
  image=binary image file part
  idempotency_key=canonical non-nil RFC 4122 UUID string

POST /api/v2/scans/{id}/assessment-revisions JSON:
  {"user_revision_id":"UUID","lifecycle_request":{"subject":"device","endpoint":"service_life","metric":"elapsed_time","unit":"years"},"idempotency_key":"UUID"}

POST /api/v2/scans/{id}/reassess JSON:
  {"base_assessment_revision_id":"UUID","user_revision_id":"UUID","lifecycle_request":{"subject":"device","endpoint":"service_life","metric":"elapsed_time","unit":"years"},"idempotency_key":"UUID"}
```

All listed fields are required and extra fields are rejected. The key is scoped to the route plus scan aggregate: replaying the same canonical body returns HTTP 200 and the original immutable result; reusing the key with a different normalized image hash, user revision, lifecycle request, or base assessment revision returns HTTP 409. Summary and Components accept optional `assessment_revision_id` query parameters and only deserialize the requested frozen revision.

Slice 3 owns and registers `GET /api/v2/condition-rubric`; its canonical guidance hash replaces the illustrative all-zero hash above. The manual capability's `manual_guidance` route/version/hash is required in the first-release scan response, and Slice 4 consumes that server-owned rubric instead of hard-coding grade copy.

## File Structure

| File | Responsibility |
|---|---|
| `server/scan_contract.py` | Closed enums, immutable aggregate types, strict JSON decoding, and public serialization |
| `server/analysis.py` | Independent capability protocols, provenance, redaction, and one-image coordinator |
| `server/assessment_engine.py` | Pure lifecycle calculation, policy evaluation, safety precedence, and frozen output types |
| `server/scan_store.py` | v2 schema, conservative migration, append-only repositories, transient fallback, and tombstones |
| `server/scan_service.py` | Command orchestration across catalog, resolver, assessment engine, and repository |
| `server/v2_api.py` | Thin `/api/v2` Flask blueprint and closed error mapping |
| `server/local_capability.py` | Per-launch loopback key generation, cookie bootstrap, and request authorization |
| `server/history.py` | `/api/v1` storage compatibility facade over v2 data |
| `server/desktop_app.py` | Dependency registration, v1 route adapters, and shutdown hooks |
| `server/app.py` | Legacy product-route adapter while preserving collection-only `/ingest` |
| `desktop/main.py` | Degraded startup assembly, capability bootstrap URL, retry, and teardown |
| `tests/test_scan_contract.py` | Closed payload, redaction, provenance, and serialization tests |
| `tests/test_analysis_coordinator.py` | Capability isolation and normalized-image lifetime tests |
| `tests/test_assessment_engine_v2.py` | Interval, endpoint, policy, source, and safety tests |
| `tests/test_scan_store.py` | Schema, migration, immutability, concurrency, fallback, and deletion tests |
| `tests/test_scan_service.py` | Resolver/service command and stale-revision tests |
| `tests/test_v2_api.py` | Route, status, response, and read-only GET tests |
| `tests/test_local_capability.py` | Bootstrap, cookie/header, denial, and key-rotation tests |
| `tests/test_privacy_retention.py` | Thumbnail, OCR, original, tombstone, and restart cleanup tests |

---

### Task 1: Freeze scan contracts and isolate the three analysis capabilities

**Files:**
- Create: `server/scan_contract.py`
- Create: `server/analysis.py`
- Create: `tests/test_scan_contract.py`
- Create: `tests/test_analysis_coordinator.py`

**Interfaces:**
- `CapabilityState = ready|low_confidence|unavailable`
- `IdentityDecisionKind = confirmed|edited|category_only|unknown`
- `VisibleGrade = excellent|good|fair|poor|critical|unknown`
- `ImageSufficiency = sufficient|insufficient|unknown`
- `OperationalState = unknown|working|intermittent|not_working`
- Consumes `RecommendationValue = reuse|repair|parts_recovery|specialist_handling|certified_recycling|more_information_needed` from `server.evidence_types`
- `FindingKind = visible_crack|deformation|missing_exterior_part|corrosion_like_appearance|surface_wear`
- `FindingSeverity = absent|minor|moderate|major|severe`
- `AnalysisCoordinator(category_analyzer, identity_analyzer, condition_analyzer).analyze(image: Image.Image) -> MachineEvidence`
- `decode_identity_decision(raw: object) -> IdentityDecisionCommand`
- `decode_observation_update(raw: object) -> ObservationCommand`
- `decode_idempotency_key(raw: object) -> str`
- `machine_evidence_to_dict(value: MachineEvidence) -> dict[str, object]`

- [ ] **Step 1: Write failing contract, redaction, and failure-isolation tests**

In `tests/test_scan_contract.py`, define concrete values for all five category IDs and assert each discriminated-union shape. Assert `confirmed`/`edited` reject `category_id`, `model_id`, and unknown keys; category-only rejects an unrecognized ID; unknown preserves a bounded note but has no scope. Assert booleans are not accepted as integers, non-finite confidence is rejected, and serial-like suggestions such as `C02X1234ABCD` never serialize. Assert `decode_idempotency_key` accepts a canonical non-nil UUID and rejects missing, nil, uppercase/noncanonical, boolean, and non-UUID values.

In `tests/test_analysis_coordinator.py`, use three recording analyzers and a 32×24 RGB image. Assert all analyzers receive independent open image copies, exactly one capability becomes `unavailable` when its analyzer raises, and the other two results and provenance remain unchanged.

```python
def test_unknown_identity_never_creates_a_scope():
    command = decode_identity_decision(
        {
            "expected_user_revision_id": "2d2d8d8c-0b87-4baf-80ef-929614e4b7f5",
            "decision": {"kind": "unknown", "unverified_model_note": "Model text unclear"},
        }
    )
    assert command.decision.kind is IdentityDecisionKind.UNKNOWN
    assert command.decision.unverified_model_note == "Model text unclear"

def test_condition_failure_preserves_category_and_identity():
    result = coordinator(condition_error=RuntimeError("condition failed")).analyze(
        Image.new("RGB", (32, 24), "white")
    )
    assert result.category.state is CapabilityState.READY
    assert result.identity.state is CapabilityState.READY
    assert result.condition.state is CapabilityState.UNAVAILABLE
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_scan_contract.py tests/test_analysis_coordinator.py -v
```

Expected: FAIL during import because `server.scan_contract` and `server.analysis` do not exist.

- [ ] **Step 3: Implement immutable types, strict decoders, and the coordinator**

Use frozen dataclasses and string enums. Reject unknown keys at every nesting level, NUL/control characters, notes longer than 500 Unicode code points, unsupported issue keys, reversed/out-of-range intervals, confidence outside `[0,1]`, and client-authored provenance. Keep separate `MachineVisibleFinding(kind, severity, confidence)` and `UserVisibleFinding(kind, severity)` types so user corrections cannot impersonate model confidence.

Define capability protocols whose exceptions are caught independently:

```python
class CategoryAnalyzer(Protocol):
    def analyze(self, image: Image.Image) -> CategoryCapability:
        raise NotImplementedError

class IdentityAnalyzer(Protocol):
    def analyze(self, image: Image.Image, category_id: str | None) -> IdentityCapability:
        raise NotImplementedError

class ConditionAnalyzer(Protocol):
    def analyze(self, image: Image.Image) -> ConditionCapability:
        raise NotImplementedError

class AnalysisCoordinator:
    def __init__(self, category_analyzer: CategoryAnalyzer, identity_analyzer: IdentityAnalyzer, condition_analyzer: ConditionAnalyzer):
        raise NotImplementedError
    def analyze(self, image: Image.Image) -> MachineEvidence:
        raise NotImplementedError
```

The coordinator consumes one already-normalized image, makes scoped copies with context managers, sanitizes exception reasons to closed codes, and returns all three capabilities. It does not persist, resolve evidence, or calculate an assessment.

- [ ] **Step 4: Run contract/coordinator tests and compile the modules**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_scan_contract.py tests/test_analysis_coordinator.py -v
.venv/bin/python -m py_compile server/scan_contract.py server/analysis.py
```

Expected: PASS for every closed union, adversarial scalar, redaction case, capability failure, and image-close assertion.

- [ ] **Step 5: Commit the aggregate boundary**

```bash
git add server/scan_contract.py server/analysis.py tests/test_scan_contract.py tests/test_analysis_coordinator.py
git commit -m "feat: define versioned scan contracts"
```

### Task 2: Replace legacy lifecycle arithmetic with a pure assessment engine

**Files:**
- Create: `server/assessment_engine.py`
- Create: `tests/test_assessment_engine_v2.py`
- Modify: `tests/test_lifecycle.py`

**Interfaces:**
- `CanonicalAssessmentEvidence(resolved_evidence: ResolvedEvidence)` with discriminator `kind="resolved"`
- `UnknownIdentityAssessmentEvidence(bundle: BundleStamp, policy: PolicyBundleSnapshot, lifecycle: UnavailableEvidenceState, components: UnavailableEvidenceState, hazards: UnavailableEvidenceState)` with discriminator `kind="unknown_identity"`; every unavailable state has `status="unavailable"` and `reason="unknown_identity"`
- `AssessmentEvidence = CanonicalAssessmentEvidence | UnknownIdentityAssessmentEvidence`
- `AssessmentSnapshot.evidence: AssessmentEvidence`
- `AssessmentEngine.assess(scope: CanonicalIdentityScope, observations: UserObservations, visible_condition: ConditionDecision, resolved_evidence: ResolvedEvidence) -> AssessmentSnapshot`
- `AssessmentEngine.assess_unknown_identity(observations: UserObservations, visible_condition: ConditionDecision, policy: PolicyBundleSnapshot, bundle: BundleStamp) -> AssessmentSnapshot`
- `derive_service_life(elapsed_time: NumericInterval, service_life: NumericInterval) -> LifecycleCalculation`
- `derive_threshold_progress(usage: NumericInterval, record: LifecycleRecordSnapshot) -> ThresholdProgress`
- `evaluate_recommendation(policy: PolicyBundleSnapshot, observations: UserObservations, visible_condition: ConditionDecision, resolved_evidence: ResolvedEvidence) -> RecommendationDecision`

- [ ] **Step 1: Write failing arithmetic, endpoint, safety, and provenance tests**

Cover these exact cases in `tests/test_assessment_engine_v2.py`:

- a record with `endpoint="service_life"`, `metric="elapsed_time"`, `unit="years"`, and range 1–2 years combined with elapsed age 3–4 years produces textual elapsed interval 150–400%, visualization interval 100–100%, and remaining interval 0–0 years;
- a `capacity_threshold` record at 80% capacity produces threshold progress only, with `percent_service_life_elapsed=None`;
- absent or incompatible usage produces Unknown with an explicit `unknown_reason`;
- visible grades Good and Critical produce identical lifecycle math when the frozen policy has no condition-adjustment rule;
- a user component scenario remains separate and is labeled unverified;
- a triggered hazard chooses `specialist_handling` even when lifecycle permits `reuse`;
- for every canonical-scope assessment, each selected lifecycle, component, hazard, policy, resolution-trace, and source snapshot equals the object supplied in `ResolvedEvidence`;
- Unknown identity calls `assess_unknown_identity`, preserves the visible-condition decision, records `scope=None`, freezes `policy` and `bundle`, marks lifecycle/components/hazards unavailable with reason `unknown_identity`, and selects the exact `unknown_identity_more_information` policy rule and `more_information_needed` outcome;
- all six recommendation values serialize and the legacy values `likely_reusable`, `diagnostic_test`, `repair_assessment`, `recycle`, and `unknown` are rejected by v2 decoding.

```python
def test_service_life_keeps_text_above_one_hundred_percent():
    value = derive_service_life(NumericInterval(3, 4), NumericInterval(1, 2))
    assert value.textual_percent_elapsed == NumericInterval(150, 400)
    assert value.visual_percent_elapsed == NumericInterval(100, 100)
    assert value.remaining == NumericInterval(0, 0)

def test_threshold_endpoint_is_not_percent_service_life(snapshot_factory):
    result = AssessmentEngine().assess(**snapshot_factory(endpoint="capacity_threshold"))
    assert result.lifecycle.threshold_progress is not None
    assert result.lifecycle.percent_service_life_elapsed is None

def test_unknown_identity_uses_policy_without_identity_resolution(policy, bundle):
    result = AssessmentEngine().assess_unknown_identity(
        observations(), condition_decision(VisibleGrade.FAIR), policy, bundle
    )
    assert result.scope is None
    assert isinstance(result.evidence, UnknownIdentityAssessmentEvidence)
    assert not hasattr(result.evidence, "resolved_evidence")
    assert result.visible_condition.grade is VisibleGrade.FAIR
    assert result.evidence.lifecycle.reason == "unknown_identity"
    assert result.recommendation.outcome is RecommendationValue.MORE_INFORMATION_NEEDED
    assert result.recommendation.applied_rule_ids == ("unknown_identity_more_information",)
```

- [ ] **Step 2: Run assessment/lifecycle tests and verify RED**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_assessment_engine_v2.py tests/test_lifecycle.py -v
```

Expected: FAIL because the v2 engine does not exist and `server/lifecycle.py` still clamps source-derived intervals and applies unsourced condition widening.

- [ ] **Step 3: Implement deterministic calculation and policy precedence**

For a compatible `service_life` record and `elapsed_time` observation in the same unit, calculate outward intervals exactly as:

```python
textual = NumericInterval(
    lower=floor(100 * elapsed_time.lower / service_life.upper),
    upper=ceil(100 * elapsed_time.upper / service_life.lower),
)
visual = NumericInterval(min(100, textual.lower), min(100, textual.upper))
remaining = NumericInterval(
    max(0, service_life.lower - elapsed_time.upper),
    max(0, service_life.upper - elapsed_time.lower),
)
```

Keep the unchanged source bounds beside every derived value. Reject zero/negative life bounds and metric/unit mismatches. Treat capacity threshold and endurance endpoints as their own result variants. Do not perform condition arithmetic: `PolicyRuleSnapshot` contains recommendation predicates/outcomes and no sourced numeric-adjustment record. Condition and operational state may select a recommendation rule, but the source-derived interval remains unchanged.

Return an immutable `AssessmentSnapshot` whose `evidence` is the closed discriminated union above. `assess` stores the supplied `ResolvedEvidence` object unchanged inside `CanonicalAssessmentEvidence`. `assess_unknown_identity` stores `BundleStamp`, `PolicyBundleSnapshot`, and three explicit unavailable states inside `UnknownIdentityAssessmentEvidence`; it requires the frozen bundle's `unknown_identity_more_information` rule, performs no identity/lifecycle/component/hazard lookup, and never constructs a `CanonicalIdentityScope` or `ResolvedEvidence`. Both variants also retain user observations, visible-condition decision, calculations, recommendation decision, applied policy rule IDs, assumptions, and Unknown reasons. Evaluate applicable hazard triggers before all reuse/repair/recovery rules. Do not import `KnowledgeStore` or `EvidenceResolver` in this module.

Turn `server/lifecycle.py` into a narrow v1 compatibility adapter in Task 7; for now keep old imports passing while moving all new calculations to `assessment_engine.py`.

- [ ] **Step 4: Run arithmetic, policy, and legacy characterization tests**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_assessment_engine_v2.py tests/test_lifecycle.py -v
.venv/bin/python -m py_compile server/assessment_engine.py
```

Expected: PASS, including >100% service-life text, separately bounded visualization, endpoint separation, no unsourced condition adjustment, safety precedence, the policy-only Unknown-identity assessment, and exact source/bundle preservation.

- [ ] **Step 5: Commit the v2 assessment engine**

```bash
git add server/assessment_engine.py tests/test_assessment_engine_v2.py tests/test_lifecycle.py
git commit -m "feat: add sourced assessment policy engine"
```

### Task 3: Migrate history into an immutable, append-only scan repository

**Files:**
- Create: `server/scan_store.py`
- Create: `tests/test_scan_store.py`
- Modify: `tests/test_history.py`

**Interfaces:**
- `SqliteScanRepository(database_path: Path, media_dir: Path, *, clock: Callable[[], datetime])`
- `SessionScanRepository(*, clock: Callable[[], datetime])`
- `ScanRepositoryRouter(session: SessionScanRepository, persistent: SqliteScanRepository | None)`
- `create_scan(machine_evidence: MachineEvidence, thumbnail: Image.Image | None, source: ScanSource, *, idempotency_key: str, command_sha256: str) -> ScanRecord`
- `append_user_state(scan_id: str, value: UserState, *, expected_revision_id: str) -> UserStateRevision`
- `append_assessment(scan_id: str, value: AssessmentSnapshot, *, user_revision_id: str, idempotency_key: str, command_sha256: str, base_assessment_revision_id: str | None) -> AssessmentRevision`
- `get_scan(scan_id)`, `list_scans()`, `get_user_state(scan_id, revision_id=None)`, `get_assessment(scan_id, revision_id)`, and `list_assessments(scan_id)`
- `ScanRepositoryRouter.activate_persistent(repository: SqliteScanRepository) -> None`

- [ ] **Step 1: Write failing schema, migration, append-only, and degraded-store tests**

Build a real pre-v2 SQLite fixture using the current `scans`, `assessments`, and `pending_media_deletions` DDL. Insert a model prediction with release provenance, a class confirmation, one managed thumbnail, one managed original, and a legacy assessment. Assert:

- first open migrates transactionally and second open is byte-for-byte/idempotently equivalent;
- the original is queued and then deleted, while the managed thumbnail remains;
- the prediction/provenance are exact, confirmation becomes category-only, identity and condition are unavailable, and no fabricated timestamps/sources appear;
- the legacy assessment is returned as `kind="legacy_v1"`, not coerced into an `AssessmentSnapshot`;
- SQL triggers reject updates to revision payloads while aggregate deletion still cascades;
- stale user revision and duplicate competing writes return `RevisionConflict`;
- replaying the same create/assessment/reassessment UUID plus canonical command hash returns the original record, while a different command hash for that key raises `IdempotencyConflict`;
- canonical assessment JSON round-trips with `evidence.kind="resolved"` and the complete unchanged `ResolvedEvidence`; Unknown assessment JSON round-trips with `evidence.kind="unknown_identity"`, bundle/policy and three unavailable states, and contains no `resolved_evidence` key;
- a `ScanRepositoryRouter` with no persistent store marks new scans `history_saved=false`; after `activate_persistent`, new scans persist but the earlier transient scan remains session-only.

```python
def test_revision_rows_cannot_be_updated(repository):
    scan = repository.create_scan(
        machine_evidence(), thumbnail(), ScanSource.MAC,
        idempotency_key="6ce0cab7-6369-47b7-8541-af6574aab6c8",
        command_sha256="a" * 64,
    )
    with pytest.raises(sqlite3.IntegrityError, match="immutable user revision"):
        repository.execute_for_test(
            "UPDATE user_state_revisions SET observations_json='{}' WHERE scan_id=?",
            (scan.scan_id,),
        )

def test_retry_does_not_silently_save_transient_scans(tmp_path):
    router = ScanRepositoryRouter(SessionScanRepository(clock=fixed_clock), None)
    transient = router.create_scan(
        machine_evidence(), None, ScanSource.MAC,
        idempotency_key="c00f866d-3996-4462-a907-a6441978e0f3",
        command_sha256="b" * 64,
    )
    router.activate_persistent(SqliteScanRepository(tmp_path / "history.sqlite", tmp_path / "media", clock=fixed_clock))
    persisted = router.create_scan(
        machine_evidence(), thumbnail(), ScanSource.MAC,
        idempotency_key="f4f78fa5-4a43-4d35-8a63-b5193083cba8",
        command_sha256="c" * 64,
    )
    assert router.get_scan(transient.scan_id).history_saved is False
    assert router.get_scan(persisted.scan_id).history_saved is True
```

- [ ] **Step 2: Run repository/history tests and verify RED**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_scan_store.py tests/test_history.py -v
```

Expected: FAIL because the v2 tables, append-only revisions, conservative migration, and session repository do not exist.

- [ ] **Step 3: Implement the schema and transactional migration**

Inside one `BEGIN IMMEDIATE` migration, rename old tables to `v1_scans` and `v1_assessments`, then create:

```text
history_metadata(key PRIMARY KEY, value NOT NULL)
scans(scan_id PRIMARY KEY, created_at, source, machine_evidence_json, thumbnail_name, creation_idempotency_key UNIQUE, creation_command_sha256, deleted_at, migrated_from_v1)
user_state_revisions(scan_id REFERENCES scans ON DELETE CASCADE, revision_id UNIQUE, sequence, created_at TEXT, attribution TEXT NOT NULL, identity_decision_json, canonical_scope_json, condition_decision_json, observations_json, PRIMARY KEY(scan_id,sequence))
assessment_revisions(scan_id REFERENCES scans ON DELETE CASCADE, assessment_revision_id UNIQUE, sequence, created_at, user_revision_id, lifecycle_request_json, snapshot_json, bundle_content_sha256, base_assessment_revision_id, idempotency_key, command_sha256, PRIMARY KEY(scan_id,sequence), UNIQUE(scan_id,idempotency_key))
legacy_assessments(scan_id PRIMARY KEY REFERENCES scans ON DELETE CASCADE, legacy_json, migrated_at)
pending_media_deletions(scan_id, media_name PRIMARY KEY)
```

Add triggers that abort updates to `machine_evidence_json`, immutable scan provenance, all user-state payload columns, all assessment payload columns, and legacy JSON. Root `deleted_at` is the only mutable aggregate field. Enable foreign keys on every connection and use compare-and-swap under `BEGIN IMMEDIATE` for sequence allocation.

Migrate a v1 prediction verbatim under category machine evidence. Preserve only real model provenance. Map a valid saved class confirmation to `{kind:"category_only",category_id:legacy_confirmation["accepted_class_name"]}`, set `attribution="legacy_user"`, and set `created_at=null` because the old row has no confirmation timestamp. Otherwise create an Unknown system-default state at the scan creation time without claiming a user decision. Mark identity and condition unavailable. Store an old assessment unchanged in `legacy_assessments` and expose it read-only. Accept only managed media basenames matching the existing 32-hex-character naming policy; remove unsafe absolute references without unlinking external paths. Journal an existing managed original for deletion after commit.

Write managed thumbnails to a sibling temporary name, fsync, rename, then commit the row. On rollback, remove only files created by that operation. Never write or retain an original.

- [ ] **Step 4: Run migration, concurrency, and reopen tests**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_scan_store.py tests/test_history.py -v
.venv/bin/python -m py_compile server/scan_store.py
```

Expected: PASS for fresh schema, every legacy case, failure injection before/after commit, repeated migration, competing writers, immutable triggers, transient fallback, and media-path containment.

- [ ] **Step 5: Commit immutable persistence**

```bash
git add server/scan_store.py tests/test_scan_store.py tests/test_history.py
git commit -m "feat: persist immutable scan revisions"
```

### Task 4: Orchestrate catalog decisions, evidence resolution, assessment, and reassessment

**Files:**
- Create: `server/scan_service.py`
- Create: `tests/test_scan_service.py`

**Interfaces:**
- `ScanService(repository: ScanRepositoryRouter, analysis_coordinator: AnalysisCoordinator, knowledge_store: KnowledgeStore | None, evidence_resolver: EvidenceResolver | None, assessment_engine: AssessmentEngine)`
- `create_scan(image: Image.Image, source: ScanSource, idempotency_key: str) -> ScanAggregateView`
- `analyze_image(image: Image.Image) -> MachineEvidence`
- `create_scan_from_analysis(image: Image.Image, machine_evidence: MachineEvidence, source: ScanSource, idempotency_key: str) -> ScanAggregateView`
- `put_identity_decision(scan_id: str, command: IdentityDecisionCommand) -> UserStateRevision`
- `put_observations(scan_id: str, command: ObservationCommand) -> UserStateRevision`
- `create_assessment(scan_id: str, command: AssessmentCommand) -> AssessmentRevision`
- `reassess(scan_id: str, command: ReassessCommand) -> ReassessmentResult`
- `get_summary(scan_id: str, assessment_revision_id: str | None) -> SummaryView`
- `get_components(scan_id: str, assessment_revision_id: str | None) -> ComponentsView`
- `search_identities(text: str, category_id: str | None, limit: int) -> CatalogSearchResult`

- [ ] **Step 1: Write failing command-orchestration and degraded-evidence tests**

Use recording fakes with real Slice 1 dataclasses. Assert:

- confirmed/edited identity loads exactly one catalog identity and uses its server-derived `CanonicalIdentityScope`;
- category-only constructs only `CanonicalIdentityScope(category_id=command.decision.category_id)`;
- Unknown never calls `EvidenceResolver` or identity/lifecycle/component/hazard queries, but `create_assessment` reads `KnowledgeStore.manifest.stamp` and `KnowledgeStore.policy_bundle()`, then freezes a policy-only assessment through `AssessmentEngine.assess_unknown_identity`;
- assessment resolution happens before the repository transaction, then append compare-and-swap rejects a changed user revision;
- resolver output is passed unchanged to `AssessmentEngine.assess`;
- reassess against a different bundle creates a sibling revision and a field-by-field comparison while the original bytes remain unchanged;
- absent/corrupt knowledge service leaves scan/condition/category usable, catalog and evidence operations return scoped unavailable results, and `retry_evidence()` can install a later `KnowledgeStore`/`EvidenceResolver`;
- GET Summary and Components cause zero repository writes and zero resolver calls.

```python
def test_unknown_identity_freezes_more_information_without_resolution(service, recording_resolver):
    revision = service.put_identity_decision(scan_id, unknown_identity_command())
    created = service.create_assessment(scan_id, assessment_command(revision.revision_id))
    assert recording_resolver.calls == []
    assert created.snapshot.scope is None
    assert created.snapshot.evidence.kind == "unknown_identity"
    assert created.snapshot.evidence.lifecycle.reason == "unknown_identity"
    assert created.snapshot.recommendation.outcome is RecommendationValue.MORE_INFORMATION_NEEDED

def test_assessment_uses_only_resolved_snapshot(service, resolved_evidence, recording_engine):
    created = service.create_assessment(scan_id, assessment_command(user_revision_id))
    assert recording_engine.calls[0].resolved_evidence == resolved_evidence
    assert created.snapshot.evidence.kind == "resolved"
    assert created.snapshot.evidence.resolved_evidence is resolved_evidence
```

- [ ] **Step 2: Run service/engine tests and verify RED**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_scan_service.py tests/test_assessment_engine_v2.py -v
```

Expected: FAIL because `ScanService` does not exist.

- [ ] **Step 3: Implement validate-resolve-calculate-append commands**

Normalize and analyze before repository creation. `create_scan` is the composition of `analyze_image` and `create_scan_from_analysis`; the latter validates provenance, canonicalizes the image/source command hash, and creates the managed thumbnail without running any analyzer again. Redact identity suggestions and machine evidence before persistence. For identity updates, require `confirmed.identity_id` to be one of the scan's machine suggestions, allow `edited.identity_id` to be any returned catalog ID, call `KnowledgeStore.get_identity(identity_id)` for display validation, and derive the exact `CanonicalIdentityScope` through `KnowledgeStore.identity_scope(identity_id)`; never trust parallel client fields.

For a canonical scope, load the named user revision, construct `LifecycleRequest(subject=command.lifecycle_request.subject, endpoint=command.lifecycle_request.endpoint, metric=command.lifecycle_request.metric, unit=command.lifecycle_request.unit)`, call `EvidenceResolver.resolve(scope, request)`, and pass the result to `AssessmentEngine.assess`. For Unknown identity, validate that the request is exactly `device/service_life/elapsed_time/years`, fetch only `KnowledgeStore.manifest.stamp` and `KnowledgeStore.policy_bundle()`, and call `AssessmentEngine.assess_unknown_identity`; do not call resolver or any identity/evidence candidate method. Append either result under compare-and-swap with the canonical command hash.

Use stable service exceptions `InvalidCommand`, `ScanNotFound`, `RevisionNotFound`, `RevisionConflict`, `CatalogUnavailable`, `AssessmentUnavailable`, and `IdempotencyConflict`. Scan creation, assessment creation, and reassessment require decoded idempotency UUIDs. Repeating the same route-scoped key with the same canonical command hash returns the committed result; reusing it for different input raises `IdempotencyConflict`. Reassessment stores `base_assessment_revision_id`, never mutates the base, and compares identity scope, lifecycle record, source range, derived range, components, hazards, recommendations, bundle stamp, and policy revision without declaring the newer result intrinsically better. Unknown-to-Unknown reassessment creates the same policy-only shape with the current bundle/policy beside the old revision.

Catalog unavailability is scoped: `search_identities` reports unavailable, exact decisions cannot be newly resolved, category-only and Unknown decisions remain saveable, and category/condition analysis remains intact.

- [ ] **Step 4: Run service, resolver-integration, and stale-write tests**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_scan_service.py tests/test_assessment_engine_v2.py tests/test_evidence_resolver.py -v
.venv/bin/python -m py_compile server/scan_service.py
```

Expected: PASS for catalog derivation, Unknown policy-only assessment with resolver bypass, category-only tier limits, exact snapshot handoff, required idempotency/replay/conflict, stale inputs, evidence degradation/retry, and read-only views.

- [ ] **Step 5: Commit scan orchestration**

```bash
git add server/scan_service.py tests/test_scan_service.py
git commit -m "feat: orchestrate versioned assessments"
```

### Task 5: Expose the validated `/api/v2` surface

**Files:**
- Create: `server/v2_api.py`
- Create: `tests/test_v2_api.py`
- Modify: `server/desktop_app.py`
- Modify: `tests/test_desktop_api.py`

**Interfaces:**
- `create_v2_blueprint(service: ScanService) -> Blueprint`
- Error envelope: `{"error":{"code":str,"message":str,"field":str|null}}`
- Routes: `POST /api/v2/scans`, `PUT /api/v2/scans/{id}/identity-decision`, `PUT /api/v2/scans/{id}/observations`, `POST /api/v2/scans/{id}/assessment-revisions`, `POST /api/v2/scans/{id}/reassess`, `GET /api/v2/scans/{id}/summary`, `GET /api/v2/scans/{id}/components`, `GET /api/v2/catalog/identities`, `GET /api/v2/history`, and `GET /api/v2/scans/{id}/thumbnail`

- [ ] **Step 1: Write failing route, status, and mutation-boundary tests**

Assert exact response keys from Closed Wire Contracts. Add cases for malformed multipart, multiple images, 16 MiB overflow, invalid UUID, non-object JSON, unknown fields, wrong scalar types, unknown category/catalog identity, stale revision, unavailable evidence, absent saved assessment, and a legacy summary. For each of POST scan/assessment/reassess, assert a missing/invalid `idempotency_key` returns 400 before a write, a new key returns 201, an exact replay returns 200 with the same scan/revision ID, and a different command under that key returns 409. Assert PUT identity/observations rejects `idempotency_key` and uses only `expected_user_revision_id`. After confirmed, edited, and category-only identity PUTs, assert the returned `user_state.canonical_scope` contains all seven server-derived fields; after Unknown, assert the field exists and is null.

Post an assessment for an Unknown identity with the exact `device/service_life/elapsed_time/years` request. Assert HTTP 201, retained visible-condition decision, `scope=null`, `evidence.kind="unknown_identity"`, frozen bundle/policy, lifecycle/components/hazards unavailable with reason `unknown_identity`, no `resolved_evidence` field, applied rule `unknown_identity_more_information`, outcome `more_information_needed`, and zero resolver calls. For canonical scope, assert `evidence.kind="resolved"` and byte-equivalent serialization of the complete `ResolvedEvidence`.

Assert:

```python
def test_gets_are_read_only(client, repository, saved_assessment):
    before = repository.write_count
    assert client.get(f"/api/v2/scans/{saved_assessment.scan_id}/summary").status_code == 200
    assert client.get(f"/api/v2/scans/{saved_assessment.scan_id}/components").status_code == 200
    assert client.get("/api/v2/history").status_code == 200
    assert repository.write_count == before

def test_full_validation_precedes_transaction(client, repository):
    before = repository.write_count
    response = client.put(
        "/api/v2/scans/00000000-0000-0000-0000-000000000000/observations",
        json={"expected_user_revision_id": True, "condition_decision": {}, "observations": {}},
    )
    assert response.status_code == 400
    assert repository.write_count == before
```

- [ ] **Step 2: Run API tests and verify RED**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_v2_api.py tests/test_desktop_api.py -v
```

Expected: FAIL with 404 for `/api/v2` routes.

- [ ] **Step 3: Implement a thin blueprint and register injected dependencies**

Use `server.imaging.normalize_image` once per upload and always close the returned image after `ScanService.create_scan(image, ScanSource.MAC, idempotency_key)` completes. Decode the required create-style UUID and every complete payload before invoking service methods. Serialize dataclasses explicitly with closed keys, including all `canonical_scope` keys or an explicit null; do not expose SQLite rows, absolute paths, exception text, raw OCR, or Python reprs. Map invalid payload to 400, missing scan/revision to 404, stale/idempotency conflict to 409, oversize to 413, semantic bounds to 422, scoped catalog/evidence unavailability to 503, and unexpected errors to a sanitized 500.

Change `create_desktop_app` to accept `scan_service: ScanService | None = None`, register the blueprint when provided, and keep nested v1 routes unchanged until Task 7. The v2 thumbnail route resolves only a managed basename through the repository and sends `Cache-Control: no-store`; it never accepts a path parameter.

- [ ] **Step 4: Run v2, desktop, imaging, and hostile-output tests**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_v2_api.py tests/test_desktop_api.py tests/test_desktop_integration_fixes.py tests/test_imaging.py tests/test_smoke_output_safety.py -v
```

Expected: PASS for all routes/status codes, exact canonical-scope serialization, three required idempotency contracts, Unknown policy-only assessments, GET non-mutation, upload closure, safe thumbnails, and sanitized errors.

- [ ] **Step 5: Commit API v2**

```bash
git add server/v2_api.py server/desktop_app.py tests/test_v2_api.py tests/test_desktop_api.py
git commit -m "feat: expose scan aggregate API v2"
```

### Task 6: Require a fresh capability key on the loopback service

**Files:**
- Create: `server/local_capability.py`
- Create: `tests/test_local_capability.py`
- Modify: `server/desktop_app.py`
- Modify: `desktop/main.py`
- Modify: `tests/test_desktop_runtime.py`
- Modify: `tests/test_packaged_smoke.py`

**Interfaces:**
- `new_capability_key() -> str`
- `install_local_capability(app: Flask, key: str) -> None`
- `capability_bootstrap_url(base_url: str, key: str) -> str`
- Cookie name `ewaste_capability`
- Test/smoke header `X-EWaste-Capability`

- [ ] **Step 1: Write failing key-generation, bootstrap, denial, and rotation tests**

Assert two calls create distinct URL-safe keys with at least 256 bits of entropy. For an app configured with key `launch-a`, assert missing/wrong cookie and header receive indistinguishable 404 responses for `/`, static files, health, `/api/v1`, and `/api/v2`. Assert `GET /?capability=launch-a` returns 303 to `/` with `ewaste_capability=launch-a; HttpOnly; SameSite=Strict; Path=/`, `Cache-Control: no-store`, and `Referrer-Policy: no-referrer`. Assert the redirected request succeeds, the query is absent, the key is absent from response HTML/JS, and a key from the prior app generation fails.

```python
def test_capability_bootstrap_sets_http_only_cookie(app_with_key):
    response = app_with_key.test_client().get("/?capability=launch-a", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["Location"] == "/"
    assert "HttpOnly" in response.headers["Set-Cookie"]
    assert "SameSite=Strict" in response.headers["Set-Cookie"]
```

- [ ] **Step 2: Run authorization/runtime tests and verify RED**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_local_capability.py tests/test_desktop_runtime.py tests/test_packaged_smoke.py -v
```

Expected: FAIL because the loopback app currently accepts unauthenticated requests and native startup loads the bare URL.

- [ ] **Step 3: Implement constant-time authorization and native bootstrap handoff**

Generate with `secrets.token_urlsafe(32)` and compare with `hmac.compare_digest`. A correct `capability` query is accepted only on `/`, sets the cookie, and 303-redirects to a clean URL. All other desktop routes require either the exact HttpOnly cookie or exact `X-EWaste-Capability` header. Missing/wrong values return 404. Apply `Cache-Control: no-store` to bootstrap, authenticated HTML/static/API, and denial responses. Never put the key in Flask config dumps, logs, HTML, JavaScript, JSON, release metadata, or the history database.

Add `capability_key: str | None = None` to `create_desktop_app`; `None` is permitted only for isolated unit factories. `desktop.main.run` creates one key before assembling any product or recovery app, passes it through `build_desktop_app`, `build_recovery_app`, and `build_reference_recovery_app`, starts `ServerThread`, and calls:

```python
window_url = capability_bootstrap_url(server.start_and_wait(), capability_key)
webview_module.create_window("E-Waste Triage", window_url, min_size=(760, 620))
```

Packaged smoke readiness publishes that same bootstrap URL; its HTTP client follows the cookie redirect. A new service generation gets a new key.

- [ ] **Step 4: Run capability, runtime, and packaged-smoke tests**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_local_capability.py tests/test_desktop_runtime.py tests/test_packaged_smoke.py tests/test_runtime_control.py -v
.venv/bin/python -m py_compile server/local_capability.py desktop/main.py
```

Expected: PASS for bootstrap/cookie/header authorization, indistinguishable denials, recovery surfaces, old-key rejection, native window URL, and smoke handshake.

- [ ] **Step 5: Commit loopback capability authorization**

```bash
git add server/local_capability.py server/desktop_app.py desktop/main.py tests/test_local_capability.py tests/test_desktop_runtime.py tests/test_packaged_smoke.py
git commit -m "feat: authorize the local desktop service"
```

### Task 7: Implement thumbnail-only deletion, ten-second Undo, and permanent Clear History

**Files:**
- Modify: `server/scan_store.py`
- Modify: `server/scan_service.py`
- Modify: `server/v2_api.py`
- Create: `tests/test_privacy_retention.py`
- Modify: `tests/test_scan_store.py`
- Modify: `tests/test_v2_api.py`

**Interfaces:**
- `delete_scan(scan_id: str) -> DeleteReceipt(undo_token: str, undo_expires_at: datetime)`
- `undo_delete(undo_token: str) -> ScanRecord`
- `purge_expired_deletions() -> int`
- `clear_history(confirmation: str) -> int`
- `close() -> None`
- Routes: `DELETE /api/v2/scans/{id}`, `POST /api/v2/deletions/{token}/undo`, and `DELETE /api/v2/history` with JSON `{confirmation:"clear_history"}`

- [ ] **Step 1: Write failing retention, tombstone, clear, crash, and path-safety tests**

Use an injected mutable UTC clock. Assert delete sets `deleted_at` and hides the scan from all reads immediately. The random token exists only in memory. At 9.999 seconds Undo clears `deleted_at`; at 10 seconds it fails and cascade-deletes rows plus the managed thumbnail. On repository close, outstanding tombstones purge. On next open after a simulated crash, rows with `deleted_at` purge before history is published and cannot reappear. Clear History with any string other than `clear_history` makes zero changes; the exact confirmation immediately deletes visible and tombstoned rows, invalidates all tokens, drains the safe deletion journal, and returns no token.

Assert forged database media names, symlinks, traversal names, and paths outside `media_dir` are unlinked from records but never deleted from disk. Assert scan JSON contains no OCR transcript, serial string, source upload path, original path, or original-retention option.

```python
def test_delete_undo_window_is_exact(repository, mutable_clock):
    scan = repository.create_scan(
        machine_evidence(), thumbnail(), ScanSource.MAC,
        idempotency_key="0bf77f1c-73a5-422e-af8f-51dde28b12ea",
        command_sha256="d" * 64,
    )
    receipt = repository.delete_scan(scan.scan_id)
    assert repository.get_scan(scan.scan_id) is None
    mutable_clock.advance(seconds=9, microseconds=999000)
    assert repository.undo_delete(receipt.undo_token).scan_id == scan.scan_id
    receipt = repository.delete_scan(scan.scan_id)
    mutable_clock.advance(seconds=10)
    assert repository.purge_expired_deletions() == 1
    with pytest.raises(DeleteTokenExpired):
        repository.undo_delete(receipt.undo_token)
```

- [ ] **Step 2: Run privacy/repository/API tests and verify RED**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_privacy_retention.py tests/test_scan_store.py tests/test_v2_api.py -v
```

Expected: FAIL because v2 delete/Undo/Clear and startup tombstone purge do not exist.

- [ ] **Step 3: Implement soft tombstones with deterministic physical purge**

Under `BEGIN IMMEDIATE`, set root `deleted_at` and return a `secrets.token_urlsafe(32)` token held in a process-local map with scan ID and deadline. Every repository read filters deleted roots. Undo validates token/deadline, clears `deleted_at` transactionally, then invalidates the token. Expiry/shutdown cascade-deletes the row, journals its managed thumbnail basename, commits, and drains the journal with resolved-path containment and regular-file checks. On startup, purge every `deleted_at` root before returning history so tokens never survive a process.

Clear History validates the body before a transaction, invalidates the token map, deletes all session and persistent aggregates immediately, and drains only managed thumbnails. It has no Undo response field. A background timer may call `purge_expired_deletions`, but correctness must not depend on scheduling: every public read/write and `close()` also purges due tombstones.

- [ ] **Step 4: Run the privacy/deletion matrix**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_privacy_retention.py tests/test_scan_store.py tests/test_v2_api.py tests/test_history.py -v
git diff --check
```

Expected: PASS for boundary timing, restart purge, Clear confirmation, transient/persistent stores, token invalidation, cascade rows, safe media cleanup, and forbidden persistence fields.

- [ ] **Step 5: Commit privacy lifecycle**

```bash
git add server/scan_store.py server/scan_service.py server/v2_api.py tests/test_privacy_retention.py tests/test_scan_store.py tests/test_v2_api.py
git commit -m "feat: enforce private scan retention"
```

### Task 8: Adapt `/api/v1`, assemble degraded startup, and close every resource

**Files:**
- Modify: `server/history.py`
- Modify: `server/lifecycle.py`
- Modify: `server/desktop_app.py`
- Modify: `server/app.py`
- Modify: `desktop/main.py`
- Modify: `server/phone_app.py`
- Modify: `server/phone_sessions.py`
- Modify: `tests/test_history.py`
- Modify: `tests/test_lifecycle.py`
- Modify: `tests/test_desktop_api.py`
- Modify: `tests/test_assessment_api.py`
- Modify: `tests/test_desktop_phone_api.py`
- Modify: `tests/test_phone_sessions.py`
- Modify: `tests/test_desktop_integration_fixes.py`

**Interfaces:**
- `HistoryStore` retains its current constructor and public v1 methods but delegates to `ScanRepositoryRouter`
- `server.lifecycle.assess_component` remains a v1 response adapter over `AssessmentEngine`
- `build_desktop_app(paths: AppPaths, *, capability_key: str, require_release_integrity: bool = False) -> Flask`
- `POST /api/v2/history/retry` retries opening local history for future scans
- `POST /api/v2/evidence/retry` retries `KnowledgeStore` and `EvidenceResolver`

- [ ] **Step 1: Write failing v1 parity, startup degradation, retry, and teardown tests**

Characterize current v1 request/response/status behavior before changing adapters. Add tests proving:

- v1 list/detail reads the migrated v2 aggregate without rewriting it;
- v1 assessment reads a `legacy_v1` snapshot and never turns it into current evidence;
- an explicit v1 edit creates a user revision and an explicit v1 calculate creates a new v2 assessment revision;
- `retain_original=true` receives 400 and no original is written, while the existing default path stores only a thumbnail;
- product v1 requests remain capability-protected; collection-only `/ingest` in `create_app(ingest_root=tmp_path, collection_only=True)` still works and cannot access product history;
- history open failure builds a usable classifier/scan app with session storage and a retry action; evidence open/hash failure builds a usable classifier/condition app with identity/catalog/lifecycle/components unavailable and retryable;
- category model failure alone still enters model recovery;
- app shutdown calls phone capture close, repository close/tombstone purge, `KnowledgeStore.close`, and server shutdown exactly once even when an earlier closer raises;
- phone cancellation, expiry, completion, and shutdown remove the temporary upload and close the LAN listener.

```python
def test_history_failure_uses_session_repository(paths, working_classifier):
    app = build_desktop_app(
        paths,
        capability_key="launch-a",
        history_repository_factory=lambda database, media: (_ for _ in ()).throw(sqlite3.OperationalError("locked")),
    )
    client = authorized_client(app, "launch-a")
    response = post_scan(client, jpeg_bytes())
    assert response.status_code == 201
    assert response.json["scan"]["history_saved"] is False

def test_collection_ingest_is_not_removed(tmp_path):
    app = create_app(ingest_root=tmp_path, collection_only=True)
    assert app.test_client().get("/ingest").status_code == 200
```

- [ ] **Step 2: Run compatibility/startup/phone tests and verify RED**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_history.py tests/test_lifecycle.py tests/test_desktop_api.py tests/test_assessment_api.py tests/test_desktop_phone_api.py tests/test_phone_sessions.py tests/test_desktop_integration_fixes.py -v
```

Expected: FAIL because v1 still owns mutable history/lifecycle behavior and desktop startup treats reference/history failure as fatal or unhandled.

- [ ] **Step 3: Implement narrow adapters and resilient assembly**

Make `HistoryStore` translate its current dictionaries to repository commands without retaining originals. Make existing v1 assessment endpoints serialize a compatibility view over an explicitly created v2 revision; remove every GET-side `create_assessment`/repair mutation. Preserve legacy rows as visibly legacy and require an explicit current reassessment. Convert closed v2 recommendations back to the established v1 labels only in `server/lifecycle.py`; no v2 path imports old `Condition`, `Confidence`, or recommendation math.

In `desktop.main.build_desktop_app`, keep the category bundle mandatory. Attempt `KnowledgeStore`/`EvidenceResolver` and persistent history independently. On known startup failure, install scoped unavailable evidence services or a `SessionScanRepository`; expose sanitized status/retry operations and continue. A successful history retry is activated through `ScanRepositoryRouter` for future scans only. A successful evidence retry atomically replaces the unavailable pair after validating bundle release expectations. Close replaced and final stores exactly once.

Keep phone HTTP authorization/session behavior unchanged in this slice, but expose the `ScanService.analyze_image(image)` and `ScanService.create_scan_from_analysis(image, machine_evidence, ScanSource.PHONE, idempotency_key)` seams that Slice 3 uses around the final phone-session authorization check. The desktop callback creates one UUID for the accepted phone upload and reuses it if the same callback is retried. A revoked/expired session discards the result. Close normalized PIL objects in `finally`, clear session result state, and stop the listener on every terminal path.

- [ ] **Step 4: Run focused compatibility, full suite, and static checks**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_scan_contract.py tests/test_analysis_coordinator.py tests/test_assessment_engine_v2.py tests/test_scan_store.py tests/test_scan_service.py tests/test_v2_api.py tests/test_local_capability.py tests/test_privacy_retention.py tests/test_history.py tests/test_lifecycle.py tests/test_desktop_api.py tests/test_assessment_api.py tests/test_desktop_phone_api.py tests/test_phone_sessions.py tests/test_desktop_integration_fixes.py -q
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' -q
.venv/bin/python -m py_compile server/scan_contract.py server/analysis.py server/assessment_engine.py server/scan_store.py server/scan_service.py server/v2_api.py server/local_capability.py server/history.py server/lifecycle.py server/desktop_app.py server/app.py desktop/main.py
git diff --check
```

Expected: all tests pass; v2 GETs make no writes; v1 history is readable through adapters; old assessments stay frozen; collection-only ingest remains; history/evidence degrade independently; no original, temporary phone upload, expired tombstone, listener, or unclosed store survives teardown.

- [ ] **Step 5: Commit the compatibility and assembly cutover**

```bash
git add server/history.py server/lifecycle.py server/desktop_app.py server/app.py server/phone_app.py server/phone_sessions.py desktop/main.py tests/test_history.py tests/test_lifecycle.py tests/test_desktop_api.py tests/test_assessment_api.py tests/test_desktop_phone_api.py tests/test_phone_sessions.py tests/test_desktop_integration_fixes.py
git commit -m "feat: cut desktop scans over to api v2"
```

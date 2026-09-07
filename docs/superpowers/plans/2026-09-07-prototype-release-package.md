# Prototype Release, Packaging, Integrity, and QA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut the prototype over once to a closed release-manifest v2, bind every category/condition/knowledge artifact at staging and frozen startup, package only the approved runtime and evidence reports, exercise the complete offline v2 workflow, and deliver an independently reviewed internal macOS prototype with an auditable handoff.

**Architecture:** One shared `server.release_contract` owns the release-manifest v2 shape. The admin staging script validates immutable candidates and atomically promotes a closed directory; runtime metadata validates that same manifest through a build-time byte anchor; the package verifier independently reopens every packaged resource. Manual-only visible condition is a first-class release state, not a missing model. The package remains an unsigned/ad-hoc internal Apple Silicon application with no updater, training data, or network dependency beyond an explicitly activated phone listener.

**Tech Stack:** Python 3.11, JSON/SQLite/SHA-256, Flask 3.1.3, ONNX Runtime 1.29.0, PyInstaller 6.22.2, macOS `hdiutil`/`lipo`/`shasum`, pytest 9.1.1

**Spec:** `docs/superpowers/specs/2026-09-06-ewaste-evidence-condition-prototype-design.md`

## Required Upstream Gate

Begin only after Slices 1–4 pass their focused gates and the following artifacts/contracts exist:

- `server.knowledge_store.KnowledgeStore` and `BundleStamp(schema_version, bundle_version, identity_catalog_version, policy_revision, content_sha256)`;
- knowledge schema `3`, first bundle version `3.0.0`, and runtime file `knowledge.sqlite`;
- deterministic `evidence-coverage.json` and `evidence-coverage-change.json` contracts;
- Slice 1's checked-in `reference/approved-release.json` trust record and exact approved candidate `.release-staging/knowledge-3.0.0/{knowledge.sqlite,evidence-coverage.json,evidence-coverage-change.json}`;
- `verify_knowledge_release_inputs(candidate_dir: Path, approval_path: Path) -> KnowledgeReleaseInputs`, whose returned paths and hashes are the only accepted knowledge release inputs;
- the closed condition evaluation/gate contract and `ManualConditionEstimator` fallback;
- optional automated condition directory containing exactly `model.onnx` and `manifest.json` only when the gate passed;
- generation-safe startup and per-generation loopback capability authentication; and
- the v2 scan, assessment, components, revision, reassessment, deletion, and history APIs used by the Slice 4 UI.

Slice 1 supplies reviewed knowledge/coverage inputs and a compatibility-injection seam; it intentionally leaves the legacy release writer, paths, and packaged `components.sqlite` intact. Tasks 1–4 below own the one manifest/schema/file-layout cutover. Do not package `components.sqlite` and `knowledge.sqlite` together, do not maintain manifest v1 and v2 writers in parallel, and do not let the new UI call `/api/v1`. A read-only `/api/v1/release-metadata` display adapter may exist only through Task 7's first packaged-parity run; Task 7 removes it with every mutable v1 product adapter before rebuilding the final artifact.

## Release Manifest v2 Contract

The top-level fields are exactly:

```text
schema_version, app_version, category_model, condition, knowledge,
evidence_coverage_change, target, created_at
```

Nested objects are closed and exact:

```text
category_model = {
  model_id, architecture, preprocessing_version, schema_version,
  artifact_sha256, manifest_sha256, labels_sha256, parity_sha256
}

condition = {
  mode, rubric_version, evaluation_sha256, model
}

condition.model when automated = {
  model_id, manifest_sha256, artifact_sha256, preprocessing_version
}

condition.model when manual_only = null

knowledge = {
  artifact, sha256, content_sha256, schema_version, bundle_version,
  identity_catalog_version, policy_revision, coverage_sha256
}

evidence_coverage_change = {
  sha256, from_bundle_version, to_bundle_version
}

target = {architecture, minimum_macos}
```

Contract constants are:

- `schema_version = 2`;
- `condition.mode = automated|manual_only`;
- `knowledge.artifact = "knowledge.sqlite"`;
- `knowledge.schema_version = 3`;
- `target.architecture = "arm64"`;
- `target.minimum_macos = "14.0"`; and
- every SHA-256 is exact lowercase 64-character hex.

`from_bundle_version` is a semantic-version string or `null`. For the first schema-3 bundle it is `null`, every current coverage claim is in `added`, and known limitations are derived from current Unknown claims. A manual-only condition release has no condition model directory anywhere in stage or package. An automated release requires both condition files and their manifest/evaluation cross-anchors.

The pinned coverage JSON is closed schema 1:

```text
{
  schema_version, bundle_version, knowledge_content_sha256,
  summary: {
    categories, canonical_identities, subtypes, lifecycle_records,
    industry_averages, component_templates, modern_overlays,
    legacy_overlays, hazard_records, reviewed_claims, unknown_claims
  },
  claims: [{
    category_id, claim_kind, claim_id, evidence_level,
    source_state, source_ids, unknown_reason
  }]
}
```

Claims and `source_ids` use canonical sorting. The closed coverage-change schema 1 is `{schema_version, from_bundle_version, to_bundle_version, added, removed, changed, known_limitations}`. Its added/removed/changed rows use the compiler's canonical claim identity, and `known_limitations` is deterministically derived from current rows whose `source_state` is `unknown`.

The closed condition evaluation is `{schema_version, generated_at, mode, model, dataset, metrics, critical_gate, gate}`. `mode` is exactly `automated_candidate|manual_only`; `gate.status` is exactly `passed|manual_only`; `critical_gate` carries independent-device count and device-balanced recall; `gate` carries the approved thresholds and deterministic reasons. Release preparation validates this report without importing its training implementation.

## Closed Stage and Package Layout

Always-staged files:

```text
model/model.onnx
model/manifest.json
labels.json
parity-report.json
condition-evaluation.json
knowledge.sqlite
evidence-coverage.json
evidence-coverage-change.json
release-manifest.json
```

Automated-condition-only staged files:

```text
condition/model.onnx
condition/manifest.json
```

Packaged destinations:

```text
model/model.onnx                    -> models/production/model.onnx
model/manifest.json                 -> models/production/manifest.json
condition/model.onnx                -> models/condition/model.onnx          (automated only)
condition/manifest.json             -> models/condition/manifest.json       (automated only)
knowledge.sqlite                    -> reference/knowledge.sqlite
evidence-coverage.json              -> reference/evidence-coverage.json
evidence-coverage-change.json       -> release/evidence-coverage-change.json
condition-evaluation.json           -> release/condition-evaluation.json
labels.json                         -> release/labels.json
parity-report.json                  -> release/parity-report.json
release-manifest.json               -> release/release-manifest.json
```

## File Map

| File | Responsibility |
|---|---|
| `server/release_contract.py` | Closed manifest-v2 dataclasses, strict parsing, cross-field rules, and conditional file set |
| `packaging/release-manifest.schema.json` | Machine-readable closed mirror of manifest v2 |
| `scripts/prepare_release.py` | Candidate validation, copy/reopen/cross-check, and atomic stage promotion |
| `requirements-app.txt` | Product-only runtime dependencies; Task 7 removes administrator-only PyYAML with the last schema-2 compatibility code |
| `requirements.txt` | Administrator/development dependencies; retains PyYAML for reviewed knowledge compilation |
| `server/reference_db.py`, `scripts/build_component_db.py` | Obsolete schema-2 compiler/store removed in Task 7 after packaged parity |
| `reference/device_components.yaml`, `reference/sources.yaml` | Obsolete schema-2 source documents removed without touching schema-3 authoring data |
| `desktop/paths.py` | Frozen category, condition, knowledge, coverage, report, manifest, and local-data paths |
| `desktop/release_metadata.py` | Build anchor, manifest/resource identity, runtime expectations, and public About payload |
| `desktop/main.py` | Startup classification of fatal, manual-fallback, evidence-degraded, and history-degraded states |
| `server/desktop_app.py` | `/api/v2/release-metadata` plus temporary v1 display adapter |
| `server/reference_adapter.py` | Temporary v1 catalog adapter deleted with all product v1 routes in Task 7 |
| `server/static/index.html` | Expanded About fields |
| `server/static/app.js` | v2 About request and literal rendering |
| `packaging/EWasteTriage.spec` | Exact mandatory/conditional resource allowlists and product-only import graph |
| `scripts/verify_macos_bundle.py` | Independent stage/app validation and forbidden-content checks |
| `scripts/render_release_notes.py` | Deterministic notes from verified stage, coverage change, condition gate, and source revision |
| `scripts/build_macos_app.sh` | Clean-tree build, metadata anchor, app/DMG assembly, reports, and checksums |
| `tests/test_release_contract.py` | Manifest closedness, types, condition union, and cross-field validation |
| `tests/test_release_pipeline.py` | Atomic staging, input swaps, logical/raw hashes, and manual/automated layouts |
| `tests/test_release_metadata.py` | Runtime anchors, public v2 metadata, and failure classification |
| `tests/test_packaging.py` | Spec/verifier/build/notes/resource/forbidden-content contracts |
| `tests/test_packaged_smoke.py` | Complete authenticated offline workflow and process/listener cleanup |
| `tests/test_desktop_integration_fixes.py` | Frozen assembly and recovery/degradation integration |
| `tests/test_desktop_ui.py` | Expanded About dialog controller/DOM behavior |
| `tests/test_release_documentation.py` | Runbook, checklist, handoff, and non-claim documentation contracts |
| `README.md` | Prototype scope and release/admin entry points |
| `docs/RELEASING_MAC_APP.md` | Exact schema-v2 stage/build/verify/archive/rollback runbook |
| `docs/MAC_APP_TESTING.md` | Fresh-account offline, hardware, accessibility, and version cross-check checklist |
| `docs/PROTOTYPE_HANDOFF.md` | Deliverables, boundaries, known limitations, reports, and acceptance ownership |
| `docs/reviews/2026-09-07-prototype-release-review.md` | Independent review evidence pinned to the final source commit |

## Task 1: Freeze the shared release-manifest v2 contract

**Files:**
- Create: `server/release_contract.py`
- Create: `tests/test_release_contract.py`

**Interfaces:**

```python
class ConditionReleaseMode(str, Enum):
    AUTOMATED = "automated"
    MANUAL_ONLY = "manual_only"

@dataclass(frozen=True)
class CategoryModelRelease:
    model_id: str
    architecture: str
    preprocessing_version: str
    schema_version: int
    artifact_sha256: str
    manifest_sha256: str
    labels_sha256: str
    parity_sha256: str

@dataclass(frozen=True)
class ConditionModelRelease:
    model_id: str
    manifest_sha256: str
    artifact_sha256: str
    preprocessing_version: str

@dataclass(frozen=True)
class ConditionRelease:
    mode: ConditionReleaseMode
    rubric_version: str
    evaluation_sha256: str
    model: ConditionModelRelease | None

@dataclass(frozen=True)
class KnowledgeRelease:
    artifact: str
    sha256: str
    content_sha256: str
    schema_version: int
    bundle_version: str
    identity_catalog_version: str
    policy_revision: str
    coverage_sha256: str

@dataclass(frozen=True)
class EvidenceCoverageChangeRelease:
    sha256: str
    from_bundle_version: str | None
    to_bundle_version: str

@dataclass(frozen=True)
class ReleaseManifest:
    schema_version: int
    app_version: str
    category_model: CategoryModelRelease
    condition: ConditionRelease
    knowledge: KnowledgeRelease
    evidence_coverage_change: EvidenceCoverageChangeRelease
    target: Mapping[str, str]
    created_at: str
```

Methods are exactly `ReleaseManifest.from_mapping(value: object) -> ReleaseManifest`, `ReleaseManifest.to_mapping() -> dict[str, object]`, `load_release_manifest(path: Path) -> ReleaseManifest`, and `expected_stage_files(manifest: ReleaseManifest) -> frozenset[str]`.

- [ ] **Step 1: Write failing strict-contract tests**

Test one valid manual-only manifest and one valid automated manifest directly against the new Python contract. Mutate every top-level and nested field to prove unknown/missing fields, boolean integers, non-finite values, uppercase/short hashes, malformed semantic versions, invalid timestamps, wrong target, wrong knowledge artifact/schema, and invalid modes fail closed.

Specifically prove:

```python
assert valid_manual.condition.model is None
assert "condition/model.onnx" not in expected_stage_files(valid_manual)
assert "condition/model.onnx" in expected_stage_files(valid_automated)
```

Reject `manual_only` plus a model, `automated` plus null, coverage-change target different from `knowledge.bundle_version`, and schema versions other than 2/3. Assert `to_mapping()` round-trips without adding defaults. Do not edit or test the active schema-1 JSON schema, stager, or verifier in this task; they remain mutually compatible until Task 2 performs the one atomic cutover.

- [ ] **Step 2: Run contract tests and verify RED**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["tests/test_release_contract.py", "-q"]))'
```

Expected: FAIL because `server.release_contract` does not exist.

- [ ] **Step 3: Implement one strict shared parser and schema mirror**

Use exact `type(...)` checks where JSON booleans could masquerade as integers, reject non-finite numbers through `parse_constant`, validate timezone-aware `created_at`, and copy/freeze nested values. Enforce condition union and coverage-target cross-field rules in Python. This module is additive in Task 1: do not wire it into the legacy writer, schema, or verifier yet.

- [ ] **Step 4: Run contract tests and verify GREEN**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["tests/test_release_contract.py", "-q"]))'
.venv/bin/python -m py_compile server/release_contract.py
```

Expected: PASS for both valid layouts and every closed-schema mutation.

- [ ] **Step 5: Commit the release contract**

```bash
git add server/release_contract.py tests/test_release_contract.py
git commit -m "feat: define closed prototype release manifest"
```

## Task 2: Stage category, condition, knowledge, and coverage atomically

**Files:**
- Modify: `scripts/prepare_release.py`
- Modify: `scripts/verify_macos_bundle.py`
- Modify: `packaging/release-manifest.schema.json`
- Modify: `tests/test_release_pipeline.py`
- Modify: `tests/test_release_contract.py`
- Modify: `tests/test_packaging.py`

**Interfaces:**

Produces exactly `prepare_release(category_model_bundle: Path, category_parity_report: Path, condition_evaluation: Path, condition_model_bundle: Path | None, knowledge_candidate_dir: Path, knowledge_approval_path: Path, output_dir: Path, app_version: str) -> Path`.

Its first trust-boundary operation is exactly `verify_knowledge_release_inputs(knowledge_candidate_dir, knowledge_approval_path) -> KnowledgeReleaseInputs`. The stager then reads only the returned `knowledge_database_path`, `evidence_coverage_path`, `evidence_coverage_change_path`, `knowledge_sha256`, `stamp`, `coverage_sha256`, and `coverage_change_sha256`; it exposes no API or CLI that accepts three untrusted raw knowledge paths.

CLI flags are exactly `--category-model-bundle`, `--category-parity-report`, `--condition-evaluation`, optional `--condition-model-bundle`, `--knowledge-candidate`, `--knowledge-approval`, `--output-dir`, and `--app-version`.

- [ ] **Step 1: Write failing stage, cross-anchor, and race tests**

Use the Slice 1 approved-candidate fixture helper to create a closed three-file candidate plus matching approval record, and the Slice 3 contract to create condition-evaluation fixtures. Do not rebuild knowledge inside a staging test. Test:

- manual-only stages omit the condition directory and automated stages require exactly two condition files;
- category artifact/manifest/labels/parity hashes and IDs/preprocessing all agree;
- condition evaluation hash agrees with the optional condition manifest and the manifest gate decides the mode;
- `prepare_release()` calls `verify_knowledge_release_inputs(candidate_dir, approval_path)` before opening or copying any candidate knowledge path and derives manifest fields only from its returned `KnowledgeReleaseInputs`;
- missing/mismatched approval, an extra candidate file, a raw-file swap after approval, or mutation after verification all fail without replacing the prior output;
- `KnowledgeStore` confirms raw hash, logical `content_sha256`, schema, bundle, catalog, policy, and coverage hash;
- coverage JSON’s `bundle_version` and `knowledge_content_sha256` match the database `BundleStamp`;
- coverage change `to_bundle_version` matches current and its `from_bundle_version` matches its manifest entry;
- initial change has `from_bundle_version:null`, all current claims in `added`, and Unknown-derived `known_limitations`;
- symlink/path traversal, input/output overlap, malformed content, a valid asset from another release, and before/during/after-copy swaps all fail;
- a failed stage preserves the previous output and fsyncs/promotes only a fully reopened temporary directory; and
- old `components.sqlite`, extra reports, checkpoints, YAML, training photos, and admin code are rejected from the closed stage.

- [ ] **Step 2: Run release-pipeline tests and verify RED**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["tests/test_release_pipeline.py", "tests/test_release_contract.py", "tests/test_packaging.py", "tests/test_knowledge_release_inputs.py", "tests/test_knowledge_compiler.py", "tests/test_knowledge_store.py", "tests/test_evidence_coverage.py", "tests/test_condition_onnx.py", "-q"]))'
```

Expected: FAIL because the current stager accepts only a category model, parity report, and schema-2 component database, while its schema/verifier still parse manifest v1.

- [ ] **Step 3: Implement validate-copy-reopen-cross-check promotion**

Call `verify_knowledge_release_inputs(knowledge_candidate_dir, knowledge_approval_path)` before creating output. Resolve only the verified paths it returns, protect every source and repository source/admin directory from overlap, and retain its approved hashes/stamp as the expected identities. Validate category/condition candidates, copy all inputs into a sibling temporary directory, then reopen and validate only the copies against those approved identities. A post-verification source swap must fail the copied-byte hash check. Construct `ReleaseManifest` from the reopened copies and write it last. Fsync files/directories and use the existing backup/restore promotion discipline.

In this same change, replace the active manifest JSON schema with its closed v2 mirror and replace the stage-only verifier's schema-1 parser with `ReleaseManifest.from_mapping()`. Update the legacy stager/verifier tests together: this is the sole writer/schema/verifier cutover, and its green state contains neither a v1 writer nor a mixed `components.sqlite`/`knowledge.sqlite` layout.

For manual-only evaluation, reject a supplied condition bundle. For a passed automated gate, require and reopen a condition bundle whose manifest `evaluation_report_sha256` equals the staged evaluation hash. Never silently downgrade a passed-but-invalid automated candidate during release preparation; the administrator must stage an explicit manual-only evaluation instead.

- [ ] **Step 4: Run pipeline and deterministic-output tests and verify GREEN**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["tests/test_release_pipeline.py", "tests/test_release_contract.py", "tests/test_packaging.py", "tests/test_knowledge_release_inputs.py", "tests/test_knowledge_compiler.py", "tests/test_knowledge_store.py", "tests/test_evidence_coverage.py", "tests/test_condition_onnx.py", "-q"]))'
```

Expected: PASS for manual/automated stages, raw/logical cross-checks, swaps, atomic failure, and exact file closure.

- [ ] **Step 5: Commit atomic prototype staging**

```bash
git add scripts/prepare_release.py scripts/verify_macos_bundle.py packaging/release-manifest.schema.json tests/test_release_pipeline.py tests/test_release_contract.py tests/test_packaging.py
git commit -m "feat: stage complete prototype releases"
```

## Task 3: Bind frozen startup and About to manifest v2

**Files:**
- Modify: `desktop/paths.py`
- Modify: `desktop/release_metadata.py`
- Modify: `desktop/main.py`
- Modify: `server/desktop_app.py`
- Modify: `server/static/index.html`
- Modify: `server/static/app.js`
- Modify: `tests/test_release_metadata.py`
- Modify: `tests/test_desktop_integration_fixes.py`
- Modify: `tests/test_desktop_ui.py`
- Modify: `tests/test_runtime_control.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class RuntimeCategoryIntegrity:
    model_id: str
    schema_version: int
    preprocessing_version: str
    artifact_sha256: str
    manifest_sha256: str
    labels_sha256: str
    parity_sha256: str
    labels: tuple[str, ...]

@dataclass(frozen=True)
class RuntimeConditionIntegrity:
    mode: ConditionReleaseMode
    rubric_version: str
    evaluation_sha256: str
    model_id: str | None
    preprocessing_version: str | None
    artifact_sha256: str | None
    manifest_sha256: str | None

@dataclass(frozen=True)
class RuntimeKnowledgeIntegrity:
    schema_version: int
    bundle_version: str
    identity_catalog_version: str
    policy_revision: str
    sha256: str
    content_sha256: str
    coverage_sha256: str

@dataclass(frozen=True)
class ReleaseMetadata:
    app_version: str
    source_revision: str
    release_manifest_sha256: str
    category_model_id: str
    category_model_sha256: str
    category_preprocessing_version: str
    condition_mode: str
    condition_model_id: str | None
    condition_rubric_version: str
    condition_preprocessing_version: str | None
    condition_evaluation_sha256: str
    knowledge_bundle_version: str
    knowledge_bundle_sha256: str
    knowledge_content_sha256: str
    evidence_coverage_sha256: str
    evidence_coverage_change_sha256: str
    identity_catalog_version: str
    policy_revision: str

@dataclass(frozen=True)
class RuntimeRelease:
    metadata: ReleaseMetadata
    category: RuntimeCategoryIntegrity
    condition: RuntimeConditionIntegrity
    knowledge: RuntimeKnowledgeIntegrity
```

Methods/functions are exactly `ReleaseMetadata.public_payload() -> dict[str, str | None]`, `load_runtime_release(paths: AppPaths) -> RuntimeRelease`, `validate_runtime_category(paths: AppPaths, classifier, integrity: RuntimeCategoryIntegrity) -> None`, and `validate_runtime_condition(paths: AppPaths, estimator, integrity: RuntimeConditionIntegrity) -> None`.

`AppPaths` adds the derived `condition_model_bundle_dir` property (returning `resources_dir / "models" / "condition"`), plus `knowledge_database_path`, `evidence_coverage_path`, `evidence_coverage_change_path`, and `condition_evaluation_path`. Do not add a condition dataclass field. Remove the schema-2 `reference_database_path` property and all `components.sqlite` assumptions.

The exact `/api/v2/release-metadata` public fields are:

```text
app_version, source_revision, release_manifest_sha256,
category_model_id, category_model_sha256, category_preprocessing_version,
condition_mode, condition_model_id, condition_rubric_version,
condition_preprocessing_version, condition_evaluation_sha256,
knowledge_bundle_version, knowledge_bundle_sha256,
knowledge_content_sha256, evidence_coverage_sha256,
evidence_coverage_change_sha256, identity_catalog_version, policy_revision
```

`condition_model_id` and `condition_preprocessing_version` are `null` in manual-only mode. The temporary, read-only `/api/v1/release-metadata` adapter returns its original five keys, mapping `model_sha256` to the category artifact, `component_database_sha256` to the knowledge raw hash, and `component_database_version` to the knowledge bundle version. It exists solely to establish first-build packaged parity and is deleted in Task 7 before the final stage/app/DMG rebuild; it is never a mutable product fallback.

- [ ] **Step 1: Write failing runtime-anchor, About, and failure-class tests**

Prove the build metadata byte-anchors the exact release manifest and source revision. Mutate each category, condition, knowledge, coverage, policy/catalog, report, labels, and manifest hash independently and assert startup cannot publish a mismatched resource.

Create a saved assessment, replace the installed current bundle, and prove the old revision still exposes its original five-field `BundleStamp` (`schema_version`, `bundle_version`, `identity_catalog_version`, `policy_revision`, `content_sha256`) byte-for-byte. A reassessment must create a new adjacent stamp; neither About nor current runtime metadata may rewrite history.

Assert failure classification matches the umbrella spec:

- invalid release manifest, category checksum/schema/labels/preprocessing/inference shape is fatal `RECOVERY`;
- missing/invalid condition automation becomes guided manual condition with its rubric and no fabricated model identity;
- valid category plus unavailable knowledge keeps Scan usable, disables evidence-backed lifecycle/Components, and exposes one retry;
- history-open failure keeps unsaved scanning usable with `history_saved:false`; and
- unexpected errors are sanitized and all partial resources close.

Test v2 About exact fields, `Cache-Control:no-store`, literal hostile-value rendering, retry/deduplication, native close/focus return, and absence of raw paths/capability values. Test the v1 adapter separately so it cannot influence the v2 UI.

- [ ] **Step 2: Run runtime/About tests and verify RED**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["tests/test_release_metadata.py", "tests/test_desktop_integration_fixes.py", "tests/test_desktop_ui.py", "tests/test_runtime_control.py", "-q"]))'
```

Expected: FAIL because runtime paths, metadata, and About expose only the old model/component identity.

- [ ] **Step 3: Implement one anchored runtime release object**

Parse build metadata, verify the raw manifest bytes against `release_manifest_sha256`, parse with `ReleaseManifest`, and derive all runtime expectations/public metadata from that one object. Validate category before inference. Open `KnowledgeStore` with all seven release expectations, including raw/logical/coverage/catalog/policy values. Validate condition evaluation in both modes; construct manual fallback on condition load/inference-contract failure and report the degradation through the startup coordinator.

Switch About to `/api/v2/release-metadata` and render labeled values without `innerHTML`. Group category, condition, knowledge, policy, and build identity for readability without turning About into a fifth destination.

- [ ] **Step 4: Run runtime/About tests and verify GREEN**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["tests/test_release_metadata.py", "tests/test_desktop_integration_fixes.py", "tests/test_desktop_ui.py", "tests/test_runtime_control.py", "tests/test_startup_coordinator.py", "tests/test_local_capability.py", "-q"]))'
```

Expected: PASS for complete About identity, fatal category/release failures, manual condition fallback, knowledge/history degradation, and cleanup.

- [ ] **Step 5: Commit frozen manifest-v2 runtime identity**

```bash
git add desktop/paths.py desktop/release_metadata.py desktop/main.py server/desktop_app.py server/static/index.html server/static/app.js tests/test_release_metadata.py tests/test_desktop_integration_fixes.py tests/test_desktop_ui.py tests/test_runtime_control.py
git commit -m "feat: bind runtime to prototype release identity"
```

## Task 4: Package and independently verify the closed prototype

**Files:**
- Modify: `packaging/EWasteTriage.spec`
- Modify: `scripts/verify_macos_bundle.py`
- Modify: `scripts/render_release_notes.py`
- Modify: `scripts/build_macos_app.sh`
- Modify: `tests/test_packaging.py`
- Modify: `tests/test_release_pipeline.py`

**Interfaces:**
- Produces: `release_resource_files(manifest: ReleaseManifest) -> dict[str, str]`
- Produces: `validate_release_stage(release_dir: Path, expected_version: str | None = None) -> ReleaseManifest`
- Produces: `verify_macos_bundle(app_bundle: Path, release_dir: Path, expected_version: str) -> None`
- Produces: `render_release_notes(release_dir: Path, version: str, source_revision: str) -> str`

- [ ] **Step 1: Write failing package/verifier/report tests**

Create manual-only and automated synthetic stages. Assert the PyInstaller spec has literal mandatory and conditional allowlists matching the layout above, includes no admin/training inputs, and condition files appear only for automated releases.

Test the verifier against stage and packaged copies for every raw hash plus:

- category manifest/artifact/labels/parity agreement and inference contract;
- condition evaluation/gate/model agreement;
- knowledge raw/logical/coverage/catalog/policy agreement;
- coverage/change JSON agreement with the database and release manifest;
- exact product static files and conditional release resources;
- arm64/minimum-macOS/plist/entitlement identity;
- absence of `scripts`, tests, PyTorch/torchvision, datasets, checkpoints, authoring YAML, `components.sqlite`, and unexpected product data; and
- build metadata app/source/manifest anchor agreement.

Assert release notes contain app/source/category model/preprocessing, condition mode/model/rubric, knowledge/catalog/policy, raw/logical hashes, coverage added/removed/changed counts, Unknown-derived limitations, target, phone HTTP boundary, and unsigned/not-notarized status. Known limitations must come only from the verified coverage change and condition gate reasons.

Assert the DMG source contains the app, Applications link, `Release Notes.md`, `Evidence Coverage.json`, `Evidence Coverage Change.json`, `Condition Evaluation.json`, `Prototype Acceptance Checklist.md`, and `Administration/Evidence Bundle Procedure.md`.

- [ ] **Step 2: Run packaging tests and verify RED**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["tests/test_packaging.py", "tests/test_release_pipeline.py", "-q"]))'
```

Expected: FAIL because spec/verifier/build/notes still know only the schema-1 category/component release.

- [ ] **Step 3: Implement conditional resource collection and independent verification**

Compute the exact stage/package file set from the parsed manifest. In the PyInstaller spec, read only the already-validated stage manifest to select the optional condition pair; do not glob. In the verifier, compare staged and packaged bytes for every mapped resource, then independently reopen model bundles, condition evaluation/model, coverage reports, and `KnowledgeStore`.

Pass the clean-tree `SOURCE_REVISION` into release-note rendering. Expand the generated release JSON with manifest schema, category model ID/hash, condition mode/rubric, knowledge raw/logical/bundle/catalog/policy values, and report hashes while retaining DMG hash, app version, architecture, minimum macOS, and source revision.

Copy the verified reports and tracked procedures/checklist into the DMG source. These administrative documents remain outside the app bundle and cannot be imported by the live runtime.

- [ ] **Step 4: Run packaging tests and verify GREEN**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["tests/test_packaging.py", "tests/test_release_pipeline.py", "tests/test_release_contract.py", "-q"]))'
```

Expected: PASS for manual/automated resource sets, stage/app tamper rejection, notes, DMG contents, and clean-tree refusal.

- [ ] **Step 5: Commit packaging and verification**

```bash
git add packaging/EWasteTriage.spec scripts/verify_macos_bundle.py scripts/render_release_notes.py scripts/build_macos_app.sh tests/test_packaging.py tests/test_release_pipeline.py
git commit -m "feat: package and verify prototype release assets"
```

## Task 5: Replace packaged smoke with the authenticated complete v2 workflow

**Files:**
- Modify: `tests/test_packaged_smoke.py`
- Modify: `tests/test_runtime_control.py`
- Modify: `tests/test_packaging.py`

**Interfaces:**
- Produces: `_bootstrap_desktop(readiness_url: str) -> tuple[OpenerDirector, str, int]`
- Produces: `_json_request(opener, base_url, endpoint, *, method, payload, data, content_type, expected_statuses) -> object`
- Produces: `_listening_ports(process: psutil.Process) -> set[tuple[str, int]]`

- [ ] **Step 1: Write failing capability and full-workflow smoke assertions**

Change readiness validation to accept exactly one non-empty `capability` query value over `http://127.0.0.1:{ephemeral_port}/`. Bootstrap a `CookieJar` through that URL, follow the `303` to `/`, and use the resulting HttpOnly session for all desktop requests. Assert a fresh unauthenticated opener receives indistinguishable `404` plus `Cache-Control:no-store`; never include the capability value in assertion messages or captured output.

Before phone activation, inspect the app process and children with `psutil` and assert the only listener is the authenticated 127.0.0.1 desktop port. Then execute, in order:

1. health and the exact `/api/v2/release-metadata` contract;
2. Mac fixture upload through `POST /api/v2/scans` with multipart `image` plus a canonical UUID `idempotency_key`, and three independent capability states;
3. explicit category-only decision for the returned canonical category using `expected_user_revision_id`;
4. an observation revision with manual grade `fair`, no model confidence, `age_months:{lower:12,upper:24}`, `full_charge_cycles:null`, `operational_state:"unknown"`, all four issue flags false, and empty component decisions;
5. an assessment revision using `lifecycle_request:{subject:"device",endpoint:"service_life",metric:"elapsed_time",unit:"years"}` plus a canonical UUID `idempotency_key`;
6. exact saved summary and Components reads without a mutation-count change;
7. History reopen, available revision list, reassessment with the same lifecycle request plus a new canonical UUID `idempotency_key`, and comparison preserving the original;
8. delete receipt, immediate absence, token Undo before expiry, and exact aggregate restoration;
9. explicit phone-session start, second listener appearance, paired upload, desktop result receipt, session stop, and phone-listener refusal;
10. confirmed Clear History with no Undo token and no managed media left; and
11. SIGTERM shutdown, readiness-file removal, desktop-port refusal, phone-port refusal, temporary upload cleanup, and no orphan child.

Accept response statuses explicitly, including `200`, `201`, `202`, and `204`; never broadly accept all 2xx responses.

- [ ] **Step 2: Run non-packaged helper tests and verify RED**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["tests/test_packaged_smoke.py", "tests/test_runtime_control.py", "-q"]))'
```

Expected: helper tests fail because readiness currently forbids a query, requests have no cookie jar, and the smoke exercises only v1 category/component paths.

- [ ] **Step 3: Implement secure helpers and the complete workflow**

Keep the current bounded readiness/poll/cleanup behavior. Redact the readiness query in diagnostics, use a dedicated opener per auth boundary, and verify cookie behavior without trying to read an HttpOnly flag through JavaScript. Gather listener state for the process tree both before and after phone activation. Use server-returned IDs/revisions/timestamps; do not sleep through the Undo window. Generate one key per scan/assessment/reassessment intent, retain the exact logical command with it, prove an ambiguous retry replays the same key, and never reuse a key for changed content.

- [ ] **Step 4: Run helper, service, and process-control tests and verify GREEN**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["tests/test_packaged_smoke.py", "tests/test_runtime_control.py", "tests/test_v2_api.py", "tests/test_scan_store.py", "tests/test_desktop_phone_api.py", "tests/test_phone_sessions.py", "-q"]))'
```

Expected: non-packaged helpers and service fixtures pass; the frozen-app case remains skipped unless `EWASTE_PACKAGED_APP` is set.

- [ ] **Step 5: Commit full packaged smoke**

```bash
git add tests/test_packaged_smoke.py tests/test_runtime_control.py tests/test_packaging.py
git commit -m "test: smoke complete authenticated prototype workflow"
```

## Task 6: Write the release, testing, and prototype handoff contract

**Files:**
- Modify: `README.md`
- Modify: `docs/RELEASING_MAC_APP.md`
- Modify: `docs/MAC_APP_TESTING.md`
- Create: `docs/PROTOTYPE_HANDOFF.md`
- Create: `tests/test_release_documentation.py`

**Interfaces:**
- Produces: one exact administrator path from reviewed sources to `dist/`
- Produces: one exact tester path from DMG receipt to signed-off acceptance record
- Cross-links: `docs/EVIDENCE_BUNDLE_PROCEDURE.md` and `docs/CONDITION_LABELING_PROCEDURE.md`

- [ ] **Step 1: Write failing documentation-contract tests**

Assert the docs name manifest schema 2, knowledge schema/bundle 3/3.0.0, raw/logical/coverage hashes, identity catalog/policy, manual-only condition, category preprocessing, source revision, exact staging flags, verifier, packaged-smoke command, DMG checksum comparison, archive/rollback, and the ban on mutating an approved stage.

Assert the manual checklist includes fresh macOS 14+ tester account, offline DMG mount/copy/eject, Finder/Open/Gatekeeper behavior, 1120×760 and 760×620, all four destinations and prerequisites, full Mac and phone paths, IPv4/IPv6 where available, Local Network denial/retry, no pre-action LAN listener, source links, History revisions/reassessment/delete/Undo/clear, About cross-checks, VoiceOver, keyboard, visible focus, Reduce Motion, light/dark appearance, relaunch, privacy/media cleanup, and crash/recovery behavior.

Require 20 cold launches on the supported reference Mac and record p95 time to first visible native startup surface and p95 time to usable Scan. The acceptance thresholds are at most 1 second and 2 seconds respectively; also verify slow copy at 2 seconds, repeating motion stopped at 5 seconds, and long-start Quit at 10 seconds with an intentionally blocked test initialization.

Reject claims of Developer ID signing, notarization, TLS phone transport, cloud sync, automatic hardware diagnosis, or automatic condition automation when the gate is manual-only.

- [ ] **Step 2: Run documentation tests and verify RED**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["tests/test_release_documentation.py", "-q"]))'
```

Expected: FAIL because current docs describe schema-2 components and the earlier five-field About/release flow.

- [ ] **Step 3: Update runbooks and handoff without overstating completion**

Document current manual-only condition as a supported product mode and include the actual gate reasons from the release report in generated notes, not hard-coded prose. Explain that source URLs remain visible offline but external opening requires the user and network. Separate app-bundle runtime resources from the reports/procedures placed beside it in the DMG.

`docs/PROTOTYPE_HANDOFF.md` identifies every artifact and owner, the internal-only/ad-hoc boundary, known limitations, how to compare About→release JSON→manifest→reports, rollback to a complete prior release, and the rule that completion is not claimed until the manual checklist has real evidence.

- [ ] **Step 4: Run docs plus focused release tests and verify GREEN**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["tests/test_release_documentation.py", "tests/test_packaging.py", "tests/test_release_pipeline.py", "-q"]))'
```

Expected: PASS with no stale `components.sqlite` release instruction or unsupported product claim.

- [ ] **Step 5: Commit release documentation**

```bash
git add README.md docs/RELEASING_MAC_APP.md docs/MAC_APP_TESTING.md docs/PROTOTYPE_HANDOFF.md tests/test_release_documentation.py
git commit -m "docs: define prototype release and acceptance handoff"
```

## Task 7: Independently review, build, smoke, and accept the 0.2.0 prototype

**Files:**
- Modify: `server/desktop_app.py`
- Modify: `server/app.py`
- Modify: `desktop/main.py`
- Modify: `requirements-app.txt`
- Delete: `server/history.py`
- Delete: `server/lifecycle.py`
- Delete: `server/reference_db.py`
- Delete: `server/reference_adapter.py`
- Delete: `scripts/build_component_db.py`
- Delete: `reference/device_components.yaml`
- Delete: `reference/sources.yaml`
- Delete: `tests/test_history.py`
- Delete: `tests/test_lifecycle.py`
- Delete: `tests/test_desktop_api.py`
- Delete: `tests/test_assessment_api.py`
- Delete: `tests/test_reference_db.py`
- Delete: `tests/test_reference_adapter.py`
- Delete: `tests/test_reference_release.py`
- Modify: `tests/test_desktop_phone_api.py`
- Modify: `tests/test_desktop_integration_fixes.py`
- Modify: `tests/test_release_metadata.py`
- Modify: `tests/test_packaging.py`
- Modify: `tests/test_packaged_smoke.py`
- Create: `tests/test_v1_retirement.py`
- Create from actual review: `docs/reviews/2026-09-07-prototype-release-review.md`
- Produce ignored artifacts: `.release-staging/condition-manual-only-0.2.0/`, `.release-staging/release-0.2.0-rc.1/`, `.release-staging/release-0.2.0/`, `build/0.2.0-rc.1/`, `build/0.2.0/`, and `dist/`

- [ ] **Step 1: Generate the honest condition report and verify the already-approved knowledge handoff**

Run:

```bash
test ! -e .release-staging/condition-manual-only-0.2.0
.venv/bin/python scripts/evaluate_condition_model.py \
  --manual-only-reason no_qualified_candidate \
  --output-dir .release-staging/condition-manual-only-0.2.0
test -f .release-staging/condition-manual-only-0.2.0/condition-evaluation.json
.venv/bin/python scripts/knowledge_release.py \
  --candidate .release-staging/knowledge-3.0.0 \
  --approval reference/approved-release.json \
  --print-summary
```

Expected: evaluation is closed `mode:"manual_only"` with reason `no_qualified_candidate`; Slice 1's approved three-file candidate verifies byte-for-byte. Do not run the knowledge compiler or coverage comparator here: rebuilding after approval would create an unreviewed release input. These commands intentionally precede every clean-tree/build gate and write only the ignored condition output.

- [ ] **Step 2: Run the complete source gate and request independent review**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["-q"]))'
git diff --check
git status --short
```

Expected: full suite passes, diff check is clean, and only intentional plan/implementation changes are present before their commits.

Use `superpowers:requesting-code-review` with a fresh reviewer that did not implement the slice. Review the final diff against the umbrella spec, both slice plans, privacy/claim boundaries, capability secrecy, startup cleanup, revision immutability, manifest cross-anchors, package exclusions, hostile inputs, and manual-only honesty. The reviewer must run focused tests and record the exact reviewed commit, commands/results, findings by Critical/Important/Minor severity, and resolution commit for every finding.

Write only actual results to `docs/reviews/2026-09-07-prototype-release-review.md`. A report with unresolved Critical or Important findings fails this task. Fix findings through failing regression tests, rerun the full suite, request re-review, then commit the accepted report:

```bash
git add docs/reviews/2026-09-07-prototype-release-review.md
git commit -m "docs: record independent prototype release review"
```

- [ ] **Step 3: Re-run from the reviewed clean commit before the parity build**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["-q"]))'
git diff --check
test -z "$(git status --porcelain=v1 --untracked-files=all)"
```

Expected: PASS and a completely clean tree. The next commands intentionally write only ignored staging/build/distribution paths.

- [ ] **Step 4: Stage, build, and smoke the 0.2.0-rc.1 parity candidate**

Run:

```bash
.venv/bin/python scripts/prepare_release.py \
  --category-model-bundle .release-staging/model-t07-20260906 \
  --category-parity-report .release-staging/parity-t07-20260906.json \
  --condition-evaluation .release-staging/condition-manual-only-0.2.0/condition-evaluation.json \
  --knowledge-candidate .release-staging/knowledge-3.0.0 \
  --knowledge-approval reference/approved-release.json \
  --output-dir .release-staging/release-0.2.0-rc.1 \
  --app-version 0.2.0-rc.1
.venv/bin/python scripts/verify_macos_bundle.py \
  --release-dir .release-staging/release-0.2.0-rc.1 \
  --expected-version 0.2.0-rc.1 \
  --stage-only
./scripts/build_macos_app.sh \
  --version 0.2.0-rc.1 \
  --release-dir .release-staging/release-0.2.0-rc.1
.venv/bin/python scripts/verify_macos_bundle.py \
  --release-dir .release-staging/release-0.2.0-rc.1 \
  --expected-version 0.2.0-rc.1 \
  --app 'dist/E-Waste Triage.app'
EWASTE_PACKAGED_APP='dist/E-Waste Triage.app' \
  .venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["tests/test_packaged_smoke.py", "-q"]))'
```

Expected: the exact approved knowledge files are staged; the manual release has no `condition/` directory or `components.sqlite`; the authenticated v2 package workflow passes. This is the sole parity window for the temporary read-only `/api/v1/release-metadata` adapter.

- [ ] **Step 5: Write the failing final v1/schema-2 retirement tests**

In `tests/test_v1_retirement.py`, enumerate every former product route and assert the desired authenticated `404` for `/api/v1/release-metadata`, classify/explain, history/detail/confirmation/delete/clear, reference catalog, and assessment read/write. Assert `server.app.create_app(..., collection_only=True)` still serves `/ingest`, but exposes none of those product routes. Assert no production module imports `server.history`, `server.lifecycle`, `server.reference_db`, or `server.reference_adapter`; their v2 replacements are `ScanRepositoryRouter`, `AssessmentEngine`, `KnowledgeStore`, and `EvidenceResolver`.

Assert `server/reference_db.py`, `scripts/build_component_db.py`, `reference/device_components.yaml`, `reference/sources.yaml`, `tests/test_reference_db.py`, `tests/test_reference_adapter.py`, and the entirely schema-2 `tests/test_reference_release.py` are absent. At the same time, assert `reference/bundle.yaml`, `reference/common/sources.yaml`, `reference/common/policies.yaml`, every `reference/categories/<released-category>/` tree, `scripts/knowledge_schema.py`, `scripts/knowledge_compiler.py`, and `scripts/build_knowledge_bundle.py` remain.

Add this executed dependency-boundary assertion to `tests/test_packaging.py`, parsing normalized distribution names rather than matching capitalization:

```python
from packaging.requirements import Requirement

def requirement_names(path: Path) -> set[str]:
    return {
        Requirement(line).name.casefold()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

assert "pyyaml" not in requirement_names(ROOT / "requirements-app.txt")
assert "pyyaml" in requirement_names(ROOT / "requirements.txt")
```

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["tests/test_v1_retirement.py", "tests/test_packaging.py", "-q"]))'
```

Expected: FAIL because the temporary adapters still register v1 product routes, schema-2 store/compiler/YAML/tests still exist, and `requirements-app.txt` still contains PyYAML.

- [ ] **Step 6: Remove every v1 product adapter and schema-2 reference path, then verify GREEN**

Remove all `/api/v1` route registration from `server.desktop_app` and `server.app`, including the read-only metadata exception. Preserve `/ingest` and its collection-only isolation; it is an administrator workflow, not a v1 product adapter. Remove `server/history.py`, `server/lifecycle.py`, and the now-unused `server/reference_adapter.py`; migrate remaining phone/integration fixtures to `ScanRepositoryRouter`, `AssessmentEngine`, `KnowledgeStore`, and `EvidenceResolver`; remove their superseded legacy-only tests; and keep all v2 tests. Update packaged smoke to assert the retired v1 paths are absent after the complete v2 workflow.

Delete `server/reference_db.py`, `scripts/build_component_db.py`, the two frozen-v1 roots `reference/device_components.yaml` and `reference/sources.yaml`, `tests/test_reference_db.py`, and the entirely legacy `tests/test_reference_release.py`. Remove PyYAML from `requirements-app.txt` in this same commit. Replace the old `test_packaged_runtime_requirements_install_a_yaml_reader` expectation with the executed product-excludes/admin-retains assertions above; do not skip it. Do not delete or rewrite the schema-3 `reference/bundle.yaml`, `reference/common/`, `reference/categories/`, knowledge compiler, coverage tooling, approval record, or administrator `requirements.txt`; the latter retains PyYAML for those admin-only YAML workflows.

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["tests/test_v1_retirement.py", "tests/test_packaging.py", "tests/test_v2_api.py", "tests/test_scan_store.py", "tests/test_assessment_engine_v2.py", "tests/test_desktop_phone_api.py", "tests/test_desktop_integration_fixes.py", "tests/test_release_metadata.py", "tests/test_packaged_smoke.py", "tests/test_knowledge_schema.py", "tests/test_knowledge_compiler.py", "tests/test_knowledge_store.py", "tests/test_evidence_resolver.py", "tests/test_evidence_coverage.py", "tests/test_knowledge_release.py", "tests/corpus", "-q"]))'
! rg -n '/api/v1|ReferenceStore|components\.sqlite|server\.reference_db|server\.reference_adapter|PyYAML|\bimport yaml\b|\bfrom yaml\b' server desktop packaging requirements-app.txt
! rg -n 'server\.(history|lifecycle|reference_db|reference_adapter)|from server import (history|lifecycle|reference_db|reference_adapter)' tests -g '!test_v1_retirement.py'
test ! -e reference/device_components.yaml
test ! -e reference/sources.yaml
test -f reference/bundle.yaml
test -f reference/common/sources.yaml
test -d reference/categories
.venv/bin/python -m py_compile server/desktop_app.py server/app.py desktop/main.py
git diff --check
```

Expected: PASS; no v1 product route, schema-2 runtime/store/compiler/source, `components.sqlite` reference, or product PyYAML dependency remains, while collection-only ingest, schema-3 authoring/compiler tests, and all v2 behavior pass.

Commit the atomic retirement:

```bash
git add -A server/desktop_app.py server/app.py desktop/main.py requirements-app.txt server/history.py server/lifecycle.py server/reference_db.py server/reference_adapter.py scripts/build_component_db.py reference/device_components.yaml reference/sources.yaml tests/test_history.py tests/test_lifecycle.py tests/test_desktop_api.py tests/test_assessment_api.py tests/test_reference_db.py tests/test_reference_adapter.py tests/test_reference_release.py tests/test_desktop_phone_api.py tests/test_desktop_integration_fixes.py tests/test_release_metadata.py tests/test_packaging.py tests/test_packaged_smoke.py tests/test_v1_retirement.py
git commit -m "refactor: retire version one product adapters"
```

- [ ] **Step 7: Re-review the retirement delta and establish the final clean source commit**

Have the independent reviewer inspect the parity result and v1-retirement commit, run the focused commands from Step 6, and update the review with the exact final reviewed commit and finding resolutions. No Critical or Important finding may remain. Commit only the factual review update, then run:

```bash
git add docs/reviews/2026-09-07-prototype-release-review.md
git commit -m "docs: finalize prototype release review"
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["-q"]))'
git diff --check
test -z "$(git status --porcelain=v1 --untracked-files=all)"
```

Expected: final source suite passes and the tree is clean. The temporary read-only metadata adapter is gone; no adapter exception extends into 0.2.0.

- [ ] **Step 8: Restage, build, and independently smoke the final 0.2.0 release**

Run:

```bash
.venv/bin/python scripts/prepare_release.py \
  --category-model-bundle .release-staging/model-t07-20260906 \
  --category-parity-report .release-staging/parity-t07-20260906.json \
  --condition-evaluation .release-staging/condition-manual-only-0.2.0/condition-evaluation.json \
  --knowledge-candidate .release-staging/knowledge-3.0.0 \
  --knowledge-approval reference/approved-release.json \
  --output-dir .release-staging/release-0.2.0 \
  --app-version 0.2.0
.venv/bin/python scripts/verify_macos_bundle.py \
  --release-dir .release-staging/release-0.2.0 \
  --expected-version 0.2.0 \
  --stage-only
./scripts/build_macos_app.sh --version 0.2.0 --release-dir .release-staging/release-0.2.0
.venv/bin/python scripts/verify_macos_bundle.py \
  --release-dir .release-staging/release-0.2.0 \
  --expected-version 0.2.0 \
  --app 'dist/E-Waste Triage.app'
EWASTE_PACKAGED_APP='dist/E-Waste Triage.app' \
  .venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["tests/test_packaged_smoke.py", "-q"]))'
```

Expected: verified arm64 app, complete authenticated offline v2 smoke, all v1 product paths absent, versioned DMG/release JSON/release notes, and no listeners or temporary files after shutdown.

- [ ] **Step 9: Compare the final DMG checksum independently**

Run:

```bash
/usr/bin/shasum -a 256 'dist/E-Waste Triage-0.2.0-arm64.dmg'
.venv/bin/python -c 'import json; print(json.load(open("dist/E-Waste Triage-0.2.0-arm64.json", encoding="utf-8"))["dmg_sha256"])'
```

Expected: the two lowercase SHA-256 values match exactly.

- [ ] **Step 10: Complete real hardware/manual acceptance**

Execute every item in the packaged `Prototype Acceptance Checklist.md` on the distributed DMG, not the development server. Save the filled record beside the release as `dist/E-Waste Triage-0.2.0-acceptance.md`, including tester, Mac model/macOS, date, source revision, release-manifest hash, DMG hash, screenshots/notes, and actual pass/fail for every item. Any failed required item or missing evidence blocks prototype completion.

- [ ] **Step 11: Archive one immutable release record**

Archive together the DMG, release JSON, release notes, acceptance record, release manifest/stage hashes, category parity, condition evaluation, knowledge coverage/change, independent review, source revision, and administrator procedures. Confirm the archived stage is read-only and document rollback as selecting an entire prior reviewed release, never mixing artifacts across versions.

## Integration and Conflict Notes

- This slice deliberately owns the single `components.sqlite` → `knowledge.sqlite` and manifest v1 → v2 cutover across `desktop/paths.py`, `desktop/main.py`, `desktop/release_metadata.py`, `scripts/prepare_release.py`, `scripts/verify_macos_bundle.py`, `scripts/render_release_notes.py`, `scripts/build_macos_app.sh`, `packaging/EWasteTriage.spec`, schema, fixtures, and docs. Assign Tasks 1–4 serially.
- After the first packaged parity run, Task 7 atomically removes the temporary v1 routes/adapters, schema-2 `ReferenceStore`/compiler/tests/source YAML, and PyYAML from `requirements-app.txt`; it preserves schema-3 authoring YAML and PyYAML in administrator `requirements.txt`.
- Slice 1 must not pre-edit those release-schema/package consumers. Start Task 1 from its legacy-v1-compatible state, consume its approved `KnowledgeReleaseInputs`, and remove every legacy release/package path only across this slice's Tasks 2–4. The temporary product v1 adapters are a separate migration boundary retired in Task 7 after packaged parity.
- Task 3 touches Slice 4’s `desktop/main.py`, `index.html`, `app.js`, and tests. Merge Slice 4 first and preserve its startup generations, mounted drafts, About focus return, and capability-cookie navigation.
- Use `KnowledgeStore` directly. Do not rename it back to `ReferenceStore`, do not retain schema-2 expectations, and do not package authoring YAML.
- Use the Slice 3 condition evaluation and model-manifest validators. Release code must not import PyTorch, dataset, training, or evaluation implementations into the live app.
- The first executable release is intentionally manual-only because no approved condition dataset exists. A later automated candidate uses the same manifest v2 union and adds only the two condition runtime files after passing its gate.
- The build script refuses a dirty tree. Commit implementation, documentation, and the accepted independent review before staging/building; keep generated acceptance evidence in ignored `dist/` so it cannot change the packaged source revision.
- Manual acceptance is a real completion gate. Automated package smoke, CSS inspection, or a development-app walkthrough cannot substitute for the fresh-account, Finder, VoiceOver, Reduce Motion, Local Network, real-phone, and offline DMG checks.

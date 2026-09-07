# Visible-Condition Rubric, Model, and Manual Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a truthful visible-exterior condition capability that always provides the five-level guided manual rubric, enables offline ONNX suggestions only after a leakage-safe evidence gate, and handles Mac and phone images through the same immutable analysis path.

**Architecture:** Treat a versioned deterministic rubric—not a directly predicted grade—as product truth. Admin-only PyTorch code learns five observable finding-severity heads plus an image-sufficiency head; evaluation derives grades through the rubric on a frozen device-grouped holdout, and export emits either a verified two-output ONNX bundle or an explicit manual-only manifest. The packaged runtime imports only Pillow/NumPy/ONNX Runtime and converts missing, corrupt, underpowered, insufficient, or low-confidence states into scoped condition results without disabling category analysis.

**Tech Stack:** Python 3.11, PyTorch 2.13.0, torchvision 0.28.0, ONNX 1.22.0, ONNX Runtime 1.29.0, NumPy 2.4.6, scikit-learn 1.5.1, Pillow 12.3.0, pytest 9.1.1

**Spec:** `docs/superpowers/specs/2026-09-06-ewaste-evidence-condition-prototype-design.md`

## Dependency Contract

This slice consumes the Slice 2 contracts in `server/scan_contract.py`, `server/analysis.py`, and `server/scan_service.py` from `docs/superpowers/plans/2026-09-06-scan-aggregate-v2.md`:

- `VisibleGrade`, `ImageSufficiency`, `CapabilityState`, `MachineVisibleFinding`, `ConditionCapability`, `MachineEvidence`, and the fixed public scope statement;
- `ConditionAnalyzer.analyze(image: Image.Image) -> ConditionCapability` and `AnalysisCoordinator`; and
- `ScanService.create_scan_from_analysis(image, machine_evidence, source, idempotency_key)` for the phone authorization race-safe persistence handoff.

Slice 1 evidence types and `KnowledgeStore` are not training inputs. Visible condition remains independent from lifecycle evidence, components, and hazards. Slice 4 may render these results, but it must not recreate grading logic in JavaScript. Slice 5 may package only the manifest/evaluation artifacts defined here.

## Global Constraints

- Released category IDs are exactly `0301_computer_mouse`, `0301_keyboard`, `0303_laptop`, `0306_mobile_phone`, and `0401_headphones`.
- Ordered grades are exactly Excellent, Good, Fair, Poor, and Critical; Unknown is separate.
- Human-readable grade definitions are exactly those in specification section 6.1 and appear verbatim in the labeling and manual-guidance contract.
- Public results always say `Visible exterior only`.
- Critical means severe visible exterior damage requiring cautious handling; it never claims an internal electrical, chemical, battery, material, or functional hazard.
- The model predicts observable finding severities and image sufficiency. It has no grade head. `grade_findings` deterministically derives the suggestion.
- Finding kinds are exactly `visible_crack`, `deformation`, `missing_exterior_part`, `corrosion_like_appearance`, and `surface_wear`.
- Severity labels are exactly `absent`, `minor`, `moderate`, `major`, and `severe`. Sufficiency labels are exactly `sufficient` and `insufficient`.
- Dataset boundaries are grouped by physical device and capture session. Raw-file and normalized-pixel duplicates cannot cross groups or splits.
- Training and checkpoint selection use train/validation only. The frozen holdout is consumed only by the separate evaluator.
- Holdout grade metrics weight each physical device equally, not each photo equally.
- Automated output requires macro-F1 at least 0.10 above the frozen majority-grade baseline, device-balanced Critical recall at least 0.70, and at least 30 independently grouped Critical devices.
- A missing candidate, failed gate, fewer than 30 Critical devices, parity failure, corrupt artifact, or runtime initialization failure yields a complete manual-only condition capability; it never blocks the product release.
- Production never trains, uploads corrections, exports local labels, downloads models, or changes weights online.
- Machine findings/confidence/provenance remain immutable. User grade/finding corrections stay separately attributed in Slice 2 user revisions.
- No licensed or first-party raw training image, checkpoint, ONNX file, prediction CSV, or error gallery is committed to git.

## Deterministic Rubric

For `image_sufficiency != sufficient`, the grade is Unknown. For a sufficient image, take the greatest severity among the five findings and map it exactly:

```text
all absent -> Excellent
minor      -> Good
moderate   -> Fair
major      -> Poor
severe     -> Critical
```

The approved descriptions are:

```text
Excellent — no meaningful visible wear or damage
Good — minor cosmetic wear without visible structural damage
Fair — moderate visible wear or limited visible damage
Poor — major visible damage likely to require inspection or repair
Critical — severe visible exterior damage requiring cautious handling
Unknown — image insufficient or condition capability unavailable
```

The rubric does not infer function, repairability, remaining life, component presence, or safety. A user may deliberately save a grade that differs from the machine-derived suggestion; both values remain visible and immutable in their respective layers.

## Manual Guidance API Contract

Slice 3 owns `GET /api/v2/condition-rubric` end to end: `server/condition_api.py` defines the route, Task 1 tests its standalone blueprint, and Task 6 registers it unconditionally in `server/desktop_app.py` for automated and manual-only launches. App-level Slice 2 capability-key middleware protects it. The GET is read-only, returns `Cache-Control: no-store`, and serializes `condition_guidance()` exactly:

```json
{
  "rubric_version": "visible-condition-v1",
  "scope_statement": "Visible exterior only",
  "grades": [
    {"value": "excellent", "label": "Excellent", "description": "no meaningful visible wear or damage"},
    {"value": "good", "label": "Good", "description": "minor cosmetic wear without visible structural damage"},
    {"value": "fair", "label": "Fair", "description": "moderate visible wear or limited visible damage"},
    {"value": "poor", "label": "Poor", "description": "major visible damage likely to require inspection or repair"},
    {"value": "critical", "label": "Critical", "description": "severe visible exterior damage requiring cautious handling"}
  ],
  "unknown": {"value": "unknown", "label": "Unknown", "description": "image insufficient or condition capability unavailable"},
  "finding_kinds": ["visible_crack", "deformation", "missing_exterior_part", "corrosion_like_appearance", "surface_wear"],
  "severity_labels": ["absent", "minor", "moderate", "major", "severe"],
  "image_sufficiency_labels": ["sufficient", "insufficient", "unknown"],
  "provenance": {"kind": "bundled_deterministic_rubric", "rubric_version": "visible-condition-v1", "content_sha256": "0000000000000000000000000000000000000000000000000000000000000000"}
}
```

`content_sha256` is SHA-256 over UTF-8 canonical JSON (`sort_keys=True`, separators `(',', ':')`) of every preceding response field except `provenance`. The UI renders these server-owned labels/descriptions and never hard-codes or recalculates them.

Every manual `ConditionCapability` returned inside `POST /api/v2/scans` includes:

```json
{
  "state": "unavailable",
  "suggested_grade": "unknown",
  "findings": [],
  "confidence": null,
  "image_sufficiency": "unknown",
  "scope_statement": "Visible exterior only",
  "provenance": {"engine_id": "manual_condition", "rubric_version": "visible-condition-v1", "guidance_content_sha256": "0000000000000000000000000000000000000000000000000000000000000000"},
  "unavailable_reason": "manual_only",
  "manual_guidance": {"required": true, "url": "/api/v2/condition-rubric", "rubric_version": "visible-condition-v1", "content_sha256": "0000000000000000000000000000000000000000000000000000000000000000"}
}
```

The closed `unavailable_reason` may instead be `missing_bundle`, `invalid_bundle`, or `runtime_unavailable`; all other fields remain identical. This is the first-release condition response because no qualified condition model exists.

## Dataset Manifest Contract

The reviewed input CSV header is exactly:

```text
image_path,device_group_id,capture_session_id,category_id,image_sufficiency,visible_crack,deformation,missing_exterior_part,corrosion_like_appearance,surface_wear,source_id,use_basis,license_or_consent_ref
```

`image_path` is a relative path beneath an explicitly supplied image root. `use_basis` is `licensed` or `first_party_consent`, and `license_or_consent_ref` is non-empty. Sufficient rows contain all five severity labels. Insufficient rows contain empty severity cells because an obstructed view cannot support a damage label. Output JSONL records add `raw_sha256`, `normalized_rgb_sha256`, `derived_grade`, and `split`; `derived_grade` is null for insufficient rows.

## Evaluation and Bundle Handoff

`condition-evaluation.json` is closed and has these top-level fields:

```json
{
  "schema_version": 1,
  "generated_at": "RFC-3339 UTC",
  "mode": "automated_candidate|manual_only",
  "model": {"model_id": null, "checkpoint_sha256": null, "architecture": null},
  "dataset": {"split_manifest_sha256": null, "holdout_manifest_sha256": null, "holdout_device_count": 0},
  "metrics": null,
  "critical_gate": {"independent_devices": 0, "device_balanced_recall": null},
  "gate": {
    "status": "passed|manual_only",
    "minimum_macro_f1_margin": 0.1,
    "minimum_critical_devices": 30,
    "minimum_critical_recall": 0.7,
    "reasons": ["no_qualified_candidate"]
  }
}
```

For an evaluated candidate, `metrics` contains `grade`, `findings`, `sufficiency`, `ordinal`, `calibration`, and `category_slices`; null is permitted only in manual-only mode. Slice 5 consumes `gate.status` and hashes rather than reimplementing the gate.

`manifest.json` in the runtime condition bundle is also closed:

```json
{
  "schema_version": 1,
  "mode": "automated|manual_only",
  "model_id": null,
  "architecture": null,
  "preprocessing_version": "rgb-224-v1",
  "rubric_version": "visible-condition-v1",
  "finding_kinds": ["visible_crack", "deformation", "missing_exterior_part", "corrosion_like_appearance", "surface_wear"],
  "severity_labels": ["absent", "minor", "moderate", "major", "severe"],
  "sufficiency_labels": ["sufficient", "insufficient"],
  "temperature": {"findings": null, "sufficiency": null},
  "confidence_floor": null,
  "artifact": null,
  "checkpoint_sha256": null,
  "dataset_manifest_sha256": null,
  "holdout_manifest_sha256": null,
  "evaluation_report_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
  "parity": null,
  "gate": {"status": "manual_only", "reasons": ["no_qualified_candidate"]}
}
```

An automated manifest replaces nullable model fields, temperature values, confidence floor, hashes, and parity with validated values; `artifact` has exactly the fields `filename` (the literal `model.onnx`) and `sha256` (64 lowercase hexadecimal characters). A manual-only manifest must have `artifact=null`, and an automated manifest must have `gate.status="passed"`.

The repository currently contains no reviewed visible-condition image corpus or qualified checkpoint. Therefore the first honest execution path is `--manual-only-reason no_qualified_candidate`; no task may fabricate candidate metrics or a passing gate. Automated mode becomes eligible only after administrators supply the reviewed out-of-repository data required by Tasks 2–4.

## File Structure

| File | Responsibility |
|---|---|
| `server/condition.py` | Finding/severity types, deterministic rubric, grade probabilities, and manual estimator |
| `server/condition_api.py` | Read-only `/api/v2/condition-rubric` blueprint over the canonical guidance object |
| `scripts/condition_model.py` | Admin-only PyTorch multi-head architecture; never imported by packaged runtime |
| `scripts/prepare_condition_dataset.py` | Rights validation, image hashing, deduplication, grouped split, and manifest hashes |
| `scripts/train_condition_model.py` | Deterministic train/validation-only fitting, calibration, and checkpoint selection |
| `scripts/evaluate_condition_model.py` | Frozen-holdout device-balanced metrics, gate, reports, and manual-only report |
| `scripts/export_condition_onnx.py` | Two-output ONNX export, parity checks, and atomic automated/manual bundle creation |
| `server/condition_bundle.py` | Closed manifest parsing, hash/gate validation, and manual-safe loader |
| `server/condition_inference.py` | ONNX Runtime inference and condition capability mapping |
| `desktop/paths.py` | Derived `condition_model_bundle_dir` resource property |
| `desktop/main.py` | Condition bundle assembly and scoped startup fallback |
| `server/analysis.py` | Runtime condition analyzer injection into the independent coordinator |
| `server/phone_app.py` | One normalized phone-image lifetime through analysis and callback |
| `server/desktop_app.py` | Race-safe phone-session reauthorization and scan persistence |
| `docs/CONDITION_LABELING_PROCEDURE.md` | Rubric, annotation, disagreement, rights, grouping, and QA procedure |
| `docs/MODEL_TRAINING_PROCEDURE.md` | Reproducible condition prepare/train/evaluate/export commands |
| `tests/test_condition.py` | Rubric, grade probability, language, and manual fallback tests |
| `tests/test_condition_api.py` | Exact guidance response, provenance hash, no-store, and read-only tests |
| `tests/test_condition_dataset.py` | Closed CSV, rights, duplicate, path, grouping, and deterministic split tests |
| `tests/test_condition_training.py` | Architecture, masking, reproducibility, calibration, and checkpoint tests |
| `tests/test_condition_evaluation.py` | Device-balanced metrics, baseline, Critical population, and gate tests |
| `tests/test_condition_onnx.py` | Manifest, hash, graph, parity, confidence, and fallback tests |
| `tests/test_analysis_coordinator.py` | Category/condition independence and provenance tests |
| `tests/test_desktop_phone_api.py` | Shared Mac/phone analysis path and revocation cleanup tests |

---

### Task 1: Implement the observable-finding rubric and complete manual fallback

**Files:**
- Create: `server/condition.py`
- Create: `server/condition_api.py`
- Create: `tests/test_condition.py`
- Create: `tests/test_condition_api.py`
- Create: `docs/CONDITION_LABELING_PROCEDURE.md`

**Interfaces:**
- `CONDITION_RUBRIC_VERSION = "visible-condition-v1"`
- `grade_findings(findings: Mapping[FindingKind, FindingSeverity], image_sufficiency: ImageSufficiency) -> VisibleGrade`
- `grade_probabilities(probabilities: np.ndarray) -> tuple[float, float, float, float, float]`
- `ManualConditionEstimator(reason: str).analyze(image: Image.Image) -> ConditionCapability`
- `condition_guidance() -> ConditionGuidance`
- `create_condition_blueprint(guidance_provider: Callable[[], ConditionGuidance] = condition_guidance) -> Blueprint`
- Route owned here: `GET /api/v2/condition-rubric`

- [ ] **Step 1: Write failing rubric, probability, copy, and fallback tests**

Parameterize all severity-to-grade mappings, every mixed-severity maximum, and insufficient/unknown states. Assert the five grade-probability values are finite, ordered as Excellent→Critical, and sum to one. Given independent per-finding cumulative probabilities, compute maximum-severity mass as:

```text
P(Excellent) = P(all findings absent)
P(Good)      = P(all findings <= minor)    - P(all findings absent)
P(Fair)      = P(all findings <= moderate) - P(all findings <= minor)
P(Poor)      = P(all findings <= major)    - P(all findings <= moderate)
P(Critical)  = 1                           - P(all findings <= major)
```

Assert `condition_guidance()` contains the approved descriptions verbatim and has the canonical content hash defined in Manual Guidance API Contract. Assert the public/manual result says `Visible exterior only`, has state unavailable and suggested grade Unknown, carries no numeric confidence, contains `manual_guidance` with the exact route/version/hash, and never contains the words `internal hazard`, `battery failure`, or `chemical danger`. In `tests/test_condition_api.py`, register `create_condition_blueprint()` on a test Flask app and assert exact keys/order-independent values, GET-only behavior, no-store, identical provenance hash, and zero mutation/provider side effects across repeated GETs.

```python
@pytest.mark.parametrize(
    ("severity", "grade"),
    [
        (FindingSeverity.ABSENT, VisibleGrade.EXCELLENT),
        (FindingSeverity.MINOR, VisibleGrade.GOOD),
        (FindingSeverity.MODERATE, VisibleGrade.FAIR),
        (FindingSeverity.MAJOR, VisibleGrade.POOR),
        (FindingSeverity.SEVERE, VisibleGrade.CRITICAL),
    ],
)
def test_rubric_maps_maximum_visible_severity(severity, grade):
    findings = {kind: FindingSeverity.ABSENT for kind in FindingKind}
    findings[FindingKind.VISIBLE_CRACK] = severity
    assert grade_findings(findings, ImageSufficiency.SUFFICIENT) is grade

def test_insufficient_image_is_unknown():
    findings = {kind: FindingSeverity.SEVERE for kind in FindingKind}
    assert grade_findings(findings, ImageSufficiency.INSUFFICIENT) is VisibleGrade.UNKNOWN
```

- [ ] **Step 2: Run rubric tests and verify RED**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_condition.py tests/test_condition_api.py -v
```

Expected: FAIL because `server.condition` and `server.condition_api` do not exist.

- [ ] **Step 3: Implement rubric, probability derivation, and manual guidance**

Import shared wire enums from `server.scan_contract`; do not declare competing grade strings. Validate that sufficient findings contain exactly one severity for every `FindingKind`. `grade_probabilities` accepts a finite `(5,5)` matrix whose rows sum to one and derives maximum-severity probabilities without a grade model. Clamp only floating-point residue, then renormalize.

`ManualConditionEstimator` ignores pixels, returns `CapabilityState.UNAVAILABLE`, Unknown, empty machine findings, Unknown image sufficiency, the fixed statement, `rubric_version`, and a sanitized closed reason (`manual_only`, `missing_bundle`, `invalid_bundle`, `runtime_unavailable`). It attaches the exact manual-guidance route/version/content hash but never assigns confidence to a user choice. `server/condition_api.py` serializes the same immutable `ConditionGuidance`; it owns no grading or persistence logic.

Write `docs/CONDITION_LABELING_PROCEDURE.md` with exact definitions, positive/negative examples for every finding/severity, obstruction rules, multi-view rules, physical-device and capture-session IDs, adjudication by a second trained reviewer, rights fields, class-balance review, and the separation among exterior condition, operation, components, lifecycle, and hazards.

- [ ] **Step 4: Run rubric tests and static compilation**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_condition.py tests/test_condition_api.py -v
.venv/bin/python -m py_compile server/condition.py server/condition_api.py
```

Expected: PASS for all grades, mixed findings, invalid mappings, probability mass, exact public language, manual reasons, route serialization/provenance/no-store, GET non-mutation, and non-hazard claims.

- [ ] **Step 5: Commit the rubric and manual capability**

```bash
git add server/condition.py server/condition_api.py tests/test_condition.py tests/test_condition_api.py docs/CONDITION_LABELING_PROCEDURE.md
git commit -m "feat: add visible condition rubric"
```

### Task 2: Prepare a licensed, duplicate-safe, grouped condition dataset

**Files:**
- Create: `scripts/prepare_condition_dataset.py`
- Create: `tests/test_condition_dataset.py`
- Modify: `docs/CONDITION_LABELING_PROCEDURE.md`
- Modify: `.gitignore`

**Interfaces:**
- `ConditionLabelRow.from_mapping(raw: Mapping[str, str]) -> ConditionLabelRow`
- `prepare_condition_dataset(labels_csv: Path, image_root: Path, output_dir: Path, *, seed: int = 20260907) -> DatasetSummary`
- Outputs: `train.jsonl`, `validation.jsonl`, `holdout.jsonl`, `dataset-summary.json`, and `split-manifest.json`
- CLI: `python scripts/prepare_condition_dataset.py --labels-csv PATH --image-root PATH --output-dir PATH --seed 20260907`

- [ ] **Step 1: Write failing schema, rights, duplicate, grouping, and determinism tests**

Generate small RGB JPEG/PNG fixtures only inside pytest temporary directories. Test exact CSV headers and reject missing/extra columns, absolute/traversal/symlink paths, undecodable/oversized images, invalid category/label values, sufficient rows with a blank finding, insufficient rows with a finding, blank group/session/source fields, unsupported `use_basis`, and absent rights references.

Assert raw-byte duplicates and differently encoded images with the same normalized RGB hash are rejected. Assert each `capture_session_id` maps to exactly one `device_group_id`, and neither group identifier crosses splits. Run preparation twice with the same seed and assert all JSONL bytes/hashes match; run with a different seed and assert membership may change while invariants remain.

```python
def test_physical_devices_and_sessions_never_cross_splits(tmp_path):
    fixture = write_condition_fixture(tmp_path, device_count=40)
    prepare_condition_dataset(fixture.csv, fixture.image_root, tmp_path / "out", seed=20260907)
    memberships = read_split_memberships(tmp_path / "out")
    for key in ("device_group_id", "capture_session_id"):
        assert memberships["train"][key].isdisjoint(memberships["validation"][key])
        assert memberships["train"][key].isdisjoint(memberships["holdout"][key])
        assert memberships["validation"][key].isdisjoint(memberships["holdout"][key])
```

- [ ] **Step 2: Run dataset tests and verify RED**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_condition_dataset.py -v
```

Expected: FAIL because the condition preparation pipeline does not exist.

- [ ] **Step 3: Implement validation, normalization hashes, and deterministic grouped splitting**

Resolve each relative path below `image_root` without following a symlink outside it. Read through `server.imaging.normalize_image`, hash original bytes and normalized RGB mode/width/height/pixels, and close every image. Refuse any duplicate hash rather than allowing photographic duplication to inflate support.

Group all rows by physical device before splitting. Summarize each group by category and derived grade. Deterministically sort groups by descending rarity and size, with `sha256(f"{seed}:{device_group_id}")` as the final tie-breaker. Greedily assign a whole group to the split that minimizes squared deviation from 70/15/15 targets across total images, categories, and grades; use train, validation, holdout as the fixed final tie order. Record realized counts and deviations rather than claiming exact ratios.

Write canonical sorted-key JSONL to a new empty staging directory, calculate each file hash, write `split-manifest.json` with seed/rubric/preprocessing/input-label hashes, write `dataset-summary.json` with rights/class/category/group counts, fsync, then atomically rename. Refuse a non-empty destination. Add `/data/condition/`, `/models/condition/`, `/build/condition-*`, checkpoints, ONNX files, prediction CSVs, and generated error galleries to `.gitignore`.

- [ ] **Step 4: Run dataset and image-safety tests**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_condition_dataset.py tests/test_imaging.py tests/test_training_exif_orientation.py -v
.venv/bin/python -m py_compile scripts/prepare_condition_dataset.py
```

Expected: PASS for strict schema, rights, hashes, EXIF normalization, duplicate rejection, grouped membership, deterministic bytes, atomic output, and cleanup after failure.

- [ ] **Step 5: Commit dataset preparation**

```bash
git add scripts/prepare_condition_dataset.py tests/test_condition_dataset.py docs/CONDITION_LABELING_PROCEDURE.md .gitignore
git commit -m "feat: prepare grouped condition data"
```

### Task 3: Train finding-severity and sufficiency heads without a grade head

**Files:**
- Create: `scripts/condition_model.py`
- Create: `scripts/train_condition_model.py`
- Create: `tests/test_condition_training.py`

**Interfaces:**
- `ConditionNetwork(architecture: str = "efficientnet_b0", pretrained: bool = True)`
- `ConditionNetwork.forward(images: Tensor) -> tuple[Tensor, Tensor]`
- Output shapes: `finding_logits=(N,5,5)` and `sufficiency_logits=(N,2)`
- `train_condition_model(train_manifest: Path, validation_manifest: Path, output_dir: Path, config: TrainingConfig) -> CheckpointSummary`
- CLI: `python scripts/train_condition_model.py --train-jsonl PATH --validation-jsonl PATH --output-dir PATH --seed 20260907 --epochs N [--no-pretrained]`

- [ ] **Step 1: Write failing architecture, masking, seed, and checkpoint tests**

Assert no module or checkpoint key contains `grade_head` or `grade_logits`. With a batch of two 224×224 tensors, assert exact two-output shapes. Assert finding cross-entropy ignores the insufficient sample while sufficiency cross-entropy includes both. Assert the trainer accepts only train and validation paths, rejects any overlapping device/session IDs or manifest-hash mismatch, and never accepts a holdout argument.

Run two CPU smoke fits with identical synthetic manifests/config and assert selected epoch, state-dict tensors, validation predictions, and checkpoint metadata hashes match. Verify checkpoint selection orders candidates by derived five-grade validation macro-F1, then Critical recall, sufficiency balanced accuracy, then earliest epoch.

```python
def test_network_has_only_observable_outputs():
    model = ConditionNetwork(architecture="efficientnet_b0", pretrained=False)
    finding_logits, sufficiency_logits = model(torch.zeros(2, 3, 224, 224))
    assert finding_logits.shape == (2, 5, 5)
    assert sufficiency_logits.shape == (2, 2)
    assert all("grade" not in name for name, _parameter in model.named_parameters())
```

- [ ] **Step 2: Run training tests and verify RED**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_condition_training.py tests/test_training_seed.py -v
```

Expected: FAIL because the multi-head architecture and condition trainer do not exist.

- [ ] **Step 3: Implement deterministic train/validation fitting and calibration**

Keep every Torch/torchvision import under `scripts/`; packaged server modules must not import them. Use an EfficientNet-B0 backbone and two linear heads. Initially freeze the backbone, then optionally unfreeze only its final two feature blocks according to explicit config. Seed Python, NumPy, Torch, data-loader generators, and workers; request deterministic algorithms and document any unsupported operation as a hard error.

For sufficient samples, sum class-weighted cross-entropy across the five severity heads. Mask finding loss for insufficient samples and always calculate sufficiency loss. Weight/sampling statistics use train only and balance physical devices before photos. Derive validation grades through `grade_findings`; never optimize a grade head. Select the checkpoint by the exact ordering tested above.

Fit one positive finite `findings` temperature and one `sufficiency` temperature on validation logits only. Freeze in the checkpoint: schema version, architecture, finding/severity/sufficiency order, rubric/preprocessing versions, train/validation/split-manifest hashes, majority baseline grade computed from device-balanced training labels, seed, config, selected epoch, temperatures, confidence-floor selection rule, state dict, and validation metrics. Do not open/import `holdout.jsonl` anywhere in the trainer.

- [ ] **Step 4: Run architecture, deterministic smoke, and import-boundary tests**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_condition_training.py tests/test_training_seed.py tests/test_packaging.py -v
.venv/bin/python -m py_compile scripts/condition_model.py scripts/train_condition_model.py
```

Expected: PASS for output shape, masking, train-only weighting, grouped validation, deterministic CPU smoke, checkpoint selection, calibration, no holdout access, and no Torch import in packaged runtime modules.

- [ ] **Step 5: Commit training tooling**

```bash
git add scripts/condition_model.py scripts/train_condition_model.py tests/test_condition_training.py
git commit -m "feat: train observable condition findings"
```

### Task 4: Evaluate the frozen holdout and enforce the release gate

**Files:**
- Create: `scripts/evaluate_condition_model.py`
- Create: `tests/test_condition_evaluation.py`
- Modify: `docs/MODEL_TRAINING_PROCEDURE.md`

**Interfaces:**
- `evaluate_condition_checkpoint(checkpoint_path: Path, holdout_manifest: Path, output_dir: Path) -> ConditionEvaluation`
- `evaluate_release_gate(evaluation: ConditionEvaluation) -> GateResult`
- `write_manual_only_evaluation(output_dir: Path, reason: ManualOnlyReason, *, dataset_summary: Path | None = None) -> Path`
- Outputs: `condition-evaluation.json`, `condition-evaluation.md`, `predictions.csv`, `confusion-matrix.png`, and `error-gallery/index.html` for a candidate; only JSON/Markdown for manual-only
- CLI candidate mode: `python scripts/evaluate_condition_model.py --checkpoint PATH --holdout-jsonl PATH --output-dir PATH`
- CLI fallback mode: `python scripts/evaluate_condition_model.py --manual-only-reason no_qualified_candidate --output-dir PATH`

- [ ] **Step 1: Write failing metric, baseline, Critical population, and gate tests**

Create table-driven predictions where one physical device has many photos and prove it receives the same total macro-metric weight as a one-photo device. Grade predictions come only from severity argmax plus `grade_findings`. Use the training-frozen majority grade as the baseline, never a holdout-selected grade.

Define a Critical device as a distinct `device_group_id` with at least one sufficient ground-truth Critical photo. Its recall is Critical true positives divided by Critical ground-truth photos for that device; the reported device-balanced Critical recall is the mean of those per-device recalls. Test the exact inclusive thresholds:

```python
def test_release_gate_is_inclusive_and_conjunctive():
    passing = evaluation(
        macro_f1=0.60,
        majority_macro_f1=0.50,
        critical_device_recall=0.70,
        critical_device_count=30,
    )
    assert evaluate_release_gate(passing).status == "passed"
    assert evaluate_release_gate(replace(passing, macro_f1=0.5999)).status == "manual_only"
    assert evaluate_release_gate(replace(passing, critical_device_recall=0.6999)).status == "manual_only"
    assert evaluate_release_gate(replace(passing, critical_device_count=29)).status == "manual_only"
```

Assert manual-only mode writes exact threshold fields and a closed reason, contains no fabricated metric, and creates no predictions/error gallery.

- [ ] **Step 2: Run evaluation tests and verify RED**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_condition_evaluation.py -v
```

Expected: FAIL because the condition evaluator and release gate do not exist.

- [ ] **Step 3: Implement device-balanced reports and the honest manual-only artifact**

Verify checkpoint/schema/rubric/preprocessing/split hashes before inference. Give each image weight `1 / image_count_for_device` for fixed-label five-grade precision/recall/F1 and normalize only when presenting aggregate values. Report the train-frozen majority baseline with the same holdout weights. Calculate per-finding/per-severity metrics, sufficiency precision/recall/F1, grade macro-F1, all per-grade values/support, ordinal confusion matrix and mean absolute ordinal error, calibrated finding/sufficiency ECE and Brier scores, category slices, rights/source coverage, and representative false positives/negatives.

Write the exact Evaluation and Bundle Handoff schema. Gate passes only when all three comparisons are true; populate stable reasons `macro_f1_margin_below_0_10`, `critical_device_count_below_30`, and `critical_recall_below_0_70`. `write_manual_only_evaluation` accepts only `no_qualified_candidate`, `dataset_unavailable`, or `evaluation_unavailable` and leaves all model/hash/metric fields null rather than claiming a test occurred.

Reports include generation time and hashes, so byte-for-byte determinism applies to predictions and metrics excluding the explicit timestamp. Refuse to overwrite non-empty output and atomically publish a complete report directory.

- [ ] **Step 4: Run evaluator, gate, and CLI tests**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_condition_evaluation.py tests/test_holdout_alignment.py tests/test_evaluate_classifier.py -v
.venv/bin/python -m py_compile scripts/evaluate_condition_model.py
```

Expected: PASS for device/photo imbalance, fixed-label macro-F1, frozen baseline, exactly 29/30 Critical groups, exactly 0.6999/0.70 recall, category slices, calibration, report schema, and manual-only truthfulness.

- [ ] **Step 5: Commit evaluation and gate tooling**

```bash
git add scripts/evaluate_condition_model.py tests/test_condition_evaluation.py docs/MODEL_TRAINING_PROCEDURE.md
git commit -m "feat: gate visible condition automation"
```

### Task 5: Export a verified ONNX bundle or an explicit manual-only bundle

**Files:**
- Create: `scripts/export_condition_onnx.py`
- Create: `server/condition_bundle.py`
- Create: `server/condition_inference.py`
- Create: `tests/test_condition_onnx.py`

**Interfaces:**
- `ConditionBundleManifest.from_mapping(raw: object) -> ConditionBundleManifest`
- `export_condition_bundle(checkpoint_path: Path | None, evaluation_path: Path, output_dir: Path, reference_images: Sequence[Path]) -> ConditionBundleManifest`
- Automated artifact: `output_dir / "model.onnx"`; manual-only output contains no ONNX file
- `load_condition_estimator(bundle_dir: Path) -> OnnxConditionEstimator | ManualConditionEstimator`
- `OnnxConditionEstimator.analyze(image: Image.Image) -> ConditionCapability`
- CLI: `python scripts/export_condition_onnx.py --evaluation PATH --output-dir PATH [--checkpoint PATH --reference-image PATH]`

- [ ] **Step 1: Write failing closed-manifest, graph, parity, and fallback tests**

Test rejection of unknown/missing fields, booleans as numbers, non-finite temperature/confidence/parity, wrong label order, unsupported preprocessing/rubric, failed evaluation paired with an artifact, passed evaluation without an artifact, wrong hash, path traversal filename, extra/missing ONNX input/output, dynamic/wrong shapes, and logits containing NaN/Inf.

Assert the graph is fixed exactly to input `image: float32[1,3,224,224]` and outputs `finding_logits: float32[1,5,5]` plus `sufficiency_logits: float32[1,2]`. Assert opset 17. Across every required reference image, calibrated PyTorch and ONNX probabilities differ by at most `0.0001`, severity/sufficiency argmax labels match, and rubric-derived grades match.

```python
def test_failed_gate_can_only_export_manual_bundle(tmp_path):
    manifest = export_condition_bundle(None, failed_evaluation_path, tmp_path / "bundle", ())
    assert manifest.mode == "manual_only"
    assert manifest.artifact is None
    assert not (tmp_path / "bundle" / "model.onnx").exists()

def test_onnx_has_no_grade_output(valid_onnx_bundle):
    session = onnxruntime.InferenceSession(str(valid_onnx_bundle / "model.onnx"))
    assert [output.name for output in session.get_outputs()] == ["finding_logits", "sufficiency_logits"]
```

- [ ] **Step 2: Run ONNX tests and verify RED**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_condition_onnx.py -v
```

Expected: FAIL because the exporter, manifest parser, and runtime estimator do not exist.

- [ ] **Step 3: Implement atomic export, strict loading, and calibrated inference**

For `gate.status="passed"`, require checkpoint/evaluation/split hashes to agree, export opset 17 as `model.onnx` into a staging directory, check graph names/types/shapes, run reference parity after temperatures, calculate artifact/report hashes, write an automated manifest whose artifact filename is exactly `model.onnx`, fsync, and atomically promote. Do not provide a force/override flag. For manual-only evaluation, reject a checkpoint/reference image and write only a manual manifest with exact reasons and report hash.

`ConditionBundleManifest.from_mapping` enforces the closed schema in Evaluation and Bundle Handoff. `load_condition_estimator` returns `ManualConditionEstimator` for a valid manual bundle. Missing/unreadable/corrupt directories are converted by desktop assembly into the corresponding manual reason; `OnnxConditionEstimator` itself raises `ConditionBundleError` so tests can distinguish corruption.

At runtime, use the shared `rgb-224-v1` transform once, apply frozen temperatures, take five severity argmax values, derive grade only through `grade_findings`, and derive grade confidence from `grade_probabilities`. If predicted sufficiency is insufficient, return `low_confidence`, Unknown, and no asserted findings. If sufficient and grade confidence is below the manifest floor, return `low_confidence` with the rubric-derived suggestion and explicit uncertainty. Otherwise return `ready`. Include model ID, artifact SHA-256, preprocessing/rubric versions, calibrated finding confidence, sufficiency confidence, and `Visible exterior only`.

- [ ] **Step 4: Run ONNX, inference, imaging, and packaging-boundary tests**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_condition_onnx.py tests/test_condition.py tests/test_imaging.py tests/test_onnx_inference.py tests/test_packaging.py -v
.venv/bin/python -m py_compile scripts/export_condition_onnx.py server/condition_bundle.py server/condition_inference.py
```

Expected: PASS for automated/manual modes, graph shape, parity boundary, hashes, corrupt output, insufficient images, confidence floor, provenance, orientation, and runtime imports without Torch.

- [ ] **Step 5: Commit export and runtime inference**

```bash
git add scripts/export_condition_onnx.py server/condition_bundle.py server/condition_inference.py tests/test_condition_onnx.py
git commit -m "feat: run gated condition inference offline"
```

### Task 6: Assemble condition inference for Mac and phone scans with manual-safe startup

**Files:**
- Modify: `desktop/paths.py`
- Modify: `desktop/main.py`
- Modify: `server/analysis.py`
- Modify: `server/phone_app.py`
- Modify: `server/desktop_app.py`
- Modify: `tests/test_condition_api.py`
- Modify: `tests/test_analysis_coordinator.py`
- Modify: `tests/test_desktop_integration_fixes.py`
- Modify: `tests/test_desktop_phone_api.py`
- Modify: `tests/test_phone_app.py`
- Modify: `tests/test_packaging.py`
- Modify: `docs/MODEL_TRAINING_PROCEDURE.md`

**Interfaces:**
- `AppPaths.condition_model_bundle_dir` property returns `resources_dir / "models" / "condition"`
- `build_condition_analyzer(bundle_dir: Path) -> OnnxConditionEstimator | ManualConditionEstimator`
- `ScanService.create_scan_from_analysis(image: Image.Image, machine_evidence: MachineEvidence, source: ScanSource, idempotency_key: str) -> ScanAggregateView`
- `create_desktop_app` unconditionally registers `create_condition_blueprint(condition_guidance)`
- Existing `create_phone_app(sessions, classify_image, receive_result) -> Flask` callback shape remains compatible

- [ ] **Step 1: Write failing startup, independence, shared-phone-image, and cleanup tests**

Do not add a dataclass field to `AppPaths`; existing tests instantiate it positionally. Assert the derived property points into immutable resources. Parameterize absent directory, manual manifest, corrupt JSON, wrong hash, ONNX initialization error, and passed bundle: every failure except the category classifier returns a working desktop app whose condition state is unavailable/manual; a valid bundle returns ready/low-confidence according to inference. In every mode, assert an authorized `GET /api/v2/condition-rubric` returns the exact Task 1 payload, an unauthenticated GET returns 404, and the scan's `manual_guidance.content_sha256` equals the route provenance hash.

For phone upload, instrument category and condition analyzers and assert both see the same normalized orientation/pixels before their independent copies close. Assert the coordinator runs once, the accepted upload receives one generated canonical UUID idempotency key, machine evidence is persisted once only after phone-session reauthorization, public phone response preserves its existing `prediction` compatibility field, and desktop inbox receives the v2 scan result. Revoke the token while analysis is blocked and assert no scan, thumbnail, OCR/condition evidence, temp upload, result inbox entry, or listener survives.

```python
def test_missing_condition_bundle_does_not_disable_category(desktop_app):
    client = authorized_client(desktop_app, "launch-a")
    response = post_scan(client, jpeg_bytes())
    assert response.status_code == 201
    assert response.json["analysis"]["category"]["state"] == "ready"
    assert response.json["analysis"]["condition"]["state"] == "unavailable"
    assert response.json["analysis"]["condition"]["suggested_grade"] == "unknown"

def test_phone_revocation_before_persistence_discards_analysis(phone_desktop):
    phone_desktop.condition_analyzer.block()
    upload = phone_desktop.begin_upload()
    phone_desktop.sessions.stop()
    phone_desktop.condition_analyzer.release()
    assert upload.result().status_code == 404
    assert phone_desktop.repository.list_scans() == ()
```

- [ ] **Step 2: Run assembly/phone/packaging tests and verify RED**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_condition_api.py tests/test_analysis_coordinator.py tests/test_desktop_integration_fixes.py tests/test_desktop_phone_api.py tests/test_phone_app.py tests/test_packaging.py -v
```

Expected: FAIL because desktop assembly has no condition bundle path/estimator, has not registered the condition-rubric blueprint, and phone completion still performs category-only analysis.

- [ ] **Step 3: Integrate condition without widening the startup failure domain**

Add only the derived `AppPaths.condition_model_bundle_dir` property. In `build_desktop_app`, load condition after the mandatory category model. Convert `FileNotFoundError`, `ConditionBundleError`, and expected ONNX initialization errors to `ManualConditionEstimator`; do not route them through model/reference recovery. Inject the estimator into `AnalysisCoordinator` and expose sanitized condition mode/model/rubric diagnostics. Register `create_condition_blueprint(condition_guidance)` unconditionally in `create_desktop_app`; do not make route availability depend on an ONNX artifact.

Keep `create_phone_app` normalization and `finally` closure. Change its analysis callback implementation in `server/desktop_app.py` to run the full coordinator once, place the immutable `MachineEvidence` plus the still-live normalized image and one `uuid.uuid4()` idempotency key in request-local state, and return the existing category prediction to the phone. In `receive_result`, pop request-local state, reacquire the phone-operation lock, reauthorize token/code, and only then call `ScanService.create_scan_from_analysis(image, machine_evidence, ScanSource.PHONE, idempotency_key)`. An unauthorized race aborts without persistence; all branches close/clear state. Do not run the category or condition model twice.

Document exact admin commands in `docs/MODEL_TRAINING_PROCEDURE.md`: prepare, train, evaluate, export; how to produce manual-only evaluation without data; required review of licenses/error gallery; gate interpretation; artifact hashes; and the prohibition on copying raw data or local corrections into the app bundle.

- [ ] **Step 4: Run slice tests, the full suite, and artifact hygiene checks**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' tests/test_condition.py tests/test_condition_api.py tests/test_condition_dataset.py tests/test_condition_training.py tests/test_condition_evaluation.py tests/test_condition_onnx.py tests/test_analysis_coordinator.py tests/test_desktop_integration_fixes.py tests/test_desktop_phone_api.py tests/test_phone_app.py tests/test_packaging.py -q
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' -q
.venv/bin/python -m py_compile server/condition.py server/condition_api.py server/condition_bundle.py server/condition_inference.py server/analysis.py server/phone_app.py server/desktop_app.py desktop/paths.py desktop/main.py scripts/condition_model.py scripts/prepare_condition_dataset.py scripts/train_condition_model.py scripts/evaluate_condition_model.py scripts/export_condition_onnx.py
git ls-files 'data/condition/**' 'models/condition/**' '*.pt' '*.onnx' '*predictions.csv' '*error-gallery*'
git diff --check
```

Expected: all tests pass; the artifact-hygiene command prints no raw condition data, checkpoint, generated ONNX, predictions, or error gallery; a real passed gate loads automated inference, while absent/failed/unqualified artifacts produce the complete manual rubric and registered guidance route; Mac and phone scans preserve independent category and condition evidence with no leaked image or live phone session.

- [ ] **Step 5: Commit visible-condition integration**

```bash
git add desktop/paths.py desktop/main.py server/analysis.py server/phone_app.py server/desktop_app.py tests/test_condition_api.py tests/test_analysis_coordinator.py tests/test_desktop_integration_fixes.py tests/test_desktop_phone_api.py tests/test_phone_app.py tests/test_packaging.py docs/MODEL_TRAINING_PROCEDURE.md
git commit -m "feat: integrate manual-safe visible condition"
```

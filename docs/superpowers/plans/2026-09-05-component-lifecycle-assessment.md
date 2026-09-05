# Component Lifecycle Assessment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add standardized, versioned component templates for the five released device categories and an editable, evidence-aware lifecycle and reuse assessment.

**Architecture:** Maintain reviewed YAML as the admin source of truth, compile it into a read-only SQLite reference database for releases, and snapshot the chosen category template into local scan history. A deterministic lifecycle engine produces ranges, confidence, evidence provenance, and conservative next steps without pretending that the exterior-photo classifier measured hidden condition.

**Tech Stack:** Python 3.11, PyYAML 6.0.3, SQLite, Flask 3.1.3, vanilla HTML/CSS/JavaScript, pytest 9.1.1

**Spec:** `docs/superpowers/specs/2026-09-05-ewaste-triage-mac-app-design.md`

## Global Constraints

- Initial templates cover computer mouse, keyboard, laptop, mobile phone, and headphones.
- Standard templates are admin-authored and read-only in the user app.
- User edits affect only the item-specific snapshot stored in local history.
- Every non-null lifecycle value and safety rule requires a source ID, review date, and evidence grade.
- Category-level components are described as commonly associated, never visually detected.
- Ranges replace unsupported exact percentages; insufficient evidence returns `Unknown`.
- Safety escalation precedes reuse recommendations and cannot be cleared by image confidence.
- The classifier supplies device category only; automated condition inference is out of scope.
- Reference data and model data update only through normal app releases.

## File structure

| File | Responsibility |
|---|---|
| `reference/sources.yaml` | Reviewed source registry with URLs, titles, publishers, and dates |
| `reference/device_components.yaml` | Five category templates and component rules |
| `server/reference_db.py` | YAML validation, compilation, and read-only queries |
| `scripts/build_component_db.py` | Admin command that atomically builds the release SQLite database |
| `server/lifecycle.py` | Range, confidence, provenance, and recommendation rules |
| `server/history.py` | Assessment snapshot and revision persistence alongside scans |
| `server/app.py` | Reference and assessment API endpoints |
| `server/static/index.html` | Assessment navigation and semantic form structure |
| `server/static/app.css` | Assessment, component, safety, and animation styling |
| `server/static/app.js` | Editable assessment state and animated result population |
| `tests/test_reference_db.py` | Schema, source, category, and immutability tests |
| `tests/test_lifecycle.py` | Boundary calculations and conservative policy tests |
| `tests/test_assessment_api.py` | Snapshot, edit, and history reproducibility contracts |
| `tests/test_assessment_ui.py` | Required copy, controls, accessibility, and motion hooks |

---

### Task 1: Versioned component-reference compiler

**Files:**
- Create: `reference/sources.yaml`
- Create: `reference/device_components.yaml`
- Create: `server/reference_db.py`
- Create: `scripts/build_component_db.py`
- Test: `tests/test_reference_db.py`

**Interfaces:**
- Produces: `compile_reference(source_dir: Path, destination: Path) -> ReferenceManifest`
- Produces: `ReferenceStore(database_path: Path)` opened read-only
- Produces: `ReferenceStore.get_category(category_id: str) -> dict | None`
- Produces: `ReferenceStore.list_categories() -> list[dict]`
- Produces: `ReferenceStore.snapshot(category_id: str) -> dict`
- Raises: `ReferenceValidationError` with source filename and record path

- [ ] **Step 1: Write failing source, schema, and category tests**

```python
EXPECTED = {
    "0301_computer_mouse", "0301_keyboard", "0303_laptop",
    "0306_mobile_phone", "0401_headphones",
}

def test_release_reference_contains_exactly_five_categories(tmp_path):
    manifest = compile_reference(ROOT / "reference", tmp_path / "components.sqlite")
    store = ReferenceStore(tmp_path / "components.sqlite")
    assert {row["category_id"] for row in store.list_categories()} == EXPECTED
    assert manifest.schema_version == 1

def test_non_null_lifecycle_requires_a_source(tmp_path):
    fixture = copy_reference_fixture(tmp_path)
    fixture["categories"][0]["components"][0]["lifecycle"] = {
        "metric": "cycles", "minimum": 800, "maximum": 800,
    }
    with pytest.raises(ReferenceValidationError, match="source_ids"):
        compile_reference(tmp_path, tmp_path / "bad.sqlite")
```

- [ ] **Step 2: Run the compiler tests and confirm the module is absent**

Run: `.venv/bin/pytest tests/test_reference_db.py -v`

Expected: FAIL because `server.reference_db` does not exist.

- [ ] **Step 3: Implement strict YAML validation and atomic SQLite compilation**

The source registry begins with these reviewed primary sources:

- `epa_used_li_ion_2026` — `https://www.epa.gov/recycle/used-lithium-ion-batteries`
- `epa_electronics_management_2026` — `https://www.epa.gov/electronics-batteries-management`
- `eu_rohs_current` — `https://environment.ec.europa.eu/topics/waste-and-recycling/rohs-directive_en`
- `eu_phone_ecodesign_2023_1670` — `https://eur-lex.europa.eu/legal-content/EN/LSU/?uri=CELEX:32023R1670`
- `apple_mac_battery_cycles_2026` — `https://support.apple.com/en-au/102888`

Seed the exact category/component structure below. `null` lifecycle means the app must
display `Unknown` until an item-specific documented reference or diagnostic is supplied.

```yaml
categories:
  - category_id: 0301_computer_mouse
    components: [enclosure, pcb_controller, optical_sensor, switches, scroll_wheel,
                 cable_or_wireless_module, removable_or_rechargeable_battery]
  - category_id: 0301_keyboard
    components: [enclosure, keycaps, key_switches, pcb_controller,
                 cable_or_wireless_module, removable_or_rechargeable_battery]
  - category_id: 0303_laptop
    components: [enclosure, display_assembly, keyboard_trackpad, logic_board,
                 memory, storage, cooling_assembly, speakers, power_adapter,
                 lithium_ion_battery]
  - category_id: 0306_mobile_phone
    components: [enclosure, display_assembly, logic_board, storage, camera_modules,
                 speakers_microphones, vibration_motor, lithium_ion_battery]
  - category_id: 0401_headphones
    components: [enclosure_headband, ear_cushions, audio_drivers, pcb_controls,
                 cable_or_wireless_module, charging_case, lithium_ion_battery]
```

Mark batteries optional for wired mice, wired keyboards, and wired headphones. Give the
mobile-phone battery an `800 cycles to 80% capacity` reference from the EU rule, with
evidence grade `regulatory_minimum`; keep other generic component lifecycle values null.
Add category-level potential-substance context from EPA/RoHS as a handling note, not a
claim that a photographed item contains a specific substance. Add the EPA battery rule
that lithium-ion batteries should not enter household trash or municipal recycling.

Compile into normalized tables `metadata`, `sources`, `categories`, `components`,
`category_components`, and `rules`. Write to a temporary sibling, fsync, then replace the
destination only after validation and integrity checks succeed.

- [ ] **Step 4: Run compiler tests and inspect all emitted categories**

Run: `.venv/bin/pytest tests/test_reference_db.py -v`

Run: `.venv/bin/python scripts/build_component_db.py --source reference --out build/components.sqlite --print-summary`

Expected: PASS and a summary of exactly five categories with no unsourced non-null ranges.

- [ ] **Step 5: Commit source data and compiler**

```bash
git add reference server/reference_db.py scripts/build_component_db.py tests/test_reference_db.py
git commit -m "feat: add versioned component reference database"
```

### Task 2: Explainable lifecycle range engine

**Files:**
- Create: `server/lifecycle.py`
- Test: `tests/test_lifecycle.py`

**Interfaces:**
- Produces: `AssessmentInputs(age_months: Range | None, usage: Usage, condition: Condition, operational: OperationalState, diagnostics: tuple[Diagnostic, ...])`
- Produces: `LifecycleResult(percent_used: Range | None, confidence: Confidence, evidence: tuple[Evidence, ...], recommendation: Recommendation, reasons: tuple[str, ...])`
- Produces: `assess_component(component: Mapping, inputs: AssessmentInputs) -> LifecycleResult`
- Enums: `Usage = unknown|light|moderate|heavy`, `Condition = unknown|no_visible_damage|visible_wear|damaged`, `OperationalState = unknown|working|intermittent|not_working`, `Confidence = unavailable|low|moderate|high`

- [ ] **Step 1: Write failing boundary and honesty tests**

```python
def test_year_range_uses_conservative_interval_math():
    component = component_with_life_years(4, 6)
    result = assess_component(component, inputs(age_months=Range(24, 36)))
    assert result.percent_used == Range(33, 75)
    assert result.confidence is Confidence.MODERATE

def test_missing_lifecycle_returns_unknown_not_a_guess():
    result = assess_component(component_with_lifecycle(None), inputs(age_months=Range(24, 36)))
    assert result.percent_used is None
    assert result.confidence is Confidence.UNAVAILABLE

def test_damaged_safety_sensitive_component_blocks_reuse():
    result = assess_component(lithium_battery(), inputs(condition=Condition.DAMAGED))
    assert result.recommendation is Recommendation.SPECIALIST_HANDLING
    assert "photo confidence" not in " ".join(result.reasons).lower()
```

- [ ] **Step 2: Run lifecycle tests and confirm the module is absent**

Run: `.venv/bin/pytest tests/test_lifecycle.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement deterministic range and recommendation rules**

Use outward-rounded integer intervals. For year-based references:

```python
low = floor(100 * age.minimum / life.maximum)
high = ceil(100 * age.maximum / life.minimum)
base = Range(max(0, low), min(100, high))
```

For cycle-based references, calculate only when the user supplies a cycle-count range.
Usage is displayed as evidence but does not numerically shift a sourced range until a
source-backed usage rule exists. Apply these explicit conservative policies:

- unknown visible condition widens a supported interval by 15 percentage points each way
  and lowers confidence one level;
- visible wear widens the upper bound by 10 points and lowers confidence one level;
- intermittent operation forces `DIAGNOSTIC_TEST` and prevents `LIKELY_REUSABLE`;
- damaged or not-working safety-sensitive components return
  `SPECIALIST_HANDLING` and do not report a lifecycle percentage;
- a supported diagnostic tagged `measured` overrides age-based estimation and yields high
  confidence, while preserving the original estimate in evidence provenance.

Every result includes human-readable reasons and evidence kinds. Never use the model's
class confidence as component-health evidence.

- [ ] **Step 4: Run full lifecycle tests**

Run: `.venv/bin/pytest tests/test_lifecycle.py -v`

Expected: PASS at 0%, 100%, missing, conflicting, damaged, and measured boundaries.

- [ ] **Step 5: Commit the lifecycle engine**

```bash
git add server/lifecycle.py tests/test_lifecycle.py
git commit -m "feat: estimate explainable component lifecycle ranges"
```

### Task 3: Assessment snapshots and API

**Files:**
- Modify: `server/history.py`
- Modify: `server/app.py`
- Test: `tests/test_assessment_api.py`
- Modify: `tests/test_history.py`

**Interfaces:**
- Produces: `HistoryStore.create_assessment(scan_id: str, template: Mapping) -> dict`
- Produces: `HistoryStore.update_assessment(scan_id: str, inputs: Mapping, component_overrides: Mapping) -> dict`
- Produces API: `GET /api/v1/reference/categories`, `GET /api/v1/reference/categories/<category_id>`
- Produces API: `GET/PUT /api/v1/scans/<scan_id>/assessment`
- Consumes: `ReferenceStore.snapshot()` and `assess_component()`

- [ ] **Step 1: Write failing snapshot reproducibility and validation tests**

```python
def test_assessment_keeps_original_template_revision_after_reference_update(client, stores):
    scan_id = create_phone_scan(client)
    first = client.get(f"/api/v1/scans/{scan_id}/assessment").json
    stores.reference.replace_with_revision("2.0.0")
    second = client.get(f"/api/v1/scans/{scan_id}/assessment").json
    assert second["template_version"] == first["template_version"]
    assert second["components"] == first["components"]

def test_invalid_user_enum_is_rejected(client, scan_id):
    response = client.put(f"/api/v1/scans/{scan_id}/assessment",
                          json={"usage": "extreme"})
    assert response.status_code == 400
```

- [ ] **Step 2: Run API tests and confirm assessment endpoints are missing**

Run: `.venv/bin/pytest tests/test_assessment_api.py tests/test_history.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement immutable snapshots and strict user updates**

Store the complete template snapshot, source IDs, rules revision, input evidence, and
calculated results as canonical JSON alongside indexed scan/category/version columns.
Create the first snapshot only after the user accepts or corrects the category. Recompute
all component results transactionally on update; user-provided component presence,
condition, and lifecycle reference overrides stay inside that assessment JSON.

```python
@app.put("/api/v1/scans/<scan_id>/assessment")
def update_assessment(scan_id):
    payload = validate_assessment_payload(request.get_json())
    return jsonify(assessment_service.update(scan_id, payload))
```

Return `404` for unknown scans, `409` when a low-confidence classification has not been
confirmed, and `422` when provided ranges are reversed or outside accepted bounds.

- [ ] **Step 4: Run assessment, history, and desktop API tests**

Run: `.venv/bin/pytest tests/test_assessment_api.py tests/test_history.py tests/test_desktop_api.py -v`

Expected: PASS.

- [ ] **Step 5: Commit assessment persistence and APIs**

```bash
git add server/history.py server/app.py tests/test_assessment_api.py tests/test_history.py
git commit -m "feat: persist editable device assessments"
```

### Task 4: Polished assessment and component UI

**Files:**
- Modify: `server/static/index.html`
- Modify: `server/static/app.css`
- Modify: `server/static/app.js`
- Test: `tests/test_assessment_ui.py`
- Modify: `tests/test_desktop_ui.py`

**Interfaces:**
- Consumes: reference and assessment APIs from Task 3
- Produces: UI states `assessment-loading`, `assessment-editing`, `assessment-ready`, `assessment-error`
- Produces: editable category, age/cycles, usage, condition, operating state, known issues, and component overrides

- [ ] **Step 1: Write failing assessment semantics and honesty-copy tests**

```python
def test_assessment_ui_labels_estimates_and_evidence():
    html = INDEX.read_text()
    for text in ("Device assessment", "Evidence used", "Components and next steps",
                 "Category-based inventory", "Unknown", "Correct identification"):
        assert text in html
    assert "not a measured health reading" in html

def test_assessment_motion_has_reduced_motion_fallback():
    css = CSS.read_text()
    assert "data-assessment-state" in css
    assert "prefers-reduced-motion: reduce" in css
```

- [ ] **Step 2: Run UI tests and confirm the assessment view is absent**

Run: `.venv/bin/pytest tests/test_assessment_ui.py tests/test_desktop_ui.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement the approved assessment screen**

Create the two-column desktop and single-column compact layout shown in the approved
mockup. Put editable device facts and evidence provenance beside the overall range,
safety-first callouts, and component rows. Show units with every range. Use `Unknown`
when the API returns null and show exactly which missing input could improve it.

```javascript
async function saveAssessment(scanId, form) {
  setAssessmentState('assessment-loading');
  const result = await api(`/api/v1/scans/${scanId}/assessment`, {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(readAssessmentForm(form)),
  });
  renderAssessment(result);
  setAssessmentState('assessment-ready');
}
```

Animate form selection, the range meter, safety callout, and component-row population
with the global motion tokens. Keep total staged reveal below 350 ms and update the ARIA
live region only after the final semantic state is available.

- [ ] **Step 4: Run UI and API tests**

Run: `.venv/bin/pytest tests/test_assessment_ui.py tests/test_desktop_ui.py tests/test_assessment_api.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the assessment experience**

```bash
git add server/static/index.html server/static/app.css server/static/app.js tests/test_assessment_ui.py tests/test_desktop_ui.py
git commit -m "feat: add polished component assessment experience"
```

### Task 5: Reference-data and assessment release verification

**Files:**
- Create: `tests/test_reference_release.py`
- Modify: `README.md`
- Create: `docs/COMPONENT_REFERENCE_PROCEDURE.md`

**Interfaces:**
- Consumes: `reference/*.yaml`, `compile_reference()`, and `assess_component()`
- Produces: documented admin review checklist and deterministic release summary

- [ ] **Step 1: Write a failing whole-reference release test**

```python
def test_every_released_rule_is_traceable_and_honest(tmp_path):
    manifest = compile_reference(ROOT / "reference", tmp_path / "components.sqlite")
    store = ReferenceStore(tmp_path / "components.sqlite")
    for category in store.list_categories():
        snapshot = store.snapshot(category["category_id"])
        assert snapshot["template_version"] == manifest.version
        for component in snapshot["components"]:
            if component["lifecycle"] is not None:
                assert component["source_ids"]
            assert component["presence_label"] in {"standard", "common", "optional", "unknown"}
```

- [ ] **Step 2: Run the release test and observe missing documentation/release contract**

Run: `.venv/bin/pytest tests/test_reference_release.py -v`

Expected: FAIL until the release summary and all metadata are complete.

- [ ] **Step 3: Complete the admin procedure and reference summary**

Document source selection, review dates, evidence grades, lifecycle nullability, safety
copy review, version increments, compiler invocation, output hash recording, and the rule
that user overrides never feed back into the standard template automatically. Add README
links and a summary command that prints category/component counts, null lifecycle counts,
source coverage, database version, and SHA-256.

- [ ] **Step 4: Run all component-assessment tests**

Run: `.venv/bin/pytest tests/test_reference_db.py tests/test_lifecycle.py tests/test_assessment_api.py tests/test_assessment_ui.py tests/test_reference_release.py -v`

Expected: PASS with no unsourced non-null lifecycle ranges.

- [ ] **Step 5: Commit the verified assessment subsystem**

```bash
git add README.md docs/COMPONENT_REFERENCE_PROCEDURE.md tests/test_reference_release.py scripts/build_component_db.py
git commit -m "docs: define component reference release procedure"
```

## Plan completion gate

The plan is complete when all five category templates compile reproducibly, every claim
is source-traceable, unsupported lifecycle values render as `Unknown`, item edits preserve
the standard database and historical revision, safety rules precede reuse guidance, and
the approved animated Assessment screen passes API and accessibility regressions.


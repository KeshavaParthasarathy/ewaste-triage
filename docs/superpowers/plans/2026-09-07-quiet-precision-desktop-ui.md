# Quiet Precision Desktop UI and Startup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current three-area, category-only desktop experience with the approved four-destination Quiet Precision shell, an immediate native startup/recovery surface, progressive v2 results, a dedicated Components workspace, and verified keyboard, motion, contrast, and minimum-window behavior.

**Architecture:** Keep the packaged product small: pywebview owns one native window, `desktop.startup` coordinates background initialization by generation, and the existing self-contained HTML/CSS/JavaScript bundle remains the product UI. The browser controller consumes only the frozen `/api/v2` aggregate; presentation helpers turn each independent capability into literal DOM content without recalculating evidence. All destination DOM stays mounted so navigation and dialogs cannot erase an unsaved draft.

**Tech Stack:** Python 3.11, pywebview 6.2.1, Flask 3.1.3, vanilla HTML/CSS/JavaScript, inline SVG, pytest 9.1.1, Node controller tests

**Spec:** `docs/superpowers/specs/2026-09-06-ewaste-evidence-condition-prototype-design.md`

## Required Upstream Gate

Do not start Task 2 until the Slice 2 capability-cookie integration and these v2 routes pass `tests/test_v2_api.py`. Do not start Tasks 4–6 until the Slice 1 `KnowledgeStore`/`BundleStamp` and Slice 3 manual-condition contracts pass their focused suites.

The UI consumes these frozen service contracts without aliases:

- `POST /api/v2/scans` is multipart with exactly one `image` file and one required canonical, non-nil RFC 4122 UUID `idempotency_key` form field. It returns `201` with `scan`, `analysis`, `user_state`, and `assessment`. `analysis` has independent `category`, `identity`, and `condition` capability objects; each state is exactly `ready`, `low_confidence`, or `unavailable`.
- Visible grades are exactly `excellent`, `good`, `fair`, `poor`, `critical`, and `unknown`. The scope statement is exactly `Visible exterior only`.
- `user_state` is exactly `{revision_id, sequence, created_at, identity_decision, canonical_scope, condition_decision, observations}`. `canonical_scope` is server-derived and read-only in the UI; the server, not JavaScript, adds scope, source, and timestamp metadata.
- Identity writes are `{expected_user_revision_id, decision}`. The closed `decision` union is:
  - `{kind: "confirmed", identity_id}`;
  - `{kind: "edited", identity_id, unverified_model_note}`;
  - `{kind: "category_only", category_id, unverified_model_note}`; or
  - `{kind: "unknown", unverified_model_note}`.
- `category_id` is one of `0301_computer_mouse`, `0301_keyboard`, `0303_laptop`, `0306_mobile_phone`, or `0401_headphones`. JavaScript never submits a canonical family, subtype, manufacturer, or model scope; the server derives that scope from `identity_id`.
- Observation writes are `{expected_user_revision_id, condition_decision, observations}`. `condition_decision` is exactly `{grade, findings, image_sufficiency, note}`, where `note` is always present and is a trimmed string or JSON `null`. Ranges use `{lower, upper}`. User findings contain only `{kind, severity}` and never copy model confidence.
- `POST /api/v2/scans/{id}/assessment-revisions` receives `{user_revision_id, lifecycle_request:{subject, endpoint, metric, unit}, idempotency_key}` and creates an immutable revision.
- `GET /api/v2/scans/{id}/summary?assessment_revision_id=` and `GET /api/v2/scans/{id}/components?assessment_revision_id=` are read-only. Omitting the query selects the latest saved revision.
- `POST /api/v2/scans/{id}/reassess` receives `{base_assessment_revision_id, user_revision_id, lifecycle_request, idempotency_key}` and returns `{revision, comparison}`.
- `DELETE /api/v2/scans/{id}` returns `202 {deleted:true, undo_token, undo_expires_at}`. Undo is `POST /api/v2/deletions/{undo_token}/undo`. Clear is `DELETE /api/v2/history` with `{confirmation:"clear_history"}` and has no Undo.
- `409` means a stale user revision, `404` means unknown or deleted, `422` means a bounded validation failure, and `503` means evidence is unavailable. The UI preserves valid partial results for every one of these cases.
- Product requests authenticate through the HttpOnly loopback capability cookie installed by startup. Browser JavaScript never reads, stores, logs, or transmits the capability key itself.

If an upstream implementation disagrees with any field above, correct its contract and tests first. Do not add a second UI-only spelling or a v1 fallback.

## File Map

| File | Responsibility |
|---|---|
| `desktop/startup_surface.py` | Self-contained startup HTML, continuity-mark SVG, truthful timers, and bridge calls |
| `desktop/startup.py` | Startup states/stages, background generations, cleanup, retry, Quit, and pywebview presentation |
| `desktop/main.py` | Immediate window creation, runtime initializer, headless smoke path, and lifecycle wiring |
| `desktop/assets/app-icon.svg` | Canonical continuity mark in the packaged icon |
| `server/static/index.html` | Four mounted destinations, prerequisite states, About/phone utilities, and live regions |
| `server/static/app.css` | Quiet Precision tokens, responsive layout, progressive states, focus, and reduced motion |
| `server/static/app.js` | v2 controller, immutable-revision writes, draft ownership, navigation, progressive views, and safe links |
| `server/static/phone.html` | Canonical inline continuity mark on the phone handoff |
| `server/static/phone.css` | Phone mark, bounded interaction motion, contrast, and reduced motion |
| `server/static/phone.js` | Phone result wording aligned to independent capabilities |
| `tests/test_brand_startup_ui.py` | Shared mark geometry and self-contained startup-surface contracts |
| `tests/test_startup_coordinator.py` | Ordering, timers, generations, cleanup, degradation, recovery, and retry |
| `tests/test_desktop_runtime.py` | Production window dimensions and run-loop integration |
| `tests/test_runtime_control.py` | Headless readiness, capability URL, shutdown, and test-mode integration |
| `tests/test_desktop_integration_fixes.py` | Fatal/recoverable initialization integration and sanitized diagnostics |
| `tests/test_workspace_ui.py` | Four destinations, prerequisites, v2 controller, and mounted-draft behavior |
| `tests/test_assessment_ui.py` | Identity, condition, lifecycle, save, stale-revision, and provenance behavior |
| `tests/test_components_ui.py` | Components order, wording, sources, unavailable state, and edits |
| `tests/test_history_v2_ui.py` | Truthful loading, revisions, comparison, tombstone Undo, and permanent clear |
| `tests/test_desktop_ui.py` | Existing Scan, phone, About, hostile-text, and request-generation regressions |
| `tests/test_accessibility_ui.py` | Semantics, focus, type size, motion budget, reduced motion, and layout contracts |

## Task 1: Establish the canonical continuity mark and startup document

**Files:**
- Create: `desktop/startup_surface.py`
- Modify: `desktop/assets/app-icon.svg`
- Modify: `server/static/index.html`
- Modify: `server/static/phone.html`
- Modify: `server/static/app.css`
- Modify: `server/static/phone.css`
- Create: `tests/test_brand_startup_ui.py`
- Modify: `tests/test_packaging.py`

**Interfaces:**
- Produces: `CONTINUITY_VIEW_BOX = "0 0 1024 1024"`
- Produces: `startup_document() -> str`
- Produces: startup DOM hook `window.EWasteStartup.update(event)`
- Produces: bridge calls `window.pywebview.api.retry()` and `window.pywebview.api.quit()`
- Produces: shared SVG parts `data-mark-part="loop"` and `data-mark-part="core"`

- [ ] **Step 1: Write the failing mark and startup-surface tests**

Assert that app, phone, startup, and icon use `viewBox="0 0 1024 1024"` and the same normalized loop/core path geometry. Assert there is no Unicode product mark (`↻` or a letter tile), every in-product mark is an inline SVG using `currentColor`, and the icon alone supplies fixed graphite/emerald colors. Parse the startup document and assert it has no external script, stylesheet, image, font, network URL, fabricated percentage, or unsanitized interpolation point.

Assert these startup hooks and states are present:

```python
assert 'data-startup-state="BOOTSTRAP"' in document
assert 'window.EWasteStartup.update' in document
assert 'data-startup-action="retry"' in document
assert 'data-startup-action="quit"' in document
assert "prefers-reduced-motion: reduce" in document
```

- [ ] **Step 2: Run the brand/startup tests and verify RED**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["tests/test_brand_startup_ui.py", "tests/test_packaging.py", "-q"]))'
```

Expected: FAIL because the desktop and phone still use platform-dependent marks and no native startup document exists.

- [ ] **Step 3: Implement one minimal mark and a self-contained startup surface**

Use a stable center/core and one simplified outer continuity loop. Put `data-mark-part` on the canonical geometry in all four renderings so the test compares path data, not screenshots. In HTML, set fill/stroke from `currentColor`; keep accessible product text outside the decorative SVG and mark the SVG `aria-hidden="true"`.

`startup_document()` returns a complete UTF-8 HTML document held in the Python module, so PyInstaller collects it with the code and no new runtime data allowlist is required. The surface must:

- use graphite, warm-neutral, and emerald colors with light/dark support;
- display real stage copy supplied by the coordinator and no percentage;
- rotate only `[data-mark-part="loop"]`, pulse only its halo/wrapper, and keep the core stable;
- replace ordinary copy with slow-start copy after 2 seconds;
- add `data-motion="stopped"` and stop repeating motion after 5 seconds;
- reveal the long-start explanation and Quit at 10 seconds;
- expose Retry only for a retryable `DEGRADED` or `RECOVERY` event;
- remove spin, pulse, stagger, spring, and scale under reduced motion; and
- use `textContent` for every coordinator-supplied value.

Update the app icon description to describe the same mark. Do not introduce a seventh product static asset.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["tests/test_brand_startup_ui.py", "tests/test_packaging.py", "tests/test_desktop_ui.py", "-q"]))'
```

Expected: PASS; the six-file product static allowlist remains unchanged.

- [ ] **Step 5: Commit the continuity mark and startup document**

```bash
git add desktop/startup_surface.py desktop/assets/app-icon.svg server/static/index.html server/static/phone.html server/static/app.css server/static/phone.css tests/test_brand_startup_ui.py tests/test_packaging.py
git commit -m "feat: add canonical continuity startup surface"
```

## Task 2: Create the generation-safe startup coordinator

**Files:**
- Create: `desktop/startup.py`
- Modify: `desktop/main.py`
- Modify: `tests/test_desktop_runtime.py`
- Modify: `tests/test_runtime_control.py`
- Modify: `tests/test_desktop_integration_fixes.py`
- Create: `tests/test_startup_coordinator.py`

**Interfaces:**

```python
class StartupState(str, Enum):
    BOOTSTRAP = "BOOTSTRAP"
    INITIALIZING = "INITIALIZING"
    REVEALING = "REVEALING"
    READY = "READY"
    DEGRADED = "DEGRADED"
    RECOVERY = "RECOVERY"
    CLOSING = "CLOSING"

class StartupStage(str, Enum):
    RELEASE_VERIFICATION = "release_verification"
    MODEL_LOADING = "model_loading"
    REFERENCE_OPENING = "reference_opening"
    HISTORY_OPENING = "history_opening"
    APPLICATION_ASSEMBLY = "application_assembly"
    LOOPBACK_BINDING = "loopback_binding"

@dataclass(frozen=True)
class StartupEvent:
    state: StartupState
    stage: StartupStage | None
    message: str
    retryable: bool
    generation: int

@dataclass
class RunningRuntime:
    generation: int
    app: Flask
    server: ServerThread
    base_url: str
    capability_url: str
    close_actions: tuple[Callable[[], None], ...]
```

Methods/functions are exactly `RunningRuntime.close() -> None`, `initialize_runtime(paths: AppPaths, *, generation: int, require_release_integrity: bool, report: Callable[[StartupStage, str], None]) -> RunningRuntime`, `StartupCoordinator.start(window) -> None`, `StartupCoordinator.retry() -> bool`, `StartupCoordinator.quit() -> None`, `StartupCoordinator.close() -> None`, `StartupBridge.retry() -> bool`, and `StartupBridge.quit() -> None`.

- [ ] **Step 1: Write failing ordering, recovery, and lifecycle tests**

Use `threading.Event`, not sleep, to block the release-verification stage. Prove:

- `create_window` receives `html=startup_document()`, `width=1120`, `height=760`, `min_size=(760, 620)`, `js_api=StartupBridge`, and is called before the blocked initializer completes;
- `webview.start` receives `func=coordinator.start`, `args=(window,)`, `debug=False`, and `private_mode=True`;
- `window.load_url()` is not called until the loopback server is ready and receives the capability bootstrap URL once;
- a fast initializer has no artificial dwell;
- stage callbacks occur in the six declared stages in order;
- category/release corruption produces sanitized `RECOVERY` with Reinstall and Quit, while condition failure selects the manual estimator, evidence failure yields usable Scan plus retryable `DEGRADED`, and history failure selects session-only storage with `history_saved:false`;
- Retry is single-flight, closes the prior partial/runtime handle, creates a fresh generation/capability, and cannot publish from an older generation;
- closing the window during initialization closes every later-produced store/server and never navigates;
- worker exceptions expose no local path, traceback, capability key, or exception representation; and
- a cleanup failure never masks the primary initialization failure.

- [ ] **Step 2: Run startup/runtime tests and verify RED**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["tests/test_startup_coordinator.py", "tests/test_desktop_runtime.py", "tests/test_runtime_control.py", "tests/test_desktop_integration_fixes.py", "-q"]))'
```

Expected: FAIL because `desktop.main.run()` still initializes the full Flask app before creating the window.

- [ ] **Step 3: Implement staged initialization and deterministic cleanup**

Move resource assembly behind `initialize_runtime()`. Report immediately before each real stage. Generate one loopback capability key per generation, inject it into `create_desktop_app(..., capability_key=key)`, bind `ServerThread`, then construct `capability_url = f"{base_url}/?capability={key}"`. Never include the key in an event or evaluate-JavaScript payload.

`RunningRuntime.close()` calls close actions once in reverse-acquisition order: phone capture, loopback server, scan/history store, knowledge store, then remaining model resources. Record all cleanup failures, but re-raise only after the primary operation has completed successfully.

`StartupCoordinator.start()` returns after launching one daemon worker. Every transition and navigation checks both the active generation and closed flag. `retry()` returns `False` when a worker is active; otherwise it invalidates the old generation, closes its runtime, resets the startup timers through the document hook, and launches exactly one fresh worker. `quit()` publishes `CLOSING`, closes resources, and calls `window.destroy()`. Attach `window.events.closed += coordinator.close` before `webview.start()`.

Preserve test mode without opening pywebview: run the same initializer, publish the capability URL to the readiness file, wait for the shutdown event, and use the same `RunningRuntime.close()`. The readiness file is an out-of-band smoke-test secret and must use mode `0o600` with atomic replacement.

- [ ] **Step 4: Run startup/runtime tests and verify GREEN**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["tests/test_startup_coordinator.py", "tests/test_desktop_runtime.py", "tests/test_runtime_control.py", "tests/test_desktop_integration_fixes.py", "tests/test_local_capability.py", "-q"]))'
```

Expected: PASS with deterministic Event-driven concurrency tests and no leaked listener.

- [ ] **Step 5: Commit immediate startup coordination**

```bash
git add desktop/startup.py desktop/main.py tests/test_startup_coordinator.py tests/test_desktop_runtime.py tests/test_runtime_control.py tests/test_desktop_integration_fixes.py
git commit -m "feat: coordinate immediate native startup"
```

## Task 3: Build the four-destination Quiet Precision shell

**Files:**
- Modify: `server/static/index.html`
- Modify: `server/static/app.css`
- Modify: `server/static/app.js`
- Create: `tests/test_workspace_ui.py`
- Modify: `tests/test_desktop_ui.py`

**Interfaces:**
- Produces: `DESTINATIONS = Object.freeze(["scan", "assessment", "components", "history"])`
- Produces: `createWorkspaceState() -> WorkspaceState`
- Produces: `prerequisitePresentation(destination, workspaceState) -> {title, detail, actions}`
- Produces: `view.showDestination(destination, {focusHeading = true} = {})`
- Preserves: `createController(options)` and CommonJS/global exports for Node tests

- [ ] **Step 1: Write failing semantic-shell and prerequisite tests**

Assert all four labeled navigation buttons exist in source/DOM order Scan, Assessment, Components, History; each owns one mounted `<section>` with a unique heading; About remains a dialog utility and phone capture remains inside Scan. Open Assessment and Components with no selected scan and assert intentional prerequisite copy plus working “Start a scan” and “Open History” actions, not `role="alert"`, error styling, or an API request.

Add a Node fake-DOM controller test that enters values, switches through all four destinations, opens/closes About, returns to Assessment, and observes the same input nodes and values. Selecting a different scan, explicit discard, successful delete, or Analyze another may reset the draft; ordinary navigation may not.

- [ ] **Step 2: Run workspace/UI tests and verify RED**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["tests/test_workspace_ui.py", "tests/test_desktop_ui.py", "tests/test_assessment_ui.py", "-q"]))'
```

Expected: FAIL because Components has no destination and opening Assessment without a scan is currently an error.

- [ ] **Step 3: Implement the mounted workspace and responsive base layout**

Add `#components-view`, `#assessment-prerequisite`, and `#components-prerequisite`. Keep every destination element in the document and switch only `hidden`, `aria-current`, and heading focus. Do not replace destination roots with generated HTML.

Use a two-column 1120×760 reference layout and a compact labeled-navigation layout at 760×620. Set `min-width:0` on workspace/grid children, wrap secondary utilities separately from primary navigation, and ensure the root never needs horizontal scrolling. Keep all four destination labels visible; do not collapse them to icon-only controls.

Create Quiet Precision tokens for graphite, warm-neutral surfaces, emerald actions, danger/safety, focus, muted text, and dark appearance. Keep the system font stack and avoid decorative cards around content that does not need grouping.

- [ ] **Step 4: Run workspace/UI tests and verify GREEN**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["tests/test_workspace_ui.py", "tests/test_desktop_ui.py", "tests/test_assessment_ui.py", "-q"]))'
```

Expected: PASS for the four destinations, both prerequisite actions, secondary utilities, and mounted draft.

- [ ] **Step 5: Commit the four-destination shell**

```bash
git add server/static/index.html server/static/app.css server/static/app.js tests/test_workspace_ui.py tests/test_desktop_ui.py tests/test_assessment_ui.py
git commit -m "feat: build four-destination quiet precision shell"
```

## Task 4: Consume progressive v2 Scan and Assessment results

**Files:**
- Modify: `server/static/index.html`
- Modify: `server/static/app.css`
- Modify: `server/static/app.js`
- Modify: `tests/test_workspace_ui.py`
- Modify: `tests/test_assessment_ui.py`
- Modify: `tests/test_desktop_ui.py`

**Interfaces:**
- Produces: `scanPresentation(scanAggregate) -> {category, identity, condition, history}`
- Produces: `identityDecisionFromValues(values) -> IdentityDecision`
- Produces: `conditionDecisionFromValues(values) -> ConditionDecision`
- Produces: `observationsFromValues(values) -> Observations`
- Produces: `lifecycleRequestFromValues(values) -> LifecycleRequest`
- Injects: `createController({request, view, idFactory})`, where `idFactory() -> canonical non-nil RFC 4122 UUID`
- Produces controller methods: `analyze(file)`, `selectIdentityDecision(value)`, `saveAssessment(form)`, `discardDraft()`, and `loadSummary(revisionId)`
- Consumes: `GET /api/v2/condition-rubric` and `GET /api/v2/catalog/identities?q=&category_id=&limit=`

- [ ] **Step 1: Write failing v2, partial-result, and draft-ownership tests**

Use exact response fixtures from `tests/test_v2_api.py`. Prove that:

- `analyze()` calls only `POST /api/v2/scans`, serializes one `image` plus one `idempotency_key` multipart field, renders category/identity/condition independently, labels the category “Suggested”, and never treats identity or condition failure as total scan failure;
- each Analyze intent creates one UUID, an ambiguous transport retry of that exact multipart command reuses it, and a new Analyze intent creates a different UUID;
- the first result reveal has no more than two groups and exposes identity plus visible condition before any lifecycle request;
- identity suggestions remain suggestions until one of the four explicit decisions is saved;
- all six visible grades render, `unknown` remains distinct, and every condition card shows `Visible exterior only`;
- model findings keep machine confidence/provenance while a user correction sends no confidence;
- executed Node serialization proves `conditionDecisionFromValues({...validConditionValues, note:"   "})` owns `note:null`, while input `note:"  hinge scratch  "` serializes as `note:"hinge scratch"`;
- Identity, Visible condition, and Lifecycle are separate cards with no combined score;
- the lifecycle card displays the unchanged source range separately from a derived item range or threshold, including unit, endpoint, assumptions, evidence scope, and an explicit Unknown reason;
- every saved Assessment/Components provenance view displays the frozen five-field bundle stamp (`schema_version`, `bundle_version`, `identity_catalog_version`, `policy_revision`, `content_sha256`) from the revision instead of current About metadata;
- every returned `user_state` is accepted only with all seven exact fields, including server-derived `canonical_scope`; JavaScript renders that scope but never submits it in either PUT;
- `saveAssessment()` serializes identity first, observations second with the returned revision ID, and assessment creation third with the newest revision ID plus `idempotency_key`; identity and observation PUTs reject/omit that field;
- an ambiguous assessment-create retry reuses the exact UUID, user revision, and lifecycle request, while a materially changed save intent receives a fresh UUID;
- a `409` leaves every input value mounted and offers Reload/Discard; `422` focuses field feedback; `503` keeps identity/condition visible and marks only evidence-dependent content unavailable; and
- stale scan, catalog, summary, and save responses cannot replace a newer scan/draft.

Execute these assertions inside the Node controller test (where `validConditionValues` contains a valid grade, findings list, and image sufficiency):

```javascript
const emptyNote = conditionDecisionFromValues({...validConditionValues, note: "   "});
assert.equal(Object.hasOwn(emptyNote, "note"), true);
assert.equal(emptyNote.note, null);
assert.equal(
  conditionDecisionFromValues({...validConditionValues, note: "  hinge scratch  "}).note,
  "hinge scratch"
);
```

- [ ] **Step 2: Run Scan/Assessment tests and verify RED**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["tests/test_workspace_ui.py", "tests/test_assessment_ui.py", "tests/test_desktop_ui.py", "-q"]))'
```

Expected: FAIL because `createController()` still calls `/api/v1/classify`, merges category/components in Assessment, and replaces the form during loading.

- [ ] **Step 3: Implement the v2 workspace state and explicit writes**

Track `activeScanId`, `userRevisionId`, `assessmentRevisionId`, request generations, pending create-command payloads/UUIDs, and `{ownerScanId, dirty}` for the mounted draft. Obtain keys only from injected `idFactory` (production passes `crypto.randomUUID`). `analyze()` renders a scan-level failure only when the request itself fails; unavailable identity or condition receives scoped copy and its permitted manual action. Retain a pending key and canonical logical command across an ambiguous transport failure, clear it after an authoritative response, and allocate a new key for a new user intent; never retry a key with changed command content.

Build identity payloads exactly as frozen above. An edited decision must contain a catalog `identity_id`; free text goes only in `unverified_model_note`. Build the observation payload with:

```javascript
{
  expected_user_revision_id,
  condition_decision: {grade, findings, image_sufficiency, note},
  observations: {
    age_months,
    full_charge_cycles,
    operational_state,
    issue_flags,
    component_decisions
  }
}
```

Always serialize the `note` key: trim its input, send the bounded literal string when non-empty, and send JSON `null` when empty. Never send model confidence, source, timestamp, or `canonical_scope`. Treat the returned scope as server-owned presentation data.

During save/recalculation, set `aria-busy` on the relevant card, disable only the duplicate submit action, and keep inputs visible and mounted. After the immutable revision returns, render the summary without rebuilding the editor. Keep the existing literal-`textContent` discipline for hostile strings.

- [ ] **Step 4: Run Scan/Assessment tests and verify GREEN**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["tests/test_workspace_ui.py", "tests/test_assessment_ui.py", "tests/test_desktop_ui.py", "tests/test_v2_api.py", "-q"]))'
```

Expected: PASS for v2 requests, partial capabilities, immutable revision ordering, stale responses, and mounted retryable forms.

- [ ] **Step 5: Commit progressive Scan and Assessment**

```bash
git add server/static/index.html server/static/app.css server/static/app.js tests/test_workspace_ui.py tests/test_assessment_ui.py tests/test_desktop_ui.py
git commit -m "feat: present progressive versioned assessments"
```

## Task 5: Add the dedicated Components destination

**Files:**
- Modify: `server/static/index.html`
- Modify: `server/static/app.css`
- Modify: `server/static/app.js`
- Create: `tests/test_components_ui.py`
- Modify: `tests/test_assessment_ui.py`

**Interfaces:**
- Produces: `componentsPresentation(savedComponents) -> ComponentsPresentation`
- Produces controller methods: `openComponents(revisionId)`, `saveComponentDecisions(form)`, and `openSource(sourceId)`
- Consumes: saved Components snapshot from `GET /api/v2/scans/{id}/components?assessment_revision_id=`
- Guarantees DOM/reading order: urgent safety → reusable/testable parts → expected components → endurance facts → sources → editing controls

- [ ] **Step 1: Write failing Components ordering and honesty tests**

Assert Components navigation is always reachable. With no selected scan, render the prerequisite. With a scan but no canonical category decision, explain that identity review is required and link to Assessment. With evidence unavailable, retain the selected category and show retryable unavailable copy rather than an empty list.

Given a saved snapshot, assert visual and source order exactly matches the required six groups. Test all closed association/recommendation values and ensure category-associated or hazard-possible parts never use “detected”, “seen”, “verified”, or equivalent photographic claims. A safety escalation must use `role="alert"` and precede reuse guidance.

For sources, assert title, publisher, evidence level, review/access dates, and copyable URL remain visible offline. Create an external `<a>` only for a parsed `http:` or `https:` URL, set `rel="noopener noreferrer"`, and require the user click; rendering must never fetch a source.

For editing, assert present/not-present/unknown and optional notes/lifecycle scenarios serialize into `observations.component_decisions`, then create a new assessment revision with a fresh `idempotency_key`. An ambiguous retry reuses that key and the exact assessment command; a saved historical snapshot remains unchanged.

- [ ] **Step 2: Run Components tests and verify RED**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["tests/test_components_ui.py", "tests/test_assessment_ui.py", "-q"]))'
```

Expected: FAIL because component content is embedded in the current Assessment view and source URLs are plain concatenated text.

- [ ] **Step 3: Implement saved-snapshot Components presentation**

Move component output, hazards, reuse guidance, and their sources to `#components-view`. Render only the server’s frozen snapshot; do not call the resolver or derive recommendations in JavaScript. `openComponents()` may fetch only after a canonical decision and must select a saved revision explicitly when History requested one.

Keep editing controls mounted in `#components-form`. Use the same draft owner and current `userRevisionId` as Assessment. A save performs the observation write without an idempotency field and then creates a new assessment revision with the create-command UUID; it does not mutate the displayed old revision in place. Retain that UUID only for an ambiguous retry of the identical command. Put Unknown reason and missing-input action beside each unavailable endurance fact.

- [ ] **Step 4: Run Components and service-contract tests and verify GREEN**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["tests/test_components_ui.py", "tests/test_assessment_ui.py", "tests/test_v2_api.py", "tests/test_evidence_resolver.py", "-q"]))'
```

Expected: PASS for ordering, frozen revisions, source safety, Unknowns, and component edits.

- [ ] **Step 5: Commit the Components destination**

```bash
git add server/static/index.html server/static/app.css server/static/app.js tests/test_components_ui.py tests/test_assessment_ui.py
git commit -m "feat: add sourced components workspace"
```

## Task 6: Implement truthful History revisions, reassessment, Undo, and clear

**Files:**
- Modify: `server/static/index.html`
- Modify: `server/static/app.css`
- Modify: `server/static/app.js`
- Create: `tests/test_history_v2_ui.py`
- Modify: `tests/test_desktop_ui.py`

**Interfaces:**
- Produces: `historyPresentation(scan) -> HistoryRowPresentation`
- Produces: `revisionPresentation(summary) -> RevisionPresentation`
- Produces controller methods: `loadHistory()`, `openHistory(scanId, revisionId)`, `reassess(scanId, revisionId)`, `deleteScan(scanId)`, `undoDeletion(token)`, and `clearHistory()`
- Consumes: `GET /api/v2/history` and `GET /api/v2/scans/{id}/thumbnail`

- [ ] **Step 1: Write failing loading, revision, deletion, and race tests**

Assert History begins with `data-history-state="loading"` and `aria-busy="true"`; it must not show “No scans yet” until a successful empty response. Test unavailable/retry, actual empty, and populated states separately.

Prove a row shows the explicit user decision beside immutable original model evidence, revision count, saved/not-saved truth, and a managed thumbnail only. Opening a revision selects that exact `assessment_revision_id`. Reassessment sends `{base_assessment_revision_id, user_revision_id, lifecycle_request, idempotency_key}`, creates a neighbor revision, and shows field-level comparison without replacing the original. Its ambiguous retry reuses the same key and exact command; selecting a different base or changing lifecycle input creates a new key.

For delete, assert the row hides immediately only after the `202` receipt, Undo calls `/api/v2/deletions/{encoded token}/undo`, and the Undo control expires at `undo_expires_at`. Test failed delete, failed undo, expiry, deletion of the selected scan, and stale list requests. For Clear History, require the exact confirmation copy and JSON body, remove rows only after success, and never offer Undo.

- [ ] **Step 2: Run History tests and verify RED**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["tests/test_history_v2_ui.py", "tests/test_desktop_ui.py", "-q"]))'
```

Expected: FAIL because History currently pre-renders an empty claim and delays the server delete in JavaScript for five seconds.

- [ ] **Step 3: Implement server-owned tombstone behavior and immutable revision browsing**

Remove the client-side delayed-delete queue. Treat the server receipt as the sole Undo authority, store only token/expiry in memory, URL-encode the token, and clear it on success, expiry, clear, shutdown, or selection of a different deletion receipt. Do not persist tombstones in browser storage.

Keep each list/summary/comparison request generation-scoped. Track reassessment create commands with the same `idFactory` and pending-command rules as assessment creation. Selecting another scan intentionally changes draft ownership and resets unsaved values; simply selecting another revision of the same scan does not alter the edit draft. Render history strings through `textContent` and thumbnail URLs only from the same-origin route.

- [ ] **Step 4: Run History/service tests and verify GREEN**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["tests/test_history_v2_ui.py", "tests/test_desktop_ui.py", "tests/test_scan_store.py", "tests/test_v2_api.py", "-q"]))'
```

Expected: PASS for truthful loading, revision selection, comparison, exact ten-second tombstones, immediate clear, and races.

- [ ] **Step 5: Commit versioned History**

```bash
git add server/static/index.html server/static/app.css server/static/app.js tests/test_history_v2_ui.py tests/test_desktop_ui.py
git commit -m "feat: browse and manage versioned scan history"
```

## Task 7: Close accessibility, motion, phone, and minimum-window gaps

**Files:**
- Modify: `server/static/index.html`
- Modify: `server/static/app.css`
- Modify: `server/static/app.js`
- Modify: `server/static/phone.html`
- Modify: `server/static/phone.css`
- Modify: `server/static/phone.js`
- Create: `tests/test_accessibility_ui.py`
- Modify: `tests/test_brand_startup_ui.py`
- Modify: `tests/test_desktop_ui.py`
- Modify: `tests/test_assessment_ui.py`
- Modify: `tests/test_components_ui.py`
- Modify: `tests/test_history_v2_ui.py`

**Interfaces:**
- Produces: plain-language `role="status"`/`aria-live="polite"` updates for non-urgent work
- Produces: urgent safety and submit failures with scoped `role="alert"`
- Produces: focus return for About/phone dialogs and predictable destination heading focus
- Guarantees: interaction/reveal durations `150–320ms`; each staged sequence completes within `350ms`

- [ ] **Step 1: Write failing accessibility and motion-budget tests**

Parse HTML/CSS and execute DOM/controller tests to prove:

- every control has an accessible name, every field has a label/error association, nav uses `aria-current`, dialog Escape/close returns focus, and hidden destinations cannot receive focus;
- all supporting text is at least 11 px equivalent and foreground/background token pairs meet WCAG AA contrast (4.5:1 normal text, 3:1 large text and controls);
- visible `:focus-visible` and press feedback exist without layout movement;
- no large-surface transition animates layout properties; only opacity and transform are allowed;
- all interaction/reveal durations fall within 150–320 ms and every stagger ends within 350 ms;
- no persistence, navigation, `hidden`, `aria-*`, or focus change waits on `animationend`/`transitionend`;
- reduced motion removes spins, pulses, staggers, springs, and scale from app, phone, and startup;
- shell and Scan reveal in no more than two groups;
- 1120×760 and 760×620 CSS contracts have no horizontal overflow, clipped primary action, or hidden destination label; and
- phone copy remains explicit about temporary same-network HTTP and the phone page uses the continuity mark.

Use fake clocks to assert slow-start copy at 2 seconds, repeating startup motion stopped at 5 seconds, and long-start/Quit at 10 seconds. Keep the Event-driven window-ordering test as the automated proxy for the one-second surface target; record actual p95 surface and two-second Scan-usable measurements on the packaged reference Mac in Slice 5 acceptance.

- [ ] **Step 2: Run accessibility tests and verify RED**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["tests/test_accessibility_ui.py", "tests/test_brand_startup_ui.py", "tests/test_desktop_ui.py", "tests/test_assessment_ui.py", "tests/test_components_ui.py", "tests/test_history_v2_ui.py", "-q"]))'
```

Expected: FAIL on current 9/10 px text, 140 ms interactions, 420 ms sheet/phone progress, three-area compact layout, and incomplete reduced-motion rules.

- [ ] **Step 3: Implement accessibility and bounded motion fixes**

Raise supporting text to 11 px or larger, correct token contrast, and use fixed-size borders/feedback so busy and pressed states do not shift layout. Change the 140 ms token to at least 150 ms, remove the 420 ms sequences, cap index-based delays, and limit large surfaces to opacity/transform. A single reduced-motion query must neutralize all named repeating/staged effects while preserving final visible state.

Use native `<button>`, `<a>`, `<input>`, `<select>`, `<fieldset>`, `<dialog>`, headings, lists, and definition lists before adding ARIA. Announce only meaningful state changes. Keep source URLs visible/copyable and external opening explicit. Preserve all current hostile-text tests.

- [ ] **Step 4: Run the complete Slice 4 gate**

Run:

```bash
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["tests/test_brand_startup_ui.py", "tests/test_startup_coordinator.py", "tests/test_desktop_runtime.py", "tests/test_runtime_control.py", "tests/test_workspace_ui.py", "tests/test_desktop_ui.py", "tests/test_assessment_ui.py", "tests/test_components_ui.py", "tests/test_history_v2_ui.py", "tests/test_accessibility_ui.py", "tests/test_v2_api.py", "-q"]))'
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["-q"]))'
git diff --check
```

Expected: all tests pass; no production page imports a network asset or v1 scan/assessment/history route.

- [ ] **Step 5: Manually inspect both required window sizes before committing**

Launch the development app once at 1120×760 and once at 760×620. At each size inspect Scan, Assessment prerequisite and populated states, Components prerequisite and populated states, History loading/empty/populated states, About, and phone dialog in light, dark, and Reduce Motion appearances. Record defects as tests before fixing them. Do not mark this step complete from CSS inspection alone.

- [ ] **Step 6: Commit the accessibility and motion gate**

```bash
git add server/static/index.html server/static/app.css server/static/app.js server/static/phone.html server/static/phone.css server/static/phone.js tests/test_accessibility_ui.py tests/test_brand_startup_ui.py tests/test_desktop_ui.py tests/test_assessment_ui.py tests/test_components_ui.py tests/test_history_v2_ui.py
git commit -m "feat: complete accessible quiet precision interaction"
```

## Integration and Conflict Notes

- `desktop/main.py` is also changed by the capability-key, condition-estimator, and release-integrity slices. Merge Slice 2 and Slice 3 assembly first. Implement this plan’s coordinator around their final `create_desktop_app()` signature; Slice 5 then replaces only the release-validation internals.
- `server/static/app.js`, `app.css`, and `index.html` are intentionally kept monolithic to preserve the six-file static allowlist. Assign Tasks 3–7 serially; do not parallel-edit them.
- `tests/test_desktop_ui.py` and `tests/test_assessment_ui.py` contain valuable v1 race tests. Port their intent to the v2 revision model before deleting obsolete assertions; do not discard stale-response or hostile-text coverage.
- Assessment and Components navigation must remain reachable when knowledge is unavailable. “Components enabled” means evidence-backed content becomes available after a canonical category decision, not that the navigation control is disabled.
- The startup document lives in Python deliberately. Moving it to `desktop/assets/` later requires a coordinated PyInstaller data allowlist, bundle verifier, and packaging-test change.
- Slice 5 expands About metadata and changes its endpoint to `/api/v2/release-metadata`. Keep About secondary and its focus behavior stable here; do not freeze the old five-field visual layout in new Slice 4 tests.
- Do not claim Slice 4 complete until the full test suite and the six-state, two-size manual inspection pass from the same clean commit.

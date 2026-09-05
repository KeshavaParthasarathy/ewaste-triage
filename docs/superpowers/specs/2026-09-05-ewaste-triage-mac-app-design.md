# E-Waste Triage Mac App — Product Design

**Date:** 2026-09-05

**Status:** Approved in conversation; awaiting final document review

**Initial audience:** owner plus a small group of testers

**Release platform:** macOS first, portable architecture for Windows and Linux later
**Initial system target:** Apple Silicon, macOS 14 or later

## 1. Product outcome

Turn the existing local Flask/PyTorch prototype into a polished desktop product that:

- launches by double-clicking a normal Mac app, with no Terminal interaction;
- classifies one device photo at a time and explains the result honestly;
- accepts photos from the Mac or from a temporarily paired phone;
- keeps a private, clearable local scan history;
- lets the user correct the predicted device and enter assessment facts;
- presents category-standard component inventories, safety flags, lifecycle ranges,
  and reuse/testing recommendations;
- works offline except for optional same-network phone transfer; and
- receives approved models and reference data only through versioned app releases.

This design supersedes the browser-only delivery constraint in the 2026-08-19 design
while preserving its scientific honesty: the image model is a device classifier, not an
x-ray, a hardware diagnostic, or a measure of hidden component health.

## 2. Product boundaries

### The product may claim

- a predicted device category and confidence;
- the model's other leading category possibilities;
- which image regions influenced a prediction, clearly labeled as an explanation of
  model behavior rather than proof of object condition;
- a standard component inventory associated with the confirmed device category;
- lifecycle ranges derived from sourced reference data and user-confirmed facts;
- conservative reuse, test, repair, recycling, or specialist-handling recommendations;
- which inputs and sources contributed to each estimate.

### The product must not claim

- that hidden components were visually detected in an exterior photo;
- that a component works without a functional or diagnostic test;
- an exact percentage of lifecycle consumed when only approximate inputs exist;
- that the absence of visible damage proves safety;
- that a category-level component template is a device teardown or bill of materials;
- that model attention is a physical diagnosis.

Lifecycle results are displayed as ranges with a confidence label. Missing or weak
evidence widens the range and lowers confidence. If the evidence cannot support an
estimate, the product displays **Unknown** instead of inventing a value.

## 3. Release scope

### Included in the first usable release

- five current categories: computer mouse, keyboard, laptop, mobile phone, headphones;
- drag-and-drop and file-picker photo import;
- JPEG, PNG, HEIC, and WebP normalization;
- prediction, confidence, top alternatives, low-confidence review state, and an
  optional model-attention explanation;
- editable device identification and user assessment inputs;
- standardized component templates for all five categories;
- component-level lifecycle ranges and next-step recommendations;
- local scan history with deletion and clear-all controls;
- temporary QR phone capture on the same local network;
- model and component-database version information;
- a packaged unsigned `.app` and tester-facing disk image or zip;
- first-run instructions for macOS Gatekeeper's one-time **Open** flow.

### Deferred without blocking the architecture

- Windows and Linux packages;
- Intel Mac or universal-binary packages;
- Apple Developer ID signing, notarization, and automatic application updates;
- manufacturer/model-specific component-template overrides;
- automatic hardware diagnostics and operating-system health imports;
- accounts, cloud synchronization, remote storage, or analytics;
- multi-object detection and internal PCB component detection;
- admin training controls inside the public application.

The displayed product name remains **E-Waste Triage** for the first release and can be
renamed later without changing the architecture.

## 4. Technical architecture

The product uses a lightweight embedded-web desktop architecture because it provides the
cleanest path from the current code to a Mac app while preserving future Windows/Linux
portability.

### 4.1 Desktop shell

- `pywebview` creates the native application window and uses macOS WebKit rather than
  bundling a second browser engine.
- A Python bootstrap starts all required services, waits for a health check, opens the
  window, and stops services cleanly when the window exits.
- PyInstaller produces a self-contained, one-directory macOS `.app` bundle. The first
  release is unsigned because no Apple Developer Program membership is available.
- No console window or Terminal command is part of the normal user workflow.

### 4.2 Local application service

- The desktop interface talks to a Flask service bound to `127.0.0.1` on an available
  ephemeral port.
- The service exposes a versioned internal API for classification, explanation,
  assessment, component references, history, and health status.
- Domain logic lives in service modules, not Flask routes, so the same logic can be used
  by tests, command-line administration, and later platform shells.
- Server-generated paths and filenames are validated and app-owned data paths are
  resolved before writes.

### 4.3 Phone capture service

- No LAN listener exists during ordinary desktop use.
- Choosing **Phone capture** starts a restricted temporary listener on the available
  local IPv4/IPv6 interfaces and displays a QR code.
- The QR URL contains a cryptographically random, single-session token. A short pairing
  code is shown on both devices for human confirmation.
- The phone service exposes only the capture page, upload, and session-status routes.
  It cannot browse history, component references, or app files.
- Sessions expire after ten minutes of inactivity and can be ended immediately from the
  Mac. Uploaded images are size-limited, decoded before acceptance, normalized, and
  handed to the same classification service as Mac imports.
- The existing IPv6-only hotspot behavior remains a required acceptance test.

### 4.4 Inference boundary

- Training remains in PyTorch inside the admin sandbox.
- A stable `InferenceEngine` interface prevents UI and product logic from depending on
  the training framework.
- The release pipeline exports an approved checkpoint to ONNX and verifies parity on a
  fixed reference set before packaging it with ONNX Runtime.
- If export parity fails, the release is blocked; the app never silently substitutes an
  unverified model.
- The bundled model manifest includes model ID, architecture, class order, image
  preprocessing version, confidence threshold, checkpoint and artifact hashes,
  evaluation summary, reference-set ID, schema compatibility, and release timestamp.
- The app verifies the manifest and artifact checksum at startup and presents a readable
  recovery message if either is invalid.

The current research-leading EfficientNet-B0 candidate is not automatically promoted.
The first package uses only a checkpoint that has passed the repository's normal model
promotion gate and the new export/parity checks.

### 4.5 Explanation boundary

The first release uses a model-agnostic occlusion explanation rather than tying the app
to a training-only gradient implementation. The service masks small image regions,
measures the change in the selected class score, and returns a low-resolution influence
map. It runs after the primary prediction so it does not delay the classification result.

The interface describes the overlay as **regions that influenced this result**. It never
describes them as detected damage, detected internal parts, or proof of condition.

## 5. Separation between user app and admin sandbox

### User application

- inference and assessment only;
- bundled read-only model and component-reference release;
- local user history and item-specific corrections;
- no dataset folders, training code, experimental checkpoints, or promotion controls.

### Admin sandbox

- image collection, normalization, labeling, and device-level splits;
- training and iterative experiment tracking;
- fixed holdout and own-device evaluation;
- component-reference authoring and source review;
- release-candidate approval;
- ONNX export and parity validation;
- construction of an immutable release manifest and packaged application inputs.

### Release gate

An admin release command accepts an explicitly approved checkpoint and component
reference revision. It runs tests, produces immutable artifacts, writes a manifest, and
stages those artifacts for the app build. The build fails closed if approval metadata,
hashes, schema versions, or required evaluation results are absent.

Model and component-reference updates ship in normal app releases. The running app does
not independently download weights or reference databases.

## 6. User experience

### 6.1 Application navigation

The first release has three primary areas:

1. **Scan** — import a photo, classify it, and inspect the result.
2. **Assessment** — confirm device details, review component risks and lifecycle ranges,
   and record next steps.
3. **History** — revisit or delete locally stored results.

Phone capture is an action within Scan and becomes a temporary session, not a permanent
background mode.

### 6.2 Scan flow

1. The empty state offers drag-and-drop, **Choose photo**, and **Capture from phone**.
2. The app validates and normalizes the image, including EXIF orientation, before any
   model call.
3. The primary result appears as soon as classification completes.
4. The result shows the predicted category, confidence, top alternatives, and either a
   normal or **Needs review** state based on the released threshold.
5. The influence overlay populates asynchronously and can be toggled off.
6. The user may accept or correct the category before opening Assessment.
7. A history record is written only after image validation succeeds. Failed attempts do
   not create broken history rows.

### 6.3 Assessment flow

1. The app creates an item-specific snapshot of the standard component template for the
   confirmed category and records its template revision.
2. The user confirms or enters approximate age, usage intensity, operating status,
   visible condition, known issues, and any available diagnostics.
3. The app displays the evidence source for every field: model estimate, user confirmed,
   diagnostic measurement, or unavailable.
4. The lifecycle engine calculates component ranges and confidence labels.
5. Safety-sensitive components appear before reuse recommendations. A safety rule cannot
   be cleared by photo confidence alone.
6. Each component receives one plain-language next step: likely reusable after test,
   diagnostic test, repair assessment, recycle, specialist handling, or unknown.
7. Users can edit their item without modifying the category-standard database.
8. The assessment may be exported as a concise local report containing provenance and
   disclaimers.

Existing valuation output remains optional secondary information when all estimator
inputs and reference data are available. Missing valuation data never blocks device
classification or component assessment.

### 6.4 History and privacy

- History is stored only on the Mac in the application's standard Application Support
  directory.
- A record contains a managed thumbnail, classification, assessment inputs and outputs,
  model version, component-template revision, and timestamps.
- The original photo is not duplicated by default. The user can explicitly choose to
  retain it with the record.
- Users can delete one record, clear all history, or disable history for future scans.
- Clearing history removes managed thumbnails and retained originals as well as database
  rows.

## 7. Standard component-reference database

The component knowledge base is standardized by device category to keep the initial
system understandable and maintainable.

### 7.1 Authoring and distribution

- Admins maintain human-readable, source-controlled YAML records.
- A validation/build command compiles them into a read-only SQLite database bundled in
  the app.
- Every release has a semantic database version and content hash.
- Source records require citations, review dates, and an explicit evidence grade. The
  compiler rejects missing required fields and invalid ranges.

### 7.2 Device template

Each device-category template contains:

- stable category ID and display name;
- required and optional component references;
- template version and compatibility metadata;
- category-level notes and handling disclaimers.

### 7.3 Component template

Each component record contains:

- stable component ID and display name;
- normal presence: standard, common, optional, or unknown;
- potential safety flags and conditions that escalate them;
- sourced expected-lifecycle range and applicable assumptions;
- recommended visual checks, functional tests, or diagnostics;
- conservative reuse, repair, recycling, and specialist-handling rules;
- source identifiers, evidence grade, review date, and revision.

The app describes these components as **commonly associated with this device type** until
the user or a diagnostic confirms their presence.

### 7.4 Item-specific snapshot

When an assessment begins, the app copies the selected template into the user's local
history database. User changes apply to that snapshot only. This preserves historical
reproducibility when future app releases update the standard template.

Manufacturer/model-specific overrides may later refine a standard template, but they
must inherit the same schema, evidence requirements, and versioning rules.

## 8. Lifecycle estimation and recommendations

The first lifecycle engine is deterministic and explainable rather than another opaque
machine-learning model.

### 8.1 Inputs

- component lifecycle reference range;
- approximate device or component age range;
- user-confirmed usage intensity and operating status;
- user-confirmed visible condition and known issues;
- available hardware diagnostics, if added later;
- evidence quality and missing-input flags.

The classifier supplies device category only. Automated condition inference is not part
of the first release unless it is separately trained, validated, and versioned.

### 8.2 Calculation behavior

- The base consumed-life interval derives from the age interval divided by the sourced
  lifecycle interval and is bounded to 0–100%.
- Usage and condition modifiers may shift or widen the interval only when their rule has
  a documented source or explicitly conservative policy rationale.
- Missing or conflicting inputs widen the interval and reduce confidence.
- Diagnostic measurements, when supported later, take precedence over photo-derived or
  self-reported estimates and identify themselves as measured evidence.
- If the resulting evidence remains insufficient, the value is **Unknown**.
- The UI rounds ranges to avoid false precision and does not animate to unsupported exact
  values.

### 8.3 Recommendations

Recommendations are rule results with visible reasons. Safety escalation rules run
before reuse scoring. A component can be labeled reusable only as a candidate pending
the specified inspection or test. Each recommendation records the rule revision used.

## 9. Motion and interaction design

Motion should feel restrained, responsive, and consistent with a high-quality modern
macOS product. It supports comprehension and feedback; it never delays work or hides
state.

### 9.1 Motion tokens

- hover and focus transitions: 120–160 ms;
- button press: immediate scale to approximately 0.985, then a short spring-like return;
- option selection and panel changes: 180–240 ms;
- primary result entrance: 240–320 ms;
- component-row reveal: small 30–40 ms stagger, capped so the total sequence remains
  under 350 ms;
- easing: one standard deceleration curve plus one restrained spring curve;
- only `transform` and `opacity` animate for large surfaces to preserve smooth rendering.

### 9.2 Functional motion states

- Dragging an accepted file over the window lifts and highlights the drop target.
- Buttons visibly depress and cannot be double-submitted while work is running.
- Selected options glide to their new state without moving surrounding layout.
- Image decoding, inference, and explanation use distinct real states rather than fake
  progress percentages.
- The result card reserves its final space before content arrives, preventing layout
  jumps. Prediction, confidence, alternatives, and explanation populate in order.
- Confidence bars animate from zero to their final values only after the numeric values
  are known.
- Low-confidence and safety states use calm color and icon changes, not shaking,
  flashing, or alarmist motion.
- History insertions and deletions animate locally and remain undoable until committed.
- Closing the window cancels pending work cleanly; animation callbacks cannot write to a
  destroyed view.

### 9.3 Accessibility and performance

- `prefers-reduced-motion` removes spring, scale, stagger, and sweeping effects while
  preserving immediate state changes.
- No information is communicated by motion or color alone.
- Focus indicators remain visible during and after transitions.
- Animations must remain smooth at the minimum supported window size and while inference
  runs in the background.
- Automated UI tests assert final state and reduced-motion behavior, while visual tests
  check intermediate loading, result, review, error, and deletion states.

This specification aims for macOS-quality polish without copying Apple branding,
proprietary assets, or product-specific visual trade dress.

## 10. Error handling

| Condition | Product behavior |
|---|---|
| Invalid, truncated, or unsupported image | Reject before inference; explain supported formats and keep the prior screen intact |
| HEIC decoder unavailable | Explain the packaging problem; do not silently skip the file |
| EXIF orientation present | Normalize identically in training, evaluation, desktop inference, and phone upload |
| Model or manifest missing/corrupt | Fail startup health check and show a recovery screen with model/app versions |
| Model/database schema mismatch | Block assessment and identify the incompatible bundled versions |
| Confidence below released threshold | Show **Needs review**, top alternatives, and category correction; do not make confident downstream claims |
| Component template absent | Keep classification, show no component estimate, and report the missing reference revision |
| Lifecycle inputs insufficient | Display **Unknown** and list the missing facts that would improve the estimate |
| Potential safety issue | Place the safety message before reuse guidance and recommend the relevant test or specialist action |
| Phone session cannot bind or advertise | Keep desktop scanning functional and show focused network troubleshooting |
| Phone token invalid/expired | Reject without revealing app data; let the Mac create a new session |
| Local history write fails | Preserve the classification result and explain that it was not saved |
| Explanation computation fails | Preserve the prediction and mark the optional explanation unavailable |

Errors use plain language and a next action. Technical diagnostics are written to a
rotating local log and exposed through **Help → Open Logs**, not shown as raw tracebacks.

## 11. Packaging and release

The build produces:

- `E-Waste Triage.app`;
- a tester-facing DMG or zip;
- release notes containing app, model, preprocessing, and component-reference versions;
- a machine-readable build manifest with hashes;
- simple unsigned-app Gatekeeper instructions.

App-owned writable data lives under the macOS Application Support and Logs directories,
never inside the read-only application bundle. Temporary uploads use app-scoped temporary
directories and are removed after processing unless the user elects to retain them.

The later signed release replaces only the packaging/signing step. The application
architecture and user data paths remain unchanged.

## 12. Verification and acceptance criteria

### 12.1 Model and preprocessing

- Training, evaluation, desktop import, and phone upload share one tested EXIF-aware image
  normalization path.
- ONNX and approved PyTorch reference predictions have identical top-1 classes on the
  release reference set and probabilities within the documented numeric tolerance.
- All five released categories, the low-confidence path, and top-alternative ordering
  have regression coverage.
- JPEG, PNG, HEIC, WebP, portrait EXIF rotation, oversized images, corrupt files, and
  unsupported files have end-to-end tests.

### 12.2 Component and lifecycle data

- Every released category compiles to a valid standard template.
- Every lifecycle range and safety rule carries source and revision metadata.
- Range calculations cover boundary ages, missing values, conflicting values, and
  unknown results.
- User edits never mutate the bundled reference database.
- Historical snapshots remain unchanged after installing a newer template revision.

### 12.3 Desktop behavior

- Double-clicking the app launches a usable window without Terminal.
- An offline clean-account launch succeeds on the supported macOS version.
- A normal classification completes within the agreed performance target on the
  development Mac; the optional explanation cannot block the result.
- Window layouts are usable at the minimum size and normal desktop sizes without clipped
  controls or horizontal scrolling.
- Keyboard navigation, focus order, contrast, and reduced-motion behavior are tested.
- All buttons, loading states, result population, navigation transitions, and history
  actions complete their functional state changes after animation.

### 12.4 Privacy and networking

- No internet connection is required for classification, assessment, history, or
  reference lookup.
- No LAN port listens until the user starts phone capture.
- Phone routes require the active token and cannot access desktop-only endpoints.
- Session expiry, manual termination, upload limits, concurrent uploads, IPv4 Wi-Fi, and
  the verified IPv6-only hotspot scenario are tested.
- Clearing history removes the associated app-managed files.

### 12.5 Release gate

- The repository test suite passes from a clean environment.
- The packaged app passes startup, classification, assessment, history, phone transfer,
  and clean shutdown smoke tests.
- A fresh tester account completes the unsigned-app first-run instructions.
- Release artifacts record exact source revision and content hashes.

## 13. Implementation principles

- Build the smallest vertical slice first: packaged shell → import → normalized inference
  → result.
- Keep UI, model inference, lifecycle rules, and persistence behind explicit interfaces.
- Prefer deterministic, source-backed reference logic over additional speculative ML.
- Preserve existing behavior with tests before refactoring routes or classifier code.
- Never overwrite the current production model during smoke tests or packaging.
- Treat EXIF consistency, model parity, data provenance, and local-network exposure as
  release blockers rather than polish tasks.

## 14. Approved design decisions

- Mac-first release with portable architecture.
- Initial distribution to the owner and a small tester group.
- Unsigned packaging until an Apple Developer membership is available.
- User app is inference/assessment only; training remains admin-only.
- Models and reference data update through normal app releases.
- Optional same-network QR phone capture is included.
- Clearable, private local history is included.
- Lifecycle values are conservative ranges with confidence labels.
- Component templates are standardized for the five current device categories.
- Item-specific edits do not alter the standard database.
- Motion is polished, restrained, functional, performant, and reduced-motion aware.

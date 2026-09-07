# E-Waste Triage Evidence, Condition, and Lifecycle Prototype — Architecture Design

**Date:** 2026-09-06

**Status:** Approved by the product owner on 2026-09-07

**Audience:** Product owner, internal prototype testers, and administrators who prepare model and reference releases

**Target:** Apple Silicon macOS 14 or later, with portable service and data boundaries for later Windows and Linux applications

## 1. Relationship to the existing product design

This specification extends
`2026-09-05-ewaste-triage-mac-app-design.md`. The earlier design still governs
the local Flask service, pywebview shell, phone handoff, package integrity, and
scientific-honesty boundaries except where this document is more specific.

This document intentionally supersedes these earlier constraints:

- the primary navigation now has four destinations—**Scan**, **Assessment**,
  **Components**, and **History**—instead of three;
- visible condition and lifecycle are separate primary results rather than one
  condition-adjusted lifecycle presentation;
- the reference bundle expands from sparse category templates to a deep,
  versioned identity, lifecycle, component, hazard, and recommendation corpus;
- a new visible-condition model may assist grading, subject to an explicit
  release gate and a complete manual fallback; and
- startup presents a native loading surface before heavyweight initialization,
  rather than waiting to create the window until initialization is complete.

To keep the prototype boundary coherent, this specification also defers the
earlier optional valuation output, assessment-file export, retained-original
photo option, and global “disable future history” control. Successful scans use
managed-thumbnail history with explicit delete and clear controls; raw originals
are never retained by this prototype.

No change in this specification permits cloud inference, runtime reference
downloads, silent background training, or claims about hidden device condition
from an exterior photograph.

## 2. Product outcome

The prototype turns one photograph into two clearly separated results:

1. **Visible condition** — an image-based, five-level assessment of observable
   exterior condition, with findings, confidence, and an editable user decision.
2. **Lifecycle estimate** — an evidence-based range derived from confirmed
   identity, user-provided usage facts, and a reviewed offline reference bundle.

The result then leads to a standard components view containing conditional
hazards, reusable-part guidance, and conservative next steps. The user can
correct the device identity and all item-specific observations. Every result
must make clear which facts came from the model, the user, an authoritative
source, or a broad industry-average fallback.

The first release goes deep on exactly five categories:

- laptop;
- mobile phone;
- headphones;
- computer mouse; and
- keyboard.

Coverage includes common modern and legacy variants within these categories.
Additional categories are outside this prototype and require a later evidence,
model, and UI release.

## 3. Claim and evidence boundaries

### 3.1 What the application may claim

The application may present:

- a suggested device category and alternatives from the image classifier;
- local OCR or visual suggestions for manufacturer, family, subtype, and model;
- visible exterior observations and a suggested five-level condition grade;
- a lifecycle range tied to a compatible reference endpoint and confirmed item
  facts;
- components commonly associated with, conditional on, legacy-specific to, or
  confirmed for the chosen device identity;
- sourced safety information and conditional hazard guidance;
- deterministic reuse, repair, parts-recovery, specialist-handling, recycling,
  or information-needed recommendations; and
- the sources, assumptions, evidence tier, model versions, and bundle version
  behind each result.

### 3.2 What the application must not claim

The application must not imply:

- that an exterior photo detects a hidden component, material, battery
  chemistry, failure, or hazardous substance;
- that attention or saliency is physical diagnosis;
- that an endurance threshold such as cycles-to-80%-capacity is total product
  life or end of life;
- that warranty, support availability, repairability, modeled use duration, or
  one-charge runtime is physical component life;
- that broad category data describes the exact bill of materials of an item;
- that visible condition proves functional condition or safety; or
- that missing evidence is evidence of absence.

When evidence cannot support a range or association, the result is **Unknown**.
The application never manufactures a precise percentage merely to fill a UI.

## 4. System architecture

The prototype is divided into six independently testable units.

### 4.1 Desktop shell and startup coordinator

The macOS shell owns the native window, lifecycle, local service, recovery
surface, and release-integrity boundary. It creates the window immediately with
a self-contained startup document, then initializes trusted resources off the
GUI thread.

The startup state machine is:

`BOOTSTRAP → INITIALIZING → REVEALING → READY`

with separate `DEGRADED`, `RECOVERY`, and `CLOSING` states. Initialization has
real stages—release verification, model loading, reference opening, history
opening, application assembly, and loopback binding—but the live region does
not announce every fast internal step.

There is no artificial minimum splash duration. When the local service is
ready, the shell navigates immediately to it. Repeating startup animation stops
after five seconds, while truthful slow-start copy remains visible. Retry is
single-flight and generation-tokened so stale initialization cannot navigate a
closed or newer window.

### 4.2 Local application service

The packaged application continues to use an ephemeral `127.0.0.1` Flask
service with a per-launch capability key. The service owns validation,
reference resolution, policy decisions, persistence, and API serialization.
The browser UI never performs authoritative lifecycle or hazard calculations.

Phone capture remains a separately activated same-network HTTP listener. It is
off until the user explicitly starts a session, uses a memory-only capability
URL plus six-digit code, expires automatically, and is stopped on dismissal,
shutdown, or completion. The product must continue to state that this transfer
is local HTTP and is not TLS.

### 4.3 Analysis coordinator

One normalized image is passed to three independent analysis capabilities:

- the existing five-category classifier;
- an identity suggestion capability using local OCR and catalog matching; and
- the new visible-condition estimator.

Each capability reports its own `ready`, `low_confidence`, or `unavailable`
state and immutable engine provenance. A failure in identity or condition
analysis does not erase a valid category prediction. OCR operates before the
raw upload is discarded; raw OCR transcripts and serial-number-like strings
are not persisted by default.

### 4.4 Evidence resolver

The resolver accepts only a canonical, user-confirmed identity scope. It
selects one compatible lifecycle record using this precedence:

`exact model → product family → subtype → industry average`

It filters by subject, endpoint, metric, applicability, time period, and device
variant before specificity. It selects the first applicable reviewed tier and
never blends tiers. If multiple records at the same tier conflict, the resolver
uses the bundle's explicit precedence metadata or returns Unknown; it never
chooses opportunistically at runtime.

A confirmed category-only decision is a valid canonical scope for an industry-
average lookup. An Unknown category skips lifecycle resolution and category
component templates. Free-form identity text is preserved as user-provided
context but does not receive exact-model or family evidence until it is linked
to a canonical catalog record.

### 4.5 Assessment and policy engine

The assessment engine combines immutable machine evidence, explicit user
observations, and one resolved reference record. It returns visible condition,
lifecycle, component associations, hazards, recommendations, calculation
trace, and source snapshots as distinct fields.

Safety policy overrides lifecycle optimism. A severe safety trigger can require
specialist handling even when a lifecycle estimate suggests substantial
remaining use. Policy is deterministic, versioned, and tested independently
from model training.

### 4.6 Local history store

The Application Support database stores versioned scan aggregates and managed
history thumbnails. It never mutates machine evidence or an old assessment
snapshot in place. Reference and model updates therefore cannot silently
rewrite past results.

## 5. Offline evidence bundle

### 5.1 Bundle contents

One immutable, release-bound knowledge bundle contains:

- **identity records:** category, subtype, manufacturer, family, model,
  aliases, model years, distinguishing text tokens, and applicability dates;
- **lifecycle records:** subject, endpoint, metric, unit, lower and upper
  bounds, endpoint qualification, applicable identity scope, evidence grade,
  assumptions, and source links;
- **component associations:** component identity, relationship status,
  applicability, template scope, and per-claim provenance;
- **hazard records:** linked component, conditional applicability, trigger
  observations, severity, user action, handling guidance, and independent
  sources;
- **industry-average records:** broad ranges, population definition,
  methodology, publication period, uncertainty, and limitations; and
- **policy records:** deterministic recommendation and safety-escalation rules.

Lifecycle and hazard claims have separate provenance. A battery endurance
source cannot become the citation for battery safety simply because both claims
refer to the same component.

### 5.2 Evidence levels

The bundle uses four evidence levels:

- **A — exact model:** a manufacturer, regulator, or qualified technical source
  directly identifies the model or model-year configuration;
- **B — family or subtype:** a source supports a defined product family or
  technical subtype;
- **C — category or industry range:** a transparent, broadly scoped estimate
  supports a category-level fallback but not an exact device;
- **D — process or contextual:** evidence supports handling or recycling
  controls but not the composition or lifespan of an intact item.

The UI translates these into plain language rather than relying on letters
alone. Grade D cannot populate item composition or lifecycle fields.

### 5.3 Industry-average fallback

Broad industry-average ranges are allowed because the user explicitly selected
that fallback. They must:

- identify the population, period, and methodology used;
- remain a range rather than a point value;
- display **Broad estimate · Low confidence**;
- list every user input and default assumption;
- never override a compatible, more-specific reviewed record; and
- return Unknown when the record's endpoint is not comparable to the requested
  lifecycle result.

Condition may widen or conservatively shift a derived range according to a
versioned policy, but it never edits the original sourced range. The UI shows
the source range and derived item estimate separately.

### 5.4 Lifecycle calculation and visualization

The lifecycle result contains two layers:

- the unchanged **reference range**, including its subject and endpoint; and
- an optional **item estimate**, derived from compatible user-confirmed usage.

For a true total-life interval `[life_lower, life_upper]` and a compatible usage
interval `[usage_lower, usage_upper]`, the estimated percentage-used interval is:

`[100 × usage_lower / life_upper, 100 × usage_upper / life_lower]`

The textual result preserves values beyond 100% as **at or beyond the reference
range**. A bounded visual band may stop at 100%, but it must not conceal that
the calculated upper bound exceeds the reference range. Remaining-use bounds
are calculated from the corresponding interval subtraction and never shown as
negative.

The application performs this calculation only when the usage and life metrics
are comparable—for example, years with years or full charge cycles with full
charge cycles—and the lifecycle record describes a total-life endpoint. A
cycles-to-80%-capacity record instead displays **progress toward the documented
capacity threshold**. It must not produce percent life consumed.

There is no universal numerical condition multiplier. A visible grade can
alter a lifecycle interval only when the bundle contains a reviewed,
scope-compatible condition-adjustment policy with its own methodology and
provenance. Without one, condition affects uncertainty copy and recommendations
but leaves lifecycle arithmetic unchanged. Missing compatible usage inputs
show the reference range without an item percentage.

### 5.5 First-bundle coverage floor

“Deep coverage” has a concrete minimum for the first prototype bundle:

- at least ten canonical family or model identity records per category—fifty
  total—with aliases, model-year scope, and at least two manufacturers per
  category;
- at least four technical subtypes per category, including one current-market
  and one discontinued or legacy subtype;
- one reviewed broad device/service-life range per category, plus at least
  three more-specific lifecycle or endurance records per category whose exact
  subject and endpoint remain visible;
- one complete standard component template per category, plus at least one
  modern and one legacy overlay where component architecture differs;
- structured battery-bearing and battery-free distinctions for headphones,
  mice, and keyboards rather than a generic battery assumption; and
- a published matrix showing every identity, lifecycle, component, and hazard
  claim, its evidence level, its source state, and every deliberate Unknown.

These are release-blocking minimum targets, not permission to weaken evidence
rules. If a target cannot be filled with defensible evidence, the bundle records
the gap as Unknown for development visibility and the prototype is not declared
complete for that category. Unsupported substitute claims are prohibited.

### 5.6 Source acquisition and review

Runtime operation uses no online dataset. Administrators may assemble a new
bundle from authoritative public sources and appropriately licensed datasets in
the admin sandbox. Preferred lifecycle and hazard sources are regulators,
standards bodies, manufacturers, official recycler guides, and transparent
industry studies. Image datasets are governed separately by their licenses and
are training evidence, not lifecycle evidence.

No single generic online parts dataset is treated as a complete bill of
materials. A licensed structured dataset may seed the administrator review
queue, but common-part associations are published only after they are reconciled
with category/subtype definitions and claim-level sources. Dataset import never
auto-publishes records into the live bundle.

Every imported claim records source title, publisher, canonical URL, publication
or revision date, access date, license or use basis, evidence grade, reviewer,
and review date. Unsupported extrapolations, unclear licenses, and sources that
do not match the claim endpoint are rejected during compilation.

Source citations remain visible and copyable while offline. Opening an external
source is an explicit user action and may require internet access; the app never
fetches citation pages in the background.

## 6. Visible-condition analysis

### 6.1 Five-level grade

The visible-condition result uses exactly these ordered grades:

1. **Excellent** — no meaningful visible wear or damage;
2. **Good** — minor cosmetic wear without visible structural damage;
3. **Fair** — moderate visible wear or limited visible damage;
4. **Poor** — major visible damage likely to require inspection or repair; and
5. **Critical** — severe visible exterior damage requiring cautious handling.

**Unknown** is a separate state when the image is insufficient or the
capability is unavailable. Critical is not a claim of internal electrical or
chemical danger. Safety questions remain an independent user-observation path.

### 6.2 Model output and deterministic rubric

The condition capability predicts observable findings, such as visible cracks,
deformation, missing exterior parts, corrosion-like appearance, surface wear,
or an obstructed/insufficient view. A deterministic, versioned rubric maps
those findings to the five-level suggestion. The result includes:

- suggested grade;
- finding list;
- independent confidence or uncertainty;
- image sufficiency state;
- condition model and rubric versions; and
- the fixed statement **Visible exterior only**.

The user may confirm or change the grade and findings. Machine evidence remains
unaltered; the user decision is stored separately with attribution and time.

### 6.3 Training and release gate

Training uses licensed imagery plus first-party labeled photographs. Split
boundaries are device- and capture-session-grouped, so views of the same
physical object cannot appear across training, validation, and holdout sets.
The evaluation report includes class balance, macro-F1, per-grade precision and
recall, ordinal confusion, image-sufficiency performance, calibration, and
category slices.

The automated condition suggestion is enabled only when, on the frozen grouped
holdout, it exceeds the majority-grade baseline by at least 0.10 macro-F1 and
achieves at least 0.70 recall across at least 30 independently grouped Critical
devices. If either gate is not met or the holdout has fewer than 30 independent
Critical devices, the release uses the same five-level guided manual rubric and
labels automation unavailable. The rest of the prototype remains fully
functional.

No production scan causes online learning. Live-app corrections remain local
and are not uploaded or exported automatically. Administrators may separately
import expressly consented label sets into the sandbox for a future reviewed
training run, but those labels do not update the live model automatically.

## 7. Components, hazards, and recommendations

### 7.1 Component associations

The Components destination begins with the category template, then applies
subtype, family, and exact-model overlays. Every component carries one status:

- commonly associated;
- conditional;
- legacy-specific;
- exact-model confirmed;
- user confirmed;
- not present; or
- Unknown.

The application says **expected component** or **commonly associated**, never
**detected**, unless the user confirms the item or an exact-model source proves
the association. Overrides remain attributed to the user.

The user may mark a component present, not present, or Unknown and may add an
item-specific component note. A user may also enter an item-specific lifecycle
range with metric, unit, and optional citation. Such a range is labeled
**User-provided · Not independently verified**, never replaces the bundled
reference record, and is frozen beside the sourced result. When its metric is
compatible, it may produce a separate **User scenario** calculation; it cannot
silently replace the evidence-backed result or suppress applicable safety
guidance.

### 7.2 Structured hazards

Hazards are separate records with:

- hazard and component identifiers;
- scope and applicability text;
- triggering user-observation keys;
- severity;
- immediate and follow-up actions;
- handling and disposal guidance;
- evidence level; and
- one or more hazard-specific source snapshots.

The UI states that these are category-, subtype-, or model-based possibilities,
not findings from the photo. Generic RoHS, WEEE, REACH, or recycling-process
evidence cannot be presented as proof that an individual device contains lead,
cadmium, mercury, brominated flame retardants, or another substance.

### 7.3 Recommendation policy

The closed recommendation set is:

- **Reuse**;
- **Repair**;
- **Parts recovery**;
- **Specialist handling**;
- **Certified recycling**; and
- **More information needed**.

Rules consider confirmed identity, visible grade, operational state, known issue
flags, lifecycle evidence, component-specific facts, and hazard triggers.
Hazard-triggered specialist handling takes precedence over reuse or parts
recovery. Unknown evidence produces a request for the missing observation or
model detail rather than an optimistic recommendation.

The Components destination displays, in order: urgent safety guidance, reusable
or testable parts, expected components, component-specific endurance facts,
sources, and editing controls. Hidden internal parts are never shown as visually
verified.

## 8. User experience and navigation

### 8.1 Primary destinations

The application has four clearly labeled primary destinations:

- **Scan** — Mac import, phone handoff, analysis progress, and the latest result;
- **Assessment** — identity review, visible condition, lifecycle inputs, and the
  frozen assessment summary;
- **Components** — component associations, hazards, reuse guidance, and sources;
- **History** — saved scans, revisions, comparison, deletion, undo, and clear all.

Assessment and Components are always reachable. Before a scan is selected, each
shows an intentional prerequisite state with actions to start a scan or open
History; absence of a scan is not rendered as an application error.

About, release versions, local/offline status, and recovery guidance remain
secondary utilities rather than primary tabs. Phone capture remains an action
inside Scan.

### 8.2 Result and editing flow

The primary flow is:

`Scan → Review identity → Visible condition and lifecycle → Components → History`

The predicted category remains labeled **Suggested** until the user explicitly
confirms it, selects another one of the five canonical categories, or chooses
**I’m not sure**. OCR and catalog matches are suggestions only. The user may
select a canonical identity, confirm category only, or preserve free-form model
text as an unverified note.

The Assessment destination presents separate cards for identity, visible
condition, and lifecycle. It never collapses their confidence or evidence into
one score. The lifecycle card shows the unchanged source range, the optional
derived item range or threshold progress, the evidence scope, assumptions, and
the reason for Unknown. The user can edit identity decisions, condition grade,
age or compatible usage, operational state, issue flags, and item-specific
overrides. Saving keeps the form mounted and creates a new revision.

Components is enabled after a canonical category decision. Safety guidance
appears before reusable parts and expected components in visual and reading
order. Returning to Scan, opening About, or switching destinations preserves
unsaved form values until the user saves, discards, deletes, or selects another
scan.

### 8.3 Quiet Precision visual system

The approved direction uses a restrained graphite, warm-neutral, and emerald
system with generous space, high information contrast, system typography, and
few decorative surfaces. Supporting text must remain readable at 11 px or
larger on the reference display and meet applicable contrast requirements.

One minimal continuity mark is used throughout the app, startup surface, phone
handoff, and packaged icon. It consists of a stable center/core and a simplified
outer continuity or scan loop. Inline SVG with `currentColor` is preferred for
in-app use so the static-resource security boundary remains small. Platform-
dependent Unicode symbols are not used as product marks.

The initial native window is approximately 1120 × 760, with a minimum of
760 × 620. The four destinations remain labeled at both sizes. Layout may
condense at the minimum size but must not introduce horizontal scrolling,
clipping, or hidden primary actions.

### 8.4 Progressive loading and motion

The startup mark rotates only its outer loop while a wrapper or halo gently
pulses from opaque toward translucent. The center remains stable. Startup copy
describes real work and never displays fabricated percentages.

Once ready, the shell and Scan surface reveal in no more than two groups.
Results populate in dependency order—identity and visible condition first,
lifecycle second, Components after an identity decision—without hiding already
valid content. History may load in the background and shows a truthful loading
state rather than briefly claiming it is empty.

Motion rules are:

- animate only opacity and transform on large surfaces;
- use 150–320 ms transitions for interaction and reveal;
- finish each staged sequence within 350 ms;
- never gate persistence, navigation, or accessibility state on animation;
- disable spins, pulses, staggers, springs, and scale effects under
  `prefers-reduced-motion`; and
- stop repeating startup motion after five seconds.

Controls provide tactile press feedback, visible keyboard focus, stable layout
while loading, and plain-language live-region updates. Forms remain mounted
during save or recalculation so unsaved user input cannot disappear.

## 9. Data model and API boundaries

### 9.1 Versioned scan aggregate

Each scan stores three distinct layers:

1. **Immutable machine evidence:** original category/top-k output, minimal
   redacted identity suggestions, visible-condition findings, image sufficiency,
   per-capability state, and exact model/preprocessing/bundle identifiers.
2. **User decisions and observations:** identity state, canonical IDs,
   user-entered display values, condition corrections, age or usage facts,
   operational state, issue flags, component confirmations, source=`user`, and
   revision timestamps.
3. **Immutable assessment revision:** selected lifecycle record, resolution
   trace, sourced and derived ranges, component/hazard snapshots, complete
   source metadata, recommendation output, policy version, and knowledge-bundle
   hash.

An update creates a new user-decision or assessment revision. It never rewrites
the old machine evidence or frozen assessment. **Reassess with current bundle**
creates a new assessment revision beside the original and provides a comparison;
it does not overwrite history.

### 9.2 API shape

New work uses an additive `/api/v2` boundary. Existing `/api/v1` routes remain
temporary adapters until packaged smoke and migration tests prove parity.

- `POST /api/v2/scans` creates one scan and returns the three independent
  analysis-capability states.
- `PUT /api/v2/scans/{id}/identity-decision` stores `confirmed`, `edited`,
  `category_only`, or `unknown` with canonical scope where available.
- `PUT /api/v2/scans/{id}/observations` stores user facts independently from
  machine evidence.
- `POST /api/v2/scans/{id}/assessment-revisions` explicitly freezes one
  reference and policy result.
- `GET /api/v2/scans/{id}/summary` returns a saved revision without mutation.
- `GET /api/v2/scans/{id}/components` returns the saved Components snapshot.
- `GET /api/v2/catalog/identities` searches the bundled canonical catalog only.
- `POST /api/v2/scans/{id}/reassess` creates a current-bundle revision while
  preserving the prior revision.

All GET endpoints are read-only. Creation and update requests validate the full
payload before opening a transaction. Child records and managed media use
cascade-safe deletion semantics.

Existing history is migrated conservatively. A pre-v2 scan retains its original
prediction and model provenance, and an existing explicit class confirmation is
mapped to a category-only identity decision. Migration does not invent OCR,
visible-condition, lifecycle, or hazard evidence. Legacy assessment snapshots
remain readable; the user may create a new current-bundle revision explicitly.

## 10. Privacy and retention

All classification, condition analysis, OCR, reference lookup, and assessment
work occurs on the Mac. The packaged runtime contains no analytics, advertising,
telemetry, cloud inference, remote fonts, or background reference synchronization.

The default retention behavior is:

- discard the uploaded original after normalization and inference;
- retain one managed thumbnail only when the scan is saved to History;
- avoid retaining complete OCR transcripts and serial-number-like values;
- retain only canonical identity matches and minimal redacted suggestion
  evidence unless the user explicitly confirms text;
- keep phone uploads in temporary storage and remove them after processing,
  session cancellation, expiry, or shutdown; and
- store history, models, references, and logs only in their defined local
  application locations.

A single delete hides the scan immediately and moves its aggregate, revisions,
and managed media into a session-local tombstone for ten seconds. Undo restores
that exact aggregate during the interval; expiry or application shutdown purges
it. Clear History requires explicit confirmation and then purges all history and
managed media immediately without Undo. Closing the app also removes any
temporary phone-session data and listener.

## 11. Admin-only training and release pipeline

The user application has no training controls. Administrators work in a separate
sandbox that may access source datasets and development tooling but never shares
writable training state with the live app.

The admin workflow performs:

1. licensed image and authoritative reference ingestion;
2. source, scope, endpoint, license, duplication, and schema validation;
3. device/session-grouped dataset splitting and frozen-holdout creation;
4. model training, evaluation, calibration, and ONNX parity checks;
5. identity, lifecycle, component, hazard, average, and policy bundle
   compilation;
6. canonical logical-digest and raw-file hash generation;
7. malicious-path, malformed-content, and cross-release swap rejection;
8. packaged application assembly and offline smoke testing; and
9. release notes and reports.

The closed release manifest identifies the app version, category model,
condition model or manual-only state, preprocessing contract, identity catalog,
knowledge database, policy revision, and every raw/logical hash. Frozen startup
binds runtime resources to those values. An administrator publishes changes only
through a new app release; no production user receives a silently changed model
or database.

Release notes state, at minimum, app version, category-model version,
condition-model/rubric version, preprocessing version, knowledge-bundle version,
policy version, source revision, known limitations, and evidence-coverage change.

## 12. Failure and recovery behavior

- A release-manifest, category-model checksum, schema, label, or inference-shape
  failure is fatal and opens a focused recovery surface with Reinstall guidance
  and Quit.
- A missing or invalid condition model disables the automated suggestion and
  uses the guided five-level manual rubric.
- A valid category model with an unavailable evidence bundle keeps Scan usable,
  disables evidence-backed lifecycle and Components results, and offers one
  explicit retry.
- A history initialization failure permits unsaved scanning and exposes a retry
  from History. It must not pretend a scan was saved.
- Identity-analysis failure permits category-only or Unknown confirmation.
- A valid bundle with no applicable record returns an explanatory Unknown, not
  a recovery screen.
- Loopback and phone-session failures offer a user-triggered retry and leave no
  orphan listener.
- Unexpected initialization exceptions are caught at the worker boundary,
  sanitized for the UI, and logged locally without exposing paths or secrets.

Partial results remain visible when another capability fails. Recovery and
retry code closes partially opened stores and servers before publishing a new
state.

## 13. Verification strategy

### 13.1 Evidence and policy

Automated tests prove:

- exact-model, family, subtype, and industry-average precedence;
- endpoint and subject compatibility before specificity;
- deterministic conflict handling and no-match Unknown behavior;
- source snapshots and independent lifecycle/hazard provenance;
- all component association states and modern/legacy overlays;
- safety overrides over optimistic lifecycle results;
- closed recommendation values and missing-input guidance;
- deterministic rebuilds, schema validation, logical hashes, and cross-release
  tamper rejection; and
- historical snapshots remaining unchanged after a newer bundle is installed.

### 13.2 Models

Category-model regression tests preserve the existing five-class contract and
record any accuracy change. Condition-model evaluation uses the frozen,
device/session-grouped holdout and enforces the release gate in section 6.3.
Reports include confusion matrices, macro and per-grade metrics, calibration,
category slices, representative errors, dataset licenses, and identified data
gaps. ONNX export must remain within the approved numerical parity tolerance.

### 13.3 Service and persistence

API, transaction, and concurrency tests cover the complete scan aggregate,
payload-before-mutation validation, explicit identity decisions, immutable
machine evidence, assessment revision creation, reassessment comparison,
save/correction races, history reopen, cascading deletion, undo, clear all,
temporary media cleanup, and restart behavior.

### 13.4 UI and accessibility

Executed controller and DOM tests cover all four destinations, prerequisite
states, visible-condition correction, separate lifecycle presentation,
Components safety ordering, source links, loading and error states, unsaved form
preservation, About, phone handoff, history revisions, and hostile text rendered
through `textContent`.

Keyboard navigation, focus return, live regions, native-dialog behavior,
contrast, 760 × 620 layout, 1120 × 760 layout, dark appearance, and reduced
motion are verified. Motion tests assert the permitted properties, maximum
timelines, and independence from functional state.

### 13.5 Startup, package, and real workflow

Tests prove the native window appears before blocked initialization completes,
navigation occurs only after service readiness, fast startup has no forced
dwell, stale initialization cannot publish, and all failure paths clean up.

Packaged smoke covers offline launch, release integrity, Mac photo analysis,
identity review, manual or automated condition grading, lifecycle resolution,
Components, History, reassessment, deletion, About versions, phone transfer,
and shutdown. Manual acceptance additionally covers a fresh macOS account,
DMG mount/copy/eject, offline first launch, Finder/Open behavior, real IPv4 and
IPv6 phone paths where available, Local Network permission behavior, VoiceOver,
Reduce Motion, and clean relaunch.

Performance targets on the supported reference Mac are:

- first visible native startup surface within 1 second at p95;
- Scan usable within 2 seconds at p95;
- truthful slow-start copy at 2 seconds;
- a long-start state with Quit at 10 seconds; and
- no LAN listener before explicit phone-session activation.

## 14. Prototype completion criteria

The internal prototype is complete only when:

- the five-category product operates entirely offline except for explicit local
  phone transfer;
- visible condition and lifecycle are independently displayed, edited, stored,
  and sourced;
- the knowledge bundle has reviewed modern and legacy coverage across all five
  categories, with a published coverage matrix and honest Unknown gaps;
- condition automation either clears its release gate or the complete manual
  fallback ships in its place;
- no result calls category associations or hazard possibilities photo-detected;
- old assessments retain original model, policy, source, and bundle provenance;
- all automated tests pass and independent review reports no unresolved
  Critical or Important findings;
- a packaged internal-test DMG passes integrity and offline smoke checks; and
- the release includes notes, evidence coverage, model evaluation, admin update
  procedure, and a manual hardware acceptance checklist.

The initial deliverable may be ad-hoc signed and is for internal prototype
testing. Developer ID signing, notarization, automatic updates, public
distribution, Windows/Linux packages, additional categories, cloud services,
and automatic hardware diagnostics remain later milestones and do not block
this prototype.

## 15. Implementation sequence

Implementation proceeds in dependency order:

1. versioned evidence schema, deep five-category corpus, compiler, and resolver;
2. scan aggregate, v2 service contract, immutable revisions, and privacy cleanup;
3. condition-labeling procedure, dataset preparation, estimator, evaluation, and
   manual fallback;
4. Quiet Precision shell, canonical logo, four-destination navigation, startup
   coordinator, progressive results, and accessibility behavior; and
5. release-manifest expansion, package rebuild, independent review, automated
   verification, and manual prototype handoff.

Each phase remains releasable behind an honest unavailable or manual state.
Training and UI work may run in parallel only after their shared data and API
contracts are frozen.

This document is the umbrella architecture contract, not one monolithic coding
task. Execution is decomposed into the five release slices above. Each slice
receives its own implementation plan, tests, review checkpoint, and integration
gate. A later slice may refine internals but cannot change the approved claim,
privacy, data, or user-experience contracts without another design review.

## 16. Approved decisions

The product owner explicitly approved:

- the layered hybrid architecture;
- exact identity suggestions followed by explicit user confirmation or edits;
- two separate primary results for visible condition and lifecycle;
- an offline bundle updated only through app releases;
- deep modern and legacy coverage for the current five categories;
- a five-level visible-condition grade;
- a clearly labeled broad industry-average lifecycle fallback;
- structured standard components and conditional hazard guidance;
- four clear primary navigation destinations;
- the Quiet Precision visual direction and minimal continuity mark;
- truthful immediate startup feedback, progressive background loading, and
  polished reduced-motion-aware animation;
- immutable history revisions and local-first privacy defaults;
- admin-only training and knowledge updates; and
- an internal macOS prototype DMG as the first completion target.

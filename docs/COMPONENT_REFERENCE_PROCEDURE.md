# Component Reference Release Procedure

This procedure is for administrators who review and publish the component-reference
database bundled with E-Waste Triage. The reviewed YAML in `reference/` is authoritative;
the generated SQLite file is a release artifact and must not be edited directly.

The reference describes components commonly associated with a confirmed device category.
It is not a teardown, a bill of materials, proof that a component is present, or a health
reading from the uploaded photo. The classifier contributes the device category only.

## Current release boundary

The release contains exactly these category templates:

- computer mouse (`0301_computer_mouse`);
- keyboard (`0301_keyboard`);
- laptop (`0303_laptop`);
- mobile phone (`0306_mobile_phone`); and
- headphones (`0401_headphones`).

The only sourced generic endurance endpoint in version `2.0.0` is the mobile-phone
lithium-ion battery regulatory minimum of 800 cycles to 80% capacity. It is not a
total-lifetime denominator: cycle count alone must leave lifecycle percentage
**Unknown**, including at or beyond 800 cycles. Every other generic component lifecycle
is null and must also appear as **Unknown**. Do not copy the phone rule
to laptops, headphones, keyboards, mice, or manufacturer-specific products without a
source that actually supports that scope.

## 1. Select authoritative sources

Prefer sources in this order: applicable law or regulation, government safety guidance,
manufacturer documentation for a clearly identified product scope, then a well-designed
primary study. Do not use search snippets, retailer copy, unsourced aggregations, or a
single product's specification as a generic category claim.

For each candidate source, verify that it supports the exact metric, population,
conditions, geography, and wording being proposed. Record it in `reference/sources.yaml`
with a stable `source_id`, title, publisher, HTTPS URL, review date, and evidence grade.
The review date is the date an administrator last opened and checked the source, not its
publication date.

Use an evidence grade that says what authority the source provides:

- `regulatory_minimum` for a binding minimum requirement such as the released phone
  battery cycle rule;
- `regulatory` for applicable regulatory context;
- `primary_guidance` for first-party government safety or handling guidance; and
- `manufacturer_documentation` for first-party product documentation whose scope is
  preserved in the claim.

These labels are project review conventions. The current compiler requires a non-empty
grade but does not enforce a closed vocabulary, so the reviewer must reject invented,
ambiguous, or mismatched grades.

## 2. Author claims conservatively

Edit `reference/device_components.yaml`. Use only the approved presence labels
`standard`, `common`, `optional`, and `unknown`. Presence describes the category template,
not something detected in the image. Use `optional` for batteries in devices that may be
wired, including the released mouse, keyboard, and headphones templates.

Every non-null lifecycle and every safety-sensitive component must carry `source_ids`,
`evidence_grade`, and `reviewed_on`. Every safety rule must carry the same provenance
plus an explicit `revision`; version `2.0.0` starts the authored rules at `1.0.0`.
Category handling notes must cite registered sources and remain potential-substance
context; they must never claim that a photographed item contains a specific substance.

When evidence does not support a generic range, either omit the `lifecycle` field or set
it explicitly to `null`. The compiler treats both forms identically: each becomes SQL
`NULL` and a `None`/JSON `null` lifecycle in the compiled snapshot. The current YAML omits
the field for unsupported lifecycles. Null is a deliberate release decision, not missing
clerical work: the assessment must return **Unknown** and name the item-specific input or
supported reference needed to improve it. Never use an empty mapping as a null marker,
and never infer lifecycle, internal condition, or safety clearance from classifier
confidence.

Review safety copy separately from reuse copy. A safety escalation must appear before
reuse guidance and cannot be cleared by an exterior photo or a high-confidence category
prediction. For lithium-ion batteries, retain the sourced EPA direction not to place the
battery in household trash or municipal recycling and to use an appropriate battery
collection option. Preserve conditional wording where a battery's presence is optional.

## 3. Review dates and evidence

Before release, a second reviewer must:

1. open every URL used by a changed claim;
2. confirm the source still says what the claim relies on;
3. confirm the claim does not broaden the source's product or jurisdictional scope;
4. update the source and claim `reviewed_on` dates to the actual review date;
5. confirm the evidence grade matches the source type; and
6. read the rendered safety and **Unknown** copy in context.

A review date alone is not proof of review. Record reviewer identity, the release version,
and any scope decision in the release ticket or change review. If a source disappears or
becomes ambiguous, set the dependent lifecycle to null or remove the claim until a valid
replacement is reviewed.

## 4. Version the reference

Set the same version string in both YAML files. Use semantic versions as the release
policy:

- patch: wording or citation maintenance that does not change assessment meaning;
- minor: a backward-compatible template, rule, source, or lifecycle change; and
- major: an incompatible schema or meaning change that requires migration or a new app
  compatibility boundary.

The current compiled schema is `2`; the reference data version is `2.0.0`. The compiler
checks that both version strings are present and equal; it does not
validate semantic-version syntax or decide the increment. Reviewers own those checks.
Reference data ships only through the normal application release process.

## 5. Compile and record the summary

From the repository root, run:

```sh
.venv/bin/python scripts/build_component_db.py \
  --source reference \
  --out build/components.sqlite \
  --print-summary
```

The compiler validates the YAML, writes a temporary sibling database, checks SQLite
integrity, fsyncs it, and atomically replaces the destination. The summary reports:

- database and schema versions;
- deterministic category and category-component counts;
- null and sourced non-null lifecycle counts;
- source coverage for release claims; and
- a SHA-256 of the canonical logical database content.

“Release claims” in source coverage means category context, each component with a
non-null lifecycle or safety-sensitive flag, and each safety rule. A claim is covered
when its required source IDs and, where the schema provides them, evidence grade and
review date are present. This metric does not mean that every registered source is used,
nor does it judge whether a citation actually supports the prose; human review does.

The reported SHA-256 is the canonical reference-content checksum stored in database
metadata. Compilation calculates it from stable ordered relational content, and every
`ReferenceStore` startup reconstructs and compares the same logical representation.
It is intentionally distinct from the SQLite byte hash, whose physical layout is not
the data contract. Release staging records both hashes and reopens the copied database
against its logical hash, byte hash, schema, and version. Save the complete summary in
the release record. Build twice from the same commit and confirm that the summaries and
reported checksums match.

## 6. Run the release gate

Use the in-memory `readline` stub on environments where direct pytest startup is unstable:

```sh
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["tests/test_reference_db.py", "tests/test_lifecycle.py", "tests/test_assessment_api.py", "tests/test_assessment_ui.py", "tests/test_reference_release.py", "-v"]))'
```

Do not publish unless the gate confirms:

- exactly five released categories and the approved presence labels;
- every lifecycle and safety claim has the required provenance;
- only the mobile-phone battery has a sourced generic lifecycle;
- unsupported lifecycle values remain null and render as **Unknown**;
- a cycles-to-capacity endurance endpoint never becomes percent lifecycle used or a
  recycle decision without a separately supported measurement;
- safety rules precede reuse decisions in assessment behavior;
- engine-policy and authored-rule revisions survive serialized results and snapshots;
- template versions and the canonical checksum are deterministic; and
- existing assessment snapshots remain immutable when reference data changes.

Also run `git diff --check`, inspect the CLI summary, and review the staged YAML and
procedure changes rather than relying on test counts alone.

## 7. Keep user overrides separate

The application copies a category template into an item-specific history snapshot.
Edits to presence, condition, operating state, or lifecycle apply only to that snapshot.
User-entered lifecycle values are stored as unverified item evidence and cannot acquire
release provenance by supplying source-like fields.

User overrides never automatically feed back into `reference/*.yaml`, the compiled
standard database, a future template, or another user's assessment. A recurring user
observation may become a proposal for an administrator, but it must complete this full
source review, versioning, compilation, and release process before becoming standard.

## Release checklist

- [ ] Source scope and URL checked by a second reviewer.
- [ ] Source and claim review dates reflect the actual review.
- [ ] Evidence grades are accurate and use the project convention.
- [ ] Unsupported lifecycle values are null; no generic values were copied across scopes.
- [ ] Safety copy is sourced, conditional where needed, and reviewed before reuse copy.
- [ ] Every authored safety rule has the approved explicit revision.
- [ ] Both YAML files use the approved matching version increment.
- [ ] Compiler and whole-reference tests pass.
- [ ] Two build summaries and canonical SHA-256 values match.
- [ ] Summary, commit, reviewer, and checksum are recorded in the release record.
- [ ] User overrides remain confined to item-specific history snapshots.

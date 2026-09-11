# Focused Windows Desktop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a focused scan-first desktop UI and an unsigned Windows 11 x64 ZIP that can be published from GitHub Actions.

**Architecture:** Keep the shared Flask, HTML/CSS/JavaScript, ONNX Runtime, and pywebview application. Simplify only the product surface and history API, add platform-aware paths/release metadata, then package the same runtime with a Windows PyInstaller spec.

**Tech Stack:** Python 3.11, Flask, SQLite, ONNX Runtime, pywebview, vanilla HTML/CSS/JavaScript, PyInstaller, PowerShell, GitHub Actions

**Spec:** `docs/superpowers/specs/2026-09-11-focused-cross-platform-desktop-design.md`

## Global Constraints

- Windows target is unsigned Windows 11 x64 in a one-directory ZIP named `E-Waste-Triage-<version>-windows-x64.zip`.
- Existing Apple Silicon macOS support remains usable.
- The service stays on loopback except during explicit phone capture.
- No analytics, account, cloud upload, revision history, undo journal, or new security framework.
- Recent scans returns at most 20 newest records and supports direct delete and clear-all.
- Keep model/reference integrity checks, but make release target metadata explicitly platform-aware.
- Do not claim a public download exists until a GitHub remote is configured and the Windows workflow succeeds.

---

### Task 1: Focus the UI and simplify Recent scans

**Files:**
- Modify: `server/static/index.html`
- Modify: `server/static/app.css`
- Modify: `server/static/app.js`
- Modify: `server/history.py`
- Modify: `server/app.py`
- Modify: `server/desktop_app.py`
- Modify: `tests/test_desktop_ui.py`
- Modify: `tests/test_desktop_api.py`
- Modify: `tests/test_history.py`

**Interfaces:**
- Consumes: existing `/api/v1/classify`, assessment, phone-capture, history item, delete, and clear endpoints.
- Produces: `HistoryStore.list_scans(limit: int | None = None) -> list[dict]`; `GET /api/v1/history` returns at most 20 rows; direct `deleteHistory(scan_id)` and `clearHistory()` controller operations.

- [x] **Step 1: Write focused failing tests**

Parse the real document and assert the user-observable structure:

```python
assert parser.landmark_count("main") == 1
assert parser.has_button("Recent scans")
assert parser.has_disclosure("Why this result?")
assert not parser.has_landmark("aside", aria_label="Application sidebar")
```

Exercise the real controller with a pending fake clock and assert that `deleteHistory("old")` sends `DELETE /api/v1/history/old` before any clock callback runs. This catches reintroduction of delayed undo without asserting private source text.

Create 25 stored records and assert:

```python
listed = client.get("/api/v1/history")
assert listed.status_code == 200
assert len(listed.json) == 20
assert listed.json[0]["scan_id"] == newest_scan_id
```

Test `HistoryStore.list_scans(limit=2)` returns exactly the two newest rows and rejects boolean, zero, or negative limits with `ValueError`.

- [x] **Step 2: Run the focused tests and confirm RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_desktop_ui.py tests/test_desktop_api.py tests/test_history.py -q
```

Expected: failures for the old sidebar/undo UI and unlimited history listing.

- [x] **Step 3: Implement bounded history reads and direct deletion**

Change `HistoryStore.list_scans` to append a parameterized SQL limit only when supplied:

```python
def list_scans(self, limit: int | None = None) -> list[dict]:
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1):
        raise ValueError("history limit must be a positive integer")
    query = "SELECT * FROM scans ORDER BY created_at DESC, rowid DESC"
    parameters = () if limit is None else (limit,)
    if limit is not None:
        query += " LIMIT ?"
    with closing(self._connect()) as connection:
        rows = connection.execute(query, parameters).fetchall()
    return [self._record(row) for row in rows]
```

Have `GET /api/v1/history` call `store.list_scans(limit=20)`. Keep single-delete and clear-all endpoints; remove the controller's delayed `stageHistoryAction`/undo state so delete and clear issue their requests immediately. Keep a short clear confirmation: `Delete all recent scans?`.

- [x] **Step 4: Reshape the existing UI into one focused journey**

Remove the fixed sidebar. Put the compact brand, `Use phone`, `Recent scans`, and `About` actions in the top bar. Preserve existing element IDs required by the controller, but present Scan → Review identity → Assessment/result as successive states in the same centered workspace. Present history as a secondary sheet/panel.

Change result language and hierarchy to show identity first, then condition/action/value, with provenance inside a collapsed native disclosure:

```html
<details class="result-evidence">
  <summary>Why this result?</summary>
  <div id="result-evidence-details"></div>
</details>
```

Use responsive CSS for a minimum 760×620 window and narrow layouts. Preserve keyboard-accessible buttons, visible focus, labels, state announcements, and reduced-motion rules.

- [x] **Step 5: Run focused and nearby tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_desktop_ui.py tests/test_desktop_api.py tests/test_history.py tests/test_assessment_ui.py tests/test_assessment_api.py tests/test_phone_app.py -q
```

Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add server/static/index.html server/static/app.css server/static/app.js server/history.py server/app.py server/desktop_app.py tests/test_desktop_ui.py tests/test_desktop_api.py tests/test_history.py
git commit -m "feat: focus desktop scan experience"
```

---

### Task 2: Make runtime paths and release metadata cross-platform

**Files:**
- Modify: `desktop/paths.py`
- Modify: `desktop/release_metadata.py`
- Modify: `scripts/prepare_release.py`
- Modify: `packaging/release-manifest.schema.json`
- Modify: `tests/test_desktop_runtime.py`
- Modify: `tests/test_release_metadata.py`
- Modify: `tests/test_release_pipeline.py`
- Modify: `tests/test_packaging.py`

**Interfaces:**
- Consumes: `AppPaths.for_runtime(frozen: bool, executable: Path | None = None)` and release manifest schema version 1.
- Produces: `platform_data_dir(system: str | None = None, environ: Mapping[str, str] | None = None) -> Path`; target metadata supports macOS arm64 and Windows x86_64 explicitly.

- [x] **Step 1: Write platform tests**

Test exact Windows and macOS data roots without changing the host OS:

```python
assert platform_data_dir("Windows", {"LOCALAPPDATA": r"C:\Users\tester\AppData\Local"}) == Path(
    r"C:\Users\tester\AppData\Local"
) / "E-Waste Triage"
assert platform_data_dir("Darwin", {}) == Path.home() / "Library/Application Support/E-Waste Triage"
```

Add release-metadata fixtures for both targets:

```python
{"platform": "macos", "architecture": "arm64", "minimum_version": "14.0"}
{"platform": "windows", "architecture": "x86_64", "minimum_version": "11"}
```

Reject mixed and unknown target values.

- [x] **Step 2: Run tests and confirm RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_desktop_runtime.py tests/test_release_metadata.py tests/test_release_pipeline.py -q
```

Expected: missing `platform_data_dir` and target-schema failures.

- [x] **Step 3: Implement platform data paths**

Use `platform.system()` by default. On Windows require a nonempty absolute `LOCALAPPDATA`, falling back to `Path.home() / "AppData/Local"`; on Darwin keep Application Support; on other systems use `XDG_DATA_HOME` or `Path.home() / ".local/share"`. Append `APP_NAME` once. Keep explicit test-mode support unchanged.

- [x] **Step 4: Make target validation explicit**

Replace the mac-only target shape with the three closed fields above. Accept only the two supported tuples. Update `scripts/prepare_release.py`, the JSON Schema, and release pipeline expectations to emit the macOS tuple by default while keeping model/component hash checks unchanged.

- [x] **Step 5: Run tests and commit**

Run:

```bash
.venv/bin/python -m pytest tests/test_desktop_runtime.py tests/test_release_metadata.py tests/test_release_pipeline.py tests/test_packaging.py tests/test_desktop_integration_fixes.py -q
```

Expected: PASS.

```bash
git add desktop/paths.py desktop/release_metadata.py scripts/prepare_release.py packaging/release-manifest.schema.json tests/test_desktop_runtime.py tests/test_release_metadata.py tests/test_release_pipeline.py tests/test_packaging.py
git commit -m "feat: support Windows desktop runtime metadata"
```

---

### Task 3: Build and smoke-test the Windows package

**Files:**
- Create: `packaging/EWasteTriage-Windows.spec`
- Create: `scripts/build_windows_app.ps1`
- Create: `scripts/verify_windows_bundle.py`
- Create: `desktop/assets/app-icon.ico`
- Create: `packaging/runtime/0.1.0/model/model.onnx`
- Create: `packaging/runtime/0.1.0/model/manifest.json`
- Create: `packaging/runtime/0.1.0/components.sqlite`
- Create: `packaging/runtime/0.1.0/labels.json`
- Create: `packaging/runtime/0.1.0/parity-report.json`
- Create: `packaging/runtime/0.1.0/release-manifest.json`
- Modify: `tests/test_packaging.py`
- Create: `tests/test_windows_packaging.py`
- Modify: `tests/test_packaged_smoke.py`
- Modify: `desktop/main.py`
- Modify: `tests/test_desktop_runtime.py`

**Interfaces:**
- Consumes: approved prototype runtime payload currently staged at `.release-staging/release-0.1.0`; shared `desktop/main.py` entry point.
- Produces: `dist/E-Waste-Triage-<version>-windows-x64.zip`; `verify_windows_bundle(release_dir: Path, app_dir: Path, expected_version: str) -> None`; cross-platform packaged-smoke executable resolution.

- [x] **Step 1: Write Windows packaging tests**

Execute the Windows spec through a small fake PyInstaller build namespace and assert the resulting build graph:

```python
assert graph.analysis_entrypoint.name == "main.py"
assert "webview.platforms.edgechromium" in graph.hidden_imports
assert graph.exe.console is False
assert graph.collect.name == "E-Waste Triage"
```

Test that the verifier rejects missing EXE/resources, mismatched hashes, and wrong manifest target. Update `_app_executable()` in packaged smoke so `EWASTE_PACKAGED_APP` accepts either a macOS `.app` or a Windows directory containing `E-Waste Triage.exe`.

- [x] **Step 2: Run packaging tests and confirm RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_packaging.py tests/test_packaged_smoke.py -q
```

Expected: Windows package files and executable resolution are missing.

- [x] **Step 3: Add the versioned prototype runtime payload**

Copy the six existing 0.1.0 runtime artifacts into `packaging/runtime/0.1.0`, preserving bytes for the model, model manifest, component database, labels, and parity report. Generate the Windows release manifest by preserving model/components/parity and setting:

```json
"target": {"platform": "windows", "architecture": "x86_64", "minimum_version": "11"}
```

Recompute the release-manifest hash used by generated build metadata. Verify every recorded model/component/labels/parity hash before packaging.

- [x] **Step 4: Add the Windows PyInstaller spec and build script**

The spec mirrors the shared data/exclusion list from `EWasteTriage.spec`, uses `webview.platforms.edgechromium`, creates a windowed one-directory EXE, and omits macOS `BUNDLE`, entitlements, architecture flags, and plist fields.

`build_windows_app.ps1 -Version 0.1.0` must:

1. require Windows and Python 3.11;
2. validate the version and clean Git state;
3. verify the tracked runtime payload;
4. write build metadata with version, source revision, and manifest hash;
5. run PyInstaller into a versioned build directory;
6. run the Windows verifier;
7. create the named ZIP with `Compress-Archive`;
8. print the final absolute ZIP path.

- [x] **Step 5: Make packaged smoke cross-platform**

Use `subprocess.CREATE_NEW_PROCESS_GROUP` only when available and terminate on Windows with `CTRL_BREAK_EVENT`, falling back to `process.terminate()`. Keep the same readiness file, loopback API, image classification, assessment, recent-history, phone session, and shutdown assertions.

- [x] **Step 6: Run portable tests and commit**

Run on the current host:

```bash
.venv/bin/python -m pytest tests/test_packaging.py tests/test_windows_packaging.py tests/test_packaged_smoke.py tests/test_desktop_runtime.py tests/test_release_metadata.py -q
.venv/bin/python -m py_compile scripts/verify_windows_bundle.py
```

Expected: PASS, with packaged smoke skipped until a real package path is supplied.

```bash
git add packaging/EWasteTriage-Windows.spec packaging/runtime scripts/build_windows_app.ps1 scripts/verify_windows_bundle.py desktop/assets/app-icon.ico desktop/main.py tests/test_windows_packaging.py tests/test_packaged_smoke.py tests/test_desktop_runtime.py
git commit -m "feat: add Windows x64 desktop package"
```

---

### Task 4: Publish the Windows ZIP with GitHub Actions

**Files:**
- Create: `.github/workflows/windows-release.yml`
- Create: `docs/RELEASING_WINDOWS.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: `scripts/build_windows_app.ps1 -Version <X.Y.Z>` and the resulting ZIP.
- Produces: workflow artifact on manual runs and GitHub Release attachment for tags matching `v*`.

- [x] **Step 1: Add the workflow and release guide**

The workflow triggers on `workflow_dispatch` and tags matching `v*`. It derives `X.Y.Z` from the tag or a required manual input, runs focused tests, builds the package, sets `EWASTE_PACKAGED_APP` to the unpacked one-directory output for smoke testing, uploads the ZIP artifact, and uses `softprops/action-gh-release` only on tag builds.

Document the unsigned warning, supported Windows version, ZIP extraction/start steps, SHA-256 verification command, and exact tag command. Update README to make Windows 11 x64 the first downloadable target while keeping macOS development support documented.

- [x] **Step 2: Validate configuration on its real consumer**

Push the branch to GitHub and run `workflow_dispatch`. A successful Windows runner must install dependencies, pass the focused tests, build the real EXE, run packaged smoke, and upload the ZIP. This configuration-only task uses the real CI run rather than a source-text test.

- [x] **Step 3: Run focused and full local verification**

Run:

```bash
.venv/bin/python -m pytest tests/test_packaging.py tests/test_desktop_runtime.py tests/test_desktop_ui.py tests/test_desktop_api.py -q
.venv/bin/python -m pytest -q
git diff --check
```

Expected: PASS.

- [x] **Step 4: Commit**

```bash
git add .github/workflows/windows-release.yml docs/RELEASING_WINDOWS.md README.md
git commit -m "ci: publish Windows desktop download"
```

---

### Task 5: Produce the real downloadable artifact

**Files:**
- No source changes unless the Windows runner exposes a reproducible defect.

**Interfaces:**
- Consumes: a configured GitHub remote and successful Windows workflow.
- Produces: a GitHub Release URL and SHA-256 for `E-Waste-Triage-0.1.0-windows-x64.zip`.

- [x] **Step 1: Configure the repository destination**

Confirm the exact GitHub repository and visibility before creating or connecting a remote. Do not overwrite an existing remote.

- [x] **Step 2: Push the implementation branch and run Windows CI**

Push the committed branch, run the manual workflow first, and inspect the packaged smoke result. Fix only reproducible Windows defects through a failing test.

- [x] **Step 3: Publish version 0.1.0**

Create and push tag `v0.1.0` only after the Windows build and packaged smoke pass. Confirm the release contains the exact named ZIP and record its SHA-256.

- [x] **Step 4: Report the download**

Provide the GitHub Release download link, checksum, unsigned-build warning, and Windows 11 x64 requirement. If repository configuration is unavailable, report Tasks 1–4 complete and name that single external blocker without claiming the download exists.

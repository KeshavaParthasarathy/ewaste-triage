# Windows GUI Runtime Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the downloadable Windows ZIP load its real pywebview/pythonnet GUI runtime after normal Internet-zone extraction.

**Architecture:** Ship an executable-adjacent .NET Framework configuration enabling trusted loading of the app's bundled managed assemblies. Add a hidden executable runtime probe and run it from the packaged smoke test after CI applies a Mark-of-the-Web stream, while the bundle verifier enforces the configuration structurally.

**Tech Stack:** Python 3.11, PyInstaller, pywebview/pythonnet, PowerShell, pytest, GitHub Actions

**Spec:** `docs/superpowers/specs/2026-09-12-windows-gui-runtime.md`

## Global Constraints

- Target remains Windows 11 x64.
- The packaged application remains a portable one-directory ZIP.
- Mac packaging and product UI do not change.
- The published Windows asset remains version 0.1.0.

---

### Task 1: Exercise and protect the downloaded GUI runtime

**Files:**
- Create: `desktop/windows/E-Waste Triage.exe.config`
- Modify: `desktop/main.py`
- Modify: `scripts/build_windows_app.ps1`
- Modify: `scripts/verify_windows_bundle.py`
- Modify: `.github/workflows/windows-release.yml`
- Test: `tests/test_desktop_runtime.py`
- Test: `tests/test_windows_packaging.py`
- Test: `tests/test_packaged_smoke.py`

**Interfaces:**
- Consumes: the current PyInstaller one-directory layout and `EWASTE_PACKAGED_APP` smoke-test path.
- Produces: `desktop.main.main(argv: Sequence[str] | None = None) -> int`, the `--gui-runtime-check` command, and an executable-adjacent CLR configuration required by `verify_windows_bundle`.

- [x] **Step 1: Write failing tests**

Add tests proving that `main(["--gui-runtime-check"])` selects the CLR probe, that the Windows verifier rejects a missing or weakened executable configuration, and that the packaged Windows smoke test invokes the probe before server-only test mode.

- [x] **Step 2: Verify the tests fail for the missing behavior**

Run the focused desktop runtime, packaged smoke, and Windows packaging tests. Confirm failures name the missing CLI probe and missing executable configuration.

- [x] **Step 3: Add the runtime probe and required CLR configuration**

Implement the CLI probe as a real `clr` import on Windows, create a .NET Framework configuration containing `<loadFromRemoteSources enabled="true"/>`, copy it beside the executable during the Windows build, and parse/enforce it in the bundle verifier.

- [x] **Step 4: Re-run focused tests**

Run the same focused tests and require a zero exit status.

- [x] **Step 5: Reproduce and close the user failure in Windows CI**

Apply a ZoneId 3 alternate stream to the packaged Windows files, then run the packaged smoke test. Require the real `--gui-runtime-check` subprocess and the existing server/API smoke paths to pass.

- [ ] **Step 6: Review, commit, publish, and verify**

Review the diff, push to `main`, rebuild the 0.1.0 Windows ZIP, replace the release asset, verify its digest and contents, and report the refreshed download link.

## Self-review

- Spec coverage: every requirement maps to Task 1.
- Placeholder scan: no deferred implementation placeholders.
- Type consistency: the CLI entry point and verifier contract are named consistently.

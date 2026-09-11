# Focused Cross-Platform Desktop Product

**Date:** 2026-09-11  
**Status:** Approved  
**Targets:** Windows 11 x64 first; existing Apple Silicon macOS support retained

## Goal

Turn the current local prototype into a focused desktop product whose primary journey is:

1. choose or drop a device photo;
2. analyze it locally;
3. confirm or correct the device identity;
4. see condition, recommended action, estimated value, and concise reasoning.

The interface and Windows download are the priority. New security architecture, immutable history revisions, tombstones, undo journals, and extensive wire-contract machinery are out of scope.

## Product surface

The desktop app uses one focused workspace rather than a dashboard. The empty state presents the photo action prominently. Analysis replaces it with clear progress. Results use a short visual hierarchy:

- identified device and confidence;
- identity confirmation or correction;
- condition summary;
- recommended reuse, repair, or recycling action;
- estimated value when available;
- collapsed “Why this result?” evidence.

Phone capture remains available as a secondary photo-source action. Technical provenance stays available inside expandable details rather than dominating the result.

Recent scans is a secondary panel containing at most the latest 20 scans. Users can delete one scan or clear all scans. There is no user-visible revision history, undo period, audit trail, migration framework, or multi-stage deletion state.

## Architecture

Retain the existing portable architecture:

- pywebview owns the native window;
- the local Flask service owns application behavior;
- the existing HTML, CSS, and JavaScript bundle owns presentation;
- ONNX Runtime performs local inference;
- PyInstaller creates platform-specific packages.

Mac and Windows share the service and UI. Platform-specific code is limited to paths, pywebview backend selection, icons, PyInstaller configuration, and build scripts.

The existing history store may remain behind a smaller product-facing API. The UI requests only the latest 20 records and exposes direct deletion and clear-all actions. Existing stored data is not rewritten merely to simplify the interface.

## Essential safeguards

Keep only safeguards needed for a reliable local desktop product:

- bind the service to loopback unless the user explicitly starts phone capture;
- accept bounded supported image types and normalize them before inference;
- keep app resources read-only and user data in the platform data directory;
- avoid analytics, remote accounts, and background uploads;
- return safe user-facing errors rather than raw exceptions.

No new security framework or exhaustive contract matrix is part of this scope.

## Failure behavior

Photo or analysis failures appear inline with a Retry action and preserve the selected photo when practical. Independently unavailable result sections show a short unavailable message while usable sections remain visible. Missing packaged model or reference assets show the existing recovery surface.

## Windows package and download

Add a Windows x64 PyInstaller build that produces a one-directory application containing `E-Waste Triage.exe`, zipped as:

`E-Waste-Triage-<version>-windows-x64.zip`

A GitHub Actions workflow runs on Windows, installs pinned runtime dependencies, builds the package, performs a startup/package smoke test, uploads a workflow artifact, and attaches the ZIP to a GitHub Release for version tags. The first Windows release is unsigned; Windows may display its normal unrecognized-publisher warning.

The current checkout has no Git remote. The workflow and package can be completed locally, but publication requires connecting the repository to GitHub and pushing the release tag.

## Verification

Verification is deliberately focused:

- UI tests cover the empty, progress, result, correction, unavailable, retry, and Recent scans flows;
- service tests cover the reduced latest/delete/clear history behavior;
- platform tests cover Windows paths and PyInstaller inputs;
- the Windows workflow runs a packaged startup and inference smoke test;
- the existing relevant Mac tests guard retained compatibility.

Broad historical migration suites, release-corpus expansion, and exhaustive closed-contract tests are not acceptance requirements for this product pass.

## Completion

This pass is complete when the focused desktop flow works in development, Recent scans is simple, the relevant automated tests pass, and a Windows CI build produces the named ZIP. A public download link additionally requires a configured GitHub remote and a published release.

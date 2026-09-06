# E-Waste Triage Mac app tester checklist

Record a pass/fail result and evidence (screenshot, short note, or issue link) for every item. Record the app version, source revision, model SHA-256, component-database SHA-256, and component-database version from Settings/release metadata with the result.

## Install and local scan

- [ ] In Finder, open the `.app` without using Terminal. For this unsigned milestone, if Gatekeeper blocks it, Control-click the app, choose **Open**, then confirm **Open**.
- [ ] Import one local JPEG, PNG, WebP, and HEIC image. Record each result and any format-specific error.
- [ ] Deny camera permission, confirm the app explains the failure, then grant permission/retry and confirm capture works.
- [ ] Correct a predicted category and confirm the saved history record uses the selected category.
- [ ] Edit assessment condition, lifecycle inputs, and known issues. Confirm saved values survive reopening the item and change only that item.
- [ ] Confirm safety and source language is conditional and honest: a photograph identifies a category, not an internal part, condition, or safety clearance.
- [ ] Close and relaunch the app; verify history persists.
- [ ] Disable network/enable airplane mode after launch and confirm local classification still works.

## Phone capture

- [ ] Put Mac and phone on the same Wi-Fi, start pairing, scan the QR code, and upload a JPEG from the phone.
- [ ] Confirm the desktop receives the result once, then reports no pending result after it is consumed.
- [ ] Try a wrong pairing code, a revoked link after Stop, and an expired pairing; each must be rejected.
- [ ] Stop pairing and confirm the phone listener is unavailable.
- [ ] Confirm the disclosure says this is temporary same-network **HTTP**, not TLS, protected by a memory-only capability URL and six-digit code.

## Accessibility and layout

- [ ] Enable reduced motion and confirm status/progress remains understandable without nonessential animation.
- [ ] Complete the primary scan, correction, assessment, history, and pairing flows using only a keyboard; check visible focus and status announcements.
- [ ] Check loading, error, and empty states for understandable text and controls.
- [ ] Check the 760 px minimum window width and normal resizing; content must remain readable and actionable.

## Evidence record

Tester: __________  Date/time: __________  App version: __________  Source revision: __________

Model SHA-256: __________  Component SHA-256/version: __________  Build/DMG checksum: __________

Overall result: Pass / Fail  Evidence location or issue IDs: __________________________________

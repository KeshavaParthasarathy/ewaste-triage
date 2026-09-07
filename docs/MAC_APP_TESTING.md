# E-Waste Triage Mac app tester checklist

Record a pass/fail result and evidence (screenshot, short note, or issue link) for every item. Open **About this release**, record its app version, source revision, model SHA-256, component-database SHA-256, and component-database version, and compare all five values with the release JSON and staged release manifest.

## Version 0.1.0 boundaries

This internal milestone imports files on the Mac and can open the phone's camera or photo chooser through Phone Capture; it does not use the Mac camera directly. It shows bundled source IDs, evidence grades, review dates, and rule revisions, but external source URLs are not clickable yet. Retain-original and disable-history controls, assessment export, Open Logs, Developer ID signing/notarization, automatic updates, TLS phone transport, Intel/Windows/Linux packages, hardware diagnostics, and internal-part detection remain later work.

## Install and local scan

- [ ] On a fresh macOS 14-or-later tester account while already offline, mount the DMG, drag **E-Waste Triage** to Applications, eject the DMG, and launch the installed copy from Finder without using Terminal. For this unsigned milestone, if Gatekeeper blocks it, Control-click the app, choose **Open**, then confirm **Open**.
- [ ] Import one local JPEG, PNG, WebP, and HEIC image. Record each result and any format-specific error.
- [ ] Correct a predicted category and confirm the saved history record uses the selected category.
- [ ] Edit assessment condition, lifecycle inputs, and known issues. Confirm saved values survive reopening the item and change only that item.
- [ ] Enter the same assessment inputs twice and confirm the lifecycle range is deterministic. Confirm missing evidence stays **Unknown**, safety precedes reuse guidance, and visible source IDs/grades/review dates/rule revisions remain conditional and honest: a photograph identifies a category, not an internal part, condition, or safety clearance.
- [ ] Delete one history item, Undo it, delete it again, then use Clear All and Undo. Clear again, relaunch, and confirm the list is empty and the app-managed thumbnail/original files are gone.
- [ ] Close and relaunch while still offline; classify a photo and open Assessment, History, and About without a network dependency.

## Phone capture

- [ ] Before starting Phone Capture, confirm no LAN listener or Local Network permission request exists. Deny Local Network permission once, confirm the app explains the failure, then grant access and retry without breaking local Mac scans.
- [ ] On ordinary IPv4 Wi-Fi, start pairing, scan the QR code, open the phone camera/photo chooser, cancel once, retry, and upload a JPEG and then a HEIC photo.
- [ ] Confirm the desktop receives the result once, then reports no pending result after it is consumed.
- [ ] Try a wrong pairing code, a revoked link after Stop, and an expired pairing; each must be rejected.
- [ ] Repeat pairing on an IPv6-only hotspot. Stop pairing, close the sheet, press Escape, and quit during pairing; each path must close the exact listener.
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

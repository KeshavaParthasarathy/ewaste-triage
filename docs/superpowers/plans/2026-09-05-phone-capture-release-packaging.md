# Phone Capture and macOS Release Packaging Implementation Plan

> **Required sub-skill:** Use `superpowers:executing-plans` to implement this plan task by task.

**Goal:** Add an explicitly activated, time-limited phone capture flow and produce a self-contained, unsigned Apple Silicon macOS application that runs the approved classifier and assessment experience without a terminal.

**Architecture:** The desktop process owns two loopback-first Flask services: the main UI remains private on an ephemeral loopback port, while a second LAN listener exists only during an active phone session. A random capability token and short pairing code protect phone uploads. Release preparation validates and stages immutable model/reference assets before PyInstaller creates the `.app`; bundle verification launches the executable in an isolated temporary home and tests the packaged HTTP API.

**Tech Stack:** Python 3.11, Flask, pywebview, qrcode/Pillow, psutil, pytest, PyInstaller, macOS `hdiutil`.

---

## Task 1: Build a bounded phone-session manager

**Files:**
- Create: `server/phone_sessions.py`
- Modify: `server/netinfo.py`
- Test: `tests/test_phone_sessions.py`
- Test: `tests/test_netinfo.py`

### Step 1: Write the failing tests

Create `tests/test_phone_sessions.py` covering:

```python
def test_session_uses_random_token_short_code_and_expiry(monkeypatch):
    clock = FakeClock(100.0)
    sessions = PhoneSessionManager(now=clock, ttl_seconds=600)
    session = sessions.start(host="192.168.1.12", port=9012)
    assert len(session.token) >= 43
    assert session.pairing_code.isdigit() and len(session.pairing_code) == 6
    assert session.upload_url.endswith(f"/phone?token={session.token}")
    clock.advance(601)
    assert sessions.active() is None


def test_successful_activity_refreshes_inactivity_deadline():
    ...


def test_stop_revokes_token_immediately():
    ...
```

Create `tests/test_netinfo.py` covering deterministic filtering and ordering of IPv4 and global/private IPv6 candidates. Reject loopback, link-local, multicast, and unspecified addresses.

### Step 2: Run the tests and verify failure

Run: `.venv/bin/pytest tests/test_phone_sessions.py tests/test_netinfo.py -q`

Expected: FAIL because `PhoneSessionManager` and the address-discovery interface do not exist.

### Step 3: Implement the manager and address discovery

In `server/phone_sessions.py`, define immutable public state and a lock-protected manager:

```python
@dataclass(frozen=True)
class PhoneSession:
    token: str
    pairing_code: str
    host: str
    port: int
    created_at: float
    expires_at: float

    @property
    def upload_url(self) -> str: ...


class PhoneSessionManager:
    def start(self, host: str, port: int) -> PhoneSession: ...
    def active(self) -> PhoneSession | None: ...
    def authorize(self, token: str, pairing_code: str | None = None) -> bool: ...
    def touch(self, token: str) -> PhoneSession | None: ...
    def stop(self) -> None: ...
```

Use `secrets.token_urlsafe(32)` for the capability token, `secrets.randbelow(1_000_000)` for the zero-padded code, constant-time token comparison, and a 600-second inactivity timeout. Starting a new session revokes the old one.

In `server/netinfo.py`, expose:

```python
def discover_lan_addresses() -> list[str]: ...
def preferred_lan_address() -> str | None: ...
```

Use `psutil.net_if_addrs()`. Prefer private IPv4, then global IPv6. Preserve IPv6 scope identifiers only when required and bracket IPv6 in URLs.

### Step 4: Run tests and commit

Run: `.venv/bin/pytest tests/test_phone_sessions.py tests/test_netinfo.py -q`

Expected: PASS.

```bash
git add server/phone_sessions.py server/netinfo.py tests/test_phone_sessions.py tests/test_netinfo.py
git commit -m "feat: add bounded phone capture sessions"
```

## Task 2: Add the restricted phone upload service

**Files:**
- Create: `server/phone_app.py`
- Create: `server/static/phone.html`
- Create: `server/static/phone.css`
- Create: `server/static/phone.js`
- Test: `tests/test_phone_app.py`

### Step 1: Write the failing route tests

Create `tests/test_phone_app.py` with an in-memory classifier and temporary upload store. Cover:

```python
def test_inactive_service_rejects_phone_page(client):
    assert client.get("/phone?token=anything").status_code == 404


def test_active_token_can_open_page_and_upload_jpeg(client, active_session, jpeg_bytes):
    page = client.get(f"/phone?token={active_session.token}")
    assert page.status_code == 200
    result = client.post(
        "/phone/upload",
        data={"token": active_session.token, "image": (io.BytesIO(jpeg_bytes), "capture.jpg")},
        content_type="multipart/form-data",
    )
    assert result.status_code == 200
    assert result.get_json()["prediction"]["label"] == "mouse"


def test_wrong_token_oversized_body_and_non_image_are_rejected(...): ...
def test_only_phone_routes_exist_on_lan_app(...): ...
def test_expired_session_rejects_upload(...): ...
```

Assert the LAN app has no training, history, filesystem, admin, or arbitrary static-file route.

### Step 2: Run the tests and verify failure

Run: `.venv/bin/pytest tests/test_phone_app.py -q`

Expected: FAIL because the restricted app factory does not exist.

### Step 3: Implement the restricted application

Expose:

```python
def create_phone_app(
    sessions: PhoneSessionManager,
    classify_image: Callable[[Image.Image], dict[str, object]],
    receive_result: Callable[[dict[str, object]], None],
) -> Flask: ...
```

Requirements:

- Set `MAX_CONTENT_LENGTH = 16 * 1024 * 1024`.
- Register only `GET /phone`, `POST /phone/upload`, `GET /phone/status`, and the required static assets.
- Require a live capability token on every route; optionally confirm the six-digit code if the desktop toggles code entry on.
- Decode through the shared image-normalization helper, reject malformed images, and never retain the upload after classification.
- Call `sessions.touch(token)` only after a valid request.
- Deliver the inference result to the desktop service through the injected callback.
- Apply `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, a restrictive Content Security Policy, and no permissive CORS headers.

Build `phone.html`, `phone.css`, and `phone.js` as a focused mobile surface: live camera capture/file selection, preview, animated analyzing state, result card, retry button, explicit session-expired view, and `prefers-reduced-motion` fallbacks. Keep all scripts local and use plain browser APIs.

### Step 4: Run tests and commit

Run: `.venv/bin/pytest tests/test_phone_app.py -q`

Expected: PASS.

```bash
git add server/phone_app.py server/static/phone.html server/static/phone.css server/static/phone.js tests/test_phone_app.py
git commit -m "feat: add secure phone capture service"
```

## Task 3: Connect phone capture to the desktop UI

**Files:**
- Modify: `desktop/server_thread.py`
- Modify: `desktop/main.py`
- Modify: `server/desktop_app.py`
- Modify: `server/static/app.html`
- Modify: `server/static/app.js`
- Modify: `server/static/app.css`
- Test: `tests/test_desktop_phone_api.py`
- Test: `tests/test_desktop_ui.py`

### Step 1: Write the failing integration tests

Add API tests:

```python
def test_start_phone_session_binds_lan_listener_and_returns_qr_data(...):
    response = client.post("/api/phone-session")
    body = response.get_json()
    assert response.status_code == 201
    assert body["active"] is True
    assert body["upload_url"].startswith(("http://192.168.", "http://10.", "http://["))
    assert body["qr_png"].startswith("data:image/png;base64,")


def test_stop_phone_session_closes_listener_and_revokes_url(...): ...
def test_phone_result_enters_desktop_inbox_once(...): ...
def test_no_lan_listener_exists_before_explicit_start(...): ...
```

Add DOM-contract tests asserting the Scan page includes `Use phone`, an initially hidden pairing sheet, QR image, pairing code, countdown, stop control, and incoming-result region.

### Step 2: Run the tests and verify failure

Run: `.venv/bin/pytest tests/test_desktop_phone_api.py tests/test_desktop_ui.py -q`

Expected: FAIL because the API and pairing surface do not exist.

### Step 3: Implement listener lifecycle and desktop endpoints

Extend the server-thread abstraction with:

```python
class PhoneServerController:
    def start(self, host: str, port: int = 0) -> BoundPhoneServer: ...
    def stop(self) -> None: ...
    @property
    def is_running(self) -> bool: ...
```

The controller must bind only after explicit user action, publish the actual bound port, close promptly on stop/expiry/app shutdown, and never start a training endpoint.

Add desktop API endpoints:

- `POST /api/phone-session` starts the listener and returns session metadata plus an in-memory QR PNG data URL.
- `GET /api/phone-session` returns live/expired state and any single-use incoming inference result.
- `DELETE /api/phone-session` stops and revokes the session.

Use `qrcode` to encode only the tokenized LAN URL. Do not write the QR image to disk.

### Step 4: Implement the polished pairing flow

Wire `Use phone` to a spring-like sheet transition. Animate the QR and code in with a 40ms stagger, show a smooth countdown/progress ring, and surface an incoming result using the same staged result animation as local scans. Button presses use the established scale/opacity tokens. Closing the sheet sends `DELETE /api/phone-session`; app shutdown stops the LAN server. Reduced-motion mode removes transforms and stagger delays.

### Step 5: Run tests and commit

Run: `.venv/bin/pytest tests/test_desktop_phone_api.py tests/test_desktop_ui.py -q`

Expected: PASS.

```bash
git add desktop/server_thread.py desktop/main.py server/desktop_app.py server/static/app.html server/static/app.js server/static/app.css tests/test_desktop_phone_api.py tests/test_desktop_ui.py
git commit -m "feat: connect phone capture to desktop app"
```

## Task 4: Create an atomic release-preparation gate

**Files:**
- Create: `scripts/prepare_release.py`
- Create: `packaging/release-manifest.schema.json`
- Modify: `.gitignore`
- Test: `tests/test_release_pipeline.py`

### Step 1: Write the failing release tests

Cover:

```python
def test_prepare_release_requires_passing_parity_report(tmp_path): ...
def test_prepare_release_rejects_checksum_mismatch(tmp_path): ...
def test_prepare_release_rejects_unknown_schema_version(tmp_path): ...
def test_prepare_release_stages_model_labels_components_and_manifest_atomically(tmp_path): ...
def test_failed_staging_preserves_previous_release(tmp_path, monkeypatch): ...
```

The success assertion checks a closed manifest containing app version, model version, model checksum, labels checksum, component database checksum, schema versions, target architecture, minimum macOS version, creation timestamp, and parity metrics.

### Step 2: Run the tests and verify failure

Run: `.venv/bin/pytest tests/test_release_pipeline.py -q`

Expected: FAIL because release preparation is absent.

### Step 3: Implement atomic staging

Expose:

```python
def prepare_release(
    model_bundle: Path,
    component_db: Path,
    parity_report: Path,
    output_dir: Path,
    app_version: str,
) -> Path: ...
```

Validate all checksums and schemas, require parity status `passed`, enforce the five approved labels in canonical order, and reject a model trained on an overlapping/invalid holdout report. Copy to a sibling temporary directory, fsync manifest/assets where supported, then swap into place while preserving the prior release on any failure. Never mutate `models/production` during packaging.

Add `.release-staging/`, `build/`, `dist/`, and generated DMGs to `.gitignore` without changing unrelated ignore rules.

### Step 4: Run tests and commit

Run: `.venv/bin/pytest tests/test_release_pipeline.py -q`

Expected: PASS.

```bash
git add scripts/prepare_release.py packaging/release-manifest.schema.json tests/test_release_pipeline.py .gitignore
git commit -m "build: add atomic release preparation"
```

## Task 5: Package and verify the unsigned macOS application

**Files:**
- Create: `packaging/EWasteTriage.spec`
- Create: `packaging/entitlements.plist`
- Create: `desktop/assets/app-icon.svg`
- Create: `scripts/render_app_icon.py`
- Create: `scripts/build_macos_app.sh`
- Create: `scripts/verify_macos_bundle.py`
- Modify: `requirements.txt`
- Test: `tests/test_packaging.py`

### Step 1: Write failing packaging-contract tests

Create `tests/test_packaging.py` to load the PyInstaller spec and scripts as data. Assert:

- Product name and bundle identifier are stable.
- Target is `arm64` and minimum system version is macOS 14.
- The release model directory, compiled component database, and desktop static assets are bundled.
- Training datasets, admin scripts, reports, raw photos, tests, and `models/best.pt` are excluded.
- `LSApplicationCategoryType` and camera/local-network usage descriptions are present.
- Build script refuses a missing/invalid release manifest.

### Step 2: Run tests and verify failure

Run: `.venv/bin/pytest tests/test_packaging.py -q`

Expected: FAIL because the packaging files are absent.

### Step 3: Add runtime and build dependencies

Pin verified versions in `requirements.txt`:

```text
pillow-heif==1.6.0
psutil==7.0.0
pywebview==6.2.1
qrcode==8.2
pyinstaller==6.22.2
onnxruntime==1.23.2
```

If the existing environment requires a compatible patch version, record the resolved version in the lock/requirements file and rerun the full suite before proceeding.

### Step 4: Implement icon, spec, build, and verifier

Create a clean vector icon based on the approved product language: deep graphite rounded square, emerald circular scan loop, and a simple white component glyph. `scripts/render_app_icon.py` must render the SVG into the required `.iconset` sizes and invoke `iconutil` to produce `.icns`.

`packaging/EWasteTriage.spec` must:

- launch `desktop/main.py` with no console;
- include only staged release assets, desktop static files, and required Python packages;
- set `CFBundleIdentifier` to `com.ewastetriage.desktop`;
- set the minimum macOS version to `14.0` and target architecture to `arm64`;
- include camera and local-network purpose strings;
- keep all data/state outside the bundle at `~/Library/Application Support/EWaste Triage`.

`scripts/build_macos_app.sh` must use `set -euo pipefail`, validate the staged release first, render the icon, run PyInstaller with a clean dedicated work path, verify the bundle, create `dist/EWaste Triage-<version>-arm64.dmg` with `hdiutil`, calculate SHA-256, and write a small release JSON beside the DMG. It must not sign or notarize in this milestone.

`scripts/verify_macos_bundle.py` must inspect `Info.plist`, bundled paths, architecture via `lipo -info`, absence of forbidden admin/data files, and manifest/checksum consistency. It must return nonzero on any mismatch.

### Step 5: Run tests and commit

Run: `.venv/bin/pytest tests/test_packaging.py -q`

Expected: PASS.

```bash
git add packaging/EWasteTriage.spec packaging/entitlements.plist desktop/assets/app-icon.svg scripts/render_app_icon.py scripts/build_macos_app.sh scripts/verify_macos_bundle.py requirements.txt tests/test_packaging.py
git commit -m "build: package ewaste triage mac app"
```

## Task 6: Exercise the packaged product and document release operations

**Files:**
- Create: `tests/test_packaged_smoke.py`
- Create: `docs/MAC_APP_TESTING.md`
- Create: `docs/RELEASING_MAC_APP.md`
- Modify: `README.md`

### Step 1: Add the packaged smoke harness

Create `tests/test_packaged_smoke.py`, skipped unless `EWASTE_PACKAGED_APP` points to a built `.app`. The test must launch the inner executable with a temporary application-support root and test mode enabled, wait for a readiness file containing the loopback URL, then verify:

1. health endpoint and five canonical labels;
2. local upload classification and history persistence;
3. assessment snapshot persistence;
4. phone listener absent before activation;
5. phone session activation and one authorized upload;
6. phone listener closure after stop;
7. process shutdown without leaked listeners.

Use bundled sample fixtures copied to a temporary directory; do not access the training or holdout datasets.

### Step 2: Document manual acceptance tests

`docs/MAC_APP_TESTING.md` must contain a checkbox runbook for:

- first launch from Finder without Terminal;
- local photo and HEIC upload;
- camera permission denial/retry;
- manual label correction;
- component condition edits and deterministic lifecycle ranges;
- safety warnings and source links;
- close/reopen offline history;
- QR upload on the same Wi-Fi network;
- expired/revoked QR behavior;
- reduced-motion and keyboard navigation;
- airplane-mode classification;
- Gatekeeper instructions for an unsigned internal build.

`docs/RELEASING_MAC_APP.md` must distinguish admin training from product release, list exact commands for ONNX export/parity, component compilation, release preparation, `.app`/DMG build, packaged smoke test, checksum publication, rollback to a prior staged bundle, and future signing/notarization.

Update the README with a short product section and links to these guides while preserving the existing training documentation.

### Step 3: Run the complete verification matrix

Run:

```bash
.venv/bin/pytest -q
.venv/bin/python scripts/prepare_release.py --help
.venv/bin/python scripts/verify_macos_bundle.py --help
./scripts/build_macos_app.sh --version 0.1.0
EWASTE_PACKAGED_APP="dist/EWaste Triage.app" .venv/bin/pytest tests/test_packaged_smoke.py -q
```

Expected: all tests pass, the app launches without a terminal, and the DMG plus SHA-256 release metadata exist.

### Step 4: Perform manual visual and functional verification

Open the built app from Finder. Verify Scan, Results, Components, History, Settings, phone pairing, loading/error/empty states, animation timing, reduced-motion behavior, window resizing, and relaunch persistence. Record any deviation before declaring release-ready.

### Step 5: Commit the runbooks and smoke harness

```bash
git add tests/test_packaged_smoke.py docs/MAC_APP_TESTING.md docs/RELEASING_MAC_APP.md README.md
git commit -m "docs: add mac app release runbooks"
```

## Final verification gate

Before calling the product complete:

1. Run every command in Task 6 from a clean process state.
2. Confirm no development Flask or phone listener remains open.
3. Confirm the packaged bundle contains no raw/holdout photos, training scripts, tests, or admin model checkpoints.
4. Confirm classification works with network disabled.
5. Confirm model and reference checksums shown in Settings match the release manifest.
6. Confirm the final `.app`, DMG, checksum JSON, and documentation paths are reported to the user.
